---
type: regex
target: { source: file, path: .monerex/config.json }
pattern: '"checks"\s*:\s*\[\s*"npm test"\s*\]'
weight: 3
---
