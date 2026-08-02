#!/usr/bin/env bash
# Assemble the plan/12 exit-gate evidence pack (privileged node posture, ADR 0023).
#
#   scripts/pv/evidence.sh [output-dir]        # default artifacts/pv/local
#
# Same rule as the P1–P4, plan/08 and plan/11 packs: every gate is *executed* and its exit
# status recorded in commands.txt. A leg this environment cannot run (no PostgreSQL, no Go,
# no browser, no enrolled node) goes in skipped.txt — never silently omitted, because a pack
# that dropped a gate reads exactly like a pack that passed it.
#
# Two legs cannot pass here by construction and are recorded every time rather than assumed:
# the browser scroll assertion needs Playwright's system libraries, and the node posture
# check needs a machine with agentd installed in the posture under test.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/pv/local}"
mkdir -p "$OUT"
COMMANDS="$OUT/commands.txt"
SKIPS="$OUT/skipped.txt"
: >"$COMMANDS"
: >"$SKIPS"

DB_URL="${CLIORA_TEST_DATABASE_URL:-}"
FAILED=0

run() {
  local label="$1" outfile="$2"
  shift 2
  local target="/dev/null"
  [ "$outfile" != "-" ] && target="$OUT/$outfile"
  echo "==> $label"
  "$@" >"$target" 2>&1
  local status=$?
  printf '%-46s exit=%-3s %s\n' "$label" "$status" "$*" >>"$COMMANDS"
  [ "$status" -eq 0 ] || FAILED=$((FAILED + 1))
  return $status
}

skip() {
  printf '%-46s %s\n' "$1" "$2" >>"$SKIPS"
  echo "-- skipped: $1 ($2)"
}

{
  echo "# plan/12 evidence pack (PV-01 … PV-11)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "agentd_version: $(cat daemon/VERSION)"
  echo "contract_version: $(grep -m1 '^## ' contracts/CHANGELOG.md)"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
  echo "go: $(go version 2>/dev/null || echo unavailable)"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
  echo "tmux: $(tmux -V 2>/dev/null || echo unavailable)"
  echo "codex: $(codex --version 2>/dev/null || echo 'not installed')"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# 1. The boundary that must not move: nobody outside the node names an argument.
# --------------------------------------------------------------------------- #
run "gate:argv-channel" argv-channel.txt scripts/pv/check-no-argv-channel.sh
if command -v uv >/dev/null 2>&1; then
  run "scope-guards" scope-guards.txt \
    uv run --project backend pytest backend/tests/test_scope_guards.py -q
else
  skip "scope-guards" "uv not available"
fi

# 2. Contract: the two report-only fields, across all three consumers.
if command -v uv >/dev/null 2>&1 && command -v go >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  run "contract:three-consumers" contract.txt make contract
else
  skip "contract:three-consumers" "needs uv, go and npm"
fi

# 3. Daemon: the flag table, the config veto, the tmux config, the sudoers writer.
if command -v go >/dev/null 2>&1; then
  run "daemon:unit" daemon-unit.txt sh -c 'cd daemon && go test ./...'
  run "daemon:race" daemon-race.txt sh -c \
    'cd daemon && go test -race ./internal/runtime/ ./internal/tmux/ ./internal/session/ ./internal/config/ ./internal/install/'
  run "daemon:launch-table" launch-table.txt sh -c \
    'cd daemon && go test ./internal/runtime -run "TestOnlyCodexHasLaunchFlags|TestResolveLaunch|TestUnsupportedFlag" -v'
  run "daemon:sudoers-and-unit" sudoers.txt sh -c \
    'cd daemon && go test ./internal/install -run "TestSudoers|TestUnit|TestInstall" -v'
else
  skip "daemon:*" "go not available"
fi

# 4. Central: posture persisted, audited on change, silent for an older daemon.
if [ -n "$DB_URL" ]; then
  run "central:db" central-db.txt sh -c \
    "cd backend && CLIORA_DATABASE_URL=$DB_URL CLIORA_TEST_DATABASE_URL=$DB_URL uv run --project . pytest tests/db -q"
else
  skip "central:db" "CLIORA_TEST_DATABASE_URL not set (no PostgreSQL)"
fi
if command -v uv >/dev/null 2>&1; then
  run "central:unit" central-unit.txt \
    uv run --project backend pytest backend/tests -q --ignore=backend/tests/db
else
  skip "central:unit" "uv not available"
fi

# 5. Console: the posture is stated, and never claimed when the node did not report it.
if command -v npm >/dev/null 2>&1; then
  run "console:unit" console-unit.txt npm --prefix frontend run test:unit
else
  skip "console:unit" "npm not available"
fi

# 6. The user's actual complaint, in a browser. Needs Playwright's system libraries *and* a
# running stack with an online node.
#
# Playwright exits 0 for a skipped test, so a run with no stack would land in commands.txt as
# `exit=0` and read as a pass. That is the exact failure this pack exists to prevent, so the
# output is inspected and a skipped run is recorded as a skip.
if command -v npx >/dev/null 2>&1; then
  # Run from frontend/ rather than with --prefix: Playwright writes test-results/ into the
  # working directory, and only frontend/test-results is gitignored — a run from the repo
  # root leaves an untracked directory behind.
  run "console:e2e-scroll" e2e-scroll.txt sh -c \
    'cd frontend && npx playwright test tests/e2e/session.spec.ts -g "wheel scrolls"'
  if grep -qE '^ *[0-9]+ skipped' "$OUT/e2e-scroll.txt" 2>/dev/null &&
    ! grep -qE '^ *[0-9]+ passed' "$OUT/e2e-scroll.txt" 2>/dev/null; then
    sed -i '/^console:e2e-scroll /d' "$COMMANDS"
    skip "console:e2e-scroll" "the spec skipped itself (no stack or no online node); scrolling is then only covered by GATE-PV-NODE-POSTURE"
  fi
else
  skip "console:e2e-scroll" "npx not available"
fi

# 7. Traceability: the nine new criteria are registered and covered.
run "traceability" traceability.txt make traceability

# 8. The three facts, measured on a node. This leg *observes*; it does not assert, so a zero
# exit means "the observations were taken", not "the node is in the privileged posture".
# Which posture it actually found is written into the summary, because an observation pack
# whose reader has to open another file to learn the answer is half a pack.
if command -v agentd >/dev/null 2>&1 && [ -f /etc/agentd/config.yaml ]; then
  run "node:posture(observe)" node-posture-run.txt \
    scripts/pv/node-posture-check.sh "$OUT/node-posture.txt"
  POSTURE_NOTE="observed on this host: $(grep -E '^(sudo -n true|codex)' "$OUT/node-posture.txt" 2>/dev/null | tr '\n' ';' | tr -s ' ')"
else
  skip "node:posture(observe)" "no enrolled node here (GATE-PV-NODE-POSTURE is release-triggered)"
  POSTURE_NOTE="not observed"
fi

{
  echo "# summary"
  echo "failed_gates: $FAILED"
  echo "node_posture: ${POSTURE_NOTE:-not observed}"
  echo "skipped_gates: $(wc -l <"$SKIPS")"
  echo ""
  echo "## executed"
  cat "$COMMANDS"
  echo ""
  echo "## skipped"
  cat "$SKIPS"
} >"$OUT/summary.md"

echo ""
echo "pack written to $OUT (failed=$FAILED, skipped=$(wc -l <"$SKIPS"))"
exit "$FAILED"
