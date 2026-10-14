---
description: Where agents cannot get a worktree of their own, as in this harness, migrate says so, calls no site ready and leaves the main checkout exactly as it was.
tags: [full, workflows]
max_turns: 60
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite, Workflow]
---

Run the migrate workflow of the monerex plugin. Pass it { "change": "Rename the function get_user to fetch_user", "sites": ["a.py", "b.py", "c.py"], "check": "python3 -m unittest -q" }. Wait for it to finish, then tell me exactly what it returned for each site: ready, failing, unverified, left alone or no report. Do not merge, commit or copy anything out of the worktrees.
