"""The eval cases are well formed: each has a prompt, a scaffold and graders of a known type.

This does not run them. `claude plugin eval` does; see evals/README.md.
"""

import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS = os.path.join(ROOT, "evals")
DETERMINISTIC = {"regex", "tool_used", "tool_order", "file_exists"}
PROMPT_KEYS = {"description", "tags", "max_turns", "timeout_seconds", "allowed_tools", "runs", "model", "name"}
GRADER_KEYS = {
    "regex": {"type", "weight", "arm", "pattern", "flags", "match", "target"},
    "tool_used": {"type", "weight", "arm", "tool", "input_match", "min", "max"},
    "tool_order": {"type", "weight", "arm", "before", "after"},
    "file_exists": {"type", "weight", "arm", "path", "exists"},
}
READ_ONLY = {"Read", "Glob", "Grep", "NotebookRead", "Skill", "AskUserQuestion", "Agent", "TodoWrite", "Workflow"}


def split(path):
    """(frontmatter as {key: raw value}, body) of a Markdown file."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if not text.startswith("---\n"):
        raise ValueError("%s has no frontmatter" % path)
    head, _, body = text[4:].partition("\n---\n")
    fields = {}
    for line in head.split("\n"):
        if line.strip():
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, body


def cases():
    return sorted(
        name for name in os.listdir(EVALS)
        if name != "results" and os.path.isdir(os.path.join(EVALS, name))
    )


class EvalCaseTest(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertGreaterEqual(len(cases()), 5)

    def test_every_case_belongs_to_exactly_one_suite(self):
        for name in cases():
            with self.subTest(name):
                fields, _ = split(os.path.join(EVALS, name, "prompt.md"))
                tags = {tag.strip() for tag in fields["tags"].strip("[]").split(",")}
                self.assertEqual(len(tags & {"smoke", "full", "incident", "gap"}), 1)

    def test_every_case_has_a_prompt_with_known_fields(self):
        for name in cases():
            with self.subTest(name):
                fields, body = split(os.path.join(EVALS, name, "prompt.md"))
                self.assertEqual(set(fields) - PROMPT_KEYS, set())
                self.assertTrue(body.strip(), "the prompt is empty")
                # The harness reads the header as YAML, where an unquoted ": " inside a value
                # ends it: such a case does not load, and a run of the others still looks whole.
                plain = [key for key, value in fields.items() if ": " in value and value[:1] not in "\"'[{"]
                self.assertEqual(plain, [], "quote the value or drop the colon")
                tools = {tool.strip() for tool in fields["allowed_tools"].strip("[]").split(",")}
                self.assertEqual(tools - READ_ONLY, set(), "anything else is granted on the command line")

    def test_every_case_names_a_scaffold_that_exists_and_parses(self):
        for name in cases():
            with self.subTest(name):
                with open(os.path.join(EVALS, name, "case.yaml"), encoding="utf-8") as handle:
                    text = handle.read()
                self.assertTrue(text.strip(), "case.yaml is empty")
                self.assertIn('schema_version: "1.1"', text)
                self.assertIn("name: %s\n" % name, text)
                script = re.search(r"scaffold_script:\s*(\S+)", text).group(1)
                path = os.path.join(EVALS, name, script)
                self.assertTrue(os.path.exists(path))
                self.assertEqual(subprocess.run(["bash", "-n", path], capture_output=True).returncode, 0)

    def test_every_grader_is_deterministic_and_uses_known_options(self):
        for name in cases():
            graders = os.path.join(EVALS, name, "graders")
            files = sorted(os.listdir(graders))
            self.assertTrue(files, "%s has no grader" % name)
            for grader in files:
                with self.subTest(case=name, grader=grader):
                    fields, _ = split(os.path.join(graders, grader))
                    kind = fields.get("type")
                    self.assertIn(kind, DETERMINISTIC, "smoke cases are graded without a judge model")
                    self.assertEqual(set(fields) - GRADER_KEYS[kind], set())
                    if "pattern" in fields:
                        re.compile(fields["pattern"].strip("\"'"))

    def test_no_case_file_trips_the_secret_scan(self):
        import sys

        sys.path.insert(0, os.path.join(ROOT, "githooks"))
        import monerex_scan

        scan = monerex_scan.Scan([])
        for folder, _, names in os.walk(EVALS):
            if os.sep + "results" in folder:
                continue
            for name in names:
                with open(os.path.join(folder, name), encoding="utf-8") as handle:
                    scan.content(os.path.join(folder, name), handle.read())
        self.assertEqual(scan.findings, [])


if __name__ == "__main__":
    unittest.main()
