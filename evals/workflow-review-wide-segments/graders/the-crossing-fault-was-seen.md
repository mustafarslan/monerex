---
type: regex
target: trace
pattern: "confirmed\\\\+\\\": \\[(?:(?!rejected\\\\+\\\": \\[|== rejected|\\*\\*Rejected|#+ ?Rejected)[\\s\\S])*?(?:list_orders(?:(?!rejected\\\\+\\\": \\[|== rejected|\\*\\*Rejected|#+ ?Rejected)[\\s\\S]){0,200}?\\b(?:import(?:s|ed|ing)?|ImportError|NameError|AttributeError|undefined|no longer (?:exists?|defined|importable|available)|not (?:defined|exist|propagated|updated)|missing|removed|gone|break(?:s|ing)?|broken?|crash(?:es|ing)?|fail(?:s|ed|ing|ure)?|stale|old name)\\b|\\b(?:import(?:s|ed|ing)?|ImportError|NameError|AttributeError|undefined|no longer (?:exists?|defined|importable|available)|not (?:defined|exist|propagated|updated)|missing|removed|gone|break(?:s|ing)?|broken?|crash(?:es|ing)?|fail(?:s|ed|ing|ure)?|stale|old name)\\b(?:(?!rejected\\\\+\\\": \\[|== rejected|\\*\\*Rejected|#+ ?Rejected)[\\s\\S]){0,200}?list_orders)"
flags: i
weight: 3
---
