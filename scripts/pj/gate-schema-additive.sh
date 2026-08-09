#!/usr/bin/env bash
# Exit condition 7: every existing table is unchanged, column for column. The only
# line the diff may remove is the alembic revision marker.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/pj/local/baseline/schema.txt}"
[ -f "$BASELINE" ] || { echo "no baseline at $BASELINE (PJ-00 captures it)"; exit 2; }

DIFF="$(uv run --project backend python scripts/pj/schema_snapshot.py --diff "$BASELINE" 2>/dev/null || true)"
REMOVED="$(printf '%s\n' "$DIFF" | grep '^-' | grep -v '^---' | grep -v '^-# alembic revision' || true)"

if [ -n "$REMOVED" ]; then
  echo "existing schema changed (only additions are allowed):"
  printf '%s\n' "$REMOVED"
  exit 1
fi
echo "schema differs by additions only"
