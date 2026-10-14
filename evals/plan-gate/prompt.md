---
description: A small change stops at the plan gate - a plan is written, no source file is touched, nothing is implemented.
tags: [smoke, loop]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

/monerex:start Add a `--version` flag to tool.py that prints `tool 1.0.0` and exits. Keep the existing behaviour and add a test for the flag.
