from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from backend.main import app


class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_endpoint_reports_local_app(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["application"], "Rupee Prediction System")
        self.assertIn("version", body)
        self.assertIn(body["readiness"], {"data_available", "data_refresh_required"})
        self.assertIn("market_data_present", body)

    def test_dashboard_route_is_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Rupee Prediction System", response.text)

    def test_status_without_data_is_actionable(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data_available", body)
        self.assertIn("sources", body)

    def test_target_source_endpoint_is_available(self):
        response = self.client.get("/api/target-source")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["target_source"], {"yahoo_proxy", "fbil_csv", "rbi_dbie_mirror"})


if __name__ == "__main__":
    unittest.main()
