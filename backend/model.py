"""Multi-horizon direction predictions with chronological model selection and conservative confidence."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from .data_processor import load_price_data, make_feature_frame
from .factor_engine import analyse_factors
from .model_comparison import model_factories, evaluation_features, calculate_metrics, latest_feature_importance
from .baselines import majority_prediction, random_walk_direction
from .confidence import confidence_assessment
from .probability_calibration import CLASS_ORDER, align_probabilities, fit_probability_calibrator, apply_probability_calibrator, probability_metrics
from .risk_features import detect_regime, detect_feature_drift
from .numerical_forecast import run_numerical_forecast
from .evaluation_uncertainty import balanced_accuracy_interval, balanced_accuracy_difference_interval

MODEL_CANDIDATES = ["Market-price Logistic", "Macro Logistic", "Macro Random Forest", "Macro Gradient Boosting"]
HORIZONS = (1, 5, 20)


def _fit_and_predict_holdout(frame: pd.DataFrame, horizon: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target_col = f"target_{horizon}d"
    labelled = frame.dropna(subset=[target_col]).copy()
    target = labelled[target_col].astype(str)
    n = len(labelled)
    if n < 400:
        raise ValueError(f"Only {n} labelled rows for {horizon}-day direction. At least 400 are recommended for model selection, calibration and holdout testing.")
    # Chronological stages: 0-50% model selection fit; 50-65% model selection validation;
    # 65-80% independent calibration; final 20% untouched evaluation.
    selection_start = int(n * 0.50)
    calibration_start = int(n * 0.65)
    test_start = int(n * 0.80)
    labelled_raw_positions = frame.index.get_indexer(labelled.index)
    selection_raw = int(labelled_raw_positions[selection_start])
    calibration_raw = int(labelled_raw_positions[calibration_start])
    test_raw = int(labelled_raw_positions[test_start])

    validation_train_pos = np.flatnonzero(labelled_raw_positions <= selection_raw - horizon - 1)
    validation_pos = np.arange(selection_start, calibration_start)
    if len(validation_train_pos) < 180 or len(validation_pos) < 40 or n - test_start < 40:
        raise ValueError("Insufficient observations for model selection, probability calibration, and untouched holdout testing.")

    factories = model_factories()
    validation_results = []
    val_true = target.iloc[validation_pos]
    for name in MODEL_CANDIDATES:
        features = evaluation_features(frame, name)
        model = factories[name]()
        model.fit(frame.iloc[labelled_raw_positions[validation_train_pos]][features], target.iloc[validation_train_pos])
        pred = model.predict(frame.iloc[labelled_raw_positions[validation_pos]][features]).astype(str)
        metrics = calculate_metrics(val_true, pred)
        validation_results.append({"model": name, "validation_balanced_accuracy_pct": metrics["balanced_accuracy_pct"], "validation_accuracy_pct": metrics["accuracy_pct"], "validation_macro_f1_pct": metrics["macro_f1_pct"], "validation_rows": metrics["rows"]})
    chosen = max(validation_results, key=lambda item: (item["validation_balanced_accuracy_pct"] or 0, item["validation_macro_f1_pct"] or 0))
    chosen_name = chosen["model"]
    features = evaluation_features(frame, chosen_name)

    # Fit calibration using predictions made on a later window not used to fit that calibrating model.
    calibration_fit_pos = np.flatnonzero(labelled_raw_positions <= calibration_raw - horizon - 1)
    calibration_label_pos = np.arange(calibration_start, test_start)
    calibration_label_pos = calibration_label_pos[labelled_raw_positions[calibration_label_pos] <= test_raw - horizon - 1]
    calibration_info = {"status": "not_fit", "message": "Calibration unavailable; raw probabilities are shown."}
    calibrator = None
    if len(calibration_fit_pos) >= 180 and len(calibration_label_pos) >= 50:
        calibration_model = factories[chosen_name]()
        calibration_model.fit(frame.iloc[labelled_raw_positions[calibration_fit_pos]][features], target.iloc[calibration_fit_pos])
        cal_x = frame.iloc[labelled_raw_positions[calibration_label_pos]][features]
        cal_raw = calibration_model.predict_proba(cal_x)
        cal_estimator = calibration_model.named_steps.get("model") if hasattr(calibration_model, "named_steps") else calibration_model
        cal_classes = list(getattr(cal_estimator, "classes_", []))
        cal_aligned = align_probabilities(cal_classes, cal_raw)
        calibrator, calibration_info = fit_probability_calibrator(cal_aligned, target.iloc[calibration_label_pos])
        calibration_info["calibration_start"] = frame.index[labelled_raw_positions[calibration_label_pos[0]]].strftime("%Y-%m-%d")
        calibration_info["calibration_end"] = frame.index[labelled_raw_positions[calibration_label_pos[-1]]].strftime("%Y-%m-%d")

    # Untouched holdout: train only on labels whose target window ends before the test starts.
    fit_label_pos = np.flatnonzero(labelled_raw_positions <= test_raw - horizon - 1)
    test_label_pos = np.arange(test_start, n)
    holdout_model = factories[chosen_name]()
    holdout_model.fit(frame.iloc[labelled_raw_positions[fit_label_pos]][features], target.iloc[fit_label_pos])
    test_x = frame.iloc[labelled_raw_positions[test_label_pos]][features]
    test_y = target.iloc[test_label_pos]
    test_raw_prob = holdout_model.predict_proba(test_x)
    holdout_estimator = holdout_model.named_steps.get("model") if hasattr(holdout_model, "named_steps") else holdout_model
    holdout_classes = list(getattr(holdout_estimator, "classes_", []))
    test_aligned_raw = align_probabilities(holdout_classes, test_raw_prob)
    test_calibrated = apply_probability_calibrator(calibrator, test_aligned_raw)
    test_pred = np.array([CLASS_ORDER[i] for i in test_calibrated.argmax(axis=1)])
    model_metrics = calculate_metrics(test_y, test_pred)
    model_metrics["balanced_accuracy_ci_95"] = balanced_accuracy_interval(test_y, test_pred, block_size=max(5, horizon * 2), seed=42 + horizon)
    probability_quality = probability_metrics(test_y, test_calibrated)

    majority_pred = majority_prediction(target.iloc[fit_label_pos], len(test_label_pos))
    flat_pred = random_walk_direction(len(test_label_pos))
    majority_metrics = calculate_metrics(test_y, majority_pred)
    flat_metrics = calculate_metrics(test_y, flat_pred)
    val_maj = majority_prediction(target.iloc[validation_train_pos], len(validation_pos))
    val_flat = random_walk_direction(len(validation_pos))
    val_maj_metric = calculate_metrics(val_true, val_maj)["balanced_accuracy_pct"] or 0
    val_flat_metric = calculate_metrics(val_true, val_flat)["balanced_accuracy_pct"] or 0
    baseline_name = "Training majority" if val_maj_metric >= val_flat_metric else "Random-walk level (FLAT)"
    baseline_metrics = majority_metrics if baseline_name == "Training majority" else flat_metrics
    baseline_predictions = majority_pred if baseline_name == "Training majority" else flat_pred
    direction_difference_ci = balanced_accuracy_difference_interval(
        test_y, test_pred, baseline_predictions, block_size=max(5, horizon * 2), seed=73 + horizon,
    )

    # Refit the selected estimator on all available labelled history for current forecasts, then
    # apply the calibration mapping fitted strictly on an earlier calibration window.
    final_model = factories[chosen_name]()
    final_model.fit(frame.iloc[labelled_raw_positions][features], target)
    latest_x = frame.iloc[[-1]][features]
    final_raw_probability = final_model.predict_proba(latest_x)
    final_estimator = final_model.named_steps.get("model") if hasattr(final_model, "named_steps") else final_model
    final_classes = list(getattr(final_estimator, "classes_", []))
    raw_aligned = align_probabilities(final_classes, final_raw_probability)
    calibrated = apply_probability_calibrator(calibrator, raw_aligned)[0]
    raw_latest = raw_aligned[0]
    probabilities = {c: round(float(calibrated[i]), 4) for i, c in enumerate(CLASS_ORDER)}
    raw_probabilities = {c: round(float(raw_latest[i]), 4) for i, c in enumerate(CLASS_ORDER)}
    predicted_class = CLASS_ORDER[int(np.argmax(calibrated))]
    confidence = confidence_assessment(
        probabilities,
        (model_metrics["balanced_accuracy_pct"] or 0) / 100,
        (baseline_metrics["balanced_accuracy_pct"] or 0) / 100,
        model_metrics["rows"],
        (model_metrics["accuracy_pct"] or 0) / 100,
    )
    final_prediction = predicted_class if confidence["label"] != "NO RELIABLE SIGNAL" else "NO RELIABLE SIGNAL"
    selection_report = sorted(validation_results, key=lambda item: item["validation_balanced_accuracy_pct"] or 0, reverse=True)
    result = {
        "horizon_days": horizon, "prediction": final_prediction, "model_prediction": predicted_class,
        "selected_model": chosen_name, "model_probabilities": probabilities,
        "raw_model_probabilities": raw_probabilities, "probability_calibration": calibration_info,
        "holdout_probability_quality": probability_quality, "confidence": confidence,
        "test_metrics": model_metrics, "baseline_metrics": baseline_metrics,
        "balanced_accuracy_delta_vs_selected_baseline_ci_95": direction_difference_ci,
        "baseline_selected": baseline_name,
        "all_baselines": {"training_majority": majority_metrics, "random_walk_flat": flat_metrics},
        "validation_model_comparison": selection_report,
        "training_rows": int(len(fit_label_pos)), "labelled_rows": int(n),
        "test_rows": int(model_metrics["rows"]), "feature_count": int(len(features)),
        "top_feature_importance": latest_feature_importance(final_model, features, top_n=12),
        "price_only_features_count": int(len(evaluation_features(frame, "Market-price Logistic"))),
    }
    return result, selection_report


def predict_next_session() -> dict[str, Any]:
    prices = load_price_data()
    if len(prices) < 400:
        raise ValueError(f"Only {len(prices)} daily rows are available. Fetch more history; v4 recommends at least 400 rows for multi-horizon testing.")
    horizon_results = []
    for horizon in HORIZONS:
        frame = make_feature_frame(prices, horizon)
        report, _ = _fit_and_predict_holdout(frame, horizon)
        report["numerical_forecast"] = run_numerical_forecast(prices, frame, horizon)
        horizon_results.append(report)
    primary = horizon_results[0]
    factors = analyse_factors(prices)
    regime = detect_regime(prices)
    drift = detect_feature_drift(prices)
    latest_date = prices.index[-1]
    rate = float(prices["USDINR"].iloc[-1])
    prior = float(prices["USDINR"].iloc[-2]) if len(prices) > 1 else None
    daily_change = (rate / prior - 1) * 100 if prior else None
    return {
        "prediction": primary["prediction"],
        "model_prediction": primary["model_prediction"],
        "selected_model": primary["selected_model"],
        "model_probabilities": primary["model_probabilities"],
        "confidence": primary["confidence"],
        "confidence_label": primary["confidence"]["label"],
        "test_accuracy_pct": primary["test_metrics"]["accuracy_pct"],
        "balanced_accuracy_pct": primary["test_metrics"]["balanced_accuracy_pct"],
        "baseline_accuracy_pct": primary["baseline_metrics"]["accuracy_pct"],
        "baseline_balanced_accuracy_pct": primary["baseline_metrics"]["balanced_accuracy_pct"],
        "baseline_selected": primary["baseline_selected"],
        "test_rows": primary["test_rows"],
        "training_rows": primary["training_rows"],
        "feature_count": primary["feature_count"],
        "top_feature_importance": primary["top_feature_importance"],
        "validation_model_comparison": primary["validation_model_comparison"],
        "horizons": horizon_results,
        "factor_analysis": factors,
        "market_regime": regime,
        "feature_drift": drift,
        "as_of_date": latest_date.strftime("%Y-%m-%d"),
        "usd_inr_close": round(rate, 4),
        "daily_change_pct": round(float(daily_change), 4) if daily_change is not None else None,
        "usable_rows": int(len(prices)),
        "feature_sources": [c for c in prices.columns if prices[c].notna().sum() >= 30 and c != "USDINR"],
        "note": "v4.0 selects classification and numerical models on earlier chronological windows, calibrates probabilities/interval residuals on a separate later window, and evaluates on a later untouched holdout. It does not select models on the holdout. Point-in-time macro vintage coverage remains incomplete; predictions are experimental and may not generalize to future regimes.",
        "probability_note": "Probabilities are calibrated only when the separate calibration window had enough observations across all classes; otherwise raw class estimates are shown. They are not guaranteed odds. 'No reliable signal' is emitted when the model has not shown enough out-of-sample evidence against a selected simple baseline.",
    }
