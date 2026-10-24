"""FastAPI service for Rupee Prediction System v4.1.0."""
from __future__ import annotations
from pathlib import Path
from typing import Any
import json
import time
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .data_collector import collect_market_data, get_source_status, DATA_FILE
from .data_processor import load_price_data
from .factor_engine import analyse_factors
from .factor_audit import run_factor_audit
from .model import predict_next_session
from .backtest import run_backtest
from .news_features import fetch_current_headlines, analyze_with_local_ollama, load_event_inputs, EVENT_COLUMNS
from .risk_features import detect_regime, detect_feature_drift
from .paths import TEMPLATE_DIR as TEMPLATE_ROOT, BACKTEST_RESULTS_FILE, FACTOR_AUDIT_JSON, FACTOR_AUDIT_CSV, OFFICIAL_REFERENCE_RATE_FILE, ensure_runtime_layout
from .target_source import get_target_source, set_target_source, load_official_reference_rates, get_rbi_dbie_cache_status
from .feature_ablation import run_feature_ablation
from .shadow_forecasts import record_shadow_forecast, evaluate_shadow_forecasts
from .data_quality import audit_market_data, read_source_status
from .operations import get_api_logger, log_request, readiness_summary
from .version import VERSION

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TEMPLATE_DIR = TEMPLATE_ROOT
ensure_runtime_layout()
app = FastAPI(title="Rupee Prediction System", version=VERSION, description="Local macro, FX forecasting, data-quality and prospective validation research dashboard")
API_LOGGER = get_api_logger()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        log_request(API_LOGGER, request.method, request.url.path, status_code, (time.perf_counter() - started) * 1000.0)
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


class NewsAnalysisRequest(BaseModel):
    model: str = Field(default="qwen2.5:7b", min_length=1, max_length=100)
    max_records: int = Field(default=10, ge=1, le=15)


class TargetSourceRequest(BaseModel):
    target_source: str = Field(min_length=1, max_length=50)


