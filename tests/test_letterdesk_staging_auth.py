"""Regression tests for mobile-safe staging login, no real Neon users."""
import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from letterdesk_staging_auth import install_staging_email_auth

ORIGIN = "https://letterdesk-v2-ui-preview.onrender.com"
NEON = "https://ep-test.neonauth.c-7.us-east-2.aws.neon.tech/my_db/auth"


class FakeResponse:
    def __init__(self, status, data=None):
        self.status_code = status
        self.data = data or {}

    def json(self):
        return self.data


class StagingAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {
            "NEON_AUTH_URL": NEON,
            "LETTERDESK_STAGING_FRONTEND_ORIGIN": ORIGIN,
        }
        with patch.dict(os.environ, env):
            app = FastAPI()
            install_staging_email_auth(
                app,
                neon_session=lambda t: {"user_id":"synthetic-user", "email":"qa@example.test", "name":"Test"} if t=="test-session" else None,
                get_or_create_account=lambda p: {"id": 1, "display_name":"Test"},
                issue_app_session=lambda p: "safe-app-session",
            )
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_cross_site_origin_rejected(self):
        r = self.client.post("/api/v2/letterdesk/auth/email", json={
            "email": "qa@example.test", "password":"Example-TestPass!"
        },headers={"origin":"https://other.example"})
        self.assertEqual(r.status_code,403)

    def test_invalid_email_rejected(self):
        r = self.client.post("/api/v2/letterdesk/auth/email", json={
            "email":"not-an-email","password":"Example-TestPass!"
        },headers={"origin":ORIGIN})
        self.assertEqual(r.status_code,400)

    def test_valid_email_login_returns_app_session_without_password_or_neon_token(self):
        fake=MagicMock()
        fake.__aenter__=AsyncMock(return_value=fake)
        fake.__aexit__=AsyncMock(return_value=None)
        fake.post=AsyncMock(return_value=FakeResponse(200,{"token":"test-session","user":{"id":"synthetic-user"}}))
        with patch("letterdesk_staging_auth.httpx.AsyncClient", return_value=fake):
            r = self.client.post("/api/v2/letterdesk/auth/email", json={
                "mode":"signin","email":"qa@example.test","password":"Example-TestPass!"
            },headers={"origin":ORIGIN})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["session"],"safe-app-session")
        self.assertNotIn("test-session",r.text)
        self.assertNotIn("Example-TestPass!",r.text)
        target=fake.post.await_args.args[0]
        self.assertTrue(target.endswith("/sign-in/email"))

    def test_unverified_token_cannot_open_letterdesk(self):
        fake=MagicMock()
        fake.__aenter__=AsyncMock(return_value=fake)
        fake.__aexit__=AsyncMock(return_value=None)
        fake.post=AsyncMock(return_value=FakeResponse(200,{"token":"unknown-token"}))
        with patch("letterdesk_staging_auth.httpx.AsyncClient",return_value=fake):
            r=self.client.post("/api/v2/letterdesk/auth/email",json={
                "mode":"signin","email":"qa@example.test","password":"Example-TestPass!"
            },headers={"origin":ORIGIN})
        self.assertEqual(r.status_code,401)

    def test_bad_credentials_not_accepted(self):
        fake=MagicMock()
        fake.__aenter__=AsyncMock(return_value=fake)
        fake.__aexit__=AsyncMock(return_value=None)
        fake.post=AsyncMock(return_value=FakeResponse(401,{"error":"invalid"}))
        with patch("letterdesk_staging_auth.httpx.AsyncClient",return_value=fake):
            r=self.client.post("/api/v2/letterdesk/auth/email",json={
                "mode":"signin","email":"qa@example.test","password":"Example-TestPass!"
            },headers={"origin":ORIGIN})
        self.assertEqual(r.status_code,401)
        self.assertNotIn("invalid",r.text)


if __name__ == "__main__":
    unittest.main()
