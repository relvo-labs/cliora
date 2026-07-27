#!/usr/bin/env bash
# Produce one same-commit release snapshot (plan/06 §3 and §9, RT-07/RT-12).
#
# Runs every gate this runner can actually satisfy, records the rest as skipped
# with the prerequisite that is missing, merges the shards and resolves them into
# a snapshot. Nothing here decides a verdict: `trace snapshot` does, from the
# shards, and a skipped required gate keeps its criteria out of `verified`.
#
#   scripts/traceability/dogfood.sh [output-dir]   # default artifacts/traceability/local
#
# The tree must be clean. Evidence that describes a working copy nobody else has
# is not evidence, so `trace snapshot` refuses it and this script stops early
# rather than producing a pack that will be rejected at the end.
set -euo pipefail

cd "$(dirname "$0")/../.."
OUT="${1:-artifacts/traceability/local}"
RUN_ID="${GITHUB_RUN_ID:-dogfood-$(git rev-parse --short HEAD)}"
PROFILE="${GITHUB_REF_NAME:-local}"
SHARDS="$OUT/shards"

if [ -n "$(git status --porcelain)" ]; then
  echo "error: the working tree is dirty; commit or stash first" >&2
  git status --short >&2
  exit 1
fi

rm -rf "$OUT"
mkdir -p "$SHARDS"
COMMIT="$(git rev-parse HEAD)"
echo "commit:  $COMMIT"
echo "run id:  $RUN_ID"
echo

have() { command -v "$1" >/dev/null 2>&1; }

postgres_up() {
  [ -n "${CLIORA_TEST_DATABASE_URL:-}" ] && return 0
  (echo >"/dev/tcp/127.0.0.1/5432") >/dev/null 2>&1
}

# run <gate> [skip-reason]        -- skips when a reason is given
# run <gate> "" [--environment leg]...
run() {
  local gate="$1" reason="${2:-}"
  shift 2 || shift 1 || true
  local shard="$SHARDS/${gate}.json"
  if [ -n "$reason" ]; then
    printf '  %-32s skipped (%s)\n' "$gate" "$reason"
    scripts/trace run-gate "$gate" \
      --run-id "$RUN_ID" --profile "$PROFILE" \
      --skip-reason "$reason" --out "$shard" "$@" >/dev/null
    return 0
  fi
  printf '  %-32s running…\n' "$gate"
  local status=0
  scripts/trace run-gate "$gate" \
    --run-id "$RUN_ID" --profile "$PROFILE" --out "$shard" "$@" >/dev/null || status=$?
  if [ "$status" -eq 0 ]; then
    printf '  %-32s passed\n' "$gate"
  else
    printf '  %-32s FAILED\n' "$gate"
  fi
}

echo "gates:"
run GATE-TRACE-STATIC ""
run GATE-BACKEND-UNIT ""
run GATE-SECURITY ""
run GATE-CONTRACT-CROSS-LANGUAGE ""

if postgres_up; then
  run GATE-BACKEND-DB ""
else
  run GATE-BACKEND-DB "no PostgreSQL 16 reachable on this runner"
fi

if have go; then
  run GATE-DAEMON-RACE ""
else
  run GATE-DAEMON-RACE "the Go toolchain is not on PATH"
fi

if have tmux && have go; then
  run GATE-DAEMON-INTEGRATION "" --environment tmux
else
  run GATE-DAEMON-INTEGRATION "tmux and the Go toolchain are both required"
fi

if have npm; then
  run GATE-FRONTEND-UNIT ""
else
  run GATE-FRONTEND-UNIT "npm is not on PATH"
fi

# The browser matrix needs the full stack behind Playwright's webServer. Each leg
# is accounted for separately: a Chromium-only run must not read as three.
if [ "${CLIORA_DOGFOOD_E2E:-0}" = "1" ]; then
  run GATE-BROWSER-E2E "" --environment chromium --environment firefox --environment webkit
else
  run GATE-BROWSER-E2E "browser matrix not requested; set CLIORA_DOGFOOD_E2E=1 to run it"
fi

if [ "${CLIORA_DOGFOOD_PERF:-0}" = "1" ]; then
  run GATE-PERFORMANCE ""
else
  run GATE-PERFORMANCE "measurement run not requested; set CLIORA_DOGFOOD_PERF=1"
fi

run GATE-CAPACITY "needs the 100-node / 500-socket capacity rig"
run GATE-P3-EVIDENCE "needs the full P3 environment (PostgreSQL, tmux, browsers)"
run GATE-OPERATIONS "needs a deployed edge and the Docker Compose stack"
run GATE-MANUAL-INSTALL-MATRIX "manual six-platform procedure; no recorded execution"
run GATE-MANUAL-LIVE-CLI "manual procedure against the real Claude and Codex CLIs"

echo
scripts/trace merge "$SHARDS"/*.json --run-id "$RUN_ID" --out "$OUT/gate-results.json"
echo
set +e
scripts/trace snapshot \
  --results "$OUT/gate-results.json" \
  --commit "$COMMIT" \
  --out "$OUT/trace-snapshot.json" \
  --format human
VERDICT=$?
set -e
echo
echo "snapshot: $OUT/trace-snapshot.json"
exit "$VERDICT"
