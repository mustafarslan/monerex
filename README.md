# monerex

**An AI-driven development lifecycle for Claude Code.** From a request to a merged pull
request, agents do the work in stages, hooks hold the rules, and you approve the plan,
anything posted under your name, and the merge.

monerex sizes each task, settles what is wanted, plans it, builds it test-first through one
agent, verifies it in a fresh context and reviews it before anything leaves your machine. It
opens the pull request, works through the review comments, takes tracked bugs from report to
fix, and looks back over the logged tasks to tune itself. Every agent runs with an explicit
model and effort, and the rules that must hold, such as "no push to the default branch" or
"the checks passed on this commit", live in hooks, not in prompts.

monerex is for Claude Code only. It runs Python 3 scripts and ships a `bin/` folder, so
claude.ai and Cowork do not install it.

**Status: early, 0.2.0,** with the changes since listed under *Unreleased* in the
[changelog](CHANGELOG.md). The whole loop and the pull-request stages have run for real on
this project, and the guards have been through several review rounds. Treat it as a careful
first release, not a finished product.

## Quick start

```
/plugin marketplace add mustafarslan/monerex
/plugin install monerex@monerex
/monerex:init
```

`init` finds your test command, writes `.monerex/config.json` and adds monerex's folders to
`.gitignore`. Then ask for a change in plain words, or type `/monerex:start <what you want>`.
`/monerex:start` on its own says where the open task stands and what comes next.

## The lifecycle

Each stage starts fresh and hands over through a short file, not through the conversation.
You type the commands marked *typed*; the others run when the stage before them hands over.

| Stage | How it starts | What it does | What you approve |
|---|---|---|---|
| **start** | typed: `/monerex:start <task>`, or a plain-words request in an opted-in repository; typed alone, it says where the open task stands and what comes next | Sizes the task (T0 trivial to T3 large), sets risk flags (auth, money, migrations, secrets, a public API, a new dependency and the like), checks the setup, and says which stages it will run | the path, for T2 and above |
| **intent** | after `start`, for T2 and above | A few questions whose answers change the design, then a short intent file | the intent |
| **plan** | after `start` or `intent`, for T1 and above | The design, the tasks and the commands that prove it works, in `docs/work/<task>/plan.md` | **the plan**, before any code changes |
| **build** | after your yes | One `implementer` agent makes the change test-first and runs the checks; the change is committed and taken out once more to prove its tests fail without it | — |
| **verify** | after `build` | A fresh agent runs the checks itself and compares the diff with the plan | — |
| **review** | after `verify`, or typed: `/monerex:review [PR]` | Fault-finding review in a fresh context, cost that grows with the input included: one reviewer, up to four with separate angles for a feature or a risk flag (five when the diff touches a query, a remote call or a loop over outside data), and, on a risk-flagged change, a second model family when you have one set up. Every finding is checked against the code before it is reported | which findings to act on |
| **ship** | typed: `/monerex:ship` | Pushes the branch, writes the pull request text, opens the pull request, watches its checks | **the text**; **the merge** is always yours |
| **feedback** | typed: `/monerex:feedback [PR]` | Treats each review comment on your pull request as a claim, checks it, fixes what holds, and drafts a reply for every thread | what to fix, and **every reply** |
| **bugfix** | typed: `/monerex:bugfix <issue>` | A test that fails for the reported symptom, the fix, proof that the test fails again without it, then verify, review, the pull request (draft if you say so) and one round of answers to its review comments; the test is locked for the rest of the task | the plan, **the pull request text** and **every reply** |
| **retro** | typed: `/monerex:retro` | Reads the task and routing logs and proposes a handful of changes to the way of working, each tied to a number, and says whether the changes you accepted earlier moved their numbers | each change |

A trivial T0 task skips the plan and runs only the checks. A T3 task is split with you into
stages that are each T2 or smaller, signed off one at a time.

## Beside the loop

