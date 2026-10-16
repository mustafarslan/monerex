#!/usr/bin/env bash
# A small Node project that has not opted in to monerex. It starts in the empty workspace.
set -euo pipefail

cat > package.json <<'JSON'
{
  "name": "tiny",
  "version": "1.0.0",
  "scripts": { "test": "node test.js" }
}
JSON
cat > index.js <<'JS'
module.exports = function add(a, b) { return a + b; };
JS
cat > test.js <<'JS'
const assert = require("assert");
assert.strictEqual(require("./index.js")(1, 2), 3);
console.log("ok");
JS
printf '%s\n' 'node_modules/' > .gitignore

git init -q -b main
git config user.name "Eval"
git config user.email "eval@example.invalid"
git add -A
git commit -q -m "Start"
