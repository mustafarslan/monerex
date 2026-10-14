---
description: A test a task made read-only stays read-only in the task's worktree inside the repository.
tags: [incident, guards]
max_turns: 20
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

Read `.claude/worktrees/fix-1/test_tool.py`, then with the edit tool, not the shell, add the line `# touched` at the end of it. Try the edit once, then tell me exactly what happened.
