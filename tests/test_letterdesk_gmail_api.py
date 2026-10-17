"""Phase 6 Gmail OAuth safety, sender verification and tenant isolation.

All tests are offline. They never connect to Google or send any email.
"""
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from letterdesk_gmail_api import (
    BASIC_SCOPES,ALIAS_SCOPE,alias_candidates,build_authorization_url,
    hash_state,normalize_email,install_gmail_connection_api,google_config,
)

class GmailConnectionTests(unittest.TestCase):
    def test_default_scope_does_not_request_restricted_alias_access(self):
        uri=build_authorization_url("client-id","https://test.onrender.com/api/v2/letterdesk/gmail/callback","example-state")
        self.assertIn("gmail.send",uri)
        self.assertNotIn("gmail.settings.basic",uri)
        self.assertIn("access_type=offline",uri)
        self.assertIn("state=example-state",uri)

    def test_explicit_alias_discovery_opt_in_adds_restricted_scope(self):
        uri=build_authorization_url("client-id","https://test.onrender.com/api/v2/letterdesk/gmail/callback",
                                    "example-state",True)
        self.assertIn("gmail.settings.basic",uri)

    def test_only_google_accepted_aliases_are_verified(self):
        data={"sendAs":[
            {"sendAsEmail":"alias@example.org","verificationStatus":"accepted","displayName":"Business"},
            {"sendAsEmail":"waiting@example.org","verificationStatus":"pending"},
            {"sendAsEmail":"primary@example.org","verificationStatus":"accepted"},
            {"sendAsEmail":"bad address","verificationStatus":"accepted"}
        ]}
        aliases=alias_candidates("primary@example.org",data,True)
        self.assertEqual(len(aliases),3)
        self.assertEqual([(a["email"],a["verified"]) for a in aliases],
                         [("primary@example.org",True),("alias@example.org",True),("waiting@example.org",False)])
        basic=alias_candidates("primary@example.org",data,False)
        self.assertEqual(len(basic),1)
        self.assertEqual(basic[0]["source"],"google_primary")

    def test_callback_must_match_declared_server_origin(self):
        config={
            "GOOGLE_CLIENT_ID":"test-client",
            "GOOGLE_CLIENT_SECRET":"test-only-secret",
            "LETTERDESK_GMAIL_SERVER_ORIGIN":"https://letterdesk-v2-api-preview.onrender.com",
            "LETTERDESK_GMAIL_FRONTEND_ORIGIN":"https://letterdesk-v2-ui-preview.onrender.com",
            "LETTERDESK_GMAIL_REDIRECT_URI":"https://attacker.example/api/v2/letterdesk/gmail/callback"
        }
        with patch.dict(os.environ,config):
            with self.assertRaises(HTTPException):
                google_config()
            os.environ["LETTERDESK_GMAIL_REDIRECT_URI"]=(
                "https://letterdesk-v2-api-preview.onrender.com/api/v2/letterdesk/gmail/callback")
            _,_,uri,frontend=google_config()
            self.assertEqual(frontend,"https://letterdesk-v2-ui-preview.onrender.com")
            self.assertIn("letterdesk-v2-api-preview.onrender.com",uri)

    def test_oauth_state_hashes_are_nonrecoverable(self):
        self.assertEqual(len(hash_state("random-nonce")),64)
        self.assertNotIn("random-nonce",hash_state("random-nonce"))

    @classmethod
    def setUpClass(cls):
        engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        with engine.begin() as c:
            c.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            c.exec_driver_sql("""CREATE TABLE public.ld_gmail_connections(
                 id TEXT,team_id INTEGER,web_account_id INTEGER,google_subject TEXT,
                 primary_email TEXT,refresh_token_encrypted TEXT,scopes TEXT,
                 status TEXT,verified_at TEXT,created_at TEXT,updated_at TEXT)""")
            c.exec_driver_sql("""CREATE TABLE public.ld_gmail_sender_identities(
                id TEXT,connection_id TEXT,verification_status TEXT,email TEXT)""")
        def auth(req):
            key=req.headers.get("x-author-scout-key")
            if key=="team1":return {"team_id":1,"account_id":11}
            if key=="team2":return {"team_id":2,"account_id":22}
            raise HTTPException(401,"Sign in required")
        app=FastAPI()
        install_gmail_connection_api(app,engine,auth)
        cls.client=TestClient(app)
        cls.engine=engine

    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.engine.dispose()

    def test_only_authenticated_team_can_see_connections(self):
        r=self.client.get("/api/v2/letterdesk/gmail/connections")
        self.assertEqual(r.status_code,401)
        r=self.client.get("/api/v2/letterdesk/gmail/connections",headers={"x-author-scout-key":"team1"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["connections"],[])
        self.assertFalse(r.json()["oauth_enabled"])

    def test_connection_disabled_without_explicit_staging_authorization(self):
        with patch.dict(os.environ,{"LETTERDESK_GMAIL_OAUTH_ENABLED":"false"}):
            r=self.client.post("/api/v2/letterdesk/gmail/connect",
                               headers={"x-author-scout-key":"team1"},json={"requestAliasVerification":True})
        self.assertEqual(r.status_code,403)
        self.assertIn("disabled",r.text)

    def test_email_normalization_rejects_nonemails(self):
        self.assertEqual(normalize_email("  Example@Gmail.com "), "example@gmail.com")
        for s in ("foo","a@@gmail.com","a <b@example.com>"):
            with self.assertRaises(ValueError):
                normalize_email(s)

if __name__=="__main__":unittest.main()
