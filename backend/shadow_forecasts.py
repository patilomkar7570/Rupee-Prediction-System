"""Append-only prospective forecast ledger and outcome scoring."""
from __future__ import annotations
import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pandas as pd

from .paths import SHADOW_FORECASTS_FILE, ensure_runtime_layout
from .targets import threshold_for_horizon

COLUMNS = [
    "forecast_id", "issued_at_utc", "as_of_date", "horizon_sessions", "origin_rate",
    "selected_model", "model_prediction", "signal_prediction", "p_down", "p_flat", "p_up",
    "confidence_label", "evaluated", "outcome_date", "actual_rate", "realized_return_pct",
    "actual_direction", "direction_correct",
]


def _read_ledger() -> pd.DataFrame:
    ensure_runtime_layout()
    if not SHADOW_FORECASTS_FILE.exists() or SHADOW_FORECASTS_FILE.stat().st_size == 0:
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(SHADOW_FORECASTS_FILE, dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not read shadow forecast ledger: {exc}") from exc
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    # Keep text/outcome fields as object columns so first scoring can write strings and booleans
    # without dtype warnings. Explicitly parsed numeric columns still permit numeric evaluation.
    numeric = ["horizon_sessions", "origin_rate", "p_down", "p_flat", "p_up", "actual_rate", "realized_return_pct"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["forecast_id", "issued_at_utc", "as_of_date", "selected_model", "model_prediction", "signal_prediction", "confidence_label", "evaluated", "outcome_date", "actual_direction", "direction_correct"]:
        df[col] = df[col].astype(object)
    return df[COLUMNS]


def _write_ledger(df: pd.DataFrame) -> None:
    ensure_runtime_layout()
    temp = SHADOW_FORECASTS_FILE.with_suffix(".csv.tmp")
    df[COLUMNS].to_csv(temp, index=False)
    temp.replace(SHADOW_FORECASTS_FILE)


def record_shadow_forecast(report: dict[str, Any], latest_prices: pd.DataFrame) -> dict[str, Any]:
    if not report.get("as_of_date") or not isinstance(report.get("horizons"), list):
        raise ValueError("Prediction report is missing its as_of_date or horizon predictions.")
    latest_date = latest_prices.index[-1].strftime("%Y-%m-%d") if not latest_prices.empty else None
    if report["as_of_date"] != latest_date:
        raise ValueError(f"Prediction is dated {report['as_of_date']}, but current data ends at {latest_date}. Refresh and run a new forecast before recording it.")
    origin_rate = float(latest_prices["USDINR"].iloc[-1])
    if abs(float(report.get("usd_inr_close", origin_rate)) - origin_rate) > max(.001, origin_rate * .00002):
        raise ValueError("Prediction rate no longer matches the latest market row; rerun the forecast before recording.")
    df = _read_ledger()
    issued = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for item in report["horizons"]:
        horizon = int(item.get("horizon_days", item.get("horizon_sessions", 0)))
        if horizon not in (1, 5, 20):
            continue
        probs = item.get("model_probabilities") or {}
        rows.append({
            "forecast_id": str(uuid.uuid4()), "issued_at_utc": issued, "as_of_date": report["as_of_date"],
            "horizon_sessions": horizon, "origin_rate": origin_rate,
            "selected_model": str(item.get("selected_model", "unknown")),
            "model_prediction": str(item.get("model_prediction", item.get("prediction", "NO RELIABLE SIGNAL"))),
            "signal_prediction": str(item.get("prediction", "NO RELIABLE SIGNAL")),
            "p_down": float(probs.get("DOWN", 0.0)), "p_flat": float(probs.get("FLAT", 0.0)), "p_up": float(probs.get("UP", 0.0)),
            "confidence_label": str((item.get("confidence") or {}).get("label", "unassessed")),
            "evaluated": False, "outcome_date": "", "actual_rate": "", "realized_return_pct": "", "actual_direction": "", "direction_correct": "",
        })
    if len(rows) != 3:
        raise ValueError(f"Expected 1-, 5- and 20-session forecasts; found {len(rows)} suitable horizon records.")
    if df.empty:
        df = pd.DataFrame(rows, columns=COLUMNS)
    else:
        df = pd.concat([df, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
    _write_ledger(df)
    return {"recorded": len(rows), "issued_at_utc": issued, "as_of_date": report["as_of_date"], "forecast_ids": [r["forecast_id"] for r in rows], "ledger_path": str(SHADOW_FORECASTS_FILE)}


def evaluate_shadow_forecasts(prices: pd.DataFrame) -> dict[str, Any]:
    df = _read_ledger()
    if not df.empty and not prices.empty:
        index = prices.index
        changed = False
        for i, row in df.iterrows():
            if str(row.get("evaluated", "False")).strip().lower() in {"true", "1", "yes"}:
                continue
            try:
                origin_date = pd.Timestamp(row["as_of_date"])
                origin_pos = int(index.get_indexer([origin_date])[0])
                horizon = int(row["horizon_sessions"])
                if origin_pos < 0 or origin_pos + horizon >= len(index):
                    continue
                origin_rate = float(prices["USDINR"].iloc[origin_pos])
                actual_rate = float(prices["USDINR"].iloc[origin_pos + horizon])
                if not origin_rate > 0 or not actual_rate > 0:
                    continue
                realized = actual_rate / origin_rate - 1.0
                threshold = threshold_for_horizon(horizon)
                actual_dir = "UP" if realized > threshold else "DOWN" if realized < -threshold else "FLAT"
                model_pred = str(row["model_prediction"])
                df.at[i, "origin_rate"] = origin_rate
                df.at[i, "evaluated"] = True
                df.at[i, "outcome_date"] = index[origin_pos + horizon].strftime("%Y-%m-%d")
                df.at[i, "actual_rate"] = actual_rate
                df.at[i, "realized_return_pct"] = realized * 100.0
                df.at[i, "actual_direction"] = actual_dir
                df.at[i, "direction_correct"] = bool(model_pred == actual_dir)
                changed = True
            except (ValueError, TypeError, KeyError, IndexError):
                continue
        if changed:
            _write_ledger(df)
    rows: list[dict[str, Any]] = []
    for _, r in df.sort_values("issued_at_utc", ascending=False).iterrows() if not df.empty else []:
        def none_if_missing(value: Any) -> Any:
            if pd.isna(value) or value == "": return None
            if isinstance(value, (np_bool_type(),)):
                return bool(value)
            return value
        evaluated = str(r.get("evaluated", "False")).strip().lower() in {"true", "1", "yes"}
        rows.append({
            "forecast_id": str(r.get("forecast_id", "")), "issued_at_utc": str(r.get("issued_at_utc", "")),
            "as_of_date": str(r.get("as_of_date", "")), "horizon_sessions": int(float(r.get("horizon_sessions", 0))),
            "selected_model": str(r.get("selected_model", "")), "model_prediction": str(r.get("model_prediction", "")),
            "signal_prediction": str(r.get("signal_prediction", "")), "confidence_label": str(r.get("confidence_label", "")),
            "evaluated": evaluated, "outcome_date": none_if_missing(r.get("outcome_date")),
            "actual_rate": float(r["actual_rate"]) if evaluated and pd.notna(r.get("actual_rate")) else None,
            "realized_return_pct": float(r["realized_return_pct"]) if evaluated and pd.notna(r.get("realized_return_pct")) else None,
            "actual_direction": none_if_missing(r.get("actual_direction")),
            "direction_correct": bool(r["direction_correct"]) if evaluated and str(r.get("direction_correct", "")).strip().lower() in {"true", "1"} else (False if evaluated else None),
        })
    summary = []
    for horizon in (1, 5, 20):
        subset = [r for r in rows if r["horizon_sessions"] == horizon]
        scored = [r for r in subset if r["evaluated"]]
        emitted = [r for r in subset if r["signal_prediction"] != "NO RELIABLE SIGNAL"]
        summary.append({
            "horizon_sessions": horizon, "recorded": len(subset), "evaluated": len(scored), "pending": len(subset) - len(scored),
            "model_direction_accuracy_pct": round(100 * sum(bool(r["direction_correct"]) for r in scored) / len(scored), 2) if scored else None,
            "signal_coverage_pct": round(100 * len(emitted) / len(subset), 2) if subset else None,
            "note": "Prospective shadow results only; overlapping horizons and repeated issue dates are not independent samples.",
        })
    return {"available": not df.empty, "total_records": len(rows), "evaluated_records": sum(r["evaluated"] for r in rows), "pending_records": sum(not r["evaluated"] for r in rows), "summary": summary, "forecasts": rows[:150], "ledger_path": str(SHADOW_FORECASTS_FILE), "note": "Forecasts are scored only after enough later observations are present in the selected target series. Existing rows are not rewritten except to add realized outcomes."}


def np_bool_type():
    """Avoid importing NumPy solely for checking the CSV boolean scalar type."""
    try:
        import numpy as np
        return np.bool_
    except Exception:
        return bool
