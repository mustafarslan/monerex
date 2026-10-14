---
description: retro reads a task history, writes up a few proposals tied to its numbers, and changes nothing. The history is seeded by the fixture, not lived.
tags: [smoke, loop]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

/monerex:retro 30
