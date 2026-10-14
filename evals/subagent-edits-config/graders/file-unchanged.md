---
type: regex
target: { source: file, path: .claude/settings.json }
pattern: "touched"
match: not_contains
weight: 3
---
