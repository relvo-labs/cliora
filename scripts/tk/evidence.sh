#!/usr/bin/env bash
# TK-11: every non-browser local gate the phase claims, in one runnable pass.
#
# The output is the evidence for `plan/17/09-implementation-status.md`; a claim in that
# file without a line here is a claim nobody checked.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
: "${CLIORA_TEST_DATABASE_URL:=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test}"
: "${CLIORA_DATABASE_URL:=$CLIORA_TEST_DATABASE_URL}"
export CLIORA_TEST_DATABASE_URL CLIORA_DATABASE_URL

PASS=0
FAIL=0
run() {
  local name="$1"; shift
  printf '\n=== %s ===\n' "$name"
  if "$@"; then PASS=$((PASS + 1)); printf '  PASS %s\n' "$name";
  else FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "$name"; fi
}

run "GATE-TK-SCHEMA-ADDITIVE"      bash scripts/pj/gate-schema-additive.sh artifacts/tk/local/baseline/schema.txt
run "GATE-TK-MIGRATION-ROUNDTRIP"  bash scripts/tk/gate-migration-roundtrip.sh artifacts/tk/local/baseline/schema.txt
run "GATE-TK-CONTRACT-ADDITIVE"    bash scripts/tk/gate-contract-additive.sh
run "GATE-TK-TOUCH-LIST"           bash scripts/tk/gate-touch-list.sh
run "GATE-TK-FLAG-OFF"             bash scripts/tk/gate-flag-off.sh
run "make check"                   make check
run "make test-db"                 make test-db
run "make integration"             make integration
run "daemon: projection + CLI"     bash -c 'cd daemon && go test ./internal/files ./internal/cli ./internal/protocol'
run "M1 (board payload)"           bash -c 'python3 scripts/tk/measure_board_payload.py --cards 200 --out artifacts/tk/local/m1.json >/dev/null'
run "traceability"                 make traceability

printf '\n%s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
