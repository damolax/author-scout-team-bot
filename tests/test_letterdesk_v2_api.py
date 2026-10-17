"""Isolated API tests: no Gmail sending and no production Neon access."""
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from letterdesk_v2_api import install_letterdesk_v2_routes


class LetterDeskV2ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        with engine.begin() as db:
            db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            ddl = [
                "CREATE TABLE public.ld_service_workspaces (id TEXT, team_id INTEGER, service_key TEXT, display_name TEXT, is_active INTEGER)",
                "CREATE TABLE public.ld_leads (id TEXT, team_id INTEGER, name TEXT, kind TEXT, email TEXT, website TEXT, maps_url TEXT, country TEXT, city TEXT, source_url TEXT, contact_verification TEXT)",
                "CREATE TABLE public.ld_opportunities (id TEXT, workspace_id TEXT, lead_id TEXT, status TEXT, fit_score INTEGER, evidence_summary TEXT, created_at TEXT)",
                "CREATE TABLE public.ld_conversations (id TEXT, opportunity_id TEXT, status TEXT)",
                "CREATE TABLE public.ld_message_records (id TEXT, conversation_id TEXT, status TEXT)",
            ]
            for sql in ddl:
                db.exec_driver_sql(sql)
            db.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
                ('a1',1,'author','Author Scouting',1),
                ('a2',2,'author','Author Scouting',1),
                ('b1',1,'automation','Automation Scouting',1)""")
            db.exec_driver_sql("""INSERT INTO public.ld_leads VALUES
                ('l1',1,'Example Author','person','author@example.org','https://example.org',NULL,'Spain',NULL,NULL,'imported_unverified'),
                ('l2',2,'Private Team Author','person','different@example.org',NULL,NULL,'Spain',NULL,NULL,'unverified'),
                ('l3',1,'Example Company','business','hello@example.net','https://example.net',NULL,'France',NULL,NULL,'unverified')""")
            db.exec_driver_sql("""INSERT INTO public.ld_opportunities VALUES
                ('o1','a1','l1','research_needed',NULL,NULL,'2026-01-01'),
                ('o2','a2','l2','research_needed',NULL,NULL,'2026-01-01'),
                ('o3','b1','l3','research_needed',75,'Evidence-backed finding','2026-01-01')""")
            db.exec_driver_sql("""INSERT INTO public.ld_conversations VALUES ('c1','o1','awaiting_reply')""")
            db.exec_driver_sql("""INSERT INTO public.ld_message_records VALUES ('m1','c1','sent')""")

        def fake_auth(req):
            key = req.headers.get("x-author-scout-key")
            if key == "team1":
                return {"team_id": 1}
            if key == "team2":
                return {"team_id": 2}
            raise HTTPException(status_code=401, detail="Sign in required")

        app = FastAPI()
        install_letterdesk_v2_routes(app, engine, fake_auth)
        cls.client = TestClient(app)
        cls.engine = engine

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()

    def test_no_access_without_auth(self):
        result = self.client.get("/api/v2/letterdesk/services")
        self.assertEqual(result.status_code, 401)

    def test_service_workspaces_isolated_to_current_team(self):
        r1 = self.client.get("/api/v2/letterdesk/services", headers={"x-author-scout-key": "team1"})
        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(len(r1.json()["services"]), 2)
        author = next(r for r in r1.json()["services"] if r["service_key"] == "author")
        self.assertEqual(author["prospect_count"], 1)
        self.assertEqual(author["sent_count"], 1)
        r2 = self.client.get("/api/v2/letterdesk/services", headers={"x-author-scout-key": "team2"})
        self.assertEqual(len(r2.json()["services"]), 1)

    def test_lead_details_do_not_leak_between_teams(self):
        headers = {"x-author-scout-key": "team1"}
        result = self.client.get("/api/v2/letterdesk/services/author/leads", headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["total"], 1)
        self.assertEqual(result.json()["leads"][0]["name"], "Example Author")
        self.assertNotIn("Private Team Author", result.text)
        other = self.client.get("/api/v2/letterdesk/services/author/leads", headers={"x-author-scout-key": "team2"})
        self.assertEqual(other.json()["leads"][0]["name"], "Private Team Author")

    def test_service_specific_leads_and_search(self):
        headers = {"x-author-scout-key": "team1"}
        result = self.client.get("/api/v2/letterdesk/services/automation/leads", headers=headers)
        self.assertEqual(result.json()["total"], 1)
        result = self.client.get("/api/v2/letterdesk/services/automation/leads?search=nonexistent", headers=headers)
        self.assertEqual(result.json()["total"], 0)
        result = self.client.get("/api/v2/letterdesk/services/automation/leads?search=example.net", headers=headers)
        self.assertEqual(result.json()["total"], 1)

    def test_reject_unknown_service(self):
        r = self.client.get("/api/v2/letterdesk/services/guess/leads", headers={"x-author-scout-key": "team1"})
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
