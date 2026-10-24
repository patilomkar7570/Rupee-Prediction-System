"""External-sector and capital-flow features using signed-safe arithmetic."""
from __future__ import annotations
import pandas as pd

FLOW_COLUMNS = [
    "INDIA_ELECTRONICS_IMPORT_BILL_USD_BN", "INDIA_GOLD_IMPORT_BILL_USD_BN",
    "FPI_NET_FLOWS_USD_BN", "FDI_NET_FLOWS_USD_BN", "FX_RESERVES_USD_BN",
    "INDIA_TRADE_BALANCE_USD_BN", "INDIA_CURRENT_ACCOUNT_USD_BN",
]


def add_flow_features(data: pd.DataFrame, features: dict[str, pd.Series]) -> None:
    for col in FLOW_COLUMNS:
        if col not in data:
            continue
        s = pd.to_numeric(data[col], errors="coerce")
        features[f"{col}_level"] = s
        # Differences, not percentage changes, are used for potentially negative/near-zero flows.
        for lag in (5, 20, 60):
            features[f"{col}_difference_{lag}"] = s.diff(lag)
        features[f"{col}_rolling_mean_20"] = s.rolling(20, min_periods=3).mean()
        features[f"{col}_rolling_mean_60"] = s.rolling(60, min_periods=5).mean()
    if "FPI_NET_FLOWS_USD_BN" in data:
        fpi = pd.to_numeric(data["FPI_NET_FLOWS_USD_BN"], errors="coerce")
        features["FPI_INFLOWS_20D_SUM"] = fpi.rolling(20, min_periods=1).sum()
        features["FPI_OUTFLOW_FLAG"] = (fpi < 0).astype(float).where(fpi.notna())
    if "FX_RESERVES_USD_BN" in data:
        reserves = pd.to_numeric(data["FX_RESERVES_USD_BN"], errors="coerce")
        features["FX_RESERVES_20D_CHANGE"] = reserves.diff(20)
        features["FX_RESERVES_60D_CHANGE"] = reserves.diff(60)
