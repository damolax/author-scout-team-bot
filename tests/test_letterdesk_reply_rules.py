"""Phase 7 reply triage is conservative and cannot send mail."""
import base64
import os
import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch

from letterdesk_reply_rules import classify_reply,safe_draft,canonical_address
from letterdesk_flow_engine import starter_flow
from letterdesk_gmail_reply_sync import (
    read_enabled,message_plain_text,matching_inbound_messages,gmail_headers
)
from letterdesk_campaign_delivery import delivery_release_ready

class ReplyRulesTests(unittest.TestCase):
    def test_explicit_opt_out_stops_even_in_spanish(self):
        for x in ("Please unsubscribe me.", "Don't email me again",
                  "Take me off this list", "No me contactes por favor.",
                  "Stop contacting me"):
            with self.subTest(value=x):
                res=classify_reply(x)
                self.assertEqual(res["outcome"],"opt_out",res)
                self.assertEqual(res["confidence"],"high")

    def test_explicit_decline_is_distinct_from_simple_contextual_no(self):
        self.assertEqual(classify_reply("No")["outcome"],"no")
        self.assertEqual(classify_reply("No thanks")["outcome"],"negative")
        self.assertEqual(classify_reply("I'm not interested")["outcome"],"negative")
        self.assertEqual(classify_reply("No estoy interesado")["outcome"],"negative")
        self.assertEqual(classify_reply("No")["confidence"],"low")

    def test_questions_deferrals_and_opt_in_possibilities_need_review(self):
        self.assertEqual(classify_reply("Could you explain the pricing?")["outcome"],"question")
        self.assertEqual(classify_reply("Maybe later")["outcome"],"not_now")
        self.assertEqual(classify_reply("Sounds like spam")["outcome"],"objection")
        self.assertEqual(classify_reply("Yes")["outcome"],"positive")
        self.assertEqual(classify_reply("Let's talk")["confidence"],"low")
        self.assertEqual(classify_reply("Hello there")["outcome"],"uncertain")

    def test_quoted_opt_out_does_not_trigger_on_original_email(self):
        reply="Thanks for the details.\nOn Sunday, you wrote:\n> Please unsubscribe me."
        self.assertNotEqual(classify_reply(reply)["outcome"],"opt_out")
        reply="Sure.\n> Don't email me again"
        self.assertNotEqual(classify_reply(reply)["outcome"],"opt_out")

    def test_confirmed_bounce_requires_explicit_provider_report(self):
        self.assertEqual(classify_reply("Delivery status notification",is_delivery_report=True)["outcome"],"bounce")

    def test_next_draft_never_sendable(self):
        f=starter_flow("author")
        planned=safe_draft(f,"Message01","positive",0,0)
        self.assertEqual(planned["action"],"draft_for_review")
        self.assertEqual(planned["draft"]["code"],"Message0101Yes")
        self.assertTrue(planned["draft"]["requiresHumanApproval"])
        refused=safe_draft(f,"Message01","opt_out",0,0)
        self.assertEqual(refused["action"],"stop")
        self.assertIsNone(refused["draft"])

    def test_staging_never_enables_send_or_thread_monitor_without_permissions(self):
        with patch.dict(os.environ,{
            "LETTERDESK_STAGING_ISOLATED":"true",
            "LETTERDESK_GMAIL_READ_ENABLED":"true",
            "LETTERDESK_REPLY_WRITE_ENABLED":"false",
            "LETTERDESK_GMAIL_SEND_ENABLED":"true",
            "LETTERDESK_REPLY_SAFETY_READY":"true",
            "LETTERDESK_DELIVERY_OPERATOR_APPROVED":"true"
        }):
            self.assertFalse(read_enabled())
            self.assertFalse(delivery_release_ready())

class ThreadReaderTests(unittest.TestCase):
    def gmail_message(self,message_id,sender,recipient,plain,timestamp):
        payload={"mimeType":"multipart/alternative","headers":[
            {"name":"From","value":sender},{"name":"To","value":recipient}],
            "parts":[{"mimeType":"text/plain","body":{
                "data":base64.urlsafe_b64encode(plain.encode()).decode().rstrip("=")}},
                {"mimeType":"text/html","body":{"data":"ZmFrZQ"}}]}
        return {"id":message_id,"internalDate":str(timestamp),"payload":payload}

    def test_known_thread_only_exact_reply_from_expected_contact(self):
        original=datetime(2026,10,17,10,0,tzinfo=timezone.utc)
        sent=int(original.timestamp()*1000)
        thread={"id":"gthread12345","messages":[
            self.gmail_message("source12345","sales@ourbrand.test","buyer@example.org","Original",sent),
            self.gmail_message("correct56789","Buyer <buyer@example.org>","sales@ourbrand.test","Yes",sent+60000),
            self.gmail_message("wrong012345","person@unrelated.test","sales@ourbrand.test","Hello",sent+70000),
            self.gmail_message("bad4567890","buyer@example.org","different@ourbrand.test","Hello",sent+80000),
            self.gmail_message("old4567890","buyer@example.org","sales@ourbrand.test","Old",sent-4000)
        ]}
        replies=matching_inbound_messages(thread,"buyer@example.org","sales@ourbrand.test",
            "source12345",original)
        self.assertEqual(len(replies),1)
        self.assertEqual(replies[0]["provider_message_id"],"correct56789")
        self.assertEqual(replies[0]["body"],"Yes")

    def test_html_is_not_harvested_as_plain_text(self):
        self.assertEqual(message_plain_text({"payload":{
            "mimeType":"text/html","body":{"data":"PHA+SGVsbG88L3A+"}}}),"")

    def test_unrelated_sender_never_matches_when_thread_id_is_same(self):
        original=datetime.now(timezone.utc)-timedelta(days=1)
        thread={"id":"known12345","messages":[self.gmail_message(
            "spam123456","else@outsider.test","sales@ourbrand.test","Unsubscribe!",int(datetime.now(timezone.utc).timestamp()*1000))]}
        self.assertEqual(matching_inbound_messages(thread,"buyer@example.org",
            "sales@ourbrand.test","original12345",original),[])

if __name__=="__main__":
    unittest.main()
