#!/usr/bin/env python3
"""The eval gate: run the plugin's eval cases and compare them with stored baselines.

  evalgate.py run [--tag smoke] [--runs N] [--model sonnet] [--max-cost-usd 8]
  evalgate.py run --holdout --milestone 0.3.0     the holdout, only at a milestone
  evalgate.py compare <result.json>               a saved `claude plugin eval --json` result
  evalgate.py baseline <result.json>              write evals/baselines.json from a clean result
  evalgate.py status                              did the gate pass on this commit?

A case regresses when it falls to zero passes, or when a one-sided Fisher exact test on
its passes against the baseline gives p < 0.1; errored runs are left out of that count, so
an error never hides a regression. `run` runs a case whose pass rate dropped once more and
judges it on all its runs together; `compare` judges a saved result as it is. Results are
compared only with baselines from the same model, and a case needs two runs to be judged.

Exit codes: 0 no regression; 1 a regression; 2 not judged: no baselines, a run stopped by
its cost cap, runs that errored, another model, too few runs, a suite case with a baseline
that did not run, or nothing compared. The cost cap covers the whole run, reruns included.
Every `run` is logged to .monerex/log/evalgate.jsonl with the commit; `status` needs the
latest run of every suite on the commit to have passed, and never counts the holdout, which
is looked at only at a milestone and never tuned on: a case that fails there is copied into
evals/ as a new case, and the holdout one stays. Standard
library only.
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time

THRESHOLD = 0.1
BASELINES = os.path.join("evals", "baselines.json")
LOG = os.path.join(".monerex", "log", "evalgate.jsonl")
TOOLS = ["Write", "Edit", "Bash", "WebSearch"]


def repo_root():
    done = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return done.stdout.strip() or os.getcwd()


def head(root):
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def parse(data):
    """The counts that matter from a `claude plugin eval --json` result."""
    suite = data.get("suite") or {}
    plugins = suite.get("plugins") or [{}]
    cases = {}
    for case in data.get("cases") or []:
        runs = (case.get("arms") or {}).get("with") or []
        cases[case["name"]] = {
            "runs": len(runs),
            "passed": sum(1 for run in runs if run.get("passed") and not run.get("error")),
            "errors": sum(1 for run in runs if run.get("error")),
        }
    return {"cases": cases, "model": suite.get("modelOverride"), "plugin_version": plugins[0].get("version"),
            "claude_version": data.get("claudeVersion"), "partial": bool(data.get("partial")), "cost": data.get("costUsd")}


def graders_hash(root, name):
    """A fingerprint of a case's graders: a baseline says nothing about graders that changed since."""
    for folder in ("evals", "holdout"):
        graders = os.path.join(root, folder, name, "graders")
        if os.path.isdir(graders):
            digest = hashlib.sha256()
            for entry in sorted(os.listdir(graders)):
                with open(os.path.join(graders, entry), "rb") as handle:
                    digest.update(entry.encode("utf-8") + b"\0" + handle.read() + b"\0")
            return digest.hexdigest()[:16]
    return None


def fisher_lower(base_passed, base_runs, now_passed, now_runs):
    """P(now_passed or fewer passes) if both sets of runs came from the same pass rate (one-sided Fisher exact)."""
    total, successes = base_runs + now_runs, base_passed + now_passed
    denominator = math.comb(total, now_runs)
    return sum(math.comb(successes, x) * math.comb(total - successes, now_runs - x)
               for x in range(0, now_passed + 1)) / denominator


MIN_RUNS = 2  # with one run a Fisher test cannot reach the threshold, and one flake would look like zero passes


def judge(base, now, model, graders=None):
    if not now["runs"]:
        return "not-run"
    if base is None:
        return "not-run" if now["errors"] else "new"
    if base.get("model") != model:
        return "other-model"
    if base.get("graders") and graders and base["graders"] != graders:
        return "other-graders"
    counted = now["runs"] - now["errors"]  # an errored run says nothing about the case, either way
    if counted >= MIN_RUNS and (
            (now["passed"] == 0 and base.get("passed", 0) > 0)
            or fisher_lower(base.get("passed", 0), base.get("runs", 0), now["passed"], counted) < THRESHOLD):
        return "regression"
    if now["errors"]:
        return "not-run"
    if now["runs"] < MIN_RUNS:
        return "too-few-runs"
    return "same"