| Command | What it does |
|---|---|
| `/monerex:init` | Opts a repository in: finds your test command, asks you to confirm it, writes `.monerex/config.json` and adds monerex's folders to `.gitignore` |
| `/monerex:consult research \| ml \| data <question>` | Puts one question to a specialist: `researcher` (web search and fetch only, no access to your files), `ml-specialist` or `data-scientist`. The claims a decision rests on are checked again before they are used |
| `/monerex:dispatch <repository> <task>` | Starts a task in another repository as its own background session, after your yes, so several run side by side and each stops at its own gates |
| `/monerex:review-wide` | A saved workflow: reviewers from several angles on one diff, every finding put to a verifier told to refute it, and the survivors ranked; the `performance` angle runs when you name it. A very large diff can be split first with `scripts/segment_diff.py`: each angle then reviews each part with the whole diff in reach, and one more reviewer looks only at what crosses the parts |
| `/monerex:audit` | A saved workflow: one question asked of many paths by read-only scouts, each answer that found something checked, and what the sweep missed named |
| `/monerex:plan-from-angles` | A saved workflow: several independent designs for one task, a judge that recommends one, and the decisions it leaves to you |
| `/monerex:migrate` | A saved workflow: the same change at many sites, each in its own worktree and checked by a verifier; nothing is merged for you |

The saved workflows start many agents, so they run only when you start them.

## How the agents are run

- **Nine agents, each with a narrow job and tool list.** `reader` turns untrusted text (an
  issue, review comments, bot output) into a fixed list of claims and reports any embedded
  instructions instead of following them. `scout` searches, `architect` judges a design,
  `implementer` is the only one that edits code, `verifier` runs the checks, `reviewer` hunts
  faults, and `researcher`, `ml-specialist` and `data-scientist` are the specialists. Only
  `implementer` has the edit tools; `verifier` and `data-scientist` have a shell to run checks
  and analyses, and `consult` reports anything the data scientist changed. Only the main
  session pushes or posts.
- **Model and effort are chosen, never inherited.** A routing table
  ([`routing/routing.json`](routing/routing.json)) picks them per stage from the tier and the
  risk flags. When a stage fails, the gap is named and the stage escalates: a skipped
  step raises the effort, a wrong diagnosis raises the model, and an unclear requirement comes
  back to you instead of being retried. Two escalations per stage at most.
- **Everything is logged locally**, so `retro` can show how each tier and route went (first
  passes, rework, escalations), and the evals (`evals/`) run the plugin for real to check a
  change to the method.

The [playbook](docs/playbook.md) has the tiers, the stages and the routing in full.

## What holds

The hooks refuse a force-push, a push to the default branch, a skipped git hook, a merge, a
push before the checks passed on what it pushes, an edit to a protected file (secrets files,
lockfiles not in the plan, the test a bugfix locked, agent and tool configuration such as
`.claude/`, `CLAUDE.md`, `AGENTS.md`, `.mcp.json`, git and editor settings and monerex's own
config and state, CI workflows), a command or edit that carries a term from your private list, and a web request
that carries a term or a secret. A subagent may not push, post or change agent configuration.
A verify verdict or a review's counts are not recorded unless that agent ran and finished in
the session recording them. Optional git hooks catch secrets and names in commits and refuse
pushes to the default branch. These are early
warnings that stop accidents; [SECURITY.md](SECURITY.md) says what each covers and what it
does not.

## Install

```
/plugin marketplace add mustafarslan/monerex
/plugin install monerex@monerex
```

