---
name: verify
description: Checks in a fresh context that a change does what its plan says. Use after build, before review.
user-invocable: false
---

# Verify

The agent that wrote the change cannot be the one that says it is done.

1. Run `monerex:route` with `--work verify` and `--author <the tier the implementer ran at>`.
2. Dispatch `monerex:verifier` with the routed `model` and `effort`. Give it the plan path, the
   diff range (for example `main...HEAD`, or `HEAD` for uncommitted work) and the check
   command. Give it nothing about how the implementation went.
3. Read its verdict.
   - **pass** → go to `monerex:review`.
   - **fail** → it names the gap. Return to `monerex:build` with that gap added.
   - It reports a weakened or edited test → treat as a fail, whatever the checks say.

If the repository has an architecture gate, also run its deep check (`<command> check
--deep`): exit 0 is clean, exit 2 is a violation and a fail, exit 1 means the tool itself
failed and is reported as not run.

Log the verdict, which `task.py` refuses unless a `monerex:verifier` ran in this task, with
`python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" event verify --verdict <pass|fail>`,
then tell the user the verdict, what the checks covered, and what they did not.
