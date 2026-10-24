"""Optional Windows Task Scheduler target: refresh market data, retrain/forecast, write JSON."""
from __future__ import annotations
import json
from .data_collector import collect_market_data
from .model import predict_next_session

from .paths import LATEST_DAILY_RUN_FILE, ensure_runtime_layout


def main() -> int:
    try:
        data = collect_market_data(period="5y")
        prediction = predict_next_session()
        result = {"run_at": __import__("pandas").Timestamp.now().isoformat(timespec="seconds"), "rows": int(len(data)), "latest_date": data.index.max().strftime("%Y-%m-%d"), "prediction": prediction}
        ensure_runtime_layout()
        LATEST_DAILY_RUN_FILE.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"Updated {len(data)} observations through {result['latest_date']}.")
        print("Forecasts:", [(item['horizon_days'], item['prediction']) for item in prediction.get("horizons", [])])
        return 0
    except Exception as exc:
        print(f"Daily update failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
