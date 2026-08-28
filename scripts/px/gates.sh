#!/usr/bin/env bash
# PX-65: the machine assertions for `v2.0.0-beta.1` (plan/26/10 §3).
#
# Nine new gates. Each guards a property whose violation is **silent** — the code runs,
# the tests pass, and what changed is a promise nobody re-reads. Four are AST scans and
# share one Python process; the rest are shell-shaped and sit below.
#
#   scripts/px/gates.sh [baseline-dir]     # default artifacts/px/local/baseline
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/px/local/baseline}"
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

echo "V2-P1 gates (baseline: $BASELINE)"

# --- the four AST invariants -------------------------------------------------
check "GATE-PX-{ONE-PROJECT-SCOPE,NO-DYNAMIC-SQL,SINGLE-ATTENTION,BULK-USES-UPDATE}" \
  uv run --project backend python scripts/px/gate_work_invariants.py

# --- GATE-PX-BUILDER-SUBSET --------------------------------------------------
#
# The filter builder is TypeScript and the allowlist is Python, so nothing in either
# language can notice them drifting — and the drift shows up as a 400 from a dropdown the
# person was invited to use. It caught six wrong values in three of eight fields the first
# time it ran.
check "GATE-PX-BUILDER-SUBSET" \
  uv run --project backend python scripts/px/gate_filter_builder_subset.py

# --- GATE-PX-NO-DAEMON-DIFF --------------------------------------------------
#
# The whole content of this gate is `git diff --stat -- daemon/` being empty against the
# commit the phase started from. Any daemon change turns "an un-upgraded node behaves
# exactly as before" from a tautology into a proposition somebody has to verify.
if [ -f "$BASELINE/COMMIT" ]; then
  if [ -z "$(git diff --name-only "$(cat "$BASELINE/COMMIT")" -- daemon/)" ]; then
    pass "GATE-PX-NO-DAEMON-DIFF"
  else
    fail "GATE-PX-NO-DAEMON-DIFF" \
      "$(git diff --name-only "$(cat "$BASELINE/COMMIT")" -- daemon/ | tr '\n' ' ')"
  fi
  # And the version string, separately: a bumped VERSION with no code change is still a
  # release nobody asked for.
  if [ "$(cat daemon/VERSION)" = "$(cat "$BASELINE/agentd-version")" ]; then
    pass "GATE-PX-NO-DAEMON-DIFF (VERSION)"
  else
    fail "GATE-PX-NO-DAEMON-DIFF (VERSION)" "$(cat daemon/VERSION) != $(cat "$BASELINE/agentd-version")"
  fi
else
  fail "GATE-PX-NO-DAEMON-DIFF" "no COMMIT in $BASELINE (run capture-baseline.sh)"
fi

# --- GATE-PX-CONTRACT-FROZEN -------------------------------------------------
#
# The **whole** `contracts/` tree this time, not only `v1/`: this phase changes nothing on
# the wire and adds no changelog entry either, so there is no explanation for the hash to
# break (compare `GATE-KN-CONTRACT-FROZEN`, which had to exclude the changelog because
# that phase wrote in it).
if [ -f "$BASELINE/contracts.sha256" ]; then
  current="$(find contracts -type f -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  if [ "$current" = "$(cat "$BASELINE/contracts.sha256")" ]; then
    pass "GATE-PX-CONTRACT-FROZEN"
  else
    fail "GATE-PX-CONTRACT-FROZEN" "contracts/ changed"
  fi
else
  fail "GATE-PX-CONTRACT-FROZEN" "no contracts.sha256 in $BASELINE"
fi

# --- GATE-PX-BOARD-UNCHANGED -------------------------------------------------
#
# **Deleted in `beta.2`** (ADR 0044, `plan/27` D126). It asserted that `BoardCardDTO`
# still had exactly 16 fields; `BoardCardDTO` no longer exists, and a gate guarding a
# deleted type passes for the wrong reason.
#
# The property it protected — a card that renders a board stays a summary — is now
# enforced on the shape that replaced it, by `backend/tests/db/test_work_items_size.py`.
# `GATE-HD-BOARD-GONE` in `scripts/hd/gates.sh` asserts the deletion itself stayed done.

# --- GATE-PX-TOUCH-LIST ------------------------------------------------------
#
# The do-not-touch list from `plan/26/00` §3, with its four named exceptions. Checked as
# paths rather than as content: the promise is "this phase did not go here", and a
# content hash would fail on a comment while a path check says exactly what happened.
if [ -f "$BASELINE/COMMIT" ]; then
  base="$(cat "$BASELINE/COMMIT")"
  forbidden="$(git diff --name-only "$base" -- \
    daemon/ contracts/ \
    backend/app/services/secrets.py \
    backend/app/services/deliveries.py \
    backend/app/services/knowledge/ \
    backend/app/composables 2>/dev/null | tr '\n' ' ')"
  if [ -z "$forbidden" ]; then
    pass "GATE-PX-TOUCH-LIST"
  else
    fail "GATE-PX-TOUCH-LIST" "$forbidden"
  fi
  # `useAsyncResource.ts` is on the list by name (D100): the new query layer is an
  # addition beside it, not an extension of it.
  if git diff --quiet "$base" -- frontend/src/composables/useAsyncResource.ts; then
    pass "GATE-PX-TOUCH-LIST (useAsyncResource)"
  else
    fail "GATE-PX-TOUCH-LIST (useAsyncResource)" "D100 says this file does not change"
  fi
  # No new dependency on either side. Both `pyproject.toml` and `package.json` are on
  # the list, and the check is the dependency *list* rather than the file, so a
  # `[tool.*]` edit does not read as a new package.
  if [ -f "$BASELINE/backend-deps.txt" ]; then
    current="$(uv run --project backend python - <<'PY'
