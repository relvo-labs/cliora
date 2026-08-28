#!/usr/bin/env bash
# HD-14: the machine assertions for `v2.0.0-beta.2` (plan/27/09 §2).
#
# Same shape as `scripts/px/gates.sh` and the same rule for what earns a gate: a property
# whose violation is **silent** — the code runs, the tests pass, and what changed is a
# promise nobody re-reads.
#
#   scripts/hd/gates.sh [baseline-dir]     # default artifacts/hd/local/baseline
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/hd/local/baseline}"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s%s\n' "$1" "${2:+ — $2}"; FAILED=1; }
skip() { printf '  \033[33mSKIP\033[0m  %s%s\n' "$1" "${2:+ — $2}"; }

# Assert a pattern is **absent**. Verification by absence: a check has a second call site
# and a file that does not contain the word does not (`GATE-DV-PROVIDER-VERBS`'s reason).
absent() {
  local name="$1" why="$2"; shift 2
  local hits
  if hits="$(git grep -nI "$@" 2>/dev/null)" && [ -n "$hits" ]; then
    fail "$name" "$why: $(printf '%s' "$hits" | head -2 | tr '\n' ' ')"
  else
    pass "$name"
  fi
}

# Assert a pattern is **present**. Rarer, and used only where the failure mode is a
# silent omission rather than a silent addition.
present() {
  local name="$1" why="$2"; shift 2
  if git grep -qI "$@" 2>/dev/null; then
    pass "$name"
  else
    fail "$name" "$why"
  fi
}

# Set difference **without `comm`**. `comm` requires both inputs in the same collation and
# only warns — on stderr — when they are not, so a caller that pipes to `tail` gets a
# confident wrong answer. These two files come from Python's `sorted()` and from the shell
# respectively, which is exactly the case that breaks. `grep -Fxv -f` needs no ordering.
#   only_in <candidate-file> <reference-file>
only_in() { grep -Fxv -f "$2" "$1" 2>/dev/null | sed '/^$/d' || true; }

echo "V2-E1 gates (baseline: $BASELINE)"

# --- the board sunset stayed done (ADR 0044, D126) ---------------------------
#
# Three shapes, because the deletion has three halves and reverting any one of them
# leaves the other two looking finished.
absent "GATE-HD-BOARD-GONE (route)" "the /board route came back" \
  -E 'projects/\{project_id\}/board"' -- 'backend/app/api/http/*.py'
absent "GATE-HD-BOARD-GONE (schemas)" "a Board DTO came back" \
  -E 'class Board(Card|Lane)?DTO' -- 'backend/app/api/http/schemas.py'
absent "GATE-HD-BOARD-GONE (client)" "the frontend can call /board again" \
  -E 'getBoard' -- 'frontend/src/*'

# --- GATE-HD-EGRESS-ALLOWLIST ------------------------------------------------
#
# Replaces `GATE-KN-NO-NEW-EGRESS (httpx)`, which was written as an *exclusion*
# (`grep -v services/providers.py`). The two are equivalent while there is one module and
# stop being equivalent at the second: the exclusion form fails with "httpx is imported
# outside services/providers.py" and **cannot say which file**. This one can.
#
# The allowlist lives in the baseline, not here: a gate holding its own copy of the answer
# is a gate that agrees with itself.
if [ -f "$BASELINE/httpx-importers.txt" ]; then
  expected="$(cat "$BASELINE/httpx-importers.txt")"
  # `provider_reads.py` is the second permitted module (D119). It is added to the expected
  # set **only once it exists**, so that before wave 2 this gate asserts the baseline
  # unchanged rather than demanding a file nobody has written. A gate that fails for the
  # whole phase until its subject arrives is a gate people learn to ignore.
  if [ -f backend/app/services/provider_reads.py ]; then
    expected="$(printf '%s\nbackend/app/services/provider_reads.py\n' "$expected" | LC_ALL=C sort -u | sed '/^$/d')"
  fi
  actual="$(git grep -l -E '^(import|from) httpx' -- 'backend/app/**/*.py' 2>/dev/null | LC_ALL=C sort -u)"
  if [ "$expected" = "$actual" ]; then
    pass "GATE-HD-EGRESS-ALLOWLIST"
    printf '        permitted: %s\n' "$(printf '%s' "$actual" | tr '\n' ' ')"
  else
    fail "GATE-HD-EGRESS-ALLOWLIST" \
      "httpx importers moved: expected [$(printf '%s' "$expected" | tr '\n' ' ')] got [$(printf '%s' "$actual" | tr '\n' ' ')]"
  fi
else
  fail "GATE-HD-EGRESS-ALLOWLIST" "no httpx-importers.txt in $BASELINE (run capture-baseline.sh)"
fi

