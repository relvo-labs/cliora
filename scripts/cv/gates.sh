#!/usr/bin/env bash
# CV-12: the machine assertions for `v2.0.0-alpha.2` (plan/23/08-…md §3).
#
# Seven gates. Each guards a property whose violation is **silent** — the code runs,
# the tests pass, and what changed is a promise nobody re-reads. Four are new here and
# live in one Python process; three are shell-shaped and sit below.
#
#   scripts/cv/gates.sh [baseline-dir]     # default artifacts/cv/local/baseline
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/cv/local/baseline}"
WAIVERS="${CV_WAIVERS:-scripts/cv/product-drift-waivers.txt}"
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

echo "V2-C1 gates (baseline: $BASELINE)"

# --- the four AST invariants ------------------------------------------------
check "GATE-CV-{PROJECTION-ONE-WRITER,CONTINUATION-REFUSALS,APPEND-ONLY,NO-CLIENT-WAITING-DERIVATION}" \
  uv run --project backend python scripts/cv/gate_conversation_invariants.py

# --- GATE-CV-CONTRACT-FROZEN ------------------------------------------------
#
# **Not one byte on the wire.** The phase's central claim is that no node has to be
# upgraded, and this is what stops that quietly ceasing to be true.
#
# Scoped to `contracts/v1/` — the schemas and fixtures a daemon decodes against — and
# **not** `CHANGELOG.md`, because `CV-02` adds an entry there stating that this release
# changes nothing on the wire. A gate that the explanation breaks is a gate that gets
# discharged by deleting the explanation.
if [ -f "$BASELINE/contract-v1.sha256" ]; then
  current="$(find contracts/v1 -type f -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  if [ "$current" = "$(cat "$BASELINE/contract-v1.sha256")" ]; then
    pass "GATE-CV-CONTRACT-FROZEN"
  else
    fail "GATE-CV-CONTRACT-FROZEN" "contracts/v1 differs from the baseline"
  fi
else
  fail "GATE-CV-CONTRACT-FROZEN" "no contract-v1.sha256 in $BASELINE (run capture-baseline.sh)"
fi

# --- GATE-CV-TOUCH-LIST -----------------------------------------------------
#
# The daemon's node half has a **zero-byte diff** this phase: a continuation is an
# ordinary queued run, so nothing about executing one changed. If that stops being
# true, the phase's risk assessment ("Central only") stops being true with it.
FORBIDDEN=(
  daemon/internal/protocol
  daemon/internal/runner
  daemon/internal/connection/run_handlers.go
  daemon/internal/workspace
  daemon/internal/gitfetch
  backend/app/services/secrets.py
  backend/app/services/rbac.py
  backend/app/services/deliveries.py
)
if [ -f "$BASELINE/COMMIT" ]; then
  base_commit="$(cat "$BASELINE/COMMIT")"
  touched=""
  for path in "${FORBIDDEN[@]}"; do
    # Two questions, because `git diff` answers only the first one. A *tracked* file
    # that changed shows up in the diff; a **new file that has never been added does
    # not**, and the gate would pass while a forbidden directory grew. That is not
    # hypothetical — a fix for the run credential arrived with a new test file under
    # `internal/runner/`, and this gate stayed green until the file was staged.
    if ! git diff --quiet "$base_commit" -- "$path" 2>/dev/null \
      || [ -n "$(git status --porcelain --untracked-files=all -- "$path" 2>/dev/null)" ]; then
      touched="$touched $path"
    fi
  done
  # `secrets.py` is the one exception, and it is a narrow one: V2-C1 adds `redact()`
  # there **because** `GATE-SC-SINGLE-DECRYPT` says exactly one module may reach
  # plaintext, and putting the helper anywhere else would raise that number to two
  # (ADR 0037 §3). Listed here so the exception is visible rather than silent.
  touched="${touched// backend\/app\/services\/secrets.py/}"
  # The closeout phase's named exceptions (`plan/24/01` D68, `plan/24/08` §1.1). Each
  # line is a path, a ticket and a sentence, and the gate **prints every one it
  # honours**: a journey that exposed a defect in a frozen file is a fact worth
  # carrying, and an exception nobody can see is how a freeze quietly stops being one.
  if [ -f "$WAIVERS" ]; then
    while read -r path ticket reason; do
      case "$path" in ''|'#'*) continue ;; esac
      if [ -n "$touched" ] && [ "$touched" != "${touched// $path/}" ]; then
        touched="${touched// $path/}"
        printf '        waived: %s (%s) %s\n' "$path" "$ticket" "$reason"
      fi
    done <"$WAIVERS"
  fi
  if [ -z "$touched" ]; then
    pass "GATE-CV-TOUCH-LIST"
  else
    fail "GATE-CV-TOUCH-LIST" "changed:$touched"
  fi
else
  fail "GATE-CV-TOUCH-LIST" "no COMMIT in $BASELINE"
fi

# --- GATE-CV-NO-LOG-IN-THREAD -----------------------------------------------
#
# A log is a diagnostic with a retention period; a message is product data that never
# expires. Mixing them in one view makes "the conversation survived, the log did not"
# impossible to explain — and the exit criterion that deletes every log and re-reads
# the thread would start failing for a reason nobody could see from the UI.
if grep -rn "listRunLogs\|/logs\|run_log" frontend/src/components/project/conversation/ 2>/dev/null; then
  fail "GATE-CV-NO-LOG-IN-THREAD" "the conversation components reach for run logs"
else
  pass "GATE-CV-NO-LOG-IN-THREAD"
fi

# --- GATE-CV-MIGRATION-ROUNDTRIP --------------------------------------------
#
# Re-uses the AR script rather than forking it — the question ("does downgrading
# restore the baseline exactly") is the same question, and a second copy would
# disagree with this one the first time either is fixed. Only the target revision
# differs.
#
# Skipped, loudly, without a database: a gate that silently passes when it could not
# run is worse than one that says it did not.
if [ -f "$BASELINE/schema.txt" ] && [ -n "${CLIORA_DATABASE_URL:-}" ]; then
  check "GATE-CV-MIGRATION-ROUNDTRIP" \
    scripts/ar/gate-migration-roundtrip.sh "$BASELINE/schema.txt" 0039_requirements_agent_driven
else
  fail "GATE-CV-MIGRATION-ROUNDTRIP" "needs $BASELINE/schema.txt and CLIORA_DATABASE_URL"
fi

# --- re-pointed from earlier phases -----------------------------------------
#
# Both are about paths V2-C1 extended rather than replaced, so they are re-run against
# this baseline rather than restated.
check "GATE-RQ-CONTEXT-DISPATCH (re-run)" \
  uv run --project backend python scripts/rq/gate_context_dispatch.py
check "GATE-SC-SINGLE-DECRYPT (re-run)" \
  uv run --project backend python scripts/sc/gate_secret_invariants.py

echo
if [ "$FAILED" -eq 0 ]; then
  echo "all V2-C1 gates passed"
else
  echo "V2-C1 gates FAILED"
fi
exit "$FAILED"
