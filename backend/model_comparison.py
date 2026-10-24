"""Model definitions and common metrics for fair, chronological comparison."""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd
import warnings
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, confusion_matrix
from .baselines import LABELS, majority_prediction, random_walk_direction
from .data_processor import price_only_columns


def model_factories() -> dict[str, Any]:
    return {
        "Market-price Logistic": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=600, C=0.35, class_weight="balanced", random_state=42)),
        ]),
        "Macro Logistic": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=600, C=0.25, class_weight="balanced", random_state=42)),
        ]),
        "Macro Random Forest": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", RandomForestClassifier(n_estimators=80, max_depth=6, min_samples_leaf=10, max_features="sqrt", class_weight="balanced_subsample", random_state=42, n_jobs=1)),
        ]),
        "Macro Gradient Boosting": lambda: Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", GradientBoostingClassifier(n_estimators=25, learning_rate=0.04, max_depth=1, min_samples_leaf=12, subsample=0.8, random_state=42)),
        ]),
    }


def evaluation_features(frame: pd.DataFrame, model_name: str) -> list[str]:
    excluded = {c for c in frame.columns if c.startswith("target_")}
    features = [c for c in frame.columns if c not in excluded]
    if model_name == "Market-price Logistic":
        price = set(price_only_columns(frame))
        features = [c for c in features if c in price]
    return features


def calculate_metrics(y_true, y_pred) -> dict[str, Any]:
    y_true = pd.Series(y_true).astype(str)
    y_pred = pd.Series(y_pred).astype(str)
    cm = confusion_matrix(y_true, y_pred, labels=LABELS).tolist()
    with warnings.catch_warnings():
        # Small regime-specific subgroups can lack a true class. The returned class-coverage
        # fields make that limitation visible without flooding the user's console with a warning.
        warnings.filterwarnings("ignore", message="y_pred contains classes not in y_true", category=UserWarning)
        bal_acc = balanced_accuracy_score(y_true, y_pred) if len(y_true) else None
    observed = sorted(set(y_true.tolist()))
    missing = [label for label in LABELS if label not in observed]
    return {
        "accuracy_pct": round(float(accuracy_score(y_true, y_pred)) * 100, 2) if len(y_true) else None,
        "balanced_accuracy_pct": round(float(bal_acc) * 100, 2) if bal_acc is not None else None,
        "macro_f1_pct": round(float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)) * 100, 2) if len(y_true) else None,
        "rows": int(len(y_true)), "true_classes_observed": observed,
        "missing_true_classes": missing,
        "metric_note": "Some target classes are absent from this sample; metrics for small samples/regimes may be unstable." if missing else None,
        "confusion_matrix": {"labels": LABELS, "values": cm},
    }


def train_latest_model(frame: pd.DataFrame, horizon: int = 1, model_name: str = "Macro Random Forest") -> tuple[Any, list[str], pd.DataFrame]:
    target_col = f"target_{horizon}d"
    target_return_col = f"target_return_{horizon}d"
    labelled = frame.dropna(subset=[target_col, target_return_col]).copy()
    xcols = evaluation_features(frame, model_name)
    labelled = labelled[labelled[target_col].astype(str).isin(LABELS)]
    if len(labelled) < 200:
        raise ValueError(f"Only {len(labelled)} labelled rows remain for {horizon}-day forecasting; at least 200 are recommended.")
    model = model_factories()[model_name]()
    model.fit(labelled[xcols], labelled[target_col].astype(str))
    return model, xcols, labelled


def latest_feature_importance(model: Any, feature_cols: list[str], top_n: int = 15) -> list[dict[str, Any]]:
    try:
        core = model.named_steps["model"]
        values = getattr(core, "feature_importances_", None)
        if values is None and hasattr(core, "coef_"):
            coef = np.asarray(core.coef_, dtype=float)
            values = np.mean(np.abs(coef), axis=0) if coef.ndim > 1 else np.abs(coef)
        if values is None:
            return []
        pairs = list(zip(feature_cols, np.asarray(values).ravel()))
        total = sum(float(v) for _, v in pairs)
        if total > 0:
            pairs = [(name, float(value) / total) for name, value in pairs]
        ranked = sorted(pairs, key=lambda pair: float(pair[1]), reverse=True)[:top_n]
        return [{"feature": name, "importance": round(float(value), 5), "caveat": "Model importance is predictive association, not causal impact."} for name, value in ranked]
    except Exception:
        return []