# --- provider reads are reads (D119, D122) -----------------------------------
#
# These four only mean anything once `provider_reads.py` exists (wave 2). Until then they
# **skip loudly** rather than passing: a gate that passes because its subject is absent is
# the failure mode `plan/26` §6 spent a page on.
if [ -f backend/app/services/provider_reads.py ]; then
  absent "GATE-HD-READS-ARE-GETS" "a non-GET method literal in the read-only provider module" \
    -E '"(POST|PUT|PATCH|DELETE)"' -- 'backend/app/services/provider_reads.py'
  absent "GATE-HD-NO-WRITE-IMPORT" "the read module reached a write verb" \
    -E '(create_pull_request|comment_on_pull_request|adapter_for)' \
    -- 'backend/app/services/provider_reads.py'
  absent "GATE-HD-NO-PROVIDER-IN-REQUEST" "an HTTP route can reach the provider" \
    -E 'provider_reads' -- 'backend/app/api/http/*.py'
else
  skip "GATE-HD-READS-ARE-GETS" "provider_reads.py does not exist yet (wave 2)"
  skip "GATE-HD-NO-WRITE-IMPORT" "provider_reads.py does not exist yet (wave 2)"
  skip "GATE-HD-NO-PROVIDER-IN-REQUEST" "provider_reads.py does not exist yet (wave 2)"
fi

if [ -f backend/app/services/knowledge/provider_sources.py ]; then
  absent "GATE-HD-PROVIDER-AUTHORITY-CEILING" "provider data reached above 'reviewed'" \
    -E '"(accepted|authoritative|canonical|verified)"' \
    -- 'backend/app/services/knowledge/provider_sources.py'
else
  skip "GATE-HD-PROVIDER-AUTHORITY-CEILING" "provider_sources.py does not exist yet (wave 3)"
fi

# --- the stage sunset (D123) -------------------------------------------------
#
# **Whole tree, not `runs.py`.** `GATE-DV-SINGLE-DONE-PATH` scans one file and one value,
# which is why `run_reaper.py`'s two writers sat outside its view for three phases.
if git grep -qI -E '\.stage\s*=\s*["'"'"']blocked["'"'"']' -- 'backend/app/**/*.py' 2>/dev/null; then
  count="$(git grep -cI -E '\.stage\s*=\s*["'"'"']blocked["'"'"']' -- 'backend/app/**/*.py' 2>/dev/null | awk -F: '{s+=$2} END {print s+0}')"
  if [ "$count" = "3" ]; then
    skip "GATE-HD-NO-LEGACY-BLOCKED" "3 writers remain — HD-06 has not run yet (expected before wave 4)"
  else
    fail "GATE-HD-NO-LEGACY-BLOCKED" "$count writers of stage='blocked' (was 3; HD-06 takes it to 0)"
  fi
else
  pass "GATE-HD-NO-LEGACY-BLOCKED"
fi

if grep -q "ck_tasks_stage" backend/app/db/models.py 2>/dev/null; then
  pass "GATE-HD-STAGE-CHECK-IN-MODEL"
else
  skip "GATE-HD-STAGE-CHECK-IN-MODEL" "HD-06 adds it; the constraint is in 0023 and not yet in the ORM"
fi

# --- the visual baseline (D124) ----------------------------------------------
if [ -d frontend/tests/visual ]; then
  declared="$(grep -c 'toHaveScreenshot(' frontend/tests/visual/*.spec.ts 2>/dev/null | awk -F: '{s+=$2} END {print s+0}')"
  stored="$(find frontend/tests/visual -name '*.png' 2>/dev/null | wc -l)"
  if [ "$declared" -gt 0 ] && [ "$declared" = "$stored" ]; then
    pass "GATE-HD-VISUAL-BASELINE ($stored screens)"
  else
    fail "GATE-HD-VISUAL-BASELINE" "$declared declared, $stored stored — a missing baseline is a screen nobody compares"
  fi
else
  skip "GATE-HD-VISUAL-BASELINE" "frontend/tests/visual does not exist yet (wave 1)"
fi

# --- GATE-HD-TOUCH-LIST ------------------------------------------------------
#
# The forbidden list of `plan/27/00` §3, with **one named exception**: the frontend
# dependency list gains exactly `@axe-core/playwright` (D125). Asserted as "differs by
# exactly this one name" rather than "unchanged", because a phase that is allowed one new
# package and checks nothing has no list at all.
# `touched` is local on purpose: keying the pass off the global `$FAILED` would make this
# gate report a failure that belongs to an unrelated one three checks earlier.
touched=""
for path in backend/app/services/providers.py backend/app/services/agent_auth.py \
            backend/app/services/rbac.py backend/app/services/done_gate.py \
            backend/app/services/secrets.py backend/app/services/deliveries.py \
            frontend/src/composables/useAsyncResource.ts; do
  if [ -f "$BASELINE/COMMIT" ] && ! git diff --quiet "$(cat "$BASELINE/COMMIT")" -- "$path" 2>/dev/null; then
    touched="$touched $path"
  fi
