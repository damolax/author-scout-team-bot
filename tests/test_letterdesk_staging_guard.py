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

    def test_email_login_route_cors_preflight_is_allowed(self):
        response = self.client.options(
            "/api/v2/letterdesk/auth/email",
            headers={
                "Origin": "https://letterdesk-v2-ui-preview.onrender.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            }
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "*"
        )

    def test_auth_endpoint_exists_and_rejects_foreign_origin(self):
        response = self.client.post(
            "/api/v2/letterdesk/auth/email",
            headers={"Origin": "https://untrusted.example"},
            json={"email": "qa@example.test", "password": "irrelevant123"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("origin", response.text.lower())

    def test_flow_simulation_requires_a_logged_in_team(self):
        response=self.client.post(
            "/api/v2/letterdesk/services/author/flows/validate",
            json={"serviceKey":"author","nodes":[],"edges":[]}
        )
        self.assertEqual(response.status_code,401)

    def test_flow_saving_is_blocked_by_default_in_preview(self):
        response=self.client.post(
            "/api/v2/letterdesk/services/author/flows",
            json={"name":"Sneaky writer","document":{}}
        )
        self.assertEqual(response.status_code,403)
        self.assertIn("read-only",response.text.lower())

    def test_flow_archival_and_updates_are_blocked_by_default(self):
        target="/api/v2/letterdesk/services/author/flows/00000000-0000-0000-0000-000000000001"
        for method,url in [("PUT",target),("POST",target+"/archive")]:
            with self.subTest(method=method):
                response=self.client.request(method,url,json={})
                self.assertEqual(response.status_code,403)

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
