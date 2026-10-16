"""Optional capabilities: what is probed, and what may be sent to a second reviewer."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "scripts", "probe.py")
SECOND = os.path.join(ROOT, "scripts", "second_opinion.py")
TERM = "zorblatt-industries"
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


class CapabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-cap-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(os.path.join(self.repo, ".monerex"))
        os.makedirs(self.bin)
        denylist = os.path.join(self.tmp, "denylist.txt")
        with open(denylist, "w", encoding="utf-8") as handle:
            handle.write(TERM + "\n")
        # A PATH with only our stand-ins and the system tools, so what is installed here does not leak in.
        self.env = dict(os.environ, PATH=self.bin + os.pathsep + "/usr/bin:/bin", MONEREX_DENYLIST=denylist, HOME=self.tmp)
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.env.pop(name, None)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def configure(self, **config):
        with open(os.path.join(self.repo, ".monerex", "config.json"), "w", encoding="utf-8") as handle:
            json.dump(config, handle)

    def program(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def brief(self, text):
        path = os.path.join(self.repo, ".monerex", "brief.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def run_script(self, script, *args):
        done = subprocess.run([sys.executable, "-I", script, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        return done, (json.loads(done.stdout) if done.stdout.strip().startswith("{") else None)

    # ------------------------------------------------------------ probe

    def test_nothing_optional_is_present_in_a_bare_repository(self):
        done, result = self.run_script(PROBE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(result["architecture_gate"]["present"])
        self.assertEqual((result["second_reviewer"]["present"], result["second_reviewer"]["usable"]), (False, False))
        # Whether `gh` is installed depends on the machine; that no repository is named does not.
        self.assertEqual((result["code_host"]["repo"], result["own_agents"]), (None, []))

    def test_an_architecture_gate_needs_its_config_and_a_way_to_run(self):
        with open(os.path.join(self.repo, "oxn.yaml"), "w", encoding="utf-8") as handle:
            handle.write("version: 1\n")
        _, result = self.run_script(PROBE)
        self.assertFalse(result["architecture_gate"]["present"])
        self.assertIn("cannot be run", result["architecture_gate"]["reason"])
        self.program("oxn", "exit 0")
        _, result = self.run_script(PROBE)
        self.assertEqual((result["architecture_gate"]["present"], result["architecture_gate"]["command"]), (True, "oxn"))

    def test_the_gate_says_whether_it_can_explain_a_finding(self):
        # `oxn explain` arrived in oxn 0.2.0; an older install answers --help with an error.
        with open(os.path.join(self.repo, "oxn.yaml"), "w", encoding="utf-8") as handle:
            handle.write("version: 1\n")
        self.program("oxn", 'if [ "$1" = explain ]; then exit 2; fi; exit 0')
        _, result = self.run_script(PROBE)
        self.assertEqual((result["architecture_gate"]["present"], result["architecture_gate"]["explain"]), (True, False))
        self.program("oxn", "exit 0")
        _, result = self.run_script(PROBE)
        self.assertTrue(result["architecture_gate"]["explain"])

    def test_probing_for_the_architecture_gate_runs_no_code_from_the_repository(self):
        # Found by review: `python -m oxn` from the repository's folder ran its own oxn.py.
        with open(os.path.join(self.repo, "oxn.yaml"), "w", encoding="utf-8") as handle:
            handle.write("version: 1\n")
        marker = os.path.join(self.tmp, "ran")
        with open(os.path.join(self.repo, "oxn.py"), "w", encoding="utf-8") as handle:
            handle.write("open(%r, 'w').write('x')\n" % marker)
        self.run_script(PROBE)
        self.assertFalse(os.path.exists(marker), "the repository's oxn.py ran")

    def module(self):
        # A stand-in oxn module, importable from PYTHONPATH like an installed one.
        package = os.path.join(self.tmp, "site", "oxn")
        os.makedirs(package)
        with open(os.path.join(package, "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write("")
        with open(os.path.join(package, "__main__.py"), "w", encoding="utf-8") as handle:
            handle.write("print('the installed oxn')\n")
        self.env["PYTHONPATH"] = os.path.dirname(package)

    @unittest.skipIf(sys.version_info < (3, 11), "-P needs Python 3.11")
    def test_the_module_command_the_stages_run_never_runs_the_repository_s_oxn_py(self):
        # Found by review: the stages ran the probe's `python3 -m oxn` from the repository's folder.
        self.module()
        with open(os.path.join(self.repo, "oxn.yaml"), "w", encoding="utf-8") as handle:
            handle.write("version: 1\n")
        marker = os.path.join(self.tmp, "ran")
        with open(os.path.join(self.repo, "oxn.py"), "w", encoding="utf-8") as handle:
            handle.write("open(%r, 'w').write('x')\n" % marker)
        _, result = self.run_script(PROBE)
        gate = result["architecture_gate"]
        self.assertEqual((gate["present"], gate["command"]), (True, "python3 -P -m oxn"))
        argv = [sys.executable] + gate["command"].split()[1:] + ["--version"]
        done = subprocess.run(argv, cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "the installed oxn")
        self.assertFalse(os.path.exists(marker), "the repository's oxn.py ran")

    def test_a_second_reviewer_is_usable_only_when_named_installed_and_allowed(self):
        self.program("agy-ask", "echo fine")
        self.configure(second_reviewer="agy")  # the policy defaults to off
        _, result = self.run_script(PROBE)
        self.assertEqual((result["second_reviewer"]["present"], result["second_reviewer"]["usable"]), (True, False))
        self.configure(second_reviewer="agy", external_review="diff-only")
        _, result = self.run_script(PROBE)
        self.assertTrue(result["second_reviewer"]["usable"])
        self.configure(second_reviewer="something-else", external_review="on")
        _, result = self.run_script(PROBE)
        self.assertEqual((result["second_reviewer"]["name"], result["second_reviewer"]["usable"]), (None, False))

    def test_the_code_host_repository_is_read_from_the_remote(self):
        self.program("gh", "exit 0")
        for url in ("git@github.com:someone/project.git", "https://github.com/someone/project"):
            with self.subTest(url):
                subprocess.run(["git", "remote", "remove", "origin"], cwd=self.repo, env=self.env, capture_output=True)
                subprocess.run(["git", "remote", "add", "origin", url], cwd=self.repo, env=self.env, capture_output=True, check=True)
                _, result = self.run_script(PROBE)
                self.assertEqual(result["code_host"], {"present": True, "repo": "someone/project"})

    def test_the_repository_s_own_agents_are_listed(self):
        os.makedirs(os.path.join(self.repo, ".claude", "agents"))
        for name in ("db-reviewer.md", "notes.txt"):
            with open(os.path.join(self.repo, ".claude", "agents", name), "w", encoding="utf-8") as handle:
                handle.write("x\n")
        _, result = self.run_script(PROBE)
        self.assertEqual(result["own_agents"], ["db-reviewer"])

    # ------------------------------------------------------------ second opinion

    def test_nothing_is_sent_while_the_policy_is_off(self):
        self.program("agy-ask", "echo should-not-run > %s/ran" % self.tmp)
        self.configure(second_reviewer="agy")
        _, result = self.run_script(SECOND, "run", self.brief("Review this diff.\n"))
        self.assertEqual(result["status"], "not run")
        self.assertIn("external_review is off", result["reason"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ran")))

    def test_an_allowed_brief_is_sent_and_the_answer_saved(self):
        self.program("agy-ask", 'echo "1. off-by-one in tool.py:12"')
        self.configure(second_reviewer="agy", external_review="diff-only")
        _, result = self.run_script(SECOND, "run", self.brief("Review this diff.\n"))
        self.assertEqual((result["status"], result["reviewer"], result["answer"]), ("ran", "agy", ".monerex/tmp/second-opinion.txt"))
        with open(os.path.join(self.repo, ".monerex", "tmp", "second-opinion.txt"), encoding="utf-8") as handle:
            self.assertIn("off-by-one", handle.read())

    def test_under_diff_only_the_reviewer_starts_in_a_scratch_folder_with_only_the_brief(self):
        seen = os.path.join(self.tmp, "seen")
        self.program("agy-ask", 'pwd > %s; ls >> %s; echo "looks fine"' % (seen, seen))
        self.configure(second_reviewer="agy", external_review="diff-only")
        _, result = self.run_script(SECOND, "run", self.brief("Review this diff.\n"))
        self.assertEqual(result["status"], "ran")
        with open(seen, encoding="utf-8") as handle:
            where, *files = handle.read().split()
        self.assertFalse(os.path.realpath(where).startswith(self.repo), "it must not start inside the repository")
        self.assertEqual(files, ["brief.md"])
        self.assertFalse(os.path.exists(where), "the scratch folder is removed afterwards")
        self.configure(second_reviewer="agy", external_review="on")
        self.run_script(SECOND, "run", self.brief("Review this diff.\n"))
        with open(seen, encoding="utf-8") as handle:
            self.assertEqual(os.path.realpath(handle.read().split()[0]), self.repo)

    def test_a_reviewer_that_says_it_changed_the_tree_is_flagged_even_when_it_then_fails(self):
        self.configure(second_reviewer="agy", external_review="on")
        for ending, status in (('echo "looks fine"', "ran"), ("exit 2", "not run")):
            with self.subTest(status):
                self.program("agy-ask", 'echo "AGY_TREE_MODIFIED: something changed" >&2; ' + ending)
                _, result = self.run_script(SECOND, "run", self.brief("Review.\n"))
                self.assertEqual(result["status"], status)
                self.assertIn("tell the user", result["warning"])

    def test_a_required_denylist_that_is_missing_stops_the_brief(self):
        self.program("agy-ask", "echo should-not-run > %s/ran" % self.tmp)
        self.configure(second_reviewer="agy", external_review="on")
        os.remove(self.env["MONEREX_DENYLIST"])
        subprocess.run(["git", "config", "monerex.requireDenylist", "true"], cwd=self.repo, env=self.env, capture_output=True, check=True)
        done, result = self.run_script(SECOND, "run", self.brief("for " + TERM + "\n"))
        self.assertEqual(result["status"], "not run")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ran")))
        done, result = self.run_script(SECOND, "check", self.brief("plain\n"))
        self.assertEqual((done.returncode, result["clean"]), (1, False))

    def test_the_policy_comes_from_the_owner_s_checkout_not_from_a_worktree(self):
        self.program("agy-ask", "echo should-not-run > %s/ran" % self.tmp)
        self.configure(second_reviewer="agy")  # off, in the owner's checkout
        for args in (("config", "user.name", "T"), ("config", "user.email", "t@example.invalid"), ("add", "-A"), ("commit", "-q", "-m", "first")):
            subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)
        other = os.path.join(self.repo, ".claude", "worktrees", "pr-9")
        subprocess.run(["git", "worktree", "add", "-q", "-b", "theirs", other], cwd=self.repo, env=self.env, capture_output=True, check=True)
        with open(os.path.join(other, ".monerex", "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"second_reviewer": "agy", "external_review": "on"}, handle)  # what a pull request could carry
        brief = os.path.join(other, "brief.md")
        with open(brief, "w", encoding="utf-8") as handle:
            handle.write("Review.\n")
        done = subprocess.run([sys.executable, "-I", SECOND, "run", brief], cwd=other, env=self.env, capture_output=True, text=True)
        self.assertEqual(json.loads(done.stdout)["status"], "not run", done.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ran")))

    def test_a_brief_with_a_term_or_a_secret_never_leaves(self):
        self.program("agy-ask", "echo should-not-run > %s/ran" % self.tmp)
        self.configure(second_reviewer="agy", external_review="on")
        for text in ("for " + TERM + "\n", "key = " + FAKE_KEY + "\n", "key = " + FAKE_KEY + "  # monerex:allow\n"):
            with self.subTest(text[:8]):
                done, result = self.run_script(SECOND, "run", self.brief(text))
                self.assertEqual(result["status"], "not run")
                self.assertTrue(result["findings"])
                self.assertNotIn(TERM, done.stdout.lower())
                self.assertNotIn(FAKE_KEY, done.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "ran")))

    def test_a_reviewer_that_fails_is_reported_by_name_and_never_as_clean(self):
        self.configure(second_reviewer="agy", external_review="on")
        for code, fragment in ((3, "out of quota"), (4, "not signed in"), (2, "returned nothing"), (9, "exit 9")):
            with self.subTest(code):
                self.program("agy-ask", "exit %d" % code)
                _, result = self.run_script(SECOND, "run", self.brief("Review.\n"))
                self.assertEqual(result["status"], "not run")
                self.assertIn(fragment, result["reason"])
        self.program("agy-ask", "exit 0")  # ran, said nothing
        _, result = self.run_script(SECOND, "run", self.brief("Review.\n"))
        self.assertEqual(result["status"], "not run")

    def test_check_scans_without_sending(self):
        done, result = self.run_script(SECOND, "check", self.brief("plain\n"))
        self.assertEqual((done.returncode, result["clean"]), (0, True))
        done, result = self.run_script(SECOND, "check", self.brief("for " + TERM + "\n"))
        self.assertEqual((done.returncode, result["clean"]), (1, False))
        self.assertNotIn(TERM, done.stdout.lower())


if __name__ == "__main__":
    unittest.main()
