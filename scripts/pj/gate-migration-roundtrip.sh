#!/usr/bin/env bash
# Down and back up. A migration that cannot be reversed is a deployment with no
# way back, and the reverse has to land exactly on the baseline — not merely run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/pj/local/baseline/schema.txt}"
[ -f "$BASELINE" ] || { echo "no baseline at $BASELINE"; exit 2; }

cd backend
uv run --project . alembic downgrade 0020_node_file_upload >/dev/null
cd ..
uv run --project backend python scripts/pj/schema_snapshot.py --diff "$BASELINE" >/tmp/pj-roundtrip.log 2>&1
STATUS=$?
cd backend
uv run --project . alembic upgrade head >/dev/null
cd ..

if [ "$STATUS" -ne 0 ]; then
  echo "downgrade did not restore the baseline schema:"
  cat /tmp/pj-roundtrip.log
  exit 1
fi
echo "downgrade restores the baseline exactly; upgrade reapplied"
