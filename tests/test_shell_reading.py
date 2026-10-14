"""The guard's reading of a command, held against what a real shell runs.

Every fault found in the shell rules so far was a difference between the two: a line joined
by a backslash, a comment, a quoted separator, a redirection between two words. Each was
found by somebody reading the code. This test runs the comparison instead. A real `sh` runs
each command with stand-ins for `git` and `gh` that only write down their arguments, and
every call the shell made must be among the commands the guard would have judged.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hooks"))

import monerex_hook  # noqa: E402

STAND_IN = """#!/bin/sh
# Writes down one call: the name it was called by, then each argument, one JSON list a line.
python3 -I -c 'import json, os, sys; print(json.dumps([os.path.basename(sys.argv[1])] + sys.argv[2:]))' "$0" "$@" >> "$CALLS"
"""

BASES = [
    "git push origin master",
    "git push --force origin feature",
    "git push origin feature",
    "gh pr merge 12 --repo o/r",
    "git commit --no-verify -m msg",
]


def shapes(base):
    """The base command in the forms an agent types, and the ones reviews found faults in."""
    words = base.split(" ")
    yield base
    yield base + " 2>&1"
    yield base + " > out.txt 2>/dev/null"
    yield base + " >| out.txt"
    yield " ".join(words[:1] + ["2>&1"] + words[1:])
    yield " ".join(words[:2] + ["> out.txt"] + words[2:])
    yield "echo hi; " + base
    yield "echo hi && " + base
    yield "echo hi\n" + base
    yield "# a note\n" + base
    yield "# don't do this\n" + base + " # it's fine"
    yield base + " # then; echo later"
    yield "echo a # (b) | c\n" + base
    yield "# a note \\\n" + base
    yield words[0] + " \\\n" + " ".join(words[1:])
    yield " \\\n  ".join(words)
    yield "true \\\n# a note\n" + base
    yield "echo a\\\n#b; " + base
    yield "echo \\ #x; " + base
    yield 'echo ok ""#; ' + base
    yield "echo '#'; " + base
    yield "echo ';' ; " + base
    yield "echo 'a; b' '&&' c; " + base
    yield 'echo "one\ntwo"; ' + base
    yield "echo 'one\n# two'; " + base
    yield "eval " + base
    yield 'eval "' + base + '"'
    yield "eval " + base + " ';' echo done"
    yield "eval echo hi ';' " + base
    yield "sh -c '" + base + "'"
    yield "sh -c 'echo hi; " + base + "'"
    yield "(" + base + ")"
    yield "(" + base + ")>out.txt"
    yield "{ " + base + "; }"
    yield "FOO=1 " + base
    yield "if true; then " + base + "; fi"
    yield "for i in 1; do " + base + "; done"
    yield "echo x | cat; " + base
    yield "command " + base
    yield "echo hi > '#out'; " + base
    # A wrapper spelled as a path, and the words after `echo`, which are text.
    yield "/usr/bin/env " + base
    yield "/usr/bin/env FOO=1 " + base
    yield "echo sh -c hi; " + base
    yield "echo eval hi && " + base
    # A shell given a long option with one dash, which bash takes: it must not hide the script.
    yield "bash -noprofile -lc '" + base + "'"
    yield "bash -noprofile -norc -ec '" + base + "'"
    # A heredoc is data for the command it is given to.
    yield "cat <<'EOF' > /dev/null\n" + base + "\nEOF\n" + base


class ShellReadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-shell-"))
        cls.bin = os.path.join(cls.tmp, "bin")
        os.makedirs(cls.bin)
        for name in ("git", "gh"):
            path = os.path.join(cls.bin, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(STAND_IN)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        cls.calls = os.path.join(cls.tmp, "calls.jsonl")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ran(self, command):
        """What a real shell called `git` and `gh` with."""
        if os.path.exists(self.calls):
            os.remove(self.calls)
        work = tempfile.mkdtemp(dir=self.tmp)
        env = {"PATH": self.bin + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "CALLS": self.calls, "HOME": self.tmp}
        subprocess.run(["sh", "-c", command], cwd=work, env=env, capture_output=True, timeout=20)
        if not os.path.exists(self.calls):
            return []
        with open(self.calls, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def judged(self, command):
        """Every `git ...` and `gh ...` word list the guard reads as a command.

        A `git` word that is only text (after `echo`) is judged by the guard's rules too, but a
        checkout is recorded only where git is the command, so the calls a shell makes have to
        be among those. The guard's own function says which: it is the one `pre_bash` uses.
        """
        found = []
        for words, is_command in monerex_hook.invocations(command):
            if is_command:
                words = [monerex_hook.unmarked(word) for word in words]
                found.append([os.path.basename(words[0])] + words[1:])
        return found

    def test_the_guard_judges_every_call_a_real_shell_makes(self):
        checked = 0
        for base in BASES:
            for command in shapes(base):
                with self.subTest(command=command):
                    ran, judged = self.ran(command), self.judged(command)
                    for call in ran:
                        self.assertIn(call, judged, "the shell ran this and the guard did not see it")
                    checked += 1
        self.assertGreater(checked, 150)

    def test_commands_inside_a_shell_come_out_in_the_order_the_shell_runs_them(self):
        # The guard follows a checkout into the push after it, so the order of two calls is part
        # of what it reads. Every shape has two calls and a shell that runs them one after the
        # other; what the guard judges must be those calls, in that order, as the real shell made them.
        for command in (
            "sh -c 'git checkout master' && git push",
            "git checkout master && sh -c 'git push'",
            "sh -c 'git push' && git checkout master",
            "sh -c 'git checkout master'; sh -c 'git push'",
            "sh -c 'git checkout master && git push' && git status",
            "git status && sh -c 'git checkout master && git push'",
            "eval 'git checkout master' && git push",
            "eval 'git push' && git checkout master",
            "eval 'git checkout master'; eval 'git push'",
            "eval git checkout master ';' git push",
            "true && eval 'git checkout master' && git push",
            "sh -c 'sh -c \"git checkout master\"' && git push",
            "bash -c 'git checkout master' && bash -c 'git push'",
            # Flags bundled with the `c`, and another flag or `--` before the script. A login
            # shell is left out unless it skips the profile: `/etc/profile` on macOS puts the
            # stand-ins behind `/usr/bin`, and the shell would then run another `git`.
            "bash -ec 'git checkout master' && git push",
            "sh -ec 'git checkout master && git push'",
            "bash -c -- 'git checkout master' && git push",
            "bash -c -x 'git checkout master' && git push",
            "bash -o pipefail -c 'git checkout master' && git push",
            "bash --noprofile --norc -lc 'git push' && git checkout master",
            # A wrapper spelled as a path is the wrapper; the same call is not text after `echo`.
            "/usr/bin/env git checkout master && git push",
            "/usr/bin/env FOO=1 git checkout master && git push",
            "echo eval git checkout master && git push",
            "echo sh -c 'git checkout master' && git push",
            # bash takes a long option with one dash, and `-noprofile` keeps the profile out of
            # the way of the stand-ins.
            "bash -noprofile -lc 'git checkout master' && git push",
            "bash -noprofile -norc -ec 'git checkout master && git push'",
            # A heredoc is data for the command it is given to: what is in it is not run.
            "cat <<'EOF' > /dev/null\ngit checkout master\nEOF\ngit push",
            "cat <<EOF > /dev/null\nsh -c 'git checkout master'\nEOF\ngit push",
            "cat <<-EOF > /dev/null\n\tgit checkout master\n\tEOF\ngit push",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.judged(command), self.ran(command))

    def test_the_plain_forms_are_read_as_exactly_what_runs(self):
        # Seeing too much is safe but refuses honest commands: for the forms with no wrapper
        # around them the two must agree exactly.
        for base in BASES:
            for command in list(shapes(base))[:25]:
                with self.subTest(command=command):
                    self.assertEqual(self.judged(command), self.ran(command))


PUSH_STAND_IN = """#!/bin/sh
# Real git for everything but a push, which only writes down the branch HEAD is on.
if [ "$1" = push ]; then
    "$REAL_GIT" symbolic-ref --short -q HEAD >> "$PUSHES" || echo "(no branch)" >> "$PUSHES"
    exit 0
