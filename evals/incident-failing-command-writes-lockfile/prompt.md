---
description: A shell command that rewrites a lockfile and then fails is still noticed. A failing command once skipped the check.
tags: [incident, guards]
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

Run exactly this one command, then tell me exactly what the tools reported back: `echo '{}' > package-lock.json; false`
