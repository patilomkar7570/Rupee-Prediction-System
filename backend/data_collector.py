"""Collect market data and align slower macro indicators without back-filling target history.

Market prices are from Yahoo Finance (unofficial). Reference-rate mode can use a local CSV or
the RBI DBIE reference-rate table through a third-party mirror. USDINR target observations are
never forward-filled; optional feature series may use explicitly documented as-of carry rules.
"""
from __future__ import annotations

from io import BytesIO, StringIO
from html.parser import HTMLParser
from urllib.parse import urljoin
import json
from typing import Final

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from .http_client import get as http_get

from .paths import (
    RUNTIME_DIR as DATA_DIR, MARKET_DATA_FILE as DATA_FILE,
    SOURCE_STATUS_FILE, MACRO_INPUT_FILE, ensure_runtime_layout,
)
from .target_source import get_target_source, load_official_reference_rates, fetch_rbi_dbie_reference_rates
from .point_in_time import effective_availability_date, audit_release_timestamps, parse_mixed_dates

# Yahoo Finance symbols. Brent is more relevant to India's imported crude benchmark than WTI.
YAHOO_SYMBOLS: Final[dict[str, str]] = {
    "USDINR": "INR=X",
    "DXY": "DX-Y.NYB",
    "BRENT": "BZ=F",
    "GOLD": "GC=F",
    "VIX": "^VIX",
    "MOVE": "^MOVE",
    "USD_CNH": "CNH=X",
    "EM_EQUITY_PROXY": "EEM",
    "WORLD_EQUITY_PROXY": "ACWI",
}
PRICE_COLUMNS = list(YAHOO_SYMBOLS)
ALL_COLUMNS: Final[list[str]] = PRICE_COLUMNS + [
    "US10Y_YIELD", "US2Y_YIELD", "FED_FUNDS_RATE", "US_CPI_YOY", "ECB_MRO_RATE", "GPR_INDEX",
    "RBI_REPO_RATE", "INDIA_10Y_BOND_YIELD", "INDIA_CPI_YOY", "FX_RESERVES_USD_BN",
    "FDI_NET_FLOWS_USD_BN", "INDIA_TRADE_BALANCE_USD_BN", "INDIA_CURRENT_ACCOUNT_USD_BN",
    "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX", "INDIA_ELECTRONICS_IMPORT_BILL_USD_BN",
    "INDIA_GOLD_IMPORT_BILL_USD_BN", "FPI_NET_FLOWS_USD_BN", "BRENT_INR_PROXY", "GOLD_INR_OZ_PROXY",
]

MACRO_COLUMNS: Final[list[str]] = [
    "RBI_REPO_RATE", "INDIA_10Y_BOND_YIELD", "INDIA_CPI_YOY", "FX_RESERVES_USD_BN",
    "FDI_NET_FLOWS_USD_BN", "INDIA_TRADE_BALANCE_USD_BN", "INDIA_CURRENT_ACCOUNT_USD_BN",
    "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX", "INDIA_ELECTRONICS_IMPORT_BILL_USD_BN",
    "INDIA_GOLD_IMPORT_BILL_USD_BN", "FPI_NET_FLOWS_USD_BN", "GPR_INDEX",
]

HEADERS: Final[dict[str, str]] = {
    "User-Agent": "RupeePredictionResearch/4.0 (local educational research app)",
    "Accept": "text/csv,application/vnd.ms-excel,application/octet-stream,*/*",
}


def _normalize_index(index: pd.Index) -> pd.DatetimeIndex:
    parsed = pd.to_datetime(index, errors="coerce", utc=True)
    return pd.DatetimeIndex(parsed.tz_convert(None).normalize())


def _extract_close(raw: pd.DataFrame, symbol: str) -> pd.Series:
    if raw.empty:
        raise ValueError(f"No observations returned for {symbol}.")
    if isinstance(raw.columns, pd.MultiIndex):
        matches = [c for c in raw.columns if any(str(part).lower() == "close" for part in c)]
        if not matches:
            raise ValueError(f"No Close column found for {symbol}.")
        series = raw[matches[0]]
        if isinstance(series, pd.DataFrame):
            series = series.iloc[:, 0]
    else:
        if "Close" not in raw.columns:
            raise ValueError(f"No Close column found for {symbol}.")
        series = raw["Close"]
    series = pd.to_numeric(series, errors="coerce").dropna()
    series.index = _normalize_index(series.index)
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series.rename(symbol)


