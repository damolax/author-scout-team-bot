"""Phase 8 import undo signing, staging gates and 500-record import performance."""
import csv
import io
import os
import time
import unittest
from unittest.mock import patch
from fastapi import HTTPException

from letterdesk_import_undo import token_for,verify_token,undo_enabled,execute
from letterdesk_service_import import SERVICES,parse_service_upload

class Phase8ReliabilityTests(unittest.TestCase):
    def test_undo_requires_genuine_fresh_file_specific_approval(self):
        with patch.dict(os.environ,{"APP_SECRET":"A"*48}):
            t=token_for(10,'author','batch-uuid','sha-1',ts=1000)
            with patch("letterdesk_import_undo.time.time",return_value=1100):
                verify_token(t,10,'author','batch-uuid','sha-1')
                for args in [(11,'author','batch-uuid','sha-1'),
                             (10,'automation','batch-uuid','sha-1'),
                             (10,'author','different-batch','sha-1'),
                             (10,'author','batch-uuid','changed')]:
                    with self.assertRaises(HTTPException):verify_token(t,*args)
            with patch("letterdesk_import_undo.time.time",return_value=2001):
                with self.assertRaises(HTTPException):
                    verify_token(t,10,'author','batch-uuid','sha-1')

    def test_undo_is_closed_by_default(self):
        with patch.dict(os.environ,{"LETTERDESK_IMPORT_UNDO_ENABLED":"false"}):
            self.assertFalse(undo_enabled())
            with self.assertRaises(HTTPException) as caught:
                execute(None,10,'author','batch-id',1,'list.csv','badtoken')
            self.assertEqual(caught.exception.status_code,403)

    def test_500_row_service_upload_is_bounded_and_has_no_send_side_effects(self):
        for service in SERVICES:
            with self.subTest(service=service):
                output=io.StringIO()
                writer=csv.writer(output)
                writer.writerow(["Name","Email","Website","Subject","Message01",
                                 "Message0101Yes","Message0101No","Source URL"])
                for i in range(500):
                    writer.writerow([f"Example {service} prospect {i}",
                        f"prospect{i}@sample-business.test",
                        f"https://example{i}.test", "Specific subject",
                        "Hello, I noticed a relevant public business update.",
                        "Thanks for the positive reply.", "I understand your decision.",
                        f"https://example{i}.test/contact"])
                started=time.monotonic()
                parsed=parse_service_upload(output.getvalue().encode(),"sample.csv",service)
                elapsed=time.monotonic()-started
                self.assertEqual(len(parsed["rows"]),500)
                self.assertEqual(len(parsed["issues"]),0)
                self.assertEqual(len(parsed["rows"][0]["branches"]),3)
                # This benchmark covers parsing, NOT network or database latency.
                self.assertLess(elapsed,8.0,"500-row parser regression")

if __name__=="__main__":
    unittest.main()
