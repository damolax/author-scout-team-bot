"""Tests: no provider calls, no database writes, no outbound email."""
import csv
import io
import unittest
from unittest.mock import patch
from openpyxl import Workbook

from letterdesk_service_import import SERVICES,parse_service_upload,import_headers,MAX_ROWS
from letterdesk_import_plan import file_token,verify_token,plan
from fastapi import HTTPException

class ImportPhase4Tests(unittest.TestCase):
    def csv_data(self,headers,rows):
        buf=io.StringIO()
        w=csv.writer(buf);w.writerow(headers);w.writerows(rows)
        return buf.getvalue().encode()

    def test_six_service_templates_load(self):
        self.assertEqual(len(SERVICES),6)
        for service in SERVICES:
            head=import_headers(service)
            self.assertIn('Name',head)
            self.assertIn('First Message',head)
            self.assertIn('Message0101Yes',head)
            self.assertIn('Message0101No',head)
            parsed=parse_service_upload(self.csv_data(head,[]),'import.csv',service)
            self.assertEqual(parsed['rows'],[])

    def test_existing_author_five_column_works_without_message(self):
        data=self.csv_data(['Author','Email','Book Titles','Genre','Source URL'],[
           ['Example Writer','writer@literature.test','Novel A','Fiction','https://writer.test/contact']])
        parsed=parse_service_upload(data,'authors.csv','author')
        self.assertEqual(len(parsed['rows']),1)
        row=parsed['rows'][0]
        self.assertEqual(row['first_message'],'')
        self.assertEqual(row['name'],'Example Writer')
        self.assertEqual(row['service_details']['book_titles'],'Novel A')
        self.assertEqual(row['disposition'],'ready_for_import')

    def test_positive_negative_branch_columns_and_first_message(self):
        data=self.csv_data(['Author','Email','Message 01','Message0101Yes','Message0101No','Message0201Yes'],[
            ['Writer','writer@literature.test','Hello','Happy to talk','Thanks, I understand','Following up']])
        row=parse_service_upload(data,'branches.csv','author')['rows'][0]
        self.assertEqual(row['first_message'],'Hello')
        self.assertEqual(set(row['branches']),{'Message01','Message0101Yes','Message0101No','Message0201Yes'})
        self.assertFalse(row['do_not_contact'])

    def test_four_other_business_schemas(self):
        cases=[
            ('automation',['Business Name','Website','Manual Workflow Signal'],
             ['Sample Business','https://business.test','Manual onboarding'],'workflow_signal'),
            ('website-design',['Business Name','Website URL','Website Issue'],
             ['Sample Business','https://business.test','Mobile page layout'],'website_issue'),
            ('digital-planner',['Creator or Shop Name','Storefront URL','Planner Niche'],
             ['Sample Shop','https://store.test','Teacher planners'],'planner_niche'),
            ('shopify',['Store Name','Shopify Store URL','Store Issue'],
             ['Sample Shop','https://store.test','Navigation issue'],'store_issue'),
            ('google-maps',['Business Name','Google Maps URL','Listing Observation'],
             ['Sample Cafe','https://maps.google.com/?q=cafe','No linked website'],'listing_observation'),
        ]
        for service,headers,values,field in cases:
            with self.subTest(service=service):
                parsed=parse_service_upload(self.csv_data(headers,[values]),'test.csv',service)
                self.assertEqual(len(parsed['rows']),1,parsed)
                self.assertEqual(parsed['rows'][0]['disposition'],'ready_for_import')
                self.assertTrue(parsed['rows'][0]['service_details'][field])

    def test_do_not_contact_and_historical_status_are_not_sendable(self):
        data=self.csv_data(['Name','Email','Do Not Contact','Status','First Message'],[
            ['Sample A','a@business.test','yes','','Hello'],
            ['Sample B','b@business.test','','sent','Already sent'],
            ['Sample C','c@business.test','','replied','Already replied']])
        parsed=parse_service_upload(data,'test.csv','automation')
        self.assertEqual([r['disposition'] for r in parsed['rows']],
                          ['suppressed','historical_skip','historical_skip'])

    def test_file_duplicate_and_bad_email_report_row_number(self):
        data=self.csv_data(['Name','Email'],[
           ['Good','good@business.test'],['Repeat','good@business.test'],
           ['Bad','notemail']])
        parsed=parse_service_upload(data,'test.csv','automation')
        self.assertEqual(len(parsed['rows']),1)
        self.assertEqual(len(parsed['issues']),2)
        self.assertEqual(parsed['issues'][0]['row'],3)
        self.assertIn('Duplicate',parsed['issues'][0]['errors'][0])

    def test_xlsx_uses_header_and_optional_message(self):
        workbook=Workbook();sheet=workbook.active
        sheet.append(['Business Name','Website','Message0101Yes'])
        sheet.append(['Brand','https://brand.test','Positive branch'])
        target=io.BytesIO();workbook.save(target)
        parsed=parse_service_upload(target.getvalue(),'test.xlsx','website-design')
        self.assertEqual(parsed['rows'][0]['branches']['Message0101Yes'],'Positive branch')

    def test_reject_non_spreadsheet_or_oversized(self):
        with self.assertRaises(ValueError):
            parse_service_upload(b'abc','evil.svg','author')
        data=self.csv_data(['Name','Email'],[['A'+str(i),'a'+str(i)+'@business.test'] for i in range(MAX_ROWS+1)])
        with self.assertRaises(ValueError):
            parse_service_upload(data,'too-many.csv','automation')

    def test_token_tied_to_account_file_and_age(self):
        secret='x'*48
        t=file_token(secret,1,'author','sha-a','list.csv',12,ts=100)
        with patch('letterdesk_import_plan.time.time',return_value=110):
            verify_token(secret,t,1,'author','sha-a','list.csv',12)
            with self.assertRaises(HTTPException):
                verify_token(secret,t,2,'author','sha-a','list.csv',12)
            with self.assertRaises(HTTPException):
                verify_token(secret,t,1,'shopify','sha-a','list.csv',12)
            with self.assertRaises(HTTPException):
                verify_token(secret,t,1,'author','sha-b','list.csv',12)
        with patch('letterdesk_import_plan.time.time',return_value=5000):
            with self.assertRaises(HTTPException):
                verify_token(secret,t,1,'author','sha-a','list.csv',12)

if __name__=='__main__':
    unittest.main()
