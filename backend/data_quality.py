"""Auditable data-quality and point-in-time readiness checks.

Checks flag issues for review; they never silently delete or alter raw market values.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from .paths import MARKET_DATA_FILE, SOURCE_STATUS_FILE

# Latest observation ages allowed before a feed is highlighted. For policy rates, an old
# effective date may remain economically current; these limits differ from daily market feeds.
FRESHNESS_LIMITS_DAYS: dict[str, int] = {
    "USDINR": 7, "DXY": 7, "BRENT": 7, "GOLD": 7, "VIX": 7, "MOVE": 7,
    "USD_CNH": 7, "EM_EQUITY_PROXY": 7, "WORLD_EQUITY_PROXY": 7,
    "US10Y_YIELD": 7, "US2Y_YIELD": 7, "FED_FUNDS_RATE": 20,
    "US_CPI_YOY": 75, "INDIA_CPI_YOY": 90, "INDIA_10Y_BOND_YIELD": 45,
    "FX_RESERVES_USD_BN": 30, "INDIA_TRADE_BALANCE_USD_BN": 150,
    "INDIA_CURRENT_ACCOUNT_USD_BN": 180, "FPI_NET_FLOWS_USD_BN": 20,
    "FDI_NET_FLOWS_USD_BN": 180, "RBI_REPO_RATE": 365, "ECB_MRO_RATE": 365,
    "GPR_INDEX": 20,
}


def read_source_status(path: Path = SOURCE_STATUS_FILE) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def _date_age(value: Any, today: pd.Timestamp) -> int | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return None
    date = pd.Timestamp(parsed).tz_convert(None).normalize()
    return int((today - date).days)


def _raw_file_integrity(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"available": path.exists(), "duplicate_date_rows": 0, "invalid_dates": 0, "read_error": None}
    if not path.exists():
        return result
    try:
        raw = pd.read_csv(path, usecols=lambda col: col in {"Date", "USDINR"})
        if "Date" in raw:
            parsed = pd.to_datetime(raw["Date"], errors="coerce")
            result["invalid_dates"] = int(parsed.isna().sum())
            result["duplicate_date_rows"] = int(parsed.duplicated(keep=False).sum())
        if "USDINR" in raw:
            rates = pd.to_numeric(raw["USDINR"], errors="coerce")
            result["invalid_or_nonpositive_rates"] = int((rates.isna() | (rates <= 0)).sum())
    except Exception as exc:
        result["read_error"] = str(exc)[:240]
    return result


def audit_market_data(
    prices: pd.DataFrame,
    source_status: dict[str, Any] | None = None,
    target_source: str = "unknown",
    raw_data_file: Path = MARKET_DATA_FILE,
    now: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Return data health, source freshness, and point-in-time readiness findings."""
    now = now or pd.Timestamp.now(tz="UTC")
    today = pd.Timestamp(now).tz_convert("UTC").tz_localize(None).normalize() if pd.Timestamp(now).tzinfo else pd.Timestamp(now).normalize()
    status = source_status if source_status is not None else read_source_status()
    frame = prices.copy().sort_index() if prices is not None else pd.DataFrame()
    integrity = _raw_file_integrity(Path(raw_data_file))
    issues: list[dict[str, str]] = []
    source_rows: list[dict[str, Any]] = []
    point_in_time_flags: list[dict[str, str]] = []

    if frame.empty:
        issues.append({"severity": "critical", "code": "NO_DATA", "message": "No usable target history is loaded. Fetch / refresh data before forecasting."})
    else:
        if "USDINR" not in frame.columns:
            issues.append({"severity": "critical", "code": "TARGET_COLUMN_MISSING", "message": "The aligned dataset does not contain USDINR."})
        else:
            rate = pd.to_numeric(frame["USDINR"], errors="coerce")
            bad = int((~np.isfinite(rate) | (rate <= 0)).sum())
            if bad:
                issues.append({"severity": "critical", "code": "INVALID_TARGET_VALUES", "message": f"{bad} target-rate rows are non-finite or non-positive."})
            latest = pd.Timestamp(frame.index.max()).normalize()
            age = int((today - latest).days)
            if age < -1:
                issues.append({"severity": "critical", "code": "FUTURE_TARGET_DATE", "message": f"Latest target row is {abs(age)} calendar days ahead of the current date; verify source timestamps and timezone handling."})
            if age > FRESHNESS_LIMITS_DAYS["USDINR"]:
                issues.append({"severity": "high", "code": "TARGET_STALE", "message": f"Latest target row is {age} calendar days old; verify holidays and feed health."})
            if len(frame) < 400:
                issues.append({"severity": "high", "code": "SHORT_HISTORY", "message": f"Only {len(frame)} target observations are available; multi-stage evaluation is unstable below roughly 400 rows."})
            # Large changes are flagged, never winsorized or removed.
            returns = rate.pct_change(fill_method=None)
            jumps = returns[returns.abs() >= 0.03]
            for date, value in jumps.tail(10).items():
                issues.append({"severity": "review", "code": "LARGE_TARGET_MOVE", "message": f"Review target move {float(value)*100:.2f}% on {pd.Timestamp(date).strftime('%Y-%m-%d')}; valid stress moves are retained."})
            gaps: list[dict[str, Any]] = []
            dates = pd.DatetimeIndex(frame.index).sort_values()
            for prev, curr in zip(dates[:-1], dates[1:]):
                gap_days = int((pd.Timestamp(curr) - pd.Timestamp(prev)).days)
                if gap_days > 5:
                    gaps.append({"from": pd.Timestamp(prev).strftime("%Y-%m-%d"), "to": pd.Timestamp(curr).strftime("%Y-%m-%d"), "calendar_days": gap_days})
            if gaps:
                issues.append({"severity": "review", "code": "LONG_DATE_GAPS", "message": f"Found {len(gaps)} gaps longer than five calendar days. Some may be holidays; verify against the relevant exchange calendar."})

        missing = []
        tail = frame.tail(180)
        for col in frame.columns:
            if col == "USDINR":
                continue
            values = pd.to_numeric(tail[col], errors="coerce")
            pct = float(values.isna().mean() * 100) if len(values) else 100.0
            if pct >= 40:
                missing.append({"column": col, "missing_pct_last_180": round(pct, 1), "available_rows_last_180": int(values.notna().sum())})
        missing.sort(key=lambda row: row["missing_pct_last_180"], reverse=True)
        if missing:
            issues.append({"severity": "review", "code": "SPARSE_FEATURES", "message": f"{len(missing)} feature columns have at least 40% missing values in the last 180 rows. Models may be using imputation; review the feature report."})
    if integrity.get("duplicate_date_rows", 0):
        issues.append({"severity": "high", "code": "RAW_DUPLICATE_DATES", "message": f"Raw market file contains {integrity['duplicate_date_rows']} rows on duplicated dates; loader deduplication can hide them from the modelling frame."})
    if integrity.get("invalid_dates", 0):
        issues.append({"severity": "high", "code": "RAW_INVALID_DATES", "message": f"Raw market file contains {integrity['invalid_dates']} invalid date values."})
    if integrity.get("invalid_or_nonpositive_rates", 0):
        issues.append({"severity": "critical", "code": "RAW_INVALID_RATES", "message": f"Raw file contains {integrity['invalid_or_nonpositive_rates']} invalid or non-positive USD/INR values."})

    now_utc = pd.Timestamp(now)
    now_utc = now_utc.tz_localize("UTC") if now_utc.tzinfo is None else now_utc.tz_convert("UTC")
    for name, info in sorted(status.items()):
        if not isinstance(info, dict):
            continue
        age = _date_age(info.get("latest_date"), today)
        checked_at = pd.to_datetime(info.get("checked_at_utc"), errors="coerce", utc=True)
        checked_age_hours = round(max(0.0, (now_utc - checked_at).total_seconds() / 3600.0), 1) if pd.notna(checked_at) else None
        limit = FRESHNESS_LIMITS_DAYS.get(name)
        state = str(info.get("status", "unknown")).lower()
        freshness = "not_assessed"
        if checked_age_hours is not None and checked_age_hours > 72 and state not in {"error", "not_fetched", "not_configured", "invalid"}:
            issues.append({"severity": "review", "code": "SOURCE_REFRESH_OVERDUE", "message": f"{name} was last checked {checked_age_hours:.1f} hours ago. Refresh data before relying on current source status."})
        if state in {"error", "not_fetched", "not_configured", "invalid"}:
            freshness = "unavailable" if state in {"error", "invalid"} else "not_configured"
        elif age is not None and limit is not None:
            freshness = "fresh" if age <= limit else "stale"
            if freshness == "stale":
                issues.append({"severity": "review", "code": "SOURCE_STALE", "message": f"{name} latest date is {age} days old (configured review threshold: {limit} days)."})
        source_rows.append({"name": name, "status": state, "checked_at_utc": info.get("checked_at_utc"), "checked_age_hours": checked_age_hours, "latest_date": info.get("latest_date"), "age_days": age, "freshness_limit_days": limit, "freshness": freshness, "rows": info.get("rows"), "source": info.get("source"), "message": info.get("message", "")})
        message = str(info.get("message", "")).lower()
        if any(term in message for term in ("approximation", "approximate", "publication-time", "availability", "mirror", "lagged", "proxy", "revised")):
            point_in_time_flags.append({"source": name, "severity": "review", "message": "Source metadata mentions proxy/lag/availability limitations. Check its timing and vintage before treating historical tests as point-in-time clean."})
        if state == "error":
            point_in_time_flags.append({"source": name, "severity": "review", "message": "Feed failed during latest refresh; ensure missing features are not being mistaken for a complete input set."})

    if target_source == "yahoo_proxy":
        point_in_time_flags.append({"source": "USDINR target", "severity": "review", "message": "Yahoo INR=X is a convenient proxy, not a verified official reference-rate series or executable dealer quote."})
    point_in_time_flags.append({"source": "Feature availability", "severity": "review", "message": "The aligned project does not yet maintain a complete vintage store for every macro series. Historical results remain experimental even when timestamps are supplied."})
    point_in_time_flags = list({(x["source"], x["message"]): x for x in point_in_time_flags}.values())
    high = sum(x["severity"] in {"critical", "high"} for x in issues)
    if high:
        release_gate = "BLOCKED"
    elif issues or point_in_time_flags:
        release_gate = "REVIEW REQUIRED"
    else:
        release_gate = "DATA CHECKS CLEAR — TIMING STILL REQUIRES SOURCE-SPECIFIC REVIEW"
    now_iso = pd.Timestamp(now).isoformat()
    missing_cols = [] if frame.empty else missing
    return {
        "generated_at": now_iso,
        "target_source": target_source,
        "release_gate": release_gate,
        "observations": int(len(frame)),
        "start_date": pd.Timestamp(frame.index.min()).strftime("%Y-%m-%d") if not frame.empty else None,
        "end_date": pd.Timestamp(frame.index.max()).strftime("%Y-%m-%d") if not frame.empty else None,
        "target_age_days": int((today - pd.Timestamp(frame.index.max()).normalize()).days) if not frame.empty else None,
        "raw_file_integrity": integrity,
        "source_health": source_rows,
        "missing_features_last_180": missing_cols,
        "issues": issues,
        "point_in_time_review_flags": point_in_time_flags,
        "interpretation": "Quality checks flag risks for review; they do not certify source accuracy, repair data, or establish predictive skill. Market jumps are retained and only flagged.",
    }
