---
description: review-wide in segments runs in the real runtime - each angle reviews each part, one reviewer looks across them, and a fault that crosses the parts and a query per row are found.
tags: [full, workflows]
max_turns: 60
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite, Workflow]
---

Run the review-wide workflow of the monerex plugin. Pass it exactly { "diff": ".monerex/tmp/review.diff", "plan": "docs/work/rename-orders/plan.md", "angles": ["correctness", "performance"], "segments": [{ "name": "api", "paths": ["api/orders.py"], "diff": ".monerex/tmp/review-1.diff" }, { "name": "web", "paths": ["web/page.py"], "diff": ".monerex/tmp/review-2.diff" }] }. Wait for it to finish, then tell me what it returned: which findings were confirmed, which were plausible, which were rejected, and anything it says was not run. Change no file.
