#!/usr/bin/env bash
# Builds the small repository this case runs in. It starts in the empty workspace.
set -euo pipefail

mkdir -p api web
: > api/__init__.py
: > web/__init__.py
cat > api/orders.py <<'PY'
"""Orders, read from the shop's database."""


def list_orders(conn):
    rows = conn.execute("SELECT id, customer_id, total FROM orders ORDER BY id DESC").fetchall()
    return [{"id": row[0], "customer_id": row[1], "total": row[2]} for row in rows]
PY
cat > web/page.py <<'PY'
"""The orders page."""

from api.orders import list_orders


def render(conn):
    return "\n".join("%s %s" % (order["id"], order["total"]) for order in list_orders(conn))
PY

mkdir -p .monerex
printf '%s\n' '{ "checks": ["python3 -m unittest -q"], "external_review": "off" }' > .monerex/config.json
printf '%s\n' '.monerex/state/' '.monerex/log/' '.monerex/tmp/' '__pycache__/' > .gitignore

git init -q -b main
git config user.name "Eval"
git config user.email "eval@example.invalid"
git add -A
git commit -q -m "Start"

# The change under review, in two parts. The api part renames list_orders to fetch_orders and
# runs one query per order; the web part still imports the old name, which only shows across
# the parts.
mkdir -p docs/work/rename-orders .monerex/tmp .monerex/log
cat > docs/work/rename-orders/plan.md <<'MD'
# Plan: name the customer on the orders page

- **Tier:** T1
- **Risk flags:** none
- **Status:** approved

## Why

Support staff want to see who placed each order. `list_orders` becomes `fetch_orders`, the name
the rest of the api uses.

## Done when

- the orders page shows each order's customer name — `python3 -m unittest -q`
MD
cat > api/orders.py <<'PY'
"""Orders, read from the shop's database."""


def customer_name(conn, customer_id):
    row = conn.execute("SELECT name FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return row[0] if row else None


def fetch_orders(conn):
    rows = conn.execute("SELECT id, customer_id, total FROM orders ORDER BY id DESC").fetchall()
    return [
        {"id": row[0], "customer_id": row[1], "total": row[2], "customer": customer_name(conn, row[1])}
        for row in rows
    ]
PY
cat > web/page.py <<'PY'
"""The orders page."""

from api.orders import list_orders


def render(conn):
    lines = ["Orders"]
    lines += ["%s %s %s" % (order["id"], order["customer"], order["total"]) for order in list_orders(conn)]
    return "\n".join(lines)
PY
# The parts as scripts/segment_diff.py cuts them: by top-level folder, byte for byte.
git diff > .monerex/tmp/review.diff
git diff -- api > .monerex/tmp/review-1.diff
git diff -- web > .monerex/tmp/review-2.diff
git checkout -q -b rename-orders
