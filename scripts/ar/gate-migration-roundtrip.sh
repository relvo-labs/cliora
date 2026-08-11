#!/usr/bin/env bash
# GATE-AR-MIGRATION-ROUNDTRIP: V2.2 must roll back exactly to the captured V2.1
# schema and then return to head (plan/18/02-…md §1).
#
# The three migrations are separable on purpose, and the downgrade is where that
# claim is tested: 0029 drops eight tables in reverse foreign-key order and gives
# back the two constraints on `tasks`, and 0031 must really `drop_column` — an
# orphan column left on a pre-existing table is what makes the *next* phase's
# baseline diff permanently unexplainable.
#
# The EXIT trap restores head even when the diff fails, so a diagnostic gate never
# leaves the developer database downgraded.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/ar/local/baseline/schema.txt}"
[ -f "$BASELINE" ] || { echo "no baseline at $BASELINE (AR-00 captures it)"; exit 2; }

ROUNDTRIP_LOG="$(mktemp)"
restore_head() {
  (cd backend && uv run --project . alembic upgrade head >/dev/null)
  rm -f "$ROUNDTRIP_LOG"
}
trap restore_head EXIT

(cd backend && uv run --project . alembic downgrade 0028_node_removal_sessions >/dev/null)
if ! uv run --project backend python scripts/pj/schema_snapshot.py --diff "$BASELINE" \
  >"$ROUNDTRIP_LOG" 2>&1; then
  echo "downgrade did not restore the V2.1 baseline schema:"
  sed -n '1,240p' "$ROUNDTRIP_LOG"
  exit 1
fi

restore_head
trap - EXIT
echo "downgrade restored the V2.1 baseline exactly; upgrade reapplied head"
