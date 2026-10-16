I reviewed your uncommitted changes against `docs/work/order-names/plan.md`. They meet the plan, but `list_orders` now runs one extra query per order. I left `orders.py` and the tests alone and posted nothing. `python3 -m unittest -q` passes (2 tests).

**Critical:** none.

**Improvement**
- **`orders.py:12`, one query per order (confirmed by reading the code).** `list_orders` has no `LIMIT`. The new `customer_name()` (lines 4–6) is called once per row, so N orders cost N+1 queries. Cost grows with the size of the orders table. One query with a `LEFT JOIN customers` would return the same result and keep `None` for a missing customer. I didn't run it against a large table.

**Nit**
- **`test_orders.py:22-23`, thin test coverage (confirmed).** The fixture has two orders that each match a customer. No test covers an order whose customer is missing (`customer` would be `None`), and nothing stops a later `INNER JOIN` from silently dropping such orders. The schema has no foreign key, so such orders can exist.

**Rejected**
- None. The reviewer's line numbers were off (it cited `orders.py:18` and lines 9–11). I checked the real ones above.

**Not run**
- **Extra reviewers:** none. The task is T1 with no risk flags and no cross-family review.
- **Task logging:** I didn't run `task.py event review` or `event done`, since this was a review of your working tree and not the close of a monerex task. Tell me if you want them logged.
- **Git workaround:** the system `git` fails in this sandbox, so I used `/opt/homebrew/bin/git` to save the diff.

**Merge?** After fixes. Swap the per-order lookup for a JOIN, and add a missing-customer row to the test if you want that behaviour pinned down. The decision is yours.