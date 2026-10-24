"""Best-effort India macro and capital-flow connectors for RPS v4.1.0.

Sources are public feeds, not a guarantee of current/complete/official real-time data.
Publication dates are approximated conservatively when the source only exposes observation dates.
The connector fails closed: malformed schemas are reported as source errors, never guessed silently.
"""
from __future__ import annotations

from html.parser import HTMLParser
from io import StringIO
from typing import Any
import re

import numpy as np
import pandas as pd
import requests

from .http_client import get as http_get

HEADERS = {
    "User-Agent": "RupeePredictionResearch/4.1.0 (local educational research app)",
    "Accept": "text/html,text/csv,application/json,application/vnd.ms-excel,*/*",
}
DBIE_API = "https://data-api.dbie.rbihub.in/api/tables"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CDSL_FPI_ARCHIVE_URL = "https://www.cdslindia.com/Publications/ArchiveDataAfter2009.aspx"
CDSL_FPI_MONTH_URL = "https://www.cdslindia.com/eservices/publications/FIIMonthly"


def _get(url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> requests.Response:
    response = http_get(url, headers=headers or HEADERS, timeout=timeout)
    response.raise_for_status()
    return response


def _normal(text: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _cell_value(value: object) -> object:
    """Unwrap DBIE mirror cell objects without assuming their exact wrapper schema."""
    if isinstance(value, dict):
        for key in ("value", "raw_value", "label", "name"):
            if key in value and value[key] is not None:
                return value[key]
    return value


def _to_numeric(series: pd.Series) -> pd.Series:
    cleaned = series.map(_cell_value).astype(str).str.strip().str.replace(",", "", regex=False)
    cleaned = cleaned.replace({"": np.nan, "-": np.nan, "–": np.nan, "—": np.nan, ".": np.nan, "nan": np.nan, "None": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def _json_rows(payload: Any) -> list[dict[str, Any]]:
    """Accept documented/current DBIE response wrappers without assuming one spelling."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "data", "results", "records", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _json_rows(value)
            if nested:
                return nested
    return []


def _dbie_rows(table_id: str, start_date: str) -> pd.DataFrame:
    schema, table = table_id.split(".", 1)
    url = f"{DBIE_API}/{schema}/{table}/rows"
    errors: list[str] = []
    # Some table deployments don't accept a date filter. Try it first, then retry without it.
    for params in (
        {"limit": 2000, "order": "asc", "labels": 1, "from": start_date},
        {"limit": 2000, "order": "asc", "labels": 1},
    ):
        try:
            response = http_get(url, params=params, headers=HEADERS, timeout=40)
            response.raise_for_status()
            rows = _json_rows(response.json())
            frame = pd.DataFrame(rows)
            if not frame.empty:
                return frame
            errors.append("API returned no tabular rows")
        except Exception as exc:
            errors.append(str(exc)[:160])
    raise RuntimeError(f"DBIE table {table_id} could not be read: {'; '.join(errors)}")


def _find_date_column(frame: pd.DataFrame) -> str | None:
    priorities = ("week ended", "date", "period", "time period", "month ended", "observation date")
    names = list(frame.columns)
    for needle in priorities:
        for col in names:
            norm = _normal(col)
            if needle in norm and not norm in {"year", "financial year"}:
                values = pd.to_datetime(frame[col].map(_cell_value), errors="coerce", dayfirst=True)
                if values.notna().sum() >= max(1, min(3, len(frame))):
                    return col
    # A less-labelled but parseable date field is acceptable only if the majority parse.
    for col in names:
        if any(word in _normal(col) for word in ("year", "month", "value", "unit", "item", "measure", "label", "trade", "balance", "export", "import", "reserve", "yield", "flow", "inflation")):
            continue
        values = pd.to_datetime(frame[col].map(_cell_value), errors="coerce", dayfirst=True)
        if values.notna().sum() >= max(3, int(len(frame) * 0.5)):
            return col
    return None


def _period_dates(frame: pd.DataFrame) -> pd.Series:
    """Normalize DBIE observation dates, including rows represented by FY + month."""
    date_col = _find_date_column(frame)
    if date_col:
        parsed = pd.to_datetime(frame[date_col].map(_cell_value), errors="coerce", dayfirst=True)
        return pd.Series(parsed, index=frame.index)
    names = {_normal(c): c for c in frame.columns}
    year_col = next((c for n, c in names.items() if n in {"year", "financial year", "year financial year"} or n.startswith("year ")), None)
    month_col = next((c for n, c in names.items() if n in {"month", "month name"}), None)
    if year_col and month_col:
        months = {name.lower(): number for number, name in enumerate(("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), start=1)}
        dates = []
        for year_raw, month_raw in zip(frame[year_col].map(_cell_value), frame[month_col].map(_cell_value)):
            year_match = re.search(r"(19|20)\d{2}", str(year_raw))
            month_text = str(month_raw).strip().lower()
            month = months.get(month_text.title().lower())
            if not year_match or not month:
                dates.append(pd.NaT)
                continue
            year = int(year_match.group(0))
            # Values labelled FY YYYY-YY are dated to their calendar month.
            if re.search(r"\d{4}\s*[-/–]\s*\d{2,4}", str(year_raw)) and month <= 3:
                year += 1
            dates.append(pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0))
        return pd.Series(pd.to_datetime(dates), index=frame.index)
    raise ValueError("No usable observation date/period column found in DBIE response.")


def _choose_value_column(frame: pd.DataFrame, include: tuple[str, ...], exclude: tuple[str, ...] = ()) -> str:
    """Choose a numeric column by semantic labels; do not pick a value by position alone."""
    scored: list[tuple[int, str]] = []
    for col in frame.columns:
        norm = _normal(col)
        if any(word in norm for word in exclude):
            continue
        score = sum(3 for word in include if word in norm)
        if score and _to_numeric(frame[col]).notna().sum() >= max(1, min(3, len(frame))):
            # Prefer richer labels such as total reserves + US dollar + millions.
            scored.append((score, str(col)))
    if scored:
        return sorted(scored, key=lambda item: (item[0], len(item[1])), reverse=True)[0][1]
    # Long-format table fallback: filter a descriptive dimension and use a column literally called value.
    desc_cols = [c for c in frame.columns if any(x in _normal(c) for x in ("item", "series", "indicator", "measure", "description", "unit"))]
    value_col = next((c for c in frame.columns if _normal(c) in {"value", "obs value", "observation value"}), None)
    if value_col and desc_cols:
        row_descriptions = frame[desc_cols].apply(lambda col: col.map(_cell_value)).astype(str).apply(lambda row: " ".join(_normal(v) for v in row), axis=1)
        mask = row_descriptions.map(lambda text: all(word in text for word in include))
        candidate = frame.loc[mask]
        if len(candidate) >= 1 and _to_numeric(candidate[value_col]).notna().any():
            # Return the value column and let caller filter matching descriptions below.
            return value_col
    raise ValueError(f"Could not identify a numeric source column for labels {include}. Columns: {', '.join(map(str, frame.columns))[:500]}")


def _filter_long_rows(frame: pd.DataFrame, include: tuple[str, ...], value_col: str) -> pd.DataFrame:
    norm_cols = {_normal(c): c for c in frame.columns}
    if _normal(value_col) not in {"value", "obs value", "observation value"}:
        return frame
    desc_cols = [c for c in frame.columns if any(x in _normal(c) for x in ("item", "series", "indicator", "measure", "description", "unit")) and c != value_col]
    if not desc_cols:
        return frame
    row_descriptions = frame[desc_cols].apply(lambda col: col.map(_cell_value)).astype(str).apply(lambda row: " ".join(_normal(v) for v in row), axis=1)
    mask = row_descriptions.map(lambda value: all(word in value for word in include))
    filtered = frame.loc[mask]
    return filtered if not filtered.empty else frame


def _fetch_dbie_reserves(start_date: str) -> tuple[pd.Series, dict[str, Any]]:
    table = "external_sector.r53_foreign_exchange_reserves_weekly"
    frame = _dbie_rows(table, start_date)
    value_col = _choose_value_column(frame, ("total", "reserves", "usd"), exclude=("rupee", "crore", "gold", "foreign currency assets", "sdr", "tranche"))
    value_frame = _filter_long_rows(frame, ("total", "reserves", "usd"), value_col)
    dates = _period_dates(value_frame)
    values = _to_numeric(value_frame[value_col])
    if values.empty or values.notna().sum() == 0:
        raise ValueError("DBIE reserves table contains no numeric total-reserves values.")
    # Table is described in US$ millions. If API omits unit text, the magnitude is checked as a fallback.
    norm = _normal(value_col)
    if "million" in norm or (values.dropna().median() > 10000):
        values = values / 1000.0
    availability = pd.DatetimeIndex(pd.to_datetime(dates, errors="coerce")) + pd.offsets.BDay(5)
    out = pd.Series(values.to_numpy(), index=availability, name="FX_RESERVES_USD_BN").dropna()
    out.index = pd.DatetimeIndex(out.index).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if out.empty:
        raise ValueError("No parsable weekly reserve dates remain after normalization.")
    return out[out.index >= pd.Timestamp(start_date)], {
        "status": "ok", "source": f"RBI DBIE mirror table {table}", "latest_date": out.index.max().strftime("%Y-%m-%d"),
        "rows": int(out.notna().sum()), "message": "Weekly reserves converted to USD bn. Observation date is shifted by 5 business days as a conservative availability proxy; the mirror can lag or revise RBI data. Verify the latest print against RBI's primary release.",
        "source_url": f"https://dbie.rbihub.in/tables?table={table}", "availability_lag_business_days": 5,
    }


def _fetch_dbie_trade_balance(start_date: str, usdinr: pd.Series) -> tuple[pd.Series, dict[str, Any]]:
    # This DBIE table is a monthly INR-crore export/import/trade-balance table from DGCIS.
    table = "external_sector.r648_india_s_foreign_trade_rupees"
    frame = _dbie_rows(table, start_date)
    value_col = _choose_value_column(frame, ("trade", "balance"), exclude=("oil", "non oil", "export", "import", "usd", "us dollar"))
    selected = _filter_long_rows(frame, ("trade", "balance"), value_col)
    dates = _period_dates(selected)
    observations = pd.DataFrame({"date": pd.to_datetime(dates, errors="coerce"), "value": _to_numeric(selected[value_col]).to_numpy()})
    observations = observations.dropna(subset=["date", "value"]).sort_values("date")
    if observations.empty:
        raise ValueError("DBIE trade table contains no usable dated trade-balance values.")
    # The RBI table is in INR crore. Convert to USD bn using USD/INR at the period month-end.
    period_ends = pd.DatetimeIndex(observations["date"]).to_period("M").to_timestamp("M")
    values = observations["value"]
    fx = pd.to_numeric(usdinr, errors="coerce").dropna().sort_index()
    if fx.empty:
        raise ValueError("USD/INR series is required to convert India trade balance from INR crore to USD bn.")
    fx_values = fx.reindex(period_ends, method="ffill").to_numpy(dtype=float)
    usd_bn = values.to_numpy(dtype=float) * 0.01 / fx_values
    # RBI table exposes reference periods rather than release timestamps; month-end +25 BDays is deliberately conservative.
    avail_idx = period_ends + pd.offsets.BDay(25)
    out = pd.Series(usd_bn, index=avail_idx, name="INDIA_TRADE_BALANCE_USD_BN").replace([np.inf, -np.inf], np.nan).dropna()
    out.index = pd.DatetimeIndex(out.index).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if out.empty:
        raise ValueError("No usable monthly trade-balance observations remain after normalization.")
    out = out[out.index >= pd.Timestamp(start_date)]
    return out, {
        "status": "ok", "source": f"RBI DBIE mirror / DGCIS table {table}", "latest_date": out.index.max().strftime("%Y-%m-%d"),
        "rows": int(out.notna().sum()), "message": "Monthly trade balance in INR crore converted to USD bn using period-end USD/INR; data availability is approximated as month-end +25 business days because the table does not expose each historical publication timestamp. Values may be revised.",
        "source_url": f"https://dbie.rbihub.in/tables?table={table}", "availability_lag_business_days": 25,
    }


def _fetch_fred_monthly(series_id: str, output_name: str, start_date: str, lag_business_days: int) -> tuple[pd.Series, dict[str, Any]]:
    url = f"{FRED_CSV}?id={series_id}&cosd={start_date}"
    response = _get(url, timeout=35)
    frame = pd.read_csv(StringIO(response.text))
    date_col = next((c for c in frame.columns if _normal(c) in {"observation date", "date", "time period"}), frame.columns[0])
    value_col = series_id if series_id in frame.columns else next((c for c in frame.columns if c != date_col), None)
    if value_col is None:
        raise ValueError(f"FRED response schema for {series_id} is unrecognized.")
    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = _to_numeric(frame[value_col])
    period_end = pd.DatetimeIndex(dates).to_period("M").to_timestamp("M")
    available_on = period_end + pd.offsets.BDay(lag_business_days)
    out = pd.Series(values.to_numpy(dtype=float), index=available_on, name=output_name).dropna()
    out.index = pd.DatetimeIndex(out.index).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out[out.index >= pd.Timestamp(start_date)]
    if out.empty:
        raise ValueError(f"FRED series {series_id} has no usable rows for the requested range.")
    return out, {
        "status": "ok", "source": f"FRED / OECD Main Economic Indicators ({series_id})", "latest_date": out.index.max().strftime("%Y-%m-%d"),
        "rows": int(out.notna().sum()), "message": f"Monthly series shifted to month-end +{lag_business_days} business days as an approximate publication-availability rule. This is current-vintage data, not a full ALFRED point-in-time vintage history.",
        "source_url": f"https://fred.stlouisfed.org/series/{series_id}", "availability_lag_business_days": lag_business_days,
    }


def _fetch_oecd_cpi(start_date: str, lag_business_days: int = 20) -> tuple[pd.Series, dict[str, Any]]:
    """Fetch monthly CPI y/y inflation through OECD SDMX; refuse to relabel CPI levels as inflation."""
    # OECD Data Explorer's public SDMX API. The query requests India monthly all-items CPI y/y
    # transformation. A second conservative dimension variant is tried if the schema changes.
    urls = [
        "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/IND.M.N.CPI.._T.N.GY%2B_Z?startPeriod=2010-01&dimensionAtObservation=AllDimensions",
        "https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,/IND.M.N.CPI.._T.N.GY%2B_Z?startPeriod=2010-01&dimensionAtObservation=AllDimensions",
    ]
    errors: list[str] = []
    frame: pd.DataFrame | None = None
    for url in urls:
        try:
            response = _get(url, timeout=45, headers={**HEADERS, "Accept": "text/csv"})
            candidate = pd.read_csv(StringIO(response.text))
            norm_columns = {_normal(c): c for c in candidate.columns}
            date_col = next((norm_columns[k] for k in ("time period", "time_period", "period") if k in norm_columns), None)
            value_col = next((norm_columns[k] for k in ("obs value", "obs_value", "observation value") if k in norm_columns), None)
            if date_col and value_col and not candidate.empty:
                frame = candidate
                break
            errors.append(f"unexpected SDMX columns: {list(candidate.columns)[:12]}")
        except Exception as exc:
            errors.append(str(exc)[:160])
    if frame is None:
        raise RuntimeError("OECD CPI SDMX feed could not be parsed: " + "; ".join(errors))

    norm_columns = {_normal(c): c for c in frame.columns}
    date_col = next(norm_columns[k] for k in ("time period", "time_period", "period") if k in norm_columns)
    value_col = next(norm_columns[k] for k in ("obs value", "obs_value", "observation value") if k in norm_columns)
    # Filter explicit labels when present. The URI requests GY (year-over-year growth); if the
    # provider returns another transformation alongside it, don't let those rows get mixed in.
    transform_col = next((c for c in frame.columns if "transformation" in _normal(c)), None)
    if transform_col:
        transform = frame[transform_col].astype(str).str.upper()
        gy = frame.loc[transform.str.contains(r"(^|[^A-Z])GY([^A-Z]|$)|YEAR.?OVER.?YEAR|GROWTH", regex=True, na=False)]
        if not gy.empty:
            frame = gy
    measure_col = next((c for c in frame.columns if _normal(c) in {"measure", "subject"}), None)
    if measure_col:
        measure = frame[measure_col].astype(str).map(_normal)
        candidates = frame.loc[measure.str.contains("cpi", na=False)]
        if not candidates.empty:
            frame = candidates
    dates = pd.to_datetime(frame[date_col].astype(str).str.replace("M", "-", regex=False), errors="coerce")
    values = _to_numeric(frame[value_col])
    clean = pd.DataFrame({"date": dates, "value": values}).dropna()
    if clean.empty:
        raise ValueError("OECD CPI feed returned no valid date/value observations.")
    clean["date"] = clean["date"].dt.to_period("M").dt.to_timestamp("M")
    # A duplicate monthly observation signals a multi-series query ambiguity; fail rather than average different indices.
    if clean["date"].duplicated().any():
        raise ValueError("OECD CPI query returned duplicate values for a month; refusing to guess which series is all-items inflation.")
    available_on = pd.DatetimeIndex(clean["date"]) + pd.offsets.BDay(lag_business_days)
    out = pd.Series(clean["value"].to_numpy(dtype=float), index=available_on, name="INDIA_CPI_YOY").sort_index()
    out = out[out.index >= pd.Timestamp(start_date)]
    if out.empty:
        raise ValueError("OECD CPI feed has no usable values within requested dates.")
    return out, {
        "status": "ok", "source": "OECD SDMX public API (India monthly all-items CPI, year-over-year transformation)",
        "latest_date": out.index.max().strftime("%Y-%m-%d"), "rows": int(out.notna().sum()),
        "message": f"Monthly CPI y/y values are shifted to month-end +{lag_business_days} business days as a conservative availability proxy. OECD data are a republished international series and may revise; verify latest values against MoSPI/RBI releases.",
        "source_url": "https://data-explorer.oecd.org/", "availability_lag_business_days": lag_business_days,
    }


class _TableRows(HTMLParser):
    """Small dependency-free HTML table-row collector for the public CDSL report."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: list[str] = []
        self._cell: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(" ".join(" ".join(self._cell).split()))
            self._in_cell = False
            self._cell = []
        elif tag == "tr" and self._in_row:
            if self._row:
                self.rows.append(self._row)
            self._in_row = False
            self._row = []


def parse_cdsl_fpi_html(html: str) -> pd.Series:
    """Parse daily total FPI net investment from CDSL's public current-month page.

    CDSL reports net investment in USD millions. The parser uses the Total row only and converts
    to USD billions; it will raise when it cannot identify the total rather than returning zeros.
    """
    # Derivatives section has a separate table. Use only the first FPI-investment part.
    html = re.split(r"Daily Trends in FII\s*/\s*FPI Derivative", html, flags=re.IGNORECASE)[0]
    parser = _TableRows()
    parser.feed(html)
    current_date: pd.Timestamp | None = None
    observations: list[tuple[pd.Timestamp, float]] = []
    # CDSL pages have used both 01-Oct-2026 and 01-10-2026 date spellings.
    date_re = re.compile(r"^\d{1,2}[-/ ](?:[A-Z]{3}|\d{1,2})[-/ ]\d{4}$", re.IGNORECASE)
    number_re = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")
    for row in parser.rows:
        date_found = None
        for cell in row:
            if date_re.match(cell.strip()):
                date_found = pd.to_datetime(cell.strip().replace("/", "-"), errors="coerce", dayfirst=True)
                break
        if date_found is not None and not pd.isna(date_found):
            current_date = pd.Timestamp(date_found).normalize()
        if current_date is None or not any(cell.strip().lower() == "total" for cell in row):
            continue
        numeric = []
        for cell in row:
            token = cell.strip().replace(" ", "")
            if number_re.match(token):
                try:
                    numeric.append(float(token.replace(",", "")))
                except ValueError:
                    pass
        # The Total row ends with Net Investment US($) million (the conversion rate is blank).
        if len(numeric) < 2:
            continue
        net_usd_mn = numeric[-1]
        observations.append((current_date, net_usd_mn / 1000.0))
    if not observations:
        raise ValueError("Could not find dated CDSL FPI Total rows in the downloaded HTML.")
    result = pd.DataFrame(observations, columns=["date", "value"]).drop_duplicates("date", keep="last").sort_values("date")
    series = pd.Series(result["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(result["date"]), name="FPI_NET_FLOWS_USD_BN")
    return series


def _fetch_cdsl_fpi(start_date: str) -> tuple[pd.Series, dict[str, Any]]:
    errors: list[str] = []
    parsed: list[tuple[str, pd.Series]] = []
    for url in (CDSL_FPI_ARCHIVE_URL, CDSL_FPI_MONTH_URL):
        try:
            response = _get(url, timeout=45)
            candidate = parse_cdsl_fpi_html(response.text)
            if not candidate.empty:
                parsed.append((url, candidate))
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:140]}")
    if not parsed:
        raise RuntimeError("Could not parse a public CDSL FPI report. " + "; ".join(errors[:2]))
    # Prefer the page with most parsed history. If the archive stops serving full history,
    # the current-month page remains a best-effort fallback and the status warns users.
    source_url, series = max(parsed, key=lambda item: len(item[1]))
    # CDSL reports confirmed-trade net investments; shift availability after the reporting date.
    series = series.copy()
    series.index = pd.DatetimeIndex(series.index) + pd.offsets.BDay(1)
    series = series[series.index >= pd.Timestamp(start_date)]
    if series.empty:
        raise ValueError("CDSL FPI page contained no observations in the selected data window.")
    is_archive = source_url == CDSL_FPI_ARCHIVE_URL
    return series, {
        "status": "ok", "source": "Central Depository Services Limited (CDSL), public FPI daily report",
        "latest_date": series.index.max().strftime("%Y-%m-%d"), "rows": int(series.notna().sum()),
        "message": ("Parsed dated Total-row net investments, USD millions converted to USD bn, and shifted by one business day. "
                    + ("Archive page selected because it returned the most rows; confirm the covered dates in the status report." if is_archive else "Current-month page selected as fallback; historical coverage may be short, so add release-dated historical rows for broader backtests.")),
        "source_url": source_url, "availability_lag_business_days": 1,
    }


def _record_status(series: pd.Series, source: dict[str, Any], column: str) -> dict[str, Any]:
    result = dict(source)
    result.setdefault("status", "ok")
    result["rows"] = int(series.notna().sum())
    result["latest_date"] = series.dropna().index.max().strftime("%Y-%m-%d") if series.notna().any() else None
    result["target_column"] = column
    # Source freshness thresholds are deliberately wider than a normal release cycle.
    # They are a warning signal, not an assertion that all data before the threshold are valid.
    max_age_days = {
        "INDIA_10Y_BOND_YIELD": 75,
        "INDIA_CPI_YOY": 100,
        "FX_RESERVES_USD_BN": 21,
        "INDIA_TRADE_BALANCE_USD_BN": 120,
        "FPI_NET_FLOWS_USD_BN": 10,
    }.get(column, 90)
    if series.notna().any():
        latest = pd.Timestamp(series.dropna().index.max()).normalize()
        age_days = max(0, int((pd.Timestamp.now().normalize() - latest).days))
        result["age_days"] = age_days
        result["freshness_threshold_days"] = max_age_days
        if age_days > max_age_days:
            result["status"] = "stale"
            result["message"] = str(result.get("message", "")) + f" Latest availability date is {age_days} calendar days old, exceeding the {max_age_days}-day freshness warning threshold."
    return result


def fetch_india_macro_sources(start_date: str, usdinr: pd.Series) -> tuple[dict[str, pd.Series], dict[str, dict[str, Any]]]:
    """Fetch all available India macro/capital-flow series independently.

    A failure in one optional provider does not stop the other feeds. Each failure becomes an
    explicit source-status row so users can tell missing data from a genuine zero.
    """
    out: dict[str, pd.Series] = {}
    status: dict[str, dict[str, Any]] = {}
    tasks = [
        ("INDIA_10Y_BOND_YIELD", lambda: _fetch_fred_monthly("INDIRLTLT01STM", "INDIA_10Y_BOND_YIELD", start_date, 15)),
        ("INDIA_CPI_YOY", lambda: _fetch_oecd_cpi(start_date, 20)),
        ("FX_RESERVES_USD_BN", lambda: _fetch_dbie_reserves(start_date)),
        ("INDIA_TRADE_BALANCE_USD_BN", lambda: _fetch_dbie_trade_balance(start_date, usdinr)),
        ("FPI_NET_FLOWS_USD_BN", lambda: _fetch_cdsl_fpi(start_date)),
    ]
    for column, fetch in tasks:
        try:
            series, metadata = fetch()
            if series.dropna().empty:
                raise ValueError("Source returned no usable observations.")
            out[column] = series.rename(column).sort_index()
            status[column] = _record_status(out[column], metadata, column)
        except Exception as exc:
            status[column] = {
                "status": "error", "source": {
                    "INDIA_10Y_BOND_YIELD": "FRED / OECD Main Economic Indicators",
                    "INDIA_CPI_YOY": "OECD SDMX public API",
                    "FX_RESERVES_USD_BN": "RBI DBIE mirror public read-only API",
                    "INDIA_TRADE_BALANCE_USD_BN": "RBI DBIE mirror / DGCIS public trade table",
                    "FPI_NET_FLOWS_USD_BN": "CDSL public FPI daily report",
                }[column],
                "target_column": column, "message": str(exc)[:400],
                "rows": 0, "latest_date": None,
            }
    return out, status
