"""Fetch current market history, run chronological walk-forward evaluation, and write a local report.

Run from the project root with: python -m backend.validate_real_data
This workflow requires network access and can take several minutes on first run.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .data_collector import collect_market_data, get_source_status
from .backtest import run_backtest
from .paths import RUNTIME_DIR, ensure_runtime_layout
from .target_source import get_target_source


BASELINES = {"Random-walk level (FLAT)", "Training majority", "Market-price Logistic"}


def _percent(value: object) -> str:
    return f"{float(value):.2f}%" if isinstance(value, (int, float)) else "n/a"

def fmt_num(value: object, digits: int = 4) -> str:
    return f"{float(value):.{digits}f}" if isinstance(value, (int, float)) else "n/a"

def fmt_pct(value: object) -> str:
    return f"{float(value):.2f}%" if isinstance(value, (int, float)) else "n/a"



def validate_target_freshness(
    prices: pd.DataFrame,
    *,
    now: pd.Timestamp | None = None,
    max_age_days: int = 7,
) -> dict[str, object]:
    """Fail closed when the target series is invalid, future-dated, or stale.

    The freshness rule is intentionally in calendar days to tolerate weekends/holidays,
    while still preventing an old cached reference-rate dataset from being presented as
    a live-data validation run.
    """
    if prices is None or prices.empty or "USDINR" not in prices.columns:
        raise RuntimeError("No valid USD/INR target history is available for freshness validation.")

    rates = pd.to_numeric(prices["USDINR"], errors="coerce").to_numpy(dtype=float)
    if not len(rates) or not np.isfinite(rates).all() or (rates <= 0).any():
        raise RuntimeError("USD/INR target history contains missing, non-finite, or non-positive values; validation stopped.")

    latest = pd.Timestamp(prices.index.max())
    if pd.isna(latest):
        raise RuntimeError("Latest USD/INR target date is invalid; validation stopped.")
    if latest.tzinfo is not None:
        latest = latest.tz_convert("UTC").tz_localize(None)
    latest = latest.normalize()

    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if current.tzinfo is not None:
        current = current.tz_convert("UTC").tz_localize(None)
    today = current.normalize()
    age_days = int((today - latest).days)

    if age_days < -1:
        raise RuntimeError(
            f"Latest USD/INR target observation ({latest:%Y-%m-%d}) is {abs(age_days)} days in the future; verify timestamps."
        )
    if age_days > int(max_age_days):
        raise RuntimeError(
            f"Latest USD/INR target observation is {age_days} calendar days old "
            f"({latest:%Y-%m-%d}); maximum allowed for live-data validation is {max_age_days} days."
        )

    return {
        "latest_target_date": latest.strftime("%Y-%m-%d"),
        "age_calendar_days": age_days,
        "maximum_age_calendar_days": int(max_age_days),
        "status": "current",
        "note": "Target freshness is a minimum live-data gate, not proof that the source is official or historically point-in-time clean.",
    }

def build_report() -> dict:
    ensure_runtime_layout()
    print("[1/3] Downloading and aligning up to five years of market/macro history...")
    prices = collect_market_data(period="5y")
    if prices.empty or "USDINR" not in prices.columns:
        raise RuntimeError("No valid USD/INR market history was collected; validation stopped.")
    target_freshness = validate_target_freshness(prices)
    if len(prices) < 400:
        raise RuntimeError(f"Only {len(prices)} aligned observations are available. At least 400 are recommended; validation stopped.")

    print(f"Collected {len(prices):,} aligned observations from {prices.index.min():%Y-%m-%d} to {prices.index.max():%Y-%m-%d}.")
    print("[2/3] Running expanding-window walk-forward tests for 1, 5 and 20 sessions...")
    backtest = run_backtest(prices, horizons=(1, 5, 20), max_folds=None)
    source_status = get_source_status()
    target_source = get_target_source()
    data_kind = {
        "fbil_csv": "user-imported reference-rate CSV for the USD/INR target, aligned with available cross-market and macro history",
        "rbi_dbie_mirror": "RBI DBIE reference-rate table via a third-party mirror; not a live RBI feed, verify latest observation date",
        "yahoo_proxy": "downloaded market history with Yahoo Finance INR=X as the USD/INR target proxy",
    }.get(target_source, f"target-source mode {target_source!r}; verify target provenance")

    horizon_summary: dict[str, dict] = {}
    for horizon, result in backtest.get("horizons", {}).items():
        metrics = result.get("model_metrics", {})
        valid = {
            name: values for name, values in metrics.items()
            if isinstance(values, dict) and isinstance(values.get("balanced_accuracy_pct"), (int, float))
        }
        baseline_valid = {name: values for name, values in valid.items() if name in BASELINES}
        model_valid = {name: values for name, values in valid.items() if name not in BASELINES}
        best_baseline = max(baseline_valid.items(), key=lambda item: item[1]["balanced_accuracy_pct"], default=(None, None))
        best_model = max(model_valid.items(), key=lambda item: item[1]["balanced_accuracy_pct"], default=(None, None))
        delta = None
        if best_baseline[1] is not None and best_model[1] is not None:
            delta = round(best_model[1]["balanced_accuracy_pct"] - best_baseline[1]["balanced_accuracy_pct"], 2)
        horizon_summary[horizon] = {
            "best_baseline": {"name": best_baseline[0], "metrics": best_baseline[1]},
            "best_macro_or_candidate": {"name": best_model[0], "metrics": best_model[1]},
            "balanced_accuracy_delta_vs_best_baseline_pp": delta,
            "model_metrics": metrics,
            "numerical_model_metrics": result.get("numerical_forecasts", {}),
            "fold_count": len(result.get("folds", [])),
            "test_method": result.get("test_method", ""),
        }

    result = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_kind": data_kind,
        "target_source": target_source,
        "target_freshness": target_freshness,
        "observations": int(len(prices)),
        "start_date": prices.index.min().strftime("%Y-%m-%d"),
        "end_date": prices.index.max().strftime("%Y-%m-%d"),
        "sources": source_status,
        "horizons": horizon_summary,
        "methodology_caveat": backtest.get("caveat", "") ,
        "interpretation": (
            "These metrics describe one historical sample under this backtest implementation. They do not establish stable future performance, "
            "economic causality, or profitability. Check point-in-time publication dates, missing sources, class coverage, and benchmark deltas before making claims."
        ),
    }
    json_path = RUNTIME_DIR / "real_market_validation.json"
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Real-Market Validation Report",
        "",
        f"- Generated (UTC): {result['generated_at_utc']}",
        f"- Data kind: {data_kind}.",
        f"- Target-source mode: {target_source}.",
        f"- Target freshness: {target_freshness['status']} (latest {target_freshness['latest_target_date']}, age {target_freshness['age_calendar_days']} calendar days; limit {target_freshness['maximum_age_calendar_days']}).",
        f"- Aligned observations: {result['observations']:,}",
        f"- Sample window: {result['start_date']} to {result['end_date']}",
        "- Method: expanding-window walk-forward evaluation; target-overlap label purging is applied by the backtest implementation.",
        "",
        "## Direction-classification results",
        "",
        "Balanced accuracy is compared against the strongest measured baseline within each horizon. Values are percentage points (pp).",
        "",
        "| Horizon | Best baseline | Baseline balanced accuracy | Best non-baseline candidate | Candidate balanced accuracy | Delta (pp) | Test rows |",
        "|---|---|---:|---|---:|---:|---:|",
    ]
    for horizon, item in horizon_summary.items():
        baseline = item["best_baseline"]
        candidate = item["best_macro_or_candidate"]
        bm = baseline["metrics"] or {}
        cm = candidate["metrics"] or {}
        lines.append(
            f"| {horizon} | {baseline['name'] or 'n/a'} | {_percent(bm.get('balanced_accuracy_pct'))} | "
            f"{candidate['name'] or 'n/a'} | {_percent(cm.get('balanced_accuracy_pct'))} | "
            f"{item['balanced_accuracy_delta_vs_best_baseline_pp'] if item['balanced_accuracy_delta_vs_best_baseline_pp'] is not None else 'n/a'} | "
            f"{cm.get('rows', 'n/a')} |"
        )
    lines.extend([
        "", "## Numerical-rate forecasting results", "",
        "MAE/RMSE are in rupees per US dollar. Positive MAE skill means the model's MAE is lower than the unchanged-rate random-walk benchmark; negative skill means it performed worse.",
        "", "| Horizon | Model | MAE (₹/$) | RMSE (₹/$) | MAE skill vs random walk | Test rows |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for horizon, item in horizon_summary.items():
        for name, metrics in item.get("numerical_model_metrics", {}).items():
            lines.append(
                f"| {horizon} | {name} | "
                f"{fmt_num(metrics.get('mae'), 5)} | {fmt_num(metrics.get('rmse'), 5)} | "
                f"{fmt_pct(metrics.get('mae_skill_vs_random_walk_pct'))} | {metrics.get('rows', 'n/a')} |"
            )
    lines.extend(["", "## Data-source status", "", "| Source | Status | Latest date | Notes |", "|---|---|---|---|"])
    for name, status in sorted(source_status.items()):
        if not isinstance(status, dict):
            continue
        label = name.replace("|", "\\|")
        source_state = str(status.get("status", "unknown")).replace("|", "\\|")
        latest = str(status.get("latest_date") or "—").replace("|", "\\|")
        note = str(status.get("message", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {label} | {source_state} | {latest} | {note} |")
    lines.extend([
        "",
        "## Interpretation and guardrails",
        "",
        result["interpretation"],
        "",
        "A candidate beating a baseline on this single historical window is not proof of durable forecasting edge. Check accuracy, balanced accuracy, macro F1, class coverage, probability calibration where available, and results across market regimes. Consider a later untouched holdout and multiple evaluation windows before publishing a performance claim.",
        "",
        "This tool is for education and research, not financial advice. Do not use a model output alone to trade or size a position.",
        "",
    ])
    report_path = RUNTIME_DIR / "REAL_MARKET_VALIDATION.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print("[3/3] Validation complete.")
    print(f"Markdown report: {report_path}")
    print(f"Structured results: {json_path}")
    print(f"Full backtest: {RUNTIME_DIR / 'backtest_results.json'}")
    return result


def main() -> int:
    try:
        report = build_report()
        print("\nBalanced-accuracy deltas vs best baseline (percentage points):")
        for horizon, item in report["horizons"].items():
            print(f"  {horizon}: {item['balanced_accuracy_delta_vs_best_baseline_pp']}")
        print("\nDo not describe the model as accurate or profitable based on one backtest alone.")
        return 0
    except Exception as exc:
        print(f"REAL-DATA VALIDATION FAILED: {exc}")
        print("Check internet access, source status, and the runtime data directory; no accuracy claim should be made from this run.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
