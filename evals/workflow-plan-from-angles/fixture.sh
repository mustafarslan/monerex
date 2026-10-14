#!/usr/bin/env bash
# Builds the small repository this case runs in. It starts in the empty workspace.
set -euo pipefail

cat > tool.py <<'EOF'
"""A tiny command-line tool."""

import sys


def greet(name):
    return "Helo, %s!" % name


def main(argv):
    print(greet(argv[1] if len(argv) > 1 else "world"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
EOF

cat > test_tool.py <<'EOF'
import unittest

import tool


class ToolTest(unittest.TestCase):
    def test_greet_names_the_person(self):
        self.assertIn("Ada", tool.greet("Ada"))


if __name__ == "__main__":
    unittest.main()
EOF

mkdir -p .monerex
printf '%s\n' '{ "checks": ["python3 -m unittest -q"], "external_review": "off" }' > .monerex/config.json
printf '%s\n' '.monerex/state/' '.monerex/log/' '.monerex/tmp/' '__pycache__/' > .gitignore

git init -q -b main
git config user.name "Eval"
git config user.email "eval@example.invalid"
git add -A
git commit -q -m "Start"
mkdir -p .monerex/log
git checkout -q -b design
