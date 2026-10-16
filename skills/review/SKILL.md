---
name: review
description: Fresh-context, fault-finding review of a diff or of a pull request, with every finding verified before it is reported and nothing posted without approval. Use when asked to review the current changes, a branch or someone's pull request, and as the last stage of a monerex task.
argument-hint: "[base ref, or a pull request number or URL]"
---

# Review

A reviewer in a fresh context finds candidates. You verify each one. Only what survives is
reported.

If the argument is a pull request number or URL, read `${CLAUDE_SKILL_DIR}/pr.md` and follow
it in place of step 1.

## 1. Save the diff

```sh
mkdir -p .monerex/tmp
git diff "<base>...HEAD" > .monerex/tmp/review.diff
```

Use `git diff HEAD` instead when the work is uncommitted. If the diff is empty, say so and stop.

If git fails, the file holds an error message, not a diff: do not hand it to a reviewer. Give
the reviewer the plan and the list of files the task changed instead, and report "no diff
available" under *Not run*.

## 2. Dispatch

Run `monerex:route` with `--work review`, `--author <tier>` when you know it, and `--risk` when
a risk flag is set. Dispatch `monerex:reviewer` with the routed `model` and `effort`, the path
`.monerex/tmp/review.diff`, and the plan path if there is one. Tell it nothing about what you
expect it to find.

Dispatch it however small the diff, and when git failed too. Your own reading is not a review:
you are not a fresh context. A reviewer that did not run goes under *Not run*.

If the diff changes training, evaluation or prompting code, also dispatch
`monerex:ml-specialist` (route `ml`); if it changes an analysis or a query that a number is
read from, `monerex:data-scientist` (route `data`). Pass `--author` on both. Their findings are
candidates like any other.

**For a T2 task, or when a risk flag is set**, dispatch up to four reviewers in one message,
each with the same diff and one angle named in its brief: correctness and edge cases; fit to
the intent, the plan and the existing structure; security, as the reviewer's item 3 lists it;
the tests. When the diff adds or
changes a database query, a remote call or a loop over data from outside, add a fifth:
performance, cost that grows with the input. The angle is a line in the brief, not a
different agent. A finding two of them report is one finding. For a very
large diff the user can start `/monerex:review-wide`, which does the same in fixed code and
puts every finding to a verifier; you do not start it yourself. When the diff adds or changes a query, a remote call or a loop
over outside data, tell the user to add `performance` to its `angles`. When the diff is very large,
offer its segmented form: `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/segment_diff.py"
.monerex/tmp/review.diff` prints the `segments` to pass it; an empty list, when splitting would
not help, makes it review the whole diff.

If the route sets `cross_family`, write a brief to `.monerex/tmp/second-brief.md` — the diff,
the plan's *Done when*, and the instruction to flag only what affects correctness or the
stated requirements — and run:

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/second_opinion.py" run .monerex/tmp/second-brief.md
```

`not run` → report it under *Not run* with the reason it gives, never as a clean review.
`ran` → the answer file holds candidates like any other. If it carries a `warning`, stop and
tell the user.

## 3. Verify every candidate

For each finding, check it against the code: read the lines, trace the trigger, and where a
test can settle it, run one. Then mark it:

- **confirmed** — you reproduced it or traced it end to end;
- **plausible** — consistent with the code, not reproduced;
- **rejected** — say why in one clause.

A reviewer asked for faults will always find some. Do not pass on what you have not checked.

While a reviewer is running, do not switch branches or edit the files it is reading. It is
looking at the working tree, and a tree that moves under it gives findings about code that is
no longer there.

## 4. Report

- **Critical** — wrong results, data loss, security. Each with `path:line`, the trigger, and
  how you verified it.
- **Improvement** — worth doing, not blocking.
- **Nit** — at most three.
- **Rejected** — one line each, so the user can see what was dismissed.
- **Not run** — any reviewer or check that was skipped, and why.
- **Merge?** — your recommendation. The decision is the user's.

When the review closes a monerex task, log the counts and the end of the task:

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" event review --confirmed <n> --plausible <n> --rejected <n> --merge <yes|after-fixes|no>
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" event done
```

Do not fix anything in this stage. Do not post anything. If the user wants the findings
posted to a PR, that text is theirs to approve first.
