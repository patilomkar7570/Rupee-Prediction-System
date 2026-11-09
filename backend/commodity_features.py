"""Commodity/market feature engineering. Price-derived proxies are marked separately."""
from __future__ import annotations
import numpy as np
import pandas as pd

PRICE_FEATURES = {
    "USDINR", "DXY", "BRENT", "GOLD", "VIX", "MOVE", "USD_CNH",
    "EM_EQUITY_PROXY", "WORLD_EQUITY_PROXY",
}


def add_commodity_features(data: pd.DataFrame, features: dict[str, pd.Series]) -> None:
    for col in PRICE_FEATURES:
        if col not in data:
            continue
        s = pd.to_numeric(data[col], errors="coerce")
        ret = s.pct_change(fill_method=None)
        for lag in (0, 1, 2, 5, 10, 20):
            features[f"{col}_return_lag{lag}"] = ret.shift(lag)
        for window in (5, 10, 20, 60):
            features[f"{col}_momentum_{window}"] = s.pct_change(window, fill_method=None)
            features[f"{col}_volatility_{window}"] = ret.rolling(window, min_periods=max(3, window // 2)).std()
            ma = s.rolling(window, min_periods=max(3, window // 2)).mean()
            features[f"{col}_vs_ma{window}"] = s / ma - 1.0
        # A shock measures today's return against a trailing volatility estimate; never uses future data.
        baseline_vol = ret.rolling(60, min_periods=20).std().shift(1)
        features[f"{col}_shock_z"] = (ret / baseline_vol.replace(0, np.nan)).clip(-8, 8)
    # Technical mean-reversion & boundary indicators for USDINR (capturing RBI intervention bands)
    if "USDINR" in data:
        usdinr = pd.to_numeric(data["USDINR"], errors="coerce")
        delta = usdinr.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14, min_periods=7).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14, min_periods=7).mean()
        rs = gain / loss.replace(0, np.nan)
        features["USDINR_RSI_14"] = (100.0 - (100.0 / (1.0 + rs))).clip(0, 100)
        ma20 = usdinr.rolling(20, min_periods=10).mean()
        sd20 = usdinr.rolling(20, min_periods=10).std()
        features["USDINR_BB_PCTB"] = ((usdinr - (ma20 - 2 * sd20)) / (4 * sd20.replace(0, np.nan))).clip(-2, 3)
        ema5 = usdinr.ewm(span=5, adjust=False).mean()
        ema20 = usdinr.ewm(span=20, adjust=False).mean()
        features["USDINR_EMA_RATIO_5_20"] = (ema5 / ema20.replace(0, np.nan) - 1.0).clip(-0.1, 0.1)
    # The India electronics import-price index is a release-dated macro series, not a
    # market quote. Keep its features in the macro model but out of the market-price baseline.
    col = "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX"
    if col in data:
        s = pd.to_numeric(data[col], errors="coerce")
        if s.notna().sum() > 0:
            ret = s.pct_change(fill_method=None)
            features[f"{col}_level"] = s
            for lag in (1, 5, 20, 60):
                features[f"{col}_change_lag{lag}"] = s.diff(lag)
            for window in (5, 20, 60):
                features[f"{col}_momentum_{window}"] = s.pct_change(window, fill_method=None)
                features[f"{col}_volatility_{window}"] = ret.rolling(window, min_periods=max(3, window // 2)).std()
