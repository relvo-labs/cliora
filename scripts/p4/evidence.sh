#!/usr/bin/env bash
# Assemble the P4 exit-gate evidence pack (plan/05/07 §3).
#
#   scripts/p4/evidence.sh [output-dir]        # default artifacts/p4/local
#
# Everything here is *generated from a real run*. Nothing is asserted in prose: each gate
# is executed and its exit status recorded in commands.txt, so a regression shows up as a
# non-zero status rather than as stale text somebody forgot to update. That is the whole
# design rule, carried over from the P1–P3 packs.
#
# Legs that need something unavailable (PostgreSQL, tmux, docker, browsers) are **skipped
# with a note**, never silently omitted. A pack that quietly dropped a gate would read as a
# pass — the one failure mode an evidence pack must not have.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/p4/local}"
mkdir -p "$OUT"
COMMANDS="$OUT/commands.txt"
SKIPS="$OUT/skipped.txt"
: >"$COMMANDS"
: >"$SKIPS"

DB_URL="${CLIORA_TEST_DATABASE_URL:-}"

run() {
  local label="$1" outfile="$2"
  shift 2
  local target="/dev/null"
  [ "$outfile" != "-" ] && target="$OUT/$outfile"
  echo "==> $label"
  if [ "$target" = "/dev/null" ]; then
    "$@" >/dev/null 2>&1
  else
    "$@" >"$target" 2>&1
  fi
  local status=$?
  printf '%-40s exit=%-3s %s\n' "$label" "$status" "$*" >>"$COMMANDS"
  return $status
}

skip() {
  printf '%-40s %s\n' "$1" "$2" >>"$SKIPS"
  echo "-- skipped: $1 ($2)"
}

