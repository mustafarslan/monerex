#!/bin/sh
# Install monerex's git guards into this clone's hooks directory.
# The installed copies are local and uncommitted; rerun after updating monerex.
set -eu

src=$(cd "$(dirname "$0")" && pwd)
dst=$(git rev-parse --git-path hooks)
mkdir -p "$dst"

skipped=0
for hook in pre-commit commit-msg pre-push; do
  if [ -e "$dst/$hook" ] && ! grep -q 'monerex_scan.py' "$dst/$hook"; then
    echo "monerex: $dst/$hook already exists and is not monerex's; left as is." >&2
    echo "monerex: call monerex_scan.py $hook from it to add the guard." >&2
    skipped=1
    continue
  fi
  cp "$src/$hook" "$dst/$hook"
  chmod +x "$dst/$hook"
done
cp "$src/monerex_scan.py" "$dst/monerex_scan.py"

# Record the default branch while the remote names it: the pre-push rule holds it even if
# the remote's HEAD is later removed or re-pointed.
head=$(git symbolic-ref --short -q refs/remotes/origin/HEAD 2>/dev/null || true)
if [ -n "$head" ]; then
  git config monerex.defaultBranch "${head#*/}"
fi

echo "monerex: git guards installed in $dst"
exit "$skipped"
