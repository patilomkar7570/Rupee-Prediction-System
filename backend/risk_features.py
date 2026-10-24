"""Global risk regime identification and features."""
from __future__ import annotations
import math
from typing import Any
import numpy as np
import pandas as pd

RISK_COLUMNS = ["VIX", "MOVE", "USD_CNH", "EM_EQUITY_PROXY", "WORLD_EQUITY_PROXY", "GPR_INDEX"]


def add_risk_features(data: pd.DataFrame, features: dict[str, pd.Series]) -> None:
    for col in RISK_COLUMNS:
        if col not in data:
            continue
        s = pd.to_numeric(data[col], errors="coerce")
        features[f"{col}_level"] = s
        features[f"{col}_change_5"] = s.diff(5)
        features[f"{col}_change_20"] = s.diff(20)
        features[f"{col}_momentum_20"] = s.pct_change(20, fill_method=None)
        ma = s.rolling(60, min_periods=20).mean()
        sd = s.rolling(60, min_periods=20).std()
        features[f"{col}_zscore_60"] = (s - ma) / sd.replace(0, np.nan)


def detect_regime(prices: pd.DataFrame) -> dict[str, Any]:
    if prices.empty or "USDINR" not in prices:
        return {"label": "UNKNOWN", "description": "No market data loaded.", "volatility_20d_pct": None, "risk_signals": []}
    fx_ret = pd.to_numeric(prices["USDINR"], errors="coerce").pct_change(fill_method=None).dropna()
    vol = float(fx_ret.tail(20).std() * np.sqrt(252) * 100) if len(fx_ret.tail(20)) >= 5 else None
    hist_vol = fx_ret.rolling(60, min_periods=20).std() * np.sqrt(252) * 100
    current_hist_vol = hist_vol.dropna()
    percentile = float((current_hist_vol <= vol).mean()) if vol is not None and len(current_hist_vol) else None
    vix = float(prices["VIX"].dropna().iloc[-1]) if "VIX" in prices and prices["VIX"].notna().any() else None
    move = float(prices["MOVE"].dropna().iloc[-1]) if "MOVE" in prices and prices["MOVE"].notna().any() else None
    dxy_up = bool(prices["DXY"].dropna().pct_change(20).iloc[-1] > 0.015) if "DXY" in prices and prices["DXY"].dropna().shape[0] > 21 else False
    brent_up = bool(prices["BRENT"].dropna().pct_change(20).iloc[-1] > 0.08) if "BRENT" in prices and prices["BRENT"].dropna().shape[0] > 21 else False
    signals = []
    if vix is not None and vix >= 25: signals.append("VIX elevated (>=25)")
    if move is not None and move >= 130: signals.append("MOVE elevated (>=130; heuristic threshold)")
    if dxy_up: signals.append("DXY up more than 1.5% over about 20 observations")
    if brent_up: signals.append("Brent up more than 8% over about 20 observations")
    if percentile is not None and percentile >= 0.8:
        label, desc = "HIGH VOLATILITY", "Recent USD/INR volatility is high versus its trailing history; model uncertainty can be elevated."
    elif (vix is not None and vix >= 25) or (move is not None and move >= 130) or (dxy_up and brent_up):
        label, desc = "RISK-OFF / SHOCK WATCH", "One or more global stress proxies are elevated. This is a heuristic regime label, not a live geopolitical verdict."
    elif percentile is not None and percentile <= 0.35 and (vix is None or vix < 22):
        label, desc = "RELATIVELY CALM", "Recent USD/INR volatility is toward the lower part of its trailing range. Calm regimes can still see surprise moves."
    else:
        label, desc = "MIXED", "Available proxies do not identify a strong high-risk or calm regime."
    return {"label": label, "description": desc, "volatility_20d_pct": round(vol, 3) if vol is not None and math.isfinite(vol) else None, "historical_vol_percentile": round(percentile * 100, 1) if percentile is not None else None, "vix": vix, "move": move, "risk_signals": signals}



def detect_historical_regimes(prices: pd.DataFrame) -> pd.Series:
    """Assign a regime using only same-day and trailing values, suitable for OOS stratification."""
    idx = prices.index
    fx_ret = pd.to_numeric(prices["USDINR"], errors="coerce").pct_change(fill_method=None)
    vol20 = fx_ret.rolling(20, min_periods=10).std() * np.sqrt(252) * 100
    vol_rank = vol20.rolling(252, min_periods=60).apply(lambda a: float(np.mean(a[:-1] <= a[-1])) if len(a) > 1 else 0.5, raw=True)
    vix = pd.to_numeric(prices["VIX"], errors="coerce") if "VIX" in prices else pd.Series(np.nan, index=idx)
    dxy = pd.to_numeric(prices["DXY"], errors="coerce") if "DXY" in prices else pd.Series(np.nan, index=idx)
    brent = pd.to_numeric(prices["BRENT"], errors="coerce") if "BRENT" in prices else pd.Series(np.nan, index=idx)
    dxy_move = dxy.pct_change(20, fill_method=None)
    brent_move = brent.pct_change(20, fill_method=None)
    labels = pd.Series("MIXED", index=idx, dtype="object")
    high_vol = vol_rank >= 0.80
    risk_off = (vix >= 25) | ((dxy_move > 0.015) & (brent_move > 0.08))
    calm = (vol_rank <= 0.35) & ((vix < 22) | vix.isna())
    labels.loc[calm] = "RELATIVELY CALM"
    labels.loc[risk_off] = "RISK-OFF / SHOCK WATCH"
    labels.loc[high_vol] = "HIGH VOLATILITY"
    return labels


def detect_feature_drift(prices: pd.DataFrame) -> dict[str, Any]:
    """Simple rolling distribution-shift monitor for selected market returns/volatility."""
    candidates = [c for c in ["USDINR", "DXY", "BRENT", "GOLD", "VIX", "US10Y_YIELD"] if c in prices.columns]
    findings = []
    for col in candidates:
        values = pd.to_numeric(prices[col], errors="coerce")
        if col in {"USDINR", "DXY", "BRENT", "GOLD"}:
            values = values.pct_change(fill_method=None)
        values = values.dropna()
        if len(values) < 180:
            continue
        recent = values.tail(40)
        reference = values.iloc[:-40].tail(252)
        mean, sd = float(reference.mean()), float(reference.std())
        z = (float(recent.mean()) - mean) / sd if np.isfinite(sd) and sd > 1e-10 else 0.0
        ref_vol = float(reference.std())
        recent_vol = float(recent.std())
        ratio = recent_vol / ref_vol if ref_vol > 1e-10 else 1.0
        if abs(z) >= 2.0 or ratio >= 2.0 or ratio <= 0.5:
            findings.append({"series": col, "mean_shift_z": round(z, 2), "recent_to_reference_volatility_ratio": round(ratio, 2), "status": "WATCH"})
    return {
        "label": "DRIFT WATCH" if findings else ("NO LARGE SHIFT DETECTED" if candidates else "INSUFFICIENT DATA"),
        "signals": findings,
        "method": "Heuristic comparison of latest 40 observations with trailing reference history; it is a warning indicator, not a formal drift test.",
    }
