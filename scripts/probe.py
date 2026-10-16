#!/usr/bin/env python3
"""What optional capabilities this repository and machine offer. See capabilities.md.

Prints one JSON object. Nothing here touches the network, and nothing is required:
a capability that is absent is reported as absent, and the stage that wanted it
reports "not run". Standard library only.

  architecture_gate   an `oxn.yaml` in the repository and a way to run the tool
  second_reviewer     a reviewer from another model family, and whether this
                      repository's `external_review` policy lets it be used
  code_host           the `gh` program, and the repository's owner/name
  own_agents          agent definitions the repository itself ships
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import sys

# The only second reviewers monerex will run, by name. Each is the program to look for.
SECOND_REVIEWERS = {"agy": "agy-ask"}
POLICIES = ("off", "diff-only", "on")


def repo_root(cwd=None):
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, cwd=cwd)
    return done.stdout.decode().strip() or cwd or os.getcwd()


def main_root(root):
    """The owner's own checkout, even when called from a worktree of it.

    Decisions about what may leave the machine are read from there. A worktree can
    hold someone else's branch, and that branch's config file is theirs.
    """

    def git(*args):
        done = subprocess.run(["git", "-C", root, *args], capture_output=True)
        return done.stdout.decode("utf-8", errors="replace").strip()

    # Git lists the main worktree first. A bare repository has no checkout of its own, a
    # folder outside git has no list, and a git directory kept apart from its checkout is
    # listed in the checkout's place: in those three cases this is all there is to read.
    first = git("worktree", "list", "--porcelain").split("\n\n")[0].split("\n")
    if first[0].startswith("worktree ") and "bare" not in first[1:]:
        main = os.path.realpath(first[0][len("worktree ") :])
        common = git("rev-parse", "--git-common-dir")
        if common and main != os.path.realpath(os.path.join(root, common)):
            return main
    return root


def load_config(root):
    try:
        with open(os.path.join(root, ".monerex", "config.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def architecture_gate(root):
    if not os.path.exists(os.path.join(root, "oxn.yaml")):
        return {"present": False, "command": None, "reason": "no oxn.yaml in this repository"}
    if shutil.which("oxn"):
        return {"present": True, "command": "oxn", "reason": "oxn.yaml and the oxn program"}
    try:
        # `-m` looks in the current folder first, and the stages run the command from the
        # repository, whose own oxn.py must not run in its place. `-P` (Python 3.11) leaves the
        # current folder out; the probe also runs from a neutral one.
        done = subprocess.run([sys.executable, "-P", "-m", "oxn", "--version"], cwd=tempfile.gettempdir(), capture_output=True, timeout=15)
        if done.returncode == 0:
            return {"present": True, "command": "python3 -P -m oxn", "reason": "oxn.yaml and the oxn module"}
    except (OSError, subprocess.SubprocessError):
        pass
    if sys.version_info < (3, 11):
        return {"present": False, "command": None, "reason": "oxn.yaml is here but the tool cannot be run: without the oxn program on the PATH, the module needs Python 3.11 to run safely"}
    return {"present": False, "command": None, "reason": "oxn.yaml is here but the tool cannot be run"}


def second_reviewer(config):
    policy = config.get("external_review", "off")
    if policy not in POLICIES:
        policy = "off"
    name = config.get("second_reviewer")
    result = {"name": name if name in SECOND_REVIEWERS else None, "policy": policy, "present": False, "usable": False}
    if name is None:
        result["reason"] = "no second_reviewer is named in .monerex/config.json"
    elif name not in SECOND_REVIEWERS:
        result["reason"] = "that second reviewer is not one monerex knows how to run"
    elif not shutil.which(SECOND_REVIEWERS[name]):
        result["reason"] = "its program is not installed"
    else:
        result["present"] = True
        result["usable"] = policy != "off"
        result["reason"] = "ready" if result["usable"] else "external_review is off for this repository"
    return result


def repo_slug(root):
    done = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True)
    match = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", done.stdout.decode().strip())
    return "%s/%s" % match.groups() if match else None


def own_agents(root):
    folder = os.path.join(root, ".claude", "agents")
    try:
        return sorted(name[:-3] for name in os.listdir(folder) if name.endswith(".md"))
    except OSError:
        return []


def probe(root):
    return {
        "architecture_gate": architecture_gate(root),
        "second_reviewer": second_reviewer(load_config(main_root(root))),
        "code_host": {"present": bool(shutil.which("gh")), "repo": repo_slug(root)},
        "own_agents": own_agents(root),
    }


def main(argv=None):
    json.dump(probe(repo_root()), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
