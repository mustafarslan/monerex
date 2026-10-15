"""The task log: events in, a per-tier summary out."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASK = os.path.join(ROOT, "scripts", "task.py")
CHECK = os.path.join(ROOT, "scripts", "check.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import task  # noqa: E402


def event(at, slug, name, **fields):
    return dict({"at": at, "task": slug, "event": name}, **fields)


class SummaryTest(unittest.TestCase):
    def test_an_empty_log_summarises_to_nothing(self):
        self.assertEqual(task.summarise([]), {})
        self.assertIn("no tasks", task.show({"tiers": {}, "days": None}))
        self.assertIn("last 7 days", task.show({"tiers": {}, "days": 7}))

    def test_one_clean_task(self):
        records = [
            event(0, "a", "start", tier="T1"),
            event(60, "a", "plan", rounds=1),
            event(120, "a", "checks", passed=True),
            event(180, "a", "verify", verdict="pass"),
            event(240, "a", "review", confirmed=1, plausible=0, rejected=3, merge="after-fixes"),
            event(600, "a", "done"),
        ]
        row = task.summarise(records)["T1"]
        self.assertEqual((row["started"], row["done"], row["completion"]), (1, 1, 1.0))
        self.assertEqual((row["first_pass_checks"], row["verify_first_pass"]), (1.0, 1.0))
        self.assertEqual((row["reviewer_hit_rate"], row["median_minutes"], row["plan_rounds"]), (0.25, 10.0, 1.0))

    def test_rework_escalations_and_unfinished_tasks_are_counted(self):
        records = [
            event(0, "a", "start", tier="T1"),
            event(10, "a", "checks", passed=False),
            event(20, "a", "escalation", gap="diligence"),
            event(30, "a", "checks", passed=False),
            event(40, "a", "escalation", gap="knowledge"),
            event(50, "a", "checks", passed=True),
            event(60, "a", "verify", verdict="fail"),
            event(70, "a", "done"),
            event(100, "b", "start", tier="T1"),
            event(110, "b", "escalation", gap="spec"),
        ]
        row = task.summarise(records)["T1"]
        self.assertEqual((row["started"], row["done"], row["completion"]), (2, 1, 0.5))
        self.assertEqual((row["first_pass_checks"], row["failed_check_runs"], row["verify_first_pass"]), (0.0, 2, 0.0))
        self.assertEqual(row["escalations"], {"diligence": 1, "knowledge": 1, "spec": 1})
        self.assertEqual(row["escalated_share"], 1.0)

    def test_a_task_counts_in_a_window_when_anything_happened_to_it_there(self):
        records = [
            event(100, "old", "start", tier="T1"), event(110, "old", "done"),
            event(300, "long", "start", tier="T1"), event(450, "long", "escalation", gap="knowledge", work="implement"), event(460, "long", "done"),
            event(500, "new", "start", tier="T1"),
        ]
        row = task.summarise(records, since=400)["T1"]
        self.assertEqual((row["started"], row["done"]), (2, 1), "one that began earlier and finished inside the window is in it")
        self.assertEqual(row["escalations"], {"knowledge (implement)": 1})
        self.assertEqual(task.summarise(records)["T1"]["started"], 3)

    def test_tiers_are_reported_apart_and_a_reused_slug_is_a_new_task(self):
        records = [
            event(0, "a", "start", tier="T0"), event(5, "a", "done"),
            event(10, "a", "start", tier="T2"), event(20, "a", "checks", passed=True),
        ]
        summary = task.summarise(records)
        self.assertEqual((summary["T0"]["done"], summary["T2"]["started"], summary["T2"]["done"]), (1, 1, 0))

    def test_the_agents_that_ran_during_a_task_are_counted_from_the_dispatch_log(self):
        records = [event(100, "a", "start", tier="T1"), event(200, "a", "done")]
        dispatches = [
            {"at": 50, "hook_event_name": "SubagentStart", "agent_type": "monerex:scout"},  # before the task
            {"at": 120, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},
            {"at": 130, "hook_event_name": "SubagentStop", "agent_type": "monerex:implementer"},
            {"at": 150, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},
            {"at": 170, "hook_event_name": "SubagentStart", "agent_type": "monerex:verifier"},
        ]
        self.assertEqual(task.summarise(records, dispatches)["T1"]["agents"], {"monerex:implementer": 2, "monerex:verifier": 1})

    def test_dispatches_are_attributed_to_the_route_that_asked_for_them(self):
        route = lambda at, slug, agent, model="sonnet", effort="medium": event(  # noqa: E731
            at, slug, "route", route_id="%s-%d" % (slug, at), work="implement", agent=agent, model=model, effort=effort)
        records = [
            event(100, "a", "start", tier="T1"),
            route(110, "a", "implementer"),
            route(115, "a", "verifier"),
            route(118, "a", "reviewer", model="opus", effort="high"),  # routed, never dispatched
            event(200, "a", "done"),
            event(300, "b", "start", tier="T2"),
            route(310, "b", "implementer", model="opus"),
            event(400, "b", "done"),
        ]
        dispatches = [
            {"at": 112, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},
            {"at": 116, "hook_event_name": "SubagentStart", "agent_type": "monerex:verifier"},
            {"at": 150, "hook_event_name": "SubagentStart", "agent_type": "monerex:scout"},  # no route asked for it
            {"at": 320, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},
        ]
        summary = task.summarise(records, dispatches)
        t1, t2 = summary["T1"], summary["T2"]
        self.assertEqual(t1["agents"], {"monerex:implementer": 1, "monerex:verifier": 1, "monerex:scout": 1}, "every agent that ran counts")
        self.assertEqual((t1["routes_not_dispatched"], t1["unrouted_dispatches"]), (1, 1))
        self.assertEqual(t1["routes"], {"implementer/sonnet/medium": 1, "verifier/sonnet/medium": 1, "reviewer/opus/high": 1})
        self.assertEqual(t1["attribution"], {"by route": 1})
        self.assertEqual((t2["agents"], t2["routes"]), ({"monerex:implementer": 1}, {"implementer/opus/medium": 1}))

    def test_a_dispatch_is_matched_once_to_the_earliest_open_route_of_its_agent(self):
        records = [
            event(100, "a", "start", tier="T1"),
            event(110, "a", "route", route_id="r1", agent="implementer", model="sonnet", effort="medium"),
            event(120, "a", "route", route_id="r2", agent="implementer", model="sonnet", effort="high"),
            event(200, "a", "done"),
        ]
        dispatches = [
            {"at": 105, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},  # before any route
            {"at": 125, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},
        ]
        row = task.summarise(records, dispatches)["T1"]
        self.assertEqual((row["agents"], row["routes_not_dispatched"], row["unrouted_dispatches"]), ({"monerex:implementer": 2}, 1, 1))

    def test_a_route_that_said_stop_is_not_waiting_for_a_dispatch(self):
        records = [
            event(100, "a", "start", tier="T1"),
            event(110, "a", "route", route_id="r1", agent="implementer", model="opus", effort="xhigh", stop=True),
            event(200, "a", "done"),
        ]
        row = task.summarise(records, [])["T1"]
        self.assertEqual((row["routes_not_dispatched"], row["routes"]), (0, {"implementer/opus/xhigh": 1}))

    def test_a_task_logged_before_routes_were_falls_back_to_the_time_window(self):
        records = [event(100, "a", "start", tier="T1"), event(200, "a", "done")]
        dispatches = [{"at": 120, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"}]
        row = task.summarise(records, dispatches)["T1"]
        self.assertEqual((row["agents"], row["attribution"]), ({"monerex:implementer": 1}, {"by time": 1}))
        self.assertEqual((row["routes_not_dispatched"], row["unrouted_dispatches"], row["routes"]), (0, 0, {}))

    def test_ablation_results_are_counted_per_tier(self):
        records = [
            event(0, "a", "start", tier="T1"), event(10, "a", "ablation", result="fail"), event(20, "a", "ablation", result="pass"),
            event(30, "b", "start", tier="T1"), event(40, "b", "ablation", result="weak"),
            event(50, "c", "start", tier="T1"),
        ]
        self.assertEqual(task.summarise(records)["T1"]["ablation"], {"fail": 1, "pass": 1, "weak": 1})

    def test_the_open_task_is_the_last_one_started_and_not_done(self):
        self.assertIsNone(task.open_task([]))
        records = [event(0, "a", "start"), event(1, "a", "done"), event(2, "b", "start")]
        self.assertEqual(task.open_task(records), "b")
        self.assertIsNone(task.open_task(records + [event(3, "b", "done")]))


class EarlierProposalsTest(unittest.TestCase):
    """A retro proposal that was accepted is judged by the tasks started after it."""

    def tasks(self, first_at, count, escalate, tier="T1"):
        records = []
        for n in range(count):
            at = first_at + n * 1000
            slug = "t%d-%d" % (first_at, n)
            records.append(event(at, slug, "start", tier=tier))
            if n < escalate:
                records.append(event(at + 10, slug, "escalation", gap="knowledge", work="implement"))
            records.append(event(at + 100, slug, "done"))
        return records

    def proposal(self, **fields):
        base = {"id": "R1", "retro": "retro-2026-10-01", "accepted": 50000, "metric": {"tier": "T1", "key": "escalated_share"},
                "baseline": 0.5, "direction": "down", "change": "routing/routing.json: implement starts at large"}
        base.update(fields)
        return base

    def test_a_metric_that_moved_the_way_it_should_is_reported_as_moved(self):
        records = self.tasks(0, 6, escalate=3) + self.tasks(60000, 5, escalate=1)
        [verdict] = task.earlier_proposals([self.proposal()], records)
        self.assertEqual((verdict["now"], verdict["n"], verdict["verdict"]), (0.2, 5, "moved"))

    def test_a_metric_that_did_not_move_is_a_revert_candidate(self):
        records = self.tasks(60000, 5, escalate=3)
        [verdict] = task.earlier_proposals([self.proposal()], records)
        self.assertEqual((verdict["now"], verdict["verdict"]), (0.6, "revert candidate"))
        [up] = task.earlier_proposals([self.proposal(metric={"tier": "T1", "key": "completion"}, baseline=1.0, direction="up")], records)
        self.assertEqual(up["verdict"], "revert candidate", "no change counts as not moved")

    def test_fewer_than_five_finished_tasks_since_acceptance_is_too_thin(self):
        records = self.tasks(0, 6, escalate=0) + self.tasks(60000, 4, escalate=0) + self.tasks(60000 + 500, 3, escalate=0, tier="T2")
        [verdict] = task.earlier_proposals([self.proposal()], records)
        self.assertEqual((verdict["n"], verdict["verdict"]), (4, "too thin"), "only tasks in the proposal's tier, started after it, count")

    def test_thin_is_judged_on_the_metrics_own_sample(self):
        records = self.tasks(60000, 6, escalate=0)
        records.append(event(60000 + 50, "t60000-0", "verify", verdict="pass"))
        [verdict] = task.earlier_proposals([self.proposal(metric={"tier": "T1", "key": "verify_first_pass"}, baseline=0.5, direction="up")], records)
        self.assertEqual((verdict["n"], verdict["verdict"]), (1, "too thin"), "six tasks finished, but only one was verified")

    def test_a_task_started_in_the_second_it_was_accepted_counts(self):
        records = self.tasks(50000, 5, escalate=0)
        [verdict] = task.earlier_proposals([self.proposal()], records)
        self.assertEqual((verdict["n"], verdict["verdict"]), (5, "moved"))

    def test_a_damaged_proposal_is_reported_as_unreadable_not_fatal(self):
        records = self.tasks(60000, 5, escalate=0)
        damaged = [
            self.proposal(id="string-metric", metric="T1.escalated_share"),
            self.proposal(id="string-date", accepted="2026-10-01"),
            self.proposal(id="unknown-key", metric={"tier": "T1", "key": "escalations"}),
            self.proposal(id="bool-baseline", baseline=True),
            self.proposal(id="no-direction", direction="decrease"),
            "not a record",
        ]
        verdicts = task.earlier_proposals(damaged, records)
        self.assertEqual([item["verdict"] for item in verdicts], ["unreadable"] * 6)

    def test_a_metric_with_no_value_yet_is_too_thin(self):
        records = self.tasks(60000, 5, escalate=0)
        [verdict] = task.earlier_proposals([self.proposal(metric={"tier": "T1", "key": "reviewer_hit_rate"})], records)
        self.assertEqual((verdict["now"], verdict["verdict"]), (None, "too thin"))


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="monerex-task-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.env = dict(os.environ)
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.env.pop(name, None)
        for args in (("init", "-q"), ("config", "user.name", "T"), ("config", "user.email", "t@example.invalid")):
            subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)
        os.makedirs(os.path.join(self.repo, ".monerex"))

    def run_script(self, script, *args):
        return subprocess.run([sys.executable, "-I", script, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)

    def events(self):
        return task.read(self.repo)

    def test_events_are_written_and_summarised(self):
        self.assertEqual(self.run_script(TASK, "event", "start", "--slug", "fix-login", "--tier", "T1", "--risk").returncode, 0)
        self.run_script(TASK, "event", "plan", "--rounds", "2")
        self.run_script(TASK, "event", "review", "--confirmed", "2", "--rejected", "2", "--merge", "yes")
        self.run_script(TASK, "event", "done")
        names = [(record["task"], record["event"]) for record in self.events()]
        self.assertEqual(names, [("fix-login", "start"), ("fix-login", "plan"), ("fix-login", "review"), ("fix-login", "done")])
        self.assertTrue(self.events()[0]["risk"])
        summary = json.loads(self.run_script(TASK, "summary", "--json").stdout)["tiers"]
        self.assertEqual((summary["T1"]["completion"], summary["T1"]["reviewer_hit_rate"], summary["T1"]["plan_rounds"]), (1.0, 0.5, 2.0))
        self.assertIn("T1  1 started, 1 done", self.run_script(TASK, "summary").stdout)

    def test_the_summary_reads_the_dispatch_commit_and_guard_logs_within_the_window(self):
        import time

        now = int(time.time())
        logs = {
            "routing.jsonl": [
                {"at": now, "hook_event_name": "SubagentStop", "agent_type": "monerex:implementer", "effort": "medium"},
                {"at": now, "hook_event_name": "SubagentStop", "agent_type": "monerex:implementer", "effort": "medium"},
                {"at": now, "hook_event_name": "SubagentStart", "agent_type": "monerex:implementer"},
                {"at": now - 40 * 86400, "hook_event_name": "SubagentStop", "agent_type": "monerex:reviewer", "effort": "high"},
            ],
            "commits.jsonl": [{"at": now, "commit": "a"}, {"at": now - 40 * 86400, "commit": "b"}],
            "guard.jsonl": [{"at": now, "paths": [".env", "package-lock.json"]}, {"at": now, "paths": [".env"], "by": "monerex:implementer"}],
        }
        os.makedirs(os.path.join(self.repo, ".monerex", "log"))
        for name, records in logs.items():
            with open(os.path.join(self.repo, ".monerex", "log", name), "w", encoding="utf-8") as handle:
                handle.write("".join(json.dumps(record) + "\n" for record in records))
        recent = json.loads(self.run_script(TASK, "summary", "--days", "30", "--json").stdout)
        self.assertEqual((recent["dispatches"], recent["commits"]), ({"monerex:implementer/medium": 2}, 1))
        self.assertEqual(recent["protected_files_changed_by_shell"], {".env (by ?)": 1, ".env (by monerex:implementer)": 1, "package-lock.json (by ?)": 1})
        everything = json.loads(self.run_script(TASK, "summary", "--json").stdout)
        self.assertEqual((everything["commits"], everything["dispatches"]["monerex:reviewer/high"]), (2, 1))
        self.assertIn("protected files changed by a shell command", self.run_script(TASK, "summary").stdout)
        self.assertEqual(self.run_script(TASK, "summary", "--days", "0").returncode, 2)

    def test_an_event_with_no_open_task_logs_nothing_and_does_not_fail(self):
        done = self.run_script(TASK, "event", "verify", "--verdict", "pass")
        self.assertEqual(done.returncode, 0)
        self.assertIn("nothing logged", done.stdout)
        self.assertEqual(self.events(), [])

    def test_a_line_that_is_not_a_record_is_skipped_everywhere(self):
        os.makedirs(os.path.join(self.repo, ".monerex", "log"))
        for name in ("tasks.jsonl", "guard.jsonl", "routing.jsonl", "commits.jsonl"):
            with open(os.path.join(self.repo, ".monerex", "log", name), "w", encoding="utf-8") as handle:
                handle.write('null\n[]\n"text"\n{"at": "yesterday", "paths": ["x"], "hook_event_name": "SubagentStop"}\nnot json\n')
        for args in (("summary",), ("summary", "--days", "7"), ("event", "start", "--slug", "a", "--tier", "T1"), ("event", "done")):
            with self.subTest(args):
                self.assertEqual(self.run_script(TASK, *args).returncode, 0)

    def test_an_accepted_proposal_is_recorded_and_reported_in_the_summary(self):
        accept = ("proposal", "accept", "--id", "R2026-10-15-1", "--retro", "retro-2026-10-15", "--metric", "T1.escalated_share",
                  "--baseline", "0.5", "--direction", "down", "--change", "routing/routing.json: implement starts at large")
        done = self.run_script(TASK, *accept)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(self.repo, ".monerex", "proposals.jsonl"), encoding="utf-8") as handle:
            [record] = [json.loads(line) for line in handle]
        self.assertEqual((record["id"], record["metric"], record["baseline"], record["direction"]),
                         ("R2026-10-15-1", {"tier": "T1", "key": "escalated_share"}, 0.5, "down"))
        self.assertIsInstance(record["accepted"], int)
        self.assertEqual(self.run_script(TASK, *accept).returncode, 2, "an id is recorded once")
        summary = json.loads(self.run_script(TASK, "summary", "--json").stdout)
        self.assertEqual([(p["id"], p["verdict"]) for p in summary["earlier_proposals"]], [("R2026-10-15-1", "too thin")])
        self.assertIn("earlier proposals", self.run_script(TASK, "summary").stdout)

    def test_a_proposal_must_name_a_metric_the_summary_reports(self):
        for metric in ("T1.feelings", "T9.completion", "completion", "T1.failed_check_runs"):
            with self.subTest(metric):
                done = self.run_script(TASK, "proposal", "accept", "--id", "R1", "--retro", "r", "--metric", metric,
                                       "--baseline", "0.5", "--direction", "up", "--change", "x")
                self.assertEqual(done.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".monerex", "proposals.jsonl")))

    def test_the_summary_counts_eval_gate_runs_and_holdout_looks(self):
        import time

        now = int(time.time())
        os.makedirs(os.path.join(self.repo, ".monerex", "log"))
        with open(os.path.join(self.repo, ".monerex", "log", "evalgate.jsonl"), "w", encoding="utf-8") as handle:
            for record in ({"at": now, "verdict": "pass", "holdout": False}, {"at": now, "verdict": "regression", "holdout": False},
                           {"at": now, "verdict": "pass", "holdout": True, "milestone": "0.3.0"},
                           {"at": now, "verdict": "pass", "holdout": True, "milestone": "0.3.0"},
                           {"at": now - 40 * 86400, "verdict": "pass", "holdout": True, "milestone": "0.2.0"}):
                handle.write(json.dumps(record) + "\n")
        recent = json.loads(self.run_script(TASK, "summary", "--days", "30", "--json").stdout)
        self.assertEqual(recent["eval_gate"], {"runs": {"pass": 3, "regression": 1}, "holdout_looks": 2, "milestones": 1})
        self.assertIn("eval gate", self.run_script(TASK, "summary").stdout)

    def test_an_ablation_result_can_be_logged_by_hand(self):
        self.run_script(TASK, "event", "start", "--slug", "tiny", "--tier", "T0")
        self.assertEqual(self.run_script(TASK, "event", "ablation", "--result", "exempt").returncode, 0)
        self.assertEqual(self.events()[-1]["result"], "exempt")
        self.assertEqual(self.run_script(TASK, "event", "ablation", "--result", "great").returncode, 2)

    def dispatch(self, agent_type):
        import time

        os.makedirs(os.path.join(self.repo, ".monerex", "log"), exist_ok=True)
        with open(os.path.join(self.repo, ".monerex", "log", "routing.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": int(time.time()), "hook_event_name": "SubagentStart", "agent_type": agent_type}) + "\n")

    def test_a_verify_verdict_needs_a_verifier_that_ran(self):
        # Seen in a live run: with git unavailable the session logged "verify pass" without dispatching anyone.
        self.run_script(TASK, "event", "start", "--slug", "a", "--tier", "T1")
        self.dispatch("monerex:implementer")
        refused = self.run_script(TASK, "event", "verify", "--verdict", "pass")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("monerex:verifier", refused.stderr)
        self.assertEqual([record["event"] for record in self.events()], ["start"], "nothing is logged")
        self.dispatch("monerex:verifier")
        self.assertEqual(self.run_script(TASK, "event", "verify", "--verdict", "pass").returncode, 0)
        self.assertEqual(self.events()[-1]["event"], "verify")

    def test_a_verifier_from_before_the_task_does_not_count(self):
        self.dispatch("monerex:verifier")
        import time

        time.sleep(1.1)
        self.run_script(TASK, "event", "start", "--slug", "b", "--tier", "T1")
        self.assertEqual(self.run_script(TASK, "event", "verify", "--verdict", "fail").returncode, 2)

    def test_start_needs_a_slug_and_a_tier(self):
        self.assertEqual(self.run_script(TASK, "event", "start").returncode, 2)

    def test_every_check_run_is_logged_against_the_open_task(self):
        with open(os.path.join(self.repo, ".monerex", "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"checks": ["test -f ok.txt"]}, handle)
        self.assertEqual(self.run_script(CHECK).returncode, 1)  # no open task yet: runs, logs nothing
        self.assertEqual(self.events(), [])
        self.run_script(TASK, "event", "start", "--slug", "a", "--tier", "T1")
        self.assertEqual(self.run_script(CHECK).returncode, 1)
        with open(os.path.join(self.repo, "ok.txt"), "w", encoding="utf-8") as handle:
            handle.write("ok\n")
        self.assertEqual(self.run_script(CHECK).returncode, 0)
        checks = [record["passed"] for record in self.events() if record["event"] == "checks"]
        self.assertEqual(checks, [False, True])
        summary = json.loads(self.run_script(TASK, "summary", "--json").stdout)["tiers"]
        self.assertEqual((summary["T1"]["first_pass_checks"], summary["T1"]["failed_check_runs"]), (0.0, 1))


if __name__ == "__main__":
    unittest.main()
