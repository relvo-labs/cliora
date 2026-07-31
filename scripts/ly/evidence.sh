#!/usr/bin/env bash
# Assemble the plan/09 exit-gate evidence pack (layout height + centre workspace).
#
#   scripts/ly/evidence.sh [output-dir]        # default artifacts/ly/local
#
# Same rule as the P1-P4 and plan/08 packs: every gate is *executed* and its exit
# status recorded in commands.txt. Legs this environment cannot offer (a browser, a
# stack, an online node) go to skipped.txt — never silently omitted, because a pack
# that quietly dropped a gate reads as a pass.
#
# What makes this pack different from plan/08's: the load-bearing gate is a
# *measurement*. Everything else here can pass while the terminal occupies half its
# pane — that is precisely what happened for three phases, since jsdom has no
# layout and the only existing layout test measured width. So the browser leg is not
# an optional extra: without it, this pack proves the code compiles, not that the
# terminal is usable.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/ly/local}"
mkdir -p "$OUT"
COMMANDS="$OUT/commands.txt"
SKIPS="$OUT/skipped.txt"
: >"$COMMANDS"
: >"$SKIPS"

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
  echo "# plan/09 evidence pack (LY-01 … LY-08)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# Frontend static + unit. Necessary, and on their own not sufficient (see header).
# --------------------------------------------------------------------------- #
run "frontend format"       -                  npm run --prefix frontend format:check
run "frontend lint"         -                  npm run --prefix frontend lint
run "frontend typecheck"    frontend-tsc.txt   npm run --prefix frontend typecheck
run "frontend unit"         frontend-unit.txt  npm run --prefix frontend test:unit -- --run
run "frontend build"        frontend-build.txt npm run --prefix frontend build

# --------------------------------------------------------------------------- #
# The three CI grep gates, run here exactly as ci.yml runs them. They are the only
# gates in this pack that need no browser, so they are the regression floor: if the
# measuring leg is skipped, these are what stops the old CSS from coming back.
# --------------------------------------------------------------------------- #
run "gate: one height source"       gate-height.txt  scripts/ly/layout-gates.sh height
run "gate: panels are flex columns" gate-panels.txt  scripts/ly/layout-gates.sh panels
run "gate: sidebar spec vs token"   gate-sidebar.txt scripts/ly/layout-gates.sh sidebar

# --------------------------------------------------------------------------- #
# Traceability: FR-TERM-001.AC-13/AC-14 must be verifiable, and the pinned
# coverage summary must be the one this phase intends (381/250).
# --------------------------------------------------------------------------- #
if command -v uv >/dev/null 2>&1; then
  run "traceability"        traceability.txt   make traceability
else
  # `scripts/trace` runs through `uv run --project backend`. No uv is an
  # environment gap like a missing browser, not a failing gate — but it must be
  # visible, because this leg is what proves the two new criteria are registered.
  skip "traceability" "uv is not installed; run 'make traceability' on a host that has it"
fi

# --------------------------------------------------------------------------- #
# The measuring leg. Same three ways in as plan/08's pack, because it is the same
# suite: the new geometry assertions live in session.spec.ts and run with it.
# --------------------------------------------------------------------------- #
STACK_DB="${E2E_STACK_DATABASE_URL:-}"
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
  skip "browser e2e: layout measurement" "$E2E_WHY"
  skip "shell opens at the panel's size" "part of the browser e2e leg, which did not run here"
else
  # WebKit's system libraries need root, and an engine that cannot launch is an
  # environment gap, not a red gate.
  E2E_ENGINES="chromium firefox"
  if (cd "$ROOT/frontend" && node -e "
    require('@playwright/test').webkit.launch()
      .then((b) => b.close()).then(() => process.exit(0)).catch(() => process.exit(1))
  " >/dev/null 2>&1); then
    E2E_ENGINES="$E2E_ENGINES webkit"
  else
    skip "browser e2e on webkit" "webkit cannot launch here (system libraries need root); CI only"
  fi
  PLAYWRIGHT_ARGS=""
  for engine in $E2E_ENGINES; do PLAYWRIGHT_ARGS="$PLAYWRIGHT_ARGS --project=$engine"; done
  # --grep layout: this pack is about geometry. The rest of session.spec.ts is
  # plan/08's pack; running it again here would only make this one slower to read.
  E2E_CMD="cd '$ROOT/frontend' && exec npx playwright test$PLAYWRIGHT_ARGS --grep layout --reporter=list"

  if [ "$E2E_MODE" = "existing" ]; then
    run "browser e2e: layout measurement ($E2E_ENGINES)" e2e-layout.txt \
      bash -c "$E2E_CMD"
  else
    run "browser e2e: layout measurement, own stack ($E2E_ENGINES)" e2e-layout.txt \
      env E2E_FULL_STACK=1 \
      CLIORA_DATABASE_URL="$STACK_DB" \
      CLIORA_TEST_DATABASE_URL="$STACK_DB" \
      E2E_ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}" \
      E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}" \
      CLIORA_ADMIN_PASSWORD="${CLIORA_ADMIN_PASSWORD:-e2e-admin-pw}" \
      "$ROOT/scripts/e2e/run-stack.sh" bash -c "$E2E_CMD"
  fi

  # A stack with no online node skips itself, and a skipped measurement must not
  # read as a passing one.
  if grep -qE '[0-9]+ skipped' "$OUT/e2e-layout.txt" 2>/dev/null; then
    skip "some layout cases" "the suite skipped what this stack could not offer; see e2e-layout.txt"
  fi
fi

# --------------------------------------------------------------------------- #
# summary.md
# --------------------------------------------------------------------------- #
{
  echo "# plan/09 evidence summary"
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
  if grep -q "browser e2e: layout measurement" "$SKIPS" 2>/dev/null; then
    echo "> The measuring gate did not run here. The three grep gates above prevent the"
    echo "> old CSS from returning, but only the browser leg can show that the terminal"
    echo "> fills its pane — treat this pack as incomplete until CI runs it."
    echo
  fi
  echo "Report: \`docs/ly-report.md\`. Ticket status: \`plan/09/05-implementation-status.md\`."
} >"$OUT/summary.md"

echo
echo "evidence pack: $OUT"
echo "summary:       $OUT/summary.md"
[ "$FAILED" -eq 0 ] || exit 1
