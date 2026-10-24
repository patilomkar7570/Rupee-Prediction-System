"""Time-ordered feature-family ablation study (diagnostic association, not causality)."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from .version import VERSION
from .data_processor import make_feature_frame
from .model_comparison import model_factories, calculate_metrics, evaluation_features
from .baselines import random_walk_direction

FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "Market prices & momentum": ("USDINR_", "DXY_", "BRENT_", "GOLD_", "VIX_", "MOVE_", "USD_CNH_", "EM_EQUITY_PROXY_", "WORLD_EQUITY_PROXY_"),
    "Rates & inflation": ("US10Y_YIELD_", "US2Y_YIELD_", "FED_FUNDS_RATE_", "RBI_REPO_RATE_", "ECB_MRO_RATE_", "INDIA_10Y_BOND_YIELD_", "INDIA_CPI_YOY_", "US_CPI_YOY_", "POLICY_SPREAD_", "BOND_SPREAD_", "INDIA_APPROX_REAL_POLICY_RATE", "US_APPROX_REAL_POLICY_RATE", "REAL_POLICY_SPREAD"),
    "India external sector & flows": ("FX_RESERVES_", "FPI_", "FDI_", "INDIA_TRADE_BALANCE_", "INDIA_CURRENT_ACCOUNT_", "INDIA_ELECTRONICS_", "INDIA_GOLD_IMPORT_BILL_"),
    "Global risk & events": ("GPR_INDEX_", "EVENT_"),
}


def family_columns(columns: list[str]) -> dict[str, list[str]]:
    mapped: dict[str, list[str]] = {}
    for family, prefixes in FEATURE_FAMILIES.items():
        matches = [name for name in columns if any(name.startswith(prefix) for prefix in prefixes)]
        if matches:
            mapped[family] = matches
    return mapped


def run_feature_ablation(prices: pd.DataFrame, horizon: int = 5) -> dict[str, Any]:
    if horizon not in (1, 5, 20):
        raise ValueError("Horizon must be 1, 5 or 20 sessions.")
    frame = make_feature_frame(prices, horizon)
    target_col = f"target_{horizon}d"
    target = frame[target_col]
    labelled = np.flatnonzero(target.notna().to_numpy())
    n = len(labelled)
    if n < 400:
        raise ValueError(f"Feature ablation needs at least 400 labelled observations; found {n}.")
    full_cols = evaluation_features(frame, "Macro Logistic")
    groups = family_columns(full_cols)
    initial_train_end = int(n * .60)
    block = max(30, int(n * .08))
    test_starts = list(range(initial_train_end, n, block))
    variants: dict[str, list[str]] = {"Full macro feature set": full_cols}
    for family, cols in groups.items():
        remaining = [col for col in full_cols if col not in set(cols)]
        if len(remaining) >= 3:
            variants[f"Without {family}"] = remaining
    rows_by_variant = {name: [] for name in variants}
    baseline_rows = []
    fold_rows = []
    factory = model_factories()["Macro Logistic"]
    for fold, start in enumerate(test_starts, start=1):
        stop = min(n, start + block)
        first_test_raw = int(labelled[start])
        train = labelled[labelled <= first_test_raw - horizon - 1]
        test = labelled[start:stop]
        if len(train) < 180 or not len(test):
            continue
        train_y = target.iloc[train].astype(str)
        test_y = target.iloc[test].astype(str)
        rw = calculate_metrics(test_y, random_walk_direction(len(test)))
        baseline_rows.extend({"truth": str(y), "prediction": "FLAT", "fold": fold} for y in test_y)
        this_fold: dict[str, Any] = {"fold": fold, "test_rows": int(len(test)), "full_features": len(full_cols)}
        for name, columns in variants.items():
            try:
                model = factory()
                model.fit(frame.iloc[train][columns], train_y)
                pred = model.predict(frame.iloc[test][columns]).astype(str)
                for pos, truth, guess in zip(test, test_y, pred):
                    rows_by_variant[name].append({"date": frame.index[pos].strftime("%Y-%m-%d"), "truth": str(truth), "prediction": str(guess), "fold": fold})
                this_fold[name] = calculate_metrics(test_y, pred)
            except Exception as exc:
                this_fold[name] = {"error": str(exc)[:180]}
        this_fold["Random-walk level (FLAT)"] = rw
        fold_rows.append(this_fold)
    baseline = calculate_metrics([r["truth"] for r in baseline_rows], [r["prediction"] for r in baseline_rows]) if baseline_rows else {"rows": 0}
    full_rows = rows_by_variant.get("Full macro feature set", [])
    full_metrics = calculate_metrics([r["truth"] for r in full_rows], [r["prediction"] for r in full_rows]) if full_rows else {"rows": 0}
    results = []
    for name, rows in rows_by_variant.items():
        metrics = calculate_metrics([r["truth"] for r in rows], [r["prediction"] for r in rows]) if rows else {"rows": 0}
        delta = None
        if name != "Full macro feature set" and isinstance(metrics.get("balanced_accuracy_pct"), (int,float)) and isinstance(full_metrics.get("balanced_accuracy_pct"), (int,float)):
            delta = round(metrics["balanced_accuracy_pct"] - full_metrics["balanced_accuracy_pct"], 2)
        results.append({"variant": name, "features": len(variants[name]), "metrics": metrics, "balanced_accuracy_delta_vs_full_pp": delta, "dates": len(rows)})
    return {
        "version": VERSION, "horizon_sessions": horizon, "model": "Macro Logistic",
        "test_method": "Same chronological fixed-block OOS test dates for every ablation variant; overlapping training labels purged at each block origin.",
        "test_rows": int(len(full_rows)), "test_start": full_rows[0]["date"] if full_rows else None, "test_end": full_rows[-1]["date"] if full_rows else None,
        "baseline_random_walk": baseline, "full_feature_metrics": full_metrics, "variants": results, "folds": fold_rows,
        "limitations": ["Ablation measures predictive contribution conditional on this model and test design; it does not establish economic causality.", "Correlated feature families can mask each other's contribution.", "Automated macro publication timing is not a complete point-in-time vintage database.", "A result from one horizon and one historical sample should not be treated as stable model truth."],
    }
