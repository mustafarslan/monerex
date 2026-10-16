---
type: regex
target: trace
pattern: "confirmed\\\\+\\\": \\[(?:(?!rejected\\\\+\\\": \\[|== rejected|\\*\\*Rejected|#+ ?Rejected)[\\s\\S])*?(?:list_orders[\\s\\S]{0,200}?(?:import|undefined|no longer|not (defined|exist|propagated|updated)|missing|removed|gone|break|broke|crash|fail|stale|old name|NameError|AttributeError)|(?:import|undefined|no longer|not (defined|exist|propagated|updated)|missing|removed|gone|break|broke|crash|fail|stale|old name|NameError|AttributeError)[\\s\\S]{0,200}?list_orders)"
flags: i
weight: 3
---
