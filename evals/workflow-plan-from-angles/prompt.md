---
description: The plan-from-angles workflow runs in the real runtime - independent designs from monerex architects, then a judge that may only pick one of them.
tags: [full, workflows]
max_turns: 60
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite, Workflow]
---

Run the plan-from-angles workflow of the monerex plugin. Pass it { "task": "Add a --version flag to tool.py that prints tool 1.0.0 and exits, keeping the existing behaviour" }. Wait for it to finish, then tell me which design the judge recommended, what it took from the others, and the decisions it left to me. Change no file.