done
if [ -z "$touched" ]; then
  pass "GATE-HD-TOUCH-LIST (forbidden paths)"
else
  fail "GATE-HD-TOUCH-LIST (forbidden paths)" "changed:$touched"
fi

if [ -f "$BASELINE/frontend-dev-deps.txt" ]; then
  actual_dev="$(node -e 'console.log(Object.keys(require("./frontend/package.json").devDependencies||{}).sort().join("\n"))' 2>/dev/null)"
  printf '%s\n' "$actual_dev" | sed '/^$/d' > /tmp/hd-dev-actual.$$
  added="$(only_in /tmp/hd-dev-actual.$$ "$BASELINE/frontend-dev-deps.txt")"
  removed="$(only_in "$BASELINE/frontend-dev-deps.txt" /tmp/hd-dev-actual.$$)"
  rm -f /tmp/hd-dev-actual.$$
  if [ -z "$removed" ] && { [ -z "$added" ] || [ "$added" = "@axe-core/playwright" ]; }; then
    pass "GATE-HD-TOUCH-LIST (frontend deps${added:+ — one permitted addition: $added})"
  else
    fail "GATE-HD-TOUCH-LIST (frontend deps)" "added [$added] removed [$removed]; D125 permits exactly @axe-core/playwright"
  fi
fi

if [ -f "$BASELINE/backend-deps.txt" ]; then
  actual_be="$(uv run --project backend python - <<'PY' 2>/dev/null
import re
import pathlib

text = pathlib.Path("backend/pyproject.toml").read_text(encoding="utf-8")
block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
print("\n".join(sorted(re.findall(r'"([A-Za-z0-9._-]+)', block.group(1))) if block else []))
PY
)"
  if [ "$actual_be" = "$(cat "$BASELINE/backend-deps.txt")" ]; then
    pass "GATE-HD-TOUCH-LIST (backend deps)"
  else
    fail "GATE-HD-TOUCH-LIST (backend deps)" "the backend dependency list moved; this phase adds none"
  fi
fi

# --- GATE-HD-OPENAPI-DIFF ----------------------------------------------------
#
# The deletion is **exactly one path**. A gate that only asserted "/board is gone" would
# pass a commit that also removed six other routes.
if [ -f "$BASELINE/openapi-paths.txt" ]; then
  if actual_paths="$(uv run --project backend python - 2>/dev/null <<'PY'
from app.main import app

for path in sorted(app.openapi()["paths"]):
    print(path)
PY
)"; then
    printf '%s\n' "$actual_paths" | sed '/^$/d' > /tmp/hd-openapi-actual.$$
    gone="$(only_in "$BASELINE/openapi-paths.txt" /tmp/hd-openapi-actual.$$)"
    new="$(only_in /tmp/hd-openapi-actual.$$ "$BASELINE/openapi-paths.txt")"
    rm -f /tmp/hd-openapi-actual.$$
    if [ "$gone" = "/api/projects/{project_id}/board" ] && [ -z "$new" ]; then
      pass "GATE-HD-OPENAPI-DIFF (exactly /board removed)"
    elif [ -z "$gone" ] && [ -z "$new" ]; then
      skip "GATE-HD-OPENAPI-DIFF" "no path change yet (HD-07 removes /board)"
    else
      fail "GATE-HD-OPENAPI-DIFF" "removed [$(printf '%s' "$gone" | tr '\n' ' ')] added [$(printf '%s' "$new" | tr '\n' ' ')]"
    fi
  else
    fail "GATE-HD-OPENAPI-DIFF" "could not build the OpenAPI schema"
  fi
else
  fail "GATE-HD-OPENAPI-DIFF" "no openapi-paths.txt in $BASELINE (run capture-baseline.sh)"
fi

# --- inherited, with the baseline swapped ------------------------------------
if [ -f "$BASELINE/agentd-version" ]; then
  if git diff --quiet "$(cat "$BASELINE/COMMIT")" -- daemon/ 2>/dev/null; then
    pass "GATE-PX-NO-DAEMON-DIFF (rebased)"
  else
    fail "GATE-PX-NO-DAEMON-DIFF (rebased)" "daemon/ changed; this phase is Central + frontend + data"
  fi
fi
if [ -f "$BASELINE/contracts.sha256" ]; then
  now="$(find contracts -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  if [ "$now" = "$(cat "$BASELINE/contracts.sha256")" ]; then
    pass "GATE-PX-CONTRACT-FROZEN (rebased)"
  else
    fail "GATE-PX-CONTRACT-FROZEN (rebased)" "contracts/ changed; contract stays at 1.13.0"
  fi
fi

exit "$FAILED"
