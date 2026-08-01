#!/usr/bin/env bash
# Assemble the plan/11 exit-gate evidence pack (port forwarding through a third-party provider).
#
#   scripts/pg/evidence.sh [output-dir]        # default artifacts/pg/local
#
# Same rule as the P1–P4 and plan/08 packs: every gate is *executed* and its exit status
# recorded in commands.txt. Nothing is asserted in prose. A leg this environment cannot run
# (no PostgreSQL, no Go, no browser, no provider account) goes in skipped.txt — never silently
# omitted, because a pack that dropped a gate reads exactly like a pack that passed it.
#
# One leg is deliberately not skippable-by-default and not runnable here: the real provider
# verification needs an account, so it is release-triggered (GATE-TUNNEL-PROVIDER) and its
# absence is recorded every time rather than assumed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/pg/local}"
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
  echo "# plan/11 evidence pack (PG-01 … PG-14)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
  echo "go: $(go version 2>/dev/null || echo unavailable)"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
  echo "ssh: $(ssh -V 2>&1 || echo unavailable)"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# Static, unit and contract
# --------------------------------------------------------------------------- #
run "backend format"        -                  uv run --project backend ruff format --check backend
run "backend lint"          -                  uv run --project backend ruff check backend
run "backend typecheck"     backend-mypy.txt   uv run --project backend mypy backend/app
run "backend unit"          backend-unit.txt   uv run --project backend python -m pytest backend/tests -q --ignore=backend/tests/db
run "frontend lint"         -                  npm run --prefix frontend lint
run "frontend typecheck"    frontend-tsc.txt   npm run --prefix frontend typecheck
run "frontend unit"         frontend-unit.txt  npm run --prefix frontend test:unit -- --run
run "contract (3 languages)" contract.txt      make contract

if command -v go >/dev/null 2>&1; then
  run "daemon test -race"   daemon-test.txt    bash -c 'cd daemon && go test -race ./...'
  # The supervisor's integration leg needs no network and no account: the provider is a fake
  # binary. That is the whole reason it exists (03 §2.6).
  run "daemon integration"  daemon-integration.txt bash -c \
    'cd daemon && go test -tags integration -race ./internal/tunnel ./internal/connection'
else
  skip "daemon test -race" "go toolchain unavailable"
  skip "daemon integration" "go toolchain unavailable"
fi

# --------------------------------------------------------------------------- #
# The two gates that are specific to this phase
# --------------------------------------------------------------------------- #
run "host key gate"         host-key-gate.txt  uv run --project backend python -m pytest \
  backend/tests/test_security.py::test_no_source_disables_provider_host_key_verification -q
run "no-proxy scope guard"  scope-013.txt      uv run --project backend python -m pytest \
  backend/tests/test_scope_guards.py::test_scope_013_central_does_not_proxy_to_a_node_http_service -q
run "credential leak scan"  token-leak.txt     scripts/pg/check-no-token-leak.sh

# --------------------------------------------------------------------------- #
# Database-backed: the three-layer policy, the limits and the credential's custody
# --------------------------------------------------------------------------- #
if [ -n "$DB_URL" ]; then
  run "migrations up/down/up" migrations.txt bash -c '
    cd backend
    uv run --project . alembic upgrade head &&
    uv run --project . alembic downgrade 0013_shell_session_parent &&
    uv run --project . alembic upgrade head'
  run "backend db suite"    backend-db.txt     make test-db
else
  skip "migrations up/down/up" "CLIORA_TEST_DATABASE_URL unset"
  skip "backend db suite" "CLIORA_TEST_DATABASE_URL unset"
fi

# --------------------------------------------------------------------------- #
# Traceability: the 23 new criteria must be verifiable and SCOPE-013 guarded
# --------------------------------------------------------------------------- #
run "traceability"          traceability.txt   make traceability

# --------------------------------------------------------------------------- #
# The two states everybody forgets to test: the feature switched off, and a
# deployment with no encryption key. Both must leave the whole suite green
# (exit condition 10) — every other run here has the key set by conftest.
# --------------------------------------------------------------------------- #
run "unit with no encryption key" no-key.txt env -u CLIORA_SECRET_ENCRYPTION_KEY \
  uv run --project backend python -m pytest backend/tests -q --ignore=backend/tests/db

# --------------------------------------------------------------------------- #
# The stack with a stand-in provider (plan/11 §3.2). Two legs, because they fail
# for different reasons and must not share a colour:
#
#   * the platform path (Central + protocol + supervisor + fake provider) needs
#     only a spare database, so it runs wherever the DB gates run;
#   * the browser path additionally needs Playwright's system libraries, which
#     only root can install — an environment gap, not a red gate.
# --------------------------------------------------------------------------- #
STACK_DB="${E2E_STACK_DATABASE_URL:-}"
if [ -z "$STACK_DB" ]; then
  skip "tunnel stack check" "set E2E_STACK_DATABASE_URL to a spare database (needs go + tmux)"
  skip "browser e2e: tunnel.spec.ts" "no stack database; see the line above"
elif ! command -v tmux >/dev/null 2>&1 || ! command -v go >/dev/null 2>&1; then
  skip "tunnel stack check" "E2E_STACK_DATABASE_URL is set but go and/or tmux is missing"
  skip "browser e2e: tunnel.spec.ts" "same"
else
  STACK_ENV=(
    env -u CLIORA_TEST_DATABASE_URL
    CLIORA_DATABASE_URL="$STACK_DB"
    E2E_ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}"
    E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}"
    CLIORA_ADMIN_PASSWORD="${CLIORA_ADMIN_PASSWORD:-e2e-admin-pw}"
  )
  run "tunnel stack check (stand-in provider)" tunnel-stack.txt \
    "${STACK_ENV[@]}" "$ROOT/scripts/e2e/run-stack.sh" "$ROOT/scripts/pg/tunnel-stack-check.sh"

  # Probe the browser before standing the stack up again for it: an unavailable browser is an
  # environment gap and belongs in skipped.txt, not in a red gate.
  if (cd "$ROOT/frontend" && node -e "
    require('@playwright/test').chromium.launch()
      .then((b) => b.close()).then(() => process.exit(0)).catch(() => process.exit(1))
  " >/dev/null 2>&1); then
    run "browser e2e: tunnel.spec.ts (chromium)" e2e-tunnel.txt \
      "${STACK_ENV[@]}" E2E_FULL_STACK=1 "$ROOT/scripts/e2e/run-stack.sh" \
      bash -c "cd '$ROOT/frontend' && exec npx playwright test tunnel.spec.ts --project=chromium --reporter=list"
  else
    skip "browser e2e: tunnel.spec.ts" "no browser can launch here (Playwright's system libraries need root); CI only"
  fi
fi

# --------------------------------------------------------------------------- #
# Real provider. Needs an account; release-triggered (GATE-TUNNEL-PROVIDER).
# --------------------------------------------------------------------------- #
if [ "${PG_VERIFY_PROVIDER:-}" = "1" ]; then
  run "real provider verification" provider-verify.txt scripts/tunnel/verify-provider.sh
else
  skip "real provider verification" "set PG_VERIFY_PROVIDER=1 with a provider account; release-triggered"
fi

# --------------------------------------------------------------------------- #
# summary.md
# --------------------------------------------------------------------------- #
{
  echo "# plan/11 evidence summary"
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
  echo "Security review: \`docs/security-review-p11.md\`. Ticket status: \`plan/11/07-implementation-status.md\`."
} >"$OUT/summary.md"

echo
echo "evidence pack: $OUT"
echo "summary:       $OUT/summary.md"
[ "$FAILED" -eq 0 ] || exit 1
