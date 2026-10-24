"""Numerical rate forecasting with chronological model selection and split residual intervals.

All performance figures are historical holdout measurements, not guarantees. Macro-series
publication timestamps are only as reliable as their source metadata; review VALIDATION.md.
"""
from __future__ import annotations
from typing import Any, Callable
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .data_processor import price_only_columns
from .evaluation_uncertainty import mae_skill_interval


def regression_factories() -> dict[str, Callable[[], Any]]:
    return {
        "Market-price Ridge": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=20.0)),
        ]),
        "Macro Ridge": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", Ridge(alpha=40.0)),
        ]),
        "Macro Extra Trees": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", ExtraTreesRegressor(n_estimators=100, max_depth=5, min_samples_leaf=10, max_features=0.75, random_state=42, n_jobs=1)),
        ]),
    }


def regression_features(frame: pd.DataFrame, model_name: str) -> list[str]:
    excluded = {c for c in frame.columns if c.startswith("target_")}
    cols = [c for c in frame.columns if c not in excluded]
    if model_name.startswith("Market-price"):
        allowed = set(price_only_columns(frame))
        cols = [c for c in cols if c in allowed]
    return cols


def _errors(actual: np.ndarray, forecast: np.ndarray) -> dict[str, Any]:
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(forecast)
    actual, forecast = actual[mask], forecast[mask]
    if not len(actual):
        return {"rows": 0, "mae": None, "rmse": None}
    return {
        "rows": int(len(actual)),
        "mae": round(float(mean_absolute_error(actual, forecast)), 6),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, forecast))), 6),
    }


def _fit_predict(factory_name: str, factories: dict[str, Callable[[], Any]], frame: pd.DataFrame,
                 y: pd.Series, fit_positions: np.ndarray, predict_positions: np.ndarray) -> np.ndarray:
    if factory_name == "Random-walk level (zero return)":
        return np.zeros(len(predict_positions), dtype=float)
    features = regression_features(frame, factory_name)
    model = factories[factory_name]()
    model.fit(frame.iloc[fit_positions][features], y.iloc[fit_positions].astype(float))
    return np.asarray(model.predict(frame.iloc[predict_positions][features]), dtype=float)


