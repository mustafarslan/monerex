#!/usr/bin/env python3
"""The task log: one line per stage event, and a summary of how tasks went.

  task.py event start --slug fix-login --tier T1 [--risk]
  task.py event plan --rounds 2            the plan was approved on its second version
  task.py event escalation --gap knowledge
  task.py event verify --verdict pass
  task.py event review --confirmed 2 --plausible 1 --rejected 3 --merge after-fixes
  task.py event ablation --result exempt   a T0 has no gate; ablate.py logs every other result itself
  task.py event done
  task.py summary [--days N] [--json]
  task.py proposal accept --id R2026-10-15-1 --retro retro-2026-10-15 --metric T1.escalated_share \
      --baseline 0.5 --direction down --change "routing/routing.json: implement starts at large"

Events go to .monerex/log/tasks.jsonl in this checkout, which git ignores. An
event without --slug belongs to the task that was started last and is not done.
check.py adds a `checks` event for every run, and route.py a `route` event for
every routing decision. The log holds counts and labels, never code or
conversation. It never blocks: the exit code is 0 unless the arguments are wrong.

Accepted retro proposals go to .monerex/proposals.jsonl, which is committed. Record
one when its change has landed: the summary judges it by the tasks in its tier
started from then on.
Standard library only.
"""

import argparse
import json
import os
import subprocess
import sys
import time

TIERS = ("T0", "T1", "T2", "T3")
GAPS = ("diligence", "knowledge", "spec")
ABLATION_RESULTS = ("pass", "weak", "fail", "flaky", "skipped", "not-run", "exempt")
# The per-tier numbers a retro proposal may rest on: rates and averages, which compare across
# periods of different length. Raw counts such as failed_check_runs do not, so they are not here.
METRICS = ("completion", "first_pass_checks", "verify_first_pass", "escalated_share", "plan_rounds",
           "reviewer_hit_rate", "median_minutes")
# A proposal is judged only once its number rests on this many samples since it was accepted.
THIN = 5


def repo_root(cwd=None):
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, cwd=cwd)
    return done.stdout.decode().strip() or cwd or os.getcwd()


def log_path(root, name="tasks.jsonl"):
    return os.path.join(root, ".monerex", "log", name)


def proposals_path(root):
    return os.path.join(root, ".monerex", "proposals.jsonl")


def read(root, name="tasks.jsonl", path=None):
    records = []
    try:
        with open(path or log_path(root, name), encoding="utf-8") as handle:
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


def starts_between(dispatches, begin, end):
    return [record for record in dispatches if record.get("hook_event_name") == "SubagentStart" and begin <= record.get("at", 0) <= end]


def match_routes(routes, starts):
    """Pair each subagent start with the earliest route asked for before it, for the same agent, not yet used.

    Returns (routes never dispatched, starts no route asked for).
    """
    open_routes = sorted(routes, key=lambda record: record["at"])
    unrouted = 0
    for start in sorted(starts, key=lambda record: record.get("at", 0)):
        for index, route in enumerate(open_routes):
            if route["at"] <= start.get("at", 0) and "monerex:%s" % route.get("agent") == start.get("agent_type"):
                del open_routes[index]
                break
        else:
            unrouted += 1
    return len(open_routes), unrouted


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
             "elapsed": [], "agents": {}, "routes": {}, "routes_not_dispatched": 0, "unrouted_dispatches": 0, "attribution": {}, "ablation": {}},
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
        for event in named("ablation"):
            result = str(event.get("result") or "unknown")
            row["ablation"][result] = row["ablation"].get(result, 0) + 1
        row["plan_rounds"] += [event["rounds"] for event in named("plan") if isinstance(event.get("rounds"), int)]
        for event in named("review"):
            for kind in row["findings"]:
                row["findings"][kind] += int(event.get(kind) or 0)
        end = finished[-1]["at"] if finished else events[-1]["at"]
        if finished:
            row["done"] += 1
            row["elapsed"].append(end - events[0]["at"])
        starts = starts_between(dispatches, events[0]["at"], end)
        for record in starts:
            name = str(record.get("agent_type") or "unknown")
            row["agents"][name] = row["agents"].get(name, 0) + 1
        routes = named("route")
        how = "by route" if routes else "by time"  # a task logged before routes were is placed by its time window only
        row["attribution"][how] = row["attribution"].get(how, 0) + 1
        for route in routes:
            label = "%s/%s/%s" % (route.get("agent"), route.get("model"), route.get("effort"))
            row["routes"][label] = row["routes"].get(label, 0) + 1
        if routes:  # a route that said stop asked for no dispatch
            not_dispatched, unrouted = match_routes([route for route in routes if not route.get("stop")], starts)
            row["routes_not_dispatched"] += not_dispatched
            row["unrouted_dispatches"] += unrouted

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
            "routes": row["routes"],
            "routes_not_dispatched": row["routes_not_dispatched"],
            "unrouted_dispatches": row["unrouted_dispatches"],
            "attribution": row["attribution"],
            "ablation": row["ablation"],
            # how many samples each rate rests on, so a proposal is not judged on one task
            "samples": {"completion": row["started"], "first_pass_checks": row["checked"], "verify_first_pass": row["verified"],
                        "escalated_share": row["started"], "plan_rounds": len(row["plan_rounds"]),
                        "reviewer_hit_rate": sum(findings.values()), "median_minutes": len(elapsed)},
        }
    return result


