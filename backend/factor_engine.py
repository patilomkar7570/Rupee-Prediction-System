"""Transparent factor-pressure explanation; not the model's probability engine."""
from __future__ import annotations
import math
from typing import Any
import numpy as np
import pandas as pd
from .paths import FACTOR_WEIGHTS_FILE, ensure_runtime_layout

# Signs are hypotheses for dashboard interpretation. Proxies derived from USDINR are context-only
# to avoid counting the same FX move twice inside the heuristic composite.
FACTOR_META: dict[str, dict[str, Any]] = {
    "USDINR": {"name": "USD/INR momentum", "group": "Currency", "unit": "₹ per USD", "kind": "price", "weight": 0.20, "sign": 1, "why": "Recent rupee weakness may persist temporarily; this is momentum, not a causal explanation."},
    "DXY": {"name": "US Dollar Index", "group": "Dollar strength", "unit": "index points", "kind": "price", "weight": 1.0, "sign": 1, "why": "A broadly stronger dollar can pressure emerging-market currencies, including INR."},
    "USD_CNH": {"name": "USD / offshore yuan proxy", "group": "Global FX", "unit": "yuan per USD", "kind": "price", "weight": 0.45, "sign": 1, "why": "A rising USD/CNH can indicate broad USD strength or China-specific stress; it is not a direct INR signal."},
    "BRENT": {"name": "Brent crude oil", "group": "Import costs", "unit": "USD / barrel", "kind": "price", "weight": 0.75, "sign": 1, "why": "Higher oil prices can increase India's dollar import bill, other things equal."},
    "BRENT_INR_PROXY": {"name": "Brent cost proxy in INR", "group": "Import costs", "unit": "₹ / barrel proxy", "kind": "price", "weight": 0.0, "sign": 0, "why": "Context-only rupee cost proxy (Brent × USD/INR); not scored separately because it duplicates two model inputs."},
    "GOLD": {"name": "Global gold price", "group": "Import costs", "unit": "USD / troy oz", "kind": "price", "weight": 0.35, "sign": 1, "why": "Higher global gold prices may raise India's gold import bill; safe-haven demand and quantities also matter."},
    "GOLD_INR_OZ_PROXY": {"name": "Gold cost proxy in INR", "group": "Import costs", "unit": "₹ / troy oz proxy", "kind": "price", "weight": 0.0, "sign": 0, "why": "Context-only gold × USD/INR proxy; not counted twice in the pressure score."},
    "VIX": {"name": "VIX equity-volatility index", "group": "Global risk", "unit": "index points", "kind": "risk", "weight": 0.65, "sign": 1, "why": "Rising equity volatility may indicate risk aversion and lower appetite for emerging-market assets."},
    "MOVE": {"name": "MOVE Treasury volatility index", "group": "Global risk", "unit": "index points", "kind": "risk", "weight": 0.45, "sign": 1, "why": "Higher Treasury-market volatility can tighten global risk appetite; feed coverage may be unavailable."},
    "EM_EQUITY_PROXY": {"name": "Emerging-markets equity proxy", "group": "Capital flows", "unit": "ETF price", "kind": "price", "weight": 0.40, "sign": -1, "why": "Broad EM equity weakness can proxy for risk-off conditions; an ETF is not a direct capital-flow measure."},
    "WORLD_EQUITY_PROXY": {"name": "Global equity proxy", "group": "Global risk", "unit": "ETF price", "kind": "price", "weight": 0.20, "sign": -1, "why": "A rising global equity proxy can coincide with risk appetite, but relationships vary by regime."},
    "US10Y_YIELD": {"name": "US 10-year Treasury yield", "group": "Capital flows", "unit": "% p.a.", "kind": "rate", "weight": 0.55, "sign": 1, "why": "Higher US yields can make dollar assets more attractive; the reason for the yield move matters."},
    "US2Y_YIELD": {"name": "US 2-year Treasury yield", "group": "Capital flows", "unit": "% p.a.", "kind": "rate", "weight": 0.40, "sign": 1, "why": "The short-end yield reflects policy expectations and can influence global portfolio allocation."},
    "FED_FUNDS_RATE": {"name": "US federal funds effective rate", "group": "Policy rates", "unit": "% p.a.", "kind": "rate", "weight": 0.25, "sign": 1, "why": "A higher US policy rate may support dollar assets; rate expectations and relative returns matter."},
    "RBI_REPO_RATE": {"name": "RBI policy repo rate", "group": "Policy rates", "unit": "% p.a.", "kind": "rate", "weight": 0.40, "sign": -1, "why": "Higher Indian policy rates may support relative returns, though inflation and growth expectations complicate the effect."},
    "INDIA_10Y_BOND_YIELD": {"name": "India 10-year government yield", "group": "Capital flows", "unit": "% p.a.", "kind": "rate", "weight": 0.35, "sign": -1, "why": "Higher Indian yields relative to US yields may support INR, but fiscal and inflation risk can offset that effect."},
    "INDIA_CPI_YOY": {"name": "India CPI inflation", "group": "Inflation", "unit": "% y/y", "kind": "rate", "weight": 0.25, "sign": 1, "why": "Unexpectedly high inflation can hurt the currency through real returns or imports, but policy responses matter."},
    "US_CPI_YOY": {"name": "US CPI inflation", "group": "Inflation", "unit": "% y/y", "kind": "rate", "weight": 0.15, "sign": 1, "why": "Inflation affects expected US policy rates; the direction depends on whether data surprise markets."},
    "ECB_MRO_RATE": {"name": "ECB main refinancing rate", "group": "Policy rates", "unit": "% p.a.", "kind": "context", "weight": 0.0, "sign": 0, "why": "ECB policy affects INR indirectly through EUR, dollar baskets and global funding; no fixed sign is imposed."},
    "GPR_INDEX": {"name": "Geopolitical Risk Index", "group": "Global risk", "unit": "index", "kind": "risk", "weight": 0.50, "sign": 1, "why": "A newspaper-based geopolitical-risk series proxies uncertainty; it is not a complete live-news monitor."},
    "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX": {"name": "Electronics import price index", "group": "Import costs", "unit": "index (base 100)", "kind": "price", "weight": 0.45, "sign": 1, "why": "Optional monthly import unit-value/price index; use a consistent source and do not confuse price with total import value."},
    "INDIA_ELECTRONICS_IMPORT_BILL_USD_BN": {"name": "Electronics import bill", "group": "Import costs", "unit": "USD bn / release", "kind": "flow", "weight": 0.30, "sign": 1, "why": "A larger import bill may raise foreign-currency demand; quantity and seasonality also matter."},
    "INDIA_GOLD_IMPORT_BILL_USD_BN": {"name": "Gold import bill", "group": "Import costs", "unit": "USD bn / release", "kind": "flow", "weight": 0.30, "sign": 1, "why": "A higher gold import bill may raise dollar demand; it combines price and quantity effects."},
    "FPI_NET_FLOWS_USD_BN": {"name": "Foreign portfolio net flows", "group": "Capital flows", "unit": "USD bn / release", "kind": "flow", "weight": 0.65, "sign": -1, "why": "Net inflows can support INR; net outflows may add pressure. Signed changes are used instead of percent changes."},
    "FDI_NET_FLOWS_USD_BN": {"name": "Foreign direct investment flows", "group": "Capital flows", "unit": "USD bn / release", "kind": "flow", "weight": 0.25, "sign": -1, "why": "Net FDI inflows can support external financing; official release timing and revisions matter."},
    "FX_RESERVES_USD_BN": {"name": "Foreign-exchange reserves", "group": "External sector", "unit": "USD bn", "kind": "flow", "weight": 0.30, "sign": -1, "why": "Reserve increases can indicate stronger buffers, but changes can also reflect valuation effects and interventions."},
    "INDIA_TRADE_BALANCE_USD_BN": {"name": "India trade balance", "group": "External sector", "unit": "USD bn / release", "kind": "flow", "weight": 0.30, "sign": -1, "why": "A more positive trade balance can reduce net external financing pressure; the series may be negative."},
    "INDIA_CURRENT_ACCOUNT_USD_BN": {"name": "India current account", "group": "External sector", "unit": "USD bn / release", "kind": "flow", "weight": 0.30, "sign": -1, "why": "An improvement in the current account can reduce external financing needs; quarterly frequency limits short-term usefulness."},
}


