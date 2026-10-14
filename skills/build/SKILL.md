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

- **Passed** → go to `monerex:verify`, passing on the tier the implementer ran at. This run
  proves the working tree; the push gate later needs the checks rerun on the committed result.
- **Failed** → read the failure and name the gap as `monerex:route` describes. Log it with
  `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" event escalation --gap <kind> --work <implement|debug>`.
  Ask the table again with every gap so far, and dispatch again with the new route. The new
  brief names the failure and what was already tried.
- The table says **stop** → stop. Report what was tried and what the checks said.

If the repository has an architecture gate, its own hook may refuse an edit and say its
retry budget is spent. That is a `spec` gap: stop and go back to the plan. Do not raise the
effort or the model to push past it.

Never edit a test to make it pass. Never mark work done on a report alone.
