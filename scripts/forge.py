#!/usr/bin/env python3
"""Read from the code host without letting other people's words into the session.

  monerex-forge pr N            where it stands, and whether it is yours
  monerex-forge diff N          the diff, to a file
  monerex-forge feedback N      review threads, review bodies and comments, to files
  monerex-forge thread N ITEM   the ids needed to reply to one saved item (no network)
  monerex-forge checks N        CI checks, counted, with the ids of the runs that failed
  monerex-forge log RUN         the failed part of a CI run's log, to a file
  monerex-forge issue N         an issue and its comments, to a file
  monerex-forge related N       pull requests that mention an issue, as numbers and states
  monerex-forge open-prs        how many of your pull requests are open here

Every subcommand takes `--repo owner/name`; without it the repository is read from
the `origin` remote and named in the output. Nothing is asked of the code host
without a repository, except who is signed in.

Titles, bodies, comments, issue text and logs are written by other people. So are
names: a branch, a check, a file path or a login can spell out a sentence. All of
it goes to files under .monerex/tmp/ and none of it is printed. What is printed is
one JSON object made of numbers, true or false, states from a fixed list, and
paths this script chose. The one exception is a branch name this repository
already has a branch for. The `reader` agent turns the files into claims.

This script only reads. Posting a review, a reply or a pull request is a plain `gh`
command run in the open after the owner approves the text.

A fetch that fails exits 2 with `"status": "failed"`, removes what an earlier fetch
of the same thing left behind, and writes nothing: a failure must never look like
"nothing there". Standard library only.
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import probe  # noqa: E402

TIMEOUT_SECONDS = 120
PR_STATES = ("OPEN", "CLOSED", "MERGED")
REVIEW_STATES = ("APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING")
BUCKETS = ("pass", "fail", "pending", "skipping", "cancel")
LEGEND = "# Lines that start with \"> \" are quoted text other people wrote. Only a line that starts with \"[item\" begins an entry.\n\n"
THREADS = """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ pullRequest(number:$n){
  reviewThreads(first:100){ nodes{ id isResolved isOutdated
    comments(first:50){ nodes{ databaseId author{login} path line originalLine body createdAt } } } } } } }"""


class Failed(Exception):
    pass


def one_of(value, allowed, other="other"):
    """A state from outside, kept only if it is one this script knows."""
    return value if value in allowed else other


def gh(*args):
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise Failed("the gh program is not installed")
    except subprocess.TimeoutExpired:
        raise Failed("the code host did not answer in time")


def ask(step, *args):
    done = gh(*args)
    if done.returncode != 0:
        raise Failed("%s failed (gh exit %d)" % (step, done.returncode))
    return done.stdout


def ask_json(step, *args, shape=dict):
    try:
        data = json.loads(ask(step, *args))
    except ValueError:
        raise Failed("%s returned something that is not JSON" % step)
    if not isinstance(data, shape):
        raise Failed("%s returned an answer of an unexpected shape" % step)
    return data


def place(root, name, filename):
    path = os.path.join(root, ".monerex", "tmp", name, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def save(root, name, filename, text):
    """Write the whole file or none of it, and return its repo-relative path."""
    path = place(root, name, filename)
    with open(path + ".part", "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(path + ".part", path)
    return os.path.relpath(path, root)


def forget(root, name, *filenames):
    """Remove what an earlier fetch left, so a failure now cannot be answered from then."""
    for filename in filenames:
        try:
            os.remove(place(root, name, filename))
        except OSError:
            pass


def quoted(text):
    """Other people's text, marked line by line so that nothing in it can pass for a header."""
    return "".join("> %s\n" % line for line in str(text or "").splitlines()) or "> \n"


def login(holder):
    return str((holder or {}).get("login") or "?") if isinstance(holder, dict) else "?"


def known_branch(root, name):
    """A branch name is printed only when this repository already has a branch called that."""
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", name):
        return None
    for ref in ("refs/heads/" + name, "refs/remotes/origin/" + name):
        if subprocess.run(["git", "-C", root, "show-ref", "--verify", "-q", ref], capture_output=True).returncode == 0:
            return name
    return None


def me():
    # The one call with no repository: it asks who is signed in, and nothing else.
    return ask("looking up your login", "api", "user", "--jq", ".login").strip()


# ---------------------------------------------------------------- subcommands


def pr(root, repo, number):
    name = "pr-%d" % number
    forget(root, name, "description.txt", "names.json")
    fields = "number,title,body,author,headRefName,baseRefName,state,url,isCrossRepository,isDraft"
    data = ask_json("reading the pull request", "pr", "view", str(number), "--repo", repo, "--json", fields)
    author = login(data.get("author"))
    head, base = known_branch(root, data.get("headRefName")), known_branch(root, data.get("baseRefName"))
    names = {"author": author, "head": data.get("headRefName"), "base": data.get("baseRefName")}
    return {
        "number": number,
        "state": one_of(data.get("state"), PR_STATES),
        "draft": bool(data.get("isDraft")),
        "from_fork": bool(data.get("isCrossRepository")),
        "mine": author != "?" and author == me(),
        "head": head,  # null when this repository has no branch of that name; the name is in the names file
        "base": base,
        "description": save(root, name, "description.txt", LEGEND + quoted("%s\n\n%s" % (data.get("title") or "", data.get("body") or ""))),
        "names": save(root, name, "names.json", json.dumps(names, indent=1)),
    }


