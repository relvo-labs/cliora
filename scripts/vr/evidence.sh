#!/usr/bin/env bash
# Assemble the plan/28 exit-gate evidence pack (visual refresh: token contract,
# themes, App Shell, components, pages).
#
#   scripts/vr/evidence.sh [output-dir]        # default artifacts/vr/local
#
# Same rule as every pack since P1: every gate is *executed* and its exit status
# recorded in commands.txt. Legs this environment cannot offer (a browser, a
# full stack, an online node) go to skipped.txt — never silently omitted,
# because a pack that quietly dropped a gate reads as a pass.
#
# WHAT MAKES THIS PACK DIFFERENT
#
# The four static gates here are cheap and they are not the interesting part.
# Three claims in this phase can only be shown in a browser:
#
#   1. a theme switch recolours in place — it does not rebuild the terminal and
#      lose the session, the scrollback and anything half-typed;
#   2. the theme is in force on the *first paint*, so a returning user whose
#      choice differs from their OS preference does not see a flash;
#   3. the terminal still has enough rows to work in after this phase made it
#      shorter (a status bar, a fixed tab strip, a taller work header, and a
#      13px -> 14px font change).
#
# None of those is visible to a grep, and (1) is invisible in review as well: a
# reconnect on a local stack finishes in a few hundred milliseconds and the
# screen looks fine again immediately. So the browser leg is not an optional
# extra — without it this pack proves the code compiles and the arithmetic is
# right, not that the workspace still works.
#
# contrast.txt is the pack's headline artefact and it holds *measured values*,
# not pass/fail marks. A report that says "all pass" is a rubber stamp; one that
# prints 4.72:1 beside the two colours can be disagreed with.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/vr/local}"
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
  printf '%-52s exit=%-3s %s\n' "$label" "$status" "$*" >>"$COMMANDS"
  [ "$status" -eq 0 ] || FAILED=$((FAILED + 1))
  return $status
}

skip() {
  printf '%-52s %s\n' "$1" "$2" >>"$SKIPS"
  echo "-- skipped: $1 ($2)"
}

