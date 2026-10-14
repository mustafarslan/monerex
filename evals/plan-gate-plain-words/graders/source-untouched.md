---
type: regex
target: { source: file, path: tool.py }
pattern: "--version"
match: not_contains
weight: 3
---
