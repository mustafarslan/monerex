#!/usr/bin/env python3
"""Opt a repository in to monerex: the checks to run, and the folders git should ignore.

  init.py detect                      what is here: opted in already, and the test commands found
  init.py write --check "<command>"   write .monerex/config.json and the .gitignore lines

`detect` reads the files a project already has (package.json, pyproject.toml, a Makefile,
go.mod, Cargo.toml, tests/) and prints {"opted_in", "candidates", "gitignore_missing"}; it
writes nothing. `write` refuses when the repository has opted in already (that file is the
user's, and in an opted-in repository the guard asks before it is edited) and when no check
command is given (an empty list would put every task on the no-checks route). It never writes
Claude's settings and never installs git hooks. Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys

IGNORED = [".monerex/state/", ".monerex/log/", ".monerex/tmp/", ".claude/worktrees/"]
CONFIG = os.path.join(".monerex", "config.json")
NPM_PLACEHOLDER = "no test specified"
RUNNERS = (("pnpm-lock.yaml", "pnpm test"), ("yarn.lock", "yarn test"), ("bun.lockb", "bun test"), ("bun.lock", "bun test"))


def repo_root():
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True)
    return done.stdout.decode().strip() or os.getcwd()


def text(root, name):
    try:
        with open(os.path.join(root, name), encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return ""


def node(root):
    try:
        script = (json.loads(text(root, "package.json") or "{}").get("scripts") or {}).get("test")
    except ValueError:
        return []
    if not isinstance(script, str) or not script.strip() or NPM_PLACEHOLDER in script:
        return []
    return [next((runner for lock, runner in RUNNERS if os.path.exists(os.path.join(root, lock))), "npm test")]


def python(root):
    pytest = ("[tool.pytest" in text(root, "pyproject.toml") or os.path.exists(os.path.join(root, "pytest.ini"))
              or "[tool:pytest]" in text(root, "setup.cfg") or os.path.exists(os.path.join(root, "conftest.py")))
    if pytest:
        return ["python3 -m pytest -q"]
    tests = os.path.join(root, "tests")
    if os.path.isdir(tests) and any(name.startswith("test") and name.endswith(".py") for name in os.listdir(tests)):
        return ["python3 -m unittest discover -s tests"]
    return []


def candidates(root):
    found = node(root) + python(root)
    if re.search(r"^test\s*:", text(root, "Makefile"), re.M):
        found.append("make test")
    if os.path.exists(os.path.join(root, "go.mod")):
        found.append("go test ./...")
    if os.path.exists(os.path.join(root, "Cargo.toml")):
        found.append("cargo test")
    return found


def ignore_missing(root):
    present = {line.strip() for line in text(root, ".gitignore").splitlines()}
    return [line for line in IGNORED if line not in present]


def detect(root):
    return {"opted_in": os.path.exists(os.path.join(root, CONFIG)), "candidates": candidates(root),
            "gitignore_missing": ignore_missing(root)}


def write(root, checks):
    if os.path.exists(os.path.join(root, CONFIG)):
        print("monerex: this repository has opted in already; %s is left as it is" % CONFIG, file=sys.stderr)
        return 2, None
    if not checks:
        print("monerex: name the command that runs the tests with --check; without one every task would run "
              "with no checks", file=sys.stderr)
        return 2, None
    os.makedirs(os.path.join(root, ".monerex"), exist_ok=True)
    with open(os.path.join(root, CONFIG), "w", encoding="utf-8") as handle:
        json.dump({"checks": checks, "external_review": "off"}, handle, indent=2)
        handle.write("\n")
    wrote = [CONFIG]
    missing = ignore_missing(root)
    if missing:
        existing = text(root, ".gitignore")
        with open(os.path.join(root, ".gitignore"), "a", encoding="utf-8") as handle:
            handle.write(("" if not existing or existing.endswith("\n") else "\n") + "\n".join(missing) + "\n")
        wrote.append(".gitignore")
    return 0, {"wrote": wrote, "checks": checks, "gitignore_added": missing}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("detect")
    writing = sub.add_parser("write")
    writing.add_argument("--check", action="append", default=[], help="a command that runs the tests; repeat for more")
    args = parser.parse_args(argv)
    root = repo_root()
    if args.action == "detect":
        result, code = detect(root), 0
    else:
        code, result = write(root, [check for check in args.check if check.strip()])
    if result is not None:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
