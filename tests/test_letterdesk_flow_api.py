"""Phase 5 authenticated flow API: validation, no-send simulation, and write lock."""
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from letterdesk_flow_engine import starter_flow
from letterdesk_flow_api import install_flow_api

class FlowApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        with engine.begin() as c:
            c.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            c.exec_driver_sql("""CREATE TABLE public.ld_service_workspaces
                 (id TEXT,team_id INTEGER,service_key TEXT,is_active INTEGER)""")
            c.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
                 ('team-one-author',1,'author',1),
                 ('team-two-author',2,'author',1),
                 ('team-one-automation',1,'automation',1)""")
            c.exec_driver_sql("""CREATE TABLE public.ld_flow_designs
                 (id TEXT,workspace_id TEXT,name TEXT,status TEXT,revision INTEGER,
                  language TEXT,document TEXT,created_at TEXT,updated_at TEXT)""")
        def auth(request):
            key=request.headers.get("x-author-scout-key")
            if key=="team-one":return {"team_id":1}
            if key=="team-two":return {"team_id":2}
            raise HTTPException(401,"Sign in required")
        app=FastAPI()
        install_flow_api(app,engine,auth)
        cls.client=TestClient(app)
        cls.engine=engine
    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()

    def test_starter_requires_login(self):
        r=self.client.get("/api/v2/letterdesk/services/author/flows/starter")
        self.assertEqual(r.status_code,401)

    def test_no_cross_service_access(self):
        r=self.client.get("/api/v2/letterdesk/services/shopify/flows/starter",
                          headers={"x-author-scout-key":"team-one"})
        self.assertEqual(r.status_code,404)

    def test_authenticated_starter_is_valid(self):
        r=self.client.get("/api/v2/letterdesk/services/author/flows/starter",
                          headers={"x-author-scout-key":"team-one"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["document"]["serviceKey"],"author")
        self.assertEqual(r.json()["document"]["nodes"][0]["code"],"Message01")

    def test_validation_read_only_with_errors(self):
        doc=starter_flow("author")
        r=self.client.post("/api/v2/letterdesk/services/author/flows/validate",
                          headers={"x-author-scout-key":"team-one"},json=doc)
        self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(r.json()["ok"])
        doc["nodes"][0]["reviewRequired"]=False
        r=self.client.post("/api/v2/letterdesk/services/author/flows/validate",
                          headers={"x-author-scout-key":"team-one"},json=doc)
        self.assertFalse(r.json()["ok"])

    def test_simulation_has_no_sending_side_effect(self):
        r=self.client.post("/api/v2/letterdesk/services/author/flows/simulate",
                          headers={"x-author-scout-key":"team-one"},json={
                            "document":starter_flow("author"),
                            "current":"Message0101Yes",
                            "outcome":"no","messageCount":1,
                            "noReplyFollowups":0})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["result"]["nextCode"],"Message0201No")
        self.assertEqual(r.json()["result"]["action"],"draft_for_review")

    def test_template_write_disabled_and_publishing_unsupported(self):
        with patch.dict(os.environ,{"LETTERDESK_FLOW_WRITE_ENABLED":"false"}):
            r=self.client.post("/api/v2/letterdesk/services/author/flows",
                   headers={"x-author-scout-key":"team-one"},
                   json={"name":"Test design","document":starter_flow("author")})
            self.assertEqual(r.status_code,403)
            self.assertIn("disabled",r.text.lower())
            r=self.client.put("/api/v2/letterdesk/services/author/flows/00000000-0000-0000-0000-000000000001",
                   headers={"x-author-scout-key":"team-one"},
                   json={"expectedRevision":1,"name":"Edited","document":starter_flow("author")})
            self.assertEqual(r.status_code,403)
        r=self.client.post("/api/v2/letterdesk/services/author/flows/00000000-0000-0000-0000-000000000001/publish",
                    headers={"x-author-scout-key":"team-one"},json={})
        self.assertEqual(r.status_code,405)

if __name__=="__main__":unittest.main()
