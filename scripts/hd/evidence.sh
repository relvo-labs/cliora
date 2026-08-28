#!/usr/bin/env bash
# HD-12: everything, in one run (plan/27/00 §5).
#
#   . scripts/hd/env.sh && scripts/hd/evidence.sh
#
# **A missing artifact is a FAIL that names the command, never a SKIP.** `plan/26` §6 spent
# a page on why: a blank checkbox gets chased, and a blank checkbox with a reason beside it
# gets accepted. Three of that phase's journeys were recorded as "needs a toolchain this
# environment lacks" while the toolchain was on the PATH the whole time.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

FAILED=0
step() { printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s%s\n' "$1" "${2:+ — $2}"; FAILED=1; }
run()  { local l="$1"; shift; if "$@" >/tmp/hd-ev.log 2>&1; then pass "$l"; else fail "$l" "$(tail -2 /tmp/hd-ev.log | tr '\n' ' ')"; fi; }

# An artifact that has to exist. The message is the command that produces it, because
# "missing" without "run this" is a dead end for whoever reads the output.
artifact() {
  local path="$1" how="$2"
  if [ -s "$path" ]; then pass "$path"; else fail "$path" "produce it with: $how"; fi
}

echo "V2-E1 evidence — $(git rev-parse --short HEAD)"

step 1/9 "gates"
scripts/hd/gates.sh | sed 's/^/  /' || FAILED=1

step 2/9 "static checks"
run "ruff check"        uv run --project backend ruff check backend
run "ruff format"       uv run --project backend ruff format --check backend
run "mypy"              uv run --project backend mypy backend/app
run "frontend lint"     bash -c 'cd frontend && npm run lint'
run "frontend typecheck" bash -c 'cd frontend && npm run typecheck'
run "frontend format"   bash -c 'cd frontend && npm run format:check'
run "css tokens"        node scripts/frontend/check-tokens.mjs

step 3/9 "unit and database suites"
run "backend pytest"    bash -c 'cd backend && uv run --project . pytest tests -q'
run "frontend vitest"   bash -c 'cd frontend && npm run test:unit -- --run'

step 4/9 "traceability"
run "traceability"      make traceability-validate

step 5/9 "migration rehearsal (HD-08)"
artifact artifacts/hd/local/w6/rehearsal-compose.log "scripts/hd/rehearsal.sh"

step 6/9 "rollback drill (HD-09)"
artifact artifacts/hd/local/w6/rollback/drill.log "scripts/hd/rollback-drill.sh"

step 7/9 "accessibility and visual (HD-04 / HD-05)"
artifact artifacts/hd/local/w1/axe-after.json "cd frontend && E2E_HD_PROJECT=… npx playwright test --config tests/hd/playwright.config.ts a11y"
artifact artifacts/hd/local/w1/visual-negative.md "see plan/27/05 §7 — deliberately break a padding, confirm two screens go red"
BASELINES="$(find frontend/tests/hd/__screenshots__ -name '*.png' 2>/dev/null | wc -l)"
[ "$BASELINES" = "8" ] && pass "eight visual baselines" || fail "visual baselines" "$BASELINES of 8"

step 8/9 "scale (HD-10)"
artifact artifacts/hd/local/w5/explain/summary.tsv "scripts/hd/seed-large.py then scripts/hd/explain.sh"
artifact artifacts/hd/local/w5/README.md "written by hand from the measurements"

step 9/9 "journeys and sign-offs"
# **The three that are people, reported as open rather than omitted.** A release script
# that only printed machine results would let a reader conclude the release is ready.
for doc in docs/security-review-v2e1.md docs/a11y-audit-v2e1.md; do
  if grep -q "NOT SIGNED\|not performed" "$doc" 2>/dev/null; then
    fail "$doc" "unsigned or with checks not performed — this is a person's action"
  else
    pass "$doc signed"
  fi
done
artifact artifacts/hd/local/journeys/summary.json "the eighteen journeys need a stack with a real daemon — scripts/e2e/run-stack.sh"

echo
if [ "$FAILED" = "0" ]; then
  echo "=== every check green ==="
else
  echo "=== NOT READY — the failures above are the list, and some of them are people ==="
fi
exit "$FAILED"
