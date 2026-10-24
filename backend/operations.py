"""Minimal structured local operations logging and readiness summary."""
from __future__ import annotations
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .paths import RUNTIME_DIR, ensure_runtime_layout

LOGGER_NAME = "rupee_prediction.api"

def get_api_logger() -> logging.Logger:
    ensure_runtime_layout()
    log_dir = RUNTIME_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target = (log_dir / "api.jsonl").resolve()
    if not any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename).resolve() == target for handler in logger.handlers):
        handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger

def log_request(logger: logging.Logger, method: str, path: str, status_code: int, duration_ms: float) -> None:
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event": "http_request", "method": method, "path": path,
        "status_code": int(status_code), "duration_ms": round(float(duration_ms), 2),
    }
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

def readiness_summary(version: str, target_source: str, data_file: Path, status_file: Path) -> dict[str, Any]:
    source_status_exists = status_file.exists()
    try:
        data_bytes = data_file.stat().st_size if data_file.exists() else 0
    except OSError:
        data_bytes = 0
    return {
        "status": "ok", "application": "Rupee Prediction System", "version": version,
        "readiness": "data_available" if data_bytes > 0 else "data_refresh_required",
        "target_source": target_source, "market_data_present": data_bytes > 0,
        "market_data_bytes": data_bytes, "source_status_present": source_status_exists,
        "runtime_mode": "local-first research; bind to loopback unless you deliberately configure otherwise",
        "note": "HTTP status ok means the local app is responding; it does not mean data sources are fresh or a forecast is ready. Inspect readiness and source status before forecasting.",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
