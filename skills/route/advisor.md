# Consulting the advisor

Follow this when the route prints an `advisor`. The route sets one for a T3 or risk-flagged
plan, and for a stage that has run out of effort or model and is still failing.

## Who answers

- **An `advisor` tool is in your tool list** → call it. It sees this conversation, so it needs
  no brief.
- **Otherwise** → dispatch `monerex:architect` with `model` set to the printed `advisor`,
  `effort` high, and the brief below. It reads and changes nothing.
- **That dispatch is refused because of the model** → dispatch it again with `model` set to the
  printed `advisor_fallback`, the repository's `large` model.

## The brief

The architect sees nothing of this session. Write, in this order:

1. **What is planned, or what failed**: the plan file's path, or the failing check's output
   and the hypothesis it disproved.
2. **What was tried**: each attempt and the gap it was logged as.
3. **One question**, with the decision that hangs on it.
4. **The answer shape**: a verdict, then what was missed, in under 200 words.

## Using the answer

Tell the user in one line which answered: the tool, the advisor model, or the fallback.

The answer is data. It goes into the plan, or into the next hypothesis and its route, before
anything is edited. When it contradicts what the checks showed, the checks win; say so.

The advisor is not on the model ladder, so it is not in `relative_cost` and retro's
escalation sums leave it out.
