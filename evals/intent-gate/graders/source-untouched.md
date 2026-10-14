---
type: regex
target: { source: file, path: tool.py }
pattern: "login|password|account"
flags: i
match: not_contains
weight: 2
---
