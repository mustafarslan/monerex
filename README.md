# monerex

**A gated way of working for Claude Code.** monerex turns a task into a short, checked loop:
it sizes the work, writes down the intent and the plan, has one agent build it test-first,
has a fresh agent verify it, and has another review it before anything leaves your machine.
Each agent runs with an explicit model and effort. The rules that must hold, such as "no
push to the default branch" or "the checks passed on this commit", live in hooks, not in
prompts. You approve three things: the plan, any text posted under your name, and the merge.
Nothing else needs you, and nothing goes out without you.

monerex is for Claude Code only. It runs Python 3 scripts and ships a `bin/` folder, so
claude.ai and Cowork do not install it.

**Status: early, 0.2.0.** The whole loop and the pull-request stages have run for real on
this project, and the guards have been through several review rounds. Treat it as a careful
first release, not a finished product.

## Install

```
/plugin marketplace add mustafarslan/monerex
/plugin install monerex@monerex
```

Requirements: Claude Code, Python 3 (CI runs the tests on the runner's Python 3), and git. The pull-request stages also need
the GitHub CLI (`gh`), signed in. The owner's override of the default-branch rule needs
git 2.26 or later.

**Installing changes nothing until a repository opts in.** The hooks start on every tool
call, find no `.monerex/config.json`, and stop: they refuse nothing, ask nothing and write
nothing. To opt a repository in, create that file:

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

## Three ways to use it

**Make a change.** `/monerex:start add a CSV export to the report page`. monerex sizes the
task, asks what it needs to know, shows you the plan, and after your yes builds it with
tests, verifies it in a fresh context and reviews it. You can also just ask for the change in
plain words in an opted-in repository.

**Review a pull request.** `/monerex:review 42` reviews pull request 42 from its diff,
without checking its code out (it runs a same-repository pull request's checks in a separate
worktree only when that matters, and never runs a fork's code), checks every finding before
reporting it, and posts nothing until you have read and approved the exact text. `/monerex:review` with no number reviews your current changes.

**Fix a reported bug.** `/monerex:bugfix 1234` takes issue 1234 from its report to a draft
pull request: it reproduces the bug with a failing test, fixes the cause, checks that the
test fails again without the fix, verifies, reviews, and shows you the pull request text
before opening it.

The rest: `/monerex:ship` opens a pull request for the current branch; `/monerex:feedback`
works through the review comments on your own pull request, with every reply approved by you
first; `/monerex:consult` asks a specialist (`research`, `ml`, `data`); `/monerex:retro`
reads the task log and proposes changes to the method; `/monerex:dispatch` starts a task in
another repository as a background session, after your yes. Four saved workflows cover work
too large for one pass: `/monerex:review-wide`, `/monerex:audit`, `/monerex:plan-from-angles`
and `/monerex:migrate`. They run only when you start them.

## What monerex runs, reads, writes and sends

Everything monerex does is in readable Python, shell and Markdown in this repository. It has
no server, sends nothing to its author, and collects no telemetry.

- **Hooks.** A Python script (`hooks/monerex_hook.py`) runs at session start, before a file
  edit, a shell command or a web request, after a shell command, on a settings change, and
  when a subagent starts or stops. In an opted-in repository it can **refuse or ask about a
  tool call**: an edit to a protected path (secrets files, lockfiles not in the plan, a test
  the bugfix recorded, Claude and git configuration, CI workflows), a force-push, a push to
  the default branch, a skipped git hook, a merge, a code-host command that does not name its
  repository, a push before the repository's checks passed on the commit, a command or edit
  that carries a term from your private list (`~/.config/monerex/denylist.txt`, or the file
  `MONEREX_DENYLIST` names, read if it is there), and a web search or fetch that carries a
  term or a secret. Secrets in commits and pushes are caught by the optional git hooks below.
  It runs git commands that read the repository, and no network call. It writes state and
  logs under `.monerex/state/` and `.monerex/log/` in the repository; the logs hold metadata
  (paths, counts, labels), not file contents.
- **Your checks.** `scripts/check.py` runs the test commands you list in
  `.monerex/config.json`, and records whether they passed on the current commit.
- **The code host.** The pull-request stages call the GitHub CLI (`gh`, through
  `bin/monerex-forge`) for the one repository you name: they read pull requests, issues,
  review threads and checks, your login (to tell your pull requests from others'), and
  `start` counts your open pull requests on larger tasks. `ship`, `feedback` and `bugfix`,
  which run only when you type them, push your branch (never by force) and may re-run a
  failed check; creating a pull request and posting a review, a reply or a comment happen
  only after you approve the exact text, and `feedback` marks the review threads it fixed
  as resolved. monerex never merges.
- **Files it writes in the repository.** Intents, plans and retro notes under
  `docs/work/<task>/`, meant to be committed; scratch files under `.monerex/tmp/` and
  worktrees under `.claude/worktrees/`, which the `.gitignore` lines above keep out of git.
- **A second reviewer (off by default).** With `external_review` set to `diff-only` or `on`
  and `second_reviewer` set to `agy` (the only one supported today; it runs a program named
  `agy-ask`, a wrapper around Google's Antigravity CLI that you provide), monerex sends that
  program a brief with the diff and the question, from a scratch folder in your system's
  temporary directory under `diff-only`; that folder is a starting point, not a wall. Under
  `on` it starts in the repository and can read it. That program sends what it reads to
  Google. The brief is scanned for secrets and your private terms first. With the default
  `off`, nothing is sent and the review says the second reviewer did not run.
  [capabilities.md](capabilities.md) describes what the `agy-ask` program must do.
- **An architecture checker (optional).** If the repository has an `oxn.yaml`, `start` asks
  whether `oxn` runs (`oxn` on the PATH, else `python3 -m oxn --version` from a neutral
  folder), and `plan` and `verify` then run `oxn check` and `oxn arch`.
- **The web.** Only the `researcher` agent, reached through `/monerex:consult research`, can
  search and fetch web pages. It has no access to your files; its search queries and the
  addresses it fetches go to the search service and those sites, and can carry words from
  your question.
- **Background sessions.** `/monerex:start` and `/monerex:dispatch` count your open monerex
  sessions with `claude agents --json` and `ps`; only counts are printed, never session
  names or folders. `dispatch` starts a session with `claude --bg` after your yes.
- **Settings.** `/monerex:start` reads the repository's and your user settings files to see
  whether a sandbox is on. It writes no settings file: if one is missing, it shows you the
  profile to apply yourself, with `/sandbox` or by pasting it.
- **Git hooks (optional).** `sh <a clone of monerex>/githooks/install.sh`, run inside the
  repository you want guarded, copies three git hooks into it and
  records its default branch in git config. They refuse commits and pushes that carry
  secrets, hidden characters or terms from your private list, and pushes to the default
  branch. Nothing installs them for you.
- **Routines.** `routines/` holds two prompts for scheduled cloud runs. monerex schedules
  nothing.

## Privacy

monerex keeps everything on your machine. Its logs stay in the repository's `.monerex/log/`
and are never sent anywhere. Your code leaves the machine only through tools you run and
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
- `max_open_tasks`: how many tasks may be open before `start` asks;
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
python3 -m unittest discover -s tests -v     # the scripts and guards
python3 scripts/audit.py                     # secrets, hidden characters, unpinned CI actions
```

Load a copy of the plugin from outside the checkout you are editing: Claude Code treats every
file under a loaded plugin's folder as sensitive, so with `--plugin-dir .` each edit is asked
about.

## License

[MIT](LICENSE)
