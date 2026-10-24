"""Policy rates, yield differentials and inflation-adjusted rate features."""
from __future__ import annotations
import pandas as pd

RATE_COLUMNS = [
    "US10Y_YIELD", "US2Y_YIELD", "RBI_REPO_RATE", "ECB_MRO_RATE", "FED_FUNDS_RATE",
    "INDIA_10Y_BOND_YIELD", "INDIA_CPI_YOY", "US_CPI_YOY",
]


def add_rate_features(data: pd.DataFrame, features: dict[str, pd.Series]) -> None:
    for col in RATE_COLUMNS:
        if col not in data:
            continue
        s = pd.to_numeric(data[col], errors="coerce")
        features[f"{col}_level"] = s
        for lag in (1, 5, 20, 60):
            features[f"{col}_change_lag{lag}"] = s.diff(lag)
    if {"RBI_REPO_RATE", "FED_FUNDS_RATE"}.issubset(data.columns):
        features["POLICY_SPREAD_IN_MINUS_US"] = data["RBI_REPO_RATE"] - data["FED_FUNDS_RATE"]
        features["POLICY_SPREAD_CHANGE_20"] = features["POLICY_SPREAD_IN_MINUS_US"].diff(20)
    if {"INDIA_10Y_BOND_YIELD", "US10Y_YIELD"}.issubset(data.columns):
        features["BOND_SPREAD_IN_MINUS_US"] = data["INDIA_10Y_BOND_YIELD"] - data["US10Y_YIELD"]
        features["BOND_SPREAD_CHANGE_20"] = features["BOND_SPREAD_IN_MINUS_US"].diff(20)
    if {"RBI_REPO_RATE", "INDIA_CPI_YOY"}.issubset(data.columns):
        features["INDIA_APPROX_REAL_POLICY_RATE"] = data["RBI_REPO_RATE"] - data["INDIA_CPI_YOY"]
    if {"FED_FUNDS_RATE", "US_CPI_YOY"}.issubset(data.columns):
        features["US_APPROX_REAL_POLICY_RATE"] = data["FED_FUNDS_RATE"] - data["US_CPI_YOY"]
    if {"INDIA_APPROX_REAL_POLICY_RATE", "US_APPROX_REAL_POLICY_RATE"}.issubset(features):
        features["REAL_POLICY_SPREAD_IN_MINUS_US"] = features["INDIA_APPROX_REAL_POLICY_RATE"] - features["US_APPROX_REAL_POLICY_RATE"]
