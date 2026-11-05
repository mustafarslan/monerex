#!/usr/bin/env python3
"""Merge one pull request, and only when every condition holds. monerex's only merge path.

  monerex-merge <N>

It takes the pull request's number and nothing else, and works out the rest itself:

- the owner opted in: `git config --local --get monerex.merge` in the owner's own checkout
  says `after-checks` (a worktree, or the committed config, cannot say it);
- `.monerex/config.json` lists `checks`;
- the repository is the one the owner checkout's `origin` names;
- the pull request is open, comes from that repository, and goes to its default branch;
- its head commit is the one the checks passed on here, with a clean tree;
- the latest review of the task ship opened it for (`task.py event ship --pr <N>`) said
  `--merge yes` on that same commit;
- CI on the pull request is green.

Then it runs `gh pr merge <N> --repo <R> --merge --delete-branch --match-head-commit <sha>`,
so GitHub itself refuses if the branch moved in between. It prints one JSON line,
`{"status": "merged" | "refused" | "failed", "reason": ...}`, and no text from the code host.
Exit 0 merged, 1 refused, 2 failed. Standard library only.
"""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import check  # noqa: E402
import forge  # noqa: E402
import probe  # noqa: E402
import task  # noqa: E402

OPT_IN = "git config monerex.merge after-checks"
SHA = re.compile(r"[0-9a-f]{40}")


class Refused(Exception):
    pass


def git(root, *args):
    done = subprocess.run(["git", "-C", root, *args], capture_output=True)
    return done.stdout.decode("utf-8", errors="replace").strip()


def task_for(records, number):
    """The task ship recorded this pull request for, or None."""
    found = None
    for record in records:
        if record.get("event") == "ship" and record.get("pr") == number:
            found = record.get("task")
    return found


def latest_review(records, slug):
    reviews = [record for record in records if record.get("event") == "review" and record.get("task") == slug]
    return reviews[-1] if reviews else None


def conditions(root, number):
    """The repository and commit to merge, once every condition holds; else Refused or forge.Failed."""
    owner = probe.main_root(root)
    if git(owner, "config", "--local", "--get", "monerex.merge") != "after-checks":
        raise Refused("the owner has not opted in to merging; they run `%s` in their own checkout." % OPT_IN)
    if not probe.load_config(root).get("checks"):
        raise Refused(".monerex/config.json lists no checks, so nothing proves the commit works.")
    repo = probe.repo_slug(owner)
    if not repo:
        raise Refused("the owner checkout's origin does not name a GitHub repository.")
    pr = forge.ask_json("reading the pull request", "pr", "view", str(number), "--repo", repo, "--json",
                        "headRefOid,headRepositoryOwner,headRefName,baseRefName,state,isCrossRepository")
    if pr.get("state") != "OPEN":
        raise Refused("pull request %d is not open." % number)
    head_owner = pr.get("headRepositoryOwner") if isinstance(pr.get("headRepositoryOwner"), dict) else {}
    if pr.get("isCrossRepository") is not False or str(head_owner.get("login", "")).lower() != repo.split("/")[0].lower():
        raise Refused("pull request %d comes from another repository." % number)
    info = forge.ask_json("reading the repository", "repo", "view", repo, "--json", "defaultBranchRef")
    default = (info.get("defaultBranchRef") or {}).get("name") if isinstance(info.get("defaultBranchRef"), dict) else None
    if not default or pr.get("baseRefName") != default:
        raise Refused("pull request %d does not go to the default branch." % number)
    sha = pr.get("headRefOid")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise forge.Failed("the pull request's head commit could not be read")
    ok, message = check.status(root, [sha])
    if not ok:
        raise Refused("the checks have not passed on the pull request's head commit here: %s." % message)
    records = task.read(root)
    slug = task_for(records, number)
    if not slug:
        raise Refused("no task in this checkout's log shipped pull request %d (`task.py event ship --pr %d`)." % (number, number))
    review = latest_review(records, slug)
    if not review or review.get("merge") != "yes" or review.get("head") != sha:
        raise Refused("the task's latest review did not say `--merge yes` on the pull request's head commit; "
                      "a change after the review needs a new one.")
    ci = forge.checks(root, repo, number)
    if ci.get("checks") != "passing":
        raise Refused("CI on pull request %d is %s, not passing." % (number, ci.get("checks")))
    return repo, sha


def merge(root, number):
    try:
        repo, sha = conditions(root, number)
    except Refused as why:
        return 1, {"status": "refused", "reason": str(why)}
    except forge.Failed as error:
        return 2, {"status": "failed", "reason": str(error)}
    done = forge.gh("pr", "merge", str(number), "--repo", repo, "--merge", "--delete-branch", "--match-head-commit", sha)
    if done.returncode != 0:
        return 2, {"status": "failed", "reason": "gh pr merge failed (gh exit %d)." % done.returncode}
    return 0, {"status": "merged", "reason": "merged %s at %s." % (repo, sha[:12])}


def main(argv):
    if len(argv) != 1 or not re.fullmatch(r"[1-9][0-9]*", argv[0]):
        code, result = 1, {"status": "refused", "reason": "usage: monerex-merge <N>, the pull request's number and nothing else."}
    else:
        try:
            code, result = merge(probe.repo_root(), int(argv[0]))
        except forge.Failed as error:
            code, result = 2, {"status": "failed", "reason": str(error)}
        except Exception as error:  # an answer nobody expected is a failed merge, never a merged one
            code, result = 2, {"status": "failed", "reason": "could not decide (%s)." % type(error).__name__}
    sys.stdout.write(json.dumps(result) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
