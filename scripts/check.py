#!/usr/bin/env python3
"""Run the repository's check commands and record the result.

The commands are the "checks" list in .monerex/config.json. The record,
.monerex/state/checks.json, names the commit the checks ran on; the push gate
reads it. Exits 0 only when every command passed.

  check.py            run the checks and record the result
  check.py --status   say whether a passing record exists for the current commit
"""

import json
import os
import subprocess
import sys
import time


def git(root, *args):
    done = subprocess.run(["git", "-C", root, *args], capture_output=True)
    return done.stdout.decode("utf-8", errors="replace").strip()


def repo_root(start=None):
    return git(start or os.getcwd(), "rev-parse", "--show-toplevel") or os.getcwd()


# Folders monerex itself writes, which a repository may not ignore: its state and the worktrees.
OWN_STATE = [":(exclude).monerex/state", ":(exclude).monerex/log", ":(exclude).monerex/tmp", ":(exclude).claude/worktrees"]


def fingerprint(root):
    """The commit, and whether the tree held anything that is not in it.

    Untracked files count: a check that passes because of a file that was never
    committed says nothing about the commit.
    """
    head = git(root, "rev-parse", "HEAD")
    pending = git(root, "status", "--porcelain", "--", ".", *OWN_STATE)
    return head, pending == ""


def record_path(root):
    return os.path.join(root, ".monerex", "state", "checks.json")


def status(root, commits=None):
    """Return (ok, message) for the push gate.

    `commits` are the commits about to be pushed; the current one by default.
    The record counts only if the checks passed on exactly that commit, with
    nothing uncommitted in the tree when they ran.
    """
    try:
        with open(record_path(root), encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        return False, "no check record"
    if commits is None:
        commits = [git(root, "rev-parse", "HEAD")]
    if any(commit != record.get("head") for commit in commits):
        return False, "the checks last ran on a different commit"
    if not record.get("passed"):
        return False, "the last check run failed"
    if not record.get("clean"):
        return False, "the checks ran with uncommitted or untracked changes; commit, then run them again"
    return True, "checks passed on this commit"


def main(argv):
    root = repo_root()
    if "--status" in argv:
        ok, message = status(root)
        print(message)
        return 0 if ok else 1
    try:
        with open(os.path.join(root, ".monerex", "config.json"), encoding="utf-8") as handle:
            commands = json.load(handle).get("checks", [])
    except (OSError, ValueError) as error:
        print("monerex: cannot read .monerex/config.json: %s" % error, file=sys.stderr)
        return 2
    if not commands:
        print("monerex: no checks are listed in .monerex/config.json", file=sys.stderr)
        return 2
    head, clean = fingerprint(root)  # the state the checks are about to run on
    results = []
    for command in commands:
        print("monerex: running %s" % command, flush=True)
        code = subprocess.run(command, shell=True, cwd=root).returncode
        results.append({"command": command, "exit": code})
        if code != 0:
            break
    passed = len(results) == len(commands) and all(result["exit"] == 0 for result in results)
    os.makedirs(os.path.dirname(record_path(root)), exist_ok=True)
    with open(record_path(root), "w", encoding="utf-8") as handle:
        json.dump({"head": head, "clean": clean, "passed": passed, "at": int(time.time()), "results": results}, handle, indent=2)
    try:  # the task log never gets in the way of the checks
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import task

        task.append(root, "checks", passed=passed)
    except Exception:
        pass
    print("monerex: checks %s" % ("passed" if passed else "FAILED"))
    if passed and not clean:
        print("monerex: the tree has uncommitted or untracked changes, so this run does not open the push gate.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
