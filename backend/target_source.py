"""Explicit USD/INR target-source selection and strict reference-rate importers."""
from __future__ import annotations

import json
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .http_client import get as http_get
from .point_in_time import parse_mixed_dates
from .paths import (
    OFFICIAL_REFERENCE_RATE_FILE,
    TARGET_SOURCE_CONFIG_FILE,
    RUNTIME_DIR,
    ensure_runtime_layout,
)

ALLOWED_TARGET_SOURCES = {"yahoo_proxy", "fbil_csv", "rbi_dbie_mirror"}
RBI_DBIE_TABLE = "financial_markets.r691_daily_interbank_forex_rates_usd_vis_a_vis_inr"
RBI_DBIE_API = "https://data-api.dbie.rbihub.in/api/tables"
RBI_DBIE_TABLE_PAGE = f"https://dbie.rbihub.in/tables?table={RBI_DBIE_TABLE}"
RBI_DBIE_CACHE_FILE = RUNTIME_DIR / "inputs" / "rbi_dbie_reference_cache.csv"


def get_target_source() -> str:
    """Environment setting overrides the local persisted UI selection."""
    ensure_runtime_layout()
    override = os.environ.get("RPS_USDINR_TARGET_SOURCE", "").strip().lower()
    if override:
        return override if override in ALLOWED_TARGET_SOURCES else "yahoo_proxy"
    try:
        payload = json.loads(TARGET_SOURCE_CONFIG_FILE.read_text(encoding="utf-8"))
        value = str(payload.get("target_source", "yahoo_proxy")).strip().lower()
        return value if value in ALLOWED_TARGET_SOURCES else "yahoo_proxy"
    except Exception:
        return "yahoo_proxy"


def set_target_source(value: str) -> dict[str, Any]:
    value = str(value).strip().lower()
    if value not in ALLOWED_TARGET_SOURCES:
        raise ValueError(f"Target source must be one of: {', '.join(sorted(ALLOWED_TARGET_SOURCES))}.")
    ensure_runtime_layout()
    TARGET_SOURCE_CONFIG_FILE.write_text(json.dumps({"target_source": value}, indent=2) + "\n", encoding="utf-8")
    return {"target_source": value, "saved": True, "restart_required": False, "refresh_required": True}


