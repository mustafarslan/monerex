---
description: The audit workflow runs in the real runtime - one monerex scout per path, each answer that found something checked, and what was missed named.
tags: [full, workflows]
max_turns: 60
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite, Workflow]
---

Run the audit workflow of the monerex plugin. Pass it { "question": "Which functions write to standard output, and where?", "paths": ["tool.py", "test_tool.py"] }. Wait for it to finish, then tell me what it returned: what held when checked, what did not, which paths found nothing, and the gaps it named. Change no file.
