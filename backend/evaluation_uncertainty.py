"""Moving-block bootstrap intervals for dependent time-series forecast errors.

These are descriptive uncertainty intervals. They do not adjust for model-selection
multiplicity, target revisions, or all possible dependence caused by overlapping horizons.
"""
from __future__ import annotations
from typing import Callable, Any
import warnings
import numpy as np
from sklearn.metrics import balanced_accuracy_score, mean_absolute_error


def moving_block_indices(n: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
    """Resample contiguous blocks to preserve short-range time dependence."""
    if n <= 0:
        return np.array([], dtype=int)
    block_size = max(1, min(int(block_size), n))
    pieces: list[np.ndarray] = []
    total = 0
    max_start = max(1, n - block_size + 1)
    while total < n:
        start = int(rng.integers(0, max_start))
        block = np.arange(start, min(start + block_size, n), dtype=int)
        pieces.append(block)
        total += len(block)
    return np.concatenate(pieces)[:n]


def _interval(values: list[float], confidence: float = 0.95) -> dict[str, Any]:
    finite = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if finite.size < 30:
        return {"lower": None, "upper": None, "confidence_level_pct": round(confidence * 100, 1), "bootstrap_replicates": int(finite.size), "status": "insufficient_replicates"}
    alpha = 1.0 - confidence
    return {
        "lower": round(float(np.quantile(finite, alpha / 2)), 4),
        "upper": round(float(np.quantile(finite, 1 - alpha / 2)), 4),
        "confidence_level_pct": round(confidence * 100, 1),
        "bootstrap_replicates": int(finite.size),
        "status": "estimated",
    }


def balanced_accuracy_interval(y_true, y_pred, block_size: int, n_bootstrap: int = 300, seed: int = 42) -> dict[str, Any]:
    """95% moving-block bootstrap interval for balanced accuracy, in percentage points."""
    truth = np.asarray(y_true, dtype=object)
    pred = np.asarray(y_pred, dtype=object)
    if truth.size != pred.size or truth.size < 60:
        return {"lower_pct": None, "upper_pct": None, "status": "insufficient_rows", "rows": int(min(truth.size, pred.size))}
    rng = np.random.default_rng(seed)
    values: list[float] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(max(100, int(n_bootstrap))):
            ix = moving_block_indices(len(truth), block_size, rng)
            if len(set(truth[ix].tolist())) < 2:
                continue
            values.append(float(balanced_accuracy_score(truth[ix], pred[ix])) * 100.0)
    band = _interval(values)
    return {"lower_pct": band["lower"], "upper_pct": band["upper"], "confidence_level_pct": band["confidence_level_pct"], "bootstrap_replicates": band["bootstrap_replicates"], "status": band["status"], "rows": int(len(truth)), "method": "moving-block bootstrap; descriptive, not multiplicity-adjusted"}


def mae_skill_interval(actual, predicted, baseline, block_size: int, n_bootstrap: int = 300, seed: int = 42) -> dict[str, Any]:
    """Paired 95% moving-block bootstrap interval for MAE skill vs baseline (%).

    Skill is 100 * (1 - MAE(model) / MAE(baseline)); positive values favour the model.
    Candidate and baseline forecasts are resampled at exactly the same timestamps.
    """
    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    b = np.asarray(baseline, dtype=float)
    if y.size != p.size or y.size != b.size:
        return {"lower_pct": None, "upper_pct": None, "status": "unaligned_rows"}
    mask = np.isfinite(y) & np.isfinite(p) & np.isfinite(b)
    y, p, b = y[mask], p[mask], b[mask]
    n = len(y)
    if n < max(60, block_size * 4):
        return {"lower_pct": None, "upper_pct": None, "status": "insufficient_rows", "rows": n, "block_size": int(block_size)}
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(max(100, int(n_bootstrap))):
        ix = moving_block_indices(n, block_size, rng)
        base_mae = float(mean_absolute_error(y[ix], b[ix]))
        if base_mae <= 1e-12:
            continue
        model_mae = float(mean_absolute_error(y[ix], p[ix]))
        values.append((1.0 - model_mae / base_mae) * 100.0)
    band = _interval(values)
    if band["lower"] is None:
        return {"lower_pct": None, "upper_pct": None, "status": band["status"], "rows": n, "block_size": int(block_size)}
    lower, upper = float(band["lower"]), float(band["upper"])
    if lower > 0:
        interpretation = "The estimated 95% interval is above zero; this sample supports lower MAE than the random-walk baseline, subject to stated limitations."
    elif upper < 0:
        interpretation = "The estimated 95% interval is below zero; the model appears worse than the random-walk baseline in this sample."
    else:
        interpretation = "The estimated 95% interval includes zero; this evaluation does not establish MAE improvement over the baseline."
    return {
        "lower_pct": round(lower, 4), "upper_pct": round(upper, 4),
        "confidence_level_pct": band["confidence_level_pct"], "bootstrap_replicates": band["bootstrap_replicates"],
        "status": band["status"], "rows": n, "block_size": int(block_size),
        "interpretation": interpretation,
        "method": "paired moving-block bootstrap on matched forecast origins; exploratory and not multiplicity-adjusted",
    }


def balanced_accuracy_difference_interval(y_true, model_pred, baseline_pred, block_size: int, n_bootstrap: int = 300, seed: int = 73) -> dict[str, Any]:
    """Paired moving-block bootstrap CI for model minus baseline balanced accuracy (pp)."""
    truth = np.asarray(y_true, dtype=object)
    model = np.asarray(model_pred, dtype=object)
    baseline = np.asarray(baseline_pred, dtype=object)
    if truth.size != model.size or truth.size != baseline.size:
        return {"lower_pp": None, "upper_pp": None, "status": "unaligned_rows"}
    n = len(truth)
    if n < max(60, block_size * 4):
        return {"lower_pp": None, "upper_pp": None, "status": "insufficient_rows", "rows": n}
    rng = np.random.default_rng(seed)
    values: list[float] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(max(100, int(n_bootstrap))):
            ix = moving_block_indices(n, block_size, rng)
            if len(set(truth[ix].tolist())) < 2:
                continue
            score_model = float(balanced_accuracy_score(truth[ix], model[ix]))
            score_baseline = float(balanced_accuracy_score(truth[ix], baseline[ix]))
            values.append((score_model - score_baseline) * 100.0)
    band = _interval(values)
    if band["lower"] is None:
        return {"lower_pp": None, "upper_pp": None, "status": band["status"], "rows": n}
    lower, upper = float(band["lower"]), float(band["upper"])
    interpretation = "The interval is above zero in this sample." if lower > 0 else "The interval is below zero in this sample." if upper < 0 else "The interval includes zero; improvement over this baseline is not established."
    return {"lower_pp": round(lower, 4), "upper_pp": round(upper, 4), "confidence_level_pct": band["confidence_level_pct"], "bootstrap_replicates": band["bootstrap_replicates"], "status": band["status"], "rows": n, "block_size": int(block_size), "interpretation": interpretation, "method": "paired moving-block bootstrap; exploratory and not multiplicity-adjusted"}
