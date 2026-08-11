#!/usr/bin/env bash
# AR-12: the phase's gates, in one runnable place (plan/18/08-…md §3/§4).
#
# Each of these asserts something a review cannot: that a *negative* proposition still
# holds. A negative proposition is the kind that quietly stops being true, so every one
# of them is a command rather than a checklist item.
#
#   scripts/ar/gates.sh
#
# Needs the AR-00 baselines (`scripts/ar/capture-baseline.sh`) and a migrated database.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="artifacts/ar/local/baseline"
failures=0

pass() { printf '[ OK ] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n%s\n' "$1" "${2:-}"; failures=$((failures + 1)); }

check() {
  local name="$1"; shift
  local output
  if output="$("$@" 2>&1)"; then
    pass "$name"
  else
    fail "$name" "$output"
  fi
}

# --- GATE-AR-SCHEMA-ADDITIVE ------------------------------------------------
# Every table that existed before this phase is unchanged, column for column.
check "GATE-AR-SCHEMA-ADDITIVE" scripts/pj/gate-schema-additive.sh "$BASELINE/schema.txt"

# --- GATE-AR-MIGRATION-ROUNDTRIP -------------------------------------------
# Down to 0028 restores the captured schema exactly, and up returns to head. The
# interesting half is `0031`'s `drop_column`: an orphan column left on a pre-existing
# table is what makes the *next* phase's baseline diff permanently unexplainable.
check "GATE-AR-MIGRATION-ROUNDTRIP" scripts/ar/gate-migration-roundtrip.sh "$BASELINE/schema.txt"

# --- GATE-AR-CONTRACT-ADDITIVE ---------------------------------------------
# Every fixture that existed before is byte-for-byte identical; only new ones appear.
# A fixture is a recorded decision about what the wire accepts, and an edited one
# silently rewrites a promise made to every daemon already deployed.
check "GATE-AR-CONTRACT-ADDITIVE" \
  uv run --project backend python scripts/tk/contract_snapshot.py \
  --diff "$BASELINE/contract-fixtures.txt"

# --- GATE-AR-TOUCH-LIST -----------------------------------------------------
# The files this phase promised not to change. `runtime.go` and `launch.go` are the
# load-bearing pair: `launch.go` already records that adding a caller-supplied string
# to its table is the change SEC-002 exists to prevent, so the whole non-interactive
# path went into a **new** file to make this assertion possible.
BASE_COMMIT="$(head -1 "$BASELINE/COMMIT" 2>/dev/null || echo '')"
if [ -z "$BASE_COMMIT" ]; then
  fail "GATE-AR-TOUCH-LIST" "no COMMIT in $BASELINE"
else
  frozen=(
    daemon/internal/runtime/runtime.go
    daemon/internal/runtime/launch.go
    daemon/internal/files
    daemon/internal/workspace
    daemon/internal/terminal
    daemon/internal/tmux
    backend/app/services/terminal_relay.py
    backend/app/services/terminal_queue.py
    backend/app/api/ws/terminal.py
  )
  touched="$(git diff --name-only "$BASE_COMMIT" -- "${frozen[@]}" || true)"
  if [ -z "$touched" ]; then
    pass "GATE-AR-TOUCH-LIST"
  else
    fail "GATE-AR-TOUCH-LIST" "$touched"
  fi
fi

# --- GATE-AR-SINGLE-CLAIM / NO-WORKSPACE-IN-RUNS / NO-REQUEST-IN-LOOP ------
#
# **Parsed, not grepped.** The first version of these three was a text scan, and all
# three failed on their own documentation: `runs.py`'s docstring explains why it must
# not call `registry.request()` and why `authorize_workspace` is not imported, and
# `uploaded_by_runner_id=` contains `runner_id=` as a substring. A guard that finds its
# own explanation is worse than no guard — the cheapest way to make it green is to
# delete the paragraph that says why the rule exists.
if uv run --project backend python scripts/ar/gate_run_invariants.py; then
  pass "GATE-AR-SINGLE-CLAIM"
  pass "GATE-AR-NO-WORKSPACE-IN-RUNS"
  pass "GATE-AR-NO-REQUEST-IN-LOOP"
else
  fail "GATE-AR-SINGLE-CLAIM / NO-WORKSPACE-IN-RUNS / NO-REQUEST-IN-LOOP"
fi

# --- criterion 14, assertion 1: no response declares text/html --------------
# A negative proposition about the whole API surface, checked against an enumeration
# rather than by reading routes.
uv run --project backend python - <<'PY'
import json, subprocess, sys
sys.path.insert(0, "backend")
from app.main import app

document = app.openapi()
offenders = []
for path, methods in document.get("paths", {}).items():
    for method, operation in methods.items():
        for code, response in (operation.get("responses") or {}).items():
            for media in (response.get("content") or {}):
                if "html" in media:
                    offenders.append(f"{method.upper()} {path} {code} {media}")
if offenders:
    print("responses declaring HTML:", offenders)
    raise SystemExit(1)

# The immutability of an artifact, as a machine statement: two verbs, no more.
verbs = sorted(
    verb.upper()
    for verb in document["paths"].get("/api/artifacts/{artifact_id}", {})
    if verb in {"get", "put", "post", "patch", "delete"}
)
if verbs != ["DELETE", "GET"]:
    print("artifact route verbs:", verbs)
    raise SystemExit(1)
print("openapi: no HTML response, artifacts are GET+DELETE only")
PY
if [ $? -eq 0 ]; then pass "criterion-14/openapi"; else fail "criterion-14/openapi"; fi

# --- criterion 14, assertion 2: the routes this phase added render no artifact
# The frontend route table is compared against the one captured before the phase, and
# the *added* rows are checked by name. A route that took an artifact id would show up
# here as a new row nobody had to think about.
added="$(python3 scripts/ar/frontend_routes.py | diff "$BASELINE/frontend-routes.txt" - \
  | grep '^>' || true)"
if printf '%s' "$added" | grep -qiE "artifact"; then
  fail "criterion-14/routes" "a new route names an artifact:
$added"
else
  pass "criterion-14/routes"
  printf '       added routes:\n%s\n' "${added:-       (none)}"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "all gates passed"
else
  echo "$failures gate(s) failed"
fi
exit "$failures"
