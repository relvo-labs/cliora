#!/usr/bin/env bash
# Exit condition 7: every existing table is unchanged, column for column. The only
# line that may disappear is the alembic revision marker.
#
# **Compared as a set of lines, not as a unified diff**, and that correction was forced
# by V2.3. A unified diff reports a *move* as a removal plus an addition, and the
# snapshot is sorted — so adding two foreign keys either side of an existing one made
# the untouched line show up as removed. The gate then failed on a schema where nothing
# had been removed at all, which is the failure mode a gate can least afford: one that
# cries wolf is one somebody switches off.
#
# The question this gate actually asks is "is every baseline line still present", and
# that is a set membership test. Ordering carries no meaning here — the snapshot sorts
# its own output — so nothing is lost by ignoring it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/pj/local/baseline/schema.txt}"
[ -f "$BASELINE" ] || { echo "no baseline at $BASELINE (PJ-00 captures it)"; exit 2; }

CURRENT="$(mktemp)"
trap 'rm -f "$CURRENT"' EXIT
uv run --project backend python scripts/pj/schema_snapshot.py > "$CURRENT"

# Lines in the baseline that are no longer present anywhere in the current schema.
REMOVED="$(grep -Fxv -f "$CURRENT" "$BASELINE" | grep -v '^# alembic revision' || true)"

if [ -n "$REMOVED" ]; then
  echo "existing schema changed (only additions are allowed):"
  printf '%s\n' "$REMOVED"
  exit 1
fi
echo "schema differs by additions only"
