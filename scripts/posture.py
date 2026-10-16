#!/usr/bin/env python3
"""Report whether the sandbox and permission profile from SECURITY.md is in place.

Reads the settings files that apply to this repository and prints what is
missing. It never blocks: the exit code is always 0. `--json` prints the
result for a skill to read.

With `--once` (what `start` passes), the list is printed in full the first
time and whenever it changes, and in one line otherwise: a warning that never
changes is one people learn to skip. What was shown is kept in the user's own
state folder, per checkout, never in the repository, where a clone could plant
a record to hide the list or a link to overwrite a file.
"""

import hashlib
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
        forget(repo_root())
        print("monerex: the sandbox and permission profile is in place.")
        if not result["strict"]:
            print("  note: hosts off the list are approved case by case, not refused. See SECURITY.md.")
        return 0
    if "--once" not in argv or not seen_before(repo_root(), result["missing"]):
        print_gaps(result)
    else:
        print("monerex: security profile: %d gaps, unchanged since they were listed (`posture.py` lists them, SECURITY.md)."
              % len(result["missing"]))
    return 0


def seen_path(root):
    """The user's own record of what was shown for this checkout, outside every repository."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "monerex", "posture", hashlib.sha256(os.path.realpath(root).encode("utf-8")).hexdigest()[:24])


def seen_before(root, missing):
    """Whether this list of gaps was shown for this checkout already; records it when it was not."""
    fingerprint = hashlib.sha256("\n".join(sorted(missing)).encode("utf-8")).hexdigest()
    path = seen_path(root)
    try:
        with open(path, encoding="utf-8") as handle:
            if handle.read(100).strip() == fingerprint:
                return True
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(fingerprint + "\n")
    except OSError:
        pass
    return False


def forget(root):
    """No gaps: a later relapse is new, and is listed in full."""
    try:
        os.remove(seen_path(root))
    except OSError:
        pass


def print_gaps(result):
    print("monerex: security profile gaps (work continues either way):")
    for name in result["missing"]:
        print("  - not set: " + name)
    print("See SECURITY.md for the profile and the alternatives.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
