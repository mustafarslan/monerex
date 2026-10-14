#!/usr/bin/env python3
"""The task log: one line per stage event, and a summary of how tasks went.

  task.py event start --slug fix-login --tier T1 [--risk]
  task.py event plan --rounds 2            the plan was approved on its second version
  task.py event escalation --gap knowledge
  task.py event verify --verdict pass
  task.py event review --confirmed 2 --plausible 1 --rejected 3 --merge after-fixes
  task.py event done
  task.py summary [--days N] [--json]

Events go to .monerex/log/tasks.jsonl in this checkout, which git ignores. An
event without --slug belongs to the task that was started last and is not done.
check.py adds a `checks` event for every run. The log holds counts and labels,
never code or conversation. It never blocks: the exit code is 0 unless the
arguments are wrong. Standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import time

TIERS = ("T0", "T1", "T2", "T3")
GAPS = ("diligence", "knowledge", "spec")


def repo_root(cwd=None):
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, cwd=cwd)
    return done.stdout.decode().strip() or cwd or os.getcwd()


def log_path(root, name="tasks.jsonl"):
    return os.path.join(root, ".monerex", "log", name)


def read(root, name="tasks.jsonl"):
    records = []
    try:
        with open(log_path(root, name), encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a damaged line is skipped, not fatal
                if isinstance(record, dict):  # so is a line that is not a record at all
                    record["at"] = record["at"] if isinstance(record.get("at"), (int, float)) else 0
                    records.append(record)
    except OSError:
        pass
    return records


def open_task(records):
    """The slug of the task started last and not yet done, or None."""
    current = None
    for record in records:
        if record.get("event") == "start":
            current = record.get("task")
        elif record.get("event") == "done" and record.get("task") == current:
            current = None
    return current


def append(root, event, slug=None, **fields):
    """Add one event. Returns the record, or None when there is no task to attach it to."""
    slug = slug or open_task(read(root))
    if not slug:
        return None
    record = {"at": int(time.time()), "task": slug, "event": event}
    record.update({key: value for key, value in fields.items() if value is not None})
    os.makedirs(os.path.dirname(log_path(root)), exist_ok=True)
    with open(log_path(root), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def runs(records):
    """Split the log into tasks: each begins at a start event."""
    tasks, current = [], {}
    for record in records:
        slug = record.get("task")
        if record.get("event") == "start":
            current[slug] = {"task": slug, "tier": record.get("tier", "T1"), "risk": bool(record.get("risk")), "events": []}
            tasks.append(current[slug])
        if slug in current:
            current[slug]["events"].append(record)
    return tasks


def rate(part, whole):
    return round(part / whole, 2) if whole else None


def agents_between(dispatches, begin, end):
    counts = {}
    for record in dispatches:
        if record.get("hook_event_name") == "SubagentStart" and begin <= record.get("at", 0) <= end:
            name = str(record.get("agent_type") or "unknown")
            counts[name] = counts.get(name, 0) + 1
    return counts


def summarise(records, dispatches=(), since=0):
    by_tier = {}
    for task in runs(records):
        events = task["events"]
        if max(event["at"] for event in events) < since:
            continue  # nothing happened to this task in the window; one that started earlier and went on counts
        named = lambda name: [event for event in events if event["event"] == name]  # noqa: E731
        row = by_tier.setdefault(
            task["tier"],
            {"started": 0, "done": 0, "checked": 0, "first_pass": 0, "failed_check_runs": 0, "escalations": {}, "escalated": 0,
             "verified": 0, "verify_first_pass": 0, "plan_rounds": [], "findings": {"confirmed": 0, "plausible": 0, "rejected": 0},
             "elapsed": [], "agents": {}},
        )
        row["started"] += 1
        checks, verifies, finished = named("checks"), named("verify"), named("done")
        if checks:
            row["checked"] += 1
            row["first_pass"] += 1 if checks[0].get("passed") else 0
            row["failed_check_runs"] += sum(1 for event in checks if not event.get("passed"))
        if verifies:
            row["verified"] += 1
            row["verify_first_pass"] += 1 if verifies[0].get("verdict") == "pass" else 0
        for event in named("escalation"):
            gap = "%s (%s)" % (event.get("gap", "unknown"), event["work"]) if event.get("work") else event.get("gap", "unknown")
            row["escalations"][gap] = row["escalations"].get(gap, 0) + 1
        row["escalated"] += 1 if named("escalation") else 0
        row["plan_rounds"] += [event["rounds"] for event in named("plan") if isinstance(event.get("rounds"), int)]
        for event in named("review"):
            for kind in row["findings"]:
                row["findings"][kind] += int(event.get(kind) or 0)
        end = finished[-1]["at"] if finished else events[-1]["at"]
        if finished:
            row["done"] += 1
            row["elapsed"].append(end - events[0]["at"])
        for name, count in agents_between(dispatches, events[0]["at"], end).items():
            row["agents"][name] = row["agents"].get(name, 0) + count

    result = {}
    for tier, row in sorted(by_tier.items()):
        findings = row["findings"]
        elapsed = sorted(row["elapsed"])
        result[tier] = {
            "started": row["started"],
            "done": row["done"],
            "completion": rate(row["done"], row["started"]),
            "first_pass_checks": rate(row["first_pass"], row["checked"]),
            "failed_check_runs": row["failed_check_runs"],
            "verify_first_pass": rate(row["verify_first_pass"], row["verified"]),
            "escalations": row["escalations"],
            "escalated_share": rate(row["escalated"], row["started"]),
            "plan_rounds": rate(sum(row["plan_rounds"]), len(row["plan_rounds"])),
            "findings": findings,
            "reviewer_hit_rate": rate(findings["confirmed"], sum(findings.values())),
            "median_minutes": round(elapsed[len(elapsed) // 2] / 60, 1) if elapsed else None,
            "agents": row["agents"],
        }
    return result


def overview(root, days=None):
    """Everything the logs in this checkout say about a period: tasks, dispatches, commits, guard events."""
    since = int(time.time()) - days * 86400 if days else 0
    recent = lambda name: [record for record in read(root, name) if record.get("at", 0) >= since]  # noqa: E731
    dispatches = {}
    for record in recent("routing.jsonl"):
        if record.get("hook_event_name") == "SubagentStop":
            label = "%s/%s" % (record.get("agent_type") or "unknown", record.get("effort") or "?")
            dispatches[label] = dispatches.get(label, 0) + 1
    changed = {}
    for record in recent("guard.jsonl"):
        for path in record.get("paths") or []:
            label = "%s (by %s)" % (path, record.get("by") or "?")
            changed[label] = changed.get(label, 0) + 1
    return {
        "days": days,
        "tiers": summarise(read(root), read(root, "routing.jsonl"), since),
        "dispatches": dispatches,
        "commits": len(recent("commits.jsonl")),
        "protected_files_changed_by_shell": changed,
    }


def show(result):
    summary = result["tiers"]
    lines = ["the last %d days" % result["days"] if result["days"] else "everything logged in this checkout"]
    if not summary:
        lines = ["monerex: no tasks have been logged in this checkout%s." % (" in the last %d days" % result["days"] if result["days"] else " yet")]
    for tier, row in summary.items():
        lines.append("%s  %d started, %d done" % (tier, row["started"], row["done"]))
        for label, key in (
            ("checks passed first time", "first_pass_checks"), ("verify passed first time", "verify_first_pass"),
            ("reviewer findings confirmed", "reviewer_hit_rate"), ("plan versions before approval", "plan_rounds"),
            ("median minutes", "median_minutes"),
        ):
            if row[key] is not None:
                lines.append("    %s: %s" % (label, row[key]))
        if row["failed_check_runs"]:
            lines.append("    failed check runs: %d" % row["failed_check_runs"])
        if row["escalations"]:
            lines.append("    escalations: " + ", ".join("%s %d" % pair for pair in sorted(row["escalations"].items())))
            lines.append("    share of tasks that escalated: %s" % row["escalated_share"])
        if row["agents"]:
            lines.append("    agents run: " + ", ".join("%s %d" % pair for pair in sorted(row["agents"].items())))
    if result.get("dispatches"):
        lines.append("dispatches by agent and effort: " + ", ".join("%s %d" % pair for pair in sorted(result["dispatches"].items())))
    if result.get("commits"):
        lines.append("commits logged: %d" % result["commits"])
    if result.get("protected_files_changed_by_shell"):
        lines.append("protected files changed by a shell command: " + ", ".join("%s %d" % pair for pair in sorted(result["protected_files_changed_by_shell"].items())))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    actions = parser.add_subparsers(dest="action", required=True)
    event = actions.add_parser("event")
    event.add_argument("name", choices=["start", "plan", "escalation", "verify", "review", "done"])
    event.add_argument("--slug")
    event.add_argument("--tier", choices=TIERS)
    event.add_argument("--risk", action="store_true", default=None)
    event.add_argument("--rounds", type=int)
    event.add_argument("--gap", choices=GAPS)
    event.add_argument("--work", help="for an escalation: the kind of work that escalated, as the routing table names it")
    event.add_argument("--verdict", choices=["pass", "fail"])
    event.add_argument("--merge", choices=["yes", "after-fixes", "no"])
    for kind in ("confirmed", "plausible", "rejected"):
        event.add_argument("--" + kind, type=int)
    summary = actions.add_parser("summary")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--days", type=int, help="look back this many days; everything when left out")
    args = parser.parse_args(argv)
    root = repo_root()

    if args.action == "summary":
        if args.days is not None and args.days <= 0:
            parser.error("--days must be a positive number")
        result = overview(root, args.days)
        print(json.dumps(result, indent=2) if args.json else show(result))
        return 0
    if args.name == "start" and not (args.slug and args.tier):
        parser.error("start needs --slug and --tier")
    fields = {key: getattr(args, key) for key in ("tier", "risk", "rounds", "gap", "work", "verdict", "merge", "confirmed", "plausible", "rejected")}
    record = append(root, args.name, slug=args.slug, **fields)
    print("monerex: logged %s for %s" % (args.name, record["task"]) if record else "monerex: no open task; nothing logged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
