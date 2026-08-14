#!/usr/bin/env bash
# DV-11: the machine assertions for V2.4 (plan/21/08-…md §3).
#
# Thirteen gates. Each guards a property whose violation is **silent** — the code runs,
# the tests pass, and what changed is a promise nobody re-reads. Nine are new here; four
# are the V2.3 gates re-pointed at this phase's baseline, because "only additions" and
# "the touch list held" are the same questions asked of a different starting point.
#
#   scripts/dv/gates.sh [baseline-dir]     # default artifacts/dv/local/baseline
#
# Needs a migrated PostgreSQL at CLIORA_DATABASE_URL for the schema gates.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/dv/local/baseline}"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s%s\n' "$1" "${2:+ — $2}"; FAILED=1; }

check() {
  local name="$1"; shift
  if output="$("$@" 2>&1)"; then
    pass "$name"
  else
    fail "$name" "$(printf '%s' "$output" | tail -3 | tr '\n' ' ')"
  fi
}

# grep-based gates: a match is a violation.
absent() {
  local name="$1" description="$2"; shift 2
  if output="$(grep -rn "$@" 2>/dev/null)"; then
    fail "$name" "$description: $(printf '%s' "$output" | head -2 | tr '\n' ' ')"
  else
    pass "$name"
  fi
}

echo "V2.4 gates (baseline: $BASELINE)"

# --- inherited from V2.3, re-pointed at this phase's baseline ---------------
check "GATE-DV-SCHEMA-ADDITIVE" scripts/pj/gate-schema-additive.sh "$BASELINE/schema.txt"
check "GATE-DV-MIGRATION-ROUNDTRIP" scripts/ar/gate-migration-roundtrip.sh \
  "$BASELINE/schema.txt" 0034_seed_secret_action
check "GATE-DV-CONTRACT-ADDITIVE" \
  uv run --project backend python scripts/tk/contract_snapshot.py --diff \
  "$BASELINE/contract-fixtures.txt"

echo "  ---- touch list ----"
# The phase's off-limits set (plan/21/00-…md D19). V2.3's nine, plus one addition whose
# form is the point: `push.go` **is** edited this phase (`existing_pr`'s branch source),
# so the file is not on the list — the five hard constraints inside it are, checked as a
# separate assertion below. A gate that only asks "did the file change" would have had
# to be switched off.
if [ ! -f "$BASELINE/COMMIT" ]; then
  fail "GATE-DV-TOUCH-LIST" "no COMMIT in $BASELINE"
else
  base_commit="$(head -1 "$BASELINE/COMMIT")"
  forbidden=(
    'backend/app/services/terminal_relay.py'
    'backend/app/services/terminal_queue.py'
    'backend/app/services/tunnels.py'
    'backend/app/services/node_update.py'
    'backend/app/services/files.py'
    'backend/app/services/favorites.py'
    'backend/app/security/secret_box.py'
    'backend/app/security/secret_envelope.py'
    'backend/app/api/ws/terminal.py'
    'daemon/internal/runtime/runtime.go'
    'daemon/internal/runtime/launch.go'
  )
  touched=""
  for path in "${forbidden[@]}"; do
    if ! git diff --quiet "$base_commit" -- "$path" 2>/dev/null; then
      touched="$touched $path"
    fi
  done
  if [ -n "$touched" ]; then
    fail "GATE-DV-TOUCH-LIST" "off-limits files changed:$touched"
  else
    pass "GATE-DV-TOUCH-LIST"
  fi
fi

# The five hard push constraints, as text rather than as a file hash. `push.go` is
# edited this phase; the constraints in it are not.
echo "  ---- red line 5 ----"
if grep -q 'ErrBranchNotAllowed' daemon/internal/gitfetch/push.go &&
   grep -q 'only a cliora/ branch may be pushed' daemon/internal/gitfetch/push.go &&
   grep -q 'args := \[\]string{"push", "--", opts.RemoteURL' daemon/internal/gitfetch/push.go; then
  pass "GATE-DV-PUSH-CONSTRAINTS"
else
  fail "GATE-DV-PUSH-CONSTRAINTS" "the five hard constraints changed shape"
fi

# **The absence of the words is the assertion.** A check can be bypassed by a second
# call site; a verb table that does not contain the word cannot.
absent "GATE-DV-PROVIDER-VERBS" "the provider adapter grew an action red line 5 forbids" \
  -iE '(def |"|/)(merge|approve|request_changes|close|delete|release|tag)\b' \
  backend/app/services/providers.py

absent "GATE-DV-NO-HTTP-IN-LOOP" "the node receive loop reached a provider" \
  -E '(httpx|adapter_for|create_pull_request)' backend/app/services/runs.py

absent "GATE-DV-SINGLE-DONE-PATH" "a run advanced a card into done" \
  -E '\.stage\s*=\s*["'"'"']done["'"'"']' backend/app/services/runs.py

# Production code only. A test that builds a scenario with `sh -c` is the test
# exercising the feature — the assertion is about what the daemon does, not about what a
# fixture is allowed to look like.
absent "GATE-DV-NO-SHELL" "a verification command was routed through a shell" \
  -E '"(sh|bash)",\s*"-c"' --include='*.go' --exclude='*_test.go' \
  daemon/internal/runner daemon/internal/connection

# `machine_verified` may be *written* from one place. The constant's definition and its
# use as a comparison are fine; a second call to the writer is not.
writers=$(grep -rln 'record_machine_verified' backend/app --include='*.py' |
  grep -v 'services/evidence.py' | wc -l)
if [ "$writers" -le 1 ]; then
  pass "GATE-DV-MACHINE-VERIFIED-ONE-WRITER"
else
  fail "GATE-DV-MACHINE-VERIFIED-ONE-WRITER" "$writers modules call the writer"
fi

absent "GATE-DV-APPEND-ONLY" "an update against an append-only table" \
  -nE 'update\((ExecutionPlan|VerificationReport|EvidenceItem)\)' \
  --include='*.py' backend/app

absent "GATE-DV-METRICS-READ-ONLY" "a service imported the metrics aggregate" \
  -E 'from app\.services\.dashboard import' \
  backend/app/services/runs.py backend/app/services/tasks.py

# Every `delivery` value must have a branch in four places. A missing one is not a
# missing feature but a silent one: the value falls through to the permissive default.
echo "  ---- delivery coverage ----"
missing=""
for value in none artifact branch pull_request existing_pr; do
  for where in \
    backend/app/services/runs.py \
    backend/app/services/done_gate.py \
    frontend/src/components/ui/labels.ts; do
    grep -q "$value" "$where" || missing="$missing $value@$(basename "$where")"
  done
done
if [ -n "$missing" ]; then
  fail "GATE-DV-DELIVERY-COVERAGE" "unhandled:$missing"
else
  pass "GATE-DV-DELIVERY-COVERAGE"
fi

# A promise pointing at this phase or later, left in code somebody will read as a plan.
absent "GATE-DV-NO-STALE-PROMISE" "an expired promise about V2.4" \
  -nE 'V2\.4 (會|將|adds|will)|takes effect in a later version' \
  --include='*.py' --include='*.go' --include='*.ts' --include='*.vue' --include='*.json' \
  backend/app daemon/internal contracts frontend/src

echo
if [ "$FAILED" = "0" ]; then
  echo "all gates passed"
else
  echo "one or more gates failed"
fi
exit "$FAILED"
