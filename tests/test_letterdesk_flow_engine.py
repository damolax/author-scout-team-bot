"""Phase 5 regression tests: flow architecture, safe branching, and all six modes."""
import unittest
from copy import deepcopy
from letterdesk_flow_engine import SERVICE_MODES,OUTCOMES,starter_flow,validate_flow,simulate

class Phase5FlowTests(unittest.TestCase):
    def test_six_specific_starters_are_valid_and_different(self):
        self.assertEqual(len(SERVICE_MODES),6)
        first=[]
        for service in SERVICE_MODES:
            f=starter_flow(service)
            self.assertEqual(validate_flow(f,service),[],(service,validate_flow(f,service)))
            first.append(f["nodes"][0]["body"])
            self.assertEqual(f["nodes"][0]["code"],"Message01")
            self.assertTrue(all(n["reviewRequired"] for n in f["nodes"]))
            self.assertTrue(any(x["code"]=="Message0101Yes" for x in f["nodes"]))
            self.assertTrue(any(x["code"]=="Message0101No" for x in f["nodes"]))
        self.assertEqual(len(set(first)),6)

    def test_nested_yes_no_and_question_are_context_specific(self):
        f=starter_flow("author")
        self.assertEqual(simulate(f,"Message01","yes")["nextCode"],"Message0101Yes")
        self.assertEqual(simulate(f,"Message01","no")["action"],"stop")
        self.assertFalse(simulate(f,"Message01","no")["suppress"])
        self.assertEqual(simulate(f,"Message01","question")["nextCode"],"Message0101Question")
        self.assertEqual(simulate(f,"Message0101Yes","no")["nextCode"],"Message0201No")
        self.assertEqual(simulate(f,"Message0101Yes","no")["action"],"draft_for_review")
        self.assertEqual(simulate(f,"Message0101Yes","yes")["nextCode"],"Message0201Yes")

    def test_opt_out_decline_and_hard_bounce_stop_all_followups(self):
        f=starter_flow("automation")
        for outcome in ("opt_out","negative","bounce"):
            with self.subTest(outcome=outcome):
                self.assertEqual(simulate(f,"Message0101Yes",outcome)["action"],"stop")
        self.assertTrue(simulate(f,"Message01","opt_out")["suppress"])
        self.assertTrue(simulate(f,"Message01","negative")["suppress"])

    def test_no_reply_caps_and_wait(self):
        f=starter_flow("website-design")
        self.assertEqual(simulate(f,"Message01","no_reply")["nextCode"],"Message0101NoReply")
        self.assertEqual(simulate(f,"Message01","no_reply",no_reply_followups=1)["action"],"stop")
        self.assertEqual(simulate(f,"Message01","yes",message_count=3)["action"],"stop")

    def test_unknown_outcome_and_missing_edge_go_to_review(self):
        f=starter_flow("shopify")
        self.assertEqual(simulate(f,"Message01","made_up_intent")["action"],"manual_review")
        self.assertEqual(simulate(f,"Message0101Question","positive")["action"],"manual_review")

    def test_loop_and_duplicate_branch_rejected(self):
        f=starter_flow("digital-planner")
        f["edges"].append({"from":"Message0201Yes","outcome":"question",
                           "to":"Message01","action":"draft_for_review"})
        self.assertTrue(any("cycle" in s.lower() for s in validate_flow(f,"digital-planner")))
        f=starter_flow("author")
        f["edges"].append(deepcopy(f["edges"][0]))
        self.assertTrue(any("duplicate" in s.lower() for s in validate_flow(f,"author")))

    def test_forced_stop_policy_and_no_reply_min_delay(self):
        f=starter_flow("google-maps")
        f["edges"].append({"from":"Message0201Yes","outcome":"opt_out",
                           "to":"Message01","action":"draft_for_review"})
        self.assertTrue(any("must stop" in s for s in validate_flow(f,"google-maps")))
        f=starter_flow("google-maps")
        edge=next(e for e in f["edges"] if e["outcome"]=="no_reply")
        edge["delayMinutes"]=1
        self.assertTrue(any("at least 1 day" in s for s in validate_flow(f,"google-maps")))

    def test_unreviewed_variants_and_bad_ids_rejected(self):
        f=starter_flow("author")
        f["nodes"][0]["reviewRequired"]=False
        self.assertTrue(any("require review" in s for s in validate_flow(f,"author")))
        f=starter_flow("author")
        f["nodes"][0]["variants"]=[{"id":"A","subject":"","body":""},
                                  {"id":"A","subject":"","body":""}]
        self.assertTrue(any("repeated variant ID" in s for s in validate_flow(f,"author")))

    def test_cannot_silently_move_flow_to_another_service(self):
        f=starter_flow("author")
        self.assertIn("another service", " ".join(validate_flow(f,"shopify")))

    def test_too_many_nodes_and_subject_multiline_rejected(self):
        f=starter_flow("author")
        f["nodes"][0]["subject"]="Hello\nBCC:someone"
        self.assertTrue(any("single line" in s for s in validate_flow(f,"author")))
        f=starter_flow("author")
        f["nodes"]=f["nodes"]*5
        self.assertTrue(any("1–45" in s for s in validate_flow(f,"author")))

if __name__=="__main__":unittest.main()
