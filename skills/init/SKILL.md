---
name: init
description: Opt a repository in to monerex. Use when the user asks to set monerex up, start using it, or opt a repository in, or when start reports there is no .monerex/config.json.
argument-hint: "[the command that runs the tests]"
disable-model-invocation: true
---

# Init

You write the one file that opts a repository in, and the lines that keep monerex's own
folders out of git. Nothing else.

## 1. Look

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/init.py" detect
```

`opted_in` true → say so, show `.monerex/config.json`, and stop; the guard asks before anyone
edits it. Its `checks` run as shell commands in build, verify and the push gate: if the user
did not write them (a repository they cloned), say so and ask them to read the commands first.

## 2. Settle the check command

The checks are what build, verify and the push gate run, so they must be the command the
user trusts. If the argument names one, use it. Otherwise show the `candidates` and ask the
user to pick one or give their own (one question). With no candidate and no answer, stop:
never write an empty list, which would run every task without checks.

## 3. Write

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/init.py" write --check '<command>'
```

Write only through this script: it refuses what must not be written (an empty list, an
existing config, a linked file). Single quotes keep the command as the user gave it; a quote
inside it is written as `'\''`. Show what it wrote: the config, and the lines it added to
`.gitignore`.

## 4. Say what is optional

In a few lines, and do none of it yourself:

- The security profile in `SECURITY.md`: `start` shows the gaps; the user applies it with
  `/sandbox` or by pasting the profile. **Never write Claude's settings.**
- The git hooks that catch secrets in commits: `sh <a clone of monerex>/githooks/install.sh`,
  run by the user, since it changes git configuration.
- `"engage": "typed"` in the config keeps the loop for the typed command only; by default a
  plain-words request for a change goes through it.

Then: ask for a change in plain words, or type `/monerex:start <what you want done>`.