def effective_factor_meta() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Return validated, user-configurable heuristic weights/signs from runtime/inputs.

    The checked-in template records defaults. Invalid rows are ignored with an explicit warning;
    settings never get silently learned from the same observations used for evaluation.
    """
    ensure_runtime_layout()
    active = {key: dict(meta) for key, meta in FACTOR_META.items()}
    warnings: list[str] = []
    applied = 0
    seen: set[str] = set()
    try:
        frame = pd.read_csv(FACTOR_WEIGHTS_FILE, keep_default_na=False)
        required = {"factor_key", "weight", "sign"}
        if not required.issubset(frame.columns):
            warnings.append("factor_weights.csv must include factor_key, weight and sign columns; hard-coded defaults are active.")
        else:
            for _, row in frame.iterrows():
                key = str(row.get("factor_key", "")).strip()
                if not key:
                    continue
                if key not in active:
                    warnings.append(f"Unknown factor key ignored: {key}")
                    continue
                if key in seen:
                    warnings.append(f"Duplicate factor key ignored after first row: {key}")
                    continue
                seen.add(key)
                meta = active[key]
                raw_weight = str(row.get("weight", "")).strip()
                raw_sign = str(row.get("sign", "")).strip()
                try:
                    weight = float(raw_weight) if raw_weight else float(meta["weight"])
                    if not np.isfinite(weight) or not 0.0 <= weight <= 2.0:
                        raise ValueError
                    meta["weight"] = weight
                except (TypeError, ValueError):
                    warnings.append(f"Invalid weight for {key}; using default {meta['weight']} (range 0–2).")
                try:
                    sign_float = float(raw_sign) if raw_sign else float(meta["sign"])
                    if not np.isfinite(sign_float) or sign_float not in {-1.0, 0.0, 1.0}:
                        raise ValueError
                    meta["sign"] = int(sign_float)
                except (TypeError, ValueError):
                    warnings.append(f"Invalid sign for {key}; using default {meta['sign']} (-1, 0 or 1).")
                enabled_raw = str(row.get("enabled", "true")).strip().lower()
                if enabled_raw in {"false", "0", "no", "off"}:
                    meta["weight"] = 0.0
                elif enabled_raw not in {"", "true", "1", "yes", "on"}:
                    warnings.append(f"Unrecognized enabled value for {key}; treating as enabled.")
                applied += 1
    except FileNotFoundError:
        warnings.append("No runtime factor configuration found; hard-coded defaults are active.")
    except Exception as exc:
        warnings.append(f"Could not read factor configuration; hard-coded defaults are active: {str(exc)[:180]}")
    return active, {
        "path": str(FACTOR_WEIGHTS_FILE), "rows_applied": applied,
        "defaults_preserved_for_unlisted_factors": True,
        "warnings": warnings,
        "weight_bounds": [0.0, 2.0], "allowed_signs": [-1, 0, 1],
        "note": "Local runtime configuration adjusts the heuristic display only; it does not train or automatically optimize the predictive model.",
    }


def _finite(v: Any) -> float | None:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _series(prices: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(prices[col], errors="coerce") if col in prices.columns else pd.Series(dtype=float, index=prices.index)


def _change(prices: pd.DataFrame, col: str, kind: str) -> tuple[float | None, float | None, str]:
    s = _series(prices, col).dropna()
    if len(s) < 2:
        return None, None, "Insufficient history"
    lookback = 20 if kind in {"flow", "rate", "context"} else 5
    previous = float(s.iloc[-lookback - 1]) if len(s) > lookback else float(s.iloc[0])
    latest = float(s.iloc[-1])
    delta = latest - previous
    if kind in {"price", "risk"}:
        pct = (latest / previous - 1.0) * 100 if previous else None
        return latest, pct, f"{pct:+.2f}% over recent {lookback} observations" if pct is not None else "Change unavailable"
    if kind == "flow":
        return latest, delta, f"{delta:+.3f} USD bn vs ~20 sessions ago (difference; no signed-flow percentage change)"
    return latest, delta, f"{delta:+.3f} over ~20 sessions"


def _standardized_move(prices: pd.DataFrame, col: str, kind: str) -> float:
    s = _series(prices, col).dropna()
    if len(s) < 22:
        return 0.0
    if kind in {"price", "risk"}:
        returns = s.pct_change(fill_method=None)
        recent = float(returns.tail(5).sum())
        scale = float(returns.tail(252).std()) * math.sqrt(5) if returns.notna().sum() > 20 else 0.0
        if not math.isfinite(scale) or scale < 1e-8:
            scale = 0.02
        return float(np.clip(recent / scale, -2.0, 2.0))
    delta = s.diff(20).dropna()
    recent = float(delta.iloc[-1]) if len(delta) else 0.0
    scale = float(delta.tail(252).std()) if len(delta) > 3 else 0.0
    if not math.isfinite(scale) or scale < 1e-6:
        scale = 0.25 if kind == "rate" else 1.0
    return float(np.clip(recent / scale, -2.0, 2.0))


def analyse_factors(prices: pd.DataFrame) -> dict[str, Any]:
    latest_date = prices.index[-1].strftime("%Y-%m-%d") if not prices.empty else None
    rows = []
    pressure_sum = 0.0
    weight_sum = 0.0
    active_meta, config_info = effective_factor_meta()
    total_weight = sum(abs(float(m["weight"])) for m in active_meta.values() if float(m["weight"]) != 0 and int(m["sign"]) != 0)
    available_weight = 0.0
    for col, meta in active_meta.items():
        default_meta = FACTOR_META[col]
        s = _series(prices, col)
        nonnull = s.dropna()
        current = _finite(s.iloc[-1]) if len(s) else None
        available = len(nonnull) >= 22 and current is not None
        latest, change, change_label = _change(prices, col, str(meta["kind"])) if current is not None else (None, None, "Not loaded or stale")
        if current is not None and len(nonnull) < 22:
            available = False
            change_label = "Sparse history; not scored"
        weight, sign = float(meta["weight"]), float(meta["sign"])
        z_move = _standardized_move(prices, col, str(meta["kind"])) if available else 0.0
        contribution = weight * sign * z_move if available else 0.0
        if available and weight != 0 and sign != 0:
            pressure_sum += contribution
            weight_sum += abs(weight)
            available_weight += abs(weight)
        signal = "Context only" if not weight or not sign else ("Rupee pressure ↑" if contribution > 0.12 else "Rupee support ↑" if contribution < -0.12 else "Mixed / small move")
        if col == "USDINR": display = f"₹{latest:,.4f}" if latest is not None else "—"
        elif col in {"US10Y_YIELD", "US2Y_YIELD", "RBI_REPO_RATE", "ECB_MRO_RATE", "FED_FUNDS_RATE", "INDIA_10Y_BOND_YIELD", "INDIA_CPI_YOY", "US_CPI_YOY"}: display = f"{latest:.2f}%" if latest is not None else "—"
        elif col in {"INDIA_ELECTRONICS_IMPORT_BILL_USD_BN", "INDIA_GOLD_IMPORT_BILL_USD_BN", "FPI_NET_FLOWS_USD_BN", "FDI_NET_FLOWS_USD_BN", "FX_RESERVES_USD_BN", "INDIA_TRADE_BALANCE_USD_BN", "INDIA_CURRENT_ACCOUNT_USD_BN"}: display = f"${latest:.3f}bn" if latest is not None else "—"
        elif col in {"BRENT", "GOLD"}: display = f"${latest:,.2f}" if latest is not None else "—"
        elif col == "BRENT_INR_PROXY": display = f"₹{latest:,.2f}/bbl" if latest is not None else "—"
        elif col == "GOLD_INR_OZ_PROXY": display = f"₹{latest:,.0f}/oz" if latest is not None else "—"
        elif col == "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX": display = f"{latest:,.2f}" if latest is not None else "—"
        else: display = f"{latest:,.2f}" if latest is not None else "—"
        rows.append({"key": col, "name": meta["name"], "group": meta["group"], "unit": meta["unit"], "value": latest, "display_value": display, "change": change, "change_label": change_label, "available": bool(available), "coverage_rows": int(len(nonnull)), "interpretation": meta["why"], "signal": signal, "contribution": round(contribution, 4), "source_date": latest_date if available else None, "weight": weight, "default_weight": float(default_meta["weight"]), "sign": sign, "default_sign": int(default_meta["sign"]), "weight_share_pct": round(abs(weight) / total_weight * 100.0, 2) if total_weight and weight != 0 and sign != 0 else 0.0, "source_key": col})
    raw = pressure_sum / max(weight_sum, 1.0)
    pressure = float(np.clip(100 * np.tanh(raw * 1.25), -100, 100))
    if pressure >= 12:
        label, detail = "Upward pressure on USD/INR", "Available directional heuristics lean toward a weaker rupee; the forecast model is evaluated separately."
    elif pressure <= -12:
        label, detail = "Downward pressure on USD/INR", "Available directional heuristics lean toward a stronger rupee; the forecast model is evaluated separately."
    else:
        label, detail = "Mixed / no strong pressure", "The transparent factor score does not show a strong directional tilt."
    coverage = round(100 * available_weight / total_weight, 1) if total_weight else 0.0
    return {"as_of_date": latest_date, "pressure_score": round(pressure, 1), "pressure_label": label, "pressure_detail": detail, "factor_coverage_pct": coverage, "factors": rows, "factor_configuration": config_info, "method_note": "Heuristic factor pressure is for interpretation only; it does not set the forecast label. Weight signs are hypotheses, not causal estimates. Weights/signs can be edited in runtime/inputs/factor_weights.csv; changes are not auto-learned. Derived INR commodity proxies are excluded from the composite to avoid double-counting USDINR."}
