"""The stage files: each names itself, says when to use it, and the ones that post are manual."""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
KNOWN = {"name", "description", "argument-hint", "user-invocable", "disable-model-invocation"}
MANUAL_ONLY = {"ship", "bugfix", "feedback", "dispatch"}  # they push, post or start sessions
INTERNAL = {"route", "plan", "build", "verify", "intent"}  # reached through start


def frontmatter(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    head, _, body = text[4:].partition("\n---\n")
    fields = {}
    for line in head.split("\n"):
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.skills = {name: frontmatter(os.path.join(SKILLS, name, "SKILL.md")) for name in sorted(os.listdir(SKILLS))}

    def test_every_stage_names_itself_and_says_when_to_use_it(self):
        for name, (fields, body) in self.skills.items():
            with self.subTest(name):
                self.assertEqual(fields.get("name"), name)
                self.assertGreater(len(fields.get("description", "")), 40)
                self.assertEqual(set(fields) - KNOWN, set())
                self.assertTrue(body.strip())

    def test_stages_that_push_post_or_start_sessions_are_manual_only(self):
        for name, (fields, _) in self.skills.items():
            with self.subTest(name):
                self.assertEqual(fields.get("disable-model-invocation") == "true", name in MANUAL_ONLY)

    def test_internal_stages_are_hidden_from_the_command_menu(self):
        for name, (fields, _) in self.skills.items():
            with self.subTest(name):
                self.assertEqual(fields.get("user-invocable") == "false", name in INTERNAL)

    def test_no_stage_writes_claudes_settings(self):
        # The directory's security scan looks for plugins that change Claude's permission
        # settings. A stage shows the sandbox profile; the user applies it.
        for name, (_, body) in self.skills.items():
            with self.subTest(name):
                flat = " ".join(body.split())
                self.assertNotRegex(flat, r"(?i)apply (it|the profile) to (this|that one|the) repositor")
                if "settings.local.json" in flat:
                    self.assertIn("Never write a settings file yourself", flat)

    def test_stages_stay_short(self):
        for name, (_, body) in self.skills.items():
            with self.subTest(name):
                self.assertLessEqual(len(body.split("\n")), 110, "a stage that needs more is two stages")

    def test_every_script_and_stage_a_stage_names_exists(self):
        for name, (_, body) in self.skills.items():
            with self.subTest(name):
                for script in re.findall(r"scripts/([a-z_]+\.py)", body):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, "scripts", script)), script)
                for stage in re.findall(r"`monerex:([a-z-]+)`", body):
                    known = stage in self.skills or os.path.exists(os.path.join(ROOT, "agents", stage + ".md"))
                    self.assertTrue(known, "monerex:%s is neither a stage nor an agent" % stage)

    def test_bugfix_takes_a_base_and_keeps_its_worktree_inside_the_repository(self):
        # Seen in a real run: with the work on another branch the stage had no way to name it,
        # and a worktree beside the repository made every edit a question nobody could answer.
        fields, body = self.skills["bugfix"]
        flat = " ".join(body.split())
        self.assertIn("[base branch]", fields["argument-hint"])
        self.assertIn('git worktree add --no-track -b "<slug>" ".claude/worktrees/<slug>" "origin/<base>"', flat)
        self.assertIn("the base from step 2", flat, "the pull request must go to the base the work started from")
        self.assertIn("`.monerex/state/protected-paths` in the worktree", flat, "say which state file takes the entry")
        self.assertIn("Do not write the file another way", flat)

    def test_retro_writes_its_file_even_when_it_proposes_nothing(self):
        # Seen in a live run: with a thin record the session showed the numbers in its answer
        # and wrote no file, so nothing recorded that a retro had been held.
        flat = " ".join(self.skills["retro"][1].split())
        self.assertIn("Write the file every time", flat)

    def test_stages_that_make_a_worktree_keep_it_inside_the_repository(self):
        # A worktree beside the repository makes every edit a question, and a refusal where
        # nobody can answer. The stages that make one name the same place.
        for name in ("bugfix", "feedback"):
            with self.subTest(name):
                flat = " ".join(self.skills[name][1].split())
                self.assertRegex(flat, r'git worktree add [^`]*"\.claude/worktrees/')

    def test_every_code_host_command_a_stage_shows_names_its_repository(self):
        folder_files = [os.path.join(SKILLS, name, "SKILL.md") for name in self.skills] + [os.path.join(SKILLS, "review", "pr.md")]
        fetch = re.compile(r"monerex-forge (?:pr|diff|feedback|checks|log|issue|related|open-prs)\b[^`\n]*")
        for path in folder_files:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for number, line in enumerate(text.split("\n"), start=1):
                stripped = line.strip()
                shown = [stripped] if stripped.startswith(("gh pr ", "gh run ", "gh issue ")) else []
                shown += fetch.findall(line)  # wherever it stands in the line, not only at its start
                for command in shown:
                    with self.subTest(path=os.path.relpath(path, ROOT), line=number):
                        self.assertIn("--repo <R>", command)

    def test_no_stage_reads_the_code_host_except_through_the_reader(self):
        """Listing or viewing with plain `gh` prints other people's titles into the session."""
        reads = re.compile(r"\bgh (?:pr|issue|run) (?:list|view|diff|checks)\b|\bgh api [^\n]*--jq")
        for name in list(self.skills) + ["review/pr.md"]:
            path = os.path.join(SKILLS, name) if name.endswith(".md") else os.path.join(SKILLS, name, "SKILL.md")
            with open(path, encoding="utf-8") as handle:
                with self.subTest(name):
                    self.assertIsNone(reads.search(handle.read()))


if __name__ == "__main__":
    unittest.main()
