"""Phase 7 read-only reply review API must honor workspace and staging gate."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from letterdesk_reply_api import install_reply_api

class ReplyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine=create_engine("sqlite://",poolclass=StaticPool,
                             connect_args={"check_same_thread":False})
        with engine.begin() as db:
            db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            db.exec_driver_sql("""CREATE TABLE public.ld_service_workspaces(
                 id TEXT,team_id INTEGER,service_key TEXT,is_active BOOLEAN)""")
            db.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
                 ('ws-one',1,'author',1),('ws-two',2,'shopify',1)""")
        def auth(request):
            key=request.headers.get("x-author-scout-key")
            if key=="one":return {"team_id":1,"account_id":10}
            if key=="two":return {"team_id":2,"account_id":20}
            raise HTTPException(401,"Authentication required")
        app=FastAPI()
        install_reply_api(app,engine,auth)
        cls.client=TestClient(app);cls.engine=engine
    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.engine.dispose()

    def test_preview_classification_requires_login(self):
        r=self.client.post("/api/v2/letterdesk/services/author/replies/classify",
                           json={"text":"Please unsubscribe"})
        self.assertEqual(r.status_code,401)

    def test_wrong_service_returns_not_found(self):
        r=self.client.post("/api/v2/letterdesk/services/shopify/replies/classify",
            headers={"x-author-scout-key":"one"},json={"text":"Yes"})
        self.assertEqual(r.status_code,404)

    def test_read_only_preview_does_not_store_or_send(self):
        r=self.client.post("/api/v2/letterdesk/services/author/replies/classify",
            headers={"x-author-scout-key":"one"},json={"text":"No thanks"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()["suggestion"]["outcome"],"negative")
        self.assertIn("no contact is changed",r.json()["note"].lower())

    def test_manual_reply_write_disabled_by_default(self):
        with patch.dict(os.environ,{"LETTERDESK_REPLY_WRITE_ENABLED":"false"}):
            r=self.client.post("/api/v2/letterdesk/services/author/replies/manual",
                 headers={"x-author-scout-key":"one"},
                 json={"conversation_id":"00000000-0000-0000-0000-000000000001",
                       "sender_email":"writer@example.org","text":"Yes",
                       "idempotency_key":"12345678901234567890"})
        self.assertEqual(r.status_code,403)

    def test_binding_changes_disabled_by_default(self):
        with patch.dict(os.environ,{"LETTERDESK_REPLY_WRITE_ENABLED":"false"}):
            r=self.client.post("/api/v2/letterdesk/services/author/replies/conversations/00000000-0000-0000-0000-000000000001/flow",
                 headers={"x-author-scout-key":"one"},json={"flow_id":None})
        self.assertEqual(r.status_code,403)

if __name__=="__main__":unittest.main()