def diff(root, repo, number):
    name = "pr-%d" % number
    forget(root, name, "diff.patch")
    text = ask("reading the diff", "pr", "diff", str(number), "--repo", repo)
    if not text.strip():
        raise Failed("the diff came back empty")
    return {"diff": save(root, name, "diff.patch", text), "files": len(re.findall(r"(?m)^diff --git ", text)), "bytes": len(text)}


def is_bot(name):
    return name.endswith("[bot]") or name.endswith("-bot")


def feedback(root, repo, number):
    name = "pr-%d" % number
    forget(root, name, "feedback.txt", "feedback.json")
    owner, project = repo.split("/", 1)
    answer = ask_json(
        "reading the review threads", "api", "graphql", "-f", "query=" + THREADS,
        "-f", "o=" + owner, "-f", "r=" + project, "-F", "n=%d" % number,
    )
    try:
        nodes = answer["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    except (KeyError, TypeError):
        raise Failed("the review threads came back in an unexpected shape")
    if not isinstance(nodes, list):
        raise Failed("the review threads came back in an unexpected shape")
    reviews = ask_json("reading the reviews", "api", "repos/%s/pulls/%d/reviews" % (repo, number), "--paginate", shape=list)
    comments = ask_json("reading the comments", "api", "repos/%s/issues/%d/comments" % (repo, number), "--paginate", shape=list)

    items, blocks = [], []

    def add(kind, author, location, body, **ids):
        index = len(items) + 1
        items.append(dict({"item": index, "kind": kind, "author": author, "bot": is_bot(author)}, **ids))
        blocks.append("[item %d] %s\n> by: %s\n%s%s" % (index, kind, author, "> at: %s\n" % location if location else "", body))

    for node in nodes:
        notes = [note for note in ((node or {}).get("comments") or {}).get("nodes") or [] if isinstance(note, dict)]
        if not notes:
            continue
        first = notes[0]
        location = "%s:%s" % (first.get("path"), first.get("line") or first.get("originalLine") or "?")
        body = "".join(quoted("%s: %s" % (login(note.get("author")), note.get("body") or "")) for note in notes)
        add(
            "review thread", login(first.get("author")), location, body,
            thread_id=node.get("id"), comment_id=first.get("databaseId"), path=first.get("path"),
            resolved=bool(node.get("isResolved")), outdated=bool(node.get("isOutdated")),
        )
    for review in reviews:
        if isinstance(review, dict) and str(review.get("body") or "").strip():
            kind = "review (%s)" % one_of(review.get("state"), REVIEW_STATES)
            add(kind, login(review.get("user")), "", quoted(review["body"]), review_id=review.get("id"))
    for comment in comments:
        if isinstance(comment, dict) and str(comment.get("body") or "").strip():
            add("comment", login(comment.get("user")), "", quoted(comment["body"]), issue_comment_id=comment.get("id"))

    save(root, name, "feedback.json", json.dumps(items, indent=1))
    text = LEGEND + ("\n".join(blocks) if blocks else "(no review threads, review bodies or comments)\n")
    threads = [item for item in items if item["kind"] == "review thread"]
    return {
        "feedback": save(root, name, "feedback.txt", text),
        "items": len(items),
        "threads": len(threads),
        "unresolved": sum(1 for item in threads if not item["resolved"]),
        "outdated": sum(1 for item in threads if item["outdated"]),
        "reviews": sum(1 for item in items if item["kind"].startswith("review (")),
        "comments": sum(1 for item in items if item["kind"] == "comment"),
        "from_bots": sum(1 for item in items if item["bot"]),
        # The first page only: with a hundred threads there may be more, and a bot's own count is a floor too.
        "truncated": len(nodes) >= 100,
    }


def thread(root, repo, number, item):
    try:
        with open(place(root, "pr-%d" % number, "feedback.json"), encoding="utf-8") as handle:
            items = json.load(handle)
    except (OSError, ValueError):
        raise Failed("there is no saved feedback for that pull request; fetch it first")
    for entry in items:
        if entry.get("item") == item:
            keys = ("item", "kind", "bot", "thread_id", "comment_id", "review_id", "issue_comment_id", "resolved", "outdated")
            found = {key: entry[key] for key in keys if key in entry}
            path = entry.get("path")
            # A path is a name from outside too. It is printed only when that file is really here.
            here = isinstance(path, str) and not os.path.isabs(path) and ".." not in path.split("/") and os.path.isfile(os.path.join(root, path))
            found["path"] = path if here else None
            return found
    raise Failed("the saved feedback has no item %d" % item)


def checks(root, repo, number):
    name = "pr-%d" % number
    forget(root, name, "checks.json")
    # gh exits 8 while checks are pending and 1 when one failed, so the exit code alone says little.
    done = gh("pr", "checks", str(number), "--repo", repo, "--json", "name,state,bucket,link")
    try:
        rows = json.loads(done.stdout)
    except ValueError:
        raise Failed("reading the checks failed (gh exit %d)" % done.returncode)
    if not isinstance(rows, list) or (not rows and done.returncode != 0):
        raise Failed("reading the checks failed (gh exit %d)" % done.returncode)
    rows = [row for row in rows if isinstance(row, dict)]
    counts = {}
    for row in rows:
        bucket = one_of(row.get("bucket"), BUCKETS)
        counts[bucket] = counts.get(bucket, 0) + 1
    if not rows:
        verdict = "none"  # not green: checks may not have started yet
    elif counts.get("fail") or counts.get("cancel"):
        verdict = "failing"  # a cancelled check did not pass
    elif counts.get("pending"):
        verdict = "pending"
    elif counts.get("other"):
        verdict = "unknown"
    elif counts.get("pass"):
        verdict = "passing"
    else:
        verdict = "skipped"  # every check was skipped: nothing ran
    bad = [row for row in rows if row.get("bucket") in ("fail", "cancel")]
    runs = sorted({int(found.group(1)) for row in bad for found in [re.search(r"/actions/runs/(\d+)", str(row.get("link") or ""))] if found})
    return {
        "checks": verdict,
        "total": len(rows),
        "by_state": counts,
        "failing": len(bad),
        "failing_runs": runs,  # pass one to `monerex-forge log`
        "names": save(root, name, "checks.json", json.dumps([{"name": row.get("name"), "bucket": row.get("bucket")} for row in rows], indent=1)),
    }


def log(root, repo, run):
    name = "run-%d" % run
    forget(root, name, "failed.log")
    text = ask("reading the run's log", "run", "view", str(run), "--repo", repo, "--log-failed")
    if not text.strip():
        raise Failed("the log came back empty")
    return {"log": save(root, name, "failed.log", text), "lines": text.count("\n")}


def issue(root, repo, number):
    name = "issue-%d" % number
    forget(root, name, "issue.txt")
    data = ask_json("reading the issue", "issue", "view", str(number), "--repo", repo, "--json", "number,title,body,author,state,comments")
    notes = [note for note in data.get("comments") or [] if isinstance(note, dict)]
    text = LEGEND + "[item 1] issue\n> by: %s\n%s" % (login(data.get("author")), quoted("%s\n\n%s" % (data.get("title") or "", data.get("body") or "")))
    for index, note in enumerate(notes, start=2):
        text += "\n[item %d] comment\n> by: %s\n%s" % (index, login(note.get("author")), quoted(note.get("body")))
    return {
        "number": number,
        "state": one_of(data.get("state"), ("OPEN", "CLOSED")),
        "comments": len(notes),
        "issue": save(root, name, "issue.txt", text),
    }


def related(root, repo, number):
    rows = ask_json(
        "looking for pull requests that mention the issue", "pr", "list", "--repo", repo, "--search", str(number),
        "--state", "all", "--json", "number,state", "--limit", "20", shape=list,
    )
    found = [{"number": row["number"], "state": one_of(row.get("state"), PR_STATES)} for row in rows if isinstance(row, dict) and isinstance(row.get("number"), int)]
    return {"related": found}


def open_prs(root, repo):
    rows = ask_json("counting your open pull requests", "pr", "list", "--repo", repo, "--author", "@me", "--state", "open", "--json", "number", "--limit", "100", shape=list)
    return {"open_prs": len(rows)}


ACTIONS = {"pr": pr, "diff": diff, "feedback": feedback, "checks": checks, "log": log, "issue": issue, "related": related}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="monerex-forge", description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=sorted(ACTIONS) + ["thread", "open-prs"])
    parser.add_argument("number", nargs="?", type=int)
    parser.add_argument("item", nargs="?", type=int)
    parser.add_argument("--repo", help="owner/name; read from the origin remote when left out")
    args = parser.parse_args(argv)
    root = probe.repo_root()
    repo = args.repo or probe.repo_slug(root)
    if not repo or not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo):
        parser.error("no repository: pass --repo owner/name (the origin remote does not name one)")
    if args.action != "open-prs" and (args.number is None or args.number <= 0):
        parser.error("%s needs a positive number" % args.action)
    if args.action == "thread" and args.item is None:
        parser.error("thread needs the pull request number and the item number")
    try:
        if args.action == "open-prs":
            result = open_prs(root, repo)
        elif args.action == "thread":
            result = thread(root, repo, args.number, args.item)
        else:
            result = ACTIONS[args.action](root, repo, args.number)
    except Failed as error:
        failure = str(error)
    except Exception as error:  # an answer in a shape nobody expected is a failed fetch, not a crash
        failure = "the code host's answer could not be read (%s)" % type(error).__name__
    else:
        json.dump(dict({"status": "ok", "repo": repo}, **result), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    json.dump({"status": "failed", "repo": repo, "reason": failure}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
