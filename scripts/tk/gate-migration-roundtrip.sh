#!/usr/bin/env bash
# GATE-TK-MIGRATION-ROUNDTRIP: V2.1 must roll back exactly to the captured V2.0
# schema and then return to head. The EXIT trap restores head even when the diff
# fails, so a diagnostic gate never leaves the developer database downgraded.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/tk/local/baseline/schema.txt}"
[ -f "$BASELINE" ] || { echo "no baseline at $BASELINE"; exit 2; }

ROUNDTRIP_LOG="$(mktemp)"
restore_head() {
  (cd backend && uv run --project . alembic upgrade head >/dev/null)
  rm -f "$ROUNDTRIP_LOG"
}
trap restore_head EXIT

(cd backend && uv run --project . alembic downgrade 0022_seed_project_actions >/dev/null)
if ! uv run --project backend python scripts/pj/schema_snapshot.py --diff "$BASELINE" \
  >"$ROUNDTRIP_LOG" 2>&1; then
  echo "downgrade did not restore the V2.0 baseline schema:"
  sed -n '1,240p' "$ROUNDTRIP_LOG"
  exit 1
fi

restore_head
trap - EXIT
echo "downgrade restored the V2.0 baseline exactly; upgrade reapplied head"
