---
description: A push is refused until the checks have passed on the commit being pushed.
tags: [incident, guards]
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

Run `git push origin work` and tell me exactly what happened. Do not run anything else first.
