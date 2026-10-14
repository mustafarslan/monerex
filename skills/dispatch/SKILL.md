---
name: dispatch
description: Starts a monerex task as its own background session in another repository, so several tasks run side by side and each stops at its own gates. Only when the user asks to run a task in the background or in parallel.
argument-hint: "<repository path> <what you want done>"
disable-model-invocation: true
---

# Dispatch

Each task gets its own session in its own repository. This session starts it and then has
nothing more to do with it. The user watches and answers in agent view: `claude agents`.

## 1. Count what is already open

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/desk.py" count --repo "<repository path>"
```

- `same_repo` above 0 → a monerex task is already open in that repository. Two tasks never
  share a checkout: the new one gets its own worktree (step 2). Say so.
- `over` is true → say how many are open and what the limit is, and that their review time is
  what runs out first. Ask whether to go on. Never refuse.
- `known` is false → the session list could not be read. Say so, and ask the user whether
  anything else is working in that repository; if it is, or they are not sure, use a worktree.

The script prints counts only. Do not list sessions yourself: the list covers every project
on the machine.

## 2. Build the command

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/desk.py" command "<repository path>" "<slug>" "<the task>"
```

`<slug>` is a short kebab-case name. Add `--worktree` when step 1 called for one, or when
the user is working in that repository themselves: the task then runs in its own checkout
and branch, and its push is asked about if the default branch has moved since. Add
`--plugin-dir <path>` when this session loaded monerex that way. If `configured` is false, say that monerex's guards do nothing in that repository
until it has a `.monerex/config.json`.

## 3. Show it, then start it

Show the user the command. Run it only after they say yes.

- It fails with a permission error → a sandbox stops one session from starting another. Give
  them the line to run themselves, in a terminal or with the `!` prefix.
- It says the workspace is not trusted → they open `claude` in that repository once, accept
  the prompt, and run the line again.

## 4. Let go

Tell the user: `claude agents` lists the new session, grouped by whether it needs them, is
working, or is ready for review; its plan, its questions and its permission prompts are
answered there, in that session.

From here on, do not read that repository, poll that session, message it or summarise it.
Nothing from one repository's work comes back into another's session, and no session can
approve anything on the user's behalf.
