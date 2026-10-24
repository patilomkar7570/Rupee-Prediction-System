from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from backend.targets import add_target, threshold_for_horizon
from backend.point_in_time import effective_availability_date
from backend.target_source import normalize_reference_rate_frame
from backend.evaluation_uncertainty import moving_block_indices
from backend.risk_features import detect_regime


class TargetTests(unittest.TestCase):
    def test_target_has_no_fabricated_future_label(self):
        frame = pd.DataFrame({"USDINR": [83.0, 83.5, 84.0, 83.0]}, index=pd.date_range("2026-01-01", periods=4, freq="B"))
        result = add_target(frame, horizon=1)
        self.assertEqual(result["target_1d"].iloc[0], "UP")
        self.assertTrue(pd.isna(result["target_1d"].iloc[-1]))
        self.assertTrue(pd.isna(result["target_return_1d"].iloc[-1]))

    def test_horizon_threshold_increases_gently(self):
        self.assertLess(threshold_for_horizon(1), threshold_for_horizon(5))
        self.assertLess(threshold_for_horizon(5), threshold_for_horizon(20))

    def test_only_supported_horizons_are_allowed(self):
        with self.assertRaises(ValueError):
            add_target(pd.DataFrame({"USDINR": [83.0, 83.1]}), horizon=3)


class PointInTimeTests(unittest.TestCase):
    def test_after_cutoff_moves_to_next_weekday(self):
        effective, audit = effective_availability_date("2026-10-23", "2026-10-23 18:00:00")
        self.assertEqual(effective.strftime("%Y-%m-%d"), "2026-10-26")
        self.assertTrue(audit["after_cutoff_shifted"])

    def test_before_cutoff_does_not_shift(self):
        effective, audit = effective_availability_date("2026-10-23", "2026-10-23 11:30:00")
        self.assertEqual(effective.strftime("%Y-%m-%d"), "2026-10-23")
        self.assertFalse(audit["after_cutoff_shifted"])

    def test_invalid_nonempty_timestamp_is_not_silently_fallbacked(self):
        effective, audit = effective_availability_date("2026-10-23", "not-a-time")
        self.assertTrue(pd.isna(effective))
        self.assertEqual(audit["status"], "invalid_available_at")


class ReferenceRateTests(unittest.TestCase):
    def test_clean_reference_rate_csv_normalizes(self):
        frame = pd.DataFrame({
            "Date": ["2026-10-20", "2026-10-21", "2026-10-22"],
            "USDINR": ["88.01", "88.12", "88.07"],
        })
        series, info, normalized = normalize_reference_rate_frame(frame, min_rows=3)
        self.assertEqual(len(series), 3)
        self.assertEqual(info["rows"], 3)
        self.assertEqual(float(series.iloc[1]), 88.12)
        self.assertEqual(normalized["USDINR"].min(), 88.01)

    def test_duplicate_reference_dates_fail_closed(self):
        frame = pd.DataFrame({"Date": ["2026-10-20", "2026-10-20"], "USDINR": [88.0, 88.1]})
        with self.assertRaisesRegex(ValueError, "duplicate dates"):
            normalize_reference_rate_frame(frame, min_rows=1)


class EvaluationHelperTests(unittest.TestCase):
    def test_moving_block_indices_return_expected_length(self):
        indices = moving_block_indices(103, 7, np.random.default_rng(42))
        self.assertEqual(len(indices), 103)
        self.assertTrue((indices >= 0).all())
        self.assertTrue((indices < 103).all())

    def test_empty_market_regime_is_unknown(self):
        result = detect_regime(pd.DataFrame())
        self.assertEqual(result["label"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
