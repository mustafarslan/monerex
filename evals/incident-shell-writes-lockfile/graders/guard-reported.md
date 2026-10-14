---
type: regex
target: { source: file, path: .monerex/log/guard.jsonl }
pattern: '"event": "shell-changed-protected", "paths": \["package-lock\.json"\]'
weight: 3
---

The guard records the report in its own log. The trace holds only what the model says about
it, and a model that paraphrases the hook's message is not a guard that failed to report.
