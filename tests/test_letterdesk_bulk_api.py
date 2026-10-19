"""50k bulk API access control and default no-write staging tests."""
import os
import unittest
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from letterdesk_bulk_api import install_bulk_import_api

class BulkUploadAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
        with engine.begin() as db:
            db.exec_driver_sql("ATTACH DATABASE ':memory:' AS public")
            db.exec_driver_sql("""CREATE TABLE public.ld_service_workspaces(
                id TEXT,team_id INTEGER,service_key TEXT,is_active BOOLEAN)""")
            db.exec_driver_sql("""INSERT INTO public.ld_service_workspaces VALUES
                ('ws-author',1,'author',1),('ws-shopify',2,'shopify',1)""")
        def auth(request):
            token=request.headers.get("x-author-scout-key")
            if token=="team1":return {"team_id":1,"account_id":101}
            if token=="team2":return {"team_id":2,"account_id":202}
            raise HTTPException(401,"Authentication required")
        app=FastAPI()
        install_bulk_import_api(app,engine,auth)
        cls.client=TestClient(app)
        cls.engine=engine

    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.engine.dispose()

    def test_unauthorized_cannot_start_upload(self):
        result=self.client.post("/api/v2/letterdesk/services/author/bulk-uploads",
          json={"filename":"test.csv","size":100,"sha256":"a"*64})
        self.assertEqual(result.status_code,401)

    def test_team_cannot_stage_file_in_another_team_service(self):
        result=self.client.post("/api/v2/letterdesk/services/shopify/bulk-uploads",
          headers={"x-author-scout-key":"team1"},
          json={"filename":"test.csv","size":100,"sha256":"a"*64})
        self.assertEqual(result.status_code,404)

    def test_bulk_writes_off_by_default_even_with_signin(self):
        with patch.dict(os.environ,{"LETTERDESK_BULK_UPLOAD_ENABLED":"false"}):
            result=self.client.post("/api/v2/letterdesk/services/author/bulk-uploads",
              headers={"x-author-scout-key":"team1"},
              json={"filename":"test.csv","size":100,"sha256":"a"*64})
            self.assertEqual(result.status_code,403)
            chunk=self.client.post(
              "/api/v2/letterdesk/services/author/bulk-uploads/00000000-0000-0000-0000-000000000001/parts/0",
              headers={"x-author-scout-key":"team1","content-type":"application/octet-stream"},
              content=b"sample data")
            self.assertEqual(chunk.status_code,403)
            confirm=self.client.post(
              "/api/v2/letterdesk/services/author/bulk-uploads/00000000-0000-0000-0000-000000000001/confirm",
              headers={"x-author-scout-key":"team1"},json={"confirmation_token":"fake"})
            self.assertEqual(confirm.status_code,403)

if __name__=="__main__":unittest.main()
