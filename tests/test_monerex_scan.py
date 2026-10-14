"""The git guards, driven through real git hooks in throwaway repositories.

Run with: python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest

GITHOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "githooks")

# A made-up term, and secrets and invisible characters assembled at run time so
# that this file stays clean.
TERM = "zorblatt-industries"
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
FAKE_PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
BIDI_OVERRIDE = chr(0x202E)
TAG_CHARACTER = chr(0xE0041)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="monerex-guard-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        self.denylist = os.path.join(self.tmp, "denylist.txt")
        with open(self.denylist, "w", encoding="utf-8") as handle:
            handle.write("# private\n" + TERM + "\nre:acme[ -]?corp\n")
        self.env = dict(os.environ, MONEREX_DENYLIST=self.denylist, HOME=self.tmp)
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.env.pop(name, None)
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        installed = subprocess.run(
            ["sh", os.path.join(GITHOOKS, "install.sh")], cwd=self.repo, env=self.env, capture_output=True, text=True
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)

    def git(self, *args, check=True, cwd=None):
        done = subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)
        if check and done.returncode != 0:
            self.fail("git %s failed: %s" % (" ".join(args), done.stderr))
        return done

    def write(self, name, text):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.git("add", "--", name)

    def commit(self, message="add a file", *flags):
        return self.git("commit", "-q", "-m", message, *flags, check=False)

    def assert_blocked(self, done, rule):
        self.assertNotEqual(done.returncode, 0, "expected the guard to block")
        self.assertIn(rule, done.stderr)

    def test_clean_commit_passes(self):
        self.write("a.txt", "hello\n")
        self.assertEqual(self.commit().returncode, 0)

    def test_term_in_content_is_blocked_without_echoing_it(self):
        self.write("a.txt", "one\nmade for Zorblatt-Industries\n")
        done = self.commit()
        self.assert_blocked(done, "a.txt:2: denylisted term (denylist line 2)")
        self.assertNotIn(TERM, done.stderr.lower())

    def test_regex_entry_matches(self):
        self.write("a.txt", "from Acme Corp with love\n")
        self.assert_blocked(self.commit(), "denylist line 3")

    def test_term_in_message_is_blocked(self):
        self.write("a.txt", "hello\n")
        self.assert_blocked(self.commit("fix for " + TERM), "commit message line 1: denylisted term")

    def test_term_in_path_is_blocked_and_redacted(self):
        self.write(TERM + "/notes.txt", "hello\n")
        done = self.commit()
        self.assert_blocked(done, "path [term]/notes.txt: denylisted term")
        self.assertNotIn(TERM, done.stderr.lower())

    def test_term_in_branch_name_is_blocked(self):
        self.write("a.txt", "hello\n")
        self.assertEqual(self.commit().returncode, 0)
        self.git("checkout", "-q", "-b", "feature/" + TERM)
        self.write("b.txt", "hello\n")
        self.assert_blocked(self.commit(), "branch name: denylisted term")

    def test_added_line_that_looks_like_a_diff_header_is_scanned(self):
        self.write("a.txt", "++ " + TERM + "\n")
        self.assert_blocked(self.commit(), "a.txt:1: denylisted term")

    def test_secret_is_blocked_and_can_be_accepted_on_the_line(self):
        self.write("a.txt", "key = " + FAKE_KEY + "\n")
        done = self.commit()
        self.assert_blocked(done, "possible secret (cloud access key id)")
        self.assertIn("monerex:allow", done.stderr)  # the way to accept a false positive is named
        self.write("a.txt", "key = " + FAKE_KEY + "  # monerex:allow test fixture\n")
        self.assertEqual(self.commit().returncode, 0)

    def test_private_key_header_is_blocked(self):
        self.write("id_rsa", FAKE_PRIVATE_KEY + "\n")
        self.assert_blocked(self.commit(), "possible secret (private key block)")

    def test_allow_marker_does_not_accept_a_term(self):
        self.write("a.txt", TERM + "  # monerex:allow\n")
        self.assert_blocked(self.commit(), "denylisted term")

    def test_hidden_characters_are_blocked(self):
        for name, character in (("bidi.txt", BIDI_OVERRIDE), ("tag.txt", TAG_CHARACTER)):
            with self.subTest(name):
                self.write(name, "plain" + character + "text\n")
                self.assert_blocked(self.commit(), "hidden or bidirectional Unicode character")
                self.git("reset", "-q", "--", name)

    def test_leading_byte_order_mark_is_allowed(self):
        self.write("a.txt", chr(0xFEFF) + "hello\n")
        self.assertEqual(self.commit().returncode, 0)

    def test_missing_denylist_warns_by_default(self):
        os.remove(self.denylist)
        self.write("a.txt", "hello\n")
        done = self.commit()
        self.assertEqual(done.returncode, 0)
        self.assertIn("no denylist at", done.stderr)

    def test_missing_or_empty_denylist_blocks_when_required(self):
        self.git("config", "monerex.requireDenylist", "true")
        self.write("a.txt", "hello\n")
        with open(self.denylist, "w", encoding="utf-8") as handle:
            handle.write("# nothing yet\n")
        self.assert_blocked(self.commit(), "has no entries")
        os.remove(self.denylist)
        self.assert_blocked(self.commit(), "no denylist at")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads any file")
    def test_a_denylist_that_cannot_be_read_blocks_unless_the_repository_says_it_has_none(self):
        os.chmod(self.denylist, 0)
        self.addCleanup(os.chmod, self.denylist, 0o600)
        self.write("a.txt", "made for " + TERM + "\n")
        self.assert_blocked(self.commit(), "cannot be read")
        self.git("config", "monerex.requireDenylist", "true")
        self.assert_blocked(self.commit(), "cannot be read")
        self.git("config", "monerex.requireDenylist", "false")
        done = self.commit()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("cannot be read; checking secrets", done.stderr)

    def test_an_invalid_denylist_line_blocks_instead_of_disabling_the_list(self):
        with open(self.denylist, "a", encoding="utf-8") as handle:
            handle.write("re:acme(\n")
        self.write("a.txt", "hello\n")
        self.assert_blocked(self.commit(), "line 4 of the denylist is not a valid pattern")

    def test_a_message_line_that_starts_with_a_hash_is_scanned(self):
        self.write("a.txt", "hello\n")
        self.assert_blocked(self.commit("#12 fix for " + TERM), "commit message line 1: denylisted term")

    def test_the_diff_shown_by_a_verbose_commit_is_not_part_of_the_message(self):
        self.write("a.txt", "hello\n")
        self.assertEqual(self.commit().returncode, 0)
        message = os.path.join(self.tmp, "message.txt")
        with open(message, "w", encoding="utf-8") as handle:
            handle.write("tidy up\n# ------------------------ >8 ------------------------\n-" + TERM + "\n")
        scanned = subprocess.run(
            ["python3", "-I", os.path.join(GITHOOKS, "monerex_scan.py"), "commit-msg", message],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(scanned.returncode, 0, scanned.stderr)

    def test_common_credential_names_are_caught(self):
        value = "A1b2C3d4E5f6G7h8I9j0K1l2"
        samples = (
            'client_secret = "%s"', "OPENAI_API_KEY=%s", 'db_password: "%s"', "auth_token = '%s'", '"api_key": "%s"', "SECRET_KEY=%s",
        )
        for number, sample in enumerate(samples):
            with self.subTest(sample):
                name = "c%d.txt" % number
                self.write(name, sample % value + "\n")
                self.assert_blocked(self.commit(), "possible secret (hard-coded credential)")
                self.git("reset", "-q", "--", name)

    def test_ordinary_assignments_are_not_credentials(self):
        self.write("a.py", "token = read_the_token_from_the_environment()\npassword_field = build_password_field\n")
        self.assertEqual(self.commit().returncode, 0)

    def test_a_forced_push_over_an_unfetched_remote_tip_is_still_scanned(self):
        self.push_setup()
        other = os.path.join(self.tmp, "other")
        self.git("clone", "-q", "-b", "main", os.path.join(self.tmp, "remote.git"), other, cwd=self.tmp)
        for key, value in (("user.name", "Other"), ("user.email", "other@example.invalid")):
            self.git("config", key, value, cwd=other)
        with open(os.path.join(other, "theirs.txt"), "w", encoding="utf-8") as handle:
            handle.write("theirs\n")
        self.git("add", "theirs.txt", cwd=other)
        self.git("commit", "-q", "-m", "theirs", cwd=other)
        self.git("push", "-q", "origin", "main", cwd=other)
        self.write("b.txt", TERM + "\n")
        self.assertEqual(self.commit("add b", "--no-verify").returncode, 0)
        done = self.git("push", "-q", "--force", "origin", "main", check=False)
        self.assert_blocked(done, "b.txt:1: denylisted term")

    def push_setup(self):
        remote = os.path.join(self.tmp, "remote.git")
        self.git("init", "-q", "--bare", remote, cwd=self.tmp)
        self.git("remote", "add", "origin", remote)
        self.write("a.txt", "hello\n")
        self.assertEqual(self.commit().returncode, 0)
        # The first push of a new repository is the owner's, made with the override.
        done = self.git("-c", "monerex.allowDefaultPush=1", "push", "-q", "origin", "main", check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_push_to_the_default_branch_is_refused_whatever_spells_it(self):
        self.push_setup()
        self.git("checkout", "-q", "-b", "topic")
        self.write("b.txt", "hello\n")
        self.assertEqual(self.commit("add b").returncode, 0)
        self.assertEqual(self.git("push", "-q", "origin", "topic", check=False).returncode, 0)
        for args in (
            ("push", "-q", "origin", "topic:main"),
            ("push", "-q", "origin", "HEAD:refs/heads/main"),
            ("push", "-q", "origin", "+topic:main"),
            ("push", "-q", "origin", ":main"),
            ("push", "-q", "--delete", "origin", "main"),
            ("-c", "push.default=upstream", "-c", "branch.topic.remote=origin", "-c", "branch.topic.merge=refs/heads/main", "push", "-q", "origin"),
        ):
            with self.subTest(args=args):
                self.assert_blocked(self.git(*args, check=False), "default branch")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--ff-only", "topic")
        for args in (("push", "-q", "origin", "main"), ("push", "-q", "--all", "origin"), ("-c", "push.default=current", "push", "-q", "origin")):
            with self.subTest(args=args):
                self.assert_blocked(self.git(*args, check=False), "default branch")
        self.assertEqual(self.git("ls-remote", "origin", "refs/heads/main").stdout.split()[0], self.git("rev-parse", "main~1").stdout.strip())

    def test_the_owners_override_counts_only_on_the_command_line(self):
        self.push_setup()
        self.write("b.txt", "hello\n")
        self.assertEqual(self.commit("add b").returncode, 0)
        self.git("config", "monerex.allowDefaultPush", "true")  # saved in the repository: not honoured
        self.assert_blocked(self.git("push", "-q", "origin", "main", check=False), "default branch")
        done = self.git("-c", "monerex.allowDefaultPush=1", "push", "-q", "origin", "main", check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        # The override lets the branch through, not the content.
        self.write("c.txt", TERM + "\n")
        self.assertEqual(self.commit("add c", "--no-verify").returncode, 0)
        self.assert_blocked(self.git("-c", "monerex.allowDefaultPush=1", "push", "-q", "origin", "main", check=False), "denylisted term")

    def test_the_default_branch_is_main_master_and_what_the_remote_names(self):
        self.push_setup()
        self.git("checkout", "-q", "-b", "trunk")
        self.assertEqual(self.git("-c", "monerex.allowDefaultPush=1", "push", "-q", "origin", "trunk", check=False).returncode, 0)
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.write("b.txt", "hello\n")
        self.assertEqual(self.commit("add b").returncode, 0)
        for target in ("trunk", "main", "master"):
            with self.subTest(target=target):
                self.assert_blocked(self.git("push", "-q", "origin", "HEAD:" + target, check=False), "default branch")
        self.assertEqual(self.git("push", "-q", "origin", "HEAD:refs/heads/topic", check=False).returncode, 0)

    def test_push_blocks_a_term_committed_past_the_commit_hooks(self):
        self.push_setup()
        self.write("b.txt", TERM + "\n")
        self.assertEqual(self.commit("add b", "--no-verify").returncode, 0)
        done = self.git("push", "-q", "origin", "main", check=False)
        self.assert_blocked(done, "b.txt:1: denylisted term")
        self.assertIn("Nothing was pushed", done.stderr)

    def test_push_blocks_a_term_that_a_later_commit_removed(self):
        self.push_setup()
        self.write("b.txt", TERM + "\n")
        self.assertEqual(self.commit("add b", "--no-verify").returncode, 0)
        self.write("b.txt", "clean\n")
        self.assertEqual(self.commit("clean b").returncode, 0)
        self.assert_blocked(self.git("push", "-q", "origin", "main", check=False), "denylisted term")

    def test_push_blocks_a_term_in_a_new_branch_name_and_message(self):
        self.push_setup()
        self.git("checkout", "-q", "-b", "topic")
        self.write("c.txt", "hello\n")
        self.assertEqual(self.commit("for " + TERM, "--no-verify").returncode, 0)
        self.assert_blocked(self.git("push", "-q", "origin", "topic", check=False), "message line 1: denylisted term")
        self.assert_blocked(
            self.git("push", "-q", "origin", "main:refs/heads/" + TERM, check=False), "pushed ref name: denylisted term"
        )

    def test_push_blocks_a_term_in_the_remote_url(self):
        self.push_setup()
        other = os.path.join(self.tmp, TERM + ".git")
        self.git("init", "-q", "--bare", other, cwd=self.tmp)
        self.git("remote", "add", "work", other)
        self.assert_blocked(self.git("push", "-q", "work", "main", check=False), "remote URL: denylisted term")

    def test_a_default_branch_recorded_at_install_holds_without_the_remote_head(self):
        # Found by review: a default branch named other than main or master was known only
        # through origin/HEAD, which `git remote set-head origin -d` removes.
        self.push_setup()
        self.git("checkout", "-q", "-b", "trunk")
        self.assertEqual(self.git("-c", "monerex.allowDefaultPush=1", "push", "-q", "origin", "trunk", check=False).returncode, 0)
        self.git("fetch", "-q", "origin")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        installed = subprocess.run(
            ["sh", os.path.join(GITHOOKS, "install.sh")], cwd=self.repo, env=self.env, capture_output=True, text=True
        )
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(self.git("config", "--get", "monerex.defaultBranch").stdout.strip(), "trunk")
        self.git("symbolic-ref", "-d", "refs/remotes/origin/HEAD")
        self.write("b.txt", "hello\n")
        self.assertEqual(self.commit("add b").returncode, 0)
        done = self.git("push", "-q", "origin", "HEAD:trunk", check=False)
        self.assert_blocked(done, "default branch")
        # The footer about accepting a false positive belongs to secrets, not to this rule.
        self.assertNotIn("monerex:allow", done.stderr)

    def test_install_leaves_a_foreign_hook_alone(self):
        hook = os.path.join(self.repo, ".git", "hooks", "pre-commit")
        with open(hook, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\nexit 0\n")
        done = subprocess.run(
            ["sh", os.path.join(GITHOOKS, "install.sh")], cwd=self.repo, env=self.env, capture_output=True, text=True
        )
        self.assertEqual(done.returncode, 1)
        with open(hook, encoding="utf-8") as handle:
            self.assertNotIn("monerex_scan.py", handle.read())


if __name__ == "__main__":
    unittest.main()
