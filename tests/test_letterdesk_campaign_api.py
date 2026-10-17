"""Phase 6 no-send campaign policy tests."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from letterdesk_campaign_api import safe_email,validate_delivery_policy,install_campaign_api

class CampaignPolicyTests(unittest.TestCase):
    def test_permission_basis_requires_specific_evidence(self):
        with self.assertRaises(HTTPException):
            validate_delivery_policy("contact@example.net","explicit_opt_in","")
        with self.assertRaises(HTTPException):
            validate_delivery_policy("contact@example.net","public_email_only",
                                     "Business email was publicly visible")
        with self.assertRaises(HTTPException):
            validate_delivery_policy("not-an-email","existing_customer",
                                     "Existing customer relationship")
        email,evidence=validate_delivery_policy("CONTACT@EXAMPLE.NET","existing_customer",
                                               "Existing customer relationship with requested updates")
        self.assertEqual(email,"contact@example.net")
        self.assertTrue(evidence.startswith("Existing"))

    @classmethod
    def setUpClass(cls):
        eng=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        with eng.begin() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            conn.exec_driver_sql("""CREATE TABLE public.ld_service_workspaces(
              id TEXT,team_id INTEGER,service_key TEXT,is_active INTEGER)""")
            conn.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
              ('a1',1,'author',1),('b2',2,'shopify',1)""")
        def auth(req):
            key=req.headers.get("x-author-scout-key")
            if key=="team1":return {"team_id":1,"account_id":11}
            if key=="team2":return {"team_id":2,"account_id":22}
            raise HTTPException(401,"Unauthorized")
        app=FastAPI()
        install_campaign_api(app,eng,auth)
        cls.client=TestClient(app);cls.eng=eng
    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.eng.dispose()

    def test_campaigns_require_login(self):
        r=self.client.get("/api/v2/letterdesk/services/author/campaigns")
        self.assertEqual(r.status_code,401)

    def test_cannot_access_wrong_team_service(self):
        r=self.client.get("/api/v2/letterdesk/services/shopify/campaigns",
            headers={"x-author-scout-key":"team1"})
        self.assertEqual(r.status_code,404)

    def test_campaign_creating_requires_separate_feature_flag(self):
        with patch.dict(os.environ,{"LETTERDESK_CAMPAIGN_WRITE_ENABLED":"false"}):
            r=self.client.post("/api/v2/letterdesk/services/author/campaigns",
                  headers={"x-author-scout-key":"team1"},
                  json={"name":"Approved Author Outreach","sender_identity_id":"00000000-0000-0000-0000-000000000001"})
        self.assertEqual(r.status_code,403)
        self.assertIn("disabled",r.text.lower())

    def test_no_send_endpoint_exists(self):
        r=self.client.post("/api/v2/letterdesk/services/author/campaigns/send",
            headers={"x-author-scout-key":"team1"},json={})
        self.assertNotEqual(r.status_code,200)

if __name__=="__main__":unittest.main()
