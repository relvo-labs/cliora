#!/usr/bin/env bash
# Assemble the plan/08 exit-gate evidence pack (workspace tabs + system terminal).
#
#   scripts/wt/evidence.sh [output-dir]        # default artifacts/wt/local
#
# Same rule as the P1–P4 packs: every gate is *executed* and its exit status recorded
# in commands.txt. Nothing is asserted in prose, because prose does not go stale
# loudly. Legs that need something this environment lacks (PostgreSQL, tmux, a
# browser, an online node) are recorded in skipped.txt — never silently omitted. A
# pack that quietly dropped a gate would read as a pass, which is the one failure
# mode an evidence pack must not have.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/wt/local}"
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
  printf '%-44s exit=%-3s %s\n' "$label" "$status" "$*" >>"$COMMANDS"
  [ "$status" -eq 0 ] || FAILED=$((FAILED + 1))
  return $status
}

skip() {
  printf '%-44s %s\n' "$1" "$2" >>"$SKIPS"
  echo "-- skipped: $1 ($2)"
}

{
  echo "# plan/08 evidence pack (WT-01 … WT-11)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
  echo "go: $(go version 2>/dev/null || echo unavailable)"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# Static + unit
# --------------------------------------------------------------------------- #
run "backend format"        -                    uv run --project backend ruff format --check backend
run "backend lint"          -                    uv run --project backend ruff check backend
run "backend typecheck"     backend-mypy.txt     uv run --project backend mypy backend/app
run "backend unit"          backend-unit.txt     uv run --project backend python -m pytest backend/tests -q --ignore=backend/tests/db
run "frontend lint"         -                    npm run --prefix frontend lint
run "frontend typecheck"    frontend-tsc.txt     npm run --prefix frontend typecheck
run "frontend unit"         frontend-unit.txt    npm run --prefix frontend test:unit -- --run
run "contract (3 languages)" contract.txt        make contract

if command -v go >/dev/null 2>&1; then
  run "daemon test -race"   daemon-test.txt      bash -c 'cd daemon && go test -race ./...'
else
  skip "daemon test -race" "go toolchain unavailable"
fi

# --------------------------------------------------------------------------- #
# Database-backed: the RBAC/scope matrix and the shell endpoint live here
# --------------------------------------------------------------------------- #
if [ -n "$DB_URL" ]; then
  run "migrations up/down/up" migrations.txt bash -c '
    cd backend
    uv run --project . alembic upgrade head &&
    uv run --project . alembic downgrade 0011_workspace_favorites &&
    uv run --project . alembic upgrade head'
  run "backend db suite"    backend-db.txt       make test-db
else
  skip "migrations up/down/up" "CLIORA_TEST_DATABASE_URL unset"
  skip "backend db suite" "CLIORA_TEST_DATABASE_URL unset"
fi

# --------------------------------------------------------------------------- #
# Traceability: FR-SHELL-001 must be verifiable and SCOPE-011 must be superseded
# --------------------------------------------------------------------------- #
run "traceability"          traceability.txt     make traceability

# --------------------------------------------------------------------------- #
# Browser E2E needs the whole stack plus an online node with a runtime. The
# system-terminal leg is not a separate gate: session.spec.ts opens a TERMINAL
# tab against the stack's node, so it either ran here or it did not run at all.
#
# Three ways in, in decreasing order of "already set up for us":
#   1. E2E_FULL_STACK=1 — a stack is already running (the CI job's shape).
#   2. E2E_STACK_DATABASE_URL — stand the stack up ourselves via run-stack.sh.
#      This needs go + tmux + a reachable PostgreSQL, all of which a developer
#      box running the DB gates already has. Use a database of its own: the
#      script migrates it and seeds an admin.
#   3. neither — skip, and say which of the two would have worked.
# --------------------------------------------------------------------------- #
STACK_DB="${E2E_STACK_DATABASE_URL:-}"

# Decide how the suite gets a stack before doing any work for it.
E2E_MODE="none"
E2E_WHY=""
if [ "${E2E_FULL_STACK:-}" = "1" ]; then
  E2E_MODE="existing"
elif [ -z "$STACK_DB" ]; then
  E2E_WHY="set E2E_STACK_DATABASE_URL to a spare database (needs go + tmux), or E2E_FULL_STACK=1 against a running stack"
elif ! command -v tmux >/dev/null 2>&1 || ! command -v go >/dev/null 2>&1; then
  E2E_WHY="E2E_STACK_DATABASE_URL is set but go and/or tmux is missing"
else
  E2E_MODE="own"
fi

if [ "$E2E_MODE" = "none" ]; then
  skip "browser e2e" "$E2E_WHY"
  skip "system terminal on a real node" "part of the browser e2e leg, which did not run here"
else
  # WebKit needs system libraries only root can install (`playwright install-deps`)
  # and is the engine that has historically differed on WebSocket behaviour, so it
  # is a real leg an unprivileged host simply cannot offer. Probe it up front
  # rather than discovering it as a suite failure: an unavailable browser is an
  # environment gap, and a gap belongs in skipped.txt, not in a red gate.
  E2E_ENGINES="chromium firefox"
  if (cd "$ROOT/frontend" && node -e "
    require('@playwright/test').webkit.launch()
      .then((b) => b.close()).then(() => process.exit(0)).catch(() => process.exit(1))
  " >/dev/null 2>&1); then
    E2E_ENGINES="$E2E_ENGINES webkit"
  else
    skip "browser e2e on webkit" "webkit cannot launch here (its system libraries need root); CI only"
  fi
  PLAYWRIGHT_ARGS=""
  for engine in $E2E_ENGINES; do PLAYWRIGHT_ARGS="$PLAYWRIGHT_ARGS --project=$engine"; done
  E2E_CMD="cd '$ROOT/frontend' && exec npx playwright test$PLAYWRIGHT_ARGS --reporter=list"

  if [ "$E2E_MODE" = "existing" ]; then
    run "browser e2e: system terminal + tabs ($E2E_ENGINES)" e2e.txt \
      bash -c "$E2E_CMD"
  else
    run "browser e2e: system terminal + tabs, own stack ($E2E_ENGINES)" e2e.txt \
      env E2E_FULL_STACK=1 \
      CLIORA_DATABASE_URL="$STACK_DB" \
      CLIORA_TEST_DATABASE_URL="$STACK_DB" \
      E2E_ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}" \
      E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}" \
      CLIORA_ADMIN_PASSWORD="${CLIORA_ADMIN_PASSWORD:-e2e-admin-pw}" \
      "$ROOT/scripts/e2e/run-stack.sh" bash -c "$E2E_CMD"
  fi

  # The suite's own skips are the honest record of what the stack could not offer
  # (no online node, or no shell binary on it). Surface them rather than letting a
  # green leg imply the system terminal was exercised.
  if grep -qE '[0-9]+ skipped' "$OUT/e2e.txt" 2>/dev/null; then
    skip "some browser e2e cases" "the suite skipped what this stack could not offer; see e2e.txt"
  fi
fi

# --------------------------------------------------------------------------- #
# summary.md
# --------------------------------------------------------------------------- #
{
  echo "# plan/08 evidence summary"
  echo
  echo '```'
  cat "$COMMANDS"
  echo '```'
  echo
  if [ -s "$SKIPS" ]; then
    echo "## Skipped"
    echo
    echo '```'
    cat "$SKIPS"
    echo '```'
    echo
  fi
  echo "## Verdict"
  echo
  if [ "$FAILED" -eq 0 ]; then
    echo "**All executed gates passed.** See Skipped for what this run did not cover."
  else
    echo "**$FAILED gate(s) failed.** The pack is evidence of a failing run; see commands.txt."
  fi
  echo
  echo "Security review: \`docs/security-review-p8.md\`. Ticket status: \`plan/08/05-implementation-status.md\`."
} >"$OUT/summary.md"

echo
echo "evidence pack: $OUT"
echo "summary:       $OUT/summary.md"
[ "$FAILED" -eq 0 ] || exit 1
