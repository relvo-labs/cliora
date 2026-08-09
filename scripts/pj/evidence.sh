#!/usr/bin/env bash
# Everything plan/16 claims, run in one go (PJ-07).
#
# Prints one line per check and a tally at the end. A skip must carry a reason: a
# skip with an explanation is useful, a silent one is a green tick that means
# nothing (the practice plan/15 established).
#
#   scripts/pj/evidence.sh
#
# Needs PostgreSQL at CLIORA_TEST_DATABASE_URL, migrated to head. The browser-based
# checks (nav baseline, project smoke) need a stack and are run separately by
# scripts/pj/browser-evidence.sh — they are listed here as explicit skips so the
# tally never implies they ran.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
: "${CLIORA_TEST_DATABASE_URL:=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test}"
: "${CLIORA_DATABASE_URL:=$CLIORA_TEST_DATABASE_URL}"
export CLIORA_TEST_DATABASE_URL CLIORA_DATABASE_URL

PASS=0
FAIL=0
SKIP=0
FAILED_NAMES=()

check() {
  local name="$1"
  shift
  if "$@" >/tmp/pj-evidence.log 2>&1; then
    echo "ok    $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL  $name"
    tail -n 12 /tmp/pj-evidence.log | sed 's/^/        /'
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
}

skip() {
  echo "skip  $1 — $2"
  SKIP=$((SKIP + 1))
}

echo "=== gates ==="
check "GATE-PJ-NO-WIRE (daemon, contract, ws, files, terminal, deploy untouched)" \
  scripts/pj/gate-no-wire.sh
check "GATE-PJ-FLAG-OFF (seven project routes 404; feature absent)" \
  scripts/pj/gate-flag-off.sh
check "OpenAPI surface is additive only" \
  uv run --project backend python scripts/pj/openapi_diff.py --quiet

echo
echo "=== schema ==="
check "DB schema differs from the baseline by additions only" \
  scripts/pj/gate-schema-additive.sh
check "migration 0021+0022 down-and-up returns to the baseline" \
  scripts/pj/gate-migration-roundtrip.sh

echo
echo "=== suites ==="
check "make check (format, lint, typecheck, unit, contract, build, traceability)" make check
check "make test-db (includes the RBAC matrix and the project suites)" make test-db
check "make integration (daemon session, connection, files, workspace, tunnel)" make integration
check "make traceability (validate, selectors, coverage --strict, baseline, tests)" make traceability

echo
echo "=== measurements ==="
check "M-PJ-01 project detail with 50 bindings stays below p95 200ms" \
  uv run --project backend python scripts/pj/measure-project-detail.py

echo
echo "=== browser (run separately; they need a live stack) ==="
skip "full browser regression + nav baseline, flag off" "needs a stack: scripts/pj/browser-evidence.sh"
skip "full browser regression + project acceptance + nav height, flag on" "needs a stack: scripts/pj/browser-evidence.sh"

echo
echo "----------------------------------------"
echo "$PASS passed, $FAIL failed, $SKIP skipped"
if [ "$FAIL" -gt 0 ]; then
  printf 'failed: %s\n' "${FAILED_NAMES[*]}"
  exit 1
fi
