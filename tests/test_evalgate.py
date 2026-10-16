"""The eval gate: eval results compared with stored baselines, and a regression stops the change."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "scripts", "evalgate.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "eval-result.json")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import evalgate  # noqa: E402


def result(cases, model="sonnet", partial=False, plugin="0.2.0"):
    """A result in the shape `claude plugin eval --json` writes (see tests/fixtures/eval-result.json)."""
    with open(FIXTURE, encoding="utf-8") as handle:
        shaped = json.load(handle)
    shaped["partial"] = partial
    shaped["suite"]["modelOverride"] = model
    shaped["suite"]["plugins"][0]["version"] = plugin
    shaped["cases"] = [
        {"name": name, "runsPerCase": len(runs), "arms": {"with": [
            {"score": 1 if outcome == "pass" else 0, "passed": outcome == "pass", "costUsd": 0.05,
             "error": "run failed" if outcome == "error" else None} for outcome in runs]},
         "aggregates": {"score": 0, "passRate": 0}}
        for name, runs in cases.items()
    ]
    return shaped


class ParseTest(unittest.TestCase):
    def test_the_real_result_shape_is_read(self):
        with open(FIXTURE, encoding="utf-8") as handle:
            parsed = evalgate.parse(json.load(handle))
        self.assertEqual(parsed["cases"], {"push-default-branch": {"runs": 1, "passed": 1, "errors": 0}})
        self.assertEqual((parsed["model"], parsed["plugin_version"], parsed["claude_version"], parsed["partial"]),
                         ("sonnet", "0.2.0", "2.1.300", False))


class CompareTest(unittest.TestCase):
    def baselines(self, cases, model="sonnet"):
        return {"version": 1, "cases": {name: {"runs": runs, "passed": passed, "model": model} for name, (runs, passed) in cases.items()}}

    def test_one_sided_fisher(self):
        self.assertAlmostEqual(evalgate.fisher_lower(3, 3, 0, 3), 0.05)
        self.assertAlmostEqual(evalgate.fisher_lower(3, 3, 2, 3), 0.5)
        self.assertAlmostEqual(evalgate.fisher_lower(3, 3, 3, 3), 1.0)

    def test_verdicts(self):
        base = self.baselines({"steady": (3, 3), "dropped": (6, 6), "noisy": (3, 3), "zeroed": (3, 2), "gone": (3, 3)})
        now = evalgate.parse(result({
            "steady": ["pass"] * 3, "dropped": ["fail"] * 5 + ["pass"], "noisy": ["pass", "pass", "fail"],
            "zeroed": ["fail"] * 3, "brand-new": ["pass"], "broke": ["pass", "error"],
        }))
        verdicts = {name: item["verdict"] for name, item in evalgate.compare(base, now)["cases"].items()}
        self.assertEqual(verdicts, {"steady": "same", "dropped": "regression", "noisy": "same", "zeroed": "regression",
                                    "brand-new": "new", "broke": "not-run"})

    def test_a_regression_is_not_hidden_by_an_errored_run(self):
        base = self.baselines({"a": (3, 3)})
        now = evalgate.parse(result({"a": ["fail", "fail", "fail", "fail", "fail", "error"]}))
        self.assertEqual(evalgate.compare(base, now)["cases"]["a"]["verdict"], "regression")

    def test_one_run_is_too_few_to_judge(self):
        base = self.baselines({"a": (3, 3)})
        report = evalgate.compare(base, evalgate.parse(result({"a": ["fail"]})))
        self.assertEqual(report["cases"]["a"]["verdict"], "too-few-runs")
        self.assertEqual(evalgate.exit_code(report), 2)

    def test_a_baselined_case_missing_from_the_run_is_not_judged(self):
        base = self.baselines({"a": (3, 3), "old": (3, 3)})
        report = evalgate.compare(base, evalgate.parse(result({"a": ["pass"] * 3})), expected={"a", "old"})
        self.assertEqual(report["cases"]["old"]["verdict"], "missing")
        self.assertEqual(evalgate.exit_code(report), 2)
        unasked = evalgate.compare(base, evalgate.parse(result({"a": ["pass"] * 3})), expected={"a"})
        self.assertEqual(evalgate.exit_code(unasked), 0, "a case outside the suite that ran is not expected")

    def test_a_result_on_another_model_is_not_compared(self):
        report = evalgate.compare(self.baselines({"a": (3, 3)}, model="opus"), evalgate.parse(result({"a": ["fail"] * 3})))
        self.assertEqual(report["cases"]["a"]["verdict"], "other-model")
        self.assertEqual(evalgate.exit_code(report), 2)

    def test_exit_codes(self):
        base = self.baselines({"a": (3, 3)})
        self.assertEqual(evalgate.exit_code(evalgate.compare(base, evalgate.parse(result({"a": ["pass"] * 3})))), 0)
        self.assertEqual(evalgate.exit_code(evalgate.compare(base, evalgate.parse(result({"a": ["fail"] * 3})))), 1)
        self.assertEqual(evalgate.exit_code(evalgate.compare(base, evalgate.parse(result({"a": ["pass"] * 3}, partial=True)))), 2,
                         "a run stopped by its cost cap is never a pass")
        only_new = evalgate.compare(base, evalgate.parse(result({"b": ["pass"] * 3})))
        self.assertEqual(evalgate.exit_code(only_new), 2, "nothing was compared with a baseline, so nothing was judged")
        with_new = evalgate.compare(base, evalgate.parse(result({"a": ["pass"] * 3, "b": ["pass"]})))
        self.assertEqual(evalgate.exit_code(with_new), 0, "a new case beside judged ones is fine")


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="monerex-evalgate-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.env = {key: value for key, value in os.environ.items() if key not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
        for args in (("init", "-q"), ("config", "user.name", "T"), ("config", "user.email", "t@example.invalid")):
            subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True, capture_output=True)
        os.makedirs(os.path.join(self.repo, "evals"))
        os.makedirs(os.path.join(self.repo, "holdout"))
        with open(os.path.join(self.repo, "README.md"), "w") as handle:
            handle.write("x\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, env=self.env, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "s"], cwd=self.repo, env=self.env, check=True, capture_output=True)
        # A stand-in for `claude`: each call hands back the next queued result and records its arguments.
        self.queue = os.path.join(self.repo, ".fake")
        os.makedirs(self.queue)
        fake = os.path.join(self.queue, "claude")
        with open(fake, "w") as handle:
            handle.write("#!%s\n" % sys.executable + (
                "import json, os, sys\n"
                "queue = os.path.dirname(os.path.abspath(__file__))\n"
                "with open(os.path.join(queue, 'calls.jsonl'), 'a') as log:\n"
                "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "pending = sorted(name for name in os.listdir(queue) if name.startswith('result-'))\n"
                "data = open(os.path.join(queue, pending[0])).read()\n"
                "os.remove(os.path.join(queue, pending[0]))\n"
                "open(sys.argv[sys.argv.index('--json') + 1], 'w').write(data)\n"))
        os.chmod(fake, 0o755)
        self.env["MONEREX_CLAUDE"] = fake

    def queue_result(self, shaped):
        number = len([name for name in os.listdir(self.queue) if name.startswith("result-")])
        with open(os.path.join(self.queue, "result-%03d.json" % number), "w") as handle:
            json.dump(shaped, handle)

    def calls(self):
        with open(os.path.join(self.queue, "calls.jsonl")) as handle:
            return [json.loads(line) for line in handle]

    def gate(self, *args):
        return subprocess.run([sys.executable, "-I", GATE, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)

    def write_baselines(self, cases):
        with open(os.path.join(self.repo, "evals", "baselines.json"), "w") as handle:
            json.dump({"version": 1, "cases": {name: {"runs": runs, "passed": passed, "model": "sonnet"}
                                               for name, (runs, passed) in cases.items()}}, handle)

    def log(self):
        with open(os.path.join(self.repo, ".monerex", "log", "evalgate.jsonl")) as handle:
            return [json.loads(line) for line in handle]

    def test_a_run_passes_logs_and_status_sees_it(self):
        self.write_baselines({"a": (3, 3)})
        self.queue_result(result({"a": ["pass"] * 3}))
        done = self.gate("run", "--tag", "smoke")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        [call] = self.calls()
        for flag in ("plugin", "eval", "--json", "--ablation", "none", "--tag", "smoke", "--max-cost-usd", "--model", "sonnet"):
            self.assertIn(flag, call)
        [record] = self.log()
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        self.assertEqual((record["head"], record["tag"], record["verdict"]), (head, "smoke", "pass"))
        self.assertEqual(self.gate("status").returncode, 0)

    def test_a_case_that_dropped_is_run_again_before_it_is_judged(self):
        self.write_baselines({"a": (3, 3), "b": (3, 3)})
        self.queue_result(result({"a": ["pass", "pass", "fail"], "b": ["pass"] * 3}))
        self.queue_result(result({"a": ["pass"] * 3}))
        done = self.gate("run", "--tag", "smoke")
        self.assertEqual(done.returncode, 0, done.stdout)
        rerun = self.calls()[1]
        self.assertEqual((rerun[rerun.index("--case") + 1], rerun[rerun.index("--runs") + 1]), ("a", "3"))
        report = json.loads(done.stdout)
        self.assertEqual((report["cases"]["a"]["runs"], report["cases"]["a"]["passed"]), (6, 5))

    def test_a_regression_exits_1_and_status_refuses(self):
        self.write_baselines({"a": (3, 3)})
        self.queue_result(result({"a": ["fail"] * 3}))
        self.queue_result(result({"a": ["fail"] * 3}))
        done = self.gate("run", "--tag", "smoke")
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertEqual(self.gate("status").returncode, 1)

    def test_without_baselines_it_is_not_a_pass(self):
        self.queue_result(result({"a": ["pass"] * 3}))
        self.assertEqual(self.gate("run", "--tag", "smoke").returncode, 2)

    def test_a_cost_cap_is_required(self):
        self.assertEqual(self.gate("run", "--tag", "smoke", "--max-cost-usd", "0").returncode, 2)

    def test_the_holdout_needs_a_milestone_and_every_look_is_logged(self):
        self.write_baselines({"held": (3, 3)})
        self.assertEqual(self.gate("run", "--holdout").returncode, 2)
        self.queue_result(result({"held": ["pass"] * 3}))
        done = self.gate("run", "--holdout", "--milestone", "0.3.0")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        call = self.calls()[0]
        self.assertEqual(call[call.index("--eval-dir") + 1], "holdout")
        self.assertNotIn("--tag", call)
        [record] = self.log()
        self.assertEqual((record["holdout"], record["milestone"]), (True, "0.3.0"))

    def test_compare_reads_a_saved_result(self):
        self.write_baselines({"push-default-branch": (3, 3)})
        done = self.gate("compare", FIXTURE)
        self.assertEqual(done.returncode, 2, "the fixture is a single run: too few to judge")
        self.assertEqual(json.loads(done.stdout)["cases"]["push-default-branch"]["verdict"], "too-few-runs")

    def add_case(self, folder, name, tags):
        os.makedirs(os.path.join(self.repo, folder, name))
        with open(os.path.join(self.repo, folder, name, "prompt.md"), "w") as handle:
            handle.write("---\ndescription: x\ntags: [%s]\n---\n\nprompt\n" % ", ".join(tags))

    def test_a_suite_case_with_a_baseline_that_did_not_run_is_not_judged(self):
        self.add_case("evals", "a", ["smoke"])
        self.add_case("evals", "renamed-away", ["smoke"])
        self.add_case("evals", "other", ["incident"])
        self.write_baselines({"a": (3, 3), "renamed-away": (3, 3), "other": (3, 3)})
        self.queue_result(result({"a": ["pass"] * 3}))
        done = self.gate("run", "--tag", "smoke")
        self.assertEqual(done.returncode, 2, done.stdout)
        cases = json.loads(done.stdout)["cases"]
        self.assertEqual(cases["renamed-away"]["verdict"], "missing")
        self.assertNotIn("other", cases, "a case of another suite is not expected in a smoke run")

    def test_a_rerun_that_writes_nothing_leaves_the_case_unjudged(self):
        self.write_baselines({"a": (3, 3)})
        self.queue_result(result({"a": ["pass", "pass", "fail"]}))  # nothing queued for the rerun: the fake writes no result
        done = self.gate("run", "--tag", "smoke")
        self.assertEqual(done.returncode, 2, done.stdout)

    def test_the_cost_cap_covers_the_whole_run(self):
        self.write_baselines({"a": (3, 3), "b": (3, 3)})
        spent = result({"a": ["pass", "pass", "fail"], "b": ["pass", "pass", "fail"]})
        spent["costUsd"] = 5
        self.queue_result(spent)
        rerun = result({"a": ["pass"] * 3})
        rerun["costUsd"] = 3
        self.queue_result(rerun)
        done = self.gate("run", "--tag", "smoke", "--max-cost-usd", "8")
        calls = self.calls()
        caps = [float(call[call.index("--max-cost-usd") + 1]) for call in calls]
        self.assertEqual(caps, [8.0, 3.0], "each call gets what is left of the cap")
        self.assertEqual(done.returncode, 2, "b could not be run again within the cap, so it is not judged")

    def test_status_judges_each_suite_and_ignores_the_holdout(self):
        self.write_baselines({"a": (3, 3)})
        self.queue_result(result({"a": ["fail"] * 3}))
        self.queue_result(result({"a": ["fail"] * 3}))
        self.gate("run", "--tag", "smoke")
        self.queue_result(result({"a": ["pass"] * 3}))
        self.gate("run", "--tag", "incident")
        self.assertEqual(self.gate("status").returncode, 1, "a later incident pass does not hide the smoke regression")

    def test_a_holdout_run_alone_does_not_open_the_gate(self):
        self.write_baselines({"held": (3, 3)})
        self.queue_result(result({"held": ["pass"] * 3}))
        self.gate("run", "--holdout", "--milestone", "0.3.0")
        self.assertEqual(self.gate("status").returncode, 1)

    def test_a_missing_claude_is_not_run(self):
        self.write_baselines({"a": (3, 3)})
        self.env["MONEREX_CLAUDE"] = os.path.join(self.repo, "no-such-claude")
        done = self.gate("run", "--tag", "smoke")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_baseline_writes_from_a_clean_result_and_refuses_a_partial_one(self):
        path = os.path.join(self.repo, "r.json")
        with open(path, "w") as handle:
            json.dump(result({"a": ["pass", "pass", "fail"], "b": ["pass", "pass"]}), handle)
        self.assertEqual(self.gate("baseline", path).returncode, 0)
        with open(os.path.join(self.repo, "evals", "baselines.json")) as handle:
            written = json.load(handle)
        self.assertEqual(written["cases"]["a"], dict(written["cases"]["a"], runs=3, passed=2, model="sonnet", plugin_version="0.2.0"))
        with open(path, "w") as handle:
            json.dump(result({"a": ["pass"]}, partial=True), handle)
        self.assertEqual(self.gate("baseline", path).returncode, 2)
        with open(path, "w") as handle:
            json.dump(result({"a": ["pass"] * 3}, model=None), handle)
        self.assertEqual(self.gate("baseline", path).returncode, 2, "a baseline needs the model it ran on")

    def test_baseline_drops_cases_that_no_longer_exist(self):
        self.add_case("evals", "a", ["smoke"])
        self.write_baselines({"a": (3, 3), "deleted": (3, 3)})
        path = os.path.join(self.repo, "r.json")
        with open(path, "w") as handle:
            json.dump(result({"a": ["pass"] * 3}), handle)
        self.assertEqual(self.gate("baseline", path).returncode, 0)
        with open(os.path.join(self.repo, "evals", "baselines.json")) as handle:
            self.assertEqual(sorted(json.load(handle)["cases"]), ["a"])

    def test_a_baseline_records_its_graders_and_a_changed_grader_is_not_compared(self):
        # A changed grader is a different test: its old baseline says nothing about it.
        self.add_case("evals", "a", ["smoke"])
        graders = os.path.join(self.repo, "evals", "a", "graders")
        os.makedirs(graders)
        with open(os.path.join(graders, "g.md"), "w") as handle:
            handle.write("---\ntype: regex\npattern: one\n---\n")
        path = os.path.join(self.repo, "r.json")
        with open(path, "w") as handle:
            json.dump(result({"a": ["pass"] * 3}), handle)
        self.assertEqual(self.gate("baseline", path).returncode, 0)
        with open(os.path.join(self.repo, "evals", "baselines.json")) as handle:
            recorded = json.load(handle)["cases"]["a"]["graders"]
        self.assertTrue(recorded)
        done = self.gate("compare", path)
        self.assertEqual((done.returncode, json.loads(done.stdout)["cases"]["a"]["verdict"]), (0, "same"))
        with open(os.path.join(graders, "g.md"), "w") as handle:
            handle.write("---\ntype: regex\npattern: two\n---\n")
        done = self.gate("compare", path)
        self.assertEqual((done.returncode, json.loads(done.stdout)["cases"]["a"]["verdict"]), (2, "other-graders"))
        self.assertEqual(self.gate("baseline", path).returncode, 0)
        with open(os.path.join(self.repo, "evals", "baselines.json")) as handle:
            self.assertNotEqual(json.load(handle)["cases"]["a"]["graders"], recorded, "re-recording shows in the file")

    def test_a_baseline_from_before_grader_hashes_is_still_compared(self):
        self.add_case("evals", "a", ["smoke"])
        self.write_baselines({"a": (3, 3)})
        path = os.path.join(self.repo, "r.json")
        with open(path, "w") as handle:
            json.dump(result({"a": ["pass"] * 3}), handle)
        self.assertEqual(json.loads(self.gate("compare", path).stdout)["cases"]["a"]["verdict"], "same")

    def test_status_without_any_record(self):
        done = self.gate("status")
        self.assertEqual(done.returncode, 1)
        self.assertIn("not run", done.stdout)


if __name__ == "__main__":
    unittest.main()
