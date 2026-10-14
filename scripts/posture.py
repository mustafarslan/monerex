#!/usr/bin/env python3
"""Report whether the sandbox and permission profile from SECURITY.md is in place.

Reads the settings files that apply to this repository and prints what is
missing. It never blocks: the exit code is always 0. `--json` prints the
result for a skill to read.
"""

import json
import os
import subprocess
import sys


def repo_root():
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    return done.stdout.decode().strip() or os.getcwd()


def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def gather(root):
    home = os.path.expanduser("~")
    sources = [
        os.path.join(root, ".claude", "settings.local.json"),
        os.path.join(root, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.json"),
    ]
    return [(path, load(path)) for path in sources]


def first(settings, *keys):
    """The value from the highest-precedence file that sets it."""
    for _, data in settings:
        node = data
        for key in keys:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if node is not None:
            return node
    return None


def rules(settings, kind):
    found = []
    for _, data in settings:
        found.extend(data.get("permissions", {}).get(kind, []) or [])
    return found


def assess(root):
    settings = gather(root)
    domains = first(settings, "sandbox", "network", "allowedDomains")
    ask, deny = rules(settings, "ask"), rules(settings, "deny")
    checks = [
        ("sandbox is on", first(settings, "sandbox", "enabled") is True),
        ("unsandboxed retry is off", first(settings, "sandbox", "allowUnsandboxedCommands") is False),
        ("fails when the sandbox cannot start", first(settings, "sandbox", "failIfUnavailable") is True),
        ("no network host is approved in advance", domains is not None and len(domains) == 0),
        ("a push always asks", any(rule.startswith("Bash(git push") for rule in ask)),
        ("secrets files cannot be read", any(rule.startswith("Read(") and ".env" in rule for rule in deny)),
    ]
    return {
        "sandbox": first(settings, "sandbox", "enabled") is True,
        "strict": first(settings, "sandbox", "network", "strictAllowlist") is True,
        "checks": [{"name": name, "ok": ok} for name, ok in checks],
        "missing": [name for name, ok in checks if not ok],
    }


def main(argv):
    result = assess(repo_root())
    if "--json" in argv:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if not result["missing"]:
        print("monerex: the sandbox and permission profile is in place.")
        if not result["strict"]:
            print("  note: hosts off the list are approved case by case, not refused. See SECURITY.md.")
        return 0
    print("monerex: security profile gaps (work continues either way):")
    for name in result["missing"]:
        print("  - not set: " + name)
    print("See SECURITY.md for the profile and the alternatives.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
