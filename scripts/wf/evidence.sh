#!/usr/bin/env bash
# Assemble the plan/13 exit-gate evidence pack (workspace write posture + text
# classification, ADR 0024).
#
#   scripts/wf/evidence.sh [output-dir]        # default artifacts/wf/local
#
# Same rule as the earlier packs: every gate is *executed* and its exit status
# recorded in commands.txt. A leg this environment cannot run goes in
# skipped.txt, never silently omitted — a pack that dropped a gate reads exactly
# like a pack that passed it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PATH="$PATH:/usr/local/go/bin"

OUT="${1:-$ROOT/artifacts/wf/local}"
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
  echo "# plan/13 evidence pack (WF-01 … WF-11)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
  echo "git_commit: $(git rev-parse HEAD 2>/dev/null || echo 'not a git repository')"
  echo "git_dirty: $(git status --porcelain 2>/dev/null | wc -l) file(s) modified"
  echo "agentd_version: $(cat daemon/VERSION)"
  echo "contract_version: $(grep -m1 '^## ' contracts/CHANGELOG.md)"
  echo "python: $(uv run --project backend python -V 2>/dev/null || echo unavailable)"
  echo "go: $(go version 2>/dev/null || echo unavailable)"
  echo "node: $(node -v 2>/dev/null || echo unavailable)"
  echo "claude: $(claude --version 2>/dev/null || echo 'not installed')"
  echo "codex: $(codex --version 2>/dev/null || echo 'not installed')"
} >"$OUT/versions.txt"

# --------------------------------------------------------------------------- #
# 1. The boundary that makes one write path safe: the sender cannot name a file.
# --------------------------------------------------------------------------- #
run "gate:no-naming-channel" naming-channel.txt scripts/wf/check-no-naming-channel.sh
if command -v uv >/dev/null 2>&1; then
  run "scope-guards" scope-guards.txt \
    uv run --project backend pytest backend/tests/test_scope_guards.py -q
else
  skip "scope-guards" "uv not available"
fi

# 2. Contract v1.8.0 across all three consumers, including the five fixtures
#    that pin the absence of a naming field.
if command -v uv >/dev/null 2>&1 && command -v go >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  run "contract:three-consumers" contract.txt make contract
else
  skip "contract:three-consumers" "needs uv, go and npm"
fi

# 3. Classification: the corpus, the regressions, and the 5 ms budget. The
#    budget test is skipped under -race (the detector costs ~15x), so it runs
#    here without it — which is why this is a separate leg from daemon:race.
if command -v go >/dev/null 2>&1; then
  run "classify:corpus-and-budget" classify-corpus.txt sh -c \
    'cd daemon && go test ./internal/files/ -run "TestClassify|TestDetectBinary" -count 1 -v'
  run "classify:whole-tree" classify-scan.txt scripts/wf/classify-scan.sh
  run "daemon:unit" daemon-unit.txt sh -c 'cd daemon && go test ./... -count 1'
  run "daemon:race" daemon-race.txt sh -c 'cd daemon && go test -race ./... -count 1'
  # The write path itself: escapes, hijacked .cliora, quota, pruning, O_EXCL.
  run "daemon:write-path" daemon-write-path.txt sh -c \
    'cd daemon && go test ./internal/files/ ./internal/workspace/ -run "Upload|SaveImage|Prune|CreateExclusive|StaysInside" -count 1 -v'
else
  skip "daemon:*" "go not available"
fi

# 4. Central: RBAC, the relayed frame's shape, the size cap, the audit entry.
if [ -n "$DB_URL" ]; then
  run "central:db" central-db.txt sh -c \
    "cd backend && CLIORA_DATABASE_URL=$DB_URL CLIORA_TEST_DATABASE_URL=$DB_URL uv run --project . pytest tests/db -q"
  run "central:upload-api" central-upload.txt sh -c \
    "cd backend && CLIORA_DATABASE_URL=$DB_URL CLIORA_TEST_DATABASE_URL=$DB_URL uv run --project . pytest tests/db/test_files_upload_api.py -q -v"
else
  skip "central:db" "CLIORA_TEST_DATABASE_URL not set (no PostgreSQL)"
  skip "central:upload-api" "CLIORA_TEST_DATABASE_URL not set (no PostgreSQL)"
fi
if command -v uv >/dev/null 2>&1; then
  run "central:unit" central-unit.txt \
    uv run --project backend pytest backend/tests -q --ignore=backend/tests/db
else
  skip "central:unit" "uv not available"
fi

# 5. Console: the three entry points, typeText's writer gate, the denial wording.
if command -v npm >/dev/null 2>&1; then
  run "console:unit" console-unit.txt npm --prefix frontend run test:unit
else
  skip "console:unit" "npm not available"
fi

# 6. Requirements: the new criteria are registered and the withdrawal recorded.
run "traceability:static" traceability.txt scripts/trace validate --level static

# 7. The end-to-end leg needs a node with claude/codex and a running stack. It
#    is recorded rather than assumed: WF-01 measured the CLI half by hand
#    (plan/13/08-measurements.md §4), and the browser half needs Playwright's
#    system libraries.
skip "e2e:paste-to-cli" "needs a running stack with an online node (see plan/13/06 §1.5)"
skip "e2e:webp" "no WebP encoder on this host; four formats measured as three (08-measurements.md §4.1)"

{
  echo
  echo "failed_gates: $FAILED"
  echo "skipped_gates: $(wc -l <"$SKIPS")"
} >>"$COMMANDS"

echo
cat "$COMMANDS"
echo
echo "skipped:"; cat "$SKIPS"
exit $((FAILED > 0))