def readable_proposal(proposal):
    """The proposal's (tier, key, accepted, baseline) when it is well formed, else None."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get("metric"), dict):
        return None
    tier, key, accepted, baseline = proposal["metric"].get("tier"), proposal["metric"].get("key"), proposal.get("accepted"), proposal.get("baseline")
    if tier not in TIERS or key not in METRICS or proposal.get("direction") not in ("up", "down"):
        return None
    if isinstance(accepted, bool) or not isinstance(accepted, (int, float)) or isinstance(baseline, bool) or not isinstance(baseline, (int, float)):
        return None
    return tier, key, accepted, baseline


def earlier_proposals(proposals, records):
    """Judge each accepted proposal by the tasks in its tier that started once it was accepted."""
    verdicts = []
    for proposal in proposals:
        readable = readable_proposal(proposal)
        if readable is None:  # a hand-edited line must not break the summary retro starts from
            label = proposal.get("id") if isinstance(proposal, dict) else None
            verdicts.append({"id": label, "change": None, "metric": None, "baseline": None, "direction": None, "now": None, "n": 0, "verdict": "unreadable"})
            continue
        tier, key, accepted, baseline = readable
        later = [task for task in runs(records) if task["tier"] == tier and task["events"][0]["at"] >= accepted]
        row = summarise([event for task in later for event in task["events"]]).get(tier, {})
        now, samples = row.get(key), row.get("samples", {}).get(key, 0)
        if now is None or samples < THIN:
            verdict = "too thin"
        elif (now < baseline) if proposal["direction"] == "down" else (now > baseline):
            verdict = "moved"
        else:
            verdict = "revert candidate"
        verdicts.append({"id": proposal.get("id"), "change": proposal.get("change"), "metric": "%s.%s" % (tier, key),
                         "baseline": baseline, "direction": proposal["direction"], "now": now, "n": samples, "verdict": verdict})
    return verdicts


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
        "earlier_proposals": earlier_proposals(read(root, path=proposals_path(root)), read(root)),
        "eval_gate": eval_gate(recent("evalgate.jsonl")),
    }


def eval_gate(records):
    """How the eval gate went in the period, and how often the holdout was looked at."""
    runs = {}
    for record in records:
        verdict = str(record.get("verdict") or "unknown")
        runs[verdict] = runs.get(verdict, 0) + 1
    looks = [record for record in records if record.get("holdout")]
    return {"runs": runs, "holdout_looks": len(looks), "milestones": len({record.get("milestone") for record in looks})}


def worktree_roots(root):
    """This checkout and every worktree of its repository: the hook logs a dispatch where it happened."""
    done = subprocess.run(["git", "-C", root, "worktree", "list", "--porcelain"], capture_output=True)
    found = [line[len("worktree "):] for line in done.stdout.decode(errors="replace").splitlines() if line.startswith("worktree ")]
    return [root] + [path for path in found if os.path.realpath(path) != os.path.realpath(root)]


def agent_ran(root, agent_type, slug=None, since=("start",), after=()):
    """Whether that agent was dispatched since the task's latest `since` event (its start, by
    default) and the latest dispatch of any agent in `after`; True when there is no open task."""
    records = read(root)
    slug = slug or open_task(records)
    starts = [record["at"] for record in records if record.get("event") == "start" and record.get("task") == slug]
    if not slug or not starts:
        return True  # nothing is logged without a task anyway
    anchor = max(record["at"] for record in records if record.get("task") == slug and record.get("event") in since
                 and record["at"] >= starts[-1])
    dispatches = [record for tree in worktree_roots(root) for record in read(tree, "routing.jsonl")
                  if record.get("hook_event_name") == "SubagentStart" and record.get("at", 0) >= starts[-1]]
    anchor = max([anchor] + [record["at"] for record in dispatches if record.get("agent_type") in after])
    return any(record.get("agent_type") == agent_type and record["at"] >= anchor for record in dispatches)


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
        if row["ablation"]:
            lines.append("    ablation gate: " + ", ".join("%s %d" % pair for pair in sorted(row["ablation"].items())))
        if row["routes"]:
            lines.append("    routes asked for: " + ", ".join("%s %d" % pair for pair in sorted(row["routes"].items())))
        if row["routes_not_dispatched"] or row["unrouted_dispatches"]:
            lines.append("    routes never dispatched: %d, dispatches with no route: %d" % (row["routes_not_dispatched"], row["unrouted_dispatches"]))
    if result.get("dispatches"):
        lines.append("dispatches by agent and effort: " + ", ".join("%s %d" % pair for pair in sorted(result["dispatches"].items())))
    if result.get("commits"):
        lines.append("commits logged: %d" % result["commits"])
    if result.get("protected_files_changed_by_shell"):
        lines.append("protected files changed by a shell command: " + ", ".join("%s %d" % pair for pair in sorted(result["protected_files_changed_by_shell"].items())))
    gate = result.get("eval_gate") or {}
    if gate.get("runs"):
        lines.append("eval gate runs: " + ", ".join("%s %d" % pair for pair in sorted(gate["runs"].items()))
                     + ("; holdout looked at %d times for %d milestones" % (gate["holdout_looks"], gate["milestones"])
                        if gate.get("holdout_looks") else ""))
    if result.get("earlier_proposals"):
        lines.append("earlier proposals (tasks started since each was accepted):")
        for item in result["earlier_proposals"]:
            if item["verdict"] == "unreadable":
                lines.append("    %s  unreadable: fix the line in .monerex/proposals.jsonl" % item["id"])
                continue
            lines.append("    %s  %s %s %s -> %s, n=%d: %s" % (
                item["id"], item["metric"], item["direction"], item["baseline"], item["now"], item["n"], item["verdict"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    actions = parser.add_subparsers(dest="action", required=True)
    event = actions.add_parser("event")
    event.add_argument("name", choices=["start", "plan", "escalation", "verify", "review", "ablation", "done"])
    event.add_argument("--slug")
    event.add_argument("--tier", choices=TIERS)
    event.add_argument("--risk", action="store_true", default=None)
    event.add_argument("--rounds", type=int)
    event.add_argument("--gap", choices=GAPS)
    event.add_argument("--work", help="for an escalation: the kind of work that escalated, as the routing table names it")
    event.add_argument("--verdict", choices=["pass", "fail"])
    event.add_argument("--merge", choices=["yes", "after-fixes", "no"])
    event.add_argument("--result", choices=ABLATION_RESULTS, help="for an ablation: the gate's result")
    for kind in ("confirmed", "plausible", "rejected"):
        event.add_argument("--" + kind, type=int)
    summary = actions.add_parser("summary")
    summary.add_argument("--json", action="store_true")
    summary.add_argument("--days", type=int, help="look back this many days; everything when left out")
    proposal = actions.add_parser("proposal")
    proposal.add_argument("verb", choices=["accept"])
    proposal.add_argument("--id", required=True)
    proposal.add_argument("--retro", required=True, help="the retro the proposal came from, e.g. retro-2026-10-15")
    proposal.add_argument("--metric", required=True, help="<tier>.<key>, a number the summary reports, e.g. T1.escalated_share")
    proposal.add_argument("--baseline", required=True, type=float, help="the number the proposal rests on")
    proposal.add_argument("--direction", required=True, choices=["up", "down"], help="which way the number should move")
    proposal.add_argument("--change", required=True, help="the file and line that changes")
    args = parser.parse_args(argv)
    root = repo_root()

    if args.action == "proposal":
        tier, _, key = args.metric.partition(".")
        if tier not in TIERS or key not in METRICS:
            parser.error("--metric must be <tier>.<key> with a tier from %s and a key from %s" % (", ".join(TIERS), ", ".join(METRICS)))
        if any(record.get("id") == args.id for record in read(root, path=proposals_path(root))):
            parser.error("proposal %s is already recorded" % args.id)
        record = {"id": args.id, "retro": args.retro, "accepted": int(time.time()), "metric": {"tier": tier, "key": key},
                  "baseline": args.baseline, "direction": args.direction, "change": args.change}
        os.makedirs(os.path.dirname(proposals_path(root)), exist_ok=True)
        with open(proposals_path(root), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        print("monerex: recorded proposal %s; the summary judges it by %s tasks started from now on" % (args.id, tier))
        return 0

    if args.action == "summary":
        if args.days is not None and args.days <= 0:
            parser.error("--days must be a positive number")
        result = overview(root, args.days)
        print(json.dumps(result, indent=2) if args.json else show(result))
        return 0
    if args.name == "start" and not (args.slug and args.tier):
        parser.error("start needs --slug and --tier")
    # A verdict or a review count with nobody behind it is the session grading its own work.
    # Review counts need a reviewer after the latest change, verify or review: bugfix dispatches
    # one long before, to doubt the root cause, and a re-review needs one of its own.
    needs = {"verify": ("monerex:verifier", "verdict", "the verifier (monerex:verify)", "since the task started",
                        ("start",), ()),
             "review": ("monerex:reviewer", "review", "the reviewer (monerex:review)",
                        "since the latest implementer, verify or review in this task",
                        ("start", "verify", "review"), ("monerex:implementer",))}
    if args.name in needs:
        agent, what, how, when, since, after = needs[args.name]
        if not agent_ran(root, agent, args.slug, since, after):
            print("monerex: no %s ran %s, so there is no %s to log. Dispatch %s; a stage that did not run "
                  "is reported as not run, never logged as passed." % (agent, when, what, how), file=sys.stderr)
            return 2
    fields = {key: getattr(args, key) for key in ("tier", "risk", "rounds", "gap", "work", "verdict", "merge", "result", "confirmed", "plausible", "rejected")}
    record = append(root, args.name, slug=args.slug, **fields)
    print("monerex: logged %s for %s" % (args.name, record["task"]) if record else "monerex: no open task; nothing logged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
