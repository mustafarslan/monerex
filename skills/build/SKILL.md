---
name: build
description: Implements an approved monerex plan through one implementer agent, with the model and effort chosen by the routing table. Use after a plan has been approved.
user-invocable: false
---

# Build

One writer, working from the plan file. You dispatch and check; the implementer edits.

## 1. Route

Run `monerex:route` with `--work implement`, the tier, and the flags that apply (`--risk`,
`--no-checks`, `--imprecise-plan`). For a bug whose cause is not yet known, use `--work debug`.

## 2. Dispatch

Dispatch `monerex:implementer` with the routed `model` and `effort`, and a brief that contains:

- the path of the plan — it reads the plan itself;
- the files it may touch;
- the check command;
- anything the plan does not say that it needs.

Its report opens with its assessment of the plan. `Assessment: clear` → carry on. `blocked` →
answer it from the plan or the code if one message can; otherwise it is a `spec` gap, and
those go back to the user.

Do not paste the conversation. The plan is the handoff.

## 3. Check its work yourself

When it returns, run the checks. Do not rely on its report:

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/check.py"
```

- **Passed** → run the ablation gate, then go to `monerex:verify`, passing on the tier the
  implementer ran at. This run proves the working tree; the push gate later needs the checks
  rerun on the committed result.
- **Failed** → read the failure and name the gap as `monerex:route` describes. Log it with
  `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" event escalation --gap <kind> --work <implement|debug>`.
  Ask the table again with every gap so far, and dispatch again with the new route. The new
  brief names the failure and what was already tried.
- The table says **stop** → stop. Report what was tried and what the checks said.

If the repository has an architecture gate, its own hook may refuse an edit and say its
retry budget is spent. That is a `spec` gap: stop and go back to the plan. Do not raise the
effort or the model to push past it.

## 4. The ablation gate

Passing tests prove little if they would pass without the change. Commit the change on the
task's branch (never the default branch), then run the gate on that commit. It works only on
committed work, so nothing can be lost:

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/ablate.py" --base <the commit before the change> \
  --test "<test command>" [--test "<another>"] [--keep <helper or fixture path>] [--refactor | --bugfix]
```

- `--test`: the narrowest command under the plan's *Done when* that runs the tests for this
  change, one file or name, not the whole suite: a verdict is per command.
- `--keep`: helpers and fixtures the tests need that are not named like tests. Lockfiles and
  test-runner manifests (`package.json`, `Makefile`, `pyproject.toml` and the like) are kept
  without it.
- `--refactor`: when the plan's *Kind* is `refactor`.
- `--bugfix`: for a bugfix (see bugfix, step 5).
- Give the shell call a timeout long enough for five runs of the command.

It runs the tests twice with the change, takes every other changed file back to the base in
the working tree only, runs them again, and writes those files back from the commit. It never
resets anything it did not take out.

- `pass` or `weak` → go on, and give verify the range `<base>..HEAD`. `weak` means a test
  fails without the change only because a new name is missing; say so in the verify brief.
- `fail` → a `diligence` gap: log it as an escalation, and the new brief quotes the gate's
  reason (a test that passes without the change does not test it). For a refactor, `fail`
  means behaviour changed: a `spec` gap.
- `flaky` → a `diligence` gap: the test must give the same answer every time.
- `skipped` → nothing outside the tests changed; go on.
- `not-run` → report the gate as not run, with its reason, and go on to `monerex:verify` as
  always: it still dispatches the verifier. Nothing was taken out. Where git cannot run at
  all, the change cannot be committed: the gate is not run, and nothing else is skipped.
  A test command that writes tracked files is one: say which files it changed.
- Exit 3 → stop: the working tree is not the commit again, or HEAD moved during the run.
  Report `git status` and the reason; do not reset anything yourself.

For T0 skip the gate and log it: `task.py event ablation --result exempt`.

Never edit a test to make it pass. Never mark work done on a report alone.
