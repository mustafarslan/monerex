"""The security posture report: shown in full when it is new or changed, in one line after that."""

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
        # HOME is the test's own, so the settings of whoever runs the tests do not count.
        self.env = dict({key: value for key, value in os.environ.items() if key not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")},
                        HOME=self.tmp)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def report(self, *args):
        done = subprocess.run([sys.executable, "-I", POSTURE, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def settings(self, data):
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        with open(os.path.join(self.repo, ".claude", "settings.local.json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_gaps_are_listed_once_then_summed_up_in_one_line(self):
        first = self.report()
        self.assertIn("not set: sandbox is on", first)
        again = self.report()
        self.assertEqual(len(again.strip().split("\n")), 1)
        self.assertIn("6 gaps, unchanged", again)
        self.assertIn("not set: sandbox is on", self.report("--full"))

    def test_a_change_in_the_gaps_is_listed_in_full_again(self):
        self.report()
        self.settings({"sandbox": {"enabled": True}})
        changed = self.report()
        self.assertIn("not set: unsandboxed retry is off", changed)
        self.assertNotIn("not set: sandbox is on", changed)

    def test_a_repository_that_has_not_opted_in_gets_the_full_list_and_nothing_written(self):
        shutil.rmtree(os.path.join(self.repo, ".monerex"))
        self.report()
        self.assertIn("not set: sandbox is on", self.report())
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".monerex")))

    def test_json_is_unchanged_by_what_was_seen(self):
        self.report()
        self.assertEqual(len(json.loads(self.report("--json"))["missing"]), 6)


if __name__ == "__main__":
    unittest.main()