Requirements: Claude Code, Python 3 (CI runs the tests on the runner's Python 3), and git. The
pull-request stages also need the GitHub CLI (`gh`), signed in. The owner's override of the
default-branch rule (`git -c monerex.allowDefaultPush=1 push ...`) needs git 2.26 or later.

**Installing changes nothing until a repository opts in.** The hooks start on every tool
call, find no `.monerex/config.json`, and stop: they refuse nothing, ask nothing and write
nothing. To opt a repository in, type `/monerex:init`, or create that file yourself:

```json
{ "checks": ["<the command that runs your tests>"], "external_review": "off" }
```

and add the folders monerex writes to the repository's `.gitignore`:

```
.monerex/state/
.monerex/log/
.monerex/tmp/
.claude/worktrees/
```

In an opted-in repository, a session that starts there is told to take a plain-words request
for a code change through the loop, as if you had typed `/monerex:start`; a question is
simply answered. Set `"engage": "typed"` to keep the loop for the typed command only. A tool
call from such a session is guarded by that repository's rules, even when it acts on another
directory.

## Try it

**Make a change.** `/monerex:start add a CSV export to the report page`. monerex sizes the
task, asks what it needs to know, shows you the plan, and after your yes builds it with
tests, verifies it in a fresh context and reviews it.

**Review a pull request.** `/monerex:review 42` reviews pull request 42 from its diff,
without checking its code out (it runs a same-repository pull request's checks in a separate
worktree only when that matters, and never runs a fork's code), checks every finding before
reporting it, and posts nothing until you have read and approved the exact text.
`/monerex:review` with no number reviews your current changes.

**Fix a reported bug.** `/monerex:bugfix 1234` takes issue 1234 from its report to a pull
request: it reproduces the bug with a failing test, fixes the cause, checks that the
test fails again without the fix, verifies, reviews, and shows you the pull request text
before opening it.

**Ask a specialist.** `/monerex:consult research what does the literature say about flaky
test detection?` returns an answer with its sources, the ones the answer rests on checked a
second time.

## What monerex runs, reads, writes and sends

Everything monerex does is in readable Python, shell and Markdown in this repository. It has
no server, sends nothing to its author, and collects no telemetry.

- **Hooks.** A Python script (`hooks/monerex_hook.py`) runs at session start, before a file
  edit, a shell command or a web request, after a shell command, on a settings change, and
  when a subagent starts or stops. In an opted-in repository it can **refuse or ask about a
  tool call**: an edit to a protected path (secrets files, lockfiles not in the plan, a test
  the bugfix recorded, agent and tool configuration, CI workflows), a force-push, a push to
  the default branch, a skipped git hook, a merge, a code-host command that does not name its
  repository or that would list your organisations, notifications or every repository you
  can see, a push before the repository's checks passed on the commit, a command or edit
  that carries a term from your private list (`~/.config/monerex/denylist.txt`, or the file
  `MONEREX_DENYLIST` names, read if it is there), and a web search or fetch that carries a
  term or a secret. A private list that cannot be read or does not compile is a broken
  protection, so the guarded calls are refused until it is fixed (`git config
  monerex.requireDenylist false` says a repository keeps none). Secrets in commits and pushes
  are caught by the optional git hooks below.
  It runs git commands that read the repository, and no network call. It writes state and
  logs under `.monerex/state/` and `.monerex/log/` in the repository; the logs hold metadata
  (paths, counts, labels), not file contents.
- **Your checks.** `scripts/check.py` runs the test commands you list in
  `.monerex/config.json`, and records whether they passed on the current commit.
- **Build's gate.** Once build has committed a change, `scripts/ablate.py` takes every changed
  file that is not a test, a lockfile, a test-runner manifest or a path you keep back to the base
  in the working tree, runs the plan's tests, and
  writes the files back from the commit. It runs only on committed work and puts back only
  what it took out.
- **The code host.** The pull-request stages call the GitHub CLI (`gh`, through
  `bin/monerex-forge`) for the one repository you name: they read pull requests, issues,
  review threads and checks, your login (to tell your pull requests from others'), and
  `start` counts your open pull requests on larger tasks. `ship`, `feedback` and `bugfix`,
  which run only when you type them, push your branch (never by force) and may re-run a
  failed check; creating a pull request and posting a review, a reply or a comment happen
  only after you approve the exact text, which is first scanned for secrets, hidden characters
  and your private terms, and `feedback` marks the review threads it fixed
  as resolved. monerex never merges.
- **Files it writes in the repository.** Intents, plans and retro notes under
  `docs/work/<task>/`, and the retro proposals you accepted in `.monerex/proposals.jsonl`,
  meant to be committed; scratch files under `.monerex/tmp/` and worktrees under
  `.claude/worktrees/`, which the `.gitignore` lines above keep out of git. `/monerex:init`
  writes `.monerex/config.json` and adds those lines to `.gitignore`.
- **A second reviewer (off by default).** With `external_review` set to `diff-only` or `on`
  and `second_reviewer` set to `agy` (the only one supported today; it runs a program named
  `agy-ask`, a wrapper around Google's Antigravity CLI that you provide), on a review the route
  marks for it (a risk-flagged change, or a bug that resists two diagnoses), monerex sends that
  program a brief with the diff and the question, from a scratch folder in your system's
  temporary directory under `diff-only`; that folder is a starting point, not a wall. Under
  `on` it starts in the repository and can read it. That program sends what it reads to
  Google. The brief is scanned for secrets and your private terms first. With the default
  `off`, nothing is sent and the review says the second reviewer did not run.
  [capabilities.md](capabilities.md) describes what the `agy-ask` program must do.
- **An architecture checker (optional).** If the repository has an `oxn.yaml`, `start` asks
  whether `oxn` runs (`oxn` on the PATH, else `python3 -P -m oxn --version` from a neutral
  folder; `-P`, which needs Python 3.11, keeps a repository's own `oxn.py` from running in its
  place). Then `plan` runs `oxn check` and `oxn arch` and writes what they say into the plan;
  `build` runs `oxn check` on the changed files, through the implementer and again itself;
  `verify` runs `oxn check --deep`; `review` quotes `oxn review --base <base>` for committed
  work, as a report, never a gate.
- **The web.** Of monerex's agents, only the `researcher`, reached through
  `/monerex:consult research`, can search and fetch web pages; the main session keeps its own
  web tools, and the hook checks every search and fetch from either for your private terms and
  secrets. The researcher has no access to your files; its search queries and the
  addresses it fetches go to the search service and those sites, and can carry words from
  your question.
- **Background sessions.** `/monerex:start` and `/monerex:dispatch` count your open monerex
  sessions with `claude agents --json` and `ps`; only counts are printed, never session
  names or folders. `dispatch` starts a session with `claude --bg` after your yes.
- **Settings.** `/monerex:start` reads the repository's and your user settings files to see
  whether a sandbox is on. It writes no settings file: if one is missing, it shows you the
  profile to apply yourself, with `/sandbox` or by pasting it. It lists the gaps in full the
  first time and when they change, and remembers which it showed in one small file per
  checkout under `~/.local/state/monerex/posture/` (or `$XDG_STATE_HOME`): a fingerprint of
  the gap names, nothing else. Besides that file, monerex writes outside the repository only the
  second reviewer's scratch folder, removed when it is done.
- **Git hooks (optional).** `sh <a clone of monerex>/githooks/install.sh`, run inside the
  repository you want guarded, copies three git hooks into it and
  records its default branch in git config. They refuse commits and pushes that carry
  secrets, hidden characters or terms from your private list, and pushes to the default
  branch. Nothing installs them for you.
- **Routines.** `routines/` holds two prompts for scheduled cloud runs. monerex schedules
  nothing.

## Privacy

monerex keeps everything on your machine. Its logs stay in the repository's `.monerex/log/`,
the record of which security gaps you were shown stays under `~/.local/state/monerex/`, and
neither is sent anywhere. Your code leaves the machine only through tools you run and
approve: `gh` for your own repositories, and a second reviewer only when you turn one on.
The `researcher`'s web searches carry the words of the question you ask it.

## Security

The hooks are early warnings, not a boundary: matching command text can be got round, and
one command removes a git hook. They stop accidents. The boundaries are a sandbox, branch
protection on your remote, and your own review of what is merged. [SECURITY.md](SECURITY.md)
has the threat model, what each guard covers and does not, and a sandbox profile.

## Configuration

`.monerex/config.json` takes:

- `checks`: the commands that must pass before a push;
- `external_review`: `off`, `diff-only` or `on`, and `second_reviewer`: `agy`;
- `engage`: `typed` keeps the loop for the typed command only;
- `max_open_tasks`: how many background monerex sessions (started with `/monerex:dispatch`)
  may be open before `start` and `dispatch` ask; 2 by default;
- `models`: which Claude model each tier (`small`, `mid`, `large`) means; see
  `routing/routing.json`.

[Optional capabilities](capabilities.md) lists what else monerex uses when it is installed.

## Learn more

- [The playbook](docs/playbook.md): tiers, the loop, the agents, model and effort routing.
- [The evidence](docs/evidence.md): the research each rule rests on.
- [The evals](evals/README.md): how the plugin is tested by running it.

## Support

Report a problem or ask a question in
[GitHub issues](https://github.com/mustafarslan/monerex/issues).

## Development

```sh
python3 -m unittest discover -s tests -v                     # the scripts and guards
python3 scripts/audit.py                                     # secrets, hidden characters, unpinned CI actions
python3 scripts/evalgate.py run --tag smoke --max-cost-usd 8 # run the plugin for real; costs model usage
```

Real tasks held out from tuning live under `holdout/` and run only at a milestone
(`evalgate.py run --holdout --milestone <name>`).

The evals and their gate are described in [evals/README.md](evals/README.md). In a repository
with eval baselines, `ship` asks whether the gate passed on the commit when the branch changes
the plugin itself (its skills, agents, hooks, scripts, routing, workflows, evals and the like).

Load a copy of the plugin from outside the checkout you are editing: Claude Code treats every
file under a loaded plugin's folder as sensitive, so with `--plugin-dir .` each edit is asked
about.

## License

[MIT](LICENSE)
