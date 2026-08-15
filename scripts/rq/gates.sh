#!/usr/bin/env bash
# RQ-12: the machine assertions for V2.5 (plan/22/09-…md §3).
#
# Ten gates. Each guards a property whose violation is **silent** — the code runs, the
# tests pass, and what changed is a promise nobody re-reads. Six are new here; four are
# earlier phases' gates re-pointed at this baseline, because "only additions" and "the
# touch list held" are the same questions asked of a different starting point.
#
#   scripts/rq/gates.sh [baseline-dir]     # default artifacts/rq/local/baseline
#
# Needs a migrated PostgreSQL at CLIORA_DATABASE_URL for the schema gates.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

BASELINE="${1:-artifacts/rq/local/baseline}"
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

echo "V2.5 gates (baseline: $BASELINE)"

# --- inherited, re-pointed at this phase's baseline -------------------------
check "GATE-RQ-SCHEMA-ADDITIVE" scripts/pj/gate-schema-additive.sh "$BASELINE/schema.txt"
check "GATE-RQ-MIGRATION-ROUNDTRIP" scripts/ar/gate-migration-roundtrip.sh \
  "$BASELINE/schema.txt" 0038_runner_features

echo "  ---- touch list ----"
# The daemon's node-side half is untouched this phase: two run kinds that produce no
# code use the *same* lifecycle, and the only daemon change is three CLI subcommands.
# A diff here means something crossed from Central into the node's execution path.
for area in runtime runner workspace gitfetch; do
  if git diff --quiet "$(cat "$BASELINE/COMMIT" | head -1)" -- "daemon/internal/$area" 2>/dev/null; then
    pass "GATE-RQ-TOUCH-LIST ($area)"
  else
    fail "GATE-RQ-TOUCH-LIST ($area)" "daemon/internal/$area changed; V2.5 touches only internal/cli"
  fi
done

echo "  ---- new in this phase ----"

# 1. contracts/ does not change by a single byte.
#
# The inherited CONTRACT-ADDITIVE gate compares the fixture *list* and allows additions,
# which is right for a phase that adds fixtures and wrong for this one. Adding a schema
# field plus a matching valid fixture would pass that gate — and that is precisely the
# move that makes an un-upgraded node silently drop every offer (ADR 0029 amendment C).
if [ -f "$BASELINE/contract-tree.sha256" ]; then
  current="$(find contracts -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  if [ "$current" = "$(cat "$BASELINE/contract-tree.sha256")" ]; then
    pass "GATE-RQ-CONTRACT-FROZEN"
  else
    fail "GATE-RQ-CONTRACT-FROZEN" "contracts/ changed; V2.5 promises v1.13.0 unchanged"
  fi
else
  fail "GATE-RQ-CONTRACT-FROZEN" "no contract-tree.sha256 in the baseline (RQ-00 captures it)"
fi

# 2. The three "who decided" columns have exactly one writer each.
#
# **The most important gate in the phase.** A second write site would not turn any test
# red: the row looks entirely normal, and what is wrong is that the "person" in it was
# not one.
check "GATE-RQ-HUMAN-ACTOR" uv run --project backend python scripts/rq/gate_human_actor.py

# 3. Submitting a proposal never creates a card.
#
# An implementation that also created cards passes every test — the proposal exists, the
# cards exist, and they agree. What breaks is "a person looked at it", which has no
# runtime shape to assert against.
check "GATE-RQ-NO-CARD-FROM-RUN" uv run --project backend python scripts/rq/gate_no_card_from_run.py

# 4. The context pack is chosen in exactly one place.
#
# A second branch's first missed kind hands a clarification card the implementation pack
# — whose "environment variables available to this run" section is a false sentence,
# because that kind of card is refused secrets at dispatch.
check "GATE-RQ-CONTEXT-DISPATCH" uv run --project backend python scripts/rq/gate_context_dispatch.py

# 5. The platform never applies a patch.
#
# "We already have the diff, let's add an apply button" is a natural next thought, and it
# would pass every test in the suite.
check "GATE-RQ-NO-PATCH-APPLY" uv run --project backend python scripts/rq/gate_no_patch_apply.py

# 6. The three proposal tables are insert-only apart from their decision columns.
#
# An in-place rewrite changes what a person looked at when they decided.
check "GATE-RQ-APPEND-ONLY" uv run --project backend python scripts/rq/gate_append_only.py

echo
if [ "$FAILED" = "0" ]; then
  echo "all V2.5 gates passed"
else
  echo "one or more V2.5 gates failed"
fi
exit "$FAILED"
