"""Splitting a large diff into a few segments for a segmented review."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEGMENT = os.path.join(ROOT, "scripts", "segment_diff.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import segment_diff  # noqa: E402


def block(path, changed):
    lines = ["diff --git a/%s b/%s" % (path, path), "--- a/%s" % path, "+++ b/%s" % path, "@@ -1,%d +1,%d @@" % (changed, changed)]
    lines += ["+line %d" % number for number in range(changed)]
    return "\n".join(lines) + "\n"


class SegmentTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="monerex-segment-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.diff = os.path.join(self.folder, "review.diff")

    def write(self, text):
        with open(self.diff, "w", encoding="utf-8") as handle:
            handle.write(text)

    def segment(self, *args):
        done = subprocess.run([sys.executable, "-I", SEGMENT, self.diff, *args], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["segments"]

    def test_a_large_diff_is_split_by_top_level_folder_into_at_most_three(self):
        self.write(block("api/a.py", 200) + block("api/b.py", 100) + block("web/c.ts", 250) + block("db/m.sql", 120)
                   + block("docs/x.md", 10) + block("README.md", 5))
        segments = self.segment("--min-lines", "400")
        self.assertEqual(len(segments), 3)
        self.assertEqual(sorted(path for segment in segments for path in segment["paths"]),
                         ["README.md", "api/a.py", "api/b.py", "db/m.sql", "docs/x.md", "web/c.ts"], "every file is in one segment")
        for segment in segments:
            with open(segment["diff"], encoding="utf-8") as handle:
                text = handle.read()
            for path in segment["paths"]:
                self.assertIn("diff --git a/%s b/%s" % (path, path), text)
            self.assertEqual(text.count("diff --git"), len(segment["paths"]), "a segment holds only its own files")
        self.assertIn("api", [segment["name"] for segment in segments], "the largest folder keeps a segment of its own")

    def test_a_small_diff_or_one_folder_is_not_split(self):
        self.write(block("api/a.py", 50) + block("web/c.ts", 50))
        self.assertEqual(self.segment("--min-lines", "400"), [])
        self.write(block("api/a.py", 500) + block("api/b.py", 500))
        self.assertEqual(self.segment("--min-lines", "400"), [], "one folder is one segment: nothing to split")

    def test_paths_with_spaces_and_renames_are_kept_whole(self):
        text = ("diff --git a/old name.py b/new name.py\nsimilarity index 90%\nrename from old name.py\nrename to new name.py\n"
                + "--- a/old name.py\n+++ b/new name.py\n@@ -1 +1 @@\n" + "+x\n" * 300 + block("web/c.ts", 300))
        self.write(text)
        segments = self.segment("--min-lines", "100")
        self.assertEqual(sorted(path for segment in segments for path in segment["paths"]), ["new name.py", "web/c.ts"])

    def real_diff(self, extra_config=()):
        """A diff from git itself, over the file names git quotes or pads: non-ASCII, quotes, tabs, spaces."""
        repo = os.path.join(self.folder, "repo")
        os.makedirs(repo)
        env = {key: value for key, value in os.environ.items() if key not in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE")}
        git = lambda *args: subprocess.run(["git", *extra_config, *args], cwd=repo, env=env, check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        git("config", "user.name", "T")
        git("config", "user.email", "t@example.invalid")
        files = {"tést_root.py": 300, "web/quo\"te.py": 120, "web/ta\tb.py": 120, "web/b.ts": 50, "sp ace/new name.py": 200,
                 "x b/y.py": 150, "api/gone.py": 40, "api/kept.py": 60, "bin/blob.bin": 0, "api/mode.sh": 0}
        for name, size in files.items():
            os.makedirs(os.path.join(repo, os.path.dirname(name) or "."), exist_ok=True)
            with open(os.path.join(repo, name), "w", encoding="utf-8") as handle:
                handle.write("".join("old %d\n" % n for n in range(size)) if size else "x\n")
        git("add", "-A")
        git("commit", "-q", "-m", "start")
        for name, size in files.items():
            if size:
                with open(os.path.join(repo, name), "a", encoding="utf-8") as handle:
                    handle.write("".join("new %d\n" % n for n in range(size)))
        os.remove(os.path.join(repo, "api", "gone.py"))
        with open(os.path.join(repo, "bin", "blob.bin"), "wb") as handle:
            handle.write(bytes(range(256)))
        os.chmod(os.path.join(repo, "api", "mode.sh"), 0o755)
        git("mv", "api/kept.py", "api/moved.py")
        git("add", "-A")
        done = subprocess.run(["git", *extra_config, "diff", "--cached"], cwd=repo, env=env, capture_output=True, check=True)
        with open(self.diff, "wb") as handle:
            handle.write(done.stdout)
        return done.stdout

    def test_every_file_of_a_real_git_diff_lands_in_exactly_one_segment(self):
        raw = self.real_diff()
        segments = self.segment("--min-lines", "100")
        paths = sorted(path for segment in segments for path in segment["paths"])
        self.assertEqual(paths, sorted(["tést_root.py", "web/quo\"te.py", "web/ta\tb.py", "web/b.ts", "sp ace/new name.py",
                                        "x b/y.py", "api/gone.py", "api/moved.py", "bin/blob.bin", "api/mode.sh"]))
        parts = b""
        for segment in segments:
            with open(segment["diff"], "rb") as handle:
                parts += handle.read()
        self.assertEqual(len(parts), len(raw), "every byte of the diff is in one segment")
        [root] = [segment for segment in segments if "tést_root.py" in segment["paths"]]
        self.assertIn("(root)", root["name"])

    def test_a_diff_whose_paths_cannot_be_read_is_an_error_not_an_empty_split(self):
        self.real_diff(extra_config=("-c", "diff.noprefix=true"))
        done = subprocess.run([sys.executable, "-I", SEGMENT, self.diff, "--min-lines", "100"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("cannot read", done.stderr)

    def test_changed_lines_are_counted_without_the_file_headers(self):
        self.assertEqual(segment_diff.changed_lines(block("a.py", 7)), 7)


if __name__ == "__main__":
    unittest.main()
