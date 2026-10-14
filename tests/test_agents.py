"""The agent definitions: each names its tools, model and effort, and agrees with the table."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import route  # noqa: E402

AGENTS = os.path.join(ROOT, "agents")
TABLE = route.load_json(route.TABLE)
WRITES = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
WEB = {"WebSearch", "WebFetch"}
LOCAL = {"Read", "Grep", "Glob", "Bash"} | WRITES


def frontmatter(path):
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    if lines[0] != "---":
        raise ValueError("%s does not start with frontmatter" % path)
    fields = {}
    for line in lines[1 : lines.index("---", 1)]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def load():
    agents = {}
    for name in sorted(os.listdir(AGENTS)):
        if name.endswith(".md"):
            fields = frontmatter(os.path.join(AGENTS, name))
            fields["tools"] = {tool.strip() for tool in fields.get("tools", "").split(",") if tool.strip()}
            agents[name[:-3]] = fields
    return agents


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.agents = load()

    def test_every_agent_names_its_tools_model_and_effort(self):
        for name, fields in self.agents.items():
            with self.subTest(name):
                self.assertEqual(fields.get("name"), name)
                self.assertTrue(fields["tools"], "an agent without a tool list inherits every tool")
                self.assertIn(fields.get("model"), TABLE["models"].values())
                self.assertIn(fields.get("effort"), TABLE["effort_ladder"])
                self.assertTrue(fields.get("description"))

    def test_every_route_points_at_an_agent_that_exists(self):
        for work, entry in TABLE["routes"].items():
            with self.subTest(work):
                self.assertIn(entry["agent"], self.agents)

    def test_every_agent_can_be_reached_through_a_route(self):
        routed = {entry["agent"] for entry in TABLE["routes"].values()}
        self.assertEqual(set(self.agents) - routed, set())

    def test_an_agent_definition_agrees_with_one_of_its_routes(self):
        for name, fields in self.agents.items():
            with self.subTest(name):
                defaults = {
                    (TABLE["models"][entry["model"]], entry["effort"])
                    for entry in TABLE["routes"].values()
                    if entry["agent"] == name
                }
                self.assertIn((fields["model"], fields["effort"]), defaults)

    def test_only_the_implementer_can_edit(self):
        for name, fields in self.agents.items():
            with self.subTest(name):
                self.assertEqual(bool(fields["tools"] & WRITES), name == "implementer")

    def test_an_agent_with_web_tools_has_no_access_to_the_repository(self):
        for name, fields in self.agents.items():
            with self.subTest(name):
                if fields["tools"] & WEB:
                    self.assertEqual(fields["tools"] & LOCAL, set())
                    self.assertEqual(fields.get("omitClaudeMd"), "true", "instruction files are private data")

    def test_only_the_researcher_reaches_the_web(self):
        self.assertEqual([name for name, fields in self.agents.items() if fields["tools"] & WEB], ["researcher"])


if __name__ == "__main__":
    unittest.main()
