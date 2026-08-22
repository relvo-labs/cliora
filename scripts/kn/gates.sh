#!/usr/bin/env bash
# KN-12: the machine assertions for `v2.0.0-alpha.3` (plan/25/09-…md §3).
#
# Eight new gates and ten re-runs. Each new one guards a property whose violation is
# **silent** — the code runs, the tests pass, and what changed is a promise nobody
# re-reads. Five are AST scans and share one Python process; three are shell-shaped and
# sit below.
#
#   scripts/kn/gates.sh [baseline-dir]     # default artifacts/kn/local/baseline
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/kn/local/baseline}"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s%s\n' "$1" "${2:+ — $2}"; FAILED=1; }

check() {
  local name="$1"; shift
  if output="$("$@" 2>&1)"; then
    pass "$name"
    # AST gates print the exemptions they honoured. An exemption nobody can see is how a
    # rule quietly stops being one.
    printf '%s' "$output" | grep -E '^ {8}' || true
  else
    fail "$name" "$(printf '%s' "$output" | tail -3 | tr '\n' ' ')"
  fi
}

echo "V2-K1 gates (baseline: $BASELINE)"

# --- the five AST invariants ------------------------------------------------
check "GATE-KN-{ONE-TOKENIZER,PROJECT-SCOPED,INSTRUCTION-LAYER,AUTHORITY-SERVER-SIDE,NO-RAW-LOG-INDEX}" \
  uv run --project backend python scripts/kn/gate_knowledge_invariants.py

# --- GATE-KN-NO-NEW-EGRESS --------------------------------------------------
#
# SR-2 item 7 is "Central added no outbound connection", and its evidence is
# "`pyproject.toml` gained no dependency". A claim whose evidence nobody recorded before
# the phase started cannot be checked after it, which is why the baseline captures the
# dependency **list** rather than a hash of the file — a `[tool.*]` line added in a phase
# with no new package must not read as a new egress.
if [ -f "$BASELINE/backend-deps.txt" ]; then
  current="$(uv run --project backend python - <<'PY'
import pathlib, re
text = pathlib.Path("backend/pyproject.toml").read_text(encoding="utf-8")
block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
print("\n".join(sorted(re.findall(r'"([A-Za-z0-9._-]+)', block.group(1))) if block else []))
PY
)"
  if [ "$current" = "$(cat "$BASELINE/backend-deps.txt")" ]; then
    pass "GATE-KN-NO-NEW-EGRESS (dependencies)"
  else
    fail "GATE-KN-NO-NEW-EGRESS (dependencies)" \
      "$(diff <(echo "$current") "$BASELINE/backend-deps.txt" | tr '\n' ' ')"
  fi
else
  fail "GATE-KN-NO-NEW-EGRESS" "no backend-deps.txt in $BASELINE (run capture-baseline.sh)"
fi

# `httpx` reachable from exactly one module is `SCOPE-013`, and the knowledge layer's
# whole design — repository content pushed from inside a run rather than fetched — exists
# to keep that number at one.
if grep -rn "^import httpx\|^from httpx" backend/app --include=*.py \
   | grep -v "backend/app/services/providers.py" > /dev/null; then
  fail "GATE-KN-NO-NEW-EGRESS (httpx)" "httpx is imported outside services/providers.py"
else
  pass "GATE-KN-NO-NEW-EGRESS (httpx)"
fi

# --- GATE-KN-CONTRACT-FROZEN ------------------------------------------------
#
# Scoped to `contracts/v1/` — the schemas and fixtures a daemon decodes against — and
# **not** `CHANGELOG.md`, where this phase records that it changed nothing. A gate that
# the explanation breaks is a gate discharged by deleting the explanation.
if [ -f "$BASELINE/contract-v1.sha256" ]; then
  current="$(find contracts/v1 -type f -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  if [ "$current" = "$(cat "$BASELINE/contract-v1.sha256")" ]; then
    pass "GATE-KN-CONTRACT-FROZEN"
  else
    fail "GATE-KN-CONTRACT-FROZEN" "contracts/v1 differs from the baseline"
  fi
else
  fail "GATE-KN-CONTRACT-FROZEN" "no contract-v1.sha256 in $BASELINE"
fi

