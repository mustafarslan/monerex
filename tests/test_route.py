"""The routing rules: one dispatch in, one model and effort out."""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import route  # noqa: E402

TABLE = route.load_json(route.TABLE)


def pick(work, **kwargs):
    return route.resolve(TABLE, work, **kwargs)


class RouteTest(unittest.TestCase):
    def assert_route(self, result, tier_model, effort):
        self.assertEqual((result["tier_model"], result["effort"]), (tier_model, effort), result["reason"])

    def test_role_defaults(self):
        for work, agent, model, effort in (
            ("read", "reader", "small", "low"),
            ("search", "scout", "small", "low"),
            ("plan", "architect", "large", "medium"),
            ("implement", "implementer", "mid", "medium"),
            ("debug", "implementer", "large", "high"),
            ("verify", "verifier", "mid", "medium"),
            ("review", "reviewer", "large", "high"),
            ("research", "researcher", "mid", "medium"),
            ("ml", "ml-specialist", "large", "medium"),
            ("data", "data-scientist", "mid", "medium"),
        ):
            with self.subTest(work):
                result = pick(work)
                self.assertEqual(result["agent"], agent)
                self.assert_route(result, model, effort)
                self.assertFalse(result["stop"])

    def test_every_route_names_a_model_and_an_effort(self):
        for work in TABLE["routes"]:
            result = pick(work)
            self.assertIn(result["model"], TABLE["models"].values())
            self.assertIn(result["effort"], TABLE["effort_ladder"])

    def test_trivial_edits_run_at_low_effort(self):
        self.assert_route(pick("implement", tier="T0"), "mid", "low")

    def test_implementation_is_never_cheap_first_without_a_safety_net(self):
        for kwargs in ({"risk": True}, {"checks": False}, {"precise": False}, {"tier": "T0", "risk": True}):
            with self.subTest(kwargs):
                self.assert_route(pick("implement", **kwargs), "large", "medium")

    def test_risky_or_large_plans_get_high_effort_and_the_advisor(self):
        for kwargs in ({"risk": True}, {"tier": "T3"}):
            with self.subTest(kwargs):
                result = pick("plan", **kwargs)
                self.assert_route(result, "large", "high")
                self.assertEqual(result["advisor"], TABLE["models"]["advisor"])
        self.assertIsNone(pick("plan", tier="T2")["advisor"])

    def test_a_risky_review_adds_a_cross_family_reviewer(self):
        self.assertTrue(pick("review", risk=True)["cross_family"])
        self.assertFalse(pick("review")["cross_family"])

    def test_the_judge_moves_up_with_the_author(self):
        self.assert_route(pick("verify", author="large"), "large", "medium")
        self.assert_route(pick("verify", author="small"), "mid", "medium")
        self.assert_route(pick("review", author="mid"), "large", "high")

    def test_a_specialist_that_judges_moves_up_with_the_author(self):
        self.assert_route(pick("data", author="large"), "large", "medium")
        self.assert_route(pick("ml", author="mid"), "large", "medium")

    def test_a_lookup_is_cheap_and_a_literature_question_is_not(self):
        self.assert_route(pick("research", tier="T0"), "small", "low")
        self.assert_route(pick("research", tier="T2"), "mid", "medium")
        self.assert_route(pick("research", tier="T0", gaps=["knowledge"]), "mid", "low")

    def test_a_risky_data_question_starts_on_the_large_model(self):
        self.assert_route(pick("data", risk=True), "large", "medium")
        self.assert_route(pick("ml", risk=True), "large", "medium")

    def test_a_diligence_gap_raises_effort(self):
        self.assert_route(pick("implement", gaps=["diligence"]), "mid", "high")
        self.assert_route(pick("implement", gaps=["diligence", "diligence"]), "mid", "xhigh")

    def test_a_knowledge_gap_raises_the_model(self):
        self.assert_route(pick("implement", gaps=["knowledge"]), "large", "medium")
        top = pick("debug", gaps=["knowledge"])
        self.assert_route(top, "large", "high")
        self.assertIsNotNone(top["advisor"])

    def test_a_spec_gap_stops_without_escalating(self):
        result = pick("implement", gaps=["spec"])
        self.assertTrue(result["stop"])
        self.assert_route(result, "mid", "medium")

    def test_the_escalation_cap_stops_the_stage(self):
        result = pick("implement", gaps=["diligence", "knowledge", "diligence"])
        self.assertTrue(result["stop"])
        self.assert_route(result, "large", "high")

    def test_a_stuck_debug_asks_for_a_second_opinion(self):
        result = pick("debug", gaps=["diligence", "knowledge"])
        self.assert_route(result, "large", "xhigh")
        self.assertIsNotNone(result["advisor"])
        self.assertTrue(result["cross_family"])

    def test_the_command_line_prints_one_json_object(self):
        done = subprocess.run(
            [sys.executable, "-I", os.path.join(ROOT, "scripts", "route.py"), "--work", "implement", "--tier", "T1", "--gap", "diligence"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["effort"], "high")


if __name__ == "__main__":
    unittest.main()