def _normal(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _date_col(frame: pd.DataFrame) -> str:
    preferred = ("date", "period", "observationdate", "referencedate", "rate date", "time period")
    normalized = {_normal(c): c for c in frame.columns}
    for target in preferred:
        n = _normal(target)
        if n in normalized:
            return normalized[n]
    for col in frame.columns:
        n = _normal(col)
        if "date" in n or n == "period":
            values = parse_mixed_dates(frame[col], dayfirst=True)
            if values.notna().sum() >= max(3, int(len(frame) * .5)):
                return str(col)
    raise ValueError(f"Could not identify a date column. Available columns: {', '.join(map(str, frame.columns))[:350]}")


def _rate_col(frame: pd.DataFrame) -> str:
    normalized = {_normal(c): c for c in frame.columns}
    for key in ("usdinr", "rbireferencerate", "fbilreferencerate", "usdinrreferencerate", "referencerateusdinr"):
        if key in normalized:
            return normalized[key]
    candidates = []
    for col in frame.columns:
        n = _normal(col)
        if "reference" in n and "rate" in n and ("rbi" in n or "fbil" in n or "usd" in n or "inr" in n):
            candidates.append(col)
    if len(candidates) == 1:
        return str(candidates[0])
    # Never mistake interbank open/high/low/close for the reference rate.
    raise ValueError(
        "Could not identify USD/INR reference-rate column. Expected `USDINR`, `RBI Reference Rate`, "
        "`FBIL Reference Rate`, or a clearly labelled USD/INR reference-rate column. "
        f"Available columns: {', '.join(map(str, frame.columns))[:450]}"
    )


def normalize_reference_rate_frame(
    frame: pd.DataFrame,
    *,
    min_rows: int = 250,
    source_label: str = "User-supplied reference-rate CSV (not independently authenticated)",
) -> tuple[pd.Series, dict[str, Any], pd.DataFrame]:
    """Normalize a reference-rate CSV without silently deduplicating ambiguous observations.

    Accepts the project's Date/USDINR template and common RBI DBIE wide-table CSV headers.
    Invalid or blank rows are measured and reported; duplicate usable dates fail closed.
    """
    if frame is None or frame.empty:
        raise ValueError("Reference-rate CSV is empty.")
    date_col = _date_col(frame)
    rate_col = _rate_col(frame)
    raw_date = frame[date_col]
    dates = parse_mixed_dates(raw_date, dayfirst=True)
    values_raw = frame[rate_col].astype(str).str.strip().str.replace(",", "", regex=False)
    values = pd.to_numeric(values_raw.replace({"": np.nan, "-": np.nan, "–": np.nan, "—": np.nan, ".": np.nan, "nan": np.nan, "None": np.nan}), errors="coerce")
    date_nonempty = raw_date.notna() & raw_date.astype(str).str.strip().ne("")
    invalid_date_rows = int((date_nonempty & dates.isna()).sum())
    dated_rows = dates.notna()
    invalid_rate_rows = int((dated_rows & (values.isna() | ~np.isfinite(values) | (values <= 0))).sum())
    usable = dated_rows & values.notna() & np.isfinite(values) & (values > 0) & (values <= 250)
    rejected_out_of_range = int((dated_rows & values.notna() & ((values <= 0) | (values > 250))).sum())
    clean = pd.DataFrame({"Date": pd.DatetimeIndex(dates[usable]).normalize(), "USDINR": values[usable].astype(float).to_numpy()})
    if clean.empty:
        raise ValueError(f"No valid positive USD/INR observations were found in {date_col!r}/{rate_col!r}.")
    duplicates = clean.loc[clean["Date"].duplicated(keep=False), "Date"].dt.strftime("%Y-%m-%d").unique().tolist()
    if duplicates:
        examples = ", ".join(duplicates[:8])
        raise ValueError(f"Reference-rate CSV has duplicate dates ({len(duplicates)} duplicate-date values; examples: {examples}). Resolve duplicates before importing; the loader will not silently choose one.")
    if len(clean) < min_rows:
        raise ValueError(f"Reference-rate CSV contains {len(clean)} valid rows; at least {min_rows} are required.")
    if invalid_rate_rows / max(1, int(dated_rows.sum())) > 0.02:
        raise ValueError(f"Reference-rate CSV has {invalid_rate_rows} invalid rate values among dated rows (>2%). Fix or document the source file before importing.")
    clean = clean.sort_values("Date").reset_index(drop=True)
    clean["Source"] = source_label
    # Preserve source publication metadata when supplied. Blank means unknown, not inferred.
    if "AvailableAt" in frame.columns:
        available_lookup = pd.DataFrame({"Date": pd.DatetimeIndex(dates[usable]).normalize(), "AvailableAt": frame.loc[usable, "AvailableAt"].astype(str).to_numpy()})
        clean = clean.merge(available_lookup, on="Date", how="left", validate="one_to_one")
    else:
        clean["AvailableAt"] = ""
    date_index = pd.DatetimeIndex(clean["Date"], name="Date")
    series = pd.Series(clean["USDINR"].to_numpy(dtype=float), index=date_index, name="USDINR")

    available_count = 0
    invalid_available_count = 0
    median_lag = None
    if "AvailableAt" in frame.columns:
        available_raw = frame.loc[usable, "AvailableAt"]
        available = pd.to_datetime(available_raw, errors="coerce", utc=True)
        nonempty = available_raw.notna() & available_raw.astype(str).str.strip().ne("")
        available_count = int((available.notna() & nonempty).sum())
        invalid_available_count = int((available.isna() & nonempty).sum())
        if available.notna().any():
            rate_dates_utc = pd.to_datetime(clean["Date"], errors="coerce", utc=True)
            lags = (available.reset_index(drop=True) - rate_dates_utc).dt.total_seconds() / 86400.0
            finite = lags[np.isfinite(lags)]
            median_lag = round(float(finite.median()), 3) if len(finite) else None
    row_total = int(len(frame))
    warning_parts = []
    if invalid_date_rows:
        warning_parts.append(f"{invalid_date_rows} non-empty date cells could not be parsed")
    if invalid_rate_rows:
        warning_parts.append(f"{invalid_rate_rows} dated rows have missing/invalid rates")
    if rejected_out_of_range:
        warning_parts.append(f"{rejected_out_of_range} rates are outside the guardrail (0, 250]")
    if invalid_available_count:
        warning_parts.append(f"{invalid_available_count} AvailableAt timestamps could not be parsed")
    info = {
        "status": "ok_with_warnings" if warning_parts else "ok",
        "source": source_label,
        "source_column": str(rate_col),
        "date_column": str(date_col),
        "latest_date": series.index.max().strftime("%Y-%m-%d"),
        "first_date": series.index.min().strftime("%Y-%m-%d"),
        "rows": int(len(series)),
        "raw_rows": row_total,
        "invalid_date_rows_dropped": invalid_date_rows,
        "invalid_rate_rows_dropped": invalid_rate_rows,
        "out_of_range_rate_rows_dropped": rejected_out_of_range,
        "available_at_rows": available_count,
        "available_at_invalid_rows": invalid_available_count,
        "available_at_lag_median_days": median_lag,
        "warnings": warning_parts,
        "message": (
            "Rates were imported without blending another target definition. "
            "This importer checks format and numerical integrity but cannot authenticate the file or prove that its publication timestamps/vintages are correct. "
            + ("Review: " + "; ".join(warning_parts) + "." if warning_parts else "No structural warning was detected.")
        ),
    }
    return series, info, clean


def load_official_reference_rates(min_rows: int = 250) -> tuple[pd.Series, dict[str, Any]]:
    """Load a user-supplied FBIL/RBI-derived CSV; provider origin is not authenticated."""
    ensure_runtime_layout()
    if not OFFICIAL_REFERENCE_RATE_FILE.exists():
        raise FileNotFoundError(
            f"Reference-rate mode is selected, but {OFFICIAL_REFERENCE_RATE_FILE} is missing. "
            "Import a sufficiently long reference-rate history using the CSV template."
        )
    try:
        frame = pd.read_csv(OFFICIAL_REFERENCE_RATE_FILE)
    except Exception as exc:
        raise ValueError(f"Could not read reference-rate CSV: {exc}") from exc
    # A Source column is provenance supplied by the file owner, not authentication.
    source_label = "User-supplied reference-rate CSV (not independently authenticated)"
    if "Source" in frame.columns:
        provided = frame["Source"].dropna().astype(str).str.strip()
        provided = provided[provided.ne("")]
        if not provided.empty:
            unique = provided.unique().tolist()
            source_label = f"User-supplied reference-rate CSV; Source field: {unique[0]}" + (f" (multiple labels: {len(unique)})" if len(unique) > 1 else "")
    series, info, _ = normalize_reference_rate_frame(frame, min_rows=min_rows, source_label=source_label)
    return series, info


def fetch_rbi_dbie_reference_rates(min_rows: int = 250) -> tuple[pd.Series, dict[str, Any]]:
    """Fetch the RBI DBIE reference-rate table through its publicly documented mirror API.

    The API documents itself as a mirror/scrape, not a direct RBI-controlled live feed. If the
    network fetch fails, a previously saved snapshot may be returned but is explicitly labelled
    as cached/stale; the caller's regular freshness gate can then block stale forecasts.
    """
    ensure_runtime_layout()
    schema, table = RBI_DBIE_TABLE.split(".", 1)
    url = f"{RBI_DBIE_API}/{schema}/{table}/csv"
    fetch_error: str | None = None
    try:
        response = http_get(url, headers={"Accept": "text/csv,*/*"}, timeout=45)
        response.raise_for_status()
        frame = pd.read_csv(StringIO(response.text))
        series, info, normalized = normalize_reference_rate_frame(
            frame,
            min_rows=min_rows,
            source_label="RBI DBIE reference-rate table via third-party mirror API (verify against RBI/FBIL primary publication)",
        )
        archived = normalized[["Date", "USDINR", "Source", "AvailableAt"]].copy()
        temp = RBI_DBIE_CACHE_FILE.with_suffix(".csv.tmp")
        RBI_DBIE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        archived.to_csv(temp, index=False, date_format="%Y-%m-%d")
        temp.replace(RBI_DBIE_CACHE_FILE)
        from datetime import datetime, timezone
        info.update({
            "status": "ok_with_warnings",
            "source": "RBI DBIE historical table via third-party mirror API",
            "source_url": RBI_DBIE_TABLE_PAGE,
            "api_url": url,
            "mirror_snapshot_fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "message": str(info.get("message", "")) + " DBIE mirror data may lag or reflect the mirror's last scrape; compare latest values with RBI/FBIL primary publications. Historical publication timestamps are not supplied by this table.",
        })
        return series, info
    except Exception as exc:
        fetch_error = str(exc)[:260]

    if RBI_DBIE_CACHE_FILE.exists():
        try:
            cached = pd.read_csv(RBI_DBIE_CACHE_FILE)
            series, info, _ = normalize_reference_rate_frame(
                cached, min_rows=min_rows,
                source_label="Cached RBI DBIE mirror snapshot (network refresh failed; not a live rate feed)",
            )
            info.update({
                "status": "stale_cache",
                "source": "Cached RBI DBIE mirror snapshot",
                "source_url": RBI_DBIE_TABLE_PAGE,
                "message": f"Live DBIE mirror refresh failed ({fetch_error}); using saved local snapshot from {RBI_DBIE_CACHE_FILE.name}. Check target date freshness before use.",
            })
            return series, info
        except Exception as cache_exc:
            raise RuntimeError(f"DBIE mirror fetch failed ({fetch_error}) and cached snapshot could not be read ({str(cache_exc)[:160]}).") from cache_exc
    raise RuntimeError(f"Could not fetch RBI DBIE reference-rate table through the public mirror API: {fetch_error}. You can import an independently downloaded FBIL/RBI DBIE CSV instead.")


def get_rbi_dbie_cache_status() -> dict[str, Any]:
    if not RBI_DBIE_CACHE_FILE.exists():
        return {"status": "not_configured", "rows": 0, "message": "No DBIE mirror snapshot has been downloaded yet."}
    try:
        _, info = _load_cache(min_rows=1)
        info["cache_path"] = str(RBI_DBIE_CACHE_FILE)
        info["status"] = "cached_not_refreshed"
        return info
    except Exception as exc:
        return {"status": "invalid", "rows": 0, "message": str(exc)[:240]}


def _load_cache(min_rows: int = 1) -> tuple[pd.Series, dict[str, Any]]:
    frame = pd.read_csv(RBI_DBIE_CACHE_FILE)
    return normalize_reference_rate_frame(frame, min_rows=min_rows, source_label="Cached RBI DBIE mirror snapshot")[:2]
