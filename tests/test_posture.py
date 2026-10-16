"""The security posture report: with --once, in full when new or changed and in one line after that."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTURE = os.path.join(ROOT, "scripts", "posture.py")


class PostureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-posture-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, ".monerex"))
        # HOME is the test's own, so the settings and state of whoever runs the tests do not count.
        self.env = dict({key: value for key, value in os.environ.items()
                         if key not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "XDG_STATE_HOME")}, HOME=self.tmp)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def report(self, *args):
        done = subprocess.run([sys.executable, "-I", POSTURE, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def settings(self, data):
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        with open(os.path.join(self.repo, ".claude", "settings.local.json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_with_once_gaps_are_listed_once_then_summed_up_in_one_line(self):
        self.assertIn("not set: sandbox is on", self.report("--once"))
        again = self.report("--once")
        self.assertEqual(len(again.strip().split("\n")), 1)
        self.assertIn("6 gaps, unchanged", again)

    def test_without_once_the_list_is_always_full(self):
        # Other callers (consult) must not use up the one time the user sees the list.
        self.report()
        self.report()
        self.assertIn("not set: sandbox is on", self.report("--once"))

    def test_a_change_in_which_gaps_are_open_is_listed_in_full_again_even_at_the_same_count(self):
        self.settings({"sandbox": {"enabled": True}})
        self.report("--once")
        self.settings({"sandbox": {"allowUnsandboxedCommands": False}})  # sandbox off again, retry fixed: still 5
        changed = self.report("--once")
        self.assertIn("not set: sandbox is on", changed)

    def test_what_was_seen_is_kept_outside_the_repository(self):
        # A clone could commit a "seen" record, or a link through which the record would overwrite a file.
        planted = os.path.join(self.repo, ".monerex", "state")
        os.makedirs(planted)
        target = os.path.join(self.tmp, "victim.txt")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("keep me\n")
        os.symlink(target, os.path.join(planted, "posture-seen"))
        self.assertIn("not set: sandbox is on", self.report("--once"))
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "keep me\n")
        self.assertEqual(os.listdir(planted), ["posture-seen"])

    def test_closing_every_gap_forgets_them_so_a_relapse_is_listed_in_full(self):
        self.report("--once")
        self.settings({"sandbox": {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                                   "network": {"allowedDomains": []}},
                       "permissions": {"ask": ["Bash(git push:*)"], "deny": ["Read(./.env)"]}})
        self.assertIn("in place", self.report("--once"))
        os.remove(os.path.join(self.repo, ".claude", "settings.local.json"))
        self.assertIn("not set: sandbox is on", self.report("--once"))

    def test_json_is_unchanged_by_what_was_seen(self):
        self.report("--once")
        self.assertEqual(len(json.loads(self.report("--json"))["missing"]), 6)


if __name__ == "__main__":
    unittest.main()