# --------------------------------------------------------------------------- #
# versions.txt — a capacity or latency number without the machine is not comparable
# --------------------------------------------------------------------------- #
{
  echo "# P4 evidence pack"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "cpus: $(nproc 2>/dev/null || echo unknown)"
  echo "ram_mib: $(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo unknown)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
  echo "go: $(go version 2>/dev/null || echo unavailable)"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
  echo "postgres: $(docker exec cliora-pg postgres --version 2>/dev/null || echo unavailable)"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# Static gates
# --------------------------------------------------------------------------- #
run "backend format"      -                  uv run --project backend ruff format --check backend
run "backend lint"        -                  uv run --project backend ruff check backend
run "backend typecheck"   backend-mypy.txt   uv run --project backend mypy backend/app
run "frontend lint"       -                  npm run --prefix frontend lint
run "frontend typecheck"  frontend-tsc.txt   npm run --prefix frontend typecheck
run "frontend format"     -                  npm run --prefix frontend format:check

if command -v go >/dev/null 2>&1; then
  run "daemon vet"        daemon-vet.txt     bash -c 'cd daemon && go vet ./...'
  run "daemon test -race" daemon-test.txt    bash -c 'cd daemon && go test -race ./...'
  run "daemon build"      -                  bash -c 'cd daemon && go build ./...'
else
  skip "daemon gates" "go not on PATH (try /usr/local/go/bin)"
fi

# --------------------------------------------------------------------------- #
# Test suites
# --------------------------------------------------------------------------- #
run "contract fixtures"   contract.txt       uv run --project backend pytest backend/tests/contract -q
run "frontend unit"       frontend-unit.txt  bash -c "cd frontend && npx vitest run --exclude 'tests/e2e/**' --reporter=dot"

if [ -n "$DB_URL" ]; then
  # CLIORA_DATABASE_URL matters as well as the test URL: the denial-audit middleware
  # writes its row on its own session through the process-wide engine, so with only the
  # test URL set those tests fail for an environmental reason.
  export CLIORA_DATABASE_URL="${CLIORA_DATABASE_URL:-$DB_URL}"
  run "backend unit + DB"     backend-tests.txt  uv run --project backend pytest backend/tests -q
  run "migrations up/down/up" migrations.txt     bash -c '
      cd backend
      uv run --project . alembic upgrade head &&
      uv run --project . alembic downgrade 0007_seed_file_browse &&
      uv run --project . alembic upgrade head'
  run "permission matrix"     permission-matrix.txt \
      uv run --project backend pytest backend/tests/db/test_permission_matrix.py backend/tests/test_authz.py -q
else
  skip "backend DB legs" "CLIORA_TEST_DATABASE_URL not set"
  run "backend unit (hermetic only)" backend-tests.txt uv run --project backend pytest backend/tests -q
fi

# --------------------------------------------------------------------------- #
# Generated documents must match their sources
# --------------------------------------------------------------------------- #
# Snapshot, regenerate, compare. Deliberately not `git diff`: this check asks "does
# regenerating change the file", which is a different question from "is the file modified
# relative to the index" — and it has to work in a working tree that is not a git
# repository, which is where it first failed.
generated_docs_current() {
  local status=0 tmp
  tmp=$(mktemp -d)
  for doc in docs/error-catalog.md docs/permission-matrix.md; do
    cp "$doc" "$tmp/$(basename "$doc")"
  done
  uv run --project backend python scripts/p4/render_error_catalog.py >/dev/null || status=1
  uv run --project backend python scripts/p4/render_permission_matrix.py >/dev/null || status=1
  for doc in docs/error-catalog.md docs/permission-matrix.md; do
    if ! diff -u "$tmp/$(basename "$doc")" "$doc"; then
      echo "!! $doc is out of date: regenerate it and commit the result"
      status=1
    fi
  done
  rm -rf "$tmp"
  return $status
}
run "generated docs are current"  generated-docs.txt generated_docs_current
run "alerts name real runbooks"   alerts.txt \
    uv run --project backend pytest backend/tests/test_alerts_and_runbooks.py -q

# --------------------------------------------------------------------------- #
# Capacity and drills — need docker for their throwaway databases
# --------------------------------------------------------------------------- #
if docker exec cliora-pg true 2>/dev/null; then
  run "capacity (smoke)" capacity-run.txt \
      uv run --project backend python scripts/p4/load/capacity.py \
        --profile smoke --out "$OUT/capacity.json"
  run "backup / restore drill" backup-restore-run.txt \
      scripts/p4/backup-restore-drill.sh "$OUT"
  run "alert drills" drills-run.txt scripts/p4/drills/run-all.sh "$OUT"
  # Slow (~3 min, 70 s of it one idle WebSocket) but it is the only gate that executes the
  # edge configuration rather than reading it. Needs a built console; builds one if absent.
  run "edge verification" edge-run.txt scripts/p4/verify-edge.sh "$OUT"
else
  skip "capacity, backup/restore, drills" "no reachable 'cliora-pg' container"
fi

# --------------------------------------------------------------------------- #
# Browser E2E — needs the full stack plus browsers; usually the CI job's output
# --------------------------------------------------------------------------- #
if [ "${P4_RUN_E2E:-}" = "1" ]; then
  run "browser e2e" e2e.txt scripts/e2e/run-stack.sh
else
  skip "browser e2e" "set P4_RUN_E2E=1; needs the full stack and installed browsers"
fi

# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
# Match on the exit= field specifically. Counting "every line whose second field is not
# exit=0" also counted the continuation lines of multi-line commands, so a run with two
# real failures reported twenty-three.
FAILED=$(grep -oE 'exit=[0-9]+' "$COMMANDS" | grep -vc 'exit=0$' || true)
{
  echo "# P4 evidence summary"
  echo
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## Gates"
  echo
  echo '```'
  cat "$COMMANDS"
  echo '```'
  echo
  if [ -s "$SKIPS" ]; then
    echo "## Skipped"
    echo
    echo "Listed, not omitted: read these before treating the pack as complete."
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
  echo "Go/No-Go decision and the twenty PRD §19 acceptance conditions: \`docs/p4-report.md\`."
} >"$OUT/summary.md"

echo
echo "evidence pack: $OUT"
echo "summary:       $OUT/summary.md"
scripts/trace emit-evidence \
  --gate-id GATE-OPERATIONS \
  --commands "$COMMANDS" \
  --skips "$SKIPS" \
  --run-id "${GITHUB_RUN_ID:-p4-local}" \
  --profile "${GITHUB_REF_NAME:-local}" \
  --out "$OUT/gate-results.json"
[ "$FAILED" -eq 0 ] || exit 1
