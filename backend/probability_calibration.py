"""Chronological multiclass probability calibration using a separate calibration window."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss

CLASS_ORDER = ["DOWN", "FLAT", "UP"]


def align_probabilities(classes: list[str], values: np.ndarray) -> np.ndarray:
    out = np.full((values.shape[0], len(CLASS_ORDER)), 1e-6, dtype=float)
    for j, cls in enumerate(classes):
        if cls in CLASS_ORDER:
            out[:, CLASS_ORDER.index(cls)] = np.asarray(values)[:, j]
    out = np.clip(out, 1e-6, None)
    return out / out.sum(axis=1, keepdims=True)


def fit_probability_calibrator(probabilities: np.ndarray, y_true) -> tuple[Any | None, dict[str, Any]]:
    y = pd.Series(y_true).astype(str).to_numpy()
    probs = np.asarray(probabilities, dtype=float)
    if len(y) < 50 or len(np.unique(y)) < 3:
        return None, {"status": "not_fit", "message": "Not enough calibration observations across all three classes; raw estimates will be shown."}
    features = np.log(np.clip(probs, 1e-6, 1.0))
    calibrator = LogisticRegression(max_iter=1000, C=1.0, random_state=43)
    calibrator.fit(features, y)
    return calibrator, {"status": "fit", "method": "multinomial logistic calibration on a separate chronological calibration window", "rows": int(len(y)), "classes": list(calibrator.classes_)}


def apply_probability_calibrator(calibrator: Any | None, probabilities: np.ndarray) -> np.ndarray:
    probs = np.asarray(probabilities, dtype=float)
    if calibrator is None:
        return probs / np.maximum(probs.sum(axis=1, keepdims=True), 1e-12)
    pred = calibrator.predict_proba(np.log(np.clip(probs, 1e-6, 1.0)))
    aligned = np.full((pred.shape[0], len(CLASS_ORDER)), 1e-6, dtype=float)
    for j, cls in enumerate(calibrator.classes_):
        if cls in CLASS_ORDER:
            aligned[:, CLASS_ORDER.index(cls)] = pred[:, j]
    return aligned / aligned.sum(axis=1, keepdims=True)


def probability_metrics(y_true, probabilities: np.ndarray) -> dict[str, Any]:
    y = pd.Series(y_true).astype(str).to_numpy()
    probs = np.clip(np.asarray(probabilities, dtype=float), 1e-8, 1.0)
    probs = probs / probs.sum(axis=1, keepdims=True)
    if len(y) == 0:
        return {"rows": 0}
    actual_idx = np.array([CLASS_ORDER.index(val) if val in CLASS_ORDER else 1 for val in y])
    onehot = np.eye(len(CLASS_ORDER))[actual_idx]
    confidence = probs.max(axis=1)
    pred_idx = probs.argmax(axis=1)
    correct = (pred_idx == actual_idx).astype(float)
    ece = 0.0
    for lower in np.linspace(0, 0.9, 10):
        upper = lower + 0.1
        mask = (confidence >= lower) & (confidence < upper if upper < 1 else confidence <= upper)
        if mask.any():
            ece += float(mask.mean()) * abs(float(correct[mask].mean()) - float(confidence[mask].mean()))
    try:
        loss = float(log_loss(y, probs, labels=CLASS_ORDER))
    except Exception:
        loss = None
    brier = float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
    return {"rows": int(len(y)), "multiclass_log_loss": round(loss, 5) if loss is not None else None, "multiclass_brier_score": round(brier, 5), "top_class_expected_calibration_error": round(ece, 5), "note": "Lower is better for log loss, Brier score and ECE. Estimates are based on a small market-specific holdout and may drift."}
