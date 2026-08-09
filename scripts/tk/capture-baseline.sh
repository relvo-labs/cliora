#!/usr/bin/env bash
# TK-00: capture the pre-V2.1 baselines (plan/17/01-…md §2.1).
#
# Three of the exit conditions are "diff against before this phase", and the before
# is unrecoverable once the phase starts. Run this before touching any code.
#
# The navigation screenshots are deliberately NOT recaptured here: the flag-off
# promise is "identical to the pre-V2 console", and that baseline already exists at
# artifacts/pj/local/baseline/nav-baseline.{txt,png} (captured at 1c28057, before the
# project layer). Comparing V2.1's flag-off console against *that* is a stronger
# assertion than comparing it against today's tree, and recapturing would only
# replace a known-good reference with a fresher one.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/tk/local/baseline"
mkdir -p "$OUT"

git rev-parse HEAD > "$OUT/COMMIT.txt"
date -u +%Y-%m-%dT%H:%M:%S%:z >> "$OUT/COMMIT.txt"

echo "→ openapi.json"
uv run --project backend python - <<'PY' > "$OUT/openapi.json"
import json, sys
sys.path.insert(0, "backend")
from app.main import app
json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
PY

echo "→ routes.txt"
uv run --project backend python - <<'PY' > "$OUT/routes.txt"
import sys
sys.path.insert(0, "backend")
from app.main import app
rows = []
for route in app.routes:
    methods = ",".join(sorted(getattr(route, "methods", []) or []))
    rows.append(f"{methods:12s} {route.path}")
print("\n".join(sorted(rows)))
PY

echo "→ schema.txt (needs the migrated test database)"
uv run --project backend python scripts/pj/schema_snapshot.py > "$OUT/schema.txt"

echo "→ contract.sha256"
uv run --project backend python scripts/tk/contract_snapshot.py > "$OUT/contract.sha256"

echo "→ permission-matrix.md"
cp docs/permission-matrix.md "$OUT/permission-matrix.md"

echo
echo "captured into $OUT:"
ls -1 "$OUT"
