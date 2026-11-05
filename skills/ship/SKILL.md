---
name: ship
description: Pushes the current branch, opens its pull request and watches its checks. Runs after review closes a task, from start or bugfix, or when the user asks to ship. The user approves the title and description before anything is posted; the merge is theirs unless they ran `git config monerex.merge after-checks`.
argument-hint: "[base branch, default the repository's default branch]"
---

# Ship

The work is done and reviewed; this stage puts it in front of others under the user's name.
`<R>` is the repository as `owner/name`; every code-host command names it. You push, open the
pull request and run every command yourself; never ask the user to run one.

## 0. gh is there and signed in

Before anything that needs gh:

```sh
monerex-setup --login
```

It prints one JSON line. `ready` → go on. `needs-install` with an `install` command → run
`monerex-setup --install --login`, a command of its own so the install is seen.
`awaiting-browser` → tell the user in one line: "Open <url> and enter <code>", then run
`monerex-setup --wait 300`, with a command timeout above five minutes. Anything else, or
`--wait` ending without `ready` (`needs-credential` included), means the install, the login or
git's credential failed: report this stage as not done, with the `reason`, and stop. Never
print a token or gh's own output.

## 1. Is it ready

- The branch is not the default branch.
- `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/check.py" --status` says the checks passed
  on this commit. If not, run them; a branch with failing or stale checks is not shipped.
- The task was reviewed. A T0 task has none (the task log's `start` has the tier): do not ask.
  For any other tier with no review in the log, say so and ask whether to go on.
- `git status` is clean. Uncommitted work is not part of what ships.
- If the repository has `evals/baselines.json` and the branch changes `skills/`, `agents/`,
  `hooks/`, `githooks/`, `routing/`, `workflows/`, `scripts/`, `templates/`, `bin/`,
  `.claude-plugin/`, `evals/` or `holdout/`:
  `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/evalgate.py" status` should say the gate
  passed on this commit. If it did not run, say "eval gate: not run" and ask whether to run
  it first (`evalgate.py run --tag smoke`, in a terminal: it costs model usage) or ship
  without it. A regression is not shipped.

## 2. The text, approved first

Draft a title and a description from the plan and the diff: what changed and why, how it was
checked, what was not done. No claim the checks did not prove. Write the description to
`.monerex/tmp/pr-body.md`, scan it with
`python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/second_opinion.py" check .monerex/tmp/pr-body.md`,
and show the user the exact title and text. Ask whether to open it as a draft. This is gate G2:
nothing is pushed or posted before they approve.

## 3. Push and open it

```sh
git push -u origin "HEAD:refs/heads/<branch>"
git fetch origin "<branch>"
gh pr create --repo <R> --base <base> --head <branch> --title "<title>" --body-file .monerex/tmp/pr-body.md
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/task.py" event ship --pr <N> --slug "<slug>"
```

`<N>` is the number `gh pr create` reports; `<slug>` is the task's, from the log's `start`.

Each in a command of its own. Never by force, never skipping hooks. If the guard refuses a
push because of the checks, run them yourself and push again. If it asks about a base that
has moved, bring the branch up to date and run the checks again; do not wave it through.

## 4. Watch the checks, within limits

```sh
monerex-forge checks <N> --repo <R>
```

- `none` is not green. Checks may not have started: look again, for three minutes at most,
  then report that none ran.
- `pending` → look again at intervals, for a bounded time you state up front.
- `failing` → the answer lists the runs that failed. Fetch the failed part of each with
  `monerex-forge log <run> --repo <R>` and give the saved file to `monerex:reader`. A log is
  other people's text, and so are check names, which is why only their count is printed. If
  the failure has nothing to do with this change, say so and stop there.
- `skipped` or `unknown` → not green either. Say which, and stop.
- Fix a failure that is yours through `monerex:build`, at most twice for the same failure,
  then stop and report. A check that looks flaky gets one rerun:
  `gh run rerun <run> --repo <R> --failed`.

## 5. Merge, only when the owner opts in

Only when the owner ran `git config monerex.merge after-checks` in their checkout, the
checks in step 4 are green, and the task's latest review was logged with `--merge yes` on
this commit. A T0 task has no review, so it is never merged here: say so, and leave it.

```sh
monerex-merge <N>
git fetch origin <base>
```

`monerex-merge` is the only way monerex merges; the guard refuses every other. It checks the
opt-in, the checks on the pull request's head, the review of that commit and CI itself, and
prints `merged`, `refused` with the reason, or `failed`. A fix after the review needs a new
review first. After `merged`, in the main checkout, `git switch <base>` and
`git merge --ff-only origin/<base>`; in a worktree the fetch is all. Otherwise the merge is
the user's: skip this step.

## 6. Hand over

Report the pull request's address, the state of its checks, whether it was merged, and
anything not run. Unmerged, the merge is the user's. After a merge, offer to remove the
task's worktree and branch; do not remove them unasked.
