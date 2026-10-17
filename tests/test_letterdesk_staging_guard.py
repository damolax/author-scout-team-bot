"""Verify isolated Letter Desk preview forbids every sending/mutation endpoint."""
import os
import unittest
from fastapi.testclient import TestClient

os.environ["LETTERDESK_STAGING_ISOLATED"] = "true"
os.environ["LETTERDESK_V2_ENABLED"] = "true"
os.environ["SOURCE_INDEX_ENABLED"] = "false"
os.environ["NEON_AUTH_URL"] = "https://ep-test.neonauth.c-7.us-east-2.aws.neon.tech/my_db/auth"
os.environ["LETTERDESK_STAGING_FRONTEND_ORIGIN"] = "https://letterdesk-v2-ui-preview.onrender.com"
from bot_main_v3 import app


class StagingIsolationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def test_health_allowed(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_requires_auth_for_service_data(self):
        response = self.client.get("/api/v2/letterdesk/services")
        self.assertEqual(response.status_code, 401)

    def test_sending_and_mutations_blocked_even_with_invalid_credentials(self):
        cases = [
            ("POST", "/api/v1/messages/1/send"),
            ("POST", "/api/v1/messages/1/send-smtp"),
            ("POST", "/api/v1/research/jobs"),
            ("POST", "/telegram/webhook"),
            ("POST", "/api/v1/messages/import"),
            ("GET", "/auth/google/start"),
            ("GET", "/oauth/google/start"),
        ]
        for method, path in cases:
            with self.subTest(method=method, path=path):
                r = self.client.request(method, path)
                self.assertEqual(r.status_code, 403, r.text)
                self.assertIn("read-only", r.text.lower())


if __name__ == "__main__":
    unittest.main()