class ShadowForecastRequest(BaseModel):
    prediction_report: dict[str, Any]


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Readiness endpoint for the local launcher and troubleshooting."""
    from .paths import MARKET_DATA_FILE, SOURCE_STATUS_FILE
    return readiness_summary(VERSION, get_target_source(), MARKET_DATA_FILE, SOURCE_STATUS_FILE)


@app.get("/")
def home() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/status")
def status() -> dict[str, Any]:
    data_file = DATA_FILE
    if not data_file.exists():
        return {"version": VERSION, "data_available": False, "rows": 0, "latest_date": None, "target_source": get_target_source(), "sources": get_source_status()}
    try:
        prices = load_price_data()
        return {"version": VERSION, "data_available": not prices.empty, "rows": int(len(prices)), "latest_date": prices.index[-1].strftime("%Y-%m-%d") if not prices.empty else None, "target_source": get_target_source(), "sources": get_source_status(), "market_regime": detect_regime(prices), "feature_drift": detect_feature_drift(prices)}
    except Exception as exc:
        return {"version": VERSION, "data_available": False, "rows": 0, "latest_date": None, "error": str(exc), "sources": get_source_status()}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    try:
        prices = load_price_data()
    except FileNotFoundError:
        return {"data_available": False, "message": "Fetch / refresh data to get started.", "sources": get_source_status(), "target_source": get_target_source(), "version": VERSION}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if prices.empty:
        return {"data_available": False, "message": "The saved dataset is empty.", "sources": get_source_status(), "target_source": get_target_source(), "version": VERSION}
    latest = prices.iloc[-1]
    previous = prices.iloc[-2] if len(prices) > 1 else None
    daily_change = (float(latest["USDINR"]) / float(previous["USDINR"]) - 1) * 100 if previous is not None and float(previous["USDINR"]) else None
    month_ago = prices.iloc[-min(22, len(prices))]
    month_change = (float(latest["USDINR"]) / float(month_ago["USDINR"]) - 1) * 100 if float(month_ago["USDINR"]) else None
    history = [{"date": date.strftime("%Y-%m-%d"), "usdinr": round(float(row["USDINR"]), 4)} for date, row in prices.tail(180).iterrows()]
    factors = analyse_factors(prices)
    events = load_event_inputs()
    return {
        "version": VERSION, "data_available": True, "rows": int(len(prices)),
        "latest_date": prices.index[-1].strftime("%Y-%m-%d"),
        "usd_inr": round(float(latest["USDINR"]), 4),
        "dxy": _num(latest, "DXY", 4), "brent": _num(latest, "BRENT", 2), "gold": _num(latest, "GOLD", 2),
        "vix": _num(latest, "VIX", 2), "move": _num(latest, "MOVE", 2), "us10y": _num(latest, "US10Y_YIELD", 3),
        "us2y": _num(latest, "US2Y_YIELD", 3), "rbi_repo": _num(latest, "RBI_REPO_RATE", 3),
        "ecb_mro": _num(latest, "ECB_MRO_RATE", 3), "fed_funds": _num(latest, "FED_FUNDS_RATE", 3),
        "usdcnh": _num(latest, "USD_CNH", 4), "india_10y": _num(latest, "INDIA_10Y_BOND_YIELD", 3),
        "daily_change_pct": round(float(daily_change), 4) if daily_change is not None else None,
        "approx_month_change_pct": round(float(month_change), 4) if month_change is not None else None,
        "history": history, "factor_analysis": factors, "market_regime": detect_regime(prices), "target_source": get_target_source(),
        "event_rows": int(len(events)), "sources": get_source_status(), "feature_drift": detect_feature_drift(prices),
        "message": "Data loaded. Confirm latest dates and source health; optional indicators may be missing.",
    }


def _num(row: pd.Series, key: str, decimals: int) -> float | None:
    try:
        value = float(row[key])
        return round(value, decimals) if pd.notna(value) else None
    except (KeyError, TypeError, ValueError):
        return None


@app.get("/api/data-quality")
def data_quality() -> dict[str, Any]:
    """Audit target integrity, feature missingness, source freshness and timing caveats."""
    try:
        try:
            prices = load_price_data()
        except FileNotFoundError:
            prices = pd.DataFrame()
        report = audit_market_data(prices, read_source_status(), get_target_source())
        from .paths import RUNTIME_DIR, ensure_runtime_layout
        ensure_runtime_layout()
        (RUNTIME_DIR / "data_quality_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        rows = []
        for issue in report.get("issues", []):
            rows.append({"section": "issue", "severity": issue.get("severity"), "code": issue.get("code"), "name": "", "status": "", "freshness": "", "message": issue.get("message", "")})
        for flag in report.get("point_in_time_review_flags", []):
            rows.append({"section": "point_in_time", "severity": flag.get("severity"), "code": "TIMING_REVIEW", "name": flag.get("source", ""), "status": "review", "freshness": "", "message": flag.get("message", "")})
        for source in report.get("source_health", []):
            rows.append({"section": "source", "severity": "", "code": "", "name": source.get("name", ""), "status": source.get("status", ""), "freshness": source.get("freshness", ""), "message": source.get("message", "")})
        pd.DataFrame(rows, columns=["section", "severity", "code", "name", "status", "freshness", "message"]).to_csv(RUNTIME_DIR / "data_quality_report.csv", index=False)
        return report
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Data-quality audit failed: {exc}") from exc


@app.get("/api/data-quality.csv")
def data_quality_csv() -> FileResponse:
    from .paths import RUNTIME_DIR
    path = RUNTIME_DIR / "data_quality_report.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Run the data-quality audit first.")
    return FileResponse(path, filename="rupee-prediction-data-quality.csv", media_type="text/csv")


@app.post("/api/refresh")
def refresh() -> dict[str, Any]:
    try:
        prices = collect_market_data(period="5y")
        data = overview()
        data["message"] = f"Refreshed {len(prices):,} aligned business-day rows. Review source status and latest dates; optional feeds can fail independently."
        return data
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/predict")
def predict() -> dict[str, Any]:
    try:
        prices = load_price_data()
        quality = audit_market_data(prices, read_source_status(), get_target_source())
        blocking_codes = {"NO_DATA", "INVALID_TARGET_VALUES", "RAW_INVALID_RATES", "RAW_INVALID_DATES", "RAW_DUPLICATE_DATES", "TARGET_STALE", "FUTURE_TARGET_DATE", "TARGET_COLUMN_MISSING"}
        blocking = [item for item in quality.get("issues", []) if item.get("code") in blocking_codes]
        if blocking:
            raise HTTPException(status_code=409, detail="Forecast blocked by data-quality checks: " + " ".join(item.get("message", "") for item in blocking[:4]))
        report = predict_next_session()
        report["data_quality_gate"] = {"status": quality.get("release_gate"), "point_in_time_flags": len(quality.get("point_in_time_review_flags", [])), "note": "The gate checks data integrity and obvious staleness; it does not certify point-in-time availability or forecasting skill."}
        return report
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/backtest")
def backtest() -> dict[str, Any]:
    try:
        prices = load_price_data()
        if len(prices) < 400:
            raise ValueError(f"Only {len(prices)} rows are available; at least 400 are recommended for walk-forward testing.")
        report = run_backtest(prices, horizons=(1, 5, 20), max_folds=None)
        # Omit verbose per-observation rows from the browser response while retaining the complete JSON report locally.
        compact_horizons = {}
        for key, value in report["horizons"].items():
            compact_horizons[key] = {k: v for k, v in value.items() if k not in {"oos_predictions", "numerical_oos_predictions"}}
        report["horizons"] = compact_horizons
        report["full_report_path"] = str(BACKTEST_RESULTS_FILE)
        return report
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/backtest/latest")
def latest_backtest() -> dict[str, Any]:
    path = BACKTEST_RESULTS_FILE
    if not path.exists():
        return {"available": False, "message": "Run the walk-forward backtest first."}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.get("horizons", {}).items():
            value.pop("oos_predictions", None)
            value.pop("numerical_oos_predictions", None)
        return {"available": True, **data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read saved backtest: {exc}") from exc


@app.get("/api/factor-audit")
def factor_audit() -> dict[str, Any]:
    """Report descriptive sign association and active/default heuristic weights."""
    try:
        prices = load_price_data()
        report = run_factor_audit(prices)
        ensure_runtime_layout()
        FACTOR_AUDIT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        pd.DataFrame(report["factors"]).to_csv(FACTOR_AUDIT_CSV, index=False)
        return report
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Fetch / refresh real market data before running the factor audit.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/factor-audit.csv")
def factor_audit_csv() -> FileResponse:
    if not FACTOR_AUDIT_CSV.exists():
        raise HTTPException(status_code=404, detail="Run the factor audit first to generate a CSV report.")
    return FileResponse(FACTOR_AUDIT_CSV, filename="rupee-prediction-factor-audit.csv", media_type="text/csv")


@app.get("/api/factor-weights-template")
def factor_weights_template() -> FileResponse:
    template = TEMPLATE_DIR / "factor_weights_template.csv"
    if not template.exists():
        raise HTTPException(status_code=404, detail="Factor-weight template is missing from the package.")
    return FileResponse(template, filename="factor_weights_template.csv", media_type="text/csv")


@app.get("/api/target-source")
def target_source_status() -> dict[str, Any]:
    mode = get_target_source()
    file_rows = 0
    if OFFICIAL_REFERENCE_RATE_FILE.exists():
        try:
            rates, info = load_official_reference_rates(min_rows=1)
            file_rows = len(rates)
        except Exception as exc:
            info = {"status": "invalid", "message": str(exc)}
    else:
        info = {"status": "not_configured", "message": "Import a reference-rate CSV using the downloadable template."}
    import os
    dbie_cache = get_rbi_dbie_cache_status()
    return {
        "target_source": mode,
        "official_reference_file": str(OFFICIAL_REFERENCE_RATE_FILE),
        "official_reference_rows": file_rows,
        "official_reference_status": info,
        "rbi_dbie_cache_status": dbie_cache,
        "target_source_options": [
            {"value": "yahoo_proxy", "label": "Yahoo Finance INR=X proxy"},
            {"value": "fbil_csv", "label": "Imported FBIL/RBI-style reference-rate CSV"},
            {"value": "rbi_dbie_mirror", "label": "RBI DBIE historical reference-rate table via mirror"},
        ],
        "environment_override": bool(os.environ.get("RPS_USDINR_TARGET_SOURCE", "").strip()),
        "note": "Changing the target definition requires a data refresh and a new validation run. Target definitions are not interchangeable. The DBIE API option uses a third-party mirror and may lag; freshness checks can block stale forecasts.",
    }


@app.post("/api/target-source")
def save_target_source(request: TargetSourceRequest) -> dict[str, Any]:
    try:
        saved = set_target_source(request.target_source)
        import os
        if os.environ.get("RPS_USDINR_TARGET_SOURCE", "").strip():
            saved["warning"] = "RPS_USDINR_TARGET_SOURCE is set in the environment and overrides this local selection until that environment variable is removed."
        saved["message"] = "Target selection saved. Click Fetch / refresh data next; then rerun all validation because the target series may have changed."
        if request.target_source == "rbi_dbie_mirror":
            saved["warning"] = "The DBIE option accesses a third-party mirror, not a direct RBI/FBIL live-feed guarantee. Check the returned latest date; stale rates must not be used for current forecasts."
        return saved
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/official-reference-template")
def official_reference_template() -> FileResponse:
    template = TEMPLATE_DIR / "official_usdinr_reference_template.csv"
    if not template.exists():
        raise HTTPException(status_code=404, detail="Official reference-rate template is missing from the package.")
    return FileResponse(template, filename="official_usdinr_reference_template.csv", media_type="text/csv")


@app.post("/api/feature-ablation")
def feature_ablation(horizon: int = Query(default=5, ge=1, le=20)) -> dict[str, Any]:
    if horizon not in (1, 5, 20):
        raise HTTPException(status_code=400, detail="Horizon must be 1, 5 or 20 sessions.")
    try:
        prices = load_price_data()
        report = run_feature_ablation(prices, horizon=horizon)
        runtime_path = Path(BACKTEST_RESULTS_FILE).parent / f"feature_ablation_{horizon}d.json"
        runtime_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["report_path"] = str(runtime_path)
        return report
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Fetch / refresh real market data before feature ablation.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/shadow-forecasts")
def shadow_forecasts() -> dict[str, Any]:
    try:
        prices = load_price_data()
        return evaluate_shadow_forecasts(prices)
    except FileNotFoundError:
        return {"available": False, "total_records": 0, "evaluated_records": 0, "pending_records": 0, "summary": [], "forecasts": [], "note": "Fetch market history to load the shadow ledger."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load shadow-forecast ledger: {exc}") from exc


@app.post("/api/shadow-forecast")
def add_shadow_forecast(request: ShadowForecastRequest) -> dict[str, Any]:
    try:
        prices = load_price_data()
        result = record_shadow_forecast(request.prediction_report, prices)
        return {**result, "summary": evaluate_shadow_forecasts(prices)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Fetch market data and run a prediction before recording a shadow forecast.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/news")
def news() -> dict[str, Any]:
    return fetch_current_headlines()


@app.post("/api/news/analyze")
def analyze_news(request: NewsAnalysisRequest) -> dict[str, Any]:
    return analyze_with_local_ollama(request.model, request.max_records)


@app.get("/api/macro-template")
def macro_template() -> FileResponse:
    template = TEMPLATE_DIR / "macro_inputs_template.csv"
    if not template.exists():
        template.parent.mkdir(parents=True, exist_ok=True)
        cols = ["Date", "ReferencePeriod", "AvailableAt", "Source", "Units", "Notes", "RBI_REPO_RATE", "INDIA_10Y_BOND_YIELD", "INDIA_CPI_YOY", "FX_RESERVES_USD_BN", "FDI_NET_FLOWS_USD_BN", "INDIA_TRADE_BALANCE_USD_BN", "INDIA_CURRENT_ACCOUNT_USD_BN", "INDIA_ELECTRONICS_IMPORT_PRICE_INDEX", "INDIA_ELECTRONICS_IMPORT_BILL_USD_BN", "INDIA_GOLD_IMPORT_BILL_USD_BN", "FPI_NET_FLOWS_USD_BN", "GPR_INDEX"]
        pd.DataFrame(columns=cols).to_csv(template, index=False)
    return FileResponse(template, filename="macro_inputs_template.csv", media_type="text/csv")


@app.get("/api/event-template")
def event_template() -> FileResponse:
    template = TEMPLATE_DIR / "event_inputs_template.csv"
    if not template.exists():
        pd.DataFrame(columns=EVENT_COLUMNS).to_csv(template, index=False)
    return FileResponse(template, filename="event_inputs_template.csv", media_type="text/csv")
