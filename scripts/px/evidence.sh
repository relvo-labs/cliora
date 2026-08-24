#!/usr/bin/env bash
# PX-65/PX-66: every machine-checkable claim in one run (plan/26/10).
#
# The point of one script is that a reader can see the whole verdict without knowing which
# of eleven commands to run — and that a **skipped** step says so instead of passing
# quietly. `plan/24` spent a whole phase learning that evidence is its own ticket; this is
# where that lands.
#
#   CLIORA_DATABASE_URL=… scripts/px/evidence.sh
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

FAILED=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s%s\n' "$1" "${2:+ — $2}"; FAILED=1; }
skip() { printf '  \033[33mSKIP\033[0m  %s — %s\n' "$1" "$2"; }

run() {
  local name="$1"; shift
  if output="$("$@" 2>&1)"; then pass "$name"; else
    fail "$name" "$(printf '%s' "$output" | tail -2 | tr '\n' ' ')"
  fi
}

echo "V2-P1 evidence"
echo

echo "[1/9] the eleven gates"
scripts/px/gates.sh | sed 's/^/  /' || FAILED=1

echo
echo "[2/9] static checks"
run "backend format"    uv run --project backend ruff format --check backend scripts/px
run "backend lint"      uv run --project backend ruff check backend scripts/px
run "backend types"     uv run --project backend mypy backend/app
run "frontend format"   bash -c 'cd frontend && npm run format:check'
run "frontend lint"     bash -c 'cd frontend && npm run lint'
run "frontend types"    bash -c 'cd frontend && npm run typecheck'
run "CSS tokens"        node scripts/frontend/check-tokens.mjs

echo
echo "[3/9] unit and component suites"
run "backend unit"      uv run --project backend pytest backend/tests -q
run "frontend unit"     bash -c 'cd frontend && npm run test:unit -- --run'

echo
echo "[4/9] database-backed suites"
if [ -n "${CLIORA_DATABASE_URL:-}" ]; then
  run "backend db" bash -c 'cd backend && CLIORA_TEST_DATABASE_URL="$CLIORA_DATABASE_URL" uv run --project . pytest tests/db -q'
else
  skip "backend db" "set CLIORA_DATABASE_URL"
fi

echo
echo "[5/9] traceability"
run "traceability" make traceability-validate

echo
echo "[6/9] the published catalogues"
run "error catalog"     uv run --project backend python scripts/p4/render_error_catalog.py --check
run "permission matrix" uv run --project backend python scripts/p4/render_permission_matrix.py --check

echo
echo "[7/9] measurements"
for artifact in \
  artifacts/px/local/w0/attention-60-queued.json \
  artifacts/px/local/w2/work-api-measurement.json \
  artifacts/px/local/baseline/work-item-bytes.json \
  artifacts/px/local/baseline/board-order-explain.json
do
  if [ -f "$artifact" ]; then pass "$artifact"; else fail "$artifact" "not captured"; fi
done

echo
echo "[8/9] the rollback drill"
if [ -f artifacts/px/local/rollback/work-views-after.tsv ]; then
  pass "artifacts/px/local/rollback (run scripts/px/rollback-drill.sh to refresh)"
else
  fail "rollback drill" "not run"
fi

echo
echo "[9/9] journeys"
# **The same check as `GATE-PX-JOURNEY-COVERAGE` in step 1, printed again on purpose.**
# Step 1 collapses it to one PASS line; here a reader wants to see *which* journey said
# what, because "six journeys passed" and "J1 passed" are different sentences and only the
# second one is this phase's purpose. The check is a filesystem scan, so running it twice
# costs nothing.
#
# The three daemon journeys are read from the JSON they wrote rather than re-run: each
# needs `scripts/e2e/run-stack.sh` to build a daemon, enrol a node and enable a runner.
# The gate is what stops that being a loophole — a verdict older than the code it covers
# fails, so "read from a file" cannot become "read from a stale file".
#
#   E2E_RUNNER=1 CLIORA_DATABASE_URL=… scripts/e2e/run-stack.sh \
#     uv run --project backend python scripts/px/journeys/j1_vague_to_done.py
run "six journeys, every assertion, on this code" \
  uv run --project backend python scripts/px/gate_journey_coverage.py
uv run --project backend python scripts/px/gate_journey_coverage.py 2>/dev/null \
  | grep -E "^        j" || true

echo
if [ "$FAILED" -eq 0 ]; then
  echo "V2-P1 evidence: all machine-checkable claims hold"
else
  echo "V2-P1 evidence: FAILED"
fi
exit "$FAILED"
