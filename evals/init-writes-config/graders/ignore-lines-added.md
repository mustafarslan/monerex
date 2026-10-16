---
type: regex
target: { source: file, path: .gitignore }
pattern: "^node_modules/$(?=[\\s\\S]*^\\.monerex/state/$)(?=[\\s\\S]*^\\.monerex/log/$)(?=[\\s\\S]*^\\.monerex/tmp/$)(?=[\\s\\S]*^\\.claude/worktrees/$)"
flags: m
weight: 2
---
