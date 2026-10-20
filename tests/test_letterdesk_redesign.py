"""Redesign regression: import comparison, localization and decisions never auto-send."""
import unittest
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient

from letterdesk_import_diff import compare_record
from letterdesk_language import language_recommendation
from letterdesk_field_review_api import normalize_decision,install_field_review_api

class RedesignTests(unittest.TestCase):
    def test_exact_repeat_does_not_change_existing_record(self):
        previous={"name":"An Author","email":"author@example.org","website":"https://writer.example.org",
                  "country":"Spain","first_message":"Hello!","branches":{"Message0101Yes":"Thank you"},
                  "service_details":{"book_titles":"Novel One"}}
        copy=dict(previous)
        self.assertTrue(compare_record(copy,previous)["exact"])
        self.assertEqual(compare_record(copy,previous)["differences"],[])
        copy["first_message"]="Hello, I read your interview."
        copy["service_details"]={"book_titles":"Novel One","recent_activity":"Interview today"}
        changes=compare_record(copy,previous)
        self.assertEqual(changes["changed_fields"],1)
        self.assertEqual(changes["new_fields"],1)
        self.assertEqual({x["field"] for x in changes["differences"]},
                         {"first_message","service_details.recent_activity"})

    def test_missing_upload_columns_never_erase_existing_values(self):
        previous={"name":"An Author","email":"author@example.org","website":"https://author.example",
                  "first_message":"Originally approved draft"}
        incoming={"name":"An Author","email":"author@example.org","website":"","first_message":""}
        self.assertTrue(compare_record(incoming,previous)["exact"])

    def test_preferred_language_wins_over_country_and_hint_is_not_verified(self):
        preferred=language_recommendation("Spain","ca")
        self.assertEqual(preferred["language"],"ca")
        self.assertFalse(preferred["needs_confirmation"])
        unknown=language_recommendation("Spain")
        self.assertEqual(unknown["language"],"es")
        self.assertTrue(unknown["needs_confirmation"])
        self.assertIn("ca",unknown["alternatives"])
        self.assertEqual(language_recommendation("Nigeria")["source"],"country_hint_only")

    def test_field_review_does_not_allow_email_replacement_or_injection(self):
        base={"field":"first_message","decision":"accepted","previous":"Old message",
              "incoming":"New message","source_sha256":"a"*64,"row":7}
        self.assertEqual(normalize_decision(base)[0],"first_message")
        for field in ("email","sender_email","status","branches.Message0201Yes","notes; DELETE"):
            with self.subTest(field=field):
                with self.assertRaises(HTTPException):
                    normalize_decision({**base,"field":field})

    def test_anonymous_or_disabled_review_denied(self):
        def auth(request):
            if request.headers.get("x-author-scout-key")=="signed":
                return {"team_id":1,"account_id":4}
            raise HTTPException(401,"Sign in required")
        app=FastAPI()
        install_field_review_api(app,None,auth)
        client=TestClient(app)
        url="/api/v2/letterdesk/services/author/prospects/00000000-0000-0000-0000-000000000001/review-field"
        body={"field":"name","decision":"accepted","previous":"Jane","incoming":"Janet",
              "source_sha256":"a"*64,"row":3}
        self.assertEqual(client.post(url,json=body).status_code,401)
        with patch.dict("os.environ",{"LETTERDESK_IMPORT_WRITE_ENABLED":"false"}):
            self.assertEqual(client.post(url,json=body,headers={"x-author-scout-key":"signed"}).status_code,403)
        client.close()

if __name__=="__main__":unittest.main()
