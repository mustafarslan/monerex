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

# A small change with one real fault in it, saved as the diff a review would be given.
mkdir -p docs/work/add-shout .monerex/tmp .monerex/log
cat > docs/work/add-shout/plan.md <<'EOF'
# Plan: add a --shout flag

- **Tier:** T1
- **Risk flags:** none
- **Status:** approved

## Why

People want the greeting in capitals.

## Done when

- `python3 tool.py --shout Ada` prints `HELO, ADA!` and a test covers it — `python3 -m unittest -q`
- Running the tool without the flag behaves as before.
EOF
cat > tool.py <<'EOF'
"""A tiny command-line tool."""

import sys


def greet(name):
    return "Helo, %s!" % name


def main(argv):
    shout = "--shout" in argv
    name = argv[2] if len(argv) > 1 else "world"
    text = greet(name)
    print(text.upper() if shout else text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
EOF
git diff > .monerex/tmp/review.diff
git checkout -q -b add-shout
