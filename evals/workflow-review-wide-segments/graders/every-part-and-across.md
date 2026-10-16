---
type: regex
target: { source: file, path: .monerex/log/routing.jsonl }
pattern: "((monerex:reviewer[^\\n]*SubagentStop|SubagentStop[^\\n]*monerex:reviewer)[\\s\\S]*?){5}"
weight: 3
---
