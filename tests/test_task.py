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

    def test_the_open_task_is_the_last_one_started_and_not_done(self):
        self.assertIsNone(task.open_task([]))
        records = [event(0, "a", "start"), event(1, "a", "done"), event(2, "b", "start")]
        self.assertEqual(task.open_task(records), "b")
        self.assertIsNone(task.open_task(records + [event(3, "b", "done")]))


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
