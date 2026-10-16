# Security

Monerex runs agents that read text you did not write, edit your files, run shell commands and
push code. This page says what monerex does about that, what it cannot do, and what you have to
set up yourself.

**Status:** the git guards, the tool-level guards and the nine agents are built and tested.
Rows marked *planned* are design, not code. The sandbox profile below was applied to this
repository and exercised once; [what held and what did not](#what-the-profile-does-and-does-not-do)
is listed with it. Four things were checked in a live session with the plugin loaded: an agent's tool list
holds (`reader` and `ml-specialist` have no shell, `researcher` has web tools and nothing
else), an agent runs at the effort its definition names, the guard fires inside a subagent,
and `researcher` starts without your instruction files or memory in its context.

## The model

Private data, untrusted text and an outbound channel are dangerous in one context. Monerex
narrows what untrusted text reaches the main session, but what actually breaks the chain is
that **every outbound action has a human gate in front of it**: you approve outward text, and
you merge. Controls are structural — tools, sandbox, hooks, gates. None relies on a model
noticing an attack. [The evidence](docs/evidence.md#security) is why.

## What monerex cannot do

A plugin ships skills, agents, hooks and workflows. It **cannot** ship sandbox or permission
settings. Installing monerex does not turn a sandbox on. Monerex documents the profile below,
and `/monerex:start` checks six of its settings (sandbox on, unsandboxed retry off, fail when
the sandbox cannot start, no host approved in advance, a push always asks, secrets files
cannot be read) in the repository's and your user settings files. It does not see the rest
of the profile (`excludedCommands`, the credential and `gh` rules) or settings passed with
`--settings`, so "in place" means those six. When gaps remain, monerex warns, shows the
profile for you to apply with `/sandbox` or by pasting it, explains the alternatives, and
carries on. It never writes a settings file and never blocks on a missing sandbox. It lists
the gaps in full the first time and when they change, and in one line otherwise; which list
it showed is kept per checkout under `~/.local/state/monerex/posture/` (or `$XDG_STATE_HOME`),
a fingerprint of the gap names and nothing else, outside the repository so a clone cannot
plant a record that hides the list or a link that overwrites a file. Closing every gap
deletes it.

## Threats and controls

| Threat | Control | State |
|---|---|---|
| **Prompt injection** through issues, PR comments, review-bot output, web pages, dependency docs, tool results | Untrusted text is fetched to a scratch file unseen and turned into a fixed schema of claims by a `Read`-only `reader` agent. Every claim is verified against the code before anything is done about it; no claim can authorise an action. | **built**, run against a live pull request: `monerex-forge` fetched its state, diff, comments and checks to files and printed only counts; `reader` turned a real comment into a claim; an approved reply was posted to its thread and the thread resolved |
| **Excess privilege** | Explicit tool lists per agent. Only the main session pushes or posts, after a gate. | **built**, checked live |
| **Exfiltration and secrets** | Sandbox profile that closes the file system outside the project and puts every network host behind an approval; deny-read rules for secrets files; secret scan on commit and push. | profile below, exercised once; it does not block the network outright; scan **built** |
| **Confidential names reaching a repo** | Private denylist scanned by git's own hooks on commit and push. | **built** |
| **Code leaving the machine** to a second reviewer or a web tool | Per-repo policy `external_review: off / diff-only / on`, default off. The only agent with web tools cannot read the repository; a web request carrying a denylisted term or a secret is refused. | **built**: the brief is scanned before it leaves; under `diff-only` the second reviewer starts in a scratch folder holding only the brief, a starting point rather than a wall, and under `on` it starts in the repository |
| **An agent that reads the web** — untrusted pages and an outbound channel in one context | `researcher` has web search and fetch and nothing else: no file tools, no shell, and no instruction files or memory in its context. What it knows is its brief. Its report is untrusted text; `consult` re-checks the claims a decision rests on in a second run before they are used. | **built**, checked live |
| **Destructive actions** | Shell guard: no force-push, no push to the default branch, no `--no-verify`, no merging a pull request. The pre-push hook refuses a push to the default branch from the refs git really pushes, in a clone where it is installed and left in place; one command removes it, so it stops accidents, not an agent set on getting round it. Branch protection on the remote is the only stop that is not on this machine; GitHub offers it for a private repository only on a paid plan. | guard and pre-push rule **built** |
| **Agent rewriting its own guards** | Edits to `.claude/`, `.mcp.json`, instruction files, `.git/`, hook scripts, CI workflows (`.github/`, `.gitlab-ci.yml`), editor settings (`.vscode/`), `.monerex/config.json` and `.monerex/state/`: denied for subagents, asked for the main session. Paths are resolved through symlinks. | **built**, checked live |
| **Supply chain** | Lockfiles are closed unless the plan lists them; hooks are standard-library Python with no network. A new or upgraded dependency is a risk flag that needs your explicit yes, and optional capabilities are a named list (`capabilities.md`), not whatever is installed. | lockfile guard **built** |
| **Insecure generated code** | Threat note in the plan for risk-flagged work; security dimension in review; deterministic scanners where the repo has them. Model review supplements them and is never the gate. | threat note and review **built**; scanners planned |
| **Tasks side by side** — several sessions, several repositories, one person approving | Each task is its own session in its own repository, or in its own worktree when the repository already has one; no session can approve for you or read another's work. The count of open tasks is a number: names and directories of other sessions are never printed. A limit on open tasks asks before it is passed. | **built**. Under the sandbox profile a session can neither start another one nor read the session list (both observed): the command is handed to you to run, and the count says it cannot tell instead of reporting zero. A full dispatch has not been exercised |
| **Unattended runs** | Trigger payloads are untrusted; no write credentials on triggers outsiders can fire; writes only to a dedicated branch prefix. | CI **built**: the job that runs on push and pull request holds no secret, a read-only token and no third-party action; the job that holds the model API key runs only when started by hand. Two routine definitions ship as prompts that read and report only; none is scheduled by monerex |

## The tool-level guards

[`hooks/monerex_hook.py`](hooks/monerex_hook.py) runs before every edit, shell command and web
request, in a repository that has opted in with a `.monerex/config.json`. Without that file it does nothing.

- **Edits:** agent configuration, secrets files, lockfiles and the guards themselves are denied
  for a subagent and asked for the main session. A subagent cannot write outside the
  repository. A path in `.monerex/state/protected-paths` is read-only for everyone: an entry
  guards the file of that name in the checkout whose list holds it, and an entry in the
  owner's checkout guards it in every worktree of the repository. The list of another
  checkout of the same repository is agent configuration too, wherever the call comes from.
  Names are matched without regard to case, and through symlinks; folders are compared by
  what they are, so a folder typed in another case is the same folder. An entry without glob
  characters also guards the file it leads to, by identity: a link and a second hard link to
  it are guarded whichever of the names the task recorded, and an entry spelled `./tests/x`
  or as a full path matches, once the file exists. An entry with glob characters is matched
  against names only. A link named like agent configuration (`CLAUDE.md`,
  `.claude/settings.json`) is classified by
  its own name as well as by what it points at. Not covered: an entry with a trailing slash;
  a glob entry spelled as no path is (`./tests/*`); the target of a link named like
  configuration, edited under the target's own name; a hard link to a configuration file; from a
  worktree of a repository whose git directory is kept apart from its checkout the owner's
  list cannot be found, so only the worktree's own applies; and a session started outside
  the repository is not a monerex session, whatever file it edits. These rules cover the
  **edit tools**.
  A shell command that writes the same file is not stopped; it is noticed afterwards. The
  guard records what the protected files at the repository root, the agent-configuration
  folders, the two task lists and the task's protected paths look like before each shell
  command, compares afterwards, and tells the agent and the log when one changed. Each call
  has its own record, links are followed, and the allowed list is read before the command
  runs, so a command cannot allow a file and then change it. Not covered: the copy of a
  protected file in another checkout than the one the command ran in, and a command that
  moved the branch or made a commit, a command still running in the background, protected
  files deeper in the tree, and anything else that writes one of these files at the same
  moment, which is reported as if the command had. A file whose time or size moved but that
  now holds exactly what HEAD has for it is not reported: build's ablation gate writes the
  change back that way, with a fresh time. So a command that puts an uncommitted edit of a
  protected file back to the committed version is not reported either.
- **Shell:** no force-push, no push to the default branch (including `--all` and `--mirror`),
  no skipped or redirected hooks, no merge. A subagent cannot push or open a PR. When the
  repository lists `checks`, a push or PR needs a record from `scripts/check.py` showing they
  passed on exactly the commit being pushed, with nothing uncommitted in the tree. A push that
  does not contain the newest commits of the default branch, as last fetched, is asked about:
  the checks ran on an older base. Where a command sends its output is left out before it is
  judged, wherever the redirection stands, and a separator in quotes (`';'`) is an argument,
  not the end of the command, a line joined by a backslash is one line, and a comment is not
  a command. This reading is held against a real shell: `tests/test_shell_reading.py` runs
  some two hundred shapes of command through `sh` with stand-ins for `git` and `gh`, and
  every call the shell makes must be one the guard judged. The commands of a line are judged
  in the order they are written, those inside `sh -c` and `eval` in the place of the command
  that holds them, and a shell given its script after other flags (`bash -lc`,
  `bash -c -- ...`, `bash -o pipefail -c ...`) is read as one given it plainly, and so is one
  given bash's long options with one dash (`bash -noprofile -lc ...`, `bash -login -ec ...`).
  The body of a here-document is data for its command and is not read as commands; the
  denylist still reads it. With an unquoted delimiter what a `$(...)` in the body holds is read,
  since that runs, and nothing else of the body; a `<<` inside `$((...))`, `$[...]`, `${...}` or a subscript starts no heredoc,
  and the delimiter has its quotes removed as the shell removes them. A push that
  follows HEAD is judged on the branch an earlier `git checkout` or `git switch` in the same
  command leaves, as well as on the one checked out when the command was submitted. A
  checkout is recorded where git is the command: alone, or after a wrapper the guard knows,
  its flags and assignments (`env -i`, `sudo`, `FOO=1`), a wrapper spelled as a path
  (`/usr/bin/env`) included; the words after `echo` or `printf` are text, a shell or `eval`
  among them included, so `echo eval git checkout master && git push` is judged on the branch
  it is on. A name that is a local branch, one a remote has, or the default branch's name,
  even when it is not there yet (a `git fetch` earlier in the line may bring it in), is a
  branch. A checkout of a name that is no branch but a commit (a tag, an id, `HEAD~1`,
  `origin/master`), and `git checkout --detach` or `git switch --detach`, leave HEAD on no
  branch, and a push from there is judged on the branch checked out at submission. Any other
  name is a file, and a checkout of a file leaves the branch recorded before it;
  `git checkout -` goes back to the branch before the last checkout in the line, past a
  detached HEAD too. Not covered: quoting the splitter does not
  model, such as `$'...'` and `$(...)`, where a command can be refused for what is only text
  in a message and a command inside one can go unseen; a command in backticks, which is not
  judged, so a checkout inside one is not recorded; a loop or function body, which is judged
  where it is written, not when or how often it runs, so
  `f() { git push; }; git checkout master && f` passes, and
  `f() { git checkout master; }; git push` is refused though `f` is never called; `&&`, `||`
  and `if ... else ... fi`, which are read as if every branch ran, in both directions: a
  fallback that never runs replaces the checkout that did, so
  `git checkout master && git pull || git checkout feature; git push` passes while the shell
  pushes `master`, and a checkout that never runs counts, so
  `false && git checkout master; git push` is refused though the shell pushes the branch it
  is on; a wrapper the guard does not know,
  or one with a flag that takes a value, such as `sudo -u root` or `timeout 5`, which hides
  the checkout after it; a branch made by `git branch` earlier in the line, which is not
  known, so a checkout of it is taken for a file, unless it is the default branch's name;
  variables, so a push of `$b` is judged as
  a push of something unknown, and a checkout of `$b` or `@{-2}`, or of `-` with no checkout
  before it in the line, is not read at all; a checkout that fails, which the guard cannot
  tell from one that worked, so after `git checkout master; git checkout other`, where the
  second fails, the push is judged on `other` and the submitted branch, not on `master`; and
  the other ways HEAD can move inside a line: `git branch -m` and `-M`, `git symbolic-ref HEAD`,
  `git rebase <upstream> <branch>`, `git stash branch`, `git checkout heads/master` (only
  `refs/heads/` is taken off), aliases and scripts, `cd` and `pushd`, `--git-dir` and
  `GIT_DIR=`, `echo ... | sh`, a heredoc fed to a shell (`sh <<EOF`, `cat <<EOF | sh`,
  `bash -s <<EOF`), whose body is not read, nesting deeper than three, and a config override such as
  `-c remote.origin.push=...`. Where the checks gate is on, a push or `gh pr create` after a
  command in the same line that can move a branch (`commit`, `merge`, `pull`, `rebase`,
  `reset`, `cherry-pick`, `revert`, `am`, `checkout` and `switch` other than a path restore
  or a new branch made where HEAD is, `branch -f`, `-m`, `-M`, `-C`, `stash branch`,
  `update-ref`, `symbolic-ref`, a `fetch` into a local branch) is refused, since the checks
  cannot have run on what it pushes; the push goes in a command of its own once they have.
  That refuses `git checkout other && git push` even when `other` passed: two commands.
  `git checkout -b topic && git push -u origin topic` is judged on HEAD's commit. The base of a push is still looked up
  for the commit checked out when the command was submitted. For the default branch, the
  pre-push hook's branch rule (below) sees the real refs and closes all of these, in a clone
  where it is installed and left in place. The guard also refuses what would switch the
  hooks off in the spellings it reads: `core.hooksPath` given with `-c`, `--config-env`,
  `GIT_CONFIG_*`, in an alias or written with `git config`; a config include
  (`include.path`, `includeIf.*`, and `GIT_CONFIG_GLOBAL` or `GIT_CONFIG_SYSTEM` pointing
  anywhere but `/dev/null`); writes to `monerex.*` settings, the whole section's removal or
  renaming included; and `rm`, `mv`, `chmod`, `tee` and the like on a path in this
  repository's hooks folder, `cp`, `ln` and `install` with it as the destination, and a
  redirection into it, inside `sh -c` and `eval` too. Another repository's hooks, a bare
  one's, and a copy made from a hook are not refused. A script, an alias that runs one, a key built
  from a variable, or any program the guard does not know still does it.
- **Logs:** after a commit made through the shell tool, one line goes to
  `.monerex/log/commits.jsonl`: commit, branch, changed paths, session and the agents that ran
  in it. Beside it: `tasks.jsonl` (stage events as counts and labels), `routing.jsonl` (each
  agent's start and stop, pointing at its transcript without copying it), `guard.jsonl` (what
  a guard refused or saw changed), `config-changes.jsonl` and `evalgate.jsonl`. The logs are
  local and git-ignored (`/monerex:init` adds the lines). Two outputs are committed instead:
  `.monerex/proposals.jsonl`, the retro changes you accepted, and `evals/baselines.json`.
- **Code host:** a command that acts on one repository (pull requests, issues, runs and the
  like) must name it with `--repo`, or it is asked about, and refused to a subagent. A
  command that lists what an account belongs to, or searches across every organisation it
  can see, is refused. The refusal is tested with a stand-in path, not the real ones.
- **Web:** a search query, a fetched address or a fetch prompt that carries a denylisted term,
  a credential or a hidden character is refused. The `monerex:allow` marker that accepts a
  false positive on a committed line has no effect here.
- **All three:** a denylisted term in the text being written, run or sent is refused.

A guard that fails denies the call, and so does a denylist with a line that does not
compile. These are early warnings: matching a command's text is defeated by encoding, by a
script that runs the command for you, and by anything the parser does not model. The
boundaries are the sandbox, the git guards and branch protection.

## Workflows

The four saved workflows start several agents at once. What limits them is the same as for
any dispatch: each agent is a monerex agent with its own tool list, on a route copied from the
routing table and checked against it by a test. `migrate` is the only one that writes: each
of its writers works in its own worktree, commits nothing, and has its work checked by a
verifier before the site is called ready. A site nobody verified is listed as unverified.

`review-wide`, `audit` and `plan-from-angles` have each run in the real runtime, inside an
evaluation. What that showed: the agents they started were monerex's own, on the models the
scripts name, and the guard that logs every agent start saw each of them. A separate case
shows an agent's tool list holding inside a workflow: a scout told to create a file could
not, and none appeared. `migrate` cannot run to success in an evaluation: the harness does
not give an agent a worktree of its own. What is seen there is its failure, which says why,
calls no site ready and leaves the main checkout untouched. It has run to success once in an
ordinary session: three sites, each changed in its own worktree and checked there.

## The specialists

Three agents answer questions instead of running the loop. What each can reach:

| Agent | Reads the repository | Shell | Web | Left open |
|---|---|---|---|---|
| `researcher` | no | no | yes | Its brief is written by the main session; whatever is put there can leave as a search term. The web guard catches denylisted terms and credentials, nothing subtler. |
| `ml-specialist` | yes | no | no | Nothing beyond what `reviewer` has. |
| `data-scientist` | yes | yes | no web tools | A shell can write files and reach the network. It is told to change nothing; `consult` compares the working tree before and after and reports any difference. The sandbox profile below keeps its writes inside the project; only the strict network setting keeps its commands offline. |

The researcher's isolation rests on two things a plugin can set — its tool list and
`omitClaudeMd` — and both were checked in a live run. Its context still carries the working
directory's path and a git status summary, which the harness adds for every agent.

## The git guards

Three hooks — `pre-commit`, `commit-msg`, `pre-push` — run one scanner,
[`githooks/monerex_scan.py`](githooks/monerex_scan.py). They are git's own hooks, so they cover a
commit typed by hand as well as one an agent makes.

They scan added lines and commit messages, in every commit of a push too (so a term added
and later removed is still caught), for all three of the following; file paths, the branch
name, pushed ref names and the remote's name and URL for denylisted terms only:

- **Denylisted terms** — your private list, e.g. an employer or client name.
- **Likely secrets** — private key blocks, cloud and code-host tokens, hard-coded credentials.
- **Hidden characters** — bidirectional controls, zero-width space, and the Unicode tag block.

A finding names the place and the rule, never the matched text.

`pre-push` also refuses a push to the **default branch**: any pushed ref whose remote ref is
`refs/heads/main`, `refs/heads/master`, or the branch `refs/remotes/<remote>/HEAD` or
`refs/remotes/origin/HEAD` names, a deletion included. It reads the refs git is about to
push, so it does not depend on how the command was spelled. The owner lets one push through
with `git -c monerex.allowDefaultPush=1 push ...`, for the first push of a new repository
say; the secret and term scan still runs. The setting counts only when it is given on the
command line: one saved in a config file is ignored, and the tool guard refuses it from an
agent in every spelling it reads (`-c`, `--config-env`, `GIT_CONFIG_*`, `git config`, an
alias body that carries it). It needs git 2.26 or later (`git config --show-scope`); with an
older git the override is never honoured. `install.sh` records the default branch in
`monerex.defaultBranch` while `origin/HEAD` names it, so the rule still holds a branch named
other than `main` or `master` after that ref is removed. A deletion that `--mirror` makes is
not passed to the hook, so the rule does not see it; the tool guard refuses `--mirror`.

### Set up

```sh
mkdir -p ~/.config/monerex
$EDITOR ~/.config/monerex/denylist.txt   # one term per line; `re:` starts a regex; `#` a comment
sh githooks/install.sh                   # copies the hooks into this clone, uncommitted
git config monerex.requireDenylist true   # optional: block when the denylist is missing or empty
```

The denylist lives outside every repository and is never committed. A denylist that is there
but cannot be read stops the commit, unless the repository has
`monerex.requireDenylist` set to `false`. `MONEREX_DENYLIST` points
at a different file. A false-positive secret or hidden-character finding is accepted by putting
`monerex:allow` on that line. A denylisted term cannot be accepted.

### Limits

These guards stop **accidents**. They are defeated by encoding a term, and by `--no-verify`.
They are not a control against someone trying to get a term through; the control for that is
review and server-side branch protection.

They guard only a clone where `githooks/install.sh` has been run, and only while the hooks
are left in place: one command (`rm .git/hooks/pre-push`, `git config core.hooksPath ...`)
takes them away. The tool guard refuses the spellings of that it reads, which stops an
accident; nothing on this machine is a boundary against an agent that sets out to remove
them. A fresh clone, another
machine, a CI job and a cloud routine's checkout have no hook, and nothing there stops a push
to the default branch but the tool guard, where monerex is loaded. Only branch protection on
the remote covers every copy. GitHub refuses it for a private repository on the free plan
(the API answers 403): it needs a paid plan or a public repository. The secret patterns are a short list, not a
replacement for a dedicated scanner.

## Sandbox and permission profile

Put this in the repository's `.claude/settings.local.json`, which is uncommitted. It affects
that repository only.

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "network": { "allowedDomains": [] },
    "excludedCommands": ["git push *", "git fetch *", "git pull *", "git clone *", "gh *"],
    "credentials": {
      "files": [
        { "path": "~/.ssh", "mode": "deny" },
        { "path": "~/.aws/credentials", "mode": "deny" }
      ],
      "envVars": [
        { "name": "GITHUB_TOKEN", "mode": "deny" },
        { "name": "GH_TOKEN", "mode": "deny" },
        { "name": "NPM_TOKEN", "mode": "deny" }
      ]
    }
  },
  "permissions": {
    "ask": [
      "Bash(git push *)",
      "Bash(gh *)",
      "Bash(dangerouslyDisableSandbox:true)"
    ],
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Read(~/.ssh/**)",
      "Read(~/.aws/**)",
      "Read(~/.config/monerex/**)"
    ]
  }
}
```

Why each part is there:

- **Empty `allowedDomains`.** No host is approved in advance. This is **not** "no network";
  see below. The list stays empty because the sandbox proxy does not inspect encrypted
  traffic, so any broad allowed domain — a code host, a paste service — is a way out.
- **`excludedCommands`.** Git over SSH cannot get through the sandbox proxy, so a push or a
  fetch fails inside it. The code-host commands are listed so they run outside the sandbox
  and go through the permission flow. Add your package installer the same way, and anything else that must reach the network or write outside the project: `monerex-forge *` for the pull-request stages, a second-opinion tool, or the eval runner. The match is
  on the whole command line: a call that chains another command, redirects to a file, changes
  directory or uses `$(...)` stays sandboxed, and a git command over SSH then fails.
- **`ask` rules.** In auto mode a classifier, not you, approves an excluded command, and it is
  reported to miss a share of overeager actions. An `ask` rule holds in every mode, so a push
  is always yours to approve.
- **`deny` rules.** The sandbox covers shell commands only. The file tools, hooks and servers
  run outside it, so secrets files need their own read rules. The rule for `~/.config/monerex`
  keeps the denylist away from the agent, and the sandbox applies the same rule to shell
  commands. A commit made from inside the sandbox may therefore be unable to read the
  denylist; the git guard then stops the commit instead of skipping the list. If you keep a
  denylist, commit yourself or add `git commit *` to `excludedCommands`. A push is already
  excluded. This case was not exercised: the pilot keeps no denylist.

### What the profile does and does not do

Exercised once, in October 2026, in a session running in auto mode.

| Check | Result |
|---|---|
| The repository-local file turns the sandbox on without a restart | held |
| A write outside the project is refused | held |
| A command that touches `~/.ssh` is refused | held |
| `git fetch`, an excluded command, works | held |
| A git network command that is not excluded fails | held |
| A push and a pull-request command ask you first | held |
| A write to `.git/hooks` from a sandboxed command is refused | held — so `githooks/install.sh` is yours to run |
| A plain web request from a sandboxed command is blocked | **did not hold** — the request went through |

The last row is the important one. A host that is not on the allowed list is not refused
outright. What happens depends on the permission mode: in the default mode you are asked; in
auto mode a classifier decides, and it allowed a command that named its host. So with this
profile alone, the network is behind an approval, not behind a wall.

A wall needs `sandbox.network.strictAllowlist: true`, which refuses every host outside the
list in every mode. A repository's own settings cannot set it; it has to come from your user
settings or from the command line when a session starts:

```sh
claude --settings '{"sandbox":{"network":{"strictAllowlist":true}}}'
```

That flag is described in the product documentation and has not been tried here. With it on,
anything that needs the network from a shell — a package install, a second-opinion tool, the
eval runner — must be added to `excludedCommands` or run by you. Not a headless Claude
session: `claude -p` with pre-approved tools approves every shell command it will run, so it
belongs *inside* the sandbox or a container, never excluded from it (the playbook's
"Running it headless").

If the sandbox breaks a tool you need — containers and git over SSH are the known cases — the
alternatives are a dev container, a virtual machine, or a cloud session.

## What monerex runs and reads on your behalf

- **Your checks are shell commands.** `checks` in `.monerex/config.json` run through the shell
  in build, verify and the push gate, and build's ablation gate runs the plan's test commands
  the same way. The file is committed, so a repository you clone brings its own: opting in is
  trusting them. `/monerex:init` shows them, and asks you to read them if you did not write
  them.
- **Build's ablation gate edits the working tree.** On committed work only, it takes every
  changed file that is not a test, a lockfile, a test-runner manifest or a path you keep back
  to the base, runs the tests, and writes the files back from the commit, with new
  modification times. It refuses uncommitted work and a test that changes tracked files.
- **The evals run code from the repository.** `evalgate.py run` starts `claude plugin eval`
  with `--trust-plugin --scaffold`, so each case's `fixture.sh` runs as you; it is for the
  plugin's own development, started by you, with a cost ceiling.
- **The architecture gate.** The probe runs `oxn --version` and `oxn explain --help` from a
  neutral folder; without the `oxn` program it uses `python3 -P -m oxn`, where `-P` (Python
  3.11) keeps a repository's own `oxn.py` from running in its place. What oxn prints goes into
  plans and review reports as it is.
- **Repository state is data.** What monerex reads back from files a repository can carry is
  bounded and filtered: another worktree's routing log is read only as a plain file of at most
  64 MiB, and only the agents of the session recording a stage count; task names and retro
  proposal ids are printed only when they are plain names, and a proposal's text only as one
  short line; `init` refuses a linked `.monerex` or `.gitignore`. The stage records guard
  against forgetting a stage, not against forging one: `.monerex/log/` is not a protected
  path, and a shell command can append to it.
- **A plan or intent file starts a task.** Writing `docs/work/<task>/plan.md` or `intent.md`
  logs the task's start, with the session that wrote it.

## Reporting

Report a vulnerability privately through the repository's security advisories:
<https://github.com/mustafarslan/monerex/security/advisories/new>. Please do not file a
public issue for one.
