# Changelog

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
