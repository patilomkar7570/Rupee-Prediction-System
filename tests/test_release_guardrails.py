from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from backend.data_quality import audit_market_data
from backend.shadow_forecasts import record_shadow_forecast, evaluate_shadow_forecasts


def make_prices(rows: int = 420, end: str = "2026-10-23") -> pd.DataFrame:
    index = pd.date_range(end=end, periods=rows, freq="B")
    values = np.linspace(82.0, 88.0, rows)
    return pd.DataFrame({"USDINR": values}, index=index)


class DataQualityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = pd.Timestamp("2026-10-24T12:00:00Z")

    def test_empty_data_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_market_data(
                pd.DataFrame(),
                source_status={},
                target_source="fbil_csv",
                raw_data_file=Path(tmp) / "not-created.csv",
                now=self.now,
            )
        codes = {item["code"] for item in report["issues"]}
        self.assertEqual(report["release_gate"], "BLOCKED")
        self.assertIn("NO_DATA", codes)

    def test_stale_target_blocks_forecast(self) -> None:
        prices = make_prices(end="2026-10-01")
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_market_data(
                prices,
                source_status={},
                target_source="fbil_csv",
                raw_data_file=Path(tmp) / "not-created.csv",
                now=self.now,
            )
        codes = {item["code"] for item in report["issues"]}
        self.assertEqual(report["release_gate"], "BLOCKED")
        self.assertIn("TARGET_STALE", codes)

    def test_nonpositive_target_blocks_forecast(self) -> None:
        prices = make_prices()
        prices.iloc[-1, prices.columns.get_loc("USDINR")] = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_market_data(
                prices,
                source_status={},
                target_source="fbil_csv",
                raw_data_file=Path(tmp) / "not-created.csv",
                now=self.now,
            )
        codes = {item["code"] for item in report["issues"]}
        self.assertEqual(report["release_gate"], "BLOCKED")
        self.assertIn("INVALID_TARGET_VALUES", codes)

    def test_duplicate_dates_in_raw_file_block_forecast(self) -> None:
        prices = make_prices()
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "market_data.csv"
            pd.DataFrame({
                "Date": ["2026-10-20", "2026-10-20", "2026-10-21"],
                "USDINR": [88.0, 88.1, 88.2],
            }).to_csv(raw, index=False)
            report = audit_market_data(
                prices,
                source_status={},
                target_source="fbil_csv",
                raw_data_file=raw,
                now=self.now,
            )
        codes = {item["code"] for item in report["issues"]}
        self.assertEqual(report["release_gate"], "BLOCKED")
        self.assertIn("RAW_DUPLICATE_DATES", codes)

    def test_fresh_valid_target_has_no_blocking_issues(self) -> None:
        prices = make_prices()
        with tempfile.TemporaryDirectory() as tmp:
            report = audit_market_data(
                prices,
                source_status={},
                target_source="fbil_csv",
                raw_data_file=Path(tmp) / "not-created.csv",
                now=self.now,
            )
        self.assertNotEqual(report["release_gate"], "BLOCKED")
        blocking = {
            item["code"] for item in report["issues"]
            if item["severity"] in {"critical", "high"}
        }
        self.assertEqual(blocking, set())


class ShadowForecastLedgerTests(unittest.TestCase):
    def test_record_and_score_all_supported_horizons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "shadow_forecasts.csv"
            with (
                patch("backend.shadow_forecasts.SHADOW_FORECASTS_FILE", ledger_path),
                patch("backend.shadow_forecasts.ensure_runtime_layout"),
            ):
                origin_prices = pd.DataFrame(
                    {"USDINR": np.linspace(82.0, 83.0, 30)},
                    index=pd.date_range("2026-08-03", periods=30, freq="B"),
                )
                report = {
                    "as_of_date": origin_prices.index[-1].strftime("%Y-%m-%d"),
                    "usd_inr_close": float(origin_prices["USDINR"].iloc[-1]),
                    "horizons": [
                        {
                            "horizon_days": horizon,
                            "selected_model": "test-model",
                            "model_prediction": "UP",
                            "prediction": "UP",
                            "model_probabilities": {"DOWN": 0.1, "FLAT": 0.1, "UP": 0.8},
                            "confidence": {"label": "test-only"},
                        }
                        for horizon in (1, 5, 20)
                    ],
                }

                saved = record_shadow_forecast(report, origin_prices)
                self.assertEqual(saved["recorded"], 3)
                self.assertTrue(ledger_path.exists())

                future_dates = pd.date_range(
                    origin_prices.index[-1] + pd.offsets.BDay(1),
                    periods=25,
                    freq="B",
                )
                future_values = origin_prices["USDINR"].iloc[-1] + 0.1 * np.arange(1, 26)
                full_prices = pd.concat([
                    origin_prices,
                    pd.DataFrame({"USDINR": future_values}, index=future_dates),
                ])
                result = evaluate_shadow_forecasts(full_prices)

                self.assertEqual(result["total_records"], 3)
                self.assertEqual(result["evaluated_records"], 3)
                self.assertEqual(result["pending_records"], 0)
                self.assertEqual({row["horizon_sessions"] for row in result["forecasts"]}, {1, 5, 20})
                self.assertTrue(all(row["evaluated"] for row in result["forecasts"]))
                self.assertTrue(all(row["actual_direction"] == "UP" for row in result["forecasts"]))


if __name__ == "__main__":
    unittest.main()
