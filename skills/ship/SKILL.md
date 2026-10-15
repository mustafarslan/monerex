---
name: ship
description: Opens a pull request for the current branch and watches its checks. The user approves the title and description before anything is posted, and the merge is always theirs. Manual only.
argument-hint: "[base branch, default the repository's default branch]"
disable-model-invocation: true
---

# Ship

The work is done and reviewed; this stage puts it in front of others under the user's name.
You never merge. `<R>` is the repository as `owner/name`; every code-host command names it.

## 1. Is it ready

- The branch is not the default branch.
- `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/check.py" --status` says the checks passed
  on this commit. If not, run them; a branch with failing or stale checks is not shipped.
- The task was reviewed. If the task log shows no review, say so and ask whether to go on.
- `git status` is clean. Uncommitted work is not part of what ships.
- If the repository has `evals/baselines.json` and the branch changes `skills/`, `agents/`,
  `hooks/`, `githooks/`, `routing/`, `workflows/`, `scripts/`, `templates/`, `bin/`,
  `.claude-plugin/`, `evals/` or `holdout/`:
  `python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/evalgate.py" status` should say the gate
  passed on this commit. If it did not run, say "eval gate: not run" and ask whether to run
  it first (`evalgate.py run --tag smoke`, in a terminal: it costs model usage) or ship
  without it. A regression is not shipped.

## 2. Push

```sh
git push -u origin "HEAD:refs/heads/<branch>"
git fetch origin "<branch>"
```

Never by force, never skipping hooks. If the guard asks about a base that has moved, bring
the branch up to date and run the checks again; do not wave it through for the user.

## 3. The text, approved first

Draft a title and a description from the plan and the diff: what changed and why, how it was
checked, what was not done. No claim the checks did not prove. Write the description to
`.monerex/tmp/pr-body.md`, scan it with
`python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/second_opinion.py" check .monerex/tmp/pr-body.md`,
and show the user the exact title and text. Ask whether to open it as a draft.

Only after they approve:

```sh
gh pr create --repo <R> --base <base> --head <branch> --title "<title>" --body-file .monerex/tmp/pr-body.md
```

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

## 5. Hand over

Report the pull request's address, the state of its checks, and anything not run. The merge
is the user's. After they merge, offer to remove the task's worktree and branch; do not
remove them unasked.
