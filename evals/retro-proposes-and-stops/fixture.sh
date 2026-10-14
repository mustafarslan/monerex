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

# A task history for retro to read. It is written here, not lived: six small tasks, three of
# which had to move to a larger model before their checks passed.
mkdir -p .monerex/log
now=$(date +%s)
{
  for n in 1 2 3 4 5 6; do
    start=$((now - n * 86400))
    printf '{"at": %d, "event": "start", "task": "task-%d", "tier": "T1"}\n' "$start" "$n"
    printf '{"at": %d, "event": "plan", "task": "task-%d", "rounds": 1}\n' "$((start + 60))" "$n"
    if [ "$n" -le 3 ]; then
      printf '{"at": %d, "event": "checks", "task": "task-%d", "passed": false}\n' "$((start + 300))" "$n"
      printf '{"at": %d, "event": "escalation", "task": "task-%d", "gap": "knowledge", "work": "implement"}\n' "$((start + 320))" "$n"
    fi
    printf '{"at": %d, "event": "checks", "task": "task-%d", "passed": true}\n' "$((start + 600))" "$n"
    printf '{"at": %d, "event": "verify", "task": "task-%d", "verdict": "pass"}\n' "$((start + 700))" "$n"
    printf '{"at": %d, "event": "review", "task": "task-%d", "confirmed": 1, "plausible": 0, "rejected": 4, "merge": "yes"}\n' "$((start + 900))" "$n"
    printf '{"at": %d, "event": "done", "task": "task-%d"}\n' "$((start + 1000))" "$n"
  done
} > .monerex/log/tasks.jsonl
git checkout -q -b work
