---
description: The same change asked for in plain words, without typing the command, still goes through the loop and stops at the plan gate.
tags: [smoke, loop]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

Add a `--version` flag to tool.py that prints `tool 1.0.0` and exits. Keep the existing behaviour and add a test for the flag.