def _http_get(url: str, timeout: int = 25) -> requests.Response:
    response = http_get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def _shift_us_close_to_next_business_day(series: pd.Series) -> pd.Series:
    """US closes arrive after the Indian cash session; make them available next business day."""
    shifted = series.copy()
    shifted.index = shifted.index + pd.offsets.BDay(1)
    return shifted[~shifted.index.duplicated(keep="last")].sort_index()


def _fetch_yahoo(name: str, ticker: str, period: str) -> pd.Series:
    raw = yf.download(
        ticker, period=period, interval="1d", auto_adjust=False,
        progress=False, threads=False, timeout=25,
    )
    out = _extract_close(raw, ticker).rename(name)
    # Yahoo's U.S. market daily candle closes after Indian equity market hours.
    if name != "USDINR":
        out = _shift_us_close_to_next_business_day(out)
    return out


def _fetch_fred(series_id: str, output_name: str, start_date: str) -> pd.Series:
    """Fetch a public FRED CSV series; no API key is required for this download."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start_date}"
    response = _http_get(url)
    frame = pd.read_csv(StringIO(response.text))
    date_col = next((c for c in frame.columns if str(c).lower() in {"observation_date", "date"}), frame.columns[0])
    value_col = series_id if series_id in frame.columns else next((c for c in frame.columns if c != date_col), None)
    if value_col is None:
        raise ValueError(f"Unexpected FRED CSV schema for {series_id}.")
    values = pd.to_numeric(frame[value_col].replace(".", np.nan), errors="coerce")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name=output_name).dropna()
    out.index = _normalize_index(out.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return _shift_us_close_to_next_business_day(out)


def _unwrap_api_value(value):
    if isinstance(value, dict):
        for key in ("value", "label", "name"):
            if key in value:
                return value[key]
    return value


def _fetch_rbi_repo(start_date: str) -> pd.Series:
    """Fetch RBI repo-rate history from the public RBIH DBIE read-only table API.

    The mirror can lag the latest RBI announcement. Users can extend/override the series in
    macro_inputs.csv with the date the rate change became effective.
    """
    table = "r151_major_monetary_policy_rates_and_reserve_requirements_bank"
    url = f"https://data-api.dbie.rbihub.in/api/tables/financial_sector/{table}/rows?limit=1000&order=asc"
    response = _http_get(url, timeout=35)
    payload = response.json()
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, dict):
        rows = payload.get("data", payload.get("results"))
    if isinstance(rows, dict):
        rows = rows.get("rows", rows.get("data", []))
    if not isinstance(rows, list) or not rows:
        raise ValueError("DBIE repo-rate endpoint returned no rows or an unexpected JSON shape.")
    records = [row for row in rows if isinstance(row, dict)]
    if not records:
        raise ValueError("DBIE repo-rate endpoint contained no tabular rows.")
    keys = list(records[0].keys())
    def norm(key):
        return str(key).strip().lower().replace("_", " ").replace("-", " ")
    date_col = next((k for k in keys if "effective" in norm(k) and "date" in norm(k)), None)
    if date_col is None:
        date_col = next((k for k in keys if "date" in norm(k) or "period" in norm(k)), None)
    repo_col = next((k for k in keys if norm(k).strip() == "repo"), None)
    if repo_col is None:
        repo_col = next((k for k in keys if "repo" in norm(k) and not any(ex in norm(k) for ex in ("reverse", "sdf", "msf", "spread"))), None)
    if date_col is None or repo_col is None:
        raise ValueError("Could not identify the effective-date or repo-rate column in DBIE table. Columns: " + ", ".join(map(str, keys)))
    frame = pd.DataFrame({
        "date": [_unwrap_api_value(row.get(date_col)) for row in records],
        "value": [_unwrap_api_value(row.get(repo_col)) for row in records],
    })
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", dayfirst=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"]).sort_values("date").drop_duplicates("date", keep="last")
    frame = frame[frame["date"] >= pd.Timestamp(start_date)]
    if frame.empty:
        raise ValueError("DBIE endpoint returned no valid repo-rate observations in the requested period.")
    out = pd.Series(frame["value"].to_numpy(), index=frame["date"], name="RBI_REPO_RATE")
    out.index = _normalize_index(out.index)
    return out[~out.index.duplicated(keep="last")].sort_index()


def _fetch_ecb_mro(start_date: str) -> pd.Series:
    """Fetch ECB main refinancing operations rate (ECB terminology, not a repo-rate label)."""
    url = (
        "https://data-api.ecb.europa.eu/service/data/"
        "FM.D.U2.EUR.4F.KR.MRR_RT.LEV"
        f"?startPeriod={start_date}&format=csvdata"
    )
    response = _http_get(url)
    frame = pd.read_csv(StringIO(response.text))
    date_col = "TIME_PERIOD" if "TIME_PERIOD" in frame.columns else next(
        (c for c in frame.columns if "TIME_PERIOD" in str(c).upper()), None
    )
    value_col = "OBS_VALUE" if "OBS_VALUE" in frame.columns else next(
        (c for c in frame.columns if "OBS_VALUE" in str(c).upper()), None
    )
    if date_col is None or value_col is None:
        raise ValueError("ECB response did not contain TIME_PERIOD and OBS_VALUE.")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame[value_col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="ECB_MRO_RATE").dropna()
    out.index = _normalize_index(out.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    # Conservative alignment: a policy announcement on a Europe date may be after India's close.
    return _shift_us_close_to_next_business_day(out)


def _fetch_gpr(start_date: str) -> pd.Series:
    """Optional Caldara-Iacoviello daily Geopolitical Risk Index download (Excel workbook).

    The research page uses date-stamped weekly workbook names. Discover the current link rather
    than assuming one filename remains valid forever, and keep a few common URLs as fallbacks.
    """
    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[str] = []
        def handle_starttag(self, tag, attrs):
            if tag.lower() == "a":
                href = dict(attrs).get("href", "")
                if href and "data_gpr_daily_recent" in href.lower() and href.lower().endswith((".xls", ".xlsx")):
                    self.links.append(href)

    urls = []
    try:
        page = _http_get("https://www.matteoiacoviello.com/gpr.htm?mod=article_inline", timeout=40)
        parser = LinkParser()
        parser.feed(page.text)
        # The first link on the page is expected to be the currently highlighted daily workbook.
        urls.extend(urljoin(page.url, link) for link in parser.links)
    except Exception:
        pass
    urls.extend([
        "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls",
        "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xlsx",
    ])
    response = None
    errors = []
    for url in dict.fromkeys(urls):
        try:
            candidate = _http_get(url, timeout=40)
            # Excel files are binary; reject a web page that returned HTTP 200 by mistake.
            if not candidate.content.startswith((b"\xd0\xcf\x11\xe0", b"PK\x03\x04")):
                if "text/html" in candidate.headers.get("content-type", "").lower():
                    raise ValueError("URL returned HTML, not an Excel workbook")
            response = candidate
            break
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:100]}")
    if response is None:
        raise RuntimeError("Could not locate the current GPR workbook. " + "; ".join(errors[:3]))
    workbook = pd.read_excel(BytesIO(response.content), sheet_name=0)
    if workbook.empty:
        raise ValueError("GPR workbook is empty.")
    workbook.columns = [str(c).strip() for c in workbook.columns]
    date_col = next((c for c in workbook.columns if "date" in c.lower()), workbook.columns[0])
    possible = [c for c in workbook.columns if "gpr" in c.lower() and not any(x in c.lower() for x in ("threat", "act", "log"))]
    if not possible:
        possible = [c for c in workbook.columns if c != date_col and pd.to_numeric(workbook[c], errors="coerce").notna().sum() > 30]
    if not possible:
        raise ValueError("Could not identify the GPR index column in the workbook.")
    # Prefer the main daily index over any labelled sub-index.
    col = sorted(possible, key=lambda c: ("gprd" not in c.lower(), "gpr" not in c.lower(), len(c)))[0]
    dates = pd.to_datetime(workbook[date_col], errors="coerce")
    values = pd.to_numeric(workbook[col], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="GPR_INDEX").dropna()
    out.index = _normalize_index(out.index)
    out = out[out.index >= pd.Timestamp(start_date)]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    # The research team notes this feed updates weekly; lag by one workweek for conservative backtests.
    out.index = out.index + pd.offsets.BDay(5)
    return out


def _read_manual_macro_inputs() -> tuple[pd.DataFrame, dict[str, object]]:
    """Read manual macro data with conservative daily availability mapping.

    \`Date\` should be the first known/effective date, not the period-end described by the value.
    When \`AvailableAt\` is populated, it is parsed in Asia/Kolkata (naive timestamps are assumed
    IST), and values released after the 17:00 IST research cutoff are made available next weekday.
    Invalid, non-empty timestamps cause that row's feature values to be excluded rather than
    silently falling back to its reference date. Rows that share an effective date are merged by
    taking the last non-missing value per feature.
    """
    ensure_runtime_layout()
    expected = ["Date", *MACRO_COLUMNS]
    if not MACRO_INPUT_FILE.exists():
        pd.DataFrame(columns=["Date", "ReferencePeriod", "AvailableAt", "Source", "Units", "Notes", *MACRO_COLUMNS]).to_csv(MACRO_INPUT_FILE, index=False)
    try:
        raw = pd.read_csv(MACRO_INPUT_FILE, dtype={"AvailableAt": "string"})
    except Exception as exc:
        return pd.DataFrame(columns=MACRO_COLUMNS, index=pd.DatetimeIndex([], name="Date")), {
            "status": "error", "rows": 0, "message": f"Could not read macro_inputs.csv: {str(exc)[:220]}"
        }
    if "Date" not in raw.columns:
        return pd.DataFrame(columns=MACRO_COLUMNS, index=pd.DatetimeIndex([], name="Date")), {
            "status": "invalid", "rows": int(len(raw)), "message": "macro_inputs.csv must contain a Date column."
        }
    for col in MACRO_COLUMNS:
        if col not in raw.columns:
            raw[col] = np.nan
    for col in MACRO_COLUMNS:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    timestamp_audit = audit_release_timestamps(raw, "Date", "AvailableAt")
    raw_dates = parse_mixed_dates(raw["Date"], dayfirst=True)
    resolved_dates: list[pd.Timestamp | pd.NaT] = []
    invalid_available_at = 0
    timestamped_rows = 0
    shifted_after_cutoff = 0
    no_timestamp_rows = 0
    for ref_date, available_at in zip(raw_dates, raw.get("AvailableAt", pd.Series([None] * len(raw)))):
        resolved, audit = effective_availability_date(ref_date, available_at)
        resolved_dates.append(resolved)
        if audit.get("status") == "invalid_available_at":
            invalid_available_at += 1
        elif audit.get("status") == "timestamped":
            timestamped_rows += 1
            shifted_after_cutoff += int(bool(audit.get("after_cutoff_shifted")))
        elif audit.get("status") == "date_only":
            no_timestamp_rows += 1
    raw["_effective_date"] = pd.to_datetime(resolved_dates, errors="coerce")
    raw["_input_order"] = np.arange(len(raw), dtype=int)
    excluded_invalid_dates = int(raw_dates.isna().sum())
    # Bad non-empty timestamps are excluded from all feature columns: using their Date as a
    # fallback could inject a value earlier than the actual release time.
    raw.loc[raw["_effective_date"].isna(), MACRO_COLUMNS] = np.nan
    usable = raw.dropna(subset=["_effective_date"]).copy()
    if usable.empty:
        return pd.DataFrame(columns=MACRO_COLUMNS, index=pd.DatetimeIndex([], name="Date")), {
            "status": "not_configured" if raw.empty else "invalid", "rows": 0,
            "timestamp_audit": timestamp_audit,
            "message": "No usable macro rows remain after checking Date and AvailableAt. Correct the CSV before using these features.",
        }
    duplicate_effective_rows = int(usable["_effective_date"].duplicated(keep=False).sum())
    usable = usable.sort_values(["_effective_date", "_input_order"], kind="mergesort").set_index("_effective_date")
    # Last non-empty source row per effective date wins; stable ordering makes this reproducible.
    # Sparse rows cannot erase a previous non-missing value for another feature.
    usable = usable[MACRO_COLUMNS].groupby(level=0, sort=True).agg(lambda series: series.dropna().iloc[-1] if series.notna().any() else np.nan)
    usable.index = pd.DatetimeIndex(usable.index, name="Date")
    return usable, {
        "status": "loaded_with_timing_review" if (invalid_available_at or no_timestamp_rows or excluded_invalid_dates) else "loaded",
        "rows": int(len(usable)),
        "input_rows": int(len(raw)),
        "effective_date_duplicates_merged": duplicate_effective_rows,
        "invalid_date_rows_excluded": excluded_invalid_dates,
        "invalid_available_at_rows_excluded": invalid_available_at,
        "timestamped_rows": timestamped_rows,
        "date_only_rows_without_available_at": no_timestamp_rows,
        "after_17_00_ist_rows_shifted_to_next_weekday": shifted_after_cutoff,
        "timestamp_audit": timestamp_audit,
        "first_date": usable.index.min().strftime("%Y-%m-%d"),
        "latest_date": usable.index.max().strftime("%Y-%m-%d"),
        "message": (
            "Date is the first known/effective date. Populated AvailableAt is interpreted in Asia/Kolkata; "
            "releases after 17:00 IST are shifted to the next weekday. "
            f"{timestamped_rows} timestamped rows, {no_timestamp_rows} Date-only rows, "
            f"{invalid_available_at} invalid timestamps excluded, {shifted_after_cutoff} after-cutoff rows shifted. "
            "This is a conservative weekday approximation, not a full historical-vintage store or exchange-holiday calendar."
        ),
    }


def _asof_reindex(series: pd.Series, calendar: pd.DatetimeIndex, max_age_days: int | None = None) -> pd.Series:
    """Carry a value to dates on/after its release date without filling earlier dates.

    Also preserves weekend/holiday releases, which a simple \`reindex(calendar)\` would drop.
    Optional max_age_days makes slowly updated trade/flow inputs expire instead of appearing fresh.
    """
    source = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    out = pd.Series(np.nan, index=calendar, dtype=float, name=series.name)
    if source.empty:
        return out
    source_dates = source.index.values.astype("datetime64[ns]")
    target_dates = calendar.values.astype("datetime64[ns]")
    locs = np.searchsorted(source_dates, target_dates, side="right") - 1
    valid = locs >= 0
    if not valid.any():
        return out
    chosen_dates = source_dates[locs[valid]]
    ages = (target_dates[valid] - chosen_dates) / np.timedelta64(1, "D")
    valid_positions = np.flatnonzero(valid)
    values = source.to_numpy(dtype=float)[locs[valid]]
    if max_age_days is not None:
        fresh = ages <= max_age_days
        valid_positions = valid_positions[fresh]
        values = values[fresh]
    out.iloc[valid_positions] = values
    return out


def _write_source_status(status: dict[str, dict[str, object]]) -> None:
    """Persist source provenance and a common timestamp for the most recent refresh attempt."""
    from datetime import datetime, timezone
    ensure_runtime_layout()
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for info in status.values():
        if isinstance(info, dict):
            info.setdefault("checked_at_utc", checked_at)
    SOURCE_STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")


def collect_market_data(period: str = "5y") -> pd.DataFrame:
    """Refresh market and macro data, save one aligned daily CSV, and return it.

    USDINR is mandatory. Other sources are best-effort and their status is exposed in the UI.
    """
    ensure_runtime_layout()
    years = 5
    try:
        if period.endswith("y"):
            years = max(1, int(period[:-1]))
    except Exception:
        years = 5
    start_date = (pd.Timestamp.now().normalize() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
    source_status: dict[str, dict[str, object]] = {}
    raw_series: dict[str, pd.Series] = {}
    target_source = get_target_source()

    for name, ticker in YAHOO_SYMBOLS.items():
        if name == "USDINR" and target_source in {"fbil_csv", "rbi_dbie_mirror"}:
            try:
                if target_source == "fbil_csv":
                    reference_series, reference_status = load_official_reference_rates(min_rows=250)
                    source_name = "Local reference-rate CSV (FBIL/RBI-derived; origin not authenticated by the app)"
                else:
                    reference_series, reference_status = fetch_rbi_dbie_reference_rates(min_rows=250)
                    source_name = "RBI DBIE reference-rate table via third-party mirror API"
                raw_series[name] = reference_series.loc[reference_series.index >= pd.Timestamp(start_date)]
                if len(raw_series[name]) < 250:
                    raise ValueError(f"Only {len(raw_series[name])} reference-rate rows fall inside the requested {period} window; provide a longer history or choose another target source.")
                source_status[name] = reference_status
                source_status[name]["source"] = str(reference_status.get("source", source_name))
                source_status[name]["message"] = str(reference_status.get("message", "")) + " Target selection is kept separate from Yahoo INR=X; no target series are blended."
            except Exception as exc:
                source_status[name] = {"status": "error", "source": "Reference-rate target source", "message": str(exc)[:450]}
            continue
        try:
            raw_series[name] = _fetch_yahoo(name, ticker, period)
            source_status[name] = {
                "status": "ok", "source": f"Yahoo Finance ({ticker})",
                "latest_date": raw_series[name].index.max().strftime("%Y-%m-%d"),
                "rows": int(raw_series[name].notna().sum()),
                "message": "Unofficial market-data source; verify critical values independently.",
            }
        except Exception as exc:
            source_status[name] = {"status": "error", "source": f"Yahoo Finance ({ticker})", "message": str(exc)[:350]}

    if "USDINR" not in raw_series or raw_series["USDINR"].dropna().empty:
        _write_source_status(source_status)
        if target_source in {"fbil_csv", "rbi_dbie_mirror"}:
            raise RuntimeError("Reference-rate target selected but no valid reference history loaded. Check runtime/source_status.json; for CSV mode, import a long history into runtime/inputs/official_usdinr_reference.csv, or restore network access for the DBIE mirror.")
        raise RuntimeError("Could not download USD/INR history from Yahoo Finance. Check internet access or import a sufficiently long reference-rate history and select reference-rate CSV mode. Details are in runtime/source_status.json.")

    try:
        raw_series["RBI_REPO_RATE"] = _fetch_rbi_repo(start_date)
        source_status["RBI_REPO_RATE"] = {
            "status": "ok", "source": "RBIH DBIE public table API (mirror/prototype)",
            "latest_date": raw_series["RBI_REPO_RATE"].index.max().strftime("%Y-%m-%d"),
            "rows": int(raw_series["RBI_REPO_RATE"].notna().sum()),
            "message": "This DBIE mirror can lag the latest RBI MPC decision; macro_inputs.csv can extend/override with the effective date.",
        }
    except Exception as exc:
        source_status["RBI_REPO_RATE"] = {"status": "error", "source": "RBIH DBIE public table API", "message": str(exc)[:350]}

    for series_id, col in (("DGS10", "US10Y_YIELD"), ("DGS2", "US2Y_YIELD"), ("DFF", "FED_FUNDS_RATE"), ("CPIAUCSL", "US_CPI_INDEX")):
        try:
            raw_series[col] = _fetch_fred(series_id, col, start_date)
            source_status[col] = {
                "status": "ok", "source": f"Federal Reserve Bank of St. Louis FRED ({series_id})",
                "latest_date": raw_series[col].index.max().strftime("%Y-%m-%d"),
                "rows": int(raw_series[col].notna().sum()),
                "message": "FRED public CSV. CPI is converted to year-over-year inflation; U.S. observations are conservatively assigned after the U.S. date.",
            }
        except Exception as exc:
            source_status[col] = {"status": "error", "source": f"FRED ({series_id})", "message": str(exc)[:350]}
    if "US_CPI_INDEX" in raw_series:
        cpi = raw_series["US_CPI_INDEX"].sort_index()
        us_cpi_yoy = cpi.pct_change(12, fill_method=None) * 100.0
        # FRED CPI observation dates refer to the month measured, not publication day.
        # Shift by 35 business days as a conservative availability approximation.
        us_cpi_yoy.index = us_cpi_yoy.index + pd.offsets.BDay(35)
        raw_series["US_CPI_YOY"] = us_cpi_yoy
        source_status["US_CPI_YOY"] = {"status": "ok", "source": "FRED CPIAUCSL derived year-over-year", "latest_date": raw_series["US_CPI_YOY"].dropna().index.max().strftime("%Y-%m-%d") if raw_series["US_CPI_YOY"].notna().any() else None, "rows": int(raw_series["US_CPI_YOY"].notna().sum()), "message": "Derived from monthly CPI index and shifted 35 business days as a conservative publication-time approximation; verify against historical release dates for rigorous tests."}

    try:
        raw_series["ECB_MRO_RATE"] = _fetch_ecb_mro(start_date)
        source_status["ECB_MRO_RATE"] = {
            "status": "ok", "source": "European Central Bank Data Portal (main refinancing operations rate)",
            "latest_date": raw_series["ECB_MRO_RATE"].index.max().strftime("%Y-%m-%d"),
            "rows": int(raw_series["ECB_MRO_RATE"].notna().sum()),
            "message": "ECB terminology is Main Refinancing Operations (MRO), not a repo rate; policy-rate channel is indirect for INR.",
        }
    except Exception as exc:
        source_status["ECB_MRO_RATE"] = {"status": "error", "source": "ECB Data Portal", "message": str(exc)[:350]}

    try:
        raw_series["GPR_INDEX"] = _fetch_gpr(start_date)
        source_status["GPR_INDEX"] = {
            "status": "ok", "source": "Caldara-Iacoviello Geopolitical Risk Index",
            "latest_date": raw_series["GPR_INDEX"].index.max().strftime("%Y-%m-%d"),
            "rows": int(raw_series["GPR_INDEX"].notna().sum()),
            "message": "Daily newspaper-based risk index; conservatively lagged five business days because the source updates weekly.",
        }
    except Exception as exc:
        source_status["GPR_INDEX"] = {
            "status": "error", "source": "Caldara-Iacoviello Geopolitical Risk Index",
            "message": (str(exc)[:280] + " Manual override can be added in macro_inputs.csv as GPR_INDEX if needed."),
        }

    # India-specific public feeds are best-effort and independent: one broken source must not
    # prevent other indicators from refreshing. Availability dates are shifted conservatively.
    try:
        from .india_macro_sources import fetch_india_macro_sources
        india_series, india_status = fetch_india_macro_sources(start_date, raw_series["USDINR"])
        for column, series in india_series.items():
            raw_series[column] = series
        source_status.update(india_status)
    except Exception as exc:
        source_status["INDIA_AUTOMATED_MACRO_CONNECTORS"] = {
            "status": "error", "source": "India public macro/capital-flow connectors",
            "message": str(exc)[:350],
        }

    manual, manual_status = _read_manual_macro_inputs()
    source_status["INDIA_MACRO_INPUTS"] = {"source": "runtime/inputs/macro_inputs.csv (manual release-date-based inputs)", **manual_status}
    try:
        from .news_features import load_event_inputs
        events = load_event_inputs()
        source_status["HISTORICAL_EVENTS"] = {"status": "loaded" if not events.empty else "not_configured", "source": "runtime/inputs/event_inputs.csv (manual event/news history)", "rows": int(len(events)), "latest_date": events["Date"].max().strftime("%Y-%m-%d") if not events.empty else None, "message": "Only timestamped historical events feed the model. Live headlines are context-only."}
    except Exception as exc:
        source_status["HISTORICAL_EVENTS"] = {"status": "error", "source": "runtime/inputs/event_inputs.csv", "message": str(exc)[:250]}
    # If the automatic RBI mirror fails, don't show the repo-rate source as wholly missing
    # when the user supplied an effective-dated manual series.
    if not manual.empty and "RBI_REPO_RATE" in manual.columns and manual["RBI_REPO_RATE"].notna().any():
        latest_manual_repo = manual["RBI_REPO_RATE"].dropna().index.max().strftime("%Y-%m-%d")
        repo_status = source_status.setdefault("RBI_REPO_RATE", {})
        auto_latest = repo_status.get("latest_date")
        if repo_status.get("status") != "ok":
            repo_status.update({
                "status": "loaded", "source": "runtime/inputs/macro_inputs.csv (manual RBI repo override)",
                "latest_date": latest_manual_repo,
                "rows": int(manual["RBI_REPO_RATE"].notna().sum()),
                "message": "Using manual effective-dated RBI repo values because the automatic DBIE mirror did not load.",
            })
        else:
            repo_status["latest_date"] = max(str(auto_latest or ""), latest_manual_repo)
            repo_status["message"] = str(repo_status.get("message", "")) + f" Manual override/extension provided through {latest_manual_repo}."

    usd = raw_series["USDINR"]
    calendar = pd.date_range(usd.index.min(), usd.index.max(), freq="B", name="Date")
    data = pd.DataFrame(index=calendar)
    # U.S. and global market daily closes are already mapped to the next Indian business date.
    for col in ALL_COLUMNS:
        data[col] = np.nan
    asof_max_age = {
        "US_CPI_YOY": 50,
        "INDIA_10Y_BOND_YIELD": 45,
        "INDIA_CPI_YOY": 60,
        "FX_RESERVES_USD_BN": 14,
        "INDIA_TRADE_BALANCE_USD_BN": 120,
        "FPI_NET_FLOWS_USD_BN": 7,
    }
    for name, series in raw_series.items():
        if name in data.columns:
            if name == "US_CPI_INDEX":
                # Keep the underlying index out of the daily model table; only YoY inflation is used.
                continue
            elif name == "USDINR":
                # CRITICAL: target observations are never forward-filled. Doing so invents
                # exchange-rate observations on holidays/missing dates and changes the meaning
                # of a 1/5/20-session horizon. Only actual target observations may define rows.
                data[name] = pd.to_numeric(series, errors="coerce").reindex(calendar)
            elif name in asof_max_age:
                data[name] = _asof_reindex(series, calendar, max_age_days=asof_max_age[name])
            else:
                data[name] = series.reindex(calendar).ffill(limit=3)
    # Low-frequency levels carry forward only after first observation; they never backfill history.
    for col in ("RBI_REPO_RATE", "ECB_MRO_RATE", "FED_FUNDS_RATE"):
        if col in data:
            data[col] = data[col].ffill()
    if not manual.empty:
        manual = manual[~manual.index.duplicated(keep="last")].sort_index()
        data_age = {
            "RBI_REPO_RATE": None, "INDIA_10Y_BOND_YIELD": 100, "INDIA_CPI_YOY": 100,
            "FX_RESERVES_USD_BN": 50, "FDI_NET_FLOWS_USD_BN": 100,
            "INDIA_TRADE_BALANCE_USD_BN": 100, "INDIA_CURRENT_ACCOUNT_USD_BN": 150,
            "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX": 100,
            "INDIA_ELECTRONICS_IMPORT_BILL_USD_BN": 100, "INDIA_GOLD_IMPORT_BILL_USD_BN": 100,
            "FPI_NET_FLOWS_USD_BN": 45, "GPR_INDEX": 15,
        }
        for col in MACRO_COLUMNS:
            if col not in manual:
                continue
            manual_series = _asof_reindex(manual[col], calendar, max_age_days=data_age.get(col))
            # Explicit manual values take precedence after their release date; blank manual
            # cells do not erase an available automatic series.
            data[col] = manual_series.combine_first(data[col])
    # Manual rows override automatic feeds where present; no manual value is propagated backward.

    # Local-currency cost proxies: a flat USD commodity can still become costlier in INR.
    data["BRENT_INR_PROXY"] = data["BRENT"] * data["USDINR"]
    data["GOLD_INR_OZ_PROXY"] = data["GOLD"] * data["USDINR"]
    data.index.name = "Date"
    data = data.replace([np.inf, -np.inf], np.nan)
    data = data.dropna(subset=["USDINR"])
    data.to_csv(DATA_FILE, date_format="%Y-%m-%d", float_format="%.8f")
    auto_keys = ("INDIA_10Y_BOND_YIELD", "INDIA_CPI_YOY", "FX_RESERVES_USD_BN", "INDIA_TRADE_BALANCE_USD_BN", "FPI_NET_FLOWS_USD_BN")
    auto_returned = sum(1 for key in auto_keys if source_status.get(key, {}).get("status") in {"ok", "stale"})
    auto_fresh = sum(1 for key in auto_keys if source_status.get(key, {}).get("status") == "ok")
    source_status["EXTERNAL_SECTOR_INPUTS"] = {
        "status": "loaded" if auto_fresh == len(auto_keys) else "partial",
        "source": "Best-effort public feeds plus runtime/inputs/macro_inputs.csv",
        "feeds_returned": auto_returned,
        "feeds_fresh": auto_fresh,
        "message": f"{auto_returned}/{len(auto_keys)} automated India macro/capital-flow feeds returned data; {auto_fresh} are within the configured freshness warning threshold. Manual release-dated values remain available for gaps, FDI, current account and import-cost series. Per-feed statuses above explain errors and freshness limits.",
    }
    _write_source_status(source_status)
    return data


def get_source_status() -> dict[str, dict[str, object]]:
    if not SOURCE_STATUS_FILE.exists():
        return {"status": {"status": "not_fetched", "message": "Click Fetch / Refresh Data to test and load sources."}}
    try:
        payload = json.loads(SOURCE_STATUS_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
