#!/usr/bin/env python3
"""Pick the agent, model and effort for one dispatch.

The table is routing/routing.json. A repository can remap the abstract model
tiers under "models" in its .monerex/config.json. The rules, in order:

  1. Start from the table's route for the kind of work.
  2. Adjust for the tier, the risk flags, and two signals: whether reliable
     checks exist and whether the plan is precise. For research, T0 means a
     single-fact lookup or a check of one citation.
  3. Apply each observed gap, oldest first:
       diligence  -> effort up one level
       knowledge  -> model up one tier (already at the top: consult the advisor)
       spec       -> stop; the task goes back to the user
  4. Stop when the escalation cap for the stage is exceeded.

Prints one JSON object, with a `route_id`. When a task is open, the decision
is also logged to it as a `route` event (task.py), so the summary can tie each
dispatch to the route that asked for it. Standard library only.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE = os.path.join(os.path.dirname(HERE), "routing", "routing.json")


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def higher(ladder, a, b):
    return a if ladder.index(a) >= ladder.index(b) else b


def step_up(ladder, value):
    index = ladder.index(value)
    return ladder[index + 1] if index + 1 < len(ladder) else None


# Work that judges someone else's output never runs below the tier that wrote it.
JUDGES = ("verify", "review", "ml", "data")


def resolve(table, work, tier="T1", risk=False, checks=True, precise=True, gaps=(), author=None):
    models, efforts = table["model_ladder"], table["effort_ladder"]
    route = table["routes"][work]
    model, effort = route["model"], route["effort"]
    reasons = ["%s starts at %s, %s" % (work, model, effort)]
    advisor = cross_family = stop = False

    if work == "implement":
        if risk or not checks or not precise:
            model = higher(models, model, "large")
            why = [name for name, hit in (("risk flag", risk), ("no reliable checks", not checks), ("imprecise plan", not precise)) if hit]
            reasons.append("never cheap-first: " + ", ".join(why))
        elif tier == "T0":
            effort = "low"
            reasons.append("T0-grade edit: low effort")
    elif work == "plan" and (risk or tier == "T3"):
        effort = higher(efforts, effort, "high")
        advisor = True
        reasons.append("%s: high effort and an advisor consult" % ("risk flag" if risk else "T3"))
    elif work == "review" and risk:
        cross_family = True
        reasons.append("risk flag: add a cross-family reviewer")
    elif work == "research" and tier == "T0":
        model, effort = "small", "low"
        reasons.append("single-fact lookup or citation check: small, low")
    elif work == "data" and risk:
        model = higher(models, model, "large")
        reasons.append("risk flag: a decision hangs on the number")

    if work in JUDGES and author:
        raised = higher(models, model, author)
        if raised != model:
            model = raised
            reasons.append("the judge is never below the author (%s)" % author)

    cap = table["max_escalations_per_stage"]
    for number, gap in enumerate(gaps, start=1):
        if number > cap:
            stop = True
            reasons.append("escalation cap of %d reached: stop and report" % cap)
            break
        if gap == "spec":
            stop = True
            reasons.append("spec gap: stop, back to intent")
            break
        if gap == "diligence":
            raised = step_up(efforts, effort)
            if raised:
                effort = raised
                reasons.append("diligence gap: effort up to " + effort)
            else:
                advisor = True
                reasons.append("diligence gap at top effort: consult the advisor")
        elif gap == "knowledge":
            raised = step_up(models, model)
            if raised:
                model = raised
                reasons.append("knowledge gap: model up to " + model)
            else:
                advisor = True
                reasons.append("knowledge gap at the top tier: consult the advisor")
    if advisor and len(gaps) >= cap and work == "debug":
        cross_family = True
        reasons.append("still stuck: add a cross-family second opinion")

    return {
        "work": work,
        "agent": route["agent"],
        "tier_model": model,
        "model": table["models"][model],
        "effort": effort,
        "advisor": table["models"]["advisor"] if advisor else None,
        "cross_family": cross_family,
        "stop": stop,
        "reason": reasons,
    }


def load_table(repo=None):
    table = load_json(TABLE)
    config = os.path.join(repo or os.getcwd(), ".monerex", "config.json")
    if os.path.exists(config):
        table["models"].update(load_json(config).get("models", {}))
    return table


def main(argv=None):
    table = load_json(TABLE)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", required=True, choices=sorted(table["routes"]))
    parser.add_argument("--tier", default="T1", choices=["T0", "T1", "T2", "T3"])
    parser.add_argument("--risk", action="store_true", help="a risk flag is set")
    parser.add_argument("--no-checks", action="store_true", help="no reliable checks exist")
    parser.add_argument("--imprecise-plan", action="store_true")
    parser.add_argument("--gap", action="append", default=[], choices=["diligence", "knowledge", "spec"])
    parser.add_argument("--author", choices=table["model_ladder"], help="the author's model tier, for verify, review, ml and data")
    parser.add_argument("--repo", help="repository root holding .monerex/config.json")
    args = parser.parse_args(argv)
    result = resolve(
        load_table(args.repo),
        args.work,
        tier=args.tier,
        risk=args.risk,
        checks=not args.no_checks,
        precise=not args.imprecise_plan,
        gaps=args.gap,
        author=args.author,
    )
    result["route_id"] = os.urandom(4).hex()
    log_route(args, result)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def log_route(args, result):
    """Record the decision on the open task. Labels only, never the reasons' prose; never in the way of routing."""
    try:
        sys.path.insert(0, HERE)
        import task

        task.append(
            task.repo_root(args.repo), "route", route_id=result["route_id"], work=result["work"], tier=args.tier,
            agent=result["agent"], model=result["model"], effort=result["effort"], gaps=args.gap or None,
            advisor=bool(result["advisor"]) or None, cross_family=result["cross_family"] or None, stop=result["stop"] or None,
        )
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
