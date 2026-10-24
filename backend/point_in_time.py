"""Point-in-time timestamp helpers for release-dated macro inputs.

The project uses daily observations and assumes a forecast is issued after the Indian
cash-market close. A release timestamp after 17:00 Asia/Kolkata is conservatively made
available on the next weekday. This is a weekday approximation, not an official exchange
holiday calendar; strict studies should map releases to the actual target-session calendar.
"""
from __future__ import annotations

from datetime import time
from typing import Any

import pandas as pd

INDIA_TZ = "Asia/Kolkata"
FORECAST_CUTOFF_IST = time(17, 0)


def parse_mixed_dates(values: Any, *, dayfirst: bool = True) -> pd.Series:
    """Parse mixed ISO/day-first source formats without globally flipping ISO dates.

    `format="mixed"` is available in the project's minimum pandas version and avoids the
    inconsistent strict single-format inference introduced by newer pandas releases.
    """
    return pd.to_datetime(values, errors="coerce", format="mixed", dayfirst=dayfirst)


def _to_india_timestamp(value: Any) -> pd.Timestamp | None:
    """Parse a timestamp and convert/localize it to India time; return None if invalid."""
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    stamp = parse_mixed_dates(pd.Series([value]), dayfirst=True).iloc[0]
    if pd.isna(stamp):
        return None
    stamp = pd.Timestamp(stamp)
    if stamp.tzinfo is None:
        # CSVs are user-entered in India and commonly contain naive local timestamps.
        stamp = stamp.tz_localize(INDIA_TZ, ambiguous="NaT", nonexistent="shift_forward")
    else:
        stamp = stamp.tz_convert(INDIA_TZ)
    if pd.isna(stamp):
        return None
    return stamp


def effective_availability_date(
    reference_date: Any,
    available_at: Any = None,
    *,
    cutoff: time = FORECAST_CUTOFF_IST,
) -> tuple[pd.Timestamp | pd.NaT, dict[str, Any]]:
    """Return the earliest daily row where a release is eligible to be used.

    `reference_date` is the observation's documented first public/effective date. If
    `available_at` is provided, it must parse as a timestamp; its India-local date is used,
    and releases after the daily cutoff are shifted to the next weekday. The later of those
    two dates wins. Missing timestamps preserve reference-date behavior but remain unaudited.
    """
    ref = parse_mixed_dates(pd.Series([reference_date]), dayfirst=True).iloc[0]
    if pd.isna(ref):
        return pd.NaT, {"status": "invalid_reference_date", "timestamp_used": False}
    ref_date = pd.Timestamp(ref).tz_localize(None).normalize() if pd.Timestamp(ref).tzinfo else pd.Timestamp(ref).normalize()
    if available_at is None or pd.isna(available_at) or str(available_at).strip() == "":
        return ref_date, {"status": "date_only", "timestamp_used": False}

    stamp = _to_india_timestamp(available_at)
    if stamp is None:
        return pd.NaT, {"status": "invalid_available_at", "timestamp_used": True}

    available_date = stamp.tz_localize(None).normalize()
    local_clock = stamp.timetz().replace(tzinfo=None)
    shifted = local_clock > cutoff
    if shifted:
        available_date = (available_date + pd.offsets.BDay(1)).normalize()
    eligible = max(ref_date, available_date)
    return eligible, {
        "status": "timestamped",
        "timestamp_used": True,
        "available_at_ist": stamp.isoformat(),
        "after_cutoff_shifted": bool(shifted),
        "reference_date": ref_date.strftime("%Y-%m-%d"),
        "effective_date": eligible.strftime("%Y-%m-%d"),
    }


def audit_release_timestamps(frame: pd.DataFrame, reference_col: str = "Date", available_col: str = "AvailableAt") -> dict[str, Any]:
    """Summarize the timestamp completeness/quality of a manual release-dated CSV."""
    if reference_col not in frame.columns:
        return {"status": "invalid", "rows": int(len(frame)), "message": f"Missing required {reference_col!r} column."}
    total = int(len(frame))
    if total == 0:
        return {"status": "not_configured", "rows": 0, "timestamp_rows": 0, "coverage_pct": 0.0}
    ref_valid = parse_mixed_dates(frame[reference_col], dayfirst=True).notna()
    if available_col not in frame.columns:
        return {
            "status": "date_only", "rows": total, "valid_reference_dates": int(ref_valid.sum()),
            "timestamp_rows": 0, "invalid_timestamp_rows": 0, "coverage_pct": 0.0,
            "message": "No AvailableAt column was provided; Date-only alignment is used and historical release times are not independently verified.",
        }
    nonempty = frame[available_col].notna() & frame[available_col].astype(str).str.strip().ne("")
    parsed = frame[available_col].map(_to_india_timestamp)
    invalid = nonempty & parsed.isna()
    valid_stamps = int((nonempty & parsed.notna()).sum())
    coverage = round(100 * valid_stamps / max(1, int(ref_valid.sum())), 2)
    return {
        "status": "ok" if not invalid.any() else "review_required",
        "rows": total,
        "valid_reference_dates": int(ref_valid.sum()),
        "timestamp_rows": valid_stamps,
        "invalid_timestamp_rows": int(invalid.sum()),
        "coverage_pct": coverage,
        "cutoff_ist": cutoff_string(FORECAST_CUTOFF_IST),
        "message": (
            "AvailableAt timestamps are interpreted in Asia/Kolkata when timezone-naive; releases after the 17:00 IST cutoff are shifted to the next weekday. "
            "This does not replace source-specific vintage history or a real exchange holiday calendar."
        ),
    }


def cutoff_string(value: time) -> str:
    return value.strftime("%H:%M IST")
