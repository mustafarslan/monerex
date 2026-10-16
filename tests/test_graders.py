"""What the graders that judge a finding accept and refuse, on real output and on near misses.

The fixtures under tests/fixtures/graders are the final reports of passing runs of
`review-cost-grows` and `workflow-review-wide-segments`; the second of the review-wide ones read
the workflow's result in a form a pattern on the trace missed. Each negative is the near miss a
grader exists to refuse.
"""

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "graders")


def grader(case, name):
    """The pattern as the harness sees it: the double-quoted YAML scalar, unescaped."""
    with open(os.path.join(ROOT, "evals", case, "graders", name), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("pattern: "):
                return re.compile(json.loads(line[len("pattern: "):].strip()), re.I)
    raise AssertionError("%s/%s has no pattern" % (case, name))


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def result(confirmed="", rejected=""):
    """A review-wide report as the session writes it: what was confirmed, then what was rejected."""
    return "**Confirmed**\n- %s\n\n**Rejected**\n- %s\n" % (confirmed or "none", rejected or "none")


class GraderTest(unittest.TestCase):
    def test_the_cost_must_be_named_before_the_rejected_section(self):
        seen = grader("review-cost-grows", "the-cost-was-seen.md")
        for name in ("review-report-1.md", "review-report-2.md"):
            with self.subTest(name):
                self.assertTrue(seen.search(fixture(name)))
        # The review skill lays the report out as bullets: `- **Rejected** — one line each`.
        for report in ("**Critical** - None.\n- **Improvement** - None.\n- **Rejected** — One query per order (N+1).",
                       "## Findings\nNone.\n### 5. Rejected\n- one query per order (N+1)",
                       "Nothing to fix.\nRejected: the N+1 in fetch_orders, two rows only."):
            with self.subTest(report=report):
                self.assertFalse(seen.search(report))
        self.assertTrue(seen.search("The change meets the plan; none were rejected.\n\n- **Improvement** - "
                                    "orders.py:12 runs one query per order (N+1).\n- **Rejected** - none"))

    def test_review_wide_findings_count_only_outside_the_rejected_list(self):
        cost = grader("workflow-review-wide-segments", "the-cost-was-seen.md")
        crossing = grader("workflow-review-wide-segments", "the-crossing-fault-was-seen.md")
        for name in ("review-wide-report-1.md", "review-wide-report-2.md"):
            with self.subTest(name):
                self.assertTrue(cost.search(fixture(name)))
                self.assertTrue(crossing.search(fixture(name)))
        self.assertFalse(cost.search(result(rejected="One query per order (N+1)")))
        self.assertFalse(crossing.search(result("One query per order (N+1)", "web/page.py still imports list_orders")))
        # The scan of a confirmed finding does not run on into the rejected one.
        self.assertFalse(crossing.search(result("fetch_orders (was list_orders) runs a query per order",
                                                "the import of list_orders breaks web/page.py")))

    def test_the_crossing_fault_needs_a_problem_not_an_account_of_the_rename(self):
        crossing = grader("workflow-review-wide-segments", "the-crossing-fault-was-seen.md")
        for claim in ("fetch_orders, renamed from list_orders, runs one extra query per order",
                      "list_orders is an important name to keep in mind"):
            with self.subTest(claim=claim):
                self.assertFalse(crossing.search(result(claim)))
        for claim in ("page.py calls list_orders, which was removed",
                      "web/page.py fails at import time: cannot import list_orders",
                      "renaming list_orders without an alias breaks web/page.py"):
            with self.subTest(claim=claim):
                self.assertTrue(crossing.search(result(claim)))


if __name__ == "__main__":
    unittest.main()
