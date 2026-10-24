"""Descriptive factor-sign and weight audit; never auto-tunes the heuristic factor engine."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from .version import VERSION

from .factor_engine import FACTOR_META, effective_factor_meta


def _rho(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(pair) < 8 or pair.iloc[:, 0].nunique() < 3 or pair.iloc[:, 1].nunique() < 3:
        return None
    value = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def _fmt_corr(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _factor_move(series: pd.Series, kind: str) -> pd.Series:
    """Mirror the factor engine's rough movement window for a comparable sign audit."""
    series = pd.to_numeric(series, errors="coerce")
    if kind in {"price", "risk"}:
        return series.pct_change(5, fill_method=None) * 100.0
    return series.diff(20)


def run_factor_audit(prices: pd.DataFrame, min_observations: int = 30) -> dict[str, Any]:
    """Measure Spearman association of known-at-t factor moves with the next 5-session USDINR return.

    Macro/flow features are sampled only when their as-of value changes to avoid inflating the
    sample size with repeated forward-filled observations. This is a descriptive, univariate
    association check; it is not causal identification, a weight optimizer, or a trading test.
    """
    if prices is None or prices.empty or "USDINR" not in prices.columns:
        raise ValueError("No usable USDINR dataset is loaded. Fetch/refresh data before auditing factors.")
    data = prices.copy().sort_index()
    data.index = pd.DatetimeIndex(pd.to_datetime(data.index, errors="coerce")).normalize()
    data = data.loc[~data.index.isna()]
    fx = pd.to_numeric(data["USDINR"], errors="coerce")
    forward_return = fx.shift(-5).div(fx).sub(1.0).mul(100.0).rename("forward_usdinr_return_5d_pct")
    active_meta, config_info = effective_factor_meta()
    active_weights = [max(0.0, float(m.get("weight", 0.0))) for m in active_meta.values() if int(m.get("sign", 0)) != 0]
    weight_total = float(sum(active_weights))
    rows: list[dict[str, Any]] = []

    for key, base in FACTOR_META.items():
        meta = active_meta.get(key, base)
        source = pd.to_numeric(data[key], errors="coerce") if key in data.columns else pd.Series(np.nan, index=data.index, dtype=float)
        move = _factor_move(source, str(base["kind"]))
        # Carried monthly/weekly observations should not be counted as many independent releases.
        if base["kind"] in {"rate", "context", "flow"}:
            new_observation = source.notna() & source.ne(source.shift())
            move = move.where(new_observation)
        joined = pd.concat([move.rename("factor_move"), forward_return], axis=1).dropna()
        n = int(len(joined))
        rho = _rho(joined["factor_move"], joined["forward_usdinr_return_5d_pct"]) if n >= 8 else None
        default_sign = int(base.get("sign", 0))
        active_sign = int(meta.get("sign", default_sign))
        default_weight = float(base.get("weight", 0.0))
        active_weight = float(meta.get("weight", default_weight))
        total_weighted = weight_total if weight_total else 1.0

        # Temporal stability: three chronological slices, not randomized cross-validation.
        segment_corrs: list[float | None] = [None, None, None]
        if n:
            boundaries = np.linspace(0, n, 4, dtype=int)
            for pos in range(3):
                segment = joined.iloc[boundaries[pos]:boundaries[pos + 1]]
                segment_corrs[pos] = _rho(segment["factor_move"], segment["forward_usdinr_return_5d_pct"]) if len(segment) >= 12 else None
        usable_segments = [c for c in segment_corrs if c is not None and abs(c) >= 0.02]
        if active_sign == 0 or active_weight == 0:
            sign_match = None
            sign_status = "Context-only / excluded"
        elif n < min_observations or rho is None:
            sign_match = None
            sign_status = "Insufficient observations"
        elif abs(rho) < 0.02:
            sign_match = None
            sign_status = "Near-zero rank association"
        else:
            sign_match = bool(np.sign(rho) == active_sign)
            sign_status = "Matches hypothesis" if sign_match else "Conflicts with hypothesis"

        if active_sign == 0 or active_weight == 0:
            review_hint = "Kept as context only; not scored in the composite."
        elif n < min_observations:
            review_hint = "Keep the stated weight provisional; collect more independent observations."
        elif len(usable_segments) >= 2 and len({int(np.sign(c)) for c in usable_segments}) > 1:
            review_hint = "Direction varies across time slices; investigate regime dependence before changing the weight."
        elif sign_match is False:
            review_hint = "Historical association conflicts with the hypothesized sign; review definition, timing and regime effects. Do not auto-flip."
        elif sign_match is True:
            review_hint = "Association aligns in the pooled sample; this alone does not validate causality or the assigned weight."
        else:
            review_hint = "No clear monotonic association detected; a non-zero heuristic weight still needs justification."

        rows.append({
            "factor_key": key,
            "factor": str(base.get("name", key)),
            "group": str(base.get("group", "Other")),
            "kind": str(base.get("kind", "unknown")),
            "observations": n,
            "required_observations": int(min_observations),
            "sample_start": joined.index.min().strftime("%Y-%m-%d") if n else None,
            "sample_end": joined.index.max().strftime("%Y-%m-%d") if n else None,
            "default_sign": default_sign,
            "active_sign": active_sign,
            "hypothesized_direction": "Higher movement tends to weaken INR" if active_sign > 0 else "Higher movement tends to support INR" if active_sign < 0 else "Context only",
            "sign_status": sign_status,
            "pooled_spearman_rho": _fmt_corr(rho),
            "sign_match": sign_match,
            "segment_1_spearman_rho": _fmt_corr(segment_corrs[0]),
            "segment_2_spearman_rho": _fmt_corr(segment_corrs[1]),
            "segment_3_spearman_rho": _fmt_corr(segment_corrs[2]),
            "stability_segments_available": sum(c is not None for c in segment_corrs),
            "stability_direction_consistent": (len(usable_segments) >= 2 and len({int(np.sign(c)) for c in usable_segments}) == 1) if len(usable_segments) >= 2 else None,
            "default_weight": round(default_weight, 4),
            "active_weight": round(active_weight, 4),
            "weight_change": round(active_weight - default_weight, 4),
            "active_weight_share_pct": round(active_weight / total_weighted * 100.0, 2) if active_weight else 0.0,
            "review_hint": review_hint,
            "interpretation": str(base.get("why", "")),
        })

    rows.sort(key=lambda row: (row["group"], row["factor"]))
    return {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of_date": data.index.max().strftime("%Y-%m-%d") if len(data.index) else None,
        "target": "Forward 5-business-session USD/INR percentage return; positive means USD/INR rose and INR weakened.",
        "sample_method": "Daily price/risk factors use 5-session percentage moves; rate/context/flow factors use 20-session differences. Rate/context/flow rows are included only when the as-of value changes. Each factor is tested independently with Spearman rank correlation against the next 5-session USD/INR return.",
        "minimum_observations_for_sign_status": int(min_observations),
        "active_weight_total": round(weight_total, 4),
        "configuration": config_info,
        "limitations": [
            "This is a descriptive, univariate sign diagnostic; it does not establish causation or incremental predictive value.",
            "Daily price observations and forward returns overlap, so pooled observations are not independent.",
            "Data-source publication dates and historical revisions may be approximate; current-vintage data can introduce look-ahead bias.",
            "Macro factors with fewer release observations are intentionally marked insufficient rather than treated as proven or disproven.",
            "Weights are not auto-tuned. Review definitions, source timing, multicollinearity and walk-forward model results before any change.",
        ],
        "factors": rows,
    }
