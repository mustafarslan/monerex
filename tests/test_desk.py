"""Counting open monerex tasks and building the command that starts another."""

import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESK = os.path.join(ROOT, "scripts", "desk.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import desk  # noqa: E402


def row(name, cwd="/work/a", status="busy", pid=100):
    return {"name": name, "cwd": cwd, "status": status, "pid": pid, "kind": "background", "sessionId": "s"}


class CountTest(unittest.TestCase):
    def test_only_sessions_named_as_monerex_tasks_are_counted(self):
        rows = [row("monerex: fix-login"), row("Monerex: add-export", pid=101), row("something else", pid=102), row(None, pid=103)]
        result = desk.count(rows)
        self.assertEqual((result["others"], result["known"]), (2, True))

    def test_one_more_task_is_over_the_limit_when_the_limit_is_already_reached(self):
        rows = [row("monerex: a"), row("monerex: b", pid=101)]
        self.assertFalse(desk.count(rows[:1], limit=2)["over"])
        self.assertTrue(desk.count(rows, limit=2)["over"])
        self.assertFalse(desk.count(rows, limit=3)["over"])

    def test_the_session_asking_is_not_counted(self):
        rows = [row("monerex: a", pid=100), row("monerex: b", pid=101)]
        self.assertEqual(desk.count(rows, own={100})["others"], 1)

    def test_statuses_are_tallied_as_the_listing_gives_them(self):
        rows = [row("monerex: a"), row("monerex: b", status="idle", pid=101), row("monerex: c", status=None, pid=102)]
        self.assertEqual(desk.count(rows)["by_status"], {"busy": 1, "idle": 1, "unknown": 1})

    def test_a_task_already_open_in_the_same_repository_is_reported(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-desk-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        rows = [row("monerex: a", cwd=os.path.join(tmp, "sub")), row("monerex: b", cwd=tmp + "-other", pid=101)]
        self.assertEqual(desk.count(rows, repo=tmp)["same_repo"], 1)

    def test_an_unreadable_or_empty_listing_is_reported_as_unknown_and_never_over(self):
        for rows in (None, []):
            with self.subTest(rows=rows):
                result = desk.count(rows)
                self.assertEqual((result["known"], result["over"]), (False, False))

    def test_the_session_asking_is_left_out_whatever_type_its_pid_arrives_as(self):
        rows = [row("monerex: a", pid="100"), row("monerex: b", pid=101)]
        self.assertEqual(desk.count(rows, own={100})["others"], 1)
        self.assertEqual(desk.count(rows, own={"101"})["others"], 1)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="monerex desk-"))  # a space, on purpose
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)

    def test_the_command_starts_a_named_background_session_in_the_repository(self):
        result = desk.command(self.repo, "fix-login", "fix the login redirect; don't touch the API")
        words = shlex.split(result["command"])
        self.assertEqual(words[:3], ["cd", self.repo, "&&"])
        self.assertEqual(words[3:7], ["claude", "--bg", "--name", "monerex: fix-login"])
        self.assertEqual(words[-1], "/monerex:start fix the login redirect; don't touch the API")
        self.assertFalse(result["configured"])

    def test_the_task_text_cannot_add_a_second_command(self):
        result = desk.command(self.repo, "x", "tidy up; rm -rf ~ && $(whoami) `id`")
        words = shlex.split(result["command"])
        self.assertEqual(words.count("&&"), 1)
        self.assertEqual(len(words), 8)
        self.assertEqual(words[-1], "/monerex:start tidy up; rm -rf ~ && $(whoami) `id`")

    def test_a_configured_repository_and_a_plugin_directory_are_reported(self):
        os.makedirs(os.path.join(self.repo, ".monerex"))
        with open(os.path.join(self.repo, ".monerex", "config.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        result = desk.command(self.repo, "x", "do it", plugin_dir=ROOT)
        self.assertTrue(result["configured"])
        self.assertIn("--plugin-dir", shlex.split(result["command"]))

    def test_a_task_can_be_given_its_own_checkout(self):
        words = shlex.split(desk.command(self.repo, "add-export", "add an export", worktree=True)["command"])
        self.assertEqual(words[words.index("--worktree") + 1], "add-export")
        self.assertNotIn("--worktree", shlex.split(desk.command(self.repo, "add-export", "add an export")["command"]))

    def test_bad_arguments_are_refused(self):
        for repo, slug, task in ((self.repo + "-missing", "x", "t"), (self.repo, "Bad Slug", "t"), (self.repo, "x", "  ")):
            with self.subTest(slug=slug, task=task):
                with self.assertRaises(ValueError):
                    desk.command(repo, slug, task)


class CommandLineTest(unittest.TestCase):
    """The real script, with a stand-in for the `claude` program on PATH."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-desk-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, ".monerex"))
        with open(os.path.join(self.repo, ".monerex", "config.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)

    def fake_claude(self, body):
        path = os.path.join(self.bin, "claude")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def run_desk(self, *args):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        done = subprocess.run([sys.executable, "-I", DESK, *args], capture_output=True, text=True, env=env, cwd=self.repo)
        return done, (json.loads(done.stdout) if done.stdout.strip().startswith("{") else None)

    def test_count_reads_the_listing_and_the_repository_limit(self):
        listing = [row("monerex: a", cwd=self.repo), row("monerex: b", cwd="/elsewhere", pid=101), row("private thing", cwd="/secret/place", pid=102)]
        with open(os.path.join(self.tmp, "listing.json"), "w", encoding="utf-8") as handle:
            json.dump(listing, handle)
        self.fake_claude('cat "%s"' % os.path.join(self.tmp, "listing.json"))
        with open(os.path.join(self.repo, ".monerex", "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"max_open_tasks": 3}, handle)
        done, result = self.run_desk("count", "--repo", self.repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((result["others"], result["same_repo"], result["limit"], result["over"]), (2, 1, 3, False))
        self.assertNotIn("private thing", done.stdout)
        self.assertNotIn("/secret/place", done.stdout)
        self.assertNotIn("/elsewhere", done.stdout)

    def test_count_does_not_fail_when_the_listing_cannot_be_read(self):
        self.fake_claude("echo not json; exit 3")
        done, result = self.run_desk("count")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(result["known"])

    def test_command_prints_the_line_to_run(self):
        done, result = self.run_desk("command", self.repo, "add-export", "add", "a", "CSV", "export")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(shlex.split(result["command"])[-1], "/monerex:start add a CSV export")
        self.assertTrue(result["configured"])

    def test_a_bad_slug_is_a_usage_error(self):
        done, _ = self.run_desk("command", self.repo, "Not A Slug", "task")
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
