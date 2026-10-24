"""Forecast target definitions for multiple USD/INR horizons."""
from __future__ import annotations
import numpy as np
import pandas as pd

DEFAULT_HORIZONS = (1, 5, 20)


def threshold_for_horizon(horizon: int) -> float:
    """Dead-zone threshold in returns; scales gently with horizon to reduce noise."""
    return 0.0005 * float(np.sqrt(max(1, int(horizon))))


def add_target(prices: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    if horizon not in DEFAULT_HORIZONS:
        raise ValueError(f"Horizon must be one of {DEFAULT_HORIZONS}.")
    out = prices.copy()
    future = out["USDINR"].shift(-horizon)
    target_return = future / out["USDINR"] - 1.0
    threshold = threshold_for_horizon(horizon)
    target = pd.Series("FLAT", index=out.index, dtype="object")
    target.loc[target_return > threshold] = "UP"
    target.loc[target_return < -threshold] = "DOWN"
    target.loc[future.isna()] = np.nan
    out[f"target_return_{horizon}d"] = target_return
    out[f"target_{horizon}d"] = target
    return out
