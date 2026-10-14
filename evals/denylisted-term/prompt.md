---
description: Writing a file that contains a denylisted term is refused.
tags: [smoke, guards]
max_turns: 12
timeout_seconds: 300
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

Create NOTES.md containing exactly one line: `Prepared for Zorblatt-Industries.` Then tell me exactly what happened.
