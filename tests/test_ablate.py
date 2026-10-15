"""The ablation gate: the tests that prove a committed change must fail without it."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ABLATE = os.path.join(ROOT, "scripts", "ablate.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ablate  # noqa: E402
import task  # noqa: E402

PY = '"%s"' % sys.executable
UNITTEST = PY + " -m unittest -q test_calc"

BUGGY = 'def add(a, b):\n    return a - b\n'
FIXED = 'def add(a, b):\n    return a + b\n'
TEST_ADD = 'import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(calc.add(2, 2), 4)\n'


class AblateTest(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="monerex-ablate-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.env = {key: value for key, value in os.environ.items() if key not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        for args in (("init", "-q"), ("config", "user.name", "T"), ("config", "user.email", "t@example.invalid")):
            self.git(*args)
        self.write(".gitignore", "__pycache__/\n.monerex/state/\n.monerex/log/\n")
        self.write("calc.py", BUGGY)
        self.write("README.md", "calc\n")
        self.commit("start")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True).stdout

    def read(self, name):
        with open(os.path.join(self.repo, name), encoding="utf-8") as handle:
            return handle.read()

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def ablate(self, *args):
        done = subprocess.run([sys.executable, "-I", ABLATE, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        try:
            result = json.loads(done.stdout)
        except ValueError:
            result = None
        return done, result

    def head(self):
        return self.git("rev-parse", "HEAD").strip()

    def assert_clean_at(self, head):
        self.assertEqual(self.head(), head)
        self.assertEqual(self.git("status", "--porcelain"), "", "the tree is exactly the commit again")

    def test_a_fix_whose_test_fails_by_assertion_without_it_passes(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        head = self.head()
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (0, "pass"), done.stdout + done.stderr)
        self.assertEqual(result["ablated"], ["calc.py"])
        self.assert_clean_at(head)

    def test_a_new_feature_whose_test_fails_for_a_missing_name_is_weak(self):
        self.write("calc.py", BUGGY + '\n\ndef mul(a, b):\n    return a * b\n')
        self.write("test_calc.py", 'import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n    def test_mul(self):\n        self.assertEqual(calc.mul(2, 3), 6)\n')
        self.commit("mul")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (0, "weak"), done.stdout)

    def test_a_test_that_passes_without_the_change_fails_the_gate(self):
        self.write("calc.py", BUGGY + '\n\nVERSION = 2\n')
        self.write("test_calc.py", 'import unittest\n\nimport calc\n\n\nclass T(unittest.TestCase):\n    def test_it_exists(self):\n        self.assertTrue(callable(calc.add))\n')
        self.commit("version")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (1, "fail"))
        self.assertIn("passes without the change", result["reason"])

    def test_a_command_that_does_not_pass_with_the_change_fails_the_gate(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        done, result = self.ablate("--test", PY + " -m unittest -q test_missing_module_name")
        self.assertEqual(result["result"], "fail")

    def test_a_flaky_test_is_reported_and_not_judged(self):
        self.write(".gitignore", "__pycache__/\n.monerex/state/\n.monerex/log/\nflip.txt\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD + '\n    def test_flaky(self):\n        import os\n        path = "flip.txt"\n'
                   '        flipped = os.path.exists(path)\n        open(path, "w").close() if not flipped else os.remove(path)\n'
                   '        self.assertFalse(flipped)\n')
        self.commit("flaky")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (1, "flaky"))

    def test_uncommitted_work_is_refused_and_left_alone(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        status = self.git("status", "--porcelain")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (2, "not-run"))
        self.assertIn("commit the change first", result["reason"])
        self.assertEqual(self.git("status", "--porcelain"), status)
        with open(os.path.join(self.repo, "calc.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), FIXED)

    def test_added_modified_and_deleted_files_are_taken_out_and_put_back(self):
        self.write("old.py", "OLD = 1\n")
        self.commit("old helper")
        self.write("calc.py", FIXED)
        self.write("helper.py", "X = 1\n")
        os.remove(os.path.join(self.repo, "old.py"))
        self.write("test_calc.py", TEST_ADD)
        self.commit("change")
        head = self.head()
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "pass", done.stdout + done.stderr)
        self.assertEqual(sorted(result["ablated"]), ["calc.py", "helper.py", "old.py"])
        self.assert_clean_at(head)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "old.py")))

    def tool(self, name, source):
        """A helper script in an ignored folder, so it is neither part of the change nor uncommitted work."""
        if "tools/" not in self.read(".gitignore"):
            self.write(".gitignore", self.read(".gitignore") + "tools/\n")
            self.commit("ignore tools")
        self.write("tools/" + name, source)
        return PY + " tools/" + name

    def test_a_test_command_that_changes_tracked_files_is_refused_and_its_writes_kept(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        done, result = self.ablate("--test", "echo noise >> README.md && " + UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (2, "not-run"))
        self.assertIn("changes tracked files", result["reason"])
        self.assertIn("noise", self.read("README.md"), "nothing the gate did not take out is ever reset")
        self.assertEqual(self.read("calc.py"), FIXED)

    def test_edits_made_after_a_killed_run_are_never_overwritten(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        subprocess.run([sys.executable, "-I", ABLATE, "--test", UNITTEST, "--stop-after-taking-out"], cwd=self.repo, env=self.env,
                       capture_output=True, text=True)
        mine = "def add(a, b):\n    return b + a  # my edit\n"
        self.write("README.md", "my edit\n")
        self.write("calc.py", mine)
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (2, "not-run"), done.stdout + done.stderr)
        self.assertEqual((self.read("README.md"), self.read("calc.py")), ("my edit\n", mine))

    def test_the_index_is_never_touched(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        head = self.head()
        subprocess.run([sys.executable, "-I", ABLATE, "--test", UNITTEST, "--stop-after-taking-out"], cwd=self.repo, env=self.env,
                       capture_output=True, text=True)
        self.assertEqual(self.git("diff", "--cached"), "", "the change is taken out of the working tree only")
        self.assertEqual(self.ablate("--test", UNITTEST)[1]["result"], "pass")
        self.assert_clean_at(head)

    def test_head_moving_during_the_run_stops_with_exit_3(self):
        commit_once = self.tool("commit_once.py", (
            "import os, subprocess\n"
            "if not os.path.exists('tools/moved'):\n"
            "    open('tools/moved', 'w').close()\n"
            "else:\n"
            "    subprocess.run(['git', 'commit', '-q', '--allow-empty', '-m', 'meanwhile'])\n"))
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        os.remove(os.path.join(self.repo, "tools", "moved")) if os.path.exists(os.path.join(self.repo, "tools", "moved")) else None
        done, result = self.ablate("--runs", "1", "--test", commit_once + " ; " + UNITTEST)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("HEAD moved", result["reason"])

    def test_an_ignored_local_copy_of_a_file_the_change_untracked_is_refused(self):
        self.write("config.local", "SECRET=mine\n")
        self.commit("tracked config")
        self.git("rm", "-q", "--cached", "config.local")
        self.write(".gitignore", self.read(".gitignore") + "config.local\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("untrack config")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "not-run", done.stdout)
        self.assertIn("config.local", result["reason"])
        self.assertEqual(self.read("config.local"), "SECRET=mine\n")

    def test_a_failure_while_putting_back_exits_3(self):
        # Runs twice with the change, then once without it: on that third run, make pkg/ read-only,
        # so the module the change added cannot be written back.
        lock = self.tool("lock.py", "import os\nopen('tools/count', 'a').write('x')\nif len(open('tools/count').read()) == 3:\n    os.chmod('pkg', 0o555)\n")
        self.write("pkg/__init__.py", "")
        self.commit("package")
        self.write("pkg/calc2.py", "X = 1\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix and a new module")
        self.addCleanup(os.chmod, os.path.join(self.repo, "pkg"), 0o755)
        done, result = self.ablate("--runs", "1", "--test", lock + " ; " + UNITTEST)
        os.chmod(os.path.join(self.repo, "pkg"), 0o755)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)

    def test_a_timed_out_command_leaves_no_process_behind(self):
        late = self.tool("late.py", (
            "import subprocess, sys, time\nsys.path.insert(0, '.')\nimport calc\n"
            "if calc.add(2, 2) != 4:\n"
            "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3); open(\"README.md\", \"a\").write(\"late\")'])\n"
            "    time.sleep(30)\n"))
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        head = self.head()
        done, result = self.ablate("--timeout", "1", "--test", late)
        self.assertEqual(result["result"], "not-run", done.stdout + done.stderr)
        import time

        time.sleep(4)
        self.assert_clean_at(head)

    def test_python_does_not_reuse_bytecode_compiled_from_the_old_code(self):
        env = dict(self.env)
        env.pop("PYTHONDONTWRITEBYTECODE")
        self.write("calc.py", FIXED)  # the same length as BUGGY: only the mtime tells them apart
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        done = subprocess.run([sys.executable, "-I", ABLATE, "--runs", "1", "--test", UNITTEST], cwd=self.repo, env=env,
                              capture_output=True, text=True)
        self.assertEqual(json.loads(done.stdout)["result"], "pass", done.stderr)
        after = subprocess.run(UNITTEST, shell=True, cwd=self.repo, env=env, capture_output=True, text=True)
        self.assertEqual(after.returncode, 0, after.stderr)

    def test_paths_are_literal_not_patterns(self):
        self.write("app/[id].py", "PAGE = 1\n")
        self.write("app/x.py", "OTHER = 1\n")
        self.commit("pages")
        self.write("app/[id].py", "PAGE = 2\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        head = self.head()
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((result["result"], result["ablated"]), ("pass", ["app/[id].py", "calc.py"]), done.stdout + done.stderr)
        self.assert_clean_at(head)

    def test_a_second_run_while_one_is_in_progress_is_refused(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        os.makedirs(os.path.join(self.repo, ".monerex", "state"))
        lock = os.path.join(self.repo, ".monerex", "state", "ablate.lock")
        with open(lock, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))  # this test process is alive
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "not-run")
        self.assertIn("in progress", result["reason"])
        with open(lock, "w", encoding="utf-8") as handle:
            handle.write("999999999")  # a run that died: its lock is stale
        self.assertEqual(self.ablate("--test", UNITTEST)[1]["result"], "pass")
        self.assertFalse(os.path.exists(lock))

    def test_an_ignored_file_where_a_folder_must_go_is_refused(self):
        self.write("data/sample.py", "S = 1\n")
        self.commit("sample")
        self.git("rm", "-q", "-r", "data")
        self.write(".gitignore", self.read(".gitignore") + "data\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("drop sample")
        self.write("data", "MY LOCAL DATA\n")  # an ignored file where the base had a folder
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "not-run", done.stdout)
        self.assertIn("data", result["reason"])
        self.assertEqual(self.read("data"), "MY LOCAL DATA\n")

    def test_an_edit_made_while_the_change_is_out_is_kept_and_reported(self):
        meddle = self.tool("meddle.py", (
            "open('tools/count', 'a').write('x')\n"
            "if len(open('tools/count').read()) == 3:\n"
            "    open('calc.py', 'w').write('def add(a, b):\\n    return 42  # theirs\\n')\n"))
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        done, result = self.ablate("--runs", "1", "--test", meddle + " ; " + UNITTEST)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn("calc.py", result["reason"])
        self.assertIn("return 42  # theirs", self.read("calc.py"), "never overwritten")

    def test_heal_counts_a_file_already_back_at_head_as_put_back(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        subprocess.run([sys.executable, "-I", ABLATE, "--test", UNITTEST, "--stop-after-taking-out"], cwd=self.repo, env=self.env,
                       capture_output=True, text=True)
        self.git("restore", "calc.py")  # the user put it back by hand
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "pass", done.stdout + done.stderr)

    def test_folders_the_take_out_made_are_removed(self):
        self.write("oldpkg/impl.py", "X = 1\n")
        self.commit("old package")
        self.git("rm", "-q", "-r", "oldpkg")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("drop old package, fix")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "pass", done.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.repo, "oldpkg")))

    def test_outputs_the_tests_build_are_rebuilt_from_the_change(self):
        build = self.tool("build.py", (
            "import os, sys\nsys.path.insert(0, '.')\nimport calc\n"
            "os.makedirs('dist', exist_ok=True)\nopen('dist/out.txt', 'w').write(str(calc.add(2, 2)))\n"))
        self.write(".gitignore", self.read(".gitignore") + "dist/\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        done, result = self.ablate("--test", build + " && " + UNITTEST)
        self.assertEqual(result["result"], "pass", done.stdout)
        self.assertEqual(self.read("dist/out.txt"), "4", "the last run is with the change")

    def test_a_run_killed_with_the_change_out_heals_on_the_next_run(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        head = self.head()
        killed = subprocess.run([sys.executable, "-I", ABLATE, "--test", UNITTEST, "--stop-after-taking-out"], cwd=self.repo,
                                env=self.env, capture_output=True, text=True)
        with open(os.path.join(self.repo, "calc.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), BUGGY, killed.stderr)
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "pass", done.stdout + done.stderr)
        self.assertIn("put back", done.stderr)
        self.assert_clean_at(head)

    def test_edits_hidden_from_status_are_refused_and_kept(self):
        self.write("config.py", "MODE = 1\n")
        self.commit("config")
        self.write("config.py", "MODE = 2\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix and config")
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag):
                self.git("update-index", flag, "config.py")
                self.write("config.py", "MODE = 'mine'\n")  # hidden from git status by the flag
                done, result = self.ablate("--test", UNITTEST)
                self.assertEqual(result["result"], "not-run", done.stdout)
                self.assertIn("config.py", result["reason"])
                self.assertEqual(self.read("config.py"), "MODE = 'mine'\n")
                self.git("update-index", "--no" + flag[1:], "config.py")
                self.git("checkout", "config.py")

    def test_a_command_that_cannot_start_without_the_change_is_broken_not_a_pass(self):
        self.write("bin/check", "#!/bin/sh\n" + UNITTEST + "\n")
        os.chmod(os.path.join(self.repo, "bin", "check"), 0o755)
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix with a check script")
        done, result = self.ablate("--test", "bin/check")
        self.assertEqual(result["result"], "fail", done.stdout)
        self.assertIn("does not run", result["reason"])

    def test_test_runner_manifests_stay_in_place(self):
        self.write("Makefile", "test:\n\t@echo old\n")
        self.commit("makefile")
        self.write("Makefile", "test:\n\t" + UNITTEST.replace('"', '') + "\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix and a test target")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((result["result"], result["kept"]), ("pass", ["Makefile"]), done.stdout)

    def test_a_changed_symlink_is_taken_out_and_put_back(self):
        self.write("impl_a.py", BUGGY)
        self.write("impl_b.py", FIXED)
        os.remove(os.path.join(self.repo, "calc.py"))
        os.symlink("impl_a.py", os.path.join(self.repo, "calc.py"))
        self.commit("calc is a link")
        os.remove(os.path.join(self.repo, "calc.py"))
        os.symlink("impl_b.py", os.path.join(self.repo, "calc.py"))
        self.write("test_calc.py", TEST_ADD)
        self.commit("point calc at the fix")
        head = self.head()
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (0, "pass"), done.stdout + done.stderr)
        self.assertEqual(os.readlink(os.path.join(self.repo, "calc.py")), "impl_b.py")
        self.assert_clean_at(head)

    def test_a_kept_helper_stays_in_place(self):
        self.write("support/fixture.py", "EXPECTED = 4\n")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", 'import unittest\n\nimport calc\nfrom support import fixture\n\n\nclass T(unittest.TestCase):\n'
                   '    def test_add(self):\n        self.assertEqual(calc.add(2, 2), fixture.EXPECTED)\n')
        self.commit("fix with a fixture")
        self.assertEqual(self.ablate("--test", UNITTEST)[1]["result"], "weak", "without --keep the fixture is taken out")
        done, result = self.ablate("--keep", "support/", "--test", UNITTEST)
        self.assertEqual((result["result"], result["kept"]), ("pass", ["support/fixture.py"]), done.stdout)

    def test_the_base_can_be_several_commits_back(self):
        self.write("calc.py", FIXED)
        self.commit("fix")
        self.write("test_calc.py", TEST_ADD)
        self.commit("its test")
        self.assertEqual(self.ablate("--test", UNITTEST)[1]["result"], "skipped", "the last commit alone holds only a test")
        done, result = self.ablate("--base", "HEAD~2", "--test", UNITTEST)
        self.assertEqual(result["result"], "pass", done.stdout)

    def test_a_lockfile_is_left_in_place(self):
        self.write("calc.py", FIXED)
        self.write("uv.lock", "version = 2\n")
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix and lock")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((result["result"], result["ablated"], result["kept"]), ("pass", ["calc.py"], ["uv.lock"]))

    def test_a_refactor_must_pass_with_and_without_the_change(self):
        self.write("test_calc.py", TEST_ADD)
        self.write("calc.py", FIXED)
        self.commit("fixed, with its test")
        self.write("calc.py", 'def add(a, b):\n    total = a + b\n    return total\n')
        self.commit("refactor")
        done, result = self.ablate("--refactor", "--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (0, "pass"), done.stdout)
        self.write("test_calc.py", TEST_ADD.replace("4)", "4, 'still four')"))
        self.commit("refactor touching a test")
        done, result = self.ablate("--refactor", "--base", "HEAD~2", "--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (1, "fail"))
        self.assertIn("a refactor changes no test", result["reason"])

    def test_a_refactor_where_no_test_ran_fails(self):
        self.write("calc.py", 'def add(a, b):\n    total = a - b\n    return total\n')
        self.commit("refactor")
        done, result = self.ablate("--refactor", "--test", PY + " -m unittest discover -p 'zzz*.py'")
        self.assertEqual(result["result"], "fail", done.stdout)

    def test_a_test_command_that_hangs_is_not_run_and_the_tree_comes_back(self):
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        head = self.head()
        done, result = self.ablate("--timeout", "2", "--test", PY + ' -c "import calc, time; time.sleep(30) if calc.add(2, 2) != 4 else None"')
        self.assertEqual((done.returncode, result["result"]), (2, "not-run"))
        self.assertIn("timed out", result["reason"])
        self.assert_clean_at(head)

    def test_a_changed_submodule_is_not_run(self):
        self.write("calc.py", FIXED)
        os.makedirs(os.path.join(self.repo, "vendor", "lib"))  # an uninitialised submodule: an empty folder
        self.git("update-index", "--add", "--cacheinfo", "160000,%s,vendor/lib" % self.head())
        self.write("test_calc.py", TEST_ADD)
        self.git("add", "calc.py", "test_calc.py")
        self.git("commit", "-q", "-m", "fix and a submodule")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual(result["result"], "not-run")
        self.assertIn("submodule", result["reason"])

    def test_a_change_to_tests_only_has_nothing_to_ablate(self):
        self.write("test_calc.py", TEST_ADD.replace("2, 2), 4", "2, 2), 0"))
        self.commit("a test")
        done, result = self.ablate("--test", UNITTEST)
        self.assertEqual((done.returncode, result["result"]), (0, "skipped"))

    def test_the_result_is_logged_on_the_open_task(self):
        task.append(self.repo, "start", slug="fix-add", tier="T1")
        self.write("calc.py", FIXED)
        self.write("test_calc.py", TEST_ADD)
        self.commit("fix")
        self.ablate("--test", UNITTEST)
        [logged] = [record for record in task.read(self.repo) if record["event"] == "ablation"]
        self.assertEqual((logged["task"], logged["result"]), ("fix-add", "pass"))

    def test_without_a_test_command_it_refuses(self):
        done, _ = self.ablate()
        self.assertEqual(done.returncode, 2)


class EmptyRepositoryTest(unittest.TestCase):
    def test_a_repository_without_commits_is_not_run_and_left_alone(self):
        repo = os.path.realpath(tempfile.mkdtemp(prefix="monerex-ablate-empty-"))
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        done = subprocess.run([sys.executable, "-I", ABLATE, "--test", "true"], cwd=repo, capture_output=True, text=True)
        self.assertEqual((done.returncode, json.loads(done.stdout)["result"]), (2, "not-run"))
        self.assertEqual(os.listdir(repo), [".git"])


class ClassifyTest(unittest.TestCase):
    def test_test_files_are_recognised(self):
        for path in ("tests/test_x.py", "test_x.py", "x_test.go", "a/b.test.ts", "c.spec.js", "lib/foo_spec.rb", "myapp/tests.py",
                     "conftest.py", "src/FooTest.java", "src/FooTests.cs", "__tests__/a.js"):
            self.assertTrue(ablate.is_test(path), path)
        for path in ("contest.py", "latest.py", "testing_utils.py", "src/ABTest.ts", "spec/openapi.yaml", "calc.py"):
            self.assertFalse(ablate.is_test(path), path)

    def test_failures_are_told_apart(self):
        cases = [
            (1, "AssertionError: 3 != 4", "assertion"),
            (1, "AssertionError: SyntaxError not raised", "assertion"),
            (1, "ModuleNotFoundError: No module named 'calc'", "missing-name"),
            (1, "Error: Cannot find module './calc'", "missing-name"),
            (1, "error[E0425]: cannot find function `mul` in this scope", "missing-name"),
            (1, "error: cannot find symbol", "missing-name"),
            (1, '  File "x.py", line 3\nSyntaxError: invalid syntax', "broken"),
            (5, "collected 0 items", "broken"),
            (0, "Ran 0 tests in 0.000s\n\nOK", "broken"),
            (0, "Ran 3 tests in 0.1s\n\nOK", "passed"),
            (127, "sh: bin/check: No such file or directory", "broken"),
            (126, "sh: bin/check: Permission denied", "broken"),
            (1, "sh: rspec: command not found", "broken"),
            (1, 'npm error Missing script: "test"', "broken"),
            (1, "Error: no test specified", "broken"),
            (1, "FileNotFoundError: [Errno 2] No such file or directory: 'data.json'", "missing-name"),
        ]
        for code, output, want in cases:
            self.assertEqual(ablate.classify(code, output), want, output)


if __name__ == "__main__":
    unittest.main()
