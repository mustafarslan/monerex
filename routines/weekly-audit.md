# Weekly audit

**When:** once a week. **Cost:** no model-driven fan-out; a few minutes of one session.

Paste this as the routine's prompt:

```
Audit this repository and report what you find. Do not change, commit, push or post anything.

1. Run: python3 scripts/audit.py --json
   It looks at every tracked file for secrets, hidden characters and denylisted terms, and at
   CI for actions that are not pinned to a commit hash.
2. Run: python3 -m unittest discover -s tests
3. Report, in this order: the audit's findings, each with its place and rule; the audit's
   notes, word for word (for example that terms were not checked because this session has no
   denylist); whether the unit tests passed, and which failed; anything that could not be run
   and why.

A finding names a place and a rule and never the text that matched: do not open the file to
quote it. Do not fix anything. Do not run /monerex:ship, /monerex:bugfix or /monerex:feedback.
```

A scheduled session starts from a fresh clone of the **default branch**. While the code you
want audited lives on another branch, add a first step that names it, for example: "If
scripts/audit.py is not in this checkout, run `git fetch origin <branch> && git checkout
FETCH_HEAD` and say at the top of the report which branch you audited."

Give the routine the tools `Bash`, `Read`, `Glob` and `Grep` and nothing that writes. A
routine made through the API gets every connector on the account attached; this one needs
none, so remove them.

The clone has no private denylist, so terms are not
checked there, and none of the local task logs, which git ignores. The task summary is
something to read on your own machine with `/monerex:retro`.