{
  echo "# plan/28 evidence pack (VR-01 … VR-12)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
  echo "npm: $(npm -v 2>/dev/null || echo unavailable)"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# Frontend static + unit. Necessary, and on their own not sufficient.
# --------------------------------------------------------------------------- #
run "frontend format"    -                  npm run --prefix frontend format:check
run "frontend lint"      -                  npm run --prefix frontend lint
run "frontend typecheck" frontend-tsc.txt   npm run --prefix frontend typecheck
run "frontend unit"      frontend-unit.txt  npm run --prefix frontend test:unit -- --run
run "frontend build"     frontend-build.txt npm run --prefix frontend build

# --------------------------------------------------------------------------- #
# The four plan/28 gates, run here exactly as ci.yml runs them. They are the
# regression floor: if the measuring leg is skipped, these are what stop the
# palette from being bypassed again.
# --------------------------------------------------------------------------- #
run "gate: no literal colour"     gate-literal-color.txt scripts/vr/vr-gates.sh literal-color
run "gate: no retired token"      gate-legacy-token.txt  scripts/vr/vr-gates.sh legacy-token
run "gate: no glyph icon"         gate-glyph-icon.txt    scripts/vr/vr-gates.sh glyph-icon
run "gate: theme contract"        gate-theme-contract.txt scripts/vr/vr-gates.sh theme-contract

# plan/09's three gates must still be green, and must not have been *made* green
# by editing them. A diff against HEAD is the cheapest honest check: this phase
# reshaped the workspace, so "we did not touch the gate" is a claim that needs
# evidence rather than a promise.
run "gate: plan/09 layout invariants" gate-layout.txt scripts/ly/layout-gates.sh all
if ! git diff --quiet HEAD -- scripts/ly/layout-gates.sh 2>/dev/null; then
  echo "WARNING: scripts/ly/layout-gates.sh is modified in this working tree." \
    >>"$OUT/gate-layout.txt"
  printf '%-52s %s\n' "plan/09 gate script modified" \
    "the layout gates were edited; a PR doing that must say why the invariant no longer holds" \
    >>"$SKIPS"
fi

# --------------------------------------------------------------------------- #
# contrast.txt — the measured table, not a pass/fail line.
#
# Every declared pair, in every theme, with its ratio. The pair list comes from
# the component contracts rather than from the token table, and that direction
# is why the list is trustworthy: the five design documents built their tables
# from the token list, which is exactly how all five missed accent.primary on
# accent.subtle (the selected state of navigation and tabs), a pair that fails
# in two themes.
# --------------------------------------------------------------------------- #
run "contrast: all pairs, all themes" contrast.txt \
  env VITEST_CONTRAST_TABLE=1 \
  npm run --prefix frontend test:unit -- --run src/theme/theme.contrast.test.ts --reporter=verbose

# --------------------------------------------------------------------------- #
# VR-01 §1/§2: the xterm geometry probe. Needs only chromium, no stack — the
# question ("how many rows does 14px/1.2 give in a 674px panel") is xterm's own,
# not Cliora's.
# --------------------------------------------------------------------------- #
PROBE="$ROOT/scripts/vr/xterm-geometry-probe.mjs"
if [ ! -f "$PROBE" ]; then
  skip "xterm geometry probe" "scripts/vr/xterm-geometry-probe.mjs is missing"
elif (cd "$ROOT/frontend" && node -e "
  require('@playwright/test').chromium.launch()
    .then((b) => b.close()).then(() => process.exit(0)).catch(() => process.exit(1))
" >/dev/null 2>&1); then
  # The probe takes the output directory positionally and writes
  # vr-01-xterm-probe.{md,json} itself, so its stdout goes to a log rather than
  # over the report it just wrote.
  run "xterm geometry probe (chromium)" vr-01-xterm-probe.log \
    node "$PROBE" "$OUT"
else
  skip "xterm geometry probe" "chromium cannot launch here"
fi

# --------------------------------------------------------------------------- #
# Traceability. This leg is what proves NFR-006 and the three new FR-TERM
# criteria are registered rather than merely written down.
# --------------------------------------------------------------------------- #
if command -v uv >/dev/null 2>&1; then
  run "traceability" traceability.txt make traceability
else
  skip "traceability" "uv is not installed; run 'make traceability' on a host that has it"
fi

# --------------------------------------------------------------------------- #
# The measuring leg. Same three ways in as plan/09's pack, because it is the
# same harness — theme.spec.ts joins session.spec.ts.
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
  skip "browser e2e: theme switch does not interrupt work" "$E2E_WHY"
  skip "browser e2e: FOUC on first paint" "part of the browser leg, which did not run here"
  skip "browser e2e: terminal rows in both themes" "part of the browser leg, which did not run here"
  skip "browser e2e: responsive, 2 themes x 3 breakpoints" "part of the browser leg, which did not run here"
  skip "acceptance screens (36 cells)" "needs the browser leg; see 06-verification-and-exit.md §4"
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

  THEME_CMD="cd '$ROOT/frontend' && exec npx playwright test$PLAYWRIGHT_ARGS tests/e2e/theme.spec.ts --reporter=list"
  # The layout leg runs too: this phase is the reason the terminal got shorter,
  # so the row-count assertion is a plan/28 result as much as a plan/09 one.
  LAYOUT_CMD="cd '$ROOT/frontend' && exec npx playwright test$PLAYWRIGHT_ARGS --grep layout --reporter=list"

  if [ "$E2E_MODE" = "existing" ]; then
    run "browser e2e: theme ($E2E_ENGINES)"  e2e-theme.txt  bash -c "$THEME_CMD"
    run "browser e2e: layout ($E2E_ENGINES)" e2e-layout.txt bash -c "$LAYOUT_CMD"
  else
    STACK_ENV=(
      env E2E_FULL_STACK=1
      CLIORA_DATABASE_URL="$STACK_DB"
      CLIORA_TEST_DATABASE_URL="$STACK_DB"
      E2E_ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}"
      E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}"
      CLIORA_ADMIN_PASSWORD="${CLIORA_ADMIN_PASSWORD:-e2e-admin-pw}"
    )
    run "browser e2e: theme, own stack ($E2E_ENGINES)" e2e-theme.txt \
      "${STACK_ENV[@]}" "$ROOT/scripts/e2e/run-stack.sh" bash -c "$THEME_CMD"
    run "browser e2e: layout, own stack ($E2E_ENGINES)" e2e-layout.txt \
      "${STACK_ENV[@]}" "$ROOT/scripts/e2e/run-stack.sh" bash -c "$LAYOUT_CMD"
  fi

  # A stack with no online node skips itself, and a skipped measurement must not
  # read as a passing one.
  for leg in e2e-theme e2e-layout; do
    if grep -qE '[0-9]+ skipped' "$OUT/$leg.txt" 2>/dev/null; then
      skip "some $leg cases" "the suite skipped what this stack could not offer; see $leg.txt"
    fi
  done

  # terminal-rows.txt: the probe measures a bare xterm in a box of the right
  # size; this measures the integrated workspace. They answer different
  # questions and the second is the one the release note quotes.
  if grep -q "rows" "$OUT/e2e-layout.txt" 2>/dev/null; then
    grep -iE "rows|paneHeight|screenHeight" "$OUT/e2e-layout.txt" >"$OUT/terminal-rows.txt" 2>/dev/null || true
  else
    skip "terminal-rows.txt" "the layout leg produced no row measurements"
  fi
