---
type: regex
pattern: "N ?\\+ ?1|O\\(n\\) (quer|SELECT|round|call)|grows with the number of (orders|rows)|(quer(y|ies)|SELECTs?|lookups?|calls?|called|round[- ]trips?|execut\\w*)\\b.{0,60}\\b(per|for each|for every|once per|once for each|inside the|in the|in a) (order|row|loop|comprehension|iteration)"
flags: i
weight: 3
---
