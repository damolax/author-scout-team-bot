"""Phase 4 API integration: preview-only by default, isolated from other teams."""
import csv
import io
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from letterdesk_import_api import install_import_api

class ImportApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine=create_engine("sqlite://",poolclass=StaticPool,
            connect_args={"check_same_thread":False})
        with engine.begin() as c:
            c.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            c.exec_driver_sql("""CREATE TABLE public.ld_service_workspaces
                (id TEXT,team_id integer,service_key TEXT,is_active boolean)""")
            c.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
                ('a',1,'author',1),('b',2,'automation',1)""")
        def auth(r):
            sid=r.headers.get("x-author-scout-key")
            if sid=="one":return {"team_id":1}
            if sid=="two":return {"team_id":2}
            raise HTTPException(401,"Sign in")
        app=FastAPI()
        install_import_api(app,engine,auth)
        cls.client=TestClient(app)
        cls.engine=engine
    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()
    @staticmethod
    def sample():
        buffer=io.StringIO()
        writer=csv.writer(buffer)
        writer.writerow(["Author","Email","Message 01","Message0101Yes"])
        writer.writerow(["Example Author","author@books.test","Hello","Thanks for replying"])
        return buffer.getvalue().encode()

    def test_cannot_preview_without_authenticated_team(self):
        r=self.client.post("/api/v2/letterdesk/services/author/imports/preview",
             files={"file":("test.csv",self.sample(),"text/csv")})
        self.assertEqual(r.status_code,401)

    def test_cannot_preview_cross_team(self):
        r=self.client.post("/api/v2/letterdesk/services/automation/imports/preview",
             headers={"x-author-scout-key":"one"},
             files={"file":("test.csv",self.sample(),"text/csv")})
        self.assertEqual(r.status_code,404)

    def test_can_download_author_template(self):
        r=self.client.get("/api/v2/letterdesk/services/author/imports/template.csv",
             headers={"x-author-scout-key":"one"})
        self.assertEqual(r.status_code,200,r.text)
        self.assertIn("Message0101Yes",r.text)
        self.assertIn("First Message",r.text)

    def test_preview_does_not_write_and_confirmation_is_locked(self):
        with patch("letterdesk_import_api.plan") as planned,patch.dict(os.environ,{
            "APP_SECRET":"staging-unit-test-secret-really-at-least-thirty-two",
            "LETTERDESK_IMPORT_WRITE_ENABLED":"false"
        }):
            row={"row":2,"name":"Example Author","email":"author@books.test",
                 "website":"","source_url":"","disposition":"created",
                 "reason":"","first_message":"Hello",
                 "branches":{"Message01":"Hello","Message0101Yes":"Thanks"}}
            summary={"created":1,"linked":0,"suppressed":0,
                     "invalid":0,"skipped_duplicate":0,"rows_total":1}
            planned.return_value=([row],summary)
            p=self.client.post("/api/v2/letterdesk/services/author/imports/preview",
                headers={"x-author-scout-key":"one"},
                files={"file":("a.csv",self.sample(),"text/csv")})
            self.assertEqual(p.status_code,200,p.text)
            self.assertFalse(p.json()["write_enabled"])
            self.assertEqual(p.json()["sample"][0]["branches"],["Message01","Message0101Yes"])
            self.assertIsInstance(p.json()["preview_token"],str)
            c=self.client.post("/api/v2/letterdesk/services/author/imports/confirm",
                headers={"x-author-scout-key":"one"},
                data={"preview_token":p.json()["preview_token"]},
                files={"file":("a.csv",self.sample(),"text/csv")})
            self.assertEqual(c.status_code,403)
            self.assertIn("disabled",c.text)

if __name__=="__main__":
    unittest.main()