def compare(baselines, parsed, expected=None, root=None):
    """Judge every case that ran; a case of the suite that has a baseline but did not run is `missing`."""
    known = (baselines or {}).get("cases", {})
    cases = {}
    for name, now in parsed["cases"].items():
        base = known.get(name)
        cases[name] = dict(now, verdict=judge(base, now, parsed["model"], graders_hash(root, name) if root else None),
                           baseline=None if base is None else {"runs": base.get("runs"), "passed": base.get("passed")})
    for name in sorted(set(expected or ()) - set(parsed["cases"])):
        if name in known:
            cases[name] = {"runs": 0, "passed": 0, "errors": 0, "verdict": "missing",
                           "baseline": {"runs": known[name].get("runs"), "passed": known[name].get("passed")}}
    return {"baselines": baselines is not None, "partial": parsed["partial"], "model": parsed["model"],
            "cost": parsed.get("cost"), "cases": cases}


NOT_JUDGED = {"not-run", "other-model", "other-graders", "too-few-runs", "missing"}


def exit_code(report):
    verdicts = {item["verdict"] for item in report["cases"].values()}
    if "regression" in verdicts:
        return 1
    if not report["baselines"] or report["partial"] or verdicts & NOT_JUDGED or "same" not in verdicts:
        return 2  # stopped early, errored, unjudgeable, or nothing compared with a baseline: not judged
    return 0


def suite_cases(root, folder, tag=None):
    """The case names under a folder, with `tag` among their prompt.md tags when one is given."""
    names = set()
    base = os.path.join(root, folder)
    if not os.path.isdir(base):
        return names
    for name in os.listdir(base):
        prompt = os.path.join(base, name, "prompt.md")
        if not os.path.isfile(prompt):
            continue
        if tag is None:
            names.add(name)
            continue
        with open(prompt, encoding="utf-8") as handle:
            match = re.search(r"^tags:\s*\[(.*)\]", handle.read(), re.MULTILINE)
        if match and tag in {item.strip() for item in match.group(1).split(",")}:
            names.add(name)
    return names


def dropped(report):
    """Cases whose pass rate fell below their baseline's but that ran: worth one more run before judging."""
    names = []
    for name, item in report["cases"].items():
        base = item.get("baseline")
        if base and base.get("runs") and item["runs"] and item["verdict"] in ("same", "regression") \
                and item["passed"] / item["runs"] < base["passed"] / base["runs"]:
            names.append(name)
    return names


def load(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def evaluate(root, args, extra, cap):
    """Run `claude plugin eval` once within `cap` dollars and return the parsed result, or None when it wrote none."""
    out = os.path.join(root, ".monerex", "tmp", "evalgate-%d-%d.json" % (int(time.time() * 1000), os.getpid()))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    command = [os.environ.get("MONEREX_CLAUDE", "claude"), "plugin", "eval", ".", "--json", out, "--ablation", "none",
               "--scaffold", "--trust-plugin", "--no-publish", "--model", args.model, "--max-cost-usd", str(round(cap, 2))]
    command += ["--eval-dir", "holdout"] if args.holdout else ["--tag", args.tag]
    command += extra
    tools = TOOLS + (["Workflow"] if args.tag == "full" and not args.holdout else [])
    command += ["--allow-tools", *tools]
    try:
        subprocess.run(command, cwd=root)
    except OSError as error:
        print("monerex: cannot run %s: %s" % (command[0], error), file=sys.stderr)
        return None
    data = load(out)
    if os.path.exists(out):
        os.remove(out)
    return None if data is None else parse(data)


def merge(first, second):
    for name, item in second["cases"].items():
        mine = first["cases"].setdefault(name, {"runs": 0, "passed": 0, "errors": 0})
        for key in ("runs", "passed", "errors"):
            mine[key] += item[key]
    first["partial"] = first["partial"] or second["partial"]
    first["cost"] = (first.get("cost") or 0) + (second.get("cost") or 0)
    return first


def run(root, args):
    baselines = load(os.path.join(root, BASELINES))
    expected = suite_cases(root, "holdout") if args.holdout else suite_cases(root, "evals", args.tag)
    budget = args.max_cost_usd
    parsed = evaluate(root, args, ["--runs", str(args.runs)] if args.runs else [], budget)
    if parsed is None:
        report = {"baselines": baselines is not None, "partial": True, "model": args.model, "cost": None, "cases": {}}
    else:
        spent = parsed.get("cost") if parsed.get("cost") is not None else budget
        report = compare(baselines, parsed, expected, root)
        for name in dropped(report):  # one unlucky run is not a regression: run that case again and judge them together
            left = budget - spent
            again = evaluate(root, args, ["--case", name, "--runs", "3"], left) if left >= 0.01 else None
            if again is not None:
                spent += again.get("cost") if again.get("cost") is not None else left
            rerun = (again or {}).get("cases", {}).get(name) or {"runs": 0, "passed": 0, "errors": 1}  # no result is an error
            parsed = merge(parsed, {"cases": {name: rerun}, "partial": bool(again and again["partial"]),
                                    "cost": (again or {}).get("cost")})
        report = compare(baselines, parsed, expected, root)
    code = exit_code(report)
    record = {"at": int(time.time()), "head": head(root), "tag": None if args.holdout else args.tag, "holdout": args.holdout,
              "milestone": args.milestone, "model": args.model, "verdict": {0: "pass", 1: "regression", 2: "not-run"}[code],
              "cost": report.get("cost"), "regressions": sorted(name for name, item in report["cases"].items() if item["verdict"] == "regression")}
    os.makedirs(os.path.dirname(os.path.join(root, LOG)), exist_ok=True)
    with open(os.path.join(root, LOG), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2))
    return code