def run_numerical_forecast(prices: pd.DataFrame, frame: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """Selects a return regressor chronologically, estimates residual bands, and scores a holdout."""
    ret_col = f"target_return_{horizon}d"
    y_all = pd.to_numeric(frame[ret_col], errors="coerce")
    valid = np.flatnonzero(y_all.notna().to_numpy())
    n = len(valid)
    if n < 400:
        raise ValueError(f"Need at least 400 labelled rows for numerical forecasting at {horizon} sessions; found {n}.")
    selection_start, calibration_start, test_start = int(n*.50), int(n*.65), int(n*.80)
    raw_selection = int(valid[selection_start])
    raw_calibration = int(valid[calibration_start])
    raw_test = int(valid[test_start])
    validation_train = valid[valid <= raw_selection - horizon - 1]
    validation = valid[selection_start:calibration_start]
    calibration_train = valid[valid <= raw_calibration - horizon - 1]
    calibration = valid[calibration_start:test_start]
    calibration = calibration[valid[calibration_start:test_start] <= raw_test - horizon - 1]
    test_train = valid[valid <= raw_test - horizon - 1]
    test = valid[test_start:]
    if len(validation_train) < 180 or len(validation) < 40 or len(calibration_train) < 180 or len(calibration) < 40 or len(test_train) < 180 or len(test) < 40:
        raise ValueError(f"Not enough chronological data for regression selection/calibration/holdout at {horizon} sessions.")

    factories = regression_factories()
    selection_scores: list[dict[str, Any]] = []
    candidates = ["Random-walk level (zero return)", *factories.keys()]
    for name in candidates:
        try:
            preds = _fit_predict(name, factories, frame, y_all, validation_train, validation)
            actual = y_all.iloc[validation].to_numpy(dtype=float)
            mae = float(mean_absolute_error(actual, preds))
            selection_scores.append({"model": name, "validation_return_mae_bps": round(mae * 10000, 3), "validation_rows": int(len(validation))})
        except Exception as exc:
            selection_scores.append({"model": name, "validation_return_mae_bps": None, "validation_rows": int(len(validation)), "error": str(exc)[:180]})
    viable = [x for x in selection_scores if x.get("validation_return_mae_bps") is not None]
    if not viable:
        raise ValueError("All numerical candidate models failed during chronological validation.")
    chosen = min(viable, key=lambda x: x["validation_return_mae_bps"])["model"]

    # Calibrate the interval from a later period with no overlapping labels into the final holdout.
    calibration_pred = _fit_predict(chosen, factories, frame, y_all, calibration_train, calibration)
    calibration_residual = y_all.iloc[calibration].to_numpy(dtype=float) - calibration_pred
    abs_calibration_residual = np.abs(calibration_residual)
    q80 = float(np.quantile(abs_calibration_residual, .80, method="higher"))
    q95 = float(np.quantile(abs_calibration_residual, .95, method="higher"))

    test_pred = _fit_predict(chosen, factories, frame, y_all, test_train, test)
    test_actual_return = y_all.iloc[test].to_numpy(dtype=float)
    test_origin_rates = prices["USDINR"].iloc[test].to_numpy(dtype=float)
    raw_positions = np.asarray(test, dtype=int)
    target_rates = np.asarray([float(prices["USDINR"].iloc[pos + horizon]) for pos in raw_positions], dtype=float)
    predicted_rates = test_origin_rates * (1.0 + test_pred)
    walk_rates = test_origin_rates.copy()
    model_rate_metrics = _errors(target_rates, predicted_rates)
    rw_rate_metrics = _errors(target_rates, walk_rates)
    model_rate_metrics["skill_vs_random_walk_pct"] = round((1 - model_rate_metrics["mae"] / rw_rate_metrics["mae"]) * 100, 2) if model_rate_metrics["mae"] is not None and rw_rate_metrics["mae"] not in (None, 0) else None
    model_rate_metrics["mae_skill_ci_95"] = mae_skill_interval(
        target_rates, predicted_rates, walk_rates, block_size=max(5, horizon * 2), seed=100 + horizon,
    )
    ci = model_rate_metrics["mae_skill_ci_95"]
    model_rate_metrics["benchmark_evidence"] = (
        "supportive_in_sample_oos_evidence" if ci.get("lower_pct") is not None and ci["lower_pct"] > 0
        else "evidence_against_baseline" if ci.get("upper_pct") is not None and ci["upper_pct"] < 0
        else "inconclusive_or_insufficient"
    )
    model_rate_metrics["return_mae_bps"] = round(float(mean_absolute_error(test_actual_return, test_pred)) * 10000, 3)
    model_rate_metrics["return_rmse_bps"] = round(float(np.sqrt(mean_squared_error(test_actual_return, test_pred))) * 10000, 3)
    interval80 = np.abs(test_actual_return - test_pred) <= q80
    interval95 = np.abs(test_actual_return - test_pred) <= q95
    holdout_coverage = {"80pct_interval_empirical_coverage_pct": round(float(interval80.mean()) * 100, 2), "95pct_interval_empirical_coverage_pct": round(float(interval95.mean()) * 100, 2), "note": "Coverage measured on a later holdout using absolute residual quantiles from the prior calibration window; results can drift."}

    final_valid = valid
    current_return = float(_fit_predict(chosen, factories, frame, y_all, final_valid, np.array([len(frame) - 1]))[0])
    current_rate = float(prices["USDINR"].iloc[-1])
    forecast_rate = current_rate * (1.0 + current_return)
    latest_q80, latest_q95 = current_rate * q80, current_rate * q95
    probs_returns = y_all.dropna().iloc[-min(756, n):]
    hist_abs_move = np.abs(probs_returns.to_numpy(dtype=float))
    historical_q80 = float(np.quantile(hist_abs_move, .80, method="higher")) if len(hist_abs_move) else None
    historical_q95 = float(np.quantile(hist_abs_move, .95, method="higher")) if len(hist_abs_move) else None
    return {
        "horizon_sessions": int(horizon), "selected_model": chosen,
        "forecast_rate": round(forecast_rate, 4), "forecast_return_pct": round(current_return * 100, 4),
        "forecast_intervals": {
            "80pct": {"lower": round(max(0.0001, forecast_rate - latest_q80), 4), "upper": round(forecast_rate + latest_q80, 4), "calibration_abs_return_pct": round(q80 * 100, 4)},
            "95pct": {"lower": round(max(0.0001, forecast_rate - latest_q95), 4), "upper": round(forecast_rate + latest_q95, 4), "calibration_abs_return_pct": round(q95 * 100, 4)},
        },
        "holdout_metrics": model_rate_metrics,
        "random_walk_holdout_metrics": rw_rate_metrics,
        "holdout_interval_coverage": holdout_coverage,
        "validation_model_comparison": selection_scores,
        "validation_period": {"start": frame.index[validation[0]].strftime("%Y-%m-%d"), "end": frame.index[validation[-1]].strftime("%Y-%m-%d")},
        "calibration_period": {"start": frame.index[calibration[0]].strftime("%Y-%m-%d"), "end": frame.index[calibration[-1]].strftime("%Y-%m-%d"), "rows": int(len(calibration))},
        "holdout_period": {"start": frame.index[test[0]].strftime("%Y-%m-%d"), "end": frame.index[test[-1]].strftime("%Y-%m-%d"), "rows": int(len(test))},
        "historical_return_distribution": {"rows": int(len(probs_returns)), "absolute_return_q80_pct": round((historical_q80 or 0) * 100, 4), "absolute_return_q95_pct": round((historical_q95 or 0) * 100, 4)},
        "caveat": "The selected return model is chosen on an earlier validation window; intervals use absolute residual quantiles from a separate later calibration window. They are empirical research intervals, not guarantees or fully regime-conditional forecasts.",
    }
