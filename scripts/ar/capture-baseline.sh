#!/usr/bin/env bash
# AR-00: capture the pre-V2.2 baselines (plan/18/01-…md §1).
#
# Gate one of the phase: **no code moves until these exist**, because every one of
# them is a "before" that stops being obtainable the moment it does. Six of them,
# three more than V2.1 needed — the frontend route table and the two OpenAPI dumps
# because criterion 14 asserts a *negative* proposition ("no path in the application
# origin renders an artifact") which can only be proved against an enumeration, and
# `COMMIT` because without it "diff against before the upgrade" is a sentence with
# nothing anchoring it.
#
# All six must come from **one** commit. Baselines taken from three different states
# are worse than no baseline: they turn some diff assertion six months from now into
# a red light nobody knows whether to believe. The script therefore refuses to run on
# a dirty tree unless AR_BASELINE_ALLOW_DIRTY=1 is set, and records the commit first.
#
#   scripts/ar/capture-baseline.sh          # five of six; latency needs the stack
#   scripts/e2e/run-stack.sh scripts/ar/capture-baseline.sh --latency-only
#
# `terminal-latency.json` is separate because it is the only one that needs a live
# node: `run-stack.sh` builds the daemon, enrolls a node and stands up Central, then
# runs this script again with --latency-only inside that environment.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

OUT="artifacts/ar/local/baseline"
mkdir -p "$OUT"

LATENCY_ONLY=0
[ "${1:-}" = "--latency-only" ] && LATENCY_ONLY=1

capture_latency() {
  echo "→ terminal-latency.json (needs a live stack)"
  uv run --project backend python scripts/ar/measure_terminal_latency.py \
    --out "$OUT/terminal-latency.json" >/dev/null
}

if [ "$LATENCY_ONLY" = "1" ]; then
  capture_latency
  echo "captured $OUT/terminal-latency.json"
  exit 0
fi

if [ -n "$(git status --porcelain)" ] && [ "${AR_BASELINE_ALLOW_DIRTY:-}" != "1" ]; then
  echo "!! working tree is dirty; a baseline captured from an uncommitted state is not" >&2
  echo "   attributable to the commit written into COMMIT. Commit, stash, or set" >&2
  echo "   AR_BASELINE_ALLOW_DIRTY=1 if the changes provably cannot affect the six." >&2
  git status --porcelain >&2
  exit 1
fi

echo "→ COMMIT"
{
  git rev-parse HEAD
  date -u +%Y-%m-%dT%H:%M:%S%:z
  # When the override is used, the uncommitted files are written here rather than
  # left implicit. "HEAD plus these paths" is still attributable; "HEAD, roughly" is
  # not, and the difference only shows up when somebody has to trust the diff.
  if [ -n "$(git status --porcelain)" ]; then
    echo "--- uncommitted at capture time (AR_BASELINE_ALLOW_DIRTY) ---"
    git status --porcelain
  fi
} > "$OUT/COMMIT"

# Two dumps, flags off and flags on. Today they are byte-identical — every V2/V2.1
# router is mounted unconditionally and answers 404 through a dependency, so the flag
# is a run-time refusal and not a schema difference. That sameness is itself the
# thing worth recording: V2.2 must not be the phase that makes the document depend on
# a deployment's flags, because then "the API surface did not change" stops having a
# single answer.
dump_openapi() {
  uv run --project backend python - <<'PY'
import json, sys
sys.path.insert(0, "backend")
from app.main import app
json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
sys.stdout.write("\n")
PY
}

echo "→ openapi-flags-off.json"
CLIORA_PROJECTS_ENABLED=false CLIORA_AGENT_RUNS_ENABLED=false dump_openapi > "$OUT/openapi-flags-off.json"

echo "→ openapi-flags-on.json"
CLIORA_PROJECTS_ENABLED=true CLIORA_AGENT_RUNS_ENABLED=true dump_openapi > "$OUT/openapi-flags-on.json"

if cmp -s "$OUT/openapi-flags-off.json" "$OUT/openapi-flags-on.json"; then
  echo "   (identical, as expected: the flags refuse at run time, not in the schema)"
else
  echo "   !! the two dumps differ — see plan/18/01-…md §1; that is a finding, not a failure" >&2
fi

echo "→ schema.txt (needs the migrated test database)"
uv run --project backend python scripts/pj/schema_snapshot.py > "$OUT/schema.txt"

echo "→ contract-fixtures.txt"
uv run --project backend python scripts/tk/contract_snapshot.py > "$OUT/contract-fixtures.txt"

echo "→ frontend-routes.txt"
python3 scripts/ar/frontend_routes.py > "$OUT/frontend-routes.txt"

echo
echo "captured into $OUT:"
ls -1 "$OUT"
echo
if [ ! -f "$OUT/terminal-latency.json" ]; then
  echo "still missing: terminal-latency.json — run"
  echo "  CLIORA_DATABASE_URL=… scripts/e2e/run-stack.sh scripts/ar/capture-baseline.sh --latency-only"
fi
