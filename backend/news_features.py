"""Release-timestamp-aware event features and optional current GDELT headlines.

Historical events are only used when entered in runtime/inputs/event_inputs.csv. Live headlines are
context-only until a timestamped history and reproducible labels are available.
"""
from __future__ import annotations
from typing import Any
import pandas as pd
import numpy as np
import requests

from .http_client import get as http_get

from .paths import EVENT_INPUT_FILE as EVENT_FILE, ensure_runtime_layout
EVENT_COLUMNS = ["Date", "Category", "Severity", "SurprisePct", "Sentiment", "Source", "Summary"]
CATEGORIES = ["FED", "RBI", "INFLATION", "OIL_SUPPLY", "GEOPOLITICAL", "TRADE", "SANCTIONS", "CAPITAL_FLOWS", "OTHER"]


def ensure_event_template() -> None:
    ensure_runtime_layout()
    if not EVENT_FILE.exists():
        EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=EVENT_COLUMNS).to_csv(EVENT_FILE, index=False)


def load_event_inputs() -> pd.DataFrame:
    ensure_event_template()
    frame = pd.read_csv(EVENT_FILE)
    for col in EVENT_COLUMNS:
        if col not in frame:
            frame[col] = np.nan
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame = frame.dropna(subset=["Date"]).copy()
    frame["Category"] = frame["Category"].astype(str).str.upper().str.strip()
    frame.loc[~frame["Category"].isin(CATEGORIES), "Category"] = "OTHER"
    for col in ("Severity", "SurprisePct", "Sentiment"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["Severity"] = frame["Severity"].clip(0, 5)
    frame["Sentiment"] = frame["Sentiment"].clip(-1, 1)
    return frame.sort_values("Date").reset_index(drop=True)


def add_event_features(data: pd.DataFrame, features: dict[str, pd.Series]) -> None:
    """Create rolling features known on each date; later events never flow backward."""
    events = load_event_inputs()
    idx = data.index
    if events.empty or len(idx) == 0:
        return
    daily_columns = [
        "EVENT_COUNT", "EVENT_SEVERITY_SUM", "EVENT_SURPRISE_ABS_SUM",
        "EVENT_SURPRISE_SIGNED_SUM", "EVENT_SENTIMENT_MEAN", "EVENT_SENTIMENT_OBSERVATIONS",
    ] + [f"EVENT_CATEGORY_{c}" for c in CATEGORIES]
    daily_columns += [f"EVENT_SURPRISE_SIGNED_{c}" for c in CATEGORIES]
    daily = pd.DataFrame(0.0, index=idx, columns=daily_columns)
    # Map event to the first observed business date on/after its publication timestamp.
    timestamps = idx.values.astype("datetime64[ns]")
    for _, event in events.iterrows():
        event_ts = event["Date"]
        pos = int(np.searchsorted(timestamps, np.datetime64(event_ts), side="left"))
        if pos >= len(idx):
            continue
        date = idx[pos]
        daily.loc[date, "EVENT_COUNT"] += 1.0
        daily.loc[date, "EVENT_SEVERITY_SUM"] += float(event["Severity"]) if pd.notna(event["Severity"]) else 0.0
        if pd.notna(event["SurprisePct"]):
            surprise = float(event["SurprisePct"])
            daily.loc[date, "EVENT_SURPRISE_ABS_SUM"] += abs(surprise)
            daily.loc[date, "EVENT_SURPRISE_SIGNED_SUM"] += surprise
            daily.loc[date, f"EVENT_SURPRISE_SIGNED_{event['Category']}"] += surprise
        if pd.notna(event["Sentiment"]):
            # Divide by sentiment-bearing events only; missing labels are not treated as neutral.
            daily.loc[date, "EVENT_SENTIMENT_MEAN"] += float(event["Sentiment"])
            daily.loc[date, "EVENT_SENTIMENT_OBSERVATIONS"] += 1.0
        daily.loc[date, f"EVENT_CATEGORY_{event['Category']}"] += 1.0
    sentiment_count = daily["EVENT_SENTIMENT_OBSERVATIONS"].replace(0, np.nan)
    daily["EVENT_SENTIMENT_MEAN"] = daily["EVENT_SENTIMENT_MEAN"] / sentiment_count
    for col in daily.columns:
        features[f"{col}_today"] = daily[col]
        features[f"{col}_rolling_5"] = daily[col].rolling(5, min_periods=1).sum() if "MEAN" not in col else daily[col].rolling(5, min_periods=1).mean()
        features[f"{col}_rolling_20"] = daily[col].rolling(20, min_periods=1).sum() if "MEAN" not in col else daily[col].rolling(20, min_periods=1).mean()


def fetch_current_headlines(max_records: int = 15) -> dict[str, Any]:
    """Fetch current FX/macro headlines from GDELT. These are display-only, not model input."""
    query = '(India rupee OR USD INR OR crude oil supply OR Federal Reserve yields OR emerging markets)'
    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {"query": query, "mode": "ArtList", "format": "json", "maxrecords": min(25, max(1, int(max_records))), "sort": "HybridRel", "timespan": "3d"}
    try:
        response = http_get(url, params=params, timeout=20, headers={"User-Agent": "RupeePredictionResearch/4.0 local research app"})
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("articles", []) if isinstance(payload, dict) else []
        articles = []
        seen = set()
        for row in rows:
            title = str(row.get("title") or "").strip()
            link = str(row.get("url") or "").strip()
            if not title or not link or link in seen:
                continue
            seen.add(link)
            articles.append({"title": title[:240], "url": link, "domain": row.get("domain", ""), "published": row.get("seendate", ""), "source_country": row.get("sourceCountry", "")})
        return {"status": "ok", "source": "GDELT DOC API", "fetched_at": pd.Timestamp.now().isoformat(timespec="seconds"), "articles": articles, "note": "Headline list is context only. It is not sentiment-scored or included in historical forecasts."}
    except Exception as exc:
        return {"status": "unavailable", "source": "GDELT DOC API", "fetched_at": pd.Timestamp.now().isoformat(timespec="seconds"), "articles": [], "note": f"Live headlines could not be loaded: {str(exc)[:240]}. You can still use timestamped historical events in runtime/inputs/event_inputs.csv."}



def analyze_with_local_ollama(model: str = "qwen2.5:7b", max_records: int = 10) -> dict[str, Any]:
    """Ask a user-installed local Ollama model to summarize headlines; output is context-only."""
    import json
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._/-]{0,99}", str(model or "")):
        return {"status": "invalid_model_name", "message": "Use a local Ollama model name such as qwen2.5:7b."}
    headlines = fetch_current_headlines(max_records=max_records)
    articles = headlines.get("articles", [])
    if not articles:
        return {"status": "no_headlines", "message": headlines.get("note", "No headline context available.")}
    compact = [{"title": a["title"], "domain": a.get("domain", ""), "published": a.get("published", ""), "url": a.get("url", "")} for a in articles[:max_records]]
    system = (
        "You are a cautious macroeconomic research assistant. Analyze supplied headlines only. "
        "Do not claim a headline causes USD/INR moves. Distinguish possible mechanisms from evidence, "
        "avoid inventing facts, and use unknown when evidence is insufficient. Return valid JSON with keys: "
        "summary (string), risk_level (LOW/MIXED/ELEVATED/UNKNOWN), possible_channels (array of objects with channel, direction_for_usdinr, evidence_strength, explanation), "
        "contradictory_signals (array of strings), data_gaps (array of strings). direction_for_usdinr must be UP, DOWN, MIXED, or UNKNOWN."
    )
    prompt = "Summarize these recent headlines for an India rupee research dashboard. They are context only and should not be treated as a numerical forecast:\n" + json.dumps(compact, ensure_ascii=False)
    try:
        response = requests.post(
            "http://127.0.0.1:11434/api/chat", timeout=90,
            json={"model": model, "stream": False, "format": "json", "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]},
        )
        response.raise_for_status()
        payload = response.json()
        content = payload.get("message", {}).get("content", "")
        parsed = json.loads(content)
        return {"status": "ok", "model": model, "headline_count": len(compact), "analysis": parsed, "headlines": compact, "note": "Local language-model commentary only. It is not a calibrated forecast and is not fed into the numerical model."}
    except Exception as exc:
        return {"status": "unavailable", "model": model, "headline_count": len(compact), "message": f"Could not reach or parse local Ollama output: {str(exc)[:260]}", "note": "Start Ollama, make sure the requested model is installed (ollama list), or use the headlines without AI summarization."}
