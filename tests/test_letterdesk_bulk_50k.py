"""High-volume no-send acceptance tests for streaming importer and job signatures."""
import csv
import hashlib
import io
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from openpyxl import Workbook
from letterdesk_service_import import iter_service_chunks,MAX_ROWS,MAX_BYTES
from letterdesk_bulk_import import checksum_token,verify_checksum,staging_enabled,writes_enabled,PART_BYTES

class Bulk50KTests(unittest.TestCase):
    def make_csv(self,total,service="author"):
        out=io.StringIO()
        wr=csv.writer(out)
        wr.writerow(["Author","Email","Website","Subject","Message01","Message0101Yes","Message0101No","Source URL"])
        for i in range(total):
            wr.writerow([f"Author {i}",f"writer{i}@example.test",f"https://books{i}.test",
                        f"Relevant work {i}",f"Hello about book {i}",
                        "Thanks for replying","Thanks for clarifying",f"https://books{i}.test/contact"])
        return out.getvalue().encode()
    def test_10000_upload_streams_without_losing_messages(self):
        parts=list(iter_service_chunks(self.make_csv(10000),"writers.csv","author"))
        self.assertEqual(len(parts),20)
        self.assertEqual(sum(len(p["rows"])+len(p["issues"]) for p in parts),10000)
        self.assertEqual(parts[-1]["rows"][-1]["row"],10001)
        self.assertEqual(parts[0]["rows"][0]["branches"]["Message0101Yes"],"Thanks for replying")
    def test_50000_record_limit_and_unique_identity_across_chunks(self):
        seen=0;pages=0
        for page in iter_service_chunks(self.make_csv(50000),"authors.csv","author"):
            seen+=len(page["rows"])+len(page["issues"]);pages+=1
        self.assertEqual((seen,pages),(50000,100))
        dupe=self.make_csv(650)
        rows=dupe.decode().splitlines()
        rows[-1]=rows[2]
        results=list(iter_service_chunks(("\n".join(rows)+"\n").encode(),"authors.csv","author"))
        self.assertEqual(len(results),2)
        self.assertIn("Duplicate in this file",results[-1]["issues"][-1]["errors"])
    def test_50001_records_rejected_not_truncated(self):
        with self.assertRaisesRegex(ValueError,"50,000"):
            for page in iter_service_chunks(self.make_csv(50001),"authors.csv","author"):
                self.assertLessEqual(len(page["rows"]),500)
    def test_10000_excel_rows_streamed_in_batches(self):
        wb=Workbook(write_only=True)
        sheet=wb.create_sheet("Store leads")
        sheet.append(["Name","Email","Shopify Store URL","Store Issue","First Message","Message0101Yes"])
        for i in range(10000):
            sheet.append([f"Store {i}",f"shop{i}@example.test",f"https://store{i}.test",
                          "Mobile shopping navigation","Specific research note","Thanks for asking"])
        blob=io.BytesIO();wb.save(blob)
        parts=list(iter_service_chunks(blob.getvalue(),"stores.xlsx","shopify",500))
        self.assertEqual(len(parts),20)
        self.assertEqual(sum(len(x["rows"]) for x in parts),10000)
        self.assertEqual(parts[0]["rows"][0]["first_message"],"Specific research note")
        self.assertIn("Message0101Yes",parts[-1]["rows"][-1]["branches"])
    def test_confirmation_bound_to_team_workspace_file_and_summary(self):
        with patch.dict(os.environ,{"APP_SECRET":"X"*64}):
            totals={"rows_total":10000,"created":9840,"suppressed":160}
            with patch("letterdesk_bulk_import.time.time",return_value=1000):
                token=checksum_token(9,"workspace-a","job-a","a"*64,totals)
            with patch("letterdesk_bulk_import.time.time",return_value=1050):
                verify_checksum(token,9,"workspace-a","job-a","a"*64,totals)
                for kwargs in [
                    (10,"workspace-a","job-a","a"*64,totals),
                    (9,"workspace-b","job-a","a"*64,totals),
                    (9,"workspace-a","job-a","b"*64,totals),
                    (9,"workspace-a","job-a","a"*64,{"rows_total":9999}),
                ]:
                    with self.assertRaises(HTTPException):
                        verify_checksum(token,*kwargs)
            with patch("letterdesk_bulk_import.time.time",return_value=5000):
                with self.assertRaises(HTTPException):
                    verify_checksum(token,9,"workspace-a","job-a","a"*64,totals)
    def test_protected_staging_does_not_upload_or_send_by_default(self):
        with patch.dict(os.environ,{"LETTERDESK_BULK_UPLOAD_ENABLED":"false",
                                     "LETTERDESK_IMPORT_WRITE_ENABLED":"false"}):
            self.assertFalse(staging_enabled())
            self.assertFalse(writes_enabled())
        self.assertEqual(PART_BYTES,1048576)
        self.assertEqual(MAX_ROWS,50000)
        self.assertEqual(MAX_BYTES,67108864)

if __name__=="__main__":unittest.main()
