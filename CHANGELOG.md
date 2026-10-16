# Changelog

## Unreleased

- **Retro judges its own earlier proposals.** Routing decisions are logged, accepted proposals
  are kept in `.monerex/proposals.jsonl`, and each retro says whether an earlier one moved its
  number, is a revert candidate, or has too few tasks to tell (#5).
- **Build proves its tests fail without the change.** `scripts/ablate.py` takes the committed
  change out of the working tree, reruns the tests and puts it back; a test that still passes
  is a `diligence` gap (#6). Bugfix uses the same gate with `--bugfix` (#9).
- **Evals compare with stored baselines.** `scripts/evalgate.py` runs, compares and records;
  a regression stops the change, and a `holdout/` folder is kept apart from tuning (#7). First
  baselines: 73 of 75 runs (#10).
- **`review-wide` can review a very large diff in segments**, with one more reviewer for what
  crosses them (#8).
- **A verify verdict needs a verifier that ran** (#11).
- **The reviewer looks at cost that grows with the input** and names the concrete security
  faults; review adds a performance angle where a diff touches a query, a remote call or a loop
  over outside data, and review dispatches its reviewer however small the diff. With an
  architecture gate, the plan carries its constraints and build runs its check (#12).
- **Review counts need a reviewer that ran** since the latest implementer, verify or review,
  as verify verdicts need a verifier (#13, #15). An agent counts once it has finished (#16), and
  only when the session logging the record dispatched it, in this checkout or a worktree (#16,
  #17); log times are no longer whole seconds (#16).
- **A baseline records its graders.** `evalgate.py` stores a fingerprint of each case's graders
  and does not compare a case whose graders changed since (`other-graders`) (#15).
- **Baselines at `acc094b`:** 81 of 81 runs across 27 cases; smoke with and without the plugin,
  30 of 30 against 6 of 30 (#14). Re-recorded with grader fingerprints in #15.
- **`python3 -P -m oxn`.** Without the `oxn` program on the PATH, the probe reports a command
  that cannot run a repository's own `oxn.py`, which plan, build and verify run from the
  repository (#13).
- **`/monerex:init` opts a repository in:** it finds the test command (npm, pnpm, yarn, bun,
  pytest, unittest, make, go, cargo), writes `.monerex/config.json` after the user confirms it,
  and adds the ignore lines. It never writes Claude's settings or installs git hooks.
- **`/monerex:start` with no argument says where the open task stands** and what comes next
  (`task.py status`).
- **The security profile gaps are listed in full once,** and again only when they change; in
  between, one line.
- **Review quotes `oxn review`.** With an architecture gate and committed work, the review
  report carries what `oxn review --base` measured, as a report and never a gate (#16).

## 0.2.0: first public release

- **Renamed from cortex to monerex.** "cortex" is the name of several other Claude Code
  plugins. Commands are `/monerex:<stage>`, the state folder is `.monerex/`, git settings
  are `monerex.*`, and the private term list lives at `~/.config/monerex/denylist.txt`.
- **`start` no longer writes Claude's settings.** When the sandbox is off, it shows the
  profile for you to apply with `/sandbox` or by pasting it.
- **The pre-push hook holds the default branch.** It refuses a push to `main`, `master`, the
  branch the remote's `HEAD` names or the one `githooks/install.sh` recorded, a deletion
  included, unless the owner gives `-c monerex.allowDefaultPush=1` on the command line.
- **A push waits for checks on what it pushes.** With the checks gate on, a push or
  `gh pr create` after a command in the same line that moves a branch is refused.
- **The shell guard reads more of what a shell runs:** a push after a checkout in the same
  line, `sh -c` and `eval` in the order they run, heredoc bodies as data, wrappers by name,
  and the spellings that would switch the git hooks off.
- **Fixes found while preparing the release:** a protected file changed by a shell command
  is reported even when git fails to say where HEAD is; the two incident cases for it grade
  the guard's own log, not the model's wording of the report; the `oxn` probe no longer runs a
  repository's own `oxn.py`; worktrees under `.claude/worktrees/` no longer make the checks
  record an unclean tree.
- MIT license; a README that lists everything monerex runs, reads, writes and sends.

### Upgrading from cortex (0.1.0)

Nothing reads the old names. In each repository that used cortex:

- Rename `.cortex/` to `.monerex/`, and the ignore lines in `.gitignore` with it.
- Rename git settings: `git config --get-regexp '^cortex\.'` lists them; set each again as
  `monerex.<name>` and unset the old one.
- Remove the old git hooks (`pre-commit`, `commit-msg`, `pre-push` and `cortex_scan.py` in
  the hooks folder) and run `sh githooks/install.sh` again; the installer leaves hooks it
  does not recognise alone.
- Move `~/.config/cortex/denylist.txt` to `~/.config/monerex/denylist.txt`, and update any
  sandbox rule that hides the old folder.

## 0.1.0

The loop, the pull-request stages, the agents, routing, the guards, the evals and the saved
workflows, developed in a private repository.
