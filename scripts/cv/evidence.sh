#!/usr/bin/env bash
# Everything `v2.0.0-alpha.2` claims, run in one go (`CE-03`, `plan/24/02` §7).
#
#   scripts/cv/evidence.sh              # the hermetic half: tests, gates, checks
#   E2E=1 scripts/cv/evidence.sh        # also the stack half: journeys, compat, perf
#
# Prints one line per check and a tally at the end. **A skip must carry a reason**: a
# skip with an explanation is useful, a silent one is a green tick that means nothing
# (the practice `plan/15` established and `scripts/pj/evidence.sh` kept).
#
# This phase has two silent skips waiting for anybody who forgets:
#
#   * `backend/tests/db/` skips its whole suite when `CLIORA_TEST_DATABASE_URL` is unset
#     (`conftest.py`), and prints `15 skipped` in green;
#   * a playwright spec behind `test.skip(!enabled, …)` exits 0 having run nothing.
#
# `GATE-CE-JOURNEY-COVERAGE` exists for the second one. This script refuses to start
# without a database for the first.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ROOT="$PWD"

export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"
: "${CLIORA_TEST_DATABASE_URL:=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test}"
: "${CLIORA_DATABASE_URL:=$CLIORA_TEST_DATABASE_URL}"
export CLIORA_TEST_DATABASE_URL CLIORA_DATABASE_URL
OUT="artifacts/cv/local"
mkdir -p "$OUT/journeys"

PASS=0; FAIL=0; SKIP=0
FAILED_NAMES=()

check() {
  local name="$1"; shift
  printf '  %-46s ' "$name"
  if output="$("$@" 2>&1)"; then
    printf '\033[32mPASS\033[0m\n'; PASS=$((PASS + 1))
  else
    printf '\033[31mFAIL\033[0m\n'; FAIL=$((FAIL + 1)); FAILED_NAMES+=("$name")
    printf '%s\n' "$output" | tail -8 | sed 's/^/        /'
  fi
}

skip() {
  printf '  %-46s \033[33mSKIP\033[0m  %s\n' "$1" "$2"; SKIP=$((SKIP + 1))
}

echo "=== 0. environment ==="
{
  echo "commit:   $(git rev-parse HEAD)"
  echo "dirty:    $(git status --porcelain | wc -l) file(s)"
  echo "uv:       $(uv --version 2>/dev/null || echo missing)"
  echo "go:       $(go version 2>/dev/null || echo missing)"
  echo "node:     $(node --version 2>/dev/null || echo missing)"
  echo "database: $CLIORA_DATABASE_URL"
  echo "agentd:   $(cat daemon/VERSION)"
  # The newest *released* heading, not the first version-shaped string in the file: the
  # top entry is `Unreleased — v2.0.0-alpha.2`, and matching that printed the product
  # version where the contract version belongs.
  echo "contract: $(grep -m1 -oE '^## [0-9]+\.[0-9]+\.[0-9]+' contracts/CHANGELOG.md | tr -d '# ' || true)"
} | sed 's/^/  /' | tee "$OUT/environment.txt"

echo
echo "=== 1. hermetic: tests and checks ==="
check "backend unit + db (pytest)" \
  bash -c "cd backend && uv run --project . pytest tests -q"
check "daemon (go test)" bash -c "cd daemon && go test ./..."
check "frontend unit (vitest)" bash -c "cd frontend && npm run test:unit -- --run"
check "make check" make check

echo
echo "=== 2. gates ==="
# The eight V2-C1 gates, then the three closeout ones. Two scripts because they answer
# two different questions — "does alpha.2 still hold" and "did this phase stay inside
# its own scope".
check "V2-C1 gates (8)" scripts/cv/gates.sh

echo
echo "=== 3. stack: journeys, compatibility, performance ==="
if [ "${E2E:-}" != "1" ]; then
  skip "seven journeys"        "E2E=1 to run them (needs a stack; minutes, not seconds)"
  skip "0.12.0 compatibility"  "E2E=1"
  skip "four measurements"     "E2E=1"
else
  # One stack for all of it. Starting three would triple the setup and, worse, make the
  # quiet-database guard meaningless: each journey would inherit the previous one's runs.
  check "journeys + compat + perf (one stack)" scripts/cv/stack-evidence.sh
fi

# **The closeout gates go last, and the first draft of this script had them in §2.**
# `GATE-CE-JOURNEY-COVERAGE` reads what the journeys produced, so running it before them
# reads the *previous* run's evidence — which passes on a machine that has run this
# before and fails on a clean checkout, the worse way round of the two.
echo
echo "=== 4. closeout gates ==="
# `CE_AT` names the commit the evidence is supposed to belong to. HEAD while a release is
# being prepared; **the tag afterwards**, because a released version's evidence belongs to
# the commit that was tagged and not to whatever has been committed since.
check "closeout gates (3)" \
  uv run --project backend python scripts/cv/gate_closeout.py \
  --baseline "${CE_BASELINE:-ac3dfef}" --at "${CE_AT:-HEAD}"

echo
printf 'evidence: %d passed, %d failed, %d skipped\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
  printf 'failed: %s\n' "${FAILED_NAMES[*]}"
  echo "alpha.2 is NOT tag-able"
  exit 1
fi
if [ "$SKIP" -gt 0 ]; then
  echo "note: $SKIP check(s) skipped — the tag needs a run with E2E=1"
fi
echo "all executed checks passed"
