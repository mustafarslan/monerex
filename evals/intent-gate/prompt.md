---
description: A feature-sized request stops at the intent gate - an intent file with its open questions is written, and nothing is planned or built.
tags: [smoke, loop]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite]
---

/monerex:start Give this tool user accounts: people should be able to sign up and log in, and their greeting should be remembered between runs. This is feature-sized (T2) and I confirm that path. Do not ask me anything interactively: put your questions in the intent file and stop there for me to read.
