"""Expanding-window walk-forward evaluation for direction and numerical rate forecasts."""
from __future__ import annotations
from typing import Any
import json
import warnings
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .baselines import majority_prediction, random_walk_direction
from .data_processor import make_feature_frame
from .model_comparison import model_factories, evaluation_features, calculate_metrics
from .numerical_forecast import regression_factories, regression_features
from .probability_calibration import CLASS_ORDER, align_probabilities, probability_metrics
from .risk_features import detect_historical_regimes, detect_feature_drift
from .paths import BACKTEST_RESULTS_FILE, ensure_runtime_layout
from .evaluation_uncertainty import balanced_accuracy_interval, balanced_accuracy_difference_interval, mae_skill_interval
from .version import VERSION


def _walk_forward_predictions(prices: pd.DataFrame, horizon: int, max_folds: int | None = None, block_size: int | None = None) -> dict[str, Any]:
    """Evaluate all configured test blocks after the initial training period.

    At each block origin, training labels whose outcome windows reach into the test block
    are purged. The model remains fixed for that block. All models share the same test dates.
    """
    frame = make_feature_frame(prices, horizon)
    target_col = f"target_{horizon}d"
    ret_col = f"target_return_{horizon}d"
    regimes = detect_historical_regimes(prices)
    target = frame[target_col]
    returns = pd.to_numeric(frame[ret_col], errors="coerce")
    labelled_positions = np.flatnonzero(target.notna().to_numpy() & returns.notna().to_numpy())
    n = len(labelled_positions)
    if n < 320:
        raise ValueError(f"Need at least 320 labelled observations for a meaningful walk-forward backtest; found {n} for horizon {horizon}d.")
    initial_train_end = int(n * 0.60)
    block = block_size or max(30, int(n * 0.08))
    test_starts = list(range(initial_train_end, n, block))
    if max_folds is not None:
        test_starts = test_starts[:max_folds]
    factories = model_factories()
    regression_models = regression_factories()
    predictions: dict[str, list[dict[str, Any]]] = {"Random-walk level (FLAT)": [], "Training majority": []}
    predictions.update({name: [] for name in factories})
    numerical_predictions: dict[str, list[dict[str, Any]]] = {"Random-walk numerical level": []}
    numerical_predictions.update({name: [] for name in regression_models})
    fold_summaries = []
    all_test_positions: list[int] = []

    for fold_number, start in enumerate(test_starts, start=1):
        stop = min(n, start + block)
        if stop <= start:
            continue
        first_test_raw_pos = int(labelled_positions[start])
        max_train_raw_pos = first_test_raw_pos - int(horizon) - 1
        train_positions = labelled_positions[labelled_positions <= max_train_raw_pos]
        test_positions = labelled_positions[start:stop]
        if len(train_positions) < 180 or len(test_positions) == 0:
            continue
        all_test_positions.extend(test_positions.tolist())
        train_y = target.iloc[train_positions].astype(str)
        test_y = target.iloc[test_positions].astype(str)
        xcols_by_model = {name: evaluation_features(frame, name) for name in factories}
        fold_metrics: dict[str, Any] = {}
        pred_majority = majority_prediction(train_y, len(test_positions))
        pred_flat = random_walk_direction(len(test_positions))
        for model_name, preds in (("Random-walk level (FLAT)", pred_flat), ("Training majority", pred_majority)):
            for pos, truth, pred in zip(test_positions, test_y, preds):
                preds_row = {"date": frame.index[pos].strftime("%Y-%m-%d"), "truth": str(truth), "prediction": str(pred), "fold": fold_number, "regime": str(regimes.iloc[pos])}
                predictions[model_name].append(preds_row)
            fold_metrics[model_name] = calculate_metrics(test_y, preds)

        for model_name, factory in factories.items():
            xcols = xcols_by_model[model_name]
            model = factory()
            try:
                model.fit(frame.iloc[train_positions][xcols], train_y)
                pred = model.predict(frame.iloc[test_positions][xcols]).astype(str)
                proba = model.predict_proba(frame.iloc[test_positions][xcols]) if hasattr(model, "predict_proba") else None
                estimator = model.named_steps.get("model", None) if hasattr(model, "named_steps") else model
                classes = list(getattr(estimator, "classes_", []))
                aligned = align_probabilities(classes, proba) if proba is not None else None
                for i, (pos, truth, guess) in enumerate(zip(test_positions, test_y, pred)):
                    row = {"date": frame.index[pos].strftime("%Y-%m-%d"), "truth": str(truth), "prediction": str(guess), "fold": fold_number, "regime": str(regimes.iloc[pos])}
                    if aligned is not None:
                        row["probabilities"] = {str(c): float(aligned[i, j]) for j, c in enumerate(CLASS_ORDER)}
                    predictions[model_name].append(row)
                fold_metrics[model_name] = calculate_metrics(test_y, pred)
                if aligned is not None:
                    fold_metrics[model_name]["probability_quality"] = probability_metrics(test_y, aligned)
            except Exception as exc:
                fold_metrics[model_name] = {"error": str(exc)[:220], "rows": len(test_y)}

        # Continuous return models. They are assessed against the random-walk numerical forecast
        # (zero return / unchanged rate) on the exact same test origins.
        ret_train = returns.iloc[train_positions].astype(float)
        ret_test = returns.iloc[test_positions].astype(float).to_numpy()
        origin_rates = pd.to_numeric(prices["USDINR"].iloc[test_positions], errors="coerce").to_numpy(dtype=float)
        actual_rates = np.asarray([float(prices["USDINR"].iloc[int(pos) + horizon]) for pos in test_positions], dtype=float)
        target_dates = [prices.index[int(pos) + horizon].strftime("%Y-%m-%d") for pos in test_positions]
        base_rows = []
        for i, pos in enumerate(test_positions):
            base_rows.append({"origin_date": frame.index[pos].strftime("%Y-%m-%d"), "target_date": target_dates[i], "origin_rate": float(origin_rates[i]), "actual_rate": float(actual_rates[i]), "predicted_rate": float(origin_rates[i]), "actual_return_pct": float(ret_test[i] * 100), "fold": fold_number})
        numerical_predictions["Random-walk numerical level"].extend(base_rows)
        for model_name, factory in regression_models.items():
            try:
                xcols = regression_features(frame, model_name)
                reg_model = factory()
                reg_model.fit(frame.iloc[train_positions][xcols], ret_train)
                pred_ret = np.asarray(reg_model.predict(frame.iloc[test_positions][xcols]), dtype=float)
                for i, pos in enumerate(test_positions):
                    numerical_predictions[model_name].append({
                        "origin_date": frame.index[pos].strftime("%Y-%m-%d"), "target_date": target_dates[i],
                        "origin_rate": float(origin_rates[i]), "actual_rate": float(actual_rates[i]),
                        "predicted_rate": float(origin_rates[i] * (1 + pred_ret[i])),
                        "predicted_return_pct": float(pred_ret[i] * 100), "actual_return_pct": float(ret_test[i] * 100),
                        "fold": fold_number,
                    })
            except Exception as exc:
                # Record a fold-level failure instead of hiding it or invalidating other candidates.
                fold_metrics[f"Numerical · {model_name}"] = {"error": str(exc)[:180], "rows": len(test_y)}
        fold_summaries.append({"fold": fold_number, "train_rows": int(len(train_positions)), "test_rows": int(len(test_positions)), "test_start": frame.index[test_positions[0]].strftime("%Y-%m-%d"), "test_end": frame.index[test_positions[-1]].strftime("%Y-%m-%d"), "metrics": fold_metrics})

    aggregate: dict[str, Any] = {}
    for model_name, rows in predictions.items():
        if rows:
            aggregate[model_name] = calculate_metrics([r["truth"] for r in rows], [r["prediction"] for r in rows])
            aggregate[model_name]["balanced_accuracy_ci_95"] = balanced_accuracy_interval(
                [r["truth"] for r in rows], [r["prediction"] for r in rows],
                block_size=max(5, horizon * 2), seed=42 + horizon,
            )
            prob_rows = [r for r in rows if isinstance(r.get("probabilities"), dict)]
            if prob_rows:
                matrix = np.asarray([[r["probabilities"].get(c, 0.0) for c in CLASS_ORDER] for r in prob_rows], dtype=float)
                aggregate[model_name]["probability_quality"] = probability_metrics([r["truth"] for r in prob_rows], matrix)
        else:
            aggregate[model_name] = {"error": "No successful out-of-sample predictions.", "rows": 0}
    baseline_rows = {r["date"]: r for r in predictions.get("Random-walk level (FLAT)", [])}
    for model_name, rows in predictions.items():
        if model_name in {"Random-walk level (FLAT)", "Training majority"}:
            continue
        model_by_date = {r["date"]: r for r in rows}
        common_dates = sorted(set(model_by_date) & set(baseline_rows))
        if common_dates:
            aggregate[model_name]["balanced_accuracy_delta_vs_random_walk_ci_95"] = balanced_accuracy_difference_interval(
                [model_by_date[d]["truth"] for d in common_dates],
                [model_by_date[d]["prediction"] for d in common_dates],
                [baseline_rows[d]["prediction"] for d in common_dates],
                block_size=max(5, horizon * 2), seed=73 + horizon,
            )

    per_regime: dict[str, Any] = {}
    for model_name, rows in predictions.items():
        per_regime[model_name] = {}
        for regime_name in sorted({r.get("regime", "MIXED") for r in rows}):
            subset = [r for r in rows if r.get("regime") == regime_name]
            if subset:
                per_regime[model_name][regime_name] = calculate_metrics([r["truth"] for r in subset], [r["prediction"] for r in subset])

    numerical: dict[str, Any] = {}
    for model_name, rows in numerical_predictions.items():
        if not rows:
            numerical[model_name] = {"rows": 0, "error": "No numerical predictions produced."}
            continue
        actual = np.asarray([r["actual_rate"] for r in rows], dtype=float)
        pred = np.asarray([r["predicted_rate"] for r in rows], dtype=float)
        mae = float(mean_absolute_error(actual, pred))
        rmse = float(np.sqrt(mean_squared_error(actual, pred)))
        numerical[model_name] = {"rows": len(rows), "mae": round(mae, 6), "rmse": round(rmse, 6), "forecast_dates_start": rows[0]["origin_date"], "forecast_dates_end": rows[-1]["origin_date"]}
        if model_name != "Random-walk numerical level":
            baseline = numerical_predictions["Random-walk numerical level"]
            if len(rows) == len(baseline) and [r["origin_date"] for r in rows] == [r["origin_date"] for r in baseline]:
                baseline_by_date = {r["origin_date"]: r for r in baseline}
                model_by_date = {r["origin_date"]: r for r in rows}
                common_dates = sorted(set(model_by_date) & set(baseline_by_date))
                aligned_actual = [float(model_by_date[d]["actual_rate"]) for d in common_dates]
                aligned_pred = [float(model_by_date[d]["predicted_rate"]) for d in common_dates]
                aligned_base = [float(baseline_by_date[d]["predicted_rate"]) for d in common_dates]
                paired_model_mae = float(mean_absolute_error(aligned_actual, aligned_pred)) if common_dates else float("nan")
                baseline_mae = float(mean_absolute_error(aligned_actual, aligned_base)) if common_dates else 0.0
                numerical[model_name]["mae_skill_vs_random_walk_pct"] = round((1 - paired_model_mae / baseline_mae) * 100, 2) if baseline_mae > 0 and np.isfinite(paired_model_mae) else None
                numerical[model_name]["paired_rows_vs_random_walk"] = int(len(common_dates))
                numerical[model_name]["mae_skill_ci_95"] = mae_skill_interval(
                    aligned_actual, aligned_pred, aligned_base,
                    block_size=max(5, horizon * 2), seed=100 + horizon,
                )
                ci = numerical[model_name]["mae_skill_ci_95"]
                numerical[model_name]["benchmark_evidence"] = (
                    "supportive_in_sample_oos_evidence" if ci.get("lower_pct") is not None and ci["lower_pct"] > 0
                    else "evidence_against_baseline" if ci.get("upper_pct") is not None and ci["upper_pct"] < 0
                    else "inconclusive_or_insufficient"
                )
        numerical[model_name]["note"] = "Fixed-block expanding-window OOS rate forecasts; USD/INR level errors are in rupees per dollar. Negative MAE skill means worse than the random-walk benchmark. Bootstrap intervals are exploratory and are not multiplicity-adjusted."
    all_test_positions = sorted(set(all_test_positions))
    return {
        "horizon_days": horizon, "folds": fold_summaries, "model_metrics": aggregate,
        "per_regime_metrics": per_regime, "oos_predictions": predictions,
        "numerical_forecasts": numerical, "numerical_oos_predictions": numerical_predictions,
        "test_observations": len(all_test_positions),
        "test_method": "Expanding-window fixed blocks. Every eligible observation in the configured later test windows is scored; training labels whose outcome windows overlap the next test block are purged. Feature publication-time integrity still depends on each input source.",
        "threshold_pct": round(0.05 * np.sqrt(horizon), 4),
    }


def run_backtest(prices: pd.DataFrame, horizons: tuple[int, ...] = (1, 5, 20), max_folds: int | None = None) -> dict[str, Any]:
    reports = {}
    for horizon in horizons:
        reports[f"{horizon}d"] = _walk_forward_predictions(prices, horizon, max_folds=max_folds)
    results = {
        "version": VERSION, "created_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "horizons": reports, "feature_drift": detect_feature_drift(prices),
        "caveat": "Historical simulation, not a guarantee. Direction balanced-accuracy intervals and numerical paired MAE-skill intervals use moving-block bootstrap resampling and are exploratory, not multiplicity-adjusted. Historical inputs are not all stored as point-in-time vintages, and several automated macro series use availability approximations. Treat results as experimental until source timestamps have been audited and future shadow forecasts are scored prospectively.",
        "inference_limits": ["Bootstrap intervals are descriptive; they do not adjust for selecting among many models/features.", "Overlapping 5- and 20-session outcomes remain serially dependent despite block resampling.", "Historical macro vintages and publication timestamps are incomplete, so this does not certify leakage-free point-in-time research."],
    }
    ensure_runtime_layout()
    BACKTEST_RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return results
