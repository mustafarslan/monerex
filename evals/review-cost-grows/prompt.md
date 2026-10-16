---
description: The review stage on a correct, tested change that runs one query per order - the reviewer reports the cost that grows with the input.
tags: [full, loop]
max_turns: 60
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

/monerex:review Review my current, uncommitted changes against the plan at docs/work/order-names/plan.md. Tell me what you found. Change no file and post nothing.
