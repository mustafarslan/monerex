# Optional capabilities

Monerex runs on its own. These are the things it uses when they are there, how it finds out,
and what happens without each. `scripts/probe.py` does the finding out and touches no
network. A stage that wanted a capability and did not get it reports "not run" with the
reason; it never reports a clean result for something that did not happen.

Monerex uses only what is named here. It does not go looking for other installed skills or
tools that seem relevant.

| Capability | Found when | Used by | Without it |
|---|---|---|---|
| **Architecture gate** (`oxn`) | the repository has an `oxn.yaml` and the tool can be run, as `oxn` or `python3 -m oxn` | `plan` reads its constraints and writes them into the plan; `build` has the implementer run its check on the changed files and runs it again itself, and treats a spent retry budget as a gap in the plan; `verify` runs its deep check | the plan's own checks |
| **Second reviewer** from another model family | `.monerex/config.json` names one monerex knows (`"second_reviewer": "agy"`), its program is installed, and `external_review` is not `off` | `review` and `bugfix`, when the route asks for one | reported as not run; the review stands on monerex's own reviewer |
| **Code host** | the `gh` program is installed and the `origin` remote names a repository | `review` of a pull request, `feedback`, `ship`, `bugfix`, and the count of open pull requests in `start` | those stages stop and say so; a pasted file can stand in for an issue |
| **The repository's own agents** | definitions under `.claude/agents/` | a stage may dispatch one when its description fits the work better than monerex's | monerex's agents |

## The second reviewer and what leaves the machine

`external_review` in `.monerex/config.json` decides, per repository:

| Value | What is sent |
|---|---|
| `off` (the default) | nothing; the reviewer is not run |
| `diff-only` | one brief, containing the diff and the criteria. The reviewer is started in an empty scratch folder holding only that brief, so it is not standing in the repository. That is not a wall: a reviewer that follows an absolute path can still read it |
| `on` | the brief, and the reviewer is started in the repository and can read the tree |

Whatever the value, the brief is scanned first: a denylisted term, a credential or a hidden
character stops it. The answer is untrusted text: candidates to verify.

The one reviewer monerex knows today is `agy`, which runs a program named `agy-ask` on the
PATH: a wrapper you provide around Google's Antigravity CLI. What monerex expects of it:

- It is called as `agy-ask -f <brief file>` and prints its answer on standard output.
- It exits 0 with an answer; 2 when it ran and returned nothing; 3 when it is out of quota;
  4 when it is not signed in. Any other code is reported as a failure, never as a clean
  review.
- It is read-only. If it finds the working tree changed, it says `TREE_MODIFIED` on
  standard error, and monerex tells you.
- monerex waits for it up to 15 minutes.

## Reading from the code host

Stages read through `monerex-forge`, which saves other people's text to files and prints only
counts and states. Names count as text too: a branch, a check or a login can spell out a
sentence, so those go to the files as well. Under a sandbox with no network a script cannot reach the code host, so a
repository that uses the profile in `SECURITY.md` and wants these stages adds
`monerex-forge *` to its excluded commands. Posting is always a plain `gh` command, run after
the user approves the text.
