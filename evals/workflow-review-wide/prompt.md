---
description: A saved workflow runs in the real runtime - review-wide dispatches monerex reviewers on a diff with one planted fault, and the guards log them.
tags: [full, workflows]
max_turns: 60
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Agent, AskUserQuestion, TodoWrite, Workflow]
---

Run the review-wide workflow of the monerex plugin on the diff at .monerex/tmp/review.diff against the plan at docs/work/add-shout/plan.md. Pass it { "diff": ".monerex/tmp/review.diff", "plan": "docs/work/add-shout/plan.md", "angles": ["correctness", "tests"] }. Wait for it to finish, then tell me what it returned: which findings were confirmed, which were plausible, which were rejected, and anything it says was not run. Change no file.
