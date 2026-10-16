"""The saved workflows, run against a stand-in runtime: no agent is started.

What is tested is what the scripts decide in code: who is dispatched on which route, how
findings are merged, what happens when an agent dies, and what is handed back. Whether the
real runtime honours an agent's tool list, or fires the guards, inside a workflow is not
something this can show.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(ROOT, "workflows")
HARNESS = os.path.join(ROOT, "tests", "workflow_harness.mjs")
NODE = shutil.which("node")
with open(os.path.join(ROOT, "routing", "routing.json"), encoding="utf-8") as handle:
    TABLE = json.load(handle)


def scripts():
    return sorted(name[:-3] for name in os.listdir(WORKFLOWS) if name.endswith(".js"))


def run(name, args=None, agents=(), path=None, misfits=False):
    scenario = json.dumps({"args": args, "agents": list(agents)})
    done = subprocess.run([NODE, HARNESS, path or os.path.join(WORKFLOWS, name + ".js")], input=scenario, capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(done.stderr)
    out = json.loads(done.stdout)
    if out["scenarioErrors"] and not misfits:
        raise AssertionError("the scenario gave an answer the script's schema would never let through: %s" % out["scenarioErrors"])
    return out


def finding(path, claim, severity="improvement", line=1):
    return {"path": path, "line": line, "claim": claim, "trigger": "when x", "severity": severity}


@unittest.skipUnless(NODE, "node is not installed")
class WorkflowTest(unittest.TestCase):
    def test_every_script_declares_itself_and_refuses_to_run_without_its_input(self):
        self.assertEqual(scripts(), ["audit", "migrate", "plan-from-angles", "review-wide"])
        for name in scripts():
            with self.subTest(name):
                out = run(name)
                self.assertEqual(out["meta"]["name"], name)
                self.assertGreater(len(out["meta"]["description"]), 30)
                self.assertTrue(out["meta"]["whenToUse"])
                self.assertIsNone(out["error"])
                self.assertIn("pass {", out["result"]["error"])
                self.assertEqual(out["calls"], [], "nothing may be dispatched before the input is known to be there")

    def test_the_routes_in_every_script_match_the_routing_table(self):
        row = re.compile(r"^\s+(\w+): \{ agentType: 'monerex:([\w-]+)', model: '(\w+)', effort: '(\w+)' \},$", re.M)
        for name in scripts():
            with open(os.path.join(WORKFLOWS, name + ".js"), encoding="utf-8") as handle:
                found = row.findall(handle.read())
            self.assertTrue(found, "%s names no routes" % name)
            for work, agent, model, effort in found:
                with self.subTest(script=name, work=work):
                    route = TABLE["routes"][work]
                    self.assertEqual((agent, model, effort), (route["agent"], TABLE["models"][route["model"]], route["effort"]))
                    self.assertTrue(os.path.exists(os.path.join(ROOT, "agents", agent + ".md")))

    def assert_nothing_inherited(self, out):
        phases = {entry["title"] for entry in out["meta"]["phases"]}
        for call in out["calls"]:
            with self.subTest(call=call["label"]):
                self.assertTrue(call["agentType"] and call["agentType"].startswith("monerex:"))
                self.assertTrue(call["model"] and call["effort"], "every dispatch names its model and effort")
                self.assertTrue(call["schema"] and call["label"])
                self.assertIn(call["phase"], phases)

    # ------------------------------------------------------------ review-wide

    def test_review_wide_merges_findings_verifies_each_and_ranks_what_survives(self):
        shared = finding("a.py", "Off by one in the loop", "critical", 12)
        agents = [
            {"match": "review:correctness", "returns": {"findings": [shared, finding("b.py", "Unhandled empty input")]}},
            {"match": "review:fit", "returns": {"findings": [dict(shared, claim="off by one  in the LOOP"), finding("c.py", "Plan asked for a flag", "nit")]}},
            {"match": "review:security", "returns": {"findings": [finding("d.py", "Token logged", "critical")]}},
            # no rule for review:tests: that reviewer died
            {"match": "Claim: Off by one", "returns": {"outcome": "reproduced", "how": "ran a test"}},
            {"match": "Claim: Unhandled empty input", "returns": {"outcome": "consistent", "how": "read it"}},
            {"match": "Claim: Plan asked for a flag", "returns": {"outcome": "refuted", "how": "the flag is there"}},
            # no rule for the token finding: its verifier died
        ]
        out = run("review-wide", {"diff": ".monerex/tmp/review.diff", "plan": "docs/work/x/plan.md"}, agents)
        self.assertIsNone(out["error"])
        self.assert_nothing_inherited(out)
        result = out["result"]
        self.assertEqual([f["claim"] for f in result["confirmed"]], ["Off by one in the loop"])
        self.assertEqual(result["confirmed"][0]["angles"], ["correctness", "fit"], "one finding from two reviewers is one finding")
        self.assertEqual([f["path"] for f in result["plausible"]], ["b.py"])
        self.assertEqual([f["path"] for f in result["rejected"]], ["c.py"])
        self.assertEqual([f["path"] for f in result["unchecked"]], ["d.py"], "an unverified finding is reported, not dropped")
        self.assertEqual(result["not_run"], ["reviewer for tests"])
        reviewers = [call for call in out["calls"] if call["phase"] == "Review"]
        verifiers = [call for call in out["calls"] if call["phase"] == "Verify"]
        self.assertEqual((len(reviewers), len(verifiers)), (4, 4))
        self.assertEqual({call["agentType"] for call in reviewers}, {"monerex:reviewer"})
        self.assertEqual({(call["agentType"], call["model"]) for call in verifiers}, {("monerex:verifier", "sonnet")})
        self.assertTrue(all("docs/work/x/plan.md" in call["prompt"] for call in reviewers))
        self.assertIn("4 candidate findings from 3 of 4 reviewers", out["logs"])

    def test_review_wide_in_segments_reviews_each_part_with_the_whole_in_reach_and_looks_across_them(self):
        segments = [
            {"name": "api", "diff": ".monerex/tmp/review-1.diff", "paths": ["api/a.py"]},
            {"name": "web", "diff": ".monerex/tmp/review-2.diff", "paths": ["web/b.ts"]},
        ]
        agents = [
            {"match": "review:correctness:api", "returns": {"findings": [finding("api/a.py", "Returns null for an empty list")]}},
            {"match": "Synthesise", "returns": {"findings": [finding("web/b.ts", "Calls the renamed endpoint by its old name", "critical")]}},
            {"match": "Claim: Returns null", "returns": {"outcome": "reproduced", "how": "ran it"}},
            {"match": "Claim: Calls the renamed", "returns": {"outcome": "consistent", "how": "read both sides"}},
        ]
        out = run("review-wide", {"diff": ".monerex/tmp/review.diff", "segments": segments}, agents)
        self.assertIsNone(out["error"])
        self.assert_nothing_inherited(out)
        reviewers = [call for call in out["calls"] if call["phase"] == "Review"]
        self.assertEqual(len(reviewers), 8, "every angle on every segment")
        for call in reviewers:
            self.assertIn(".monerex/tmp/review.diff", call["prompt"], "the whole diff stays in reach")
            self.assertTrue(any(segment["diff"] in call["prompt"] for segment in segments))
        [synthesis] = [call for call in out["calls"] if call["phase"] == "Synthesise"]
        self.assertEqual((synthesis["agentType"], synthesis["model"]), ("monerex:reviewer", "opus"))
        self.assertIn("Returns null for an empty list", synthesis["prompt"], "it is shown what the segment reviews found")
        result = out["result"]
        self.assertEqual([f["claim"] for f in result["confirmed"]], ["Returns null for an empty list"])
        self.assertEqual(result["confirmed"][0]["segments"], ["api"])
        self.assertEqual([f["claim"] for f in result["plausible"]], ["Calls the renamed endpoint by its old name"])
        self.assertEqual(result["plausible"][0]["angles"], ["across segments"])

    def test_review_wide_refuses_segments_it_cannot_use(self):
        many = [{"name": "s%d" % n, "diff": "s%d.diff" % n, "paths": ["s%d/x" % n]} for n in range(4)]
        twice = [{"name": "a", "diff": "1.diff", "paths": ["a/x"]}, {"name": "a", "diff": "2.diff", "paths": ["a/y"]}]
        empty = [{"name": "a", "diff": "1.diff", "paths": []}, {"name": "b", "diff": "2.diff", "paths": ["b/y"]}]
        for segments in (many, [{"name": "a"}], "a.diff", twice, empty):
            with self.subTest(segments=segments):
                out = run("review-wide", {"diff": "d.diff", "segments": segments})
                self.assertIn("segments", out["result"]["error"])
                self.assertEqual(out["calls"], [])

    def test_review_wide_with_no_segments_reviews_the_whole_diff(self):
        out = run("review-wide", {"diff": "d.diff", "segments": []}, [])
        self.assertEqual(sorted(call["label"] for call in out["calls"]),
                         ["review:correctness", "review:fit", "review:security", "review:tests"], "segment_diff.py found nothing to split")

    def test_review_wide_keeps_the_part_reviews_when_the_reviewer_across_them_fails(self):
        segments = [{"name": "api", "diff": "1.diff", "paths": ["api/a.py"]}, {"name": "web", "diff": "2.diff", "paths": ["web/b.ts"]}]
        agents = [
            {"match": "review:correctness:api", "returns": {"findings": [finding("api/a.py", "Returns null for an empty list")]}},
            {"match": "Synthesise", "fail": True},
            {"match": "Claim: Returns null", "returns": {"outcome": "reproduced", "how": "ran it"}},
            {"match": "review:", "returns": {"findings": []}},  # the other part reviewers found nothing
        ]
        out = run("review-wide", {"diff": "d.diff", "segments": segments}, agents)
        self.assertIsNone(out["error"])
        self.assertEqual([f["claim"] for f in out["result"]["confirmed"]], ["Returns null for an empty list"])
        self.assertIn("reviewer across segments", out["result"]["not_run"])
        self.assertIn("1 candidate findings from 8 of 9 reviewers", out["logs"])

    def test_review_wide_refuses_angles_it_does_not_know_instead_of_reviewing_nothing(self):
        for angles in (["nothing"], [], ["security", "test"], "securty"):
            with self.subTest(angles=angles):
                out = run("review-wide", {"diff": "d.diff", "angles": angles})
                self.assertIn("angles must be some of", out["result"]["error"])
                self.assertEqual(out["calls"], [])

    def test_review_wide_looks_at_cost_only_when_asked(self):
        default = run("review-wide", {"diff": "d.diff"}, [])
        self.assertNotIn("review:performance", [call["label"] for call in default["calls"]])
        out = run("review-wide", {"diff": "d.diff", "angles": ["correctness", "performance"]}, [])
        reviewers = {call["label"]: call["prompt"] for call in out["calls"] if call["phase"] == "Review"}
        self.assertEqual(sorted(reviewers), ["review:correctness", "review:performance"])
        self.assertIn("N+1", reviewers["review:performance"])

    def test_review_wide_refuses_more_than_twelve_reviewers_instead_of_starting_them(self):
        def parts(count):
            return [{"name": "s%d" % n, "diff": "s%d.diff" % n, "paths": ["s%d/x" % n]} for n in range(count)]

        every = ["correctness", "fit", "security", "tests", "performance"]
        out = run("review-wide", {"diff": "d.diff", "angles": every, "segments": parts(3)})
        self.assertIn("at most 12 reviewers", out["result"]["error"])
        self.assertEqual(out["calls"], [])
        fits = run("review-wide", {"diff": "d.diff", "angles": every, "segments": parts(2)}, [])
        self.assertEqual(len([call for call in fits["calls"] if call["phase"] == "Review"]), 10)
        default = run("review-wide", {"diff": "d.diff", "segments": parts(3)}, [])
        self.assertEqual(len([call for call in default["calls"] if call["phase"] == "Review"]), 12)

    def test_review_wide_keeps_the_graver_severity_and_every_trigger_of_a_merged_finding(self):
        agents = [
            {"match": "review:correctness", "returns": {"findings": [dict(finding("a.py", "Input is not checked", "nit", 3), trigger="a blank name")]}},
            {"match": "review:security", "returns": {"findings": [dict(finding("a.py", "Input is not checked", "critical", 3), trigger="shell injection via name")]}},
            {"match": "Claim:", "returns": {"outcome": "reproduced", "how": "ran it"}},
        ]
        out = run("review-wide", {"diff": "d.diff", "angles": ["correctness", "security"]}, agents)
        merged = out["result"]["confirmed"]
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["severity"], merged[0]["trigger"], merged[0]["triggers"]), ("critical", "shell injection via name", ["a blank name", "shell injection via name"]))
        self.assertIn("a blank name / shell injection via name", [call for call in out["calls"] if call["phase"] == "Verify"][0]["prompt"])

    def test_review_wide_orders_by_severity_and_takes_a_subset_of_angles(self):
        agents = [
            {"match": "review:security", "returns": {"findings": [finding("n.py", "A nit", "nit"), finding("c.py", "A critical one", "critical"), finding("i.py", "An improvement")]}},
            {"match": "Claim:", "returns": {"outcome": "reproduced", "how": "ran it"}},
        ]
        out = run("review-wide", {"diff": "d.diff", "angles": ["security"]}, agents)
        self.assertEqual([f["severity"] for f in out["result"]["confirmed"]], ["critical", "improvement", "nit"])
        self.assertEqual(len([call for call in out["calls"] if call["phase"] == "Review"]), 1)
        self.assertEqual(out["result"]["not_run"], [])

    # ------------------------------------------------------------ audit

    def test_audit_checks_what_was_found_and_says_what_was_not_read(self):
        yes = {"found": True, "answer": "it retries forever", "evidence": [{"path": "a.py", "line": 3, "note": "loop"}]}
        agents = [
            {"match": "read:a.py", "returns": yes},
            {"match": "read:b.py", "returns": dict(yes, answer="it never times out")},
            {"match": "read:c.py", "returns": {"found": False, "answer": "does not apply", "evidence": []}},
            # d.py: the reader died
            {"match": "check:a.py", "returns": {"holds": True, "how": "read the loop"}},
            {"match": "check:b.py", "returns": {"holds": False, "how": "there is a timeout on line 9"}},
            {"match": "gaps", "returns": {"gaps": ["the retry helper in util/"]}},
        ]
        out = run("audit", {"question": "Where can a request hang?", "paths": ["a.py", "b.py", "c.py", "d.py"]}, agents)
        self.assertIsNone(out["error"])
        self.assert_nothing_inherited(out)
        result = out["result"]
        self.assertEqual([entry["path"] for entry in result["supported"]], ["a.py"])
        self.assertEqual([entry["path"] for entry in result["unsupported"]], ["b.py"])
        self.assertEqual((result["nothing_found"], result["not_read"], result["gaps"]), (["c.py"], ["d.py"], ["the retry helper in util/"]))
        self.assertEqual(len([call for call in out["calls"] if call["phase"] == "Check"]), 2, "only answers that found something are checked")

    def test_audit_keeps_what_it_found_when_a_later_agent_fails(self):
        yes = {"found": True, "answer": "it retries forever", "evidence": [{"path": "a.py", "line": 3, "note": "loop"}]}
        agents = [{"match": "read:a.py", "returns": yes}, {"match": "check:a.py", "fail": True}, {"match": "gaps", "fail": True}]
        out = run("audit", {"question": "Where can a request hang?", "paths": ["a.py"]}, agents)
        self.assertIsNone(out["error"], "a failing agent must not take the whole result with it")
        result = out["result"]
        self.assertEqual((result["not_read"], [entry["path"] for entry in result["unchecked"]]), ([], ["a.py"]), "the path was read; only its check is missing")
        self.assertEqual((result["gaps"], result["not_run"]), (None, ["the gap check"]))

    # ------------------------------------------------------------ plan-from-angles

    def test_plan_from_angles_needs_two_designs_to_compare(self):
        design = {"approach": "x", "files": ["a.py"], "risks": [], "checks": ["make test"], "open_questions": []}
        ruling = {"recommended": "smallest", "why": "least to go wrong", "taken_from_others": [], "against_each": [], "decisions_for_the_owner": []}
        agents = [{"match": "design:smallest", "returns": design}, {"match": "design:durable", "returns": design}, {"match": "judge", "returns": ruling}]
        out = run("plan-from-angles", {"task": "Add export", "intent": "docs/work/x/intent.md"}, agents)
        self.assert_nothing_inherited(out)
        self.assertEqual([entry["angle"] for entry in out["result"]["designs"]], ["smallest", "durable"])
        self.assertEqual((out["result"]["ruling"]["recommended"], out["result"]["not_run"]), ("smallest", ["design for safest"]))
        self.assertTrue(all("docs/work/x/intent.md" in call["prompt"] for call in out["calls"]))

        out = run("plan-from-angles", "Add export", agents[:1])
        self.assertIn("fewer than two designs", out["result"]["error"])
        self.assertEqual(len([call for call in out["calls"] if call["phase"] == "Judge"]), 0)

    def test_plan_from_angles_does_not_pass_on_a_ruling_for_a_design_that_was_not_drafted(self):
        design = {"approach": "x", "files": ["a.py"], "risks": [], "checks": ["make test"], "open_questions": []}
        ruling = {"recommended": "safest", "why": "y", "taken_from_others": [], "against_each": [], "decisions_for_the_owner": []}
        two = [{"match": "design:smallest", "returns": design}, {"match": "design:durable", "returns": design}]
        out = run("plan-from-angles", {"task": "Add export"}, two + [{"match": "judge", "returns": ruling}], misfits=True)
        self.assertEqual(len(out["scenarioErrors"]), 1, "the judge's answer is held to the designs that came back by the schema itself")
        self.assertIn("recommended is not one of smallest, durable", out["scenarioErrors"][0])
        self.assertIsNone(out["result"]["ruling"])
        out = run("plan-from-angles", {"task": "Add export"}, two + [{"match": "judge", "fail": True}])
        self.assertIsNone(out["error"])
        self.assertEqual((len(out["result"]["designs"]), out["result"]["not_run"]), (2, ["design for safest", "the judge"]))

    # ------------------------------------------------------------ migrate

    def test_migrate_gives_every_site_its_own_worktree_has_it_verified_and_merges_nothing(self):
        def report(site, **fields):
            return dict({"assessment": "clear", "changed": True, "summary": "renamed", "check_passed": True, "worktree": "/wt/" + site,
                         "site_found": True, "head_before": "a" * 40, "head_after": "a" * 40}, **fields)

        agents = [
            {"match": "change:a.py", "returns": report("a")},
            {"match": "change:b.py", "returns": report("b")},
            {"match": "change:h.py", "returns": report("h")},
            {"match": "verify:h.py", "returns": {"passes": True, "how": "ran it", "ran_in": "/the/main/checkout"}},
            {"match": "change:c.py", "returns": report("c", assessment="blocked", changed=False, check_passed=False)},
            {"match": "change:e.py", "returns": report("e", assessment="blocked")},  # says blocked, yet changed and passing
            {"match": "change:f.py", "returns": report("f")},
            {"match": "change:g.py", "fail": True},
            # d.py: no report came back
            {"match": "verify:a.py", "returns": {"passes": True, "how": "ran the check", "ran_in": "/wt/a/"}},
            {"match": "verify:b.py", "returns": {"passes": False, "how": "the check fails", "ran_in": "/wt/b"}},
            # f.py: its verifier died
        ]
        sites = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py", "g.py", "h.py"]
        out = run("migrate", {"change": "Rename getUser to fetchUser", "sites": sites, "check": "make test"}, agents)
        self.assertIsNone(out["error"])
        self.assert_nothing_inherited(out)
        result = out["result"]
        names = {key: [entry["site"] for entry in result[key]] for key in ("ready", "failing", "unverified", "left_alone")}
        self.assertEqual(names, {"ready": ["a.py"], "failing": ["b.py"], "unverified": ["f.py", "h.py"], "left_alone": ["c.py", "e.py"]})
        elsewhere = [entry for entry in result["unverified"] if entry["site"] == "h.py"][0]
        self.assertEqual(elsewhere["verified_elsewhere"], "/the/main/checkout", "a verifier that ran in the wrong tree does not make a site ready")
        self.assertEqual(result["no_report"], ["d.py", "g.py"])
        self.assertTrue(result["merged"].startswith("nothing"))
        writers = [call for call in out["calls"] if call["phase"] == "Change"]
        self.assertEqual(({call["isolation"] for call in writers}, {call["agentType"] for call in writers}), ({"worktree"}, {"monerex:implementer"}))
        self.assertTrue(all("Do not commit" in call["prompt"] for call in writers), "the implementer's own rule is that it never commits")
        checkers = [call for call in out["calls"] if call["phase"] == "Verify"]
        self.assertEqual(sorted(call["label"] for call in checkers), ["verify:a.py", "verify:b.py", "verify:f.py", "verify:h.py"], "only a clear, changed site is verified")
        self.assertTrue(all("cd /wt/" in call["prompt"] for call in checkers), "the verifier is sent to the worktree, not left in the main checkout")

    def test_migrate_says_why_when_no_writer_could_start(self):
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py", "b.py"]}, [{"match": "change:", "fail": True}])
        self.assertIsNone(out["error"])
        result = out["result"]
        self.assertEqual((result["ready"], result["no_report"]), ([], ["a.py", "b.py"]))
        self.assertIn("no agent could start", result["problem"])
        one = run("migrate", {"change": "x", "check": "y", "sites": ["a.py", "b.py"]},
                  [{"match": "change:a.py", "returns": {"assessment": "blocked", "changed": False, "summary": "n/a", "check_passed": False, "worktree": "/wt/a",
                                                        "site_found": True, "head_before": "a" * 40, "head_after": "a" * 40}}])
        self.assertIsNone(one["result"]["problem"], "one writer that came back means the session can start them")

    def test_migrate_says_so_when_the_sites_are_not_on_the_commit_the_worktrees_started_from(self):
        # Issue 5: the sites are on the branch the session is on, but an agent's worktree starts from
        # the default branch, which does not have them. Each writer reports a missing file.
        sites = ["scratch/a.py", "scratch/b.py", "scratch/c.py"]
        default_branch = "13e0a198ad6357a4c4d3c37ededa3f1c94cfb1dc"
        agents = [
            {"match": "change:" + site, "returns": {
                "assessment": "blocked", "changed": False, "check_passed": False, "worktree": "/wt/%d" % index,
                "summary": site + " does not exist: this worktree holds only the default branch's files",
                "site_found": False, "head_before": default_branch, "head_after": default_branch,
            }}
            for index, site in enumerate(sites)
        ]
        out = run("migrate", {"change": "Rename getUser to fetchUser", "sites": sites, "check": "make test"}, agents)
        self.assertIsNone(out["error"])
        result = out["result"]
        self.assertEqual((result["ready"], [entry["site"] for entry in result["left_alone"]]), ([], sites), "the symptom as reported: nothing ready, every site left alone")
        with self.subTest("the run says plainly that the sites were not found"):
            self.assertTrue(result["problem"], "problem is null: the run does not say the sites were not found on the base the worktrees started from")
            self.assertIn("not found", result["problem"])
            self.assertIn("started from", result["problem"])
            self.assertIn(default_branch, result["problem"], "it names the commit the worktrees started from")
        with self.subTest("the closing line makes no claim that a change was made"):
            self.assertNotIn("sits uncommitted", result["merged"], "merged says a change sits uncommitted in a worktree although no site was changed")

    @staticmethod
    def migrate_report(site, **fields):
        return dict({"assessment": "clear", "changed": True, "summary": "renamed", "check_passed": True, "worktree": "/wt/" + site,
                     "site_found": True, "head_before": "d" * 40, "head_after": "a" * 40}, **fields)

    def test_migrate_with_a_base_tells_every_writer_to_switch_to_it_and_without_one_never_mentions_git_switch(self):
        base = "a" * 40
        sites = ["a.py", "b.py"]
        agents = [{"match": "change:" + site, "returns": self.migrate_report(site)} for site in sites]
        out = run("migrate", {"change": "x", "check": "y", "sites": sites, "base": base}, agents)
        writers = [call for call in out["calls"] if call["phase"] == "Change"]
        self.assertEqual(len(writers), 2)
        for call in writers:
            self.assertIn("git switch --detach " + base, call["prompt"])
            self.assertIn("not an edit", call["prompt"])
            self.assertIn("git rev-parse HEAD", call["prompt"])
        out = run("migrate", {"change": "x", "check": "y", "sites": sites}, agents)
        writers = [call for call in out["calls"] if call["phase"] == "Change"]
        self.assertEqual(len(writers), 2)
        for call in writers:
            self.assertNotIn("git switch", call["prompt"])
            self.assertIn("git rev-parse HEAD", call["prompt"])

    def test_migrate_refuses_a_base_that_is_not_a_full_commit_id_and_accepts_one_that_is(self):
        for base in ["HEAD", "@", "main", "abc1234", "", "-" + "a" * 39, "a" * 40 + " ; ls"]:
            with self.subTest(refused=base):
                out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": base})
                self.assertIn("git rev-parse HEAD", out["result"]["error"])
                self.assertEqual(out["calls"], [])
        for base in ["a" * 40, "A" * 40, "a" * 64]:
            with self.subTest(accepted=base):
                out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": base},
                          [{"match": "change:a.py", "returns": self.migrate_report("a", head_after=base)}])
                self.assertIsNone(out["result"].get("error"))
                self.assertEqual(len(out["calls"]), 2)

    def test_migrate_puts_a_writer_that_ended_off_the_base_under_wrong_base_and_never_verifies_it(self):
        base = "a" * 40
        elsewhere = "13e0a198ad6357a4c4d3c37ededa3f1c94cfb1dc"
        agents = [
            {"match": "change:off.py", "returns": self.migrate_report("off", head_after=elsewhere)},
            {"match": "change:on.py", "returns": self.migrate_report("on", head_after=base.upper())},
            {"match": "verify:on.py", "returns": {"passes": True, "how": "ran it", "ran_in": "/wt/on"}},
        ]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["off.py", "on.py"], "base": base}, agents)
        result = out["result"]
        self.assertEqual([entry["site"] for entry in result["wrong_base"]], ["off.py"])
        self.assertEqual([entry["site"] for entry in result["ready"]], ["on.py"])
        for key in ("failing", "unverified", "left_alone"):
            self.assertEqual(result[key], [])
        self.assertEqual([call["label"] for call in out["calls"] if call["phase"] == "Verify"], ["verify:on.py"])
        self.assertIn(base, result["problem"])
        self.assertIn(elsewhere, result["problem"])
        self.assertIn("off.py", result["problem"])

    def test_migrate_leaves_a_site_that_was_not_found_on_the_base_alone_and_says_so(self):
        base = "a" * 40
        agents = [{"match": "change:a.py", "returns": self.migrate_report("a", site_found=False, head_before="d" * 40, head_after=base)}]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": base}, agents)
        result = out["result"]
        self.assertEqual([entry["site"] for entry in result["left_alone"]], ["a.py"], "a missing site is never changed, whatever else the report says")
        self.assertEqual((result["ready"], result["wrong_base"]), ([], []))
        self.assertEqual([call for call in out["calls"] if call["phase"] == "Verify"], [])
        self.assertIn("not found", result["problem"])
        self.assertIn(base, result["problem"])
        self.assertNotIn("unless { base }", result["problem"], "the owner already passed a base")
        self.assertIn("committed there", result["problem"])

    def test_migrate_tells_the_owner_about_base_when_a_site_was_not_found_and_none_was_given(self):
        agents = [{"match": "change:a.py", "returns": self.migrate_report("a", site_found=False, assessment="blocked", changed=False)}]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"]}, agents)
        self.assertIn("unless { base }", out["result"]["problem"])
        self.assertIn("worktree.baseRef", out["result"]["problem"])

    def test_migrate_keeps_the_uncommitted_sentence_when_a_blocked_writer_changed_the_file_and_not_otherwise(self):
        sites = ["e.py"]
        changed = [{"match": "change:e.py", "returns": self.migrate_report("e", assessment="blocked")}]
        out = run("migrate", {"change": "x", "check": "y", "sites": sites}, changed)
        self.assertEqual(out["result"]["merged"], "nothing. Each change sits uncommitted in its own worktree for the owner to review, commit and merge.")
        none = [{"match": "change:e.py", "returns": self.migrate_report("e", assessment="blocked", changed=False)}]
        out = run("migrate", {"change": "x", "check": "y", "sites": sites}, none)
        self.assertTrue(out["result"]["merged"].startswith("nothing"))
        self.assertIn("No writer reported a change", out["result"]["merged"])
        self.assertNotIn("sits uncommitted", out["result"]["merged"])
        self.assertNotIn("may still have left", out["result"]["merged"])
        out = run("migrate", {"change": "x", "check": "y", "sites": ["e.py", "g.py"]}, none + [{"match": "change:g.py", "fail": True}])
        self.assertIn("did not report may still have left an edit", out["result"]["merged"])

    def test_migrate_is_not_a_problem_when_every_writer_was_blocked_because_the_change_does_not_apply(self):
        sites = ["a.py", "b.py"]
        agents = [{"match": "change:" + site, "returns": self.migrate_report(site, assessment="blocked", changed=False, head_after="b" * 40)} for site in sites]
        out = run("migrate", {"change": "x", "check": "y", "sites": sites}, agents)
        self.assertIsNone(out["result"]["problem"])
        self.assertIn("b" * 40, out["result"]["base_note"], "without a base the run names the commit the work was done on")
        out = run("migrate", {"change": "x", "check": "y", "sites": sites, "base": "b" * 40}, agents)
        self.assertIsNone(out["result"]["problem"])
        self.assertIsNone(out["result"]["base_note"])

    def test_migrate_answer_without_site_found_is_a_scenario_error(self):
        answer = self.migrate_report("a")
        del answer["site_found"]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"]}, [{"match": "change:a.py", "returns": answer}], misfits=True)
        self.assertEqual(len(out["scenarioErrors"]), 1)
        self.assertIn("site_found", out["scenarioErrors"][0])

    def test_migrate_takes_a_repeated_site_once(self):
        agents = [{"match": "change:a.py", "returns": {"assessment": "clear", "changed": False, "summary": "nothing to do", "check_passed": True, "worktree": "/wt/a",
                                                       "site_found": True, "head_before": "a" * 40, "head_after": "a" * 40}}]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py", "a.py", "./a.py"]}, agents)
        self.assertEqual(len(out["calls"]), 1)
        self.assertIn("2 repeated site(s) taken once", out["logs"])

    def test_migrate_refuses_a_list_too_long_for_one_run(self):
        out = run("migrate", {"change": "x", "check": "y", "sites": ["f%d.py" % index for index in range(51)]})
        self.assertIn("Split the list", out["result"]["error"])
        self.assertEqual(out["calls"], [])

    def test_migrate_names_only_the_missing_site_when_another_was_changed_and_verified(self):
        agents = [
            {"match": "change:ok.py", "returns": self.migrate_report("ok")},
            {"match": "verify:ok.py", "returns": {"passes": True, "how": "ran it", "ran_in": "/wt/ok"}},
            {"match": "change:gone.py", "returns": self.migrate_report("gone", site_found=False, assessment="blocked", changed=False)},
        ]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["ok.py", "gone.py"]}, agents)
        result = out["result"]
        self.assertEqual([entry["site"] for entry in result["ready"]], ["ok.py"])
        self.assertEqual([entry["site"] for entry in result["left_alone"]], ["gone.py"])
        self.assertIn("not found", result["problem"])
        self.assertIn("gone.py", result["problem"])
        self.assertNotIn("ok.py", result["problem"])
        self.assertIn("sits uncommitted", result["merged"], "a change was reported, so the closing line keeps its claim")

    def test_migrate_reports_a_site_that_is_both_off_the_base_and_not_found_under_wrong_base_with_both_reasons(self):
        base = "a" * 40
        elsewhere = "c" * 40
        agents = [{"match": "change:a.py", "returns": self.migrate_report("a", site_found=False, assessment="blocked", changed=False, head_after=elsewhere)}]
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": base}, agents)
        result = out["result"]
        self.assertEqual([entry["site"] for entry in result["wrong_base"]], ["a.py"])
        self.assertEqual(result["left_alone"], [])
        self.assertEqual([call for call in out["calls"] if call["phase"] == "Verify"], [])
        self.assertIn("ended on a commit other than the base", result["problem"])
        self.assertIn("not found", result["problem"])

    def test_migrate_refuses_a_base_with_a_trailing_newline(self):
        out = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": "a" * 40 + "\n"})
        self.assertIn("git rev-parse HEAD", out["result"]["error"])
        self.assertEqual(out["calls"], [])

    def test_migrate_tells_every_writer_to_stop_when_the_switch_to_the_base_fails(self):
        base = "a" * 40
        sites = ["a.py", "b.py"]
        agents = [{"match": "change:" + site, "returns": self.migrate_report(site)} for site in sites]
        out = run("migrate", {"change": "x", "check": "y", "sites": sites, "base": base}, agents)
        writers = [call for call in out["calls"] if call["phase"] == "Change"]
        self.assertEqual(len(writers), 2)
        for call in writers:
            self.assertIn("then stop and change nothing", call["prompt"])

    def test_migrate_warns_that_head_is_detached_only_when_a_base_was_given_and_a_change_was_reported(self):
        base = "a" * 40
        changed = [{"match": "change:a.py", "returns": self.migrate_report("a", head_after=base)},
                   {"match": "verify:a.py", "returns": {"passes": True, "how": "ran it", "ran_in": "/wt/a"}}]
        merged = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": base}, changed)["result"]["merged"]
        self.assertTrue(merged.startswith("nothing"))
        self.assertIn("sits uncommitted", merged)
        self.assertTrue(merged.endswith("started from."))
        self.assertIn("detached", merged)
        self.assertIn("git switch -c", merged)
        merged = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"]}, changed)["result"]["merged"]
        self.assertNotIn("detached", merged)
        none = [{"match": "change:a.py", "returns": self.migrate_report("a", head_after=base, assessment="blocked", changed=False)}]
        merged = run("migrate", {"change": "x", "check": "y", "sites": ["a.py"], "base": base}, none)["result"]["merged"]
        self.assertNotIn("detached", merged)

    # ------------------------------------------------------------ the stand-in itself

    def test_the_stand_in_keeps_the_runtime_s_rules(self):
        folder = tempfile.mkdtemp(prefix="monerex-workflow-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)

        def script(body):
            path = os.path.join(folder, "t.js")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("export const meta = {\n  name: 't',\n  description: 'x',\n}\n" + body)
            return path

        self.assertIn("not available", run("t", path=script("return Date.now()\n"))["error"])
        self.assertIn("not available", run("t", path=script("return Math.random()\n"))["error"])
        self.assertIn("not available", run("t", path=script("return new Date().getTime()\n"))["error"])
        self.assertEqual(run("t", path=script("return new Date(0).getTime()\n"))["result"], 0, "a date that was passed in is fine")
        self.assertEqual(run("t", path=script("return [typeof process, typeof fetch, typeof require]\n"))["result"], ["undefined"] * 3)
        wrong = run("t", path=script("return await agent('x', {label: 'one', schema: {type: 'object', properties: {n: {type: 'integer'}}, required: ['n']}})\n"),
                    agents=[{"match": "one", "returns": {"n": "seven"}}], misfits=True)
        self.assertIn("does not fit the schema", wrong["scenarioErrors"][0])
        out = run("t", path=script("return await parallel([() => agent('a', {label: 'one'}), () => { throw new Error('x') }])\n"), agents=[{"match": "one", "returns": 1}])
        self.assertEqual(out["result"], [1, None], "a failed branch of parallel is null, not an error")
        out = run("t", path=script("return await pipeline([1, 2], (n) => { if (n === 2) throw new Error('x'); return n }, (n) => n * 10)\n"))
        self.assertEqual(out["result"], [10, None], "an item whose stage throws drops to null and skips the rest")
        with open(os.path.join(folder, "bad.js"), "w", encoding="utf-8") as handle:
            handle.write("const NAME = 't'\nexport const meta = {\n  name: NAME,\n}\n")
        done = subprocess.run([NODE, HARNESS, os.path.join(folder, "bad.js")], input="{}", capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0, "meta must come first and be a pure literal")


if __name__ == "__main__":
    unittest.main()
