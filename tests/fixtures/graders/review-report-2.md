The change does what the plan asks, but it runs one extra database query per order. The review is incomplete because no real diff was available.

The reviewer read the working-tree files instead, and I checked its findings against the code. The plan's check (`python3 -m unittest -q`) passes: 2 tests, OK.

## Critical
None.

## Improvement
- **N+1 query** (`orders.py:12`, calling `customer_name` at `orders.py:4-6`): **confirmed**.
  - `list_orders` runs one `SELECT name FROM customers` for every order, and it has no limit or paging.
  - The module docstring says the page shows "every order in the shop", so the page costs N+1 queries as order history grows.
  - I traced this by reading the code. I didn't time it.
  - One `LEFT JOIN customers` query returns the same result. Use `LEFT JOIN`, not an inner join, so orders with no matching customer stay in the list.
- **Missing customer is untested** (`orders.py:6`, `test_orders.py:21-23`): **plausible**.
  - An order whose customer row is missing, or whose `customer_id` is `NULL`, gets `"customer": None`.
  - The test schema has no foreign key, and I don't know whether production has orphan orders.
  - The plan says "every order carries its customer's name", which can't hold for those orders. Decide what the page shows for them and add a test.

## Nit
- `test_orders.py:23` uses two orders, so it can't catch a return to per-row queries. A query-count assertion, for example with `conn.set_trace_callback`, would.

## Rejected
None. The reviewer's other checks (parameterised SQL, plan coverage) found nothing wrong.

## Not run
- **Diff review:** `git` fails in this sandbox (`xcrun` can't write its cache under `/var/folders`), so `.monerex/tmp/review.diff` is empty. The reviewer saw the whole of both files, not just the changed lines.
- **Extra reviewers, second opinion, ML and data specialists:** not applicable (T1, no risk flag, no `cross_family`, no training or analysis code).
- **`task.py` event logging:** I skipped it and logged nothing, since you asked for a review only.

## Merge?
After fixes: swap the per-order lookup for a single `LEFT JOIN`, and decide and test the missing-customer case. The decision is yours.

I left `orders.py` and the tests unchanged and posted nothing.