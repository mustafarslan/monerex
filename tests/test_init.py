"""Opting a repository in: what init.py finds to run as the checks, and what it writes."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = os.path.join(ROOT, "scripts", "init.py")
IGNORED = [".monerex/state/", ".monerex/log/", ".monerex/tmp/", ".claude/worktrees/"]


class InitTest(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="monerex-init-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        env = {key: value for key, value in os.environ.items() if key not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
        self.env = env
        subprocess.run(["git", "init", "-q"], cwd=self.repo, env=env, capture_output=True, check=True)

    def write(self, path, text):
        full = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def run_init(self, *args):
        done = subprocess.run([sys.executable, "-I", INIT, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        return done, (json.loads(done.stdout) if done.stdout.strip().startswith("{") else None)

    def candidates(self):
        return self.run_init("detect")[1]["candidates"]

    def test_the_test_command_is_found_from_what_the_repository_already_has(self):
        cases = [
            ("package.json", json.dumps({"scripts": {"test": "jest"}}), "npm test"),
            ("go.mod", "module example.com/x\n", "go test ./..."),
            ("Cargo.toml", "[package]\nname = \"x\"\n", "cargo test"),
            ("Makefile", "build:\n\tcc x.c\ntest:\n\t./run-tests\n", "make test"),
            ("pyproject.toml", "[tool.pytest.ini_options]\naddopts = \"-q\"\n", "python3 -m pytest -q"),
        ]
        for path, text, command in cases:
            with self.subTest(path):
                for name in os.listdir(self.repo):
                    if name != ".git":
                        os.remove(os.path.join(self.repo, name))
                self.write(path, text)
                self.assertIn(command, self.candidates())

    def test_a_package_manager_s_lockfile_picks_its_runner(self):
        self.write("package.json", json.dumps({"scripts": {"test": "vitest run"}}))
        self.write("pnpm-lock.yaml", "lockfileVersion: 9\n")
        self.assertEqual(self.candidates()[0], "pnpm test")

    def test_npm_s_placeholder_test_script_is_not_a_test_command(self):
        self.write("package.json", json.dumps({"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}))
        self.assertEqual(self.candidates(), [])

    def test_plain_unittest_files_under_tests_are_found(self):
        self.write("tests/test_a.py", "import unittest\n")
        self.assertIn("python3 -m unittest discover -s tests", self.candidates())

    def test_pytest_style_tests_are_not_offered_to_unittest(self):
        # unittest would find no tests in them: the checks would run nothing, or always fail.
        self.write("tests/test_a.py", "def test_one():\n    assert True\n")
        self.assertEqual(self.candidates(), ["python3 -m pytest -q"])

    def test_a_package_json_of_an_odd_shape_offers_nothing_rather_than_crashing(self):
        for text in ("[1, 2]", json.dumps({"scripts": "jest"}), "{not json"):
            with self.subTest(text=text):
                self.write("package.json", text)
                done, found = self.run_init("detect")
                self.assertEqual((done.returncode, found["candidates"]), (0, []))

    def test_ignore_lines_go_on_a_line_of_their_own_and_a_covering_folder_counts(self):
        self.write(".gitignore", "node_modules/")  # no newline at the end
        self.run_init("write", "--check", "npm test")
        with open(os.path.join(self.repo, ".gitignore"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().split("\n")[:2], ["node_modules/", ".monerex/state/"])
        os.remove(os.path.join(self.repo, ".monerex", "config.json"))
        self.write(".gitignore", "/.monerex/\n.claude/\n")
        _, found = self.run_init("detect")
        self.assertEqual(found["gitignore_missing"], [])

    def test_a_linked_config_or_gitignore_is_refused(self):
        # A clone can commit links: writing through them lands outside the file it names.
        outside = os.path.join(self.repo, "..", os.path.basename(self.repo) + "-outside")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        os.makedirs(outside)
        os.makedirs(os.path.join(self.repo, ".monerex"))
        os.symlink(os.path.join(outside, "config.json"), os.path.join(self.repo, ".monerex", "config.json"))
        done, _ = self.run_init("write", "--check", "npm test")
        self.assertEqual(done.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(outside, "config.json")))
        os.remove(os.path.join(self.repo, ".monerex", "config.json"))
        os.symlink(os.path.join(outside, "ignore"), os.path.join(self.repo, ".gitignore"))
        done, _ = self.run_init("write", "--check", "npm test")
        self.assertEqual(done.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".monerex", "config.json")), "nothing is half done")

    def test_writing_creates_the_config_and_the_ignore_lines_once(self):
        self.write(".gitignore", "node_modules/\n.monerex/log/\n")
        done, result = self.run_init("write", "--check", "npm test")
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(self.repo, ".monerex", "config.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"checks": ["npm test"], "external_review": "off"})
        with open(os.path.join(self.repo, ".gitignore"), encoding="utf-8") as handle:
            lines = handle.read().split("\n")
        self.assertEqual([line for line in lines if line in IGNORED], [".monerex/log/"] + [i for i in IGNORED if i != ".monerex/log/"])
        self.assertIn("node_modules/", lines)
        self.assertEqual(result["wrote"], [".monerex/config.json", ".gitignore"])

    def test_a_repository_that_already_opted_in_is_left_as_it_is(self):
        self.write(".monerex/config.json", '{ "checks": ["make check"] }\n')
        _, found = self.run_init("detect")
        self.assertTrue(found["opted_in"])
        done, _ = self.run_init("write", "--check", "npm test")
        self.assertEqual(done.returncode, 2)
        with open(os.path.join(self.repo, ".monerex", "config.json"), encoding="utf-8") as handle:
            self.assertIn("make check", handle.read())

    def test_without_a_check_command_nothing_is_written(self):
        # An empty list would quietly put every task on the no-checks route.
        done, _ = self.run_init("write")
        self.assertEqual(done.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".monerex", "config.json")))

    def test_it_never_writes_claude_s_settings(self):
        self.assertEqual(self.run_init("write", "--check", "npm test")[0].returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "settings.json")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "settings.local.json")))


if __name__ == "__main__":
    unittest.main()
