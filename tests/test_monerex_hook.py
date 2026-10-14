"""The tool-level guards, fed the JSON a hook receives, in throwaway repositories."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "monerex_hook.py")
CHECK = os.path.join(ROOT, "scripts", "check.py")
TERM = "zorblatt-industries"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-hook-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        denylist = os.path.join(self.tmp, "denylist.txt")
        with open(denylist, "w", encoding="utf-8") as handle:
            handle.write(TERM + "\n")
        self.env = dict(os.environ, MONEREX_DENYLIST=denylist, HOME=self.tmp)
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.env.pop(name, None)
        self.git("init", "-q", "-b", "master")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.put("a.txt", "hello\n")
        self.git("add", "a.txt")
        self.git("commit", "-q", "-m", "first")
        self.configure({})  # on the default branch, so every branch has it
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def put(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def configure(self, config):
        """Write the repo's monerex config and commit it, as a real repo would."""
        self.put(".monerex/config.json", json.dumps(config))
        self.put(".gitignore", ".monerex/state/\n.monerex/log/\n")
        self.git("add", ".monerex/config.json", ".gitignore")
        self.git("commit", "-q", "--allow-empty", "-m", "configure monerex")

    def run_checks(self):
        return subprocess.run([sys.executable, "-I", CHECK], cwd=self.repo, env=self.env, capture_output=True, text=True)

    def run_hook(self, event, tool_input=None, subagent=False, **extra):
        data = dict({"cwd": self.repo, "session_id": "s1", "tool_input": tool_input or {}}, **extra)
        if subagent:
            data.update(agent_id="a1", agent_type="monerex:implementer")
        return subprocess.run(
            [sys.executable, "-I", HOOK, event], input=json.dumps(data), cwd=self.repo, env=self.env, capture_output=True, text=True
        )

    def edit(self, path, subagent=False, **fields):
        return self.run_hook("pre-edit", dict({"file_path": path}, **fields), subagent=subagent)

    def bash(self, command, subagent=False):
        return self.run_hook("pre-bash", {"command": command}, subagent=subagent)

    def web(self, subagent=False, **fields):
        return self.run_hook("pre-web", fields, subagent=subagent)

    def assert_allowed(self, done):
        self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)

    def assert_denied(self, done, fragment=""):
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn(fragment, done.stderr)

    def assert_asked(self, done, fragment=""):
        self.assertEqual(done.returncode, 0, done.stderr)
        decision = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "ask")
        self.assertIn(fragment, decision["permissionDecisionReason"])

    # ------------------------------------------------------------ opt-in

    def test_nothing_is_guarded_without_a_config(self):
        self.git("rm", "-q", "--cached", ".monerex/config.json")
        os.remove(os.path.join(self.repo, ".monerex", "config.json"))
        self.assert_allowed(self.edit(".claude/settings.json", subagent=True))
        self.assert_allowed(self.bash("git push --force origin master"))

    def test_a_broken_config_fails_closed(self):
        self.put(".monerex/config.json", "{not json")
        self.assert_denied(self.edit("a.txt"), "the guard itself failed")

    # ------------------------------------------------------------ edits

    def test_an_ordinary_edit_is_allowed(self):
        self.assert_allowed(self.edit("src/app.py", subagent=True, content="print('hi')\n"))

    def test_agent_config_is_denied_for_a_subagent_and_asked_for_the_main_session(self):
        for path in (".claude/settings.json", ".mcp.json", "CLAUDE.md", "docs/AGENTS.md", ".github/workflows/ci.yml", ".monerex/config.json"):
            with self.subTest(path):
                self.assert_denied(self.edit(path, subagent=True), "agent configuration")
                self.assert_asked(self.edit(path), "agent configuration")

    def test_a_symlink_to_agent_config_is_resolved(self):
        self.put(".claude/settings.json", "{}")
        os.symlink(os.path.join(self.repo, ".claude", "settings.json"), os.path.join(self.repo, "innocent.json"))
        self.assert_denied(self.edit("innocent.json", subagent=True), ".claude/settings.json is agent configuration")

    def test_a_path_outside_the_repo_is_denied_for_a_subagent_only(self):
        outside = os.path.join(self.tmp, "elsewhere.txt")
        self.assert_denied(self.edit(outside, subagent=True), "outside the repository")
        self.assert_denied(self.edit("../elsewhere.txt", subagent=True), "outside the repository")
        self.assert_allowed(self.edit(outside))

    def test_secrets_files_are_restricted_but_examples_are_not(self):
        self.assert_denied(self.edit(".env", subagent=True), "a secrets file")
        self.assert_asked(self.edit("config/.env.production"), "a secrets file")
        self.assert_allowed(self.edit(".env.example", subagent=True))

    def test_a_lockfile_is_restricted_unless_the_plan_lists_it(self):
        self.assert_denied(self.edit("uv.lock", subagent=True), "a lockfile")
        self.put(".monerex/state/allowed-paths", "uv.lock\n")
        self.assert_allowed(self.edit("uv.lock", subagent=True))

    def test_a_task_protected_path_is_denied_for_everyone(self):
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        self.assert_denied(self.edit("tests/test_bug.py"), "read-only for this task")

    def worktree(self, relative):
        """A real linked worktree of the test repository, on a branch of its own."""
        path = os.path.join(self.repo, relative) if not os.path.isabs(relative) else relative
        self.git("worktree", "add", "-q", "-b", os.path.basename(path), path)
        return path

    def test_a_task_protected_path_is_read_only_in_a_worktree_of_the_task(self):
        # The owner's checkout holds the entry; the file is the worktree's copy. Seen in review:
        # the entry was compared with the path as the main checkout spells it, and let it through.
        inner = self.worktree(".claude/worktrees/fix-1")
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        for subagent in (False, True):
            with self.subTest("from the main checkout", subagent=subagent):
                self.assert_denied(self.edit(".claude/worktrees/fix-1/tests/test_bug.py", subagent=subagent), "read-only for this task")
            with self.subTest("from inside the worktree", subagent=subagent):
                done = self.run_hook("pre-edit", {"file_path": "tests/test_bug.py"}, subagent=subagent, cwd=inner)
                self.assert_denied(done, "read-only for this task")
        self.assert_allowed(self.edit(".claude/worktrees/fix-1/tests/other.py", subagent=True))

    def test_an_entry_kept_in_the_worktree_guards_the_file_from_the_main_checkout_too(self):
        inner = self.worktree(".claude/worktrees/fix-1")
        os.makedirs(os.path.join(inner, ".monerex", "state"))
        with open(os.path.join(inner, ".monerex", "state", "protected-paths"), "w", encoding="utf-8") as handle:
            handle.write("tests/test_bug.py\n")
        self.assert_denied(self.edit(".claude/worktrees/fix-1/tests/test_bug.py"), "read-only for this task")
        self.assert_denied(self.run_hook("pre-edit", {"file_path": "tests/test_bug.py"}, cwd=inner), "read-only for this task")

    def test_a_task_protected_path_is_read_only_in_a_worktree_beside_the_repository(self):
        beside = self.worktree(os.path.join(self.tmp, "beside"))
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        self.assert_denied(self.edit(os.path.join(beside, "tests", "test_bug.py")), "read-only for this task")
        self.assert_allowed(self.edit(os.path.join(beside, "tests", "other.py")))

    def other_repo(self, path, **init):
        """A repository that has nothing to do with the test one."""
        subprocess.run(["git", "init", "-q", "-b", "master", *init.get("flags", ()), path], env=self.env, capture_output=True, check=True)
        return path

    def test_a_protected_name_in_another_repository_or_a_plain_folder_is_not_refused(self):
        # A fault the first version of the rule above brought in: this repository's entries were
        # applied to any file whose own folder happened to give it the same name.
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n*notes*\n")
        other = self.other_repo(os.path.join(self.tmp, "other"))
        nested = self.other_repo(os.path.join(self.repo, "vendor", "lib"))
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        self.assert_allowed(self.edit(os.path.join(other, "tests", "test_bug.py")))
        self.assert_allowed(self.edit(os.path.join(plain, "tests", "test_bug.py")))
        self.assert_allowed(self.edit(os.path.join(plain, "notes_test.py")))
        for subagent in (False, True):
            self.assert_allowed(self.edit(os.path.join(nested, "tests", "test_bug.py"), subagent=subagent))
        self.assert_denied(self.edit(os.path.join(other, "tests", "test_bug.py"), subagent=True), "outside the repository")

    def case_is_ignored_here(self):
        return os.path.exists(self.repo.upper()) and os.path.samefile(self.repo, self.repo.upper())

    def test_a_folder_spelled_in_another_case_is_the_same_folder(self):
        if not self.case_is_ignored_here():
            self.skipTest("this volume tells REPO from repo")
        inner = self.worktree("work/fix")
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        shouted = os.path.join(os.path.dirname(self.repo), os.path.basename(self.repo).upper())
        for subagent in (False, True):
            with self.subTest(subagent=subagent):
                self.assert_denied(self.edit("work/FIX/tests/test_bug.py", subagent=subagent), "read-only for this task")
                self.assert_denied(self.edit("WORK/fix/tests/test_bug.py", subagent=subagent), "read-only for this task")
                self.assert_denied(self.edit(os.path.join(shouted, "tests", "test_bug.py"), subagent=subagent), "read-only for this task")
                self.assert_denied(self.edit(os.path.join(inner.upper(), "tests", "test_bug.py"), subagent=subagent), "read-only for this task")
        # A session that typed its own folder in another case is still guarded.
        self.assert_asked(self.run_hook("pre-edit", {"file_path": "CLAUDE.md"}, cwd=shouted), "agent configuration")
        self.assert_asked(self.edit(os.path.join(shouted, "CLAUDE.md")), "agent configuration")
        self.assert_denied(self.edit(os.path.join(shouted, "src", "app.py"), subagent=True, content=TERM), "would write")

    def test_a_task_list_in_another_checkout_is_still_configuration(self):
        inner = self.worktree("work/fix")
        beside = self.worktree(os.path.join(self.tmp, "beside"))
        state = os.path.join(".monerex", "state", "protected-paths")
        # From a worktree, the owner's list by its full path: asked, not waved through.
        for cwd in (inner, beside):
            self.assert_asked(self.run_hook("pre-edit", {"file_path": os.path.join(self.repo, state)}, cwd=cwd), "agent configuration")
        # From the owner's checkout, the list of a worktree kept somewhere inside it.
        self.assert_denied(self.edit(os.path.join("work", "fix", state), subagent=True), "agent configuration")
        self.assert_asked(self.edit(os.path.join("work", "fix", state)), "agent configuration")
        self.assert_asked(self.edit(os.path.join(beside, state)), "agent configuration")
        self.assert_allowed(self.edit(os.path.join(beside, "src", "app.py")))

    def test_a_git_directory_kept_apart_leaves_each_checkout_its_own_list(self):
        # Git does not record where the checkout of such a repository is, so a worktree cannot
        # find the owner's list. Its own list holds, and so does the owner's in the owner's checkout.
        owner = self.other_repo(os.path.join(self.tmp, "apart"), flags=("--separate-git-dir", os.path.join(self.tmp, "apart-git")))

        def git(*args):
            subprocess.run(["git", "-C", owner, *args], env=self.env, capture_output=True, check=True)

        git("config", "user.name", "Test")
        git("config", "user.email", "test@example.invalid")
        os.makedirs(os.path.join(owner, ".monerex", "state"))
        for name, text in ((".monerex/config.json", "{}"), (".gitignore", ".monerex/state/\n")):
            with open(os.path.join(owner, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        git("add", ".monerex/config.json", ".gitignore")
        git("commit", "-q", "-m", "first")
        inner = os.path.join(owner, ".claude", "worktrees", "fix-1")
        git("worktree", "add", "-q", "-b", "fix-1", inner)
        with open(os.path.join(owner, ".monerex", "state", "protected-paths"), "w", encoding="utf-8") as handle:
            handle.write("tests/test_bug.py\n")
        self.assert_denied(self.run_hook("pre-edit", {"file_path": "tests/test_bug.py"}, cwd=owner), "read-only for this task")
        self.assert_allowed(self.run_hook("pre-edit", {"file_path": "tests/test_bug.py"}, cwd=inner))
        os.makedirs(os.path.join(inner, ".monerex", "state"))
        with open(os.path.join(inner, ".monerex", "state", "protected-paths"), "w", encoding="utf-8") as handle:
            handle.write("tests/test_bug.py\n")
        self.assert_denied(self.run_hook("pre-edit", {"file_path": "tests/test_bug.py"}, cwd=inner), "read-only for this task")
        self.assert_denied(self.run_hook("pre-edit", {"file_path": os.path.join(inner, "tests", "test_bug.py")}, cwd=owner), "read-only for this task")

    def test_an_entry_that_names_a_link_guards_the_link_and_an_entry_for_the_file_guards_it_through_one(self):
        self.put("tests/real_test.py", "x\n")
        os.symlink("real_test.py", os.path.join(self.repo, "tests", "test_bug.py"))
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        self.assert_denied(self.edit("tests/test_bug.py"), "read-only for this task")
        self.put(".monerex/state/protected-paths", "tests/real_test.py\n")
        self.assert_denied(self.edit("tests/test_bug.py", subagent=True), "read-only for this task")

    def test_an_entry_without_glob_characters_guards_the_file_it_leads_to(self):
        self.put("tests/real_test.py", "x\n")
        os.symlink("real_test.py", os.path.join(self.repo, "tests", "test_bug.py"))
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        for subagent in (False, True):
            with self.subTest("the entry names the link, the file is edited by its own name", subagent=subagent):
                self.assert_denied(self.edit("tests/real_test.py", subagent=subagent), "read-only for this task")
        self.put("tests/other.py", "y\n")
        os.link(os.path.join(self.repo, "tests", "other.py"), os.path.join(self.repo, "tests", "other_hard.py"))
        self.put(".monerex/state/protected-paths", "tests/other.py\n")
        self.assert_denied(self.edit("tests/other_hard.py"), "read-only for this task")
        self.put(".monerex/state/protected-paths", "./tests/real_test.py\n")
        self.assert_denied(self.edit("tests/real_test.py"), "read-only for this task")

    def test_the_owners_entry_for_a_link_guards_its_target_in_a_worktree(self):
        self.put("tests/real_test.py", "x\n")
        os.symlink("real_test.py", os.path.join(self.repo, "tests", "test_bug.py"))
        self.git("add", "tests/real_test.py", "tests/test_bug.py")
        self.git("commit", "-q", "-m", "a test and a link to it")
        inner = self.worktree(".claude/worktrees/fix-1")
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        self.assert_denied(self.edit(".claude/worktrees/fix-1/tests/real_test.py"), "read-only for this task")
        self.assert_denied(self.run_hook("pre-edit", {"file_path": "tests/real_test.py"}, subagent=True, cwd=inner), "read-only for this task")

    def test_a_link_named_like_agent_configuration_is_configuration(self):
        self.put("docs/notes.md", "notes\n")
        self.put("tools/settings.json", "{}\n")
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        os.symlink(os.path.join(self.repo, "docs", "notes.md"), os.path.join(self.repo, "CLAUDE.md"))
        os.symlink(os.path.join(self.repo, "tools", "settings.json"), os.path.join(self.repo, ".claude", "settings.json"))
        for path in ("CLAUDE.md", ".claude/settings.json"):
            with self.subTest(path):
                self.assert_denied(self.edit(path, subagent=True), "agent configuration")
                self.assert_asked(self.edit(path), "agent configuration")

    def test_a_link_named_like_a_lockfile_is_a_lockfile_until_the_plan_lists_it(self):
        self.put("docs/lock.json", "{}\n")
        os.symlink(os.path.join(self.repo, "docs", "lock.json"), os.path.join(self.repo, "package-lock.json"))
        self.assert_denied(self.edit("package-lock.json", subagent=True), "a lockfile")
        self.put(".monerex/state/allowed-paths", "package-lock.json\n")
        self.assert_allowed(self.edit("package-lock.json", subagent=True))

    def test_an_allowed_lockfile_name_on_a_link_does_not_hide_configuration_in_another_checkout(self):
        beside = self.worktree(os.path.join(self.tmp, "beside"))
        with open(os.path.join(beside, "CLAUDE.md"), "w", encoding="utf-8") as handle:
            handle.write("notes\n")
        os.symlink(os.path.join(beside, "CLAUDE.md"), os.path.join(self.repo, "package-lock.json"))
        self.put(".monerex/state/allowed-paths", "package-lock.json\n")
        self.assert_asked(self.edit("package-lock.json"), "another checkout")

    def test_the_refusal_says_which_list_holds_the_entry(self):
        inner = self.worktree(".claude/worktrees/fix-1")
        self.put(".monerex/state/protected-paths", "tests/test_bug.py\n")
        done = self.run_hook("pre-edit", {"file_path": "tests/test_bug.py"}, cwd=inner)
        self.assert_denied(done, os.path.join(self.repo, ".monerex", "state", "protected-paths"))

    def test_files_in_a_worktree_are_ordinary_but_its_config_is_not(self):
        self.assert_allowed(self.edit(".claude/worktrees/task-1/src/app.py", subagent=True))
        self.assert_denied(self.edit(".claude/worktrees/task-1/.claude/settings.json", subagent=True), "agent configuration")

    def test_writing_a_denylisted_term_is_denied_without_echoing_it(self):
        for fields in ({"content": "for " + TERM}, {"new_string": TERM.upper()}, {"edits": [{"new_string": TERM}]}):
            with self.subTest(sorted(fields)):
                done = self.edit("notes.md", **fields)
                self.assert_denied(done, "denylisted term")
                self.assertNotIn(TERM, done.stderr.lower())

    # ------------------------------------------------------------ shell

    def test_ordinary_commands_are_allowed(self):
        for command in ("ls -la", "git status", "git commit -m 'add a thing'", "git push origin feature", "git push -u origin HEAD"):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_hook_skipping_is_denied(self):
        self.assert_denied(self.bash("git commit --no-verify -m x"), "skip git's hooks")
        self.assert_denied(self.bash("git commit -nm x"), "skip git's hooks")
        self.assert_denied(self.bash("git push --no-verify origin feature"), "skip git's hooks")

    def test_force_pushes_are_denied(self):
        for command in ("git push --force origin feature", "git push -f", "git push --force-with-lease origin feature", "git push origin +feature", "cd sub && git -C . push -f"):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "force-pushes")

    def test_pushing_to_the_default_branch_is_denied(self):
        for command in ("git push origin master", "git push origin feature:main", "git push origin HEAD:refs/heads/master"):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "default branch")
        self.git("checkout", "-q", "master")
        self.assert_denied(self.bash("git push"), "default branch")
        self.assert_denied(self.bash("git push origin HEAD"), "default branch")

    def test_a_push_is_judged_on_the_branch_an_earlier_checkout_in_the_command_leaves(self):
        # Issue 8: the guard read the checked-out branch once, when the command was submitted.
        # `git checkout master && git merge feature && git push` was judged on `feature` and
        # ran as a push of `master`.
        symptom = "a bare push after a checkout of the default branch in the same command passed the guard"
        for command in (
            "git checkout master && git merge feature && git push",
            "git checkout master && git merge feature && git push origin HEAD",
            "git switch master && git push",
            "git checkout master; git push",
            "git checkout -B master && git push",
            "git checkout master && sh -c 'git push'",
            "sh -c 'git checkout master' && git push",
            "eval 'git checkout master' && git push",
            # The forms that carry the name: glued to the flag, behind another flag, after `/`.
            "git checkout -Bmaster && git push",
            "git checkout -t origin/master && git push",
            "git switch -C master && git push",
            "git checkout --orphan master && git push",
            # A trailing `--` names no path, the last of two checkouts counts, `-C` is the same repository.
            "git checkout master -- && git push",
            "git checkout master && git checkout master && git push",
            "git -C . checkout master && git -C . push",
            # `-t` takes the branch off a remote-tracking ref however it is spelled, as git does.
            "git checkout -t refs/remotes/origin/master && git push",
            "git checkout -t remotes/origin/master && git push",
            "git checkout --track=direct origin/master && git push",
            # A checkout of a file leaves HEAD where it was, so it does not take the place of the
            # branch checked out before it; `--ours` and `--theirs` cannot switch at all.
            "git checkout master && git checkout a.txt && git push",
            "git checkout master && git checkout --theirs a.txt && git push",
            "git checkout master && git checkout --ours a.txt && git push",
            "git checkout master && git checkout --conflict=diff3 a.txt && git push",
            "git checkout master && git checkout -p a.txt && git push",
            "git checkout master && git switch a.txt && git push",
            # `--conflict` and `--merge` do switch branches, so they are no reason to look away.
            "git checkout --conflict=diff3 master && git push",
            "git checkout --merge master && git push",
            # `-` goes back to the branch before the last checkout: here, to master again.
            "git checkout master && git checkout - && git checkout - && git push",
            "git checkout master && git checkout @{-1} && git checkout @{-1} && git push",
            # Wrappers and assignments before git leave it the command.
            "env GIT_PAGER=cat git checkout master && git push",
            "env -i git checkout master && git push",
            "FOO=1 git checkout master && git push",
            "time git checkout master && git push",
            "sudo git checkout master && git push",
            "command git checkout master && git push",
            "if true; then git checkout master; fi && git push",
        ):
            with self.subTest(command):
                done = self.bash(command)
                refused = (done.returncode, "default branch" in done.stderr, "checks out `master`" in done.stderr)
                self.assertEqual(refused, (2, True, True), symptom)

    def test_a_branch_only_a_remote_has_is_a_branch_to_check_out(self):
        # `git checkout master` with no local master makes one from origin/master, so a name that
        # is no local branch is still a branch when a remote has it.
        self.git("branch", "-D", "master")
        self.git("update-ref", "refs/remotes/origin/master", "HEAD")
        for command in ("git checkout master && git push", "git checkout master && git checkout a.txt && git push"):
            with self.subTest(command):
                done = self.bash(command)
                self.assertEqual((done.returncode, "checks out `master`" in done.stderr), (2, True), done.stderr)

    def test_a_checkout_before_a_push_does_not_refuse_what_is_not_the_default_branch(self):
        # What the test above must not cost: a checkout that does not reach the default branch,
        # one that comes after the push, and a push that names its branch.
        for command in (
            "git checkout feature && git push",
            "git checkout -b other && git push -u origin HEAD",
            "git switch -c other && git push",
            "git checkout -- a.txt && git push",
            "git checkout master -- a.txt && git push",
            "git push && git checkout master",
            "git push origin HEAD && git checkout master && git pull",
            "git checkout master && git push origin feature",
            # Nested commands are in the order they run: the push is first, the checkout after it.
            "sh -c 'git push' && git checkout master",
            "eval 'git push' && git checkout master",
            # The last checkout wins: out to the default branch and back, by name or by `-`.
            "git checkout master && git pull && git checkout feature && git push",
            "git checkout master && git pull && git checkout - && git push",
            "git checkout master && git pull && git checkout @{-1} && git push",
            "git checkout -b other && git checkout - && git push -u origin HEAD",
            # A start point is not the branch, and a path is not a branch.
            "git checkout -b other master && git push -u origin HEAD",
            "git checkout master a.txt && git push",
            "git checkout -- master && git push",
            "git checkout -p master && git push",
            # Words that follow `echo` or `printf` are text, not a git command: they check out nothing.
            "echo git checkout master && git push origin feature",
            "echo git checkout master && git push",
            "echo git switch master && git push",
            "printf '%s ' git checkout master && git push",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_a_shell_given_its_script_after_other_flags_is_read_as_one_given_it_plainly(self):
        # `bash -c "..."` was read, and `bash -lc "..."` was not: the script is the first word
        # after the shell's options, whichever letters ride along with the `c`.
        symptom = "a push to the default branch passed the guard inside a shell called with other flags"
        for command in (
            'bash -c "git push origin master"',
            'bash -lc "git push origin master"',
            'sh -ec "git push origin master"',
            'zsh -ic "git push origin master"',
            'bash -cl "git push origin master"',
            'bash -c -- "git push origin master"',
            'bash -c -x "git push origin master"',
            'bash -c +x "git push origin master"',
            'bash -o pipefail -c "git push origin master"',
            'bash -co pipefail "git push origin master"',
            'bash --norc --noprofile -ec "git push origin master"',
            'bash --rcfile /dev/null -lc "git push origin master"',
            '/bin/bash -lc "git push origin master"',
            'env bash -lc "git push origin master"',
            'echo hi && bash -lc "git push origin master" arg0',
            'bash -lc "git checkout master && git push"',
            'bash -lc "echo hi; git push origin master"',
        ):
            with self.subTest(command):
                done = self.bash(command)
                self.assertEqual((done.returncode, "default branch" in done.stderr), (2, True), symptom)
        done = self.bash('bash -lc "git push --force origin feature"')
        self.assertEqual((done.returncode, "force" in done.stderr), (2, True), symptom)
        # What it does not touch: a script that does no harm, one that names its branch, and a
        # file given to the shell, whose arguments are not a script.
        for command in (
            'bash -lc "echo hi"',
            'bash -c -- "echo hi"',
            'bash -lc "git push origin feature"',
            'bash -o pipefail -c "git status"',
            'bash script.sh -x "echo hi"',
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_a_wrapper_spelled_as_a_path_is_still_a_wrapper(self):
        # `env git checkout master && git push` was refused and `/usr/bin/env git checkout master
        # && git push` was not: the words before git were compared as written, git by its name.
        symptom = "a checkout behind a wrapper spelled as a path was not recorded"
        for command in (
            "/usr/bin/env git checkout master && git push",
            "/usr/bin/env FOO=1 git checkout master && git push",
            "/usr/bin/env -i git checkout master && git push",
            "/usr/bin/sudo git checkout master && git push",
            "/usr/bin/time git checkout master && git push",
            "/usr/bin/nohup git checkout master && git push",
            "/usr/bin/env /usr/bin/git switch master && git push",
            "/usr/bin/git checkout master && git push",
        ):
            with self.subTest(command):
                done = self.bash(command)
                refused = (done.returncode, "default branch" in done.stderr, "checks out `master`" in done.stderr)
                self.assertEqual(refused, (2, True, True), symptom)
        # A path does not make text a command: `echo` and `printf` are still no wrapper.
        for command in (
            "/bin/echo git checkout master && git push",
            "/usr/bin/printf '%s ' git checkout master && git push",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_a_checkout_that_detaches_head_is_recorded_so_that_going_back_is_to_the_right_branch(self):
        # A name that is a commit and no branch (a tag, an id, `HEAD~1`, `origin/master`) and
        # `--detach` leave HEAD on no branch. `git checkout -` goes back to the branch before
        # it. Such a name was taken for a file, which records nothing, so the `-` swapped the
        # wrong pair and the push was judged on `feature`.
        self.git("tag", "v1.0")
        self.git("update-ref", "refs/remotes/origin/master", "HEAD")
        first = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD~1"], cwd=self.repo, env=self.env, capture_output=True, text=True, check=True
        ).stdout.strip()
        symptom = "a push after a checkout that detached HEAD and a `-` was judged on the wrong branch"
        for command in (
            "git checkout master && git checkout v1.0 && git checkout - && git push",
            "git checkout master && git checkout HEAD~1 && git checkout - && git push",
            "git checkout master && git checkout %s && git checkout - && git push" % first,
            "git checkout master && git checkout origin/master && git checkout - && git push",
            "git checkout master && git checkout --detach && git checkout - && git push",
            "git checkout master && git checkout --detach v1.0 && git checkout - && git push",
            "git checkout master && git checkout -d v1.0 && git checkout - && git push",
            "git checkout master && git switch --detach v1.0 && git switch - && git push",
            "git checkout master && git checkout v1.0 && git checkout @{-1} && git push",
            "git checkout master && sh -c 'git checkout v1.0' && git checkout - && git push",
        ):
            with self.subTest(command):
                done = self.bash(command)
                refused = (done.returncode, "default branch" in done.stderr, "checks out `master`" in done.stderr)
                self.assertEqual(refused, (2, True, True), symptom)
        # What it must not cost. Back to feature is feature. A push with HEAD on no branch names
        # no default branch; two steps back from the tag is the tag, not master.
        for command in (
            "git checkout feature && git checkout v1.0 && git checkout - && git push",
            "git checkout v1.0 && git checkout - && git push",
            "git checkout master && git checkout v1.0 && git push",
            "git checkout master && git checkout v1.0 && git checkout master && git checkout - && git push",
            "git checkout feature && git checkout --detach && git checkout - && git push",
            "git checkout master a.txt && git checkout - && git push",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_a_default_branch_a_fetch_brings_in_is_a_branch_to_check_out(self):
        # `git fetch && git checkout master` makes master from origin/master. The guard reads the
        # refs when the command is submitted, before the fetch ran, so the name of the default
        # branch is a branch whether or not it is there yet.
        self.git("branch", "-D", "master")
        for command, branch in (
            ("git fetch -q origin && git checkout master && git commit --allow-empty -qm x && git push", "master"),
            ("git fetch origin && git checkout master && git push", "master"),
            ("git pull -q origin && git switch master && git push", "master"),
            ("git fetch origin && git checkout main && git push", "main"),
            ("git checkout master && git push", "master"),
        ):
            with self.subTest(command):
                done = self.bash(command)
                refused = (done.returncode, "checks out `%s`" % branch in done.stderr)
                self.assertEqual(refused, (2, True), done.stderr)
        # Only the default branch's name is a branch before it exists: any other name is still
        # taken for a file, and a name that is not the default branch here is no exception.
        for command in ("git fetch origin && git checkout topic && git push", "git checkout a.txt && git push"):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))
        self.git("update-ref", "refs/remotes/origin/trunk", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        for command in ("git fetch origin && git checkout master && git push", "git checkout main && git push"):
            with self.subTest(command + " with trunk as the default branch"):
                self.assert_allowed(self.bash(command))

    def test_a_heredoc_body_is_text_and_not_a_command(self):
        # What `cat <<'EOF' > notes.txt` is given is data for `cat`. Its lines were read as
        # commands, so a note that held `git checkout master` refused the push after it.
        for command in (
            "cat <<'EOF' > notes.txt\ngit checkout master\nEOF\ngit push",
            "cat <<EOF > notes.txt\ngit checkout master\nEOF\ngit push",
            'cat <<"END" > notes.txt\ngit checkout master\nEND\ngit push',
            "cat <<-EOF > notes.txt\n\tgit checkout master\n\tEOF\ngit push",
            "cat > notes.md <<'EOF'\ngit push origin master\nEOF",
            "cat <<'EOF' | tee notes.txt\ngit push origin master\nEOF",
            "cat <<'EOF' > notes.txt\nsh -c 'git checkout master'\neval git checkout master\nEOF\ngit push",
            "git commit -F - <<'EOF'\nfix: git checkout master\n\ngit push origin master\nEOF",
            "git commit -m \"$(cat <<'EOF'\ngit checkout master\nEOF\n)\" && git push",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))
        # The commands around it are still read, and so is what only looks like one: a here-string,
        # a shift, quoted or commented text.
        for command in (
            "cat <<'EOF' > notes.txt\nnotes\nEOF\ngit checkout master && git push",
            "cat <<'EOF' > notes.txt && git checkout master\nnotes\nEOF\ngit push",
            "git checkout master && cat <<'EOF' > notes.txt\nnotes\nEOF\ngit push",
            "cat <<'EOF' > notes.txt\ngit checkout master\nEOF\ngit push origin master",
            "cat <<< hi\ngit checkout master\ngit push",
            "x=$((1<<2))\ngit checkout master\ngit push",
            "((x = 1<<2))\ngit checkout master\ngit push",
            "x=$[1<<2]\ngit checkout master\ngit push",
            "echo $[a[1]<<2]\ngit push origin master",
            "echo '<<EOF'\ngit checkout master\ngit push",
            "# cat <<EOF\ngit checkout master\ngit push",
        ):
            with self.subTest(command):
                done = self.bash(command)
                self.assertEqual((done.returncode, "default branch" in done.stderr), (2, True), done.stderr)

    def test_a_double_less_than_that_starts_no_heredoc_hides_no_line(self):
        # Found by review: each of these took a `<<` for a heredoc whose delimiter no line
        # matches, and dropped every line after it. Bash runs the next line.
        for command in (
            "echo ${x:-<<EOF}\ngit push --force origin feature",
            "echo ${a[1<<2]}\ngit push --force origin feature",
            "a[1<<2]=5\ngit push --force origin feature",
            "echo ${x:1<<1}\ngit push --force origin feature",
            'cat <<"E\\\\F"\nbody\nE\\F\ngit push --force origin feature',
            # An unquoted delimiter: what `$(...)` in the body holds runs, and only that is read.
            "cat <<EOF\n$(git push --force origin feature)\nEOF",
            "cat <<EOF\nDon't $(git push --force origin feature)\nEOF",
            "cat <<EOF\nsee $(echo $(git push --force origin feature))\nEOF",
            # A wrapper's flag value is not the command.
            "env -u echo sh -c 'git push --force origin feature'",
            "exec -a echo sh -c 'git push --force origin feature'",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "force")
        for command in (
            "cat <<'EOF'\n$(git push --force origin feature)\nEOF",
            "cat > notes.md <<EOF\nNever run git push --force; use `--force-with-lease`\nEOF\ngit push origin feature",
            "cat > notes.md <<EOF\nDon't run git push --force, it is $(date)\nEOF\ngit push origin feature",
            "echo sh -c 'git push --force origin feature'",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_a_denylisted_term_in_a_heredoc_body_is_still_denied(self):
        done = self.bash("cat <<'EOF' > notes.txt\nwork for %s\nEOF" % TERM)
        self.assert_denied(done, "denylisted term")
        self.assertNotIn(TERM, done.stderr)

    def test_a_shell_option_with_one_dash_is_not_a_bundle_of_letters(self):
        # bash takes its long options with one dash too. The bundle rule read the `o` in
        # `-noprofile` and `-login` as `-o` and took the next word, the `-lc`, as its value.
        symptom = "a push to the default branch passed the guard inside bash given a long option with one dash"
        for command in (
            'bash -noprofile -lc "git push origin master"',
            'bash -login -ec "git push origin master"',
            'bash -norc -c "git push origin master"',
            'bash -noprofile -norc -c "git push origin master"',
            'bash -posix -c "git push origin master"',
            'bash -restricted -c "git push origin master"',
            'bash -verbose -c "git push origin master"',
            'bash -noediting -c "git push origin master"',
            'bash -debugger -c "git push origin master"',
            'bash -rcfile /dev/null -c "git push origin master"',
            'bash -init-file /dev/null -lc "git push origin master"',
            '/bin/bash -login -c "git push origin master"',
            'env bash -noprofile -lc "git push origin master"',
            'bash -noprofile -lc "git checkout master && git push"',
        ):
            with self.subTest(command):
                done = self.bash(command)
                self.assertEqual((done.returncode, "default branch" in done.stderr), (2, True), symptom)
        # A script that does no harm, one that names its branch, a script file, and `-o`,
        # which does take a value, are as before.
        for command in (
            'bash -noprofile -lc "echo hi"',
            'bash -login -c "echo hi"',
            'bash -rcfile /dev/null -c "git push origin feature"',
            'bash -noprofile script.sh "git push origin master"',
            'bash -o pipefail -c "git push origin feature"',
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_what_follows_echo_is_text_even_when_it_is_a_shell_or_eval(self):
        # SECURITY.md says the words after `echo` or `printf` are text. A shell or `eval`
        # among them was still read as a command, so `echo eval git checkout master && git
        # push` refused a push that the shell runs on the branch it is on.
        for command in (
            "echo eval git checkout master && git push",
            "echo sh -c 'git checkout master' && git push -u origin HEAD",
            "echo bash -lc 'git checkout master' && git push",
            "printf '%s ' eval git checkout master && git push",
            "env echo eval git checkout master && git push",
            "time echo sh -c 'git checkout master' && git push",
            "/bin/echo sh -c 'git checkout master' && git push",
            "echo hi; echo sh -c 'git checkout master' && git push",
            "if true; then echo eval git checkout master; fi && git push",
            "echo sh -c 'git push origin master'",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))
        # What `echo` does not hide: the commands before and after it, a shell that is the
        # command, and one a wrapper the guard does not know runs.
        for command in (
            "echo hi && sh -c 'git push origin master'",
            "echo hi; eval git checkout master && git push",
            "echo hi | xargs sh -c 'git push origin master'",
            "echo hi && echo sh -c ok; bash -lc 'git checkout master' && git push",
        ):
            with self.subTest(command):
                done = self.bash(command)
                self.assertEqual((done.returncode, "default branch" in done.stderr), (2, True), done.stderr)

    def test_a_subagent_cannot_push_or_open_a_pr(self):
        self.assert_denied(self.bash("git push origin feature", subagent=True), "only the main session pushes")
        self.assert_denied(self.bash("gh pr create --fill", subagent=True), "only the main session opens a PR")

    def test_merging_is_never_done_by_monerex(self):
        self.assert_denied(self.bash("gh pr merge 12 --squash"), "merging is the user's decision")

    def test_a_command_with_a_denylisted_term_is_denied(self):
        done = self.bash("git commit -m 'work for %s'" % TERM)
        self.assert_denied(done, "denylisted term")
        self.assertNotIn(TERM, done.stderr)

    def test_the_push_gate_needs_passing_checks_on_this_commit(self):
        self.configure({"checks": ["test -f a.txt"]})
        self.assert_denied(self.bash("git push origin feature"), "no check record")
        self.assert_denied(self.bash("gh pr create --fill"), "no check record")
        ran = self.run_checks()
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assert_allowed(self.bash("git push origin feature"))
        self.put("b.txt", "more\n")
        self.git("add", "b.txt")
        self.git("commit", "-q", "-m", "second")
        self.assert_denied(self.bash("git push origin feature"), "a different commit")

    def test_a_push_after_a_command_that_moves_a_branch_waits_for_the_checks(self):
        # The gate reads the commit when the command is submitted. A commit, merge or checkout
        # earlier in the same line changes what is pushed, and no check has run on that.
        self.configure({"checks": ["test -f a.txt"]})
        self.git("branch", "other")
        self.assertEqual(self.run_checks().returncode, 0)
        for command in (
            "git commit -qam x && git push",
            "git commit -qam x && git push origin feature",
            "git commit --amend --no-edit && git push origin HEAD",
            "git pull && git push",
            "git merge other && git push origin feature",
            "git rebase other && git push",
            "git reset --soft HEAD~1 && git push origin feature",
            "git cherry-pick other; git push",
            "git revert --no-edit HEAD && git push",
            "git am < fix.patch && git push",
            "git checkout other && git push",
            "git switch other && git push origin other",
            "git checkout -b next HEAD~1 && git push -u origin HEAD",
            "git switch -c next HEAD~1 && git push -u origin next",
            "git stash branch next && git push",
            "git update-ref refs/heads/feature other && git push origin feature",
            "git symbolic-ref HEAD refs/heads/other && git push",
            "git branch -f feature other && git push origin feature",
            "git branch -M renamed && git push",
            "git fetch origin master:feature && git push origin feature",
            "git fetch https://example.invalid/o/r.git main:feature && git push origin feature",
            "git fetch -u origin && git push",
            "sh -c 'git commit -qam x' && git push",
            "env git commit -qam x && git push",
            "git commit -qam x && gh pr create --fill --repo o/r",
            "git checkout -B other && git push origin other",
            "git switch -C other && git push origin other",
            "git checkout HEAD~1 && git push origin feature",
            "git checkout $b && git push origin feature",
            "git checkout - && git push origin feature",
            "git checkout --detach && git push origin feature",
            "git symbolic-ref -d HEAD; git push origin feature",
            "git reset --hard $sha && git push origin feature",
            "git fetch && git reset --hard origin/topic && git push origin feature",
            "cat > notes.md <<EOF\nDon't run `make` here\nEOF\ngit commit -qam x && git push origin feature",
            "git commit -m --abort && git push origin feature",
            "git checkout --conflict diff3 other && git push origin feature",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "moves a branch")
        # What moves no branch, or comes after the push, leaves the gate as it was.
        for command in (
            "git push origin feature",
            "git status && git push origin feature",
            "git add a.txt && git push origin feature",
            "git fetch origin && git push origin feature",
            "git stash pop && git push origin feature",
            "git checkout -- a.txt && git push origin feature",
            "git checkout -b next && git push -u origin next",
            "git checkout -bnext && git push -u origin HEAD",
            "git switch -c next && git push -u origin HEAD",
            "git fetch git@example.invalid:o/r.git && git push origin feature",
            "git fetch https://example.invalid/o/r.git main && git push origin feature",
            "git branch -c copy && git push origin feature",
            "git checkout a.txt && git push origin feature",
            "git checkout HEAD a.txt && git push origin feature",
            "git checkout . && git push origin feature",
            "git checkout feature && git push origin feature",
            "git reset HEAD a.txt && git push origin feature",
            "git reset a.txt && git push origin feature",
            "git reset --hard && git push origin feature",
            "git checkout -b next HEAD && git push -u origin next",
            "git reset --soft HEAD && git push origin feature",
            "git merge --abort; git push origin feature",
            "git rebase --abort; git push origin feature",
            "git symbolic-ref --short HEAD && git push origin feature",
            "git fetch origin refs/heads/master:refs/remotes/origin/master && git push origin feature",
            "git fetch origin v1:refs/tags/v1 && git push origin feature",
            "git fetch --depth 1 git@example.invalid:o/r.git && git push origin feature",
            "git fetch --depth=1 origin && git push origin feature",
            "git push origin feature && git commit -qam x",
            "gh pr create --fill --repo o/r",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))
        # Without a checks gate there is nothing to wait for.
        self.configure({})
        self.assert_allowed(self.bash("git commit -qam x && git push origin feature"))

    def test_a_reset_to_what_a_fetch_in_the_line_brings_in_waits_for_the_checks(self):
        # Found by review: origin/feature equalled HEAD when the command was submitted, so the
        # reset looked like no move, though the fetch before it moves origin/feature on.
        self.configure({"checks": ["test -f a.txt"]})
        remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", remote], env=self.env, capture_output=True, check=True)
        self.git("remote", "add", "origin", remote)
        self.git("push", "-q", "origin", "feature")
        self.git("fetch", "-q", "origin")
        self.assertEqual(self.run_checks().returncode, 0)
        for command in (
            "git fetch && git reset --hard origin/feature && git push origin HEAD:other",
            "git fetch origin; git reset --hard @{u}; git push origin HEAD:other",
            "git pull --ff-only && git push origin feature",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "moves a branch")
        self.assert_allowed(self.bash("git reset --hard origin/feature && git push origin feature"))
        self.assert_allowed(self.bash("git fetch && git push origin feature"))

    def test_the_owners_override_of_the_default_branch_rule_is_not_for_agents(self):
        for command in (
            "git -c monerex.allowDefaultPush=1 push origin master",
            "git -c MONEREX.ALLOWDEFAULTPUSH=yes push origin feature",
            "git -cmonerex.allowDefaultPush=1 push origin master",
            "V=1 git --config-env=monerex.allowDefaultPush=V push origin master",
            "git --config-env monerex.allowDefaultPush=V push origin master",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=monerex.allowDefaultPush GIT_CONFIG_VALUE_0=1 git push origin master",
            "export GIT_CONFIG_PARAMETERS=\"'monerex.allowdefaultpush'='1'\"; git push origin master",
            "git config monerex.allowDefaultPush true",
            "git config --local monerex.allowdefaultpush 1",
            "git config set monerex.allowDefaultPush true",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=monerex.allow\"\"DefaultPush GIT_CONFIG_VALUE_0=1 git push origin feature",
            "git -c monerex.allow\"\"DefaultPush=1 push origin feature",
            "git -c alias.p='!git -c monerex.allowDefaultPush=1 push' p origin feature:master",
            "git config alias.p '!git -c monerex.allowDefaultPush=1 push'",
            "git --attr-source HEAD -c monerex.allowDefaultPush=1 push origin feature",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "not for agents")
        # Naming it is not using it, and reading or removing it is harmless.
        for command in (
            "git commit -qm 'document monerex.allowDefaultPush'",
            "grep -rn allowDefaultPush SECURITY.md",
            "grep -rn 'monerex.allowDefaultPush\\|GIT_CONFIG_COUNT' SECURITY.md",
            "git commit -qm 'monerex.allowDefaultPush is ignored in GIT_CONFIG_COUNT files'",
            "echo monerex.allowDefaultPush GIT_CONFIG_PARAMETERS",
            "git config --get monerex.allowDefaultPush",
            "git config --show-scope --get monerex.allowDefaultPush",
            "git config --unset monerex.allowDefaultPush",
            "git config -l",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_no_git_command_skips_the_hooks(self):
        # A merge, am, rebase, cherry-pick or revert that makes a commit runs commit-msg.
        for command in (
            "git merge --no-verify other",
            "git am --no-verify < fix.patch",
            "git rebase --no-verify other",
            "git cherry-pick --no-verify other",
            "git revert --no-verify HEAD",
            "git merge --no-veri other",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "skip git's hooks")
        self.assert_allowed(self.bash("git merge --verify other"))

    def test_the_git_hooks_cannot_be_switched_off_or_removed(self):
        for command in (
            "git config core.hooksPath /dev/null",
            "git config --local core.hookspath /tmp/none",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git push origin feature",
            "GIT_CONFIG_PARAMETERS=\"'core.hookspath=/dev/null'\" git push origin feature",
            "git -c alias.p='!git -c core.hooksPath=/dev/null push' p origin feature",
            "git --attr-source HEAD -c core.hooksPath=/dev/null push origin feature",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "hooks may not be redirected")
        for command in (
            "rm .git/hooks/pre-push",
            "rm -f %s/.git/hooks/pre-push" % self.repo,
            "mv .git/hooks .git/hooks.off",
            "chmod -x .git/hooks/pre-push",
            "echo exit 0 > .git/hooks/pre-push",
            "cp /dev/null .git/hooks/pre-commit",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "git's hooks")
        for command in (
            "git -c include.path=/abs/inc.cfg push origin feature",
            "git -c includeIf.onbranch:feature.path=/abs/inc.cfg push origin feature",
            "git config include.path /abs/inc.cfg",
            "GIT_CONFIG_GLOBAL=/abs/other.cfg git push origin feature",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "may carry any setting")
        for command in (
            "git config monerex.defaultBranch other",
            "git config monerex.requireDenylist false",
            "git config --remove-section monerex",
            "git config --rename-section monerex other",
            "git config remove-section monerex",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "monerex's own settings")
        for command in (
            "sh -c 'echo exit 0 > .git/hooks/pre-push'",
            "eval 'echo x > .git/hooks/pre-push'",
            "echo x >> $PWD/.git/hooks/pre-commit",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "git's hooks")
        for command in (
            "ls .git/hooks",
            "cat .git/hooks/pre-push",
            "sh githooks/install.sh",
            "git config --get core.hooksPath",
            "git config user.name Someone",
            "GIT_CONFIG_GLOBAL=/dev/null git log",
            "GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git status",
            "export GIT_CONFIG_GLOBAL=/dev/null",
            # Another repository's hooks, a read of this one's, a bare repository's.
            "cp githooks/pre-push .monerex/tmp/r/.git/hooks/pre-push",
            "rm -rf .monerex/tmp/probe-r/.git/hooks/pre-push",
            "cp .git/hooks/pre-push backup-of-pre-push",
            "cp -r foo.git/hooks/post-receive x",
            "echo x > .monerex/tmp/r/.git/hooks/pre-push",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_where_a_push_sends_its_output_is_not_a_branch_to_push(self):
        # Seen in a real ship: `2>&1` after a push was read as a branch, no commit was found for
        # it, and the push was refused as if the checks had run on another commit.
        self.configure({"checks": ["test -f a.txt"]})
        self.assertEqual(self.run_checks().returncode, 0)
        for tail in ("2>&1", "> out.txt 2>/dev/null", "&> log", ">>log", "2>&1 | tail -3", '2>&1; echo "exit=$?"'):
            with self.subTest(tail):
                self.assert_allowed(self.bash("git push -u origin HEAD:refs/heads/feature " + tail))
        # What it hides nothing of: the branch named after a redirection is still seen.
        self.assert_denied(self.bash("git push origin 2>&1 master"), "default branch")
        self.assert_denied(self.bash("git push origin feature:master > out.txt"), "default branch")
        self.assert_denied(self.bash("git push --force origin feature 2>&1"), "force")
        # A redirection that overwrites anyway, and one with a space before its file.
        for tail in (">| out.txt", "2>| out.txt", "2> out.txt"):
            with self.subTest(tail):
                self.assert_allowed(self.bash("git push origin feature " + tail))
        # Lexed again from joined words.
        self.assert_allowed(self.bash('sh -c "git push origin feature 2>&1"'))
        self.assert_allowed(self.bash("eval git push origin feature 2>&1"))

    def test_a_spaced_number_or_a_quoted_operator_is_an_argument_of_a_push(self):
        for command in (
            "git push --repo 2 >/dev/null origin main",
            "git push -o 2 > out.txt origin main",
            "git push --repo '>' origin main",
            "git push origin '>' main",
            "git push origin \\> main",
            "git push origin feature '>' main",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "default branch")

    def test_a_branch_named_by_a_number_before_a_redirection_is_pushed(self):
        self.configure({"checks": ["test -f a.txt"]})
        self.assertEqual(self.run_checks().returncode, 0)
        self.git("branch", "42", "HEAD~1")
        self.assert_denied(self.bash("git push origin 42 > out.txt"), "a different commit")
        self.assert_allowed(self.bash("git push origin feature 2> out.txt"))

    def test_a_separator_in_quotes_does_not_end_the_command(self):
        # To the shell `';'` is an argument. Read as the end of the command it cut a push in
        # two, and the half that named the default branch was judged as a command called `main`.
        for quoted in ("';'", '";"', "\\;", "'&'", "'|'", "'&&'", "'('", "')'"):
            with self.subTest(quoted):
                self.assert_denied(self.bash("git push origin %s master" % quoted), "default branch")
                self.assert_denied(self.bash("git push %s --force origin feature" % quoted), "force")
        # A separator that is not quoted still ends it, and one inside a longer word is part of the word.
        self.assert_denied(self.bash("echo hi; git push origin master"), "default branch")
        self.assert_denied(self.bash("sh -c 'echo hi; git push origin master'"), "default branch")
        self.assert_allowed(self.bash("git commit -m 'one; two & three | four (five)'"))

    def test_what_eval_runs_is_read_as_the_shell_reads_it(self):
        # `eval` takes its arguments apart again, so a separator that was quoted outside is a
        # separator inside. A second-family read found the quoted character dropped on the way
        # in. These held before that was put right, by other rules; they pin the behaviour.
        self.assert_denied(self.bash("eval echo hi ';' git push origin master"), "default branch")
        self.assert_denied(self.bash("eval \"git push origin ';' master\""), "default branch")
        self.assert_denied(self.bash("sh -c 'git push origin \">\" master'"), "default branch")
        self.assert_allowed(self.bash("eval \"echo '>'\""))

    def test_only_what_eval_reads_again_is_judged(self):
        # From a fresh review: the words outside were judged too, where `'&&'` is an argument,
        # so `echo done` became a branch to push and the push was refused for its checks.
        self.configure({"checks": ["test -f a.txt"]})
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_allowed(self.bash("eval git push origin feature '&&' echo done"))
        self.assert_allowed(self.bash("eval git push origin feature ';' git status"))
        # The redirection is one inside: a file called master is written, nothing is pushed there.
        self.assert_allowed(self.bash("eval \"git push origin feature\" '>' master"))
        self.assert_denied(self.bash("eval git push origin feature '&&' git push origin master"), "default branch")
        self.assert_denied(self.bash("time eval git push --force origin feature"), "force")

    def test_a_word_eval_that_is_an_argument_hides_nothing(self):
        # From a second-family read of the change above: `eval` as a branch name made the
        # command vanish, and the push to the default branch, or by force, with it.
        self.assert_denied(self.bash("git push origin eval master"), "default branch")
        self.assert_denied(self.bash("git push origin eval --force"), "force")
        self.assert_denied(self.bash("git push --no-verify origin eval"), "hooks")
        self.assert_allowed(self.bash("git push origin eval"))
        self.assert_denied(self.bash("FOO=1 time eval git push origin master"), "default branch")

    def test_a_comment_runs_to_the_end_of_its_line(self):
        # Also from that read: a parenthesis inside a comment ended the comment.
        self.assert_allowed(self.bash("git status # (gh pr merge 12 --repo o/r)"))
        self.assert_allowed(self.bash("git status # one; gh pr merge 12 --repo o/r && two | three"))
        self.assert_denied(self.bash("git status # note\ngh pr merge 12 --repo o/r"), "merging is the user's decision")
        self.assert_denied(self.bash("git commit -m 'line one\n# not a comment' --no-verify"))

    def test_a_line_joined_by_a_backslash_is_one_command(self):
        # From a second-family read, and as old as the guard: `\` at a line end joins the
        # lines, but they were judged as two commands, so the branch on the second line was
        # not seen as part of the push.
        self.configure({"checks": ["test -f a.txt"]})
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_denied(self.bash("git push origin \\\nmaster"), "default branch")
        self.assert_denied(self.bash("git push \\\n  origin master"), "default branch")
        self.assert_denied(self.bash("git push \\\n  --force \\\n  origin feature"), "force")
        self.assert_denied(self.bash("gh pr \\\n  merge 12 --repo o/r"), "merging is the user's decision")
        self.assert_allowed(self.bash("git push origin \\\nfeature"))
        self.assert_allowed(self.bash("git push \\\n  -u origin \\\n  feature"))

    def test_a_comment_is_only_what_the_shell_takes_for_one(self):
        # Also from that read. A `#` after a closing quote is part of the word; a quote
        # inside a comment opens nothing; and a backslash does not carry a comment on.
        self.assert_denied(self.bash('echo ok ""#; git push origin master'), "default branch")
        self.assert_denied(self.bash("echo \\ #x; git push origin master"), "default branch")
        self.assert_denied(self.bash("echo a\\\n#b; git push origin master"), "default branch")
        self.assert_allowed(self.bash("git status \\\n# then; git push origin master"))
        self.assert_denied(self.bash("# don't\ngit push origin master # it's"), "default branch")
        self.assert_denied(self.bash("# a note \\\ngit push origin master"), "default branch")
        self.assert_denied(self.bash("echo 'one\n# two'; git push origin master"), "default branch")
        self.assert_allowed(self.bash("git status # don't push yet; git push origin master"))

    def test_a_comment_is_not_a_command(self):
        # Also from that review, and older than this branch: a comment was read as a command.
        self.configure({"checks": ["test -f a.txt"]})
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_allowed(self.bash("git status\n# gh pr merge 12 --repo o/r\ngit log -1"))
        self.assert_allowed(self.bash("git push origin feature # ship it"))
        self.assert_allowed(self.bash("# first push the branch\ngit push origin feature"))
        self.assert_allowed(self.bash("(git push origin feature)>out.txt"))
        # A `#` that is quoted or inside a word starts nothing, and a new line ends a comment.
        self.assert_denied(self.bash("git push origin '#' master"), "default branch")
        self.assert_denied(self.bash("git push origin feature#1 master"), "default branch")
        self.assert_denied(self.bash("echo ok # then\ngit push origin master"), "default branch")
        self.assert_denied(self.bash("git commit -m '#12 fix' --no-verify"))

    def test_an_option_between_pr_and_merge_does_not_hide_the_merge(self):
        # Also from that read, and older than this branch: `--repo o/r` between the two words.
        for command in ("gh pr --repo o/r merge 12", "gh pr -R o/r merge 12", "gh --repo o/r pr merge 12", "gh pr --repo=o/r merge 12"):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "merging is the user's decision")
        self.assert_denied(self.bash("gh pr --repo o/r create --fill", subagent=True), "only the main session opens a PR")

    def test_a_redirection_between_the_words_of_a_command_hides_nothing(self):
        # Found while answering a review: with `2>&1` between `pr` and `merge` the rule for
        # merging did not see a merge, and the same between `git` and `push`.
        self.assert_denied(self.bash("gh pr 2>&1 merge 12 --repo o/r"))
        self.assert_denied(self.bash("gh 2>/dev/null pr merge 12 --repo o/r"))
        self.assert_denied(self.bash("git 2>&1 push origin master"), "default branch")
        self.assert_denied(self.bash("git > out.txt push --force origin feature"), "force")

    def test_a_failing_check_is_recorded_and_blocks_the_push(self):
        self.configure({"checks": ["test -f a.txt", "test -f missing.txt"]})
        self.assertEqual(self.run_checks().returncode, 1)
        self.assert_denied(self.bash("git push origin feature"), "the last check run failed")

    def test_a_worktree_folder_monerex_makes_is_not_uncommitted_work(self):
        # Found by review: bugfix and feedback make worktrees under .claude/worktrees, which a
        # user's repository does not ignore, and the checks then recorded an unclean tree.
        self.configure({"checks": ["test -f a.txt"]})
        self.put(".claude/worktrees/fix-1/a.txt", "x\n")
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_allowed(self.bash("git push origin feature"))

    def test_checks_that_ran_on_uncommitted_work_do_not_open_the_gate(self):
        self.configure({"checks": ["test -f new.txt"]})
        self.put("new.txt", "never committed\n")
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_denied(self.bash("git push origin feature"), "uncommitted or untracked changes")

    def test_the_gate_checks_the_commit_being_pushed_not_the_one_checked_out(self):
        self.configure({"checks": ["test -f a.txt"]})
        self.git("branch", "other")
        self.put("b.txt", "more\n")
        self.git("add", "b.txt")
        self.git("commit", "-q", "-m", "second")
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_allowed(self.bash("git push origin feature"))
        self.assert_denied(self.bash("git push origin other"), "a different commit")

    def test_a_push_built_on_an_old_default_branch_is_asked_about(self):
        self.configure({"checks": ["test -f a.txt"]})
        remote = os.path.join(self.tmp, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", remote], env=self.env, capture_output=True, check=True)
        self.git("remote", "add", "origin", remote)
        self.git("push", "-q", "origin", "master")
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_allowed(self.bash("git push origin feature"))

        self.git("checkout", "-q", "master")  # the default branch moves on, and we know about it
        self.put("c.txt", "theirs\n")
        self.git("add", "c.txt")
        self.git("commit", "-q", "-m", "moved on")
        self.git("push", "-q", "origin", "master")
        self.git("checkout", "-q", "feature")
        self.assert_asked(self.bash("git push origin feature"), "does not contain the newest 1 commit(s) of origin/master")
        self.assert_denied(self.bash("git push origin feature", subagent=True), "only the main session pushes")

        self.git("merge", "-q", "--no-edit", "origin/master")
        self.assert_denied(self.bash("git push origin feature"), "a different commit")  # checks are for the old head
        self.assertEqual(self.run_checks().returncode, 0)
        self.assert_allowed(self.bash("git push origin feature"))

    # ------------------------------------------------------------ code-host scope

    def test_a_code_host_command_that_names_its_repository_is_allowed(self):
        for command in (
            "gh pr list --repo o/r",
            "gh -R o/r issue view 3",
            "gh pr view https://github.com/o/r/pull/1",
            "gh run list --repo=o/r",
            "gh api repos/o/r/pulls",
            "gh auth status",
        ):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_a_code_host_command_with_no_repository_is_asked_about_and_refused_to_a_subagent(self):
        for command in ("gh pr list", "gh issue view 3", "gh run view 99 --log"):
            with self.subTest(command):
                self.assert_asked(self.bash(command), "does not name its repository")
                self.assert_denied(self.bash(command, subagent=True), "does not name its repository")

    def test_an_api_endpoint_is_found_wherever_it_stands(self):
        """Options and their values may come before the endpoint. Tried in process, with a
        made-up wide path, so that this file holds none of the real ones."""
        sys.path.insert(0, os.path.join(ROOT, "hooks"))
        import monerex_hook

        real = monerex_hook.GH_WIDE_PATHS
        monerex_hook.GH_WIDE_PATHS = ("zz/everything",)
        self.addCleanup(setattr, monerex_hook, "GH_WIDE_PATHS", real)

        def verdict(command):
            words = command.split()
            return monerex_hook.gh_scope(words, [word for word in words[1:] if not word.startswith("-")])

        for command in (
            "gh api zz/everything",
            "gh api /zz/everything/more",
            "gh api -X GET zz/everything",
            "gh api --method GET zz/everything",
            "gh api -H Accept:x zz/everything",
            "gh api --jq .[].login zz/everything",
            "gh api https://api.example.invalid/zz/everything",
            "gh -R o/r api --paginate zz/everything",
        ):
            with self.subTest(command):
                refused = verdict(command)
                self.assertTrue(refused and not isinstance(refused, monerex_hook.Ask), command)
        for command in ("gh api repos/o/r/pulls", "gh api -X GET repos/o/r/zz/everything", "gh api -f q=zz graphql"):
            with self.subTest(command):
                self.assertIsNone(verdict(command))
        self.assertEqual(monerex_hook.gh_command("gh -R o/r pr list".split()), "pr")
        self.assertEqual(monerex_hook.gh_command("gh --repo o/r issue view 3".split()), "issue")

    # ------------------------------------------------------------ shell writes

    def shell(self, command, change=None, subagent=False, after_id="t1"):
        self.run_hook("pre-bash", {"command": command}, subagent=subagent, tool_use_id="t1")
        if change:
            change()
        return self.run_hook("post-bash", {"command": command}, subagent=subagent, tool_use_id=after_id)

    def test_a_shell_command_that_changes_agent_configuration_is_reported(self):
        self.put(".claude/settings.json", "{}\n")
        done = self.shell("sed -i '' s/a/b/ .claude/settings.json", lambda: self.put(".claude/settings.json", '{"x": 1}\n'))
        self.assert_denied(done, ".claude/settings.json")
        self.assertIn("Tell the user", done.stderr)
        with open(os.path.join(self.repo, ".monerex", "log", "guard.jsonl"), encoding="utf-8") as handle:
            self.assertEqual(json.loads(handle.readline())["paths"], [".claude/settings.json"])

    def test_a_git_that_fails_after_the_command_does_not_hide_the_change(self):
        # When one of the hook's two readings of HEAD fails, the change must not be taken for
        # a checkout's and left unreported.
        self.put(".claude/settings.json", "{}\n")
        before = self.run_hook("pre-bash", {"command": "echo x > .claude/settings.json"}, tool_use_id="t9")
        self.assertEqual(before.returncode, 0, before.stderr)
        self.put(".claude/settings.json", '{"x": 1}\n')
        failing = os.path.join(self.tmp, "failing-git")
        os.makedirs(failing)
        with open(os.path.join(failing, "git"), "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 128\n")  # git starts and fails, as the macOS launcher can under load
        os.chmod(os.path.join(failing, "git"), 0o755)
        env = dict(self.env, PATH=failing + os.pathsep + "/usr/bin:/bin")
        data = {"cwd": self.repo, "session_id": "s1", "tool_input": {"command": "echo x"}, "tool_use_id": "t9"}
        done = subprocess.run([sys.executable, "-I", HOOK, "post-bash"], input=json.dumps(data), cwd=self.repo, env=env, capture_output=True, text=True)
        self.assert_denied(done, ".claude/settings.json")

    def test_a_subagent_is_told_to_put_it_back(self):
        done = self.shell("echo SECRET=1 > .env", lambda: self.put(".env", "SECRET=1\n"), subagent=True)
        self.assert_denied(done, ".env")
        self.assertIn("Put them back", done.stderr)

    def test_an_ordinary_file_changed_by_the_shell_is_not_reported(self):
        self.assert_allowed(self.shell("echo hi > src/app.py", lambda: self.put("src/app.py", "hi\n")))

    def test_a_lockfile_the_plan_lists_is_not_reported(self):
        self.put(".monerex/state/allowed-paths", "package-lock.json\n")
        self.assert_allowed(self.shell("npm install", lambda: self.put("package-lock.json", "{}\n")))
        os.remove(os.path.join(self.repo, ".monerex", "state", "allowed-paths"))
        self.assert_denied(self.shell("npm install", lambda: self.put("package-lock.json", '{"a": 1}\n')), "package-lock.json")

    def test_a_command_that_moved_head_is_not_reported(self):
        def commit_a_config_change():
            self.put(".mcp.json", "{}\n")
            self.git("add", ".mcp.json")
            self.git("commit", "-q", "-m", "add servers")

        self.assert_allowed(self.shell("git pull", commit_a_config_change))

    def test_a_result_that_does_not_belong_to_the_snapshot_is_not_judged(self):
        self.assert_allowed(self.shell("x", lambda: self.put(".mcp.json", "{}\n"), after_id="t2"))

    def test_a_command_cannot_allow_a_file_and_then_change_it(self):
        def allow_then_change():
            self.put(".monerex/state/allowed-paths", ".claude/settings.json\n")
            self.put(".claude/settings.json", '{"permissions": {"allow": ["Bash(*)"]}}\n')

        done = self.shell("sh trick.sh", allow_then_change)
        self.assert_denied(done, ".claude/settings.json")
        self.assertIn(".monerex/state/allowed-paths", done.stderr)

    def test_the_allowed_list_opens_lockfiles_and_nothing_else(self):
        self.put(".monerex/state/allowed-paths", ".mcp.json\npackage-lock.json\n")
        self.assert_denied(self.shell("x", lambda: self.put(".mcp.json", "{}\n")), ".mcp.json")

    def test_two_commands_in_flight_each_keep_their_own_snapshot(self):
        self.run_hook("pre-bash", {"command": "slow"}, tool_use_id="a")
        self.put(".mcp.json", "{}\n")
        self.run_hook("pre-bash", {"command": "quick"}, tool_use_id="b")
        self.assert_allowed(self.run_hook("post-bash", {"command": "quick"}, tool_use_id="b"))
        self.assert_denied(self.run_hook("post-bash", {"command": "slow"}, tool_use_id="a"), ".mcp.json")
        self.assertEqual(os.listdir(os.path.join(self.repo, ".monerex", "state", "shell")), [])

    def test_listing_a_new_protected_path_does_not_report_the_file_it_names(self):
        self.put("tests/test_bug.py", "x\n")
        done = self.shell("echo tests/test_bug.py >> .monerex/state/protected-paths", lambda: self.put(".monerex/state/protected-paths", "tests/test_bug.py\n"))
        self.assert_denied(done, ".monerex/state/protected-paths")
        self.assertNotIn("tests/test_bug.py,", done.stderr.replace(".monerex/state/protected-paths", ""))
        self.assertNotIn("test_bug.py", done.stderr.replace("protected-paths", ""))

    def test_a_protected_pattern_is_watched_as_the_edit_rule_reads_it(self):
        self.put("tests/test_bug.py", "x\n")
        self.put("tests/deep/test_more.py", "x\n")
        self.put(".monerex/state/protected-paths", "tests/*\n")
        self.assert_denied(self.edit("tests/test_bug.py"), "read-only for this task")
        self.assert_denied(self.shell("x", lambda: self.put("tests/test_bug.py", "changed\n")), "tests/test_bug.py")
        self.assert_denied(self.shell("x", lambda: self.put("tests/deep/test_more.py", "changed\n")), "tests/deep/test_more.py")

    def test_a_change_behind_a_link_is_seen(self):
        self.put("shared/settings.json", "{}\n")
        os.makedirs(os.path.join(self.repo, ".claude"), exist_ok=True)
        os.symlink(os.path.join(self.repo, "shared", "settings.json"), os.path.join(self.repo, ".claude", "settings.json"))
        self.assert_denied(self.shell("x", lambda: self.put("shared/settings.json", '{"x": 1}\n')), ".claude/settings.json")

        os.makedirs(os.path.join(self.repo, "agents-a"))
        os.makedirs(os.path.join(self.repo, "agents-b"))
        self.put("agents-b/evil.md", "x\n")
        link = os.path.join(self.repo, ".claude", "agents")
        os.symlink(os.path.join(self.repo, "agents-a"), link)

        def repoint():
            os.remove(link)
            os.symlink(os.path.join(self.repo, "agents-b"), link)

        self.assert_denied(self.shell("x", repoint), ".claude/agents")

    def test_compiled_python_in_a_watched_folder_is_not_a_change(self):
        self.put(".claude/hooks/__pycache__/x.cpython-312.pyc", "one")
        self.put(".claude/hooks/y.pyc", "one")
        def recompile():
            self.put(".claude/hooks/__pycache__/x.cpython-312.pyc", "two!")
            self.put(".claude/hooks/y.pyc", "two!")

        self.assert_allowed(self.shell("python3 -m unittest", recompile))

    # ------------------------------------------------------------ review findings

    def test_a_newline_separates_commands(self):
        self.assert_denied(self.bash("git status\ngit push --force origin feature"), "force-pushes")
        self.assert_denied(self.bash("git add -A\ngit commit --no-verify -m x"), "skip git's hooks")

    def test_a_hash_inside_a_word_is_not_a_comment(self):
        self.assert_denied(self.bash("echo a#b; git push -f origin feature"), "force-pushes")

    def test_wrappers_and_shell_syntax_do_not_hide_a_command(self):
        for command in (
            "command git push -f origin feature",
            "env GIT_TRACE=1 git push -f origin feature",
            "time git push -f origin feature",
            "if true; then git push -f origin feature; fi",
            "bash -c 'git push -f origin feature'",
            "eval git push -f origin feature",
        ):
            with self.subTest(command):
                self.assert_denied(self.bash(command), "force-pushes")
        self.assert_denied(self.bash("FOO=1 gh pr merge 12"), "merging is the user's decision")
        self.assert_denied(self.bash("gh -R o/r pr merge 12"), "merging is the user's decision")
        self.assert_denied(self.bash("gh api -X PUT repos/o/r/pulls/1/merge"), "merging is the user's decision")

    def test_abbreviated_and_redirected_hook_skipping_is_denied(self):
        self.assert_denied(self.bash("git commit --no-verif -m x"), "skip git's hooks")
        self.assert_denied(self.bash("git push --no-verif origin feature"), "skip git's hooks")
        self.assert_denied(self.bash("git -c core.hooksPath=/dev/null commit -m x"), "may not be redirected")

    def test_push_flags_that_reach_the_default_branch_are_denied(self):
        self.assert_denied(self.bash("git push --all origin"), "every branch")
        self.assert_denied(self.bash("git push --mirror origin"), "deletes or overwrites")
        self.assert_denied(self.bash("git push --forc origin feature"), "force-pushes")
        self.git("checkout", "-q", "master")
        self.assert_denied(self.bash("git push -o ci.skip origin"), "default branch")
        self.assert_denied(self.bash("git push --push-option ci.skip origin"), "default branch")
        self.assert_denied(self.bash("git push --delete origin master"), "default branch")

    def test_option_values_are_not_read_as_flags(self):
        for command in ("git commit -m '- add thing'", "git commit -m 'no flags here' -uno", "git commit -F notes.txt", "git push -o ci.skip origin feature"):
            with self.subTest(command):
                self.assert_allowed(self.bash(command))

    def test_path_rules_ignore_case(self):
        for path in (".CLAUDE/settings.json", "claude.md", ".ENV", "UV.LOCK"):
            with self.subTest(path):
                self.assertEqual(self.edit(path, subagent=True).returncode, 2)

    def test_the_git_file_of_a_linked_worktree_is_protected(self):
        self.assert_denied(self.edit(".claude/worktrees/task-1/.git", subagent=True), "agent configuration")

    def test_the_guards_own_files_are_protected_wherever_the_plugin_lives(self):
        for name in ("hooks/monerex_hook.py", "githooks/monerex_scan.py", "scripts/check.py", "routing/routing.json"):
            with self.subTest(name):
                path = os.path.join(ROOT, name)
                self.assert_denied(self.edit(path, subagent=True), "part of the guards themselves")
                self.assert_asked(self.edit(path), "part of the guards themselves")

    def test_an_invalid_denylist_line_stops_everything_instead_of_disabling_the_list(self):
        with open(self.env["MONEREX_DENYLIST"], "a", encoding="utf-8") as handle:
            handle.write("re:acme(\n")
        self.assert_denied(self.bash("echo " + TERM), "not a valid pattern")
        self.assert_denied(self.edit("notes.md", content=TERM), "not a valid pattern")
        self.assert_denied(self.bash("ls"), "not a valid pattern")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any file")
    def test_a_denylist_that_cannot_be_read_stops_the_guards(self):
        os.chmod(self.env["MONEREX_DENYLIST"], 0)
        self.addCleanup(os.chmod, self.env["MONEREX_DENYLIST"], 0o600)
        self.assert_denied(self.edit("notes.md", content="hello"), "cannot be read")
        self.assert_denied(self.bash("ls"), "cannot be read")
        self.assert_denied(self.web(query="interquartile mean"), "cannot be read")
        self.git("config", "monerex.requireDenylist", "false")  # "I keep no denylist", as in the git guards
        self.assert_allowed(self.edit("notes.md", content="hello"))
        self.assert_allowed(self.bash("ls"))

    def test_the_session_root_is_guarded_when_a_call_runs_elsewhere(self):
        env = dict(self.env, CLAUDE_PROJECT_DIR=self.repo)
        data = {"cwd": self.tmp, "agent_id": "a1", "tool_input": {"file_path": os.path.join(self.repo, ".claude", "settings.json")}}
        done = subprocess.run([sys.executable, "-I", HOOK, "pre-edit"], input=json.dumps(data), cwd=self.tmp, env=env, capture_output=True, text=True)
        self.assert_denied(done, "agent configuration")
        data = {"cwd": self.tmp, "tool_input": {"command": "git -C %s push -f origin feature" % self.repo}}
        done = subprocess.run([sys.executable, "-I", HOOK, "pre-bash"], input=json.dumps(data), cwd=self.tmp, env=env, capture_output=True, text=True)
        self.assert_denied(done, "force-pushes")

    # ------------------------------------------------------------ web

    def test_an_ordinary_web_request_is_allowed(self):
        self.assert_allowed(self.web(query="interquartile mean reinforcement learning", subagent=True))
        self.assert_allowed(self.web(url="https://arxiv.org/abs/2108.13264", prompt="Quote the sentence that names the metric."))

    def test_a_web_request_with_a_denylisted_term_is_denied_without_echoing_it(self):
        for fields in ({"query": "who owns " + TERM}, {"url": "https://example.invalid/?q=" + TERM}, {"url": "https://example.invalid/", "prompt": TERM.upper()}):
            with self.subTest(sorted(fields)):
                done = self.web(**fields)
                self.assert_denied(done, "denylisted term")
                self.assertIn("Nothing was sent", done.stderr)
                self.assertNotIn(TERM, done.stderr.lower())

    def test_a_web_request_carrying_a_secret_is_denied(self):
        key = "AKIA" + "ABCDEFGHIJKLMNOP"
        self.assert_denied(self.web(url="https://example.invalid/?k=" + key, subagent=True), "possible secret")
        self.assert_denied(self.web(query="why does token %s fail" % key), "possible secret")
        self.assert_denied(self.web(query="why does token %s fail  # monerex:allow" % key), "possible secret")

    # ------------------------------------------------------------ session and task start

    def test_a_new_session_is_told_that_the_loop_applies(self):
        done = self.run_hook("session-start", source="startup")
        self.assertEqual(done.returncode, 0, done.stderr)
        added = json.loads(done.stdout)["hookSpecificOutput"]
        self.assertEqual(added["hookEventName"], "SessionStart")
        self.assertIn("monerex:start", added["additionalContext"])
        self.assertIn("another monerex command", added["additionalContext"])

    def test_a_repository_can_ask_for_the_loop_only_when_typed(self):
        self.configure({"engage": "typed"})
        self.assert_allowed(self.run_hook("session-start", source="startup"))

    def test_a_repository_without_monerex_is_told_nothing(self):
        self.git("rm", "-q", "--cached", ".monerex/config.json")
        os.remove(os.path.join(self.repo, ".monerex", "config.json"))
        self.assert_allowed(self.run_hook("session-start", source="startup"))

    def tasks_logged(self):
        path = os.path.join(self.repo, ".monerex", "log", "tasks.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def test_writing_a_plan_starts_the_task_in_the_log_when_nobody_did(self):
        plan = "# Plan: add export\n\n- **Tier:** T2\n- **Risk flags:** none\n"
        self.assert_allowed(self.edit("docs/work/add-export/plan.md", content=plan))
        records = self.tasks_logged()
        self.assertEqual([(r["task"], r["event"], r["tier"]) for r in records], [("add-export", "start", "T2")])
        self.assert_allowed(self.edit("docs/work/add-export/plan.md", content=plan + "more\n"))
        self.assertEqual(len(self.tasks_logged()), 1, "a task that was started is not started twice")

    def test_editing_the_plan_of_a_finished_task_starts_nothing(self):
        self.put("docs/work/add-export/plan.md", "# Plan\n\n- **Tier:** T2\n")
        for args in (("start", "--slug", "add-export", "--tier", "T2"), ("done",)):
            subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "task.py"), "event", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)
        self.assert_allowed(self.edit("docs/work/add-export/plan.md", old_string="x", new_string="## Result"))
        self.assertEqual([r["event"] for r in self.tasks_logged()], ["start", "done"])

    def test_a_new_plan_starts_its_task_even_when_an_abandoned_one_is_still_open(self):
        subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "task.py"), "event", "start", "--slug", "abandoned", "--tier", "T1"],
                       cwd=self.repo, env=self.env, capture_output=True, check=True)
        self.assert_allowed(self.edit("docs/work/next-one/plan.md", content="# Plan\n\n- **Tier:** T0\n"))
        self.assertEqual([(r["task"], r["tier"]) for r in self.tasks_logged()], [("abandoned", "T1"), ("next-one", "T0")])

    def test_an_edit_reads_the_tier_from_the_file_as_it_stands(self):
        self.put("docs/work/big-one/plan.md", "# Plan: <short title>\n\n- **Tier:** T2\n")  # copied from the template by a shell command
        self.assert_allowed(self.edit("docs/work/big-one/plan.md", old_string="<short title>", new_string="big one"))
        self.assertEqual([(r["task"], r["tier"]) for r in self.tasks_logged()], [("big-one", "T2")])

    def test_an_intent_file_starts_a_feature_sized_task_and_other_files_start_nothing(self):
        self.assert_allowed(self.edit("docs/notes.md", content="hello"))
        self.assert_allowed(self.edit("docs/work/Bad Name/plan.md", content="x"))
        self.assertEqual(self.tasks_logged(), [])
        self.assert_allowed(self.edit("docs/work/accounts/intent.md", content="# Intent: accounts\n"))
        self.assertEqual([(r["task"], r["tier"]) for r in self.tasks_logged()], [("accounts", "T2")])

    # ------------------------------------------------------------ logs

    def test_agent_starts_are_logged(self):
        done = self.run_hook("agent-log", subagent=True, hook_event_name="SubagentStart")
        self.assert_allowed(done)
        with open(os.path.join(self.repo, ".monerex", "log", "routing.jsonl"), encoding="utf-8") as handle:
            record = json.loads(handle.readline())
        self.assertEqual(record["agent_type"], "monerex:implementer")
        self.assertEqual(record["hook_event_name"], "SubagentStart")

    def commits_logged(self):
        path = os.path.join(self.repo, ".monerex", "log", "commits.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def test_a_commit_made_through_the_shell_is_logged_with_its_session_and_agents(self):
        self.run_hook("agent-log", subagent=True, hook_event_name="SubagentStop", effort={"level": "medium"})
        self.put("b.txt", "more\n")
        self.git("add", "b.txt")
        self.git("commit", "-q", "-m", "second")
        self.assert_allowed(self.run_hook("commit-log", {"command": "git add b.txt && git commit -q -m second"}))
        self.assert_allowed(self.run_hook("commit-log", {"command": "git commit -q -m again"}))  # nothing new: one line
        self.assert_allowed(self.run_hook("commit-log", {"command": "ls"}))
        records = self.commits_logged()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual((record["paths"], record["branch"], record["session_id"]), (["b.txt"], "feature", "s1"))
        self.assertEqual((record["by"], record["agents"]), ("main session", ["monerex:implementer/medium"]))

    def test_a_command_that_does_not_commit_logs_nothing(self):
        self.assert_allowed(self.run_hook("commit-log", {"command": "git status && git log -1 && ls"}))
        self.assertEqual(self.commits_logged(), [])

    def test_a_commit_in_a_repository_that_has_not_opted_in_leaves_nothing_there(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        for args in (("init", "-q"), ("config", "user.name", "T"), ("config", "user.email", "t@example.invalid"),
                     ("commit", "-q", "--allow-empty", "-m", "theirs")):
            subprocess.run(["git", *args], cwd=other, env=self.env, capture_output=True, check=True)
        self.assert_allowed(self.run_hook("commit-log", {"command": "git -C %s commit -q -m theirs" % other}))
        self.assertFalse(os.path.exists(os.path.join(other, ".monerex")))
        self.assertEqual(self.commits_logged(), [])

    def test_a_commit_the_call_did_not_make_is_not_logged(self):
        old = dict(self.env, GIT_COMMITTER_DATE="2001-01-01T00:00:00", GIT_AUTHOR_DATE="2001-01-01T00:00:00")
        self.put("b.txt", "more\n")
        self.git("add", "b.txt")
        subprocess.run(["git", "commit", "-q", "-m", "long ago"], cwd=self.repo, env=old, capture_output=True, check=True)
        self.assert_allowed(self.run_hook("commit-log", {"command": "git commit -m 'this one failed'"}))
        self.assertEqual(self.commits_logged(), [])

    def test_the_effort_an_agent_ran_at_is_logged_when_it_stops(self):
        self.run_hook("agent-log", subagent=True, hook_event_name="SubagentStop", effort={"level": "medium"})
        with open(os.path.join(self.repo, ".monerex", "log", "routing.jsonl"), encoding="utf-8") as handle:
            self.assertEqual(json.loads(handle.readline())["effort"], "medium")

    def test_the_dispatch_log_points_at_the_agents_transcript(self):
        self.run_hook("agent-log", subagent=True, hook_event_name="SubagentStop", agent_transcript_path="/somewhere/agent.jsonl")
        with open(os.path.join(self.repo, ".monerex", "log", "routing.jsonl"), encoding="utf-8") as handle:
            self.assertEqual(json.loads(handle.readline())["agent_transcript_path"], "/somewhere/agent.jsonl")


if __name__ == "__main__":
    unittest.main()