def write_baselines(root, path):
    data = load(path)
    if data is None:
        print("monerex: cannot read %s" % path, file=sys.stderr)
        return 2
    parsed = parse(data)
    if parsed["partial"] or any(item["errors"] or item["runs"] < MIN_RUNS for item in parsed["cases"].values()):
        print("monerex: a partial result, runs that errored, or a case with fewer than %d runs is not a baseline" % MIN_RUNS,
              file=sys.stderr)
        return 2
    if not parsed["model"]:
        print("monerex: the result does not name its model; run the evals with --model so later runs compare with it",
              file=sys.stderr)
        return 2
    target = os.path.join(root, BASELINES)
    baselines = load(target) or {"version": 1, "cases": {}}
    existing = suite_cases(root, "evals") | suite_cases(root, "holdout")
    if existing:  # a case that was deleted or renamed leaves no baseline behind to be skipped silently
        baselines["cases"] = {name: entry for name, entry in baselines["cases"].items() if name in existing}
    date = time.strftime("%Y-%m-%d")
    for name, item in parsed["cases"].items():
        baselines["cases"][name] = {"runs": item["runs"], "passed": item["passed"], "model": parsed["model"],
                                    "plugin_version": parsed["plugin_version"], "claude_version": parsed["claude_version"], "date": date,
                                    "graders": graders_hash(root, name)}
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(baselines, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("monerex: baselines written for %d cases; commit %s through the loop" % (len(parsed["cases"]), BASELINES))
    return 0


def status(root):
    """The latest run of every suite on this commit must have passed; the holdout never counts."""
    current, latest = head(root), {}
    try:
        with open(os.path.join(root, LOG), encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("head") == current and not record.get("holdout"):
                    latest[(record.get("tag"), record.get("model"))] = record
    except OSError:
        pass
    if not latest:
        print("monerex: the eval gate has not run on this commit")
        return 1
    failing = ["%s (%s)" % (tag, record["verdict"]) for (tag, _), record in sorted(latest.items(), key=str) if record["verdict"] != "pass"]
    if failing:
        print("monerex: the eval gate did not pass on this commit: " + ", ".join(failing))
        return 1
    print("monerex: the eval gate passed on this commit: " + ", ".join(sorted(str(tag) for tag, _ in latest)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    actions = parser.add_subparsers(dest="action", required=True)
    runner = actions.add_parser("run")
    runner.add_argument("--tag", default="smoke", help="the suite to run: smoke, incident, full or real")
    runner.add_argument("--runs", type=int, help="runs per case; the case's own setting when left out")
    runner.add_argument("--model", default="sonnet")
    runner.add_argument("--max-cost-usd", type=float, default=8.0, help="a hard cost ceiling for the whole run, reruns included (default 8)")
    runner.add_argument("--holdout", action="store_true", help="run the holdout cases instead of a tag")
    runner.add_argument("--milestone", help="required with --holdout: the release or milestone this look is for")
    comparer = actions.add_parser("compare")
    comparer.add_argument("result")
    comparer.add_argument("--tag", help="the suite the result ran: its cases with a baseline must all be in it")
    actions.add_parser("baseline").add_argument("result")
    actions.add_parser("status")
    args = parser.parse_args(argv)
    root = repo_root()

    if args.action == "run":
        if args.max_cost_usd <= 0:
            print("monerex: a cost ceiling above zero is required", file=sys.stderr)
            return 2
        if args.holdout and not args.milestone:
            print("monerex: the holdout is looked at only for a milestone: pass --milestone", file=sys.stderr)
            return 2
        return run(root, args)
    if args.action == "compare":
        data = load(args.result)
        if data is None:
            print("monerex: cannot read %s" % args.result, file=sys.stderr)
            return 2
        report = compare(load(os.path.join(root, BASELINES)), parse(data), suite_cases(root, "evals", args.tag) if args.tag else None, root)
        print(json.dumps(report, indent=2))
        return exit_code(report)
    if args.action == "baseline":
        return write_baselines(root, args.result)
    return status(root)


if __name__ == "__main__":
    sys.exit(main())