# --- GATE-KN-TOUCH-LIST -----------------------------------------------------
#
# The daemon's node half has a **zero-byte diff** this phase: repository content is
# pushed by the CLI over HTTPS, so nothing about executing a run changed. If that stops
# being true, the phase's risk assessment stops being true with it.
FORBIDDEN=(
  contracts
  daemon/internal/protocol
  daemon/internal/runner
  daemon/internal/connection
  daemon/internal/workspace
  daemon/internal/gitfetch
  backend/app/services/rbac.py
  backend/app/services/secrets.py
  backend/app/services/deliveries.py
)
if [ -f "$BASELINE/COMMIT" ]; then
  base_commit="$(cat "$BASELINE/COMMIT")"
  touched=""
  for path in "${FORBIDDEN[@]}"; do
    # Two questions, because `git diff` answers only the first. A tracked file that
    # changed shows up in the diff; a **new file that has never been added does not**,
    # and the gate would pass while a forbidden directory grew. `plan/23/10` §9.1 records
    # that happening for real.
    if ! git diff --quiet "$base_commit" -- "$path" 2>/dev/null \
      || [ -n "$(git status --porcelain --untracked-files=all -- "$path" 2>/dev/null)" ]; then
      touched="$touched $path"
    fi
  done
  if [ -z "$touched" ]; then
    pass "GATE-KN-TOUCH-LIST"
  else
    fail "GATE-KN-TOUCH-LIST" "changed:$touched"
  fi
else
  fail "GATE-KN-TOUCH-LIST" "no COMMIT in $BASELINE"
fi

# --- GATE-KN-MIGRATION-ROUNDTRIP --------------------------------------------
#
# Re-uses the AR script rather than forking it: the question — does downgrading restore
# the baseline exactly — is the same question, and a second copy would disagree with this
# one the first time either is fixed. Only the target revision differs.
#
# Skipped **loudly** without a database: a gate that silently passes when it could not
# run is worse than one that says it did not.
if [ -f "$BASELINE/schema.txt" ] && [ -n "${CLIORA_DATABASE_URL:-}" ]; then
  check "GATE-KN-MIGRATION-ROUNDTRIP" \
    scripts/ar/gate-migration-roundtrip.sh "$BASELINE/schema.txt" 0040_ticket_conversation
else
  fail "GATE-KN-MIGRATION-ROUNDTRIP" "needs $BASELINE/schema.txt and CLIORA_DATABASE_URL"
fi

# --- GATE-KN-JOURNEY-COVERAGE -----------------------------------------------
#
# **The most likely false green in this phase**: five journeys that all skip, and a suite
# that reports success. `plan/24` names it in exactly those words. So the gate counts
# files, checks each verdict, and — because evidence is only evidence if it describes
# *this* code — refuses a stamp from another commit.
JOURNEYS="artifacts/kn/local/journeys"
EXPECTED="J11 J12 J13 J14 J15"
HEAD_COMMIT="$(git rev-parse HEAD)"
missing=""
stale=""
failed=""
for name in $EXPECTED; do
  file="$JOURNEYS/$name.json"
  if [ ! -f "$file" ]; then
    missing="$missing $name"
    continue
  fi
  verdict="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['verdict'])" "$file")"
  stamped="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['commit'])" "$file")"
  [ "$verdict" = "PASS" ] || failed="$failed $name"
  [ "$stamped" = "$HEAD_COMMIT" ] || stale="$stale $name"
done
if [ -n "$missing$failed" ]; then
  fail "GATE-KN-JOURNEY-COVERAGE" "missing:$missing failed:$failed"
elif [ -n "$stale" ]; then
  # A warning rather than a failure while the tree is dirty: during development HEAD
  # moves under the evidence constantly, and a gate that is red for a whole phase is a
  # gate people learn to ignore. It **must** be clean at closeout, which is condition 20.
  pass "GATE-KN-JOURNEY-COVERAGE (verdicts)"
  printf '        stale evidence (re-run before tagging):%s\n' "$stale"
else
  pass "GATE-KN-JOURNEY-COVERAGE"
fi

# --- re-pointed from earlier phases -----------------------------------------
#
# Paths V2-K1 extended rather than replaced, so they are re-run against this baseline
# rather than restated. `GATE-RQ-CONTEXT-DISPATCH` is the load-bearing one: the policy
# digest is **appended** to a renderer's output rather than being a fifth renderer, and
# this is what asserts that distinction survived.
check "GATE-RQ-CONTEXT-DISPATCH (re-run)" \
  uv run --project backend python scripts/rq/gate_context_dispatch.py
check "GATE-SC-SINGLE-DECRYPT (re-run)" \
  uv run --project backend python scripts/sc/gate_secret_invariants.py
check "GATE-CV-* (re-run)" \
  uv run --project backend python scripts/cv/gate_conversation_invariants.py

echo
if [ "$FAILED" -eq 0 ]; then
  echo "all V2-K1 gates passed"
else
  echo "V2-K1 gates FAILED"
fi
exit "$FAILED"