import pathlib, re
text = pathlib.Path("backend/pyproject.toml").read_text(encoding="utf-8")
block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
print("\n".join(sorted(re.findall(r'"([A-Za-z0-9._-]+)', block.group(1))) if block else []))
PY
)"
    if [ "$current" = "$(cat "$BASELINE/backend-deps.txt")" ]; then
      pass "GATE-PX-TOUCH-LIST (backend dependencies)"
    else
      fail "GATE-PX-TOUCH-LIST (backend dependencies)" "the dependency list moved"
    fi
  fi
  if [ -f "$BASELINE/frontend-deps.txt" ]; then
    current="$(node -e 'const p=require("./frontend/package.json");console.log(Object.keys(p.dependencies||{}).sort().join("\n"))')"
    if [ "$current" = "$(cat "$BASELINE/frontend-deps.txt")" ]; then
      pass "GATE-PX-TOUCH-LIST (frontend dependencies)"
    else
      fail "GATE-PX-TOUCH-LIST (frontend dependencies)" "D56: no new frontend package"
    fi
  fi
else
  fail "GATE-PX-TOUCH-LIST" "no COMMIT in $BASELINE"
fi

# --- GATE-PX-MIGRATION-ROUNDTRIP ---------------------------------------------
#
# `0043` down and up again against a real database, because "additive and reversible" is
# a claim about PostgreSQL rather than about the file. Skipped without a database rather
# than failed: the other gates are static and useful on their own.
if [ -n "${CLIORA_DATABASE_URL:-}" ]; then
  # **The database has to be Alembic's, and this checks before blaming the migration.**
  # `pytest tests/db` builds its schema with `metadata.create_all`, so a database it
  # touched last has a stamped `alembic_version` over objects Alembic never created — and
  # then `downgrade` fails on something that was never there. That reported as
  # "0043 did not survive down-and-up", which is a claim about the migration and was not
  # true. A gate that misattributes its own precondition is worse than one that skips.
  roundtrip_error=""
  if ! (cd backend && uv run --project . alembic current 2>/dev/null | grep -q '(head)'); then
    roundtrip_error="the database is not at head — run \`alembic upgrade head\` first"
  elif ! (cd backend && uv run --project . alembic downgrade 0042_knowledge_tables \
      > /tmp/px-roundtrip-down.log 2>&1); then
    roundtrip_error="downgrade failed: $(tail -1 /tmp/px-roundtrip-down.log)"
  elif ! (cd backend && uv run --project . alembic upgrade head \
      > /tmp/px-roundtrip-up.log 2>&1); then
    roundtrip_error="re-upgrade failed: $(tail -1 /tmp/px-roundtrip-up.log)"
  fi
  if [ -z "$roundtrip_error" ]; then
    pass "GATE-PX-MIGRATION-ROUNDTRIP"
  else
    fail "GATE-PX-MIGRATION-ROUNDTRIP" "$roundtrip_error"
  fi
else
  printf '  \033[33mSKIP\033[0m  GATE-PX-MIGRATION-ROUNDTRIP — set CLIORA_DATABASE_URL\n'
fi

# --- GATE-PX-JOURNEY-COVERAGE ------------------------------------------------
#
# `plan/26/10` §3 calls this **the phase's most likely false green**, and it was right:
# for weeks `evidence.sh` printed three `SKIP` lines with a reason that was not true. The
# gate checks that all six journeys left evidence, that every assertion inside a verdict
# passed, and that no source file the journey covers is newer than the journey — the last
# of which is the only one that works while a phase is uncommitted.
check "GATE-PX-JOURNEY-COVERAGE" \
  uv run --project backend python scripts/px/gate_journey_coverage.py

# --- GATE-PX-MYWORK-READS-STATE ----------------------------------------------
#
# This replaces an upstream exit condition that could not be written: it required "marking
# notifications read does not change My Work's counts", and **this system has no
# notifications** — no table, no endpoint, no read state. A test for it would pass
# forever while asserting nothing.
#
# What the gate defends instead is the property the condition was really about: My Work's
# predicates read Task, Run and gate state and nothing about what a person has *seen*. So
# when notifications do arrive, nobody wires them into a count.
# **The scan strips comments and docstrings first.** The first version of this gate was a
# plain `grep` and it failed on its own explanatory paragraph — which is exactly the
# failure `plan/18/09` §3 item 15 records: V2.2 shipped three gates that matched their own
# comments, and the cheapest way to green such a gate is to delete the sentence saying why
# the rule exists.
check "GATE-PX-MYWORK-READS-STATE" \
  uv run --project backend python scripts/px/gate_mywork_reads_state.py

# --- the one earlier gate this phase could plausibly break --------------------
#
# `GATE-DV-SINGLE-DONE-PATH` re-run **specifically**, rather than the whole V2.4 suite.
# The suite's other gates depend on that phase's own baseline and on a database named for
# it, so running all of them here reports this phase failing for somebody else's stale
# fixture — a red that teaches the reader to ignore reds.
#
# This one matters because it is the reason bulk update is a loop: it is the AST scan that
# makes `TaskService.update()` the only assigner of `task.stage`, and a bulk statement
# written straight against the table is the shape it exists to catch.
if grep -rnE '\.stage\s*=\s*["'"'"']done["'"'"']' backend/app/services/runs.py >/dev/null; then
  fail "GATE-DV-SINGLE-DONE-PATH (re-run)" "a run advanced a card into done"
else
  pass "GATE-DV-SINGLE-DONE-PATH (re-run)"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "all V2-P1 gates passed"
else
  echo "V2-P1 gates FAILED"
fi
exit "$FAILED"
