---
name: route
description: Picks the agent, model and effort for a monerex dispatch from the routing table. Use before dispatching any monerex agent, and again when a stage fails and has to escalate.
user-invocable: false
---

# Route

Every monerex dispatch names its model and effort. Neither is ever inherited. Ask the table:

```sh
python3 -I "${CLAUDE_SKILL_DIR}/../../scripts/route.py" --work implement --tier T1
```

| Flag | Meaning |
|---|---|
| `--work` | `read`, `search`, `plan`, `implement`, `debug`, `verify`, `review`, `research`, `ml`, `data` |
| `--tier` | `T0`–`T3`; for `research`, `T0` is a single-fact lookup |
| `--risk` | a risk flag is set |
| `--no-checks` | no reliable checks cover this code |
| `--imprecise-plan` | the plan leaves real choices open |
| `--author <tier>` | for `verify`, `review`, `ml` and `data`: the tier the author ran at (`small`, `mid`, `large`) |
| `--gap <kind>` | one per failure so far, oldest first |

It prints `agent`, `model`, `effort`, `advisor`, `cross_family`, `stop` and the reasons.

**Use the answer exactly.** Dispatch `monerex:<agent>` with `model` and `effort` set to the
printed values. Tell the user the route and the first reason in one line.

- `advisor` is set → consult the advisor before dispatching. When it is not set, do not
  consult one for this stage: the strongest model is the most expensive call there is.
- `cross_family` is set → add a reviewer from another model family if one is available and
  this repository's `external_review` setting allows it. Otherwise report "not run" and why.
- `stop` is true → do not dispatch. Report to the user what was tried.

## Escalating

Escalate only on something observed: the checks failed twice, the verifier and the author
disagree, or a review finding survived verification. Never because an agent says it is unsure.

Name the gap, then ask the table again with every gap so far:

| Gap | What you saw | Effect |
|---|---|---|
| `diligence` | a file was skipped, the tests were not run, a step was left out | effort goes up |
| `knowledge` | wrong diagnosis, wrong approach, unfamiliar territory | model goes up |
| `spec` | the task is ambiguous or contradicts the code | stop and ask the user |

The route resets at the next stage. When the author moves up, pass `--author` so the verifier
and the reviewer move with it.
