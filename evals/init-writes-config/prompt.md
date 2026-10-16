---
description: init opts a repository in - it finds the project's own test command, writes .monerex/config.json and the ignore lines, and writes none of Claude's settings.
tags: [smoke, loop]
max_turns: 30
timeout_seconds: 600
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion, TodoWrite]
---

/monerex:init Use the test command you find in this repository; I confirm it, so do not stop to ask me.
