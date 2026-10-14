#!/usr/bin/env python3
"""Several monerex tasks side by side, each in its own background session.

  desk.py count [--repo PATH]              how many monerex tasks are open besides this one
  desk.py command REPO SLUG TASK...        the command that starts a task in REPO
                                           (--worktree: in its own checkout)

A monerex task is a session whose name starts with "monerex:"; `command` names
sessions that way. The list comes from `claude agents --json`, which covers
every project on this machine, so only counts leave this script: the names and
working directories of sessions are never printed.

Prints one JSON object. It never blocks: the exit code is 0 unless the
arguments are wrong. Standard library only.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

PREFIX = "monerex:"
DEFAULT_LIMIT = 2


def load_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def sessions():
    """Every active session on this machine, or None when the list cannot be read."""
    try:
        done = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, timeout=30)
        rows = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return rows if isinstance(rows, list) else None


def ancestors():
    """This process and the ones above it, so the session running us is not counted."""
    found, pid = set(), os.getpid()
    for _ in range(32):
        found.add(pid)
        try:
            done = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
            pid = int(done.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            break
        if pid <= 1:
            break
    return found


def inside(path, directory):
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    return path == directory or path.startswith(directory + os.sep)


def count(rows, repo=None, limit=DEFAULT_LIMIT, own=()):
    if not rows:
        # A session is asking, so a listing with nothing in it was not read properly
        # (a sandbox closes the place it is kept): say so instead of counting zero.
        return {"known": False, "others": 0, "by_status": {}, "same_repo": 0, "limit": limit, "over": False}
    own = {str(pid) for pid in own}
    tasks = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("name") or "").lower().startswith(PREFIX) and str(row.get("pid")) not in own
    ]
    by_status = {}
    for row in tasks:
        status = str(row.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    same_repo = sum(1 for row in tasks if repo and row.get("cwd") and inside(row["cwd"], repo))
    return {
        "known": True,
        "others": len(tasks),
        "by_status": by_status,
        "same_repo": same_repo,
        "limit": limit,
        "over": len(tasks) >= limit,  # one more would go past the limit
    }


def repo_limit(repo):
    value = load_json(os.path.join(repo, ".monerex", "config.json")).get("max_open_tasks")
    return value if isinstance(value, int) and value > 0 else DEFAULT_LIMIT


def command(repo, slug, task, plugin_dir=None, worktree=False):
    repo = os.path.realpath(os.path.expanduser(repo))
    if not os.path.isdir(repo):
        raise ValueError("%s is not a directory" % repo)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", slug):
        raise ValueError("the slug is lower-case letters, digits and hyphens, at most 40 characters")
    if not task.strip():
        raise ValueError("the task is empty")
    words = ["claude", "--bg", "--name", "%s %s" % (PREFIX, slug)]
    if worktree:
        words += ["--worktree", slug]  # its own checkout and branch, so two tasks never share files
    if plugin_dir:
        words += ["--plugin-dir", os.path.realpath(os.path.expanduser(plugin_dir))]
    words.append("/monerex:start " + task.strip())
    return {
        "command": "cd %s && %s" % (shlex.quote(repo), " ".join(shlex.quote(word) for word in words)),
        "repo": repo,
        "configured": os.path.exists(os.path.join(repo, ".monerex", "config.json")),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    actions = parser.add_subparsers(dest="action", required=True)
    counting = actions.add_parser("count")
    counting.add_argument("--repo", default=os.getcwd(), help="the repository a new task would run in")
    starting = actions.add_parser("command")
    starting.add_argument("repo")
    starting.add_argument("slug")
    starting.add_argument("task", nargs="+")
    starting.add_argument("--plugin-dir", help="pass the plugin to the new session when it is not installed")
    starting.add_argument("--worktree", action="store_true", help="give the task its own checkout of the repository")
    args = parser.parse_args(argv)

    if args.action == "count":
        repo = os.path.realpath(os.path.expanduser(args.repo))
        result = count(sessions(), repo=repo, limit=repo_limit(repo), own=ancestors())
    else:
        try:
            result = command(args.repo, args.slug, " ".join(args.task), plugin_dir=args.plugin_dir, worktree=args.worktree)
        except ValueError as error:
            parser.error(str(error))
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
