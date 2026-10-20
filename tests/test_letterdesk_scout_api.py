"""Phase 3 API: service isolation, bounded plans, no mutation by default."""
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from letterdesk_scout_api import install_scouting_api


class ScoutApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        with engine.begin() as db:
            db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            db.exec_driver_sql("""CREATE TABLE public.ld_service_workspaces
                (id TEXT,team_id INTEGER,service_key TEXT,is_active INTEGER)""")
            db.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
                ('w1',1,'author',1),('w2',2,'automation',1),('w3',1,'google-maps',1)""")
            db.exec_driver_sql("""CREATE TABLE public.ld_discovery_jobs
                (id TEXT,workspace_id TEXT,created_at TEXT,status TEXT)""")
        def auth(request):
            identity=request.headers.get("x-author-scout-key")
            if identity=="one":return {"team_id":1}
            if identity=="two":return {"team_id":2}
            raise HTTPException(401,"Sign in required")
        app=FastAPI()
        install_scouting_api(app,engine,auth)
        cls.client=TestClient(app)
        cls.engine=engine

    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.engine.dispose()

    def test_anonymous_cannot_access_query_plan(self):
        r=self.client.get("/api/v2/letterdesk/services/author/scout/plan")
        self.assertEqual(r.status_code,401)

    def test_team_cannot_plan_for_other_team_service(self):
        r=self.client.get("/api/v2/letterdesk/services/automation/scout/plan",headers={"x-author-scout-key":"one"})
        self.assertEqual(r.status_code,404)

    def test_queries_relevant_and_have_no_auto_email(self):
        r=self.client.get("/api/v2/letterdesk/services/author/scout/plan?niche=poets&city=Madrid&country=Spain",
                          headers={"x-author-scout-key":"one"})
        self.assertEqual(r.status_code,200,r.text)
        body=r.json()
        self.assertEqual(body["service_key"],"author")
        self.assertGreaterEqual(len(body["queries"]),4)
        self.assertTrue(any("Madrid" in x for x in body["queries"]))
        self.assertFalse(body["can_run"])
        self.assertTrue(any("never automatically" in x.lower() for x in body["notes"]))

    def test_unknown_mode_returns_not_found(self):
        r=self.client.get("/api/v2/letterdesk/services/fake/scout/plan",headers={"x-author-scout-key":"one"})
        self.assertEqual(r.status_code,404)

    def test_job_creation_is_disabled_without_explicit_flag(self):
        with patch.dict(os.environ,{"LETTERDESK_SCOUT_WRITE_ENABLED":"false"}):
            r=self.client.post("/api/v2/letterdesk/services/author/scout/jobs",
                headers={"x-author-scout-key":"one"},
                json={"niche":"emerging authors","city":"Madrid"})
        self.assertEqual(r.status_code,403)
        self.assertIn("not enabled",r.text)


if __name__=="__main__":
    unittest.main()
