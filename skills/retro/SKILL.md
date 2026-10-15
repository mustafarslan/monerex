---
name: retro
description: Looks back over the logged tasks and proposes at most a handful of changes to the way of working, each tied to a number. Use when the user asks how monerex has been doing, wants a retrospective, or wants the routing table retuned.
argument-hint: "[days to look back, default 30]"
---

# Retro

The method is corrected by its own record, not by impressions. You read the numbers, propose
a few changes, and the user decides. Nothing changes in this stage.

## 1. The numbers

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" summary --days <the days asked for, 30 when none were>
git worktree list
```

Show the user the summary as it is. Its last part, *earlier proposals*, judges every proposal
accepted so far by the tasks in its tier started since: `moved`, `revert candidate`, or
`too thin` (its number rests on fewer than five samples), or `unreadable` (a damaged line
in `.monerex/proposals.jsonl`: say which, and fix it through an ordinary task). If fewer than five tasks finished in the period, say the
record is too thin to conclude from, and propose housekeeping only. The same holds tier by
tier: a tier with fewer than five finished tasks supports no change to its route, in either
direction.

## 2. Read them against the method

- **Routes.** Starting cheap only pays while escalations stay rare. If the share of tasks
  that escalated is above 1 − (cost of the cheap model ÷ cost of the large one), the route
  that escalated should start one rung higher. The cost ratios are `relative_cost` in
  `routing/routing.json`; they are rough and the user's to keep current, so say which
  ratio you used. A tier that never escalates and passes its
  checks first time could start lower. The summary counts escalations per tier, with the
  kind of work where the stage logged it; name those counts and nothing finer.
- **Kinds of gap.** Mostly *diligence* → effort was too low. Mostly *knowledge* → the model
  was too small. *Spec* gaps → the intent or the plan left something open: say what.
- **Checks failing first time**, and failed check runs per task → is the plan's *Done when*
  precise enough for the implementer.
- **The reviewer.** If most of its findings were rejected, its briefs are noisy: say which
  kind was rejected. A kind of finding that keeps being confirmed is a candidate for a guard
  or an eval case, so it is caught without a reviewer.
- **Plan versions before approval** above two on average → the questions came too late.
- **Guard log.** Each time a protected file changed while a shell command ran: the summary
  prints the file and who was running.
- **Worktrees** that belong to finished tasks → offer to remove them.
- **Earlier proposals.** `moved` → it stays. `revert candidate` → its number did not move:
  propose undoing it, kind `revert`. `too thin` → say so and leave it.

## 3. Propose, at most five

For each proposal give the number it rests on as `<tier>.<key>` from the summary (for example
`T1.escalated_share`) with its value and the way it should move, the exact change (file and
line), and what would show that it worked. Naming the number that way is what lets a later
retro judge it. The kinds allowed:

| Kind | Example |
|---|---|
| retune a route | one line in `routing/routing.json` |
| add an eval case | an incident becomes a case under `evals/` |
| add a guard | a rule a hook can check |
| prune | an instruction no task has needed |
| revert | undo an earlier proposal its number did not support |
| housekeeping | a stale worktree, a leftover state file |

Not allowed: adding advice to a stage or an agent. A lesson becomes a guard or an eval case,
which catch the mistake whoever makes it. Only when neither can catch it, and the log shows
the same mistake at least three times in the period, may you propose one line for a stage
file, quoting the three. Never write lessons into an instruction file on your own.

A proposal that changes a skill or an agent names the eval case that shows the change working,
passing three runs of three. If no case can show it, propose the case first.

## 4. Write it up and stop

Copy `${CLAUDE_SKILL_DIR}/../../templates/retro.md` to `docs/work/retro-<date>/retro.md`,
fill it in, show it, and stop. Write the file every time, also when the record was too thin
or you propose nothing: it then says so, with the numbers, and the next retro can see that
this one was held. A command that failed, such as the worktree list, goes in it as not run.
The user marks each proposal yes or no. Each yes is an ordinary task through
`monerex:start`. When that task is done and the change has landed, record it, so later retros
judge it only by tasks that ran with the change in place:

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" proposal accept --id R<date>-<n> --retro retro-<date> \
  --metric <tier>.<key> --baseline <value> --direction <up|down> --change "<file and line>"
```

Use the number and value the proposal rested on. `.monerex/proposals.jsonl` is meant to be
committed, so a changed baseline shows in the diff.
