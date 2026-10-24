"""Simple, leakage-aware baselines used in time-ordered evaluation."""
from __future__ import annotations
from collections import Counter
from typing import Any
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score

LABELS = ["DOWN", "FLAT", "UP"]


def majority_prediction(y_train: pd.Series, n: int) -> list[str]:
    if len(y_train) == 0:
        return ["FLAT"] * n
    counts = y_train.astype(str).value_counts()
    return [str(counts.index[0])] * n


def random_walk_direction(n: int) -> list[str]:
    # Random-walk level forecast: tomorrow's level equals today's, mapped to FLAT target.
    return ["FLAT"] * n


def metric_pack(y_true, y_pred) -> dict[str, Any]:
    y_true = pd.Series(y_true).astype(str)
    y_pred = pd.Series(y_pred).astype(str)
    return {
        "accuracy_pct": round(float(accuracy_score(y_true, y_pred)) * 100, 2),
        "balanced_accuracy_pct": round(float(balanced_accuracy_score(y_true, y_pred)) * 100, 2),
        "macro_f1_pct": round(float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)) * 100, 2),
        "rows": int(len(y_true)),
    }
