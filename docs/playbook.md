# The monerex playbook

How work moves from a request to a merged change when agents do most of the doing. The rules
behind it are in [evidence.md](evidence.md); the security model is in
[SECURITY.md](../SECURITY.md).

**Status:** all four build-order steps are built ([build order](#build-order) says what has
run for real and what has only been tested).

## Principles

1. **One writer.** Agents fan out to read, search and review. One agent at a time changes code
   in a checkout.
2. **Done means a check ran and passed.** Never that an agent said so.
3. **Fresh eyes review.** The reviewer never shares the author's context; risky changes also
   get a reviewer from another model family.
4. **Process is sized to the task.** A typo gets none. A migration gets a lot.
5. **Three human gates, no more.** You approve the intent and plan, the words that go out under
   your name, and the merge. An agent acts up to a gate and never through it.
6. **Must-hold rules live in hooks.** Instructions are advice; a hook is enforcement.
7. **Measure it.** A change to the method is kept when the evals say it helped.

## Tiers

`/monerex:start` classifies each task once. **Risk flags** — auth, data migration, money,
concurrency, secrets, public API, irreversible operations — raise review depth and the model
route regardless of size.

| Tier | Typical task | Committed artifacts | Who writes | Verification and review |
|---|---|---|---|---|
| **T0** trivial | typo, rename, config value | none | main session, inline | checks only |
| **T1** small | bug, change in ≤3 files | `plan.md` | `implementer` from the plan | one fresh-context `verifier` |
| **T2** feature | multi-file change | `intent.md`, `plan.md` | one `implementer` in a worktree; `scout`s for read fan-out | up to four reviewers, each with one angle, and a fifth on cost when the diff touches a query, a remote call or a loop over outside data; a second reviewer from another model family on a risk flag |
| **T3** large | migration, audit, deep research | T2 + staged plan | saved workflows, one per stage, isolated worktrees | verify per stage; your sign-off between stages |

Artifacts live in `docs/work/<slug>/` in the target repository and are committed. They are
capped so they do not crowd the next stage's context: intent ≤60 lines, plan ≤150 lines.

## The loop

One owner per stage. Eight commands you type; five stages `start` chains into.

| Stage | Entry point | You type it | Reads → writes | Gate |
|---|---|---|---|---|
| Triage | `/monerex:start` | yes | request → tier, risk flags, path, routes | confirm path (T2+) |
| Intent | `monerex:intent` | via start | interview → `intent.md` | **G1** accept |
| Plan | `monerex:plan` | via start | intent + code → `plan.md` | **G1** approve |
| Build | `monerex:build` | via start | plan → diff + tests | — |
| Verify | `monerex:verify` | via start | diff + plan → pass/fail with evidence | — |
| Review | `/monerex:review` | yes | diff or PR → verified, ranked findings | triage findings |
| Ship | `/monerex:ship` | yes, manual only | branch → PR, CI watched to green | **G2** your words first; **G3** you merge |
| Feedback | `/monerex:feedback` | yes | review threads → fixes + replies | **G2** approve replies |
| Bugfix | `/monerex:bugfix` | yes, manual only | tracker issue → failing test → fix → PR | G2, G3 |
| Retro | `/monerex:retro` | yes | work log → lessons, eval cases, routing changes | approve changes |
| Consult | `/monerex:consult` | yes, or from `plan` and `review` | one question → a specialist's report, checked | — |
| Dispatch | `/monerex:dispatch` | yes, manual only | a repository and a task → a background session running `start` there | you say yes before it starts |
| Route | `monerex:route` | via start | tier + risk + signals → model, effort, reason | — |

Rules that hold across stages:

- **Review capacity is the limit.** `start` asks before opening a new T2+ task while more than two of
  your PRs in that repository await your review.
- **Every loop is bounded.** At most two escalations per stage, then stop and report. A gap in
  the spec is never retried; it comes back to you.
- **Worktrees are cleaned up.** `start` lists stale ones; `ship` and `retro` offer to remove them.
- **Which primitive.** A subagent for fresh eyes or isolation. A saved workflow when one step
  runs over many items or a quality pattern must repeat exactly. Background sessions for
  parallel small tasks. Routines for scheduled jobs. Agent teams are not used.

## Several tasks at once

Two or three unrelated tasks in different repositories are independent work, so they can run
side by side. What does not scale is you: every task still stops at the same three gates, and
approving in a hurry is worse than approving late.

- **One session per task, in its own repository.** `/monerex:dispatch <repository> <task>`
  starts it in the background, named `monerex: <slug>`, running `start`.
- **Agent view is the desk.** `claude agents` lists every session, grouped by whether it needs
  you, is working, or is ready for review. You answer a plan, a question or a permission
  prompt there, in the session that asked.
- **No session supervises another.** A message from one session never counts as your consent
  in another, so a "main" session could only relay. Monerex does not build one.
- **A limit on open tasks.** `start` and `dispatch` count the monerex tasks already open and ask
  before going past the limit: two by default, `max_open_tasks` in `.monerex/config.json`. It
  asks; it never refuses.
- **One writer per checkout.** A second task in a repository that already has one runs in its
  own worktree and branch, never in the same files. Its checks ran on the base it started
  from, so a push built on a default branch that has since moved is asked about first.
- **Every commit is logged.** One line per commit: what changed, on which branch, from which
  session and after which agents. That is what `retro` reads to tell tasks apart.
- **Nothing crosses repositories.** The count is a number. Monerex never prints another
  session's name or directory, and the session that dispatched a task does not read it again.
- **Cost.** Sessions in parallel use quota in parallel.

The number two is a judgement, not a measurement. Change it if it is wrong for you.

## Work too large for one pass

One writer stays the default. Four saved workflows are the places where more than one agent
works at once, because the work is independent or read-only. Each is a short script whose
control flow is fixed in code: who is dispatched on which route, how results are merged, what
happens when an agent dies. You start them; no stage does, because each starts many agents.

| Workflow | For | What comes back |
|---|---|---|
| `/monerex:review-wide` | a large or risky diff | findings from four angles (a fifth, `performance`, when named), merged, each put to a verifier told to refute it: confirmed, plausible, rejected, and unchecked; with `segments` from `scripts/segment_diff.py`, every angle on every part of a very large diff, plus one reviewer across the parts |
| `/monerex:audit` | one question asked of many paths | answers that held when checked, answers that did not, paths not read, and what the sweep missed |
| `/monerex:plan-from-angles` | a feature with more than one reasonable design | three independent designs, a judge's recommendation, and the choices that are yours |
| `/monerex:migrate` | one mechanical change at many sites | each site changed in its own worktree, then checked by a verifier that did not make the change; nothing committed or merged; `base` starts the writers on a named commit, otherwise the result names the commit they worked on |

A finding nobody could verify is reported as unchecked, never dropped and never counted as
cleared. `scripts/audit.py` is the deterministic counterpart: it reads every tracked file for
secrets, hidden characters and denylisted terms, and CI for actions not pinned to a hash. If
git cannot list the files it says so and fails; it never calls a tree it did not read clean.

Two routine definitions under `routines/` run the smoke evals nightly and the audit weekly.
They read and report; they never push, post or merge. Scheduling one is yours to do.

## Agents

Nine, shipped in the plugin: six that run the loop and three specialists called when a
question needs one. Model and effort are always explicit; nothing is inherited.

| Agent | Job | Tools | Default route |
|---|---|---|---|
| `reader` | turn one file of untrusted text into a fixed schema of claims | `Read` only | small, low |
| `scout` | locate, inventory, summarise; returns paths, not dumps | read-only | small, low |
| `architect` | design verdict before code: boundaries, data model, decision triggers | read-only | large, medium |
| `implementer` | scoped change to named files, test-first, runs the checks | edit + shell, no push | mid, medium |
| `verifier` | fresh context; runs checks, compares the diff to the plan | read-only + shell | mid, medium |
| `reviewer` | fault-finding review against intent and plan | read-only | large, high |

The specialists answer questions; none of them edits code, so the one-writer rule is untouched.

| Specialist | Job | Tools | Default route |
|---|---|---|---|
| `researcher` | literature, standards, official documentation, best practice; every claim with a source it opened | web search and fetch only — it cannot see the repository | mid, medium |
| `ml-specialist` | checks ML, deep-learning, reinforcement-learning and LLM work: evaluation, leakage, baselines, judges | read-only | large, medium |
| `data-scientist` | looks at data and analyses; says how far the numbers support the conclusion | read-only + shell | mid, medium |

A specialist's prompt is not a persona. It is a short list of the mistakes a generalist makes in
that field and a fixed report shape. The ML and data specialists have no web tools: when they
need a current source, `consult` runs the researcher and hands them the result as a file.

## Model and effort routing

One small table, three escalation rules, a log. No learned router.

1. **Role default** in each agent's definition.
2. **`routing/routing.json`** is the single source. `route` reads the tier, the risk flags and
   two signals — *do reliable checks exist?* and *is the plan precise?* — and returns a model
   and an effort that the stage passes on the dispatch. The table names abstract tiers
   (`small`, `mid`, `large`, `advisor`); you map them to models in `.monerex/config.json`.
3. **Escalation is triggered by what the harness observes**: checks failed twice, verifier and
   author disagree, or a finding survived verification.
   - *Diligence gap* — skipped a file, did not run the tests → effort up one level.
   - *Knowledge gap* — wrong diagnosis, unfamiliar domain → model up one tier.
   - *Spec gap* — ambiguous or contradictory requirement → stop, back to intent.

   The route resets at the next stage. When the author moves up, the verifier moves with it.
4. **Log and tune.** `retro` reads escalation and first-pass rates per tier. Starting cheap
   only pays while the escalation rate stays below 1 − (cheap cost ÷ large cost). The table
   holds rough cost ratios for that sum under `relative_cost`; keep them current.

| Work | Model | Effort | Then |
|---|---|---|---|
| Search, inventory, summarise, rank, dedupe | small | low | empty or contradictory → mid, medium |
| Plan and architecture, T2 | large | medium | T3 or risk flag → high + advisor |
| Implementation: precise plan, checks exist | mid | medium (low for T0-grade edits) | escalation rules |
| Implementation: novel, risk-flagged, or no reliable checks | large | medium | never cheap-first |
| Root-cause debugging | large | high | failed hypothesis → xhigh; stuck → advisor, then cross-family |
| Verification | executed checks first, then a mid judge | medium | judge and checks disagree → large |
| Review | large — never below the author | high | risk flag → add cross-family |
| Research | mid | medium | a single fact or one citation check → small, low |
| ML consult | large — never below the author | medium | escalation rules |
| Data consult | mid — never below the author | medium | risk flag → large |
| Advisor | strongest available | — | called by the harness: T3 or risk plans, second failure, pre-ship on risk |

The main session's model is not switched mid-session; routing happens at dispatch. The highest
effort level is used only on request. Effort values are re-tested when the model generation
changes.

## Guardrails

| Hook | Rule |
|---|---|
| Before an edit | Protected paths: secrets files, lockfiles unless the plan lists them, the failing test recorded during a bugfix, and the guards and agent configuration themselves. |
| Before a shell command | No force-push, no push to the default branch, no skipping of hooks. |
| Before a push or PR | The plan's check commands must have passed on the current commit. A push that lacks the newest commits of the default branch is asked about. |
| After a commit | One line to the commit log: commit, branch, paths, session, agents. |
| Before a commit or PR | Confidential terms and secrets — an early warning; git's own hooks are the binding layer. |
| Before a web search or fetch | A query, address or fetch prompt carrying a confidential term or a secret is refused. |
| Agent start and stop | One line to the routing log. |
| Session start | In a repository that uses monerex, the session is told that code changes begin with `start`. Set `"engage": "typed"` in `.monerex/config.json` to keep the loop for the typed command only. |
| A plan or intent file is written | The task's start is logged if no task is open. |

Two stage records are held in `scripts/task.py` rather than in a hook: a verify verdict is
refused unless a `monerex:verifier` ran since the task started, and review counts unless a
`monerex:reviewer` ran since the latest implementer, verify or review. "Ran" means it started
and finished: an agent cut off before it reported does not count. Only the agents of
the session logging the record count, in this checkout and in each worktree: the hook logs
`CLAUDE_CODE_SESSION_ID` with every dispatch, and a dispatch names its session, not its task,
so another session's agents are another task's. A fresh session can still finish a task that
another one started, with agents of its own. An implementer of any session in this checkout
still moves the review anchor, since sessions here share one working tree. Without that
variable (an older Claude Code), this checkout's log alone counts, as it stands. Sessions are
not tasks: a checkout has one open task, the one started last, whichever session started it.
`/clear` gives the session a new id, so an agent dispatched before it and recorded after it
does not count: dispatch it again, which the session has to anyway, since it no longer has
the agent's report. A stage that did not run is reported as not run. No check reaches what a reviewer
found: that is the session's verification of each finding.

The completion gate sits on push, not on session end, so a deliberately failing test or an
outside blocker cannot trap a session.

Build has a gate of its own, in a script rather than a hook: once the change is committed,
`scripts/ablate.py` takes every changed file that is not a test back to the base, in the
working tree only, runs the tests that prove the change, and writes the commit back. It
refuses uncommitted work, so the commit always holds the change; it never resets anything it
did not take out; and a killed run is put back by the next one, file by file, only where
nothing was edited since. A test that
still passes without the change fails the gate, as a `diligence` gap; for a refactor the
tests must pass both ways. Bugfix uses the same gate with `--bugfix`: without the fix its test must fail by assertion,
and the session reads that failure to judge that it is the reported symptom.

## Standalone first

Every stage carries its own instructions and depends on nothing else.
[`capabilities.md`](../capabilities.md) names what monerex uses when it is present, and
`scripts/probe.py` finds out without touching the network. Each stage report says what was
not run:

| Capability | Found when | Without it |
|---|---|---|
| A second reviewer from another model family | the repository names one, its program is installed, and `external_review` is not `off` | reported as "not run" — never as clean |
| The code host | `gh` is installed and the remote names a repository | the pull-request stages stop and say so; an issue can be pasted |
| A repository's own agents | present in `.claude/agents/` | monerex's agents |
| An architecture gate such as `oxn` | its config file is in the repo and its command resolves | the plan's own check commands |

Monerex uses only what that page names. It does not go looking for other installed skills.

When an architecture gate is present, its constraints feed `plan` and go into the plan's
*Architecture* section, `build` runs its check on the changed files, its deep check joins
`verify`, and `review` quotes what `review --base` measured, as a report and not a gate. That
is the measurable half of maintainability (complexity, nesting, length, coupling, each marked
new or already there); the reviewer still reports no style. When its own retry budget runs out, monerex treats that as a spec gap and stops,
rather than raising effort.

## Running it headless

Run it unattended only inside a sandbox or a container. The command below approves edits and
every shell command ahead of time, and with nobody watching, text in the repository that
steers the session (an issue, a planted file) meets no prompt; monerex's hooks are early
warnings, not that boundary. Turn the sandbox on (`/sandbox`, SECURITY.md) or use a dev
container or a throwaway machine first.

Every stage runs in `claude -p` with the plugin loaded from a folder: `claude -p "<prompt>"
--plugin-dir <a clone of monerex> --permission-mode acceptEdits --allowedTools Bash Read Glob
Grep Skill Agent TodoWrite`, started in the repository to work on (a clone, with its push URL
disabled, to try something out). Stages that are not typed commands (`verify`, `plan`, `build`)
run when the prompt asks for them by skill name ("use the monerex:verify skill"). Give a T2
review room: four reviewers and a specialist cost about seven dollars on the mid model, and a
run stopped by `--max-budget-usd` leaves agents that started and never finished, which the
stage guards do not count. `--output-format stream-json --verbose` keeps each agent's report.

## Reading and writing on the code host

Reading and posting are kept apart on purpose.

- **Reading goes through `monerex-forge`.** Descriptions, comments, issue text and CI logs are
  other people's words. The command saves them to files and prints only counts and states;
  `reader` turns the files into claims; each claim is checked against the code. A fetch that
  fails is reported as a failure, never as an empty result.
- **Posting is a plain command, in the open.** A review, a reply or a pull request is posted
  by the main session with `gh`, after you have read and approved the exact text, so your
  permission rules and monerex's guard both see it. No script wraps a post.

## Measuring

- **Per task:** the stages log one line per event to a local task log, and every check run
  adds its own. `scripts/task.py summary` reports, per tier: completion, checks passing first
  time, failed check runs, escalations by kind, plan versions before approval, how many of
  the reviewer's findings were confirmed, the agents that ran, and elapsed time.
- **Smoke evals:** ten cases under `evals/`, cost-capped, on every change to skills, agents,
  hooks or the routing table. Each runs the plugin for real in a scratch repository and is
  graded by what happened — a file, a tool call, a line in the transcript — never by a model.
  Six more cost more and run on their own: a whole task through plan, build, verify and
  review, and five that run a saved workflow in the real runtime.
  **Real suite:** real tasks that went wrong become cases tagged `real`, split mechanically
  between `evals/` (tuned against) and `holdout/` (looked at only at a milestone). The suite
  grows from the task log toward 20–50 cases; every incident adds a case.
- **The eval gate:** `scripts/evalgate.py` compares a run with committed baselines and fails on
  a regression (zero passes, or a one-sided Fisher exact test at p < 0.1), after running a
  case that dropped once more. `ship` asks for a passing gate on the commit when the diff
  touches the plugin and baselines exist.
- **Incident cases:** every real defect found in the guards becomes a live case, tagged
  `incident` and run at milestones. Nine so far.
- **What the plugin adds:** run with and without it once, the whole-loop case scored 1.00
  against 0.25. Both made the change; the difference is the plan, the independent check and
  the review around it, at about five times the cost on a task that small. On a change asked
  for in plain words, 0.85 against 0.27 before the session-start notice was added. The smoke
  suite on 2026-10-16: 30 of 30 runs with the plugin, 6 of 30 without (mean 1.00 against
  0.50).
- **Retro:** `/monerex:retro` reads the logs for a period and proposes at most five changes,
  each tied to a number: retune a route, turn a repeated finding into a guard or an eval
  case, prune an instruction. You decide each one. It never writes lessons into an
  instruction file on its own. Each yes is recorded once its change lands
  (`.monerex/proposals.jsonl`), and every later retro reports whether its number moved:
  moved, revert candidate, or too thin.
- **CI:** the unit tests run on every push and pull request, with a read-only token and no
  third-party action. Plugin validation and the smoke evals run only when you start them by
  hand, because they need your model API key.
- **Baselines:** recorded on 2026-10-16 at `acc094b` from three runs of every case (81 of 81
  passed; see `evals/README.md`). The whole set costs about 10.80 USD a pass on the mid model.
- **Not measured:** tokens per tier. The harness does not report usage to hooks; the eval
  tool's cost estimate is the only figure there is.

## Build order

0. Guards, ignore rules, these documents.
1. The core loop for T0 and T1: agents, routing, `start`, `plan`, `build`, `verify`, `review`;
   the three specialists and `consult`; `dispatch` for tasks side by side.
2. T2: `intent`, `ship`, review from several angles and of pull requests, `feedback`,
   `bugfix`, capability probes. Built. The saved review workflow moves to step 4.
3. Measurement: the task log, the smoke and incident evals, `retro` and CI are built. The
   suite grows as real tasks produce incidents.
4. Scale: background sessions through `dispatch`, four saved workflows for work too large
   for one pass, a tree audit, and two routine definitions. Built. The workflows are tested
   against a stand-in runtime; `review-wide`, `audit` and `plan-from-angles` have also run for
   real in an evaluation, and `migrate` in an ordinary session. Scheduling a routine is the
   owner's to do.