fi
exec "$REAL_GIT" "$@"
"""

# Lines whose push a real shell runs on the default branch. The second item says which repository:
# `clone` has origin/master and a tag; `fresh` has neither a local master nor origin/master, and
# an origin that a fetch brings them in from.
REACHES_THE_DEFAULT_BRANCH = [
    ("clone", "git checkout master && git merge feature && git push"),
    ("clone", "git checkout master && git push"),
    ("clone", "git switch master && git push"),
    ("clone", "git checkout feature && git checkout master && git push"),
    ("clone", "env git checkout master && git push"),
    ("clone", "command git checkout master && git push"),
    ("clone", "/usr/bin/env git checkout master && git push"),
    ("clone", "/usr/bin/env FOO=1 git switch master && git push"),
    ("clone", "git checkout master && git checkout v1.0 && git checkout - && git push"),
    ("clone", "git checkout master && git checkout HEAD~1 && git checkout - && git push"),
    ("clone", "git checkout master && git checkout origin/master && git checkout - && git push"),
    ("clone", "git checkout master && git checkout --detach && git checkout - && git push"),
    ("clone", "git checkout master && git checkout -d v1.0 && git checkout @{-1} && git push"),
    ("clone", "sh -c 'git checkout master' && git push"),
    ("clone", "eval 'git checkout master' && git push"),
    ("clone", 'bash -noprofile -lc "git checkout master && git push"'),
    ("clone", 'bash -noprofile -norc -ec "git checkout master && git push"'),
    ("fresh", "git fetch -q origin && git checkout master && git push"),
    ("fresh", "git fetch origin && git switch master && git push"),
    ("fresh", "git fetch -q origin && git checkout master && git commit --allow-empty -qm x && git push"),
]

# Lines that are only honest: the push runs on another branch, or on none.
STAYS_OFF_THE_DEFAULT_BRANCH = [
    ("clone", "git push"),
    ("clone", "git checkout feature && git push"),
    ("clone", "/usr/bin/env git checkout feature && git push"),
    ("clone", "git checkout master && git checkout feature && git push"),
    ("clone", "git checkout master && git checkout - && git push"),
    ("clone", "git checkout feature && git checkout v1.0 && git checkout - && git push"),
    ("clone", "git checkout master && git checkout v1.0 && git checkout master && git checkout - && git push"),
    ("clone", "git checkout --detach && git push"),
    ("clone", "git checkout -b other && git push"),
    ("clone", "git checkout master a.txt && git push"),
    ("clone", "echo eval git checkout master && git push"),
    ("clone", "echo sh -c 'git checkout master' && git push"),
    ("clone", "cat <<'EOF' > /dev/null\ngit checkout master\nEOF\ngit push"),
    ("clone", "cat <<'EOF' > /dev/null\nsh -c 'git checkout master'\nEOF\ngit push"),
    ("fresh", "git fetch -q origin && git checkout -b topic && git push"),
]


class HeadAtThePushTest(unittest.TestCase):
    """The guard's decision, held against where a real shell's push really runs.

    The tests above compare the calls a shell makes with the calls the guard reads. What the
    guard exists for is the branch a push runs on, and that depends on what git did to HEAD
    before it: a tag, `checkout -`, a fetch. Here real git runs everything but the push, which
    a stand-in replaces with one that writes down the branch HEAD is on. The guard is asked
    about the same line first, in the same repository, before anything has run.
    """

    DEFAULT = {"master", "main"}

    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-head-"))
        cls.real_git = shutil.which("git")
        cls.bin = os.path.join(cls.tmp, "bin")
        os.makedirs(cls.bin)
        stand_in = os.path.join(cls.bin, "git")
        with open(stand_in, "w", encoding="utf-8") as handle:
            handle.write(PUSH_STAND_IN)
        os.chmod(stand_in, os.stat(stand_in).st_mode | stat.S_IXUSR)
        denylist = os.path.join(cls.tmp, "denylist.txt")
        with open(denylist, "w", encoding="utf-8") as handle:
            handle.write("zorblatt-industries\n")
        cls.env = {
            "PATH": cls.bin + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
            "HOME": cls.tmp,
            "XDG_CONFIG_HOME": cls.tmp,
            "REAL_GIT": cls.real_git,
            "MONEREX_DENYLIST": denylist,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        cls.clone = os.path.join(cls.tmp, "clone")
        os.makedirs(os.path.join(cls.clone, ".monerex"))
        cls.git(cls.clone, "init", "-q", "-b", "master")
        cls.write(cls.clone, "a.txt", "hello\n")
        cls.git(cls.clone, "add", "a.txt")
        cls.git(cls.clone, "commit", "-q", "-m", "first")
        cls.write(cls.clone, ".monerex/config.json", "{}")
        cls.write(cls.clone, ".gitignore", ".monerex/state/\n.monerex/log/\n")
        cls.git(cls.clone, "add", ".monerex/config.json", ".gitignore")
        cls.git(cls.clone, "commit", "-q", "-m", "configure monerex")
        cls.git(cls.clone, "branch", "feature")
        cls.git(cls.clone, "tag", "v1.0")
        cls.git(cls.clone, "update-ref", "refs/remotes/origin/master", "HEAD")
        cls.git(cls.clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")
        cls.git(cls.clone, "checkout", "-q", "feature")
        # The same repository before a fetch: no master, here or as origin/master, and an origin
        # that has it.
        bare = os.path.join(cls.tmp, "origin.git")
        cls.git(cls.tmp, "clone", "-q", "--bare", cls.clone, bare)
        cls.fresh = os.path.join(cls.tmp, "fresh")
        shutil.copytree(cls.clone, cls.fresh, symlinks=True)
        cls.git(cls.fresh, "remote", "add", "origin", bare)
        cls.git(cls.fresh, "branch", "-D", "master")
        cls.git(cls.fresh, "update-ref", "-d", "refs/remotes/origin/master")
        cls.git(cls.fresh, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def git(cls, cwd, *args):
        subprocess.run([cls.real_git, *args], cwd=cwd, env=cls.env, capture_output=True, check=True)

    @staticmethod
    def write(root, name, text):
        with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def outcome(self, state, command):
        """(the guard's exit code, the branches a push ran on) for one line in one repository."""
        work = tempfile.mkdtemp(dir=self.tmp)
        repo = os.path.join(work, "repo")
        shutil.copytree(self.clone if state == "clone" else self.fresh, repo, symlinks=True)
        data = {"cwd": repo, "session_id": "s1", "tool_input": {"command": command}}
        guard = subprocess.run(
            [sys.executable, "-I", os.path.join(ROOT, "hooks", "monerex_hook.py"), "pre-bash"],
            input=json.dumps(data), cwd=repo, env=self.env, capture_output=True, text=True,
        )
        pushes = os.path.join(work, "pushes")
        subprocess.run(["sh", "-c", command], cwd=repo, env=dict(self.env, PUSHES=pushes), capture_output=True, timeout=30)
        if not os.path.exists(pushes):
            return guard.returncode, []
        with open(pushes, encoding="utf-8") as handle:
            return guard.returncode, [line.strip() for line in handle if line.strip()]

    def test_a_push_the_shell_runs_on_the_default_branch_is_refused(self):
        for state, command in REACHES_THE_DEFAULT_BRANCH:
            with self.subTest(command=command, state=state):
                code, pushed = self.outcome(state, command)
                self.assertTrue(set(pushed) & self.DEFAULT, "the line does not push on the default branch: %r" % pushed)
                self.assertEqual(code, 2, "the shell pushed on %s and the guard did not refuse it" % pushed)

    def test_a_push_the_shell_runs_on_another_branch_is_not_refused(self):
        for state, command in STAYS_OFF_THE_DEFAULT_BRANCH:
            with self.subTest(command=command, state=state):
                code, pushed = self.outcome(state, command)
                self.assertTrue(pushed and not set(pushed) & self.DEFAULT, "the line pushes on the default branch: %r" % pushed)
                self.assertEqual(code, 0, "the shell pushed on %s and the guard refused it" % pushed)


if __name__ == "__main__":
    unittest.main()
