"""The tree audit: what is already tracked, not what a commit adds."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, "scripts", "audit.py")
TERM = "zorblatt-industries"
FAKE_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
HIDDEN = chr(0x202E)
SHA = "0123456789abcdef0123456789abcdef01234567"


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="monerex-audit-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.denylist = os.path.join(self.tmp, "denylist.txt")
        with open(self.denylist, "w", encoding="utf-8") as handle:
            handle.write(TERM + "\n")
        self.env = dict(os.environ, MONEREX_DENYLIST=self.denylist, HOME=self.tmp)
        for name in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            self.env.pop(name, None)
        for args in (("init", "-q"), ("config", "user.name", "T"), ("config", "user.email", "t@example.invalid")):
            subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def track(self, name, data):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        subprocess.run(["git", "add", "--", name], cwd=self.repo, env=self.env, capture_output=True, check=True)

    def audit(self, cwd=None, env=None):
        done = subprocess.run([sys.executable, "-I", AUDIT, "--json"], cwd=cwd or self.repo, env=env or self.env, capture_output=True, text=True)
        return done, json.loads(done.stdout)

    def rules(self, result):
        return sorted((finding["where"], finding["rule"].split(" (")[0]) for finding in result["findings"])

    def test_a_clean_tree_is_clean(self):
        self.track("a.py", "print('hello')\n")
        self.track(".github/workflows/ci.yml", "steps:\n  - uses: someone/thing@%s\n  - uses: ./local\n  - run: make test\n  # - uses: old/thing@v1\n" % SHA)
        done, result = self.audit()
        self.assertEqual((done.returncode, result["clean"], result["files"], result["not_read"]), (0, True, 2, []))

    def test_what_is_already_tracked_is_found_without_being_echoed(self):
        self.track("notes.md", "one\nfor " + TERM + "\n")
        self.track("config.py", "key = '" + FAKE_KEY + "'\n")
        self.track("readme.txt", "plain" + HIDDEN + "text\n")
        self.track(TERM + "/x.txt", "fine\n")
        self.track("crlf.txt", "a\r\nkey = " + FAKE_KEY + "\r\n")
        self.track("wide.txt", ("key = " + FAKE_KEY + "\n").encode("utf-16"))
        done, result = self.audit()
        self.assertEqual(done.returncode, 1)
        self.assertNotIn(TERM, done.stdout.lower())
        self.assertNotIn(FAKE_KEY, done.stdout)
        self.assertEqual(self.rules(result), [
            ("config.py:1", "possible secret"),
            ("crlf.txt:2", "possible secret"),
            ("notes.md:2", "denylisted term"),
            ("path [term]/x.txt", "denylisted term"),
            ("readme.txt:1", "hidden or bidirectional Unicode character"),
            ("wide.txt:1", "possible secret"),
        ])

    def test_a_term_in_a_path_is_cut_out_of_every_line_that_names_the_path(self):
        self.track(".github/workflows/" + TERM + ".yml", "steps:\n  - uses: actions/checkout@v4\n")
        self.track(TERM + "/uv.lock", "x\n")
        done, result = self.audit()
        self.assertNotIn(TERM, done.stdout.lower())
        self.assertIn((".github/workflows/[term].yml:2", "an action from outside that is not pinned to a commit hash"), self.rules(result))
        if not shutil.which("pip-audit"):
            self.assertIn("[term]/uv.lock has no audit tool installed here (pip-audit)", result["notes"])

    def test_every_spelling_of_an_unpinned_reference_is_found(self):
        workflow = "\n".join([
            "jobs:",                                                   # 1
            "  a:",                                                    # 2
            "    steps:",                                              # 3
            "      - uses: actions/checkout@v4",                       # 4  the plain form
            "      - uses: someone/thing@main  # latest",              # 5
            "      - uses: other/pinned@%s" % SHA,                     # 6  pinned
            "      - uses: docker://alpine:3",                         # 7  an image by tag
            "      - uses: docker://alpine@sha256:%s" % ("a" * 64),    # 8  pinned
            "      - {uses: actions/cache@v4}",                        # 9  inside braces
            "      - { name: x, uses: actions/setup@v1 }",             # 10
            '      - "uses": actions/upload@v4',                       # 11 quoted key
            "      - uses : actions/spaced@v4",                        # 12 a space before the colon
            "  b:",                                                    # 13
            "    'uses': other/repo/.github/workflows/r.yml@v1",       # 14 a reusable workflow
            "",
        ])
        self.track(".github/workflows/ci.yml", workflow)
        self.track(".github/actions/build/action.yml", "runs:\n  steps:\n    - uses: actions/checkout@v4\n")
        self.track("docs/example.yml", "- uses: actions/checkout@v4\n")  # not a CI file of this repository
        done, result = self.audit()
        self.assertEqual(done.returncode, 1)
        places = [finding["where"] for finding in result["findings"]]
        self.assertEqual(places, [".github/actions/build/action.yml:3"] + [".github/workflows/ci.yml:%d" % line for line in (4, 5, 7, 9, 10, 11, 12, 14)])

    def test_a_hidden_character_in_a_file_name_is_a_finding(self):
        self.track("report" + HIDDEN + "txt.exe", "fine\n")
        done, result = self.audit()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(result["findings"][0]["rule"], "hidden or bidirectional Unicode character in a file name")
        self.assertNotIn(HIDDEN, done.stdout)

    def test_a_link_is_scanned_as_text_and_never_followed(self):
        outside = os.path.join(self.tmp, "outside.txt")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("key = " + FAKE_KEY + "\n")
        os.symlink(outside, os.path.join(self.repo, "out"))
        os.symlink("pointing/at/" + FAKE_KEY, os.path.join(self.repo, "named"))
        subprocess.run(["git", "add", "--", "out", "named"], cwd=self.repo, env=self.env, capture_output=True, check=True)
        done, result = self.audit()
        self.assertEqual(self.rules(result), [("named:1", "possible secret")], "what is behind a link is not this repository's to read")

    def test_files_that_were_not_read_are_named(self):
        self.track("image.bin", b"\x00\x01" + FAKE_KEY.encode())
        self.track("gone.txt", "x\n")
        os.remove(os.path.join(self.repo, "gone.txt"))
        with open(os.path.join(self.repo, "untracked.txt"), "w", encoding="utf-8") as handle:
            handle.write(FAKE_KEY + "\n")
        done, result = self.audit()
        self.assertEqual((done.returncode, result["files"]), (0, 2))
        self.assertEqual(sorted(result["not_read"]), ["gone.txt (tracked but missing from the working tree)", "image.bin (binary)"])
        self.assertIn("2 file(s) were not read", result["notes"][-1])

    def test_a_lockfile_is_noted_when_no_tool_here_could_audit_it(self):
        self.track("package-lock.json", "{}\n")
        _, result = self.audit()
        noted = "package-lock.json has no audit tool installed here (npm)" in result["notes"]
        self.assertEqual(noted, shutil.which("npm", path=self.env.get("PATH")) is None)

    def test_an_audit_that_could_not_list_the_files_is_not_a_clean_audit(self):
        self.track("a.txt", "key = " + FAKE_KEY + "\n")
        done, result = self.audit(env=dict(self.env, GIT_DIR=os.path.join(self.tmp, "missing")))
        self.assertEqual((done.returncode, result["clean"], result["findings"][0]["where"]), (1, False, "git"))
        folder = os.path.join(self.tmp, "plain")
        os.makedirs(folder)
        done, result = self.audit(cwd=folder, env=dict(self.env, GIT_CEILING_DIRECTORIES=self.tmp))
        self.assertEqual((done.returncode, result["clean"]), (1, False))
        self.assertIn("nothing was audited", result["findings"][0]["rule"])

    def test_a_missing_denylist_is_noted_and_a_broken_one_is_a_finding(self):
        self.track("a.txt", "for " + TERM + "\n")
        os.remove(self.denylist)
        done, result = self.audit()
        self.assertEqual(done.returncode, 0)
        self.assertIn("terms were not checked", result["notes"][0])
        with open(self.denylist, "w", encoding="utf-8") as handle:
            handle.write("re:broken(\n")
        done, result = self.audit()
        self.assertEqual((done.returncode, result["findings"][0]["where"]), (1, "the denylist"))

    def test_this_repository_passes_its_own_audit_with_terms_checked(self):
        """With a denylist of its own, so that terms are checked wherever this runs."""
        with open(self.denylist, "w", encoding="utf-8") as handle:
            handle.write("a-term-that-appears-" + "nowhere-qxzv\n")  # in two pieces, so that it is not in this file either
        env = dict(self.env)
        done, result = self.audit(cwd=ROOT, env=env)
        self.assertEqual(result["findings"], [])
        self.assertGreater(result["files"], 150, "the whole tree was listed")
        # The listing icon is the one binary file this repository is meant to hold.
        self.assertEqual(result["not_read"], [".claude-plugin/icon.png (binary)"])
        self.assertFalse([note for note in result["notes"] if "terms were not checked" in note])


if __name__ == "__main__":
    unittest.main()
