---
description: One small task goes through the whole loop - plan, build, verify, review - with the plan approved in advance by the user.
tags: [full, loop]
max_turns: 150
timeout_seconds: 3000
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

/monerex:start Add a `--version` flag to tool.py that prints `tool 1.0.0` and exits. Keep the existing behaviour and add a test for the flag. I approve whatever plan you write: do not stop to ask me, and carry on through build, verify and review.
