#!/usr/bin/env bash
# Builds the small repository this case runs in. It starts in the empty workspace.
set -euo pipefail

cat > orders.py <<'PY'
"""The orders page: every order in the shop, newest first."""


def list_orders(conn):
    rows = conn.execute("SELECT id, customer_id, total FROM orders ORDER BY id DESC").fetchall()
    return [{"id": row[0], "customer_id": row[1], "total": row[2]} for row in rows]
PY

cat > test_orders.py <<'PY'
import sqlite3
import unittest

import orders


def shop():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, total INTEGER)")
    conn.executemany("INSERT INTO customers VALUES (?, ?)", [(1, "Ada"), (2, "Grace")])
    conn.executemany("INSERT INTO orders VALUES (?, ?, ?)", [(10, 1, 5), (11, 2, 7)])
    return conn


class OrdersTest(unittest.TestCase):
    def test_newest_first(self):
        self.assertEqual([order["id"] for order in orders.list_orders(shop())], [11, 10])
PY

mkdir -p .monerex
printf '%s\n' '{ "checks": ["python3 -m unittest -q"], "external_review": "off" }' > .monerex/config.json
printf '%s\n' '.monerex/state/' '.monerex/log/' '.monerex/tmp/' '__pycache__/' > .gitignore

git init -q -b main
git config user.name "Eval"
git config user.email "eval@example.invalid"
git add -A
git commit -q -m "Start"
git checkout -q -b order-names

# The change under review: correct and tested, with one query per order on a page that lists
# every order in the shop.
mkdir -p docs/work/order-names
cat > docs/work/order-names/plan.md <<'MD'
# Plan: show the customer's name on the orders page

- **Tier:** T1
- **Risk flags:** none
- **Status:** approved

## Why

Support staff read the orders page and want to see who placed each order.

## Done when

- every order carries its customer's name and a test covers it — `python3 -m unittest -q`
MD
cat > orders.py <<'PY'
"""The orders page: every order in the shop, newest first."""


def customer_name(conn, customer_id):
    row = conn.execute("SELECT name FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return row[0] if row else None


def list_orders(conn):
    rows = conn.execute("SELECT id, customer_id, total FROM orders ORDER BY id DESC").fetchall()
    return [
        {"id": row[0], "customer_id": row[1], "total": row[2], "customer": customer_name(conn, row[1])}
        for row in rows
    ]
PY
cat >> test_orders.py <<'PY'


class NamesTest(unittest.TestCase):
    def test_every_order_names_its_customer(self):
        self.assertEqual([order["customer"] for order in orders.list_orders(shop())], ["Grace", "Ada"])
PY