fi

# --------------------------------------------------------------------------- #
# Legs no script can supply. Named rather than omitted: each one is a claim the
# exit report would otherwise be making without evidence.
# --------------------------------------------------------------------------- #
skip "ansi.png (VR-01 §5)" \
  "the 16-colour comparison must be judged on real Claude/Codex screens; its criterion is 'can a person still read it', which has no numeric answer"
skip "Midnight / Studio / Industrial screens" \
  "deliberate: their values pass the completeness and contrast tests but they are not in the switcher and have no layout variant (ADR 0027 §5). Recorded in the release note."

# overlap.txt: what the v2 line will have to replay. A report for a person to
# read, not a gate — merging v2 is always a human decision.
if git rev-parse --verify v2 >/dev/null 2>&1; then
  {
    echo "# Files this phase touched that the v2 line also touches"
    echo "# A report, not a gate: whether v2 replays this diff is a human call."
    echo
    git diff master...v2 --stat -- frontend/src 2>/dev/null || echo "(diff unavailable)"
  } >"$OUT/overlap.txt"
else
  skip "overlap.txt (v2 replay cost)" "the v2 branch is not present in this clone"
fi

# --------------------------------------------------------------------------- #
# summary.md
# --------------------------------------------------------------------------- #
{
  echo "# plan/28 evidence summary"
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
  if grep -q "browser e2e: theme" "$SKIPS" 2>/dev/null; then
    echo "> The measuring legs did not run here. The four gates above stop the palette"
    echo "> from being bypassed, and the contrast table is arithmetic that holds"
    echo "> regardless — but only the browser can show that a theme switch leaves the"
    echo "> session, the scrollback and the unsent input alone, and that the theme is"
    echo "> in force on the first paint. **Treat this pack as incomplete until CI runs"
    echo "> those legs.**"
    echo
  fi
  echo "Report: \`docs/vr-report.md\`. Ticket status: \`plan/28/07-implementation-status.md\`."
  echo "Security review: \`docs/security-review-p28.md\`."
} >"$OUT/summary.md"

echo
echo "evidence pack: $OUT"
echo "summary:       $OUT/summary.md"
[ "$FAILED" -eq 0 ] || exit 1
