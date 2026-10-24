"""Conservative confidence labels based on out-of-sample evidence."""
from __future__ import annotations
from typing import Any
import numpy as np


def confidence_assessment(probabilities: dict[str, float], balanced_accuracy: float | None, baseline_accuracy: float | None, oos_rows: int, recent_accuracy: float | None = None) -> dict[str, Any]:
    usable = [float(v) for v in probabilities.values() if v is not None and np.isfinite(float(v))]
    top_probability = max(usable) if usable else 0.0
    margin = top_probability - sorted(usable)[-2] if len(usable) >= 2 else 0.0
    edge = (balanced_accuracy - 1/3) if balanced_accuracy is not None else None
    beats_baseline = baseline_accuracy is not None and balanced_accuracy is not None and balanced_accuracy > baseline_accuracy + 0.02
    enough_history = int(oos_rows) >= 60
    if not enough_history or not beats_baseline or top_probability < 0.45 or margin < 0.08:
        label = "NO RELIABLE SIGNAL"
        explanation = "Out-of-sample evidence, class separation, or test sample size is not strong enough to claim a reliable directional edge."
    elif top_probability >= 0.65 and margin >= 0.18 and recent_accuracy is not None and recent_accuracy > 0.5:
        label = "STRONGER MODEL SIGNAL"
        explanation = "The model shows a clearer class preference and recent out-of-sample performance is supportive; this is still not a calibrated probability or guarantee."
    else:
        label = "MODEST / UNCERTAIN SIGNAL"
        explanation = "The model has a directional preference, but uncertainty remains. Compare horizons and review data freshness and model tests."
    return {
        "label": label,
        "explanation": explanation,
        "raw_top_class_score_pct": round(top_probability * 100, 1),
        "raw_probability_margin_pct": round(margin * 100, 1),
        "oos_balanced_accuracy_pct": round(float(balanced_accuracy) * 100, 2) if balanced_accuracy is not None else None,
        "baseline_accuracy_pct": round(float(baseline_accuracy) * 100, 2) if baseline_accuracy is not None else None,
        "balanced_accuracy_minus_one_third_pct_points": round(float(edge) * 100, 2) if edge is not None else None,
        "oos_rows": int(oos_rows),
        "confidence_note": "Calibrated estimates use a separate chronological window, but market regimes can change. Confidence label is a conservative evidence screen, not a guarantee that the forecast will be correct.",
    }
