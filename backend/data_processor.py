"""Build lagged features and release-date-aware targets for the FX research system."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .commodity_features import add_commodity_features, PRICE_FEATURES
from .rates_features import add_rate_features, RATE_COLUMNS
from .flows_features import add_flow_features, FLOW_COLUMNS
from .risk_features import add_risk_features, RISK_COLUMNS
from .news_features import add_event_features
from .targets import add_target, DEFAULT_HORIZONS

from .paths import MARKET_DATA_FILE as DATA_FILE


def load_price_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        raise FileNotFoundError("No market dataset yet. Click 'Fetch / refresh data' first.")
    data = pd.read_csv(DATA_FILE, parse_dates=["Date"], index_col="Date")
    data = data.sort_index()
    data = data[~data.index.duplicated(keep="last")]
    for col in data.columns:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan)
    if "USDINR" not in data.columns:
        raise ValueError("Dataset has no USDINR column. Refresh the data.")
    data = data.dropna(subset=["USDINR"])
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("Dataset date index could not be parsed.")
    return data


def make_feature_frame(prices: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """Features known by t close; target is t→t+horizon USD/INR return.

    U.S. close feeds are mapped to the next business day by the collector. Release-date CSV
    data are only available on/after their Date field. No backward filling is used.
    """
    if horizon not in DEFAULT_HORIZONS:
        raise ValueError(f"Horizon must be one of {DEFAULT_HORIZONS}.")
    data = prices.copy().sort_index()
    features: dict[str, pd.Series] = {}
    add_commodity_features(data, features)
    add_rate_features(data, features)
    add_flow_features(data, features)
    add_risk_features(data, features)
    add_event_features(data, features)

    x = pd.DataFrame(features, index=data.index).replace([np.inf, -np.inf], np.nan)
    # Keep the feature schema fixed for a given input schema. Do NOT prune columns using
    # non-null counts or variation over the entire historical frame: in an early walk-forward
    # fold, that would allow future feature availability to influence which columns exist.
    # Model pipelines fit imputers on each training window; columns empty/constant there carry
    # no learned signal in that fold, and source missingness is separately surfaced by the audit.
    labelled = add_target(data, horizon)
    x[f"target_{horizon}d"] = labelled[f"target_{horizon}d"]
    x[f"target_return_{horizon}d"] = labelled[f"target_return_{horizon}d"]
    x.attrs["horizon"] = horizon
    return x


def price_only_columns(frame: pd.DataFrame) -> list[str]:
    nonfeatures = {"target_1d", "target_5d", "target_20d", "target_return_1d", "target_return_5d", "target_return_20d"}
    return [c for c in frame.columns if c not in nonfeatures and any(c.startswith(f"{p}_") for p in PRICE_FEATURES)]


def macro_aware_columns(frame: pd.DataFrame) -> list[str]:
    nonfeatures = {"target_1d", "target_5d", "target_20d", "target_return_1d", "target_return_5d", "target_return_20d"}
    return [c for c in frame.columns if c not in nonfeatures]
