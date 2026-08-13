#!/usr/bin/env bash
# SC-09: the machine assertions for V2.3 (plan/20/07-…md §3).
#
# Ten gates. Each guards a property whose violation is **silent** — the code runs, the
# tests pass, and what changed is a promise nobody re-reads. Six are new here; four are
# the V2.2 gates re-pointed at this phase's baseline, because "only additions" and "the
# touch list held" are the same questions asked of a different starting point.
#
#   scripts/sc/gates.sh [baseline-dir]     # default artifacts/sc/local/baseline
#
# Needs a migrated PostgreSQL at CLIORA_DATABASE_URL for the schema gates.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/sc/local/baseline}"
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

echo "V2.3 gates (baseline: $BASELINE)"

# --- inherited from V2.2, re-pointed at this phase's baseline ---------------
# The questions are the same; only the "before" moved.
check "GATE-SC-SCHEMA-ADDITIVE" scripts/pj/gate-schema-additive.sh "$BASELINE/schema.txt"
# Down to the revision *this* baseline was taken at, not V2.2's.
check "GATE-SC-MIGRATION-ROUNDTRIP" scripts/ar/gate-migration-roundtrip.sh \
  "$BASELINE/schema.txt" 0032_runner_pressure
check "GATE-SC-CONTRACT-ADDITIVE" \
  uv run --project backend python scripts/tk/contract_snapshot.py --diff \
  "$BASELINE/contract-fixtures.txt"

# --- GATE-SC-TOUCH-LIST -----------------------------------------------------
# The phase's off-limits set (plan/20/00-…md D19). `secret_box.py` joins it: sharing that
# module would tie two rotations together and turn something that passed a security
# review for one purpose into something serving two.
echo "  ---- touch list ----"
if [ ! -f "$BASELINE/COMMIT" ]; then
  fail "GATE-SC-TOUCH-LIST" "no COMMIT in $BASELINE"
else
  base_commit="$(head -1 "$BASELINE/COMMIT")"
  forbidden=(
    'backend/app/services/terminal_relay.py'
    'backend/app/services/terminal_queue.py'
    'backend/app/services/tunnels.py'
    'backend/app/services/integrations.py'
    'backend/app/services/node_update.py'
    'backend/app/services/files.py'
    'backend/app/services/favorites.py'
    'backend/app/security/secret_box.py'
    'backend/app/api/ws/terminal.py'
    'daemon/internal/terminal/'
    'daemon/internal/tmux/'
    'daemon/internal/tunnel/'
    'daemon/internal/update/'
    'daemon/internal/workspace/'
    'daemon/internal/systeminfo/'
    'daemon/internal/session/'
    'daemon/internal/files/'
    'daemon/internal/runtime/runtime.go'
    'daemon/internal/runtime/launch.go'
    'frontend/src/terminal/'
    'frontend/src/monaco/'
  )
  touched=""
  for path in "${forbidden[@]}"; do
    if git diff --name-only "$base_commit" -- "$path" 2>/dev/null | grep -q .; then
      touched="$touched $path"
    fi
  done
  if [ -z "$touched" ]; then
    pass "GATE-SC-TOUCH-LIST"
  else
    fail "GATE-SC-TOUCH-LIST" "changed:$touched"
  fi
fi

# --- the four ast invariants ------------------------------------------------
# SINGLE-DECRYPT / TAG-BOTH-QUERIES / NO-PLAINTEXT-COLUMN / NO-BINDING-PROMISE.
echo "  ---- invariants ----"
check "GATE-SC-{SINGLE-DECRYPT,TAG-BOTH-QUERIES,NO-PLAINTEXT-COLUMN,NO-BINDING-PROMISE}" \
  uv run --project backend python scripts/sc/gate_secret_invariants.py

# --- GATE-SC-NO-SECRET-IN-RESPONSE ------------------------------------------
# Every schema reachable from a **response**, not every schema in the document: the
# first version of this failed on `CreateProjectSecretRequest`, which of course carries a
# value — that is the request that stores one. A guard that cannot tell a request from a
# response would be "fixed" by renaming the field somebody has to type.
echo "  ---- no secret in any response ----"
check "GATE-SC-NO-SECRET-IN-RESPONSE" \
  uv run --project backend python scripts/sc/gate_no_secret_in_response.py

# --- GATE-SC-PUSH-ARGV ------------------------------------------------------
# Constraint 3, statically. Implemented as "those strings are not in the table" rather
# than as a check that they are absent: a check can be bypassed by a second call site.
# Comments are stripped first, so the paragraph explaining the rule does not trip it.
echo "  ---- push argv ----"
if uv run --project backend python - <<'PY'
import pathlib, re, sys
root = pathlib.Path("daemon/internal/gitfetch")
forbidden = ["--force", "--force-with-lease", "--delete", "--tags", "--mirror", "push --all"]
bad = []
for path in sorted(root.glob("*.go")):
    if path.name.endswith("_test.go"):
        continue
    code = "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("//")
    )
    for flag in forbidden:
        if flag in code:
            bad.append(f"{path}: {flag}")
if bad:
    print("\n".join(bad), file=sys.stderr)
    sys.exit(1)
PY
then pass "GATE-SC-PUSH-ARGV"; else fail "GATE-SC-PUSH-ARGV" "a destructive flag is in the table"; fi

# --- GATE-SC-NO-SECRET-TO-DISK ---------------------------------------------
# A secret value must not reach a file. The one apparent exception is `ssh-agent`'s
# socket, and a socket is not a key. Checked structurally: no field of `Secrets` may be
# an argument to a file-writing call.
echo "  ---- no secret to disk ----"
if uv run --project backend python - <<'PY'
import pathlib, re, sys
root = pathlib.Path("daemon/internal")
writers = re.compile(r"os\.(WriteFile|Create|OpenFile)\(")
bad = []
for path in sorted(root.rglob("*.go")):
    if path.name.endswith("_test.go"):
        continue
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not writers.search(line):
            continue
        # The value-bearing identifiers, by the names the code actually uses.
        # `run.token` is the one deliberate exception, and it is **excluded by name
        # rather than by loosening the pattern**: the `cliora` CLI is a separate
        # process and has to read its credential from somewhere, so V2.2 writes it at
        # 0600 and deletes it the moment the run ends (ADR 0029). A project secret has
        # no such need — it is inherited through the environment — so nothing else may
        # take this route.
        if "run.token" in line:
            continue
        if re.search(r"\b(secret|secrets\.(All|Env|Git)|privateKey|password|token)\b", line):
            bad.append(f"{path}:{number}  {line.strip()}")
if bad:
    print("\n".join(bad), file=sys.stderr)
    sys.exit(1)
PY
then pass "GATE-SC-NO-SECRET-TO-DISK"; else fail "GATE-SC-NO-SECRET-TO-DISK" "a secret value reaches a file"; fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "all V2.3 gates passed"
else
  echo "V2.3 gates FAILED" >&2
fi
exit "$FAILED"
