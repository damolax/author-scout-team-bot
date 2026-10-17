"""Phase 6 delivery never attempts Gmail without explicit production safety gates."""
import base64
import os
import unittest
from unittest.mock import patch, AsyncMock

from letterdesk_campaign_delivery import (
    delivery_release_ready,gmail_send_one,sanitize_email_message,deliver_one,
)

class GmailDeliverySafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_all_release_gates_required(self):
        initial={"LETTERDESK_STAGING_ISOLATED":"true",
                 "LETTERDESK_GMAIL_SEND_ENABLED":"true",
                 "LETTERDESK_REPLY_SAFETY_READY":"true",
                 "LETTERDESK_DELIVERY_OPERATOR_APPROVED":"true"}
        with patch.dict(os.environ,initial):
            self.assertFalse(delivery_release_ready())
        initial["LETTERDESK_STAGING_ISOLATED"]="false"
        with patch.dict(os.environ,initial):
            self.assertTrue(delivery_release_ready())
        for flag in ("LETTERDESK_GMAIL_SEND_ENABLED",
                     "LETTERDESK_REPLY_SAFETY_READY",
                     "LETTERDESK_DELIVERY_OPERATOR_APPROVED"):
            isolated=dict(initial);isolated[flag]="false"
            with patch.dict(os.environ,isolated):
                self.assertFalse(delivery_release_ready())

    def test_email_headers_are_safe_and_valid(self):
        raw=sanitize_email_message("sender@example.com","recipient@example.com",
                                   "An appropriate subject","Hello,\nThanks")
        decoded=base64.urlsafe_b64decode(raw+"="*(-len(raw)%4)).decode()
        self.assertIn("From: sender@example.com",decoded)
        self.assertIn("To: recipient@example.com",decoded)
        self.assertIn("An appropriate subject",decoded)
        for value in ("Hello\nBcc: outsider@example.com","Subject\r\nExtra"):
            with self.assertRaises(ValueError):
                sanitize_email_message(value,"recipient@example.com","subject","Body")
        with self.assertRaises(ValueError):
            sanitize_email_message("sender@example.com","recipient@example.com",
                                   "Hello\nBcc: outsider@example.com","Body")

    async def test_google_api_never_called_in_staging(self):
        with patch.dict(os.environ,{
            "LETTERDESK_STAGING_ISOLATED":"true",
            "LETTERDESK_GMAIL_SEND_ENABLED":"true",
            "LETTERDESK_REPLY_SAFETY_READY":"true",
            "LETTERDESK_DELIVERY_OPERATOR_APPROVED":"true"
        }), patch("letterdesk_campaign_delivery.httpx.AsyncClient") as http:
            with self.assertRaises(RuntimeError):
                await gmail_send_one("dummy","sender@example.com",
                    "recipient@example.com","subject","body")
            http.assert_not_called()
            r=await deliver_one(None)
            self.assertEqual(r["status"],"disabled")
            http.assert_not_called()

if __name__=="__main__":unittest.main()
