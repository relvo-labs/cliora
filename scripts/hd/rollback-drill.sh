#!/usr/bin/env bash
# HD-09: the rollback drill (plan/27/07 §3).
#
#   CLIORA_DATABASE_URL=… scripts/hd/rollback-drill.sh
#
# Six steps on a `beta.1`-shaped database. The one that matters most is step 6, and it is
# an obligation `plan/26` left behind rather than a nicety: D117 decided **not** to create
# `CLIORA_PROJECT_EXPERIENCE_V2`, so the new interface has no kill switch — and the
# consequence, written down at the time, is that saved views must be exported before any
# rollback, because nothing turns them off and nothing else preserves them.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

DB="${DRILL_DB:-cliora_drill}"
URL="postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/$DB"
OUT="artifacts/hd/local/w6/rollback"
mkdir -p "$OUT"
LOG="$OUT/drill.log"
: > "$LOG"

FAILED=0
say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1" | tee -a "$LOG"; }
fail() { printf '  \033[31mFAIL\033[0m  %s — %s\n' "$1" "${2:-}" | tee -a "$LOG"; FAILED=1; }
psql_() { docker exec -i cliora-pg psql -U cliora -d "$DB" -tAc "$1" 2>&1; }
alem()  { ( cd backend && CLIORA_DATABASE_URL="$URL" uv run --project . alembic "$@" ); }

say "=== HD-09 rollback drill ($DB) ==="
docker exec cliora-pg psql -U cliora -d postgres -c "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1
docker exec cliora-pg psql -U cliora -d postgres -c "CREATE DATABASE $DB" >/dev/null 2>&1
alem upgrade head >>"$LOG" 2>&1
CLIORA_DATABASE_URL="$URL" CLIORA_ADMIN_PASSWORD=x \
  uv run --project backend python -m app.bootstrap create-admin --username drill >>"$LOG" 2>&1
CLIORA_DATABASE_URL="$URL" uv run --project backend python scripts/cv/seed-dataset.py \
  --out "$OUT/dataset.json" >>"$LOG" 2>&1

CARDS_BEFORE="$(psql_ "SELECT count(*) FROM tasks")"
MESSAGES_BEFORE="$(psql_ "SELECT count(*) FROM task_messages")"
VIEWS_BEFORE="$(psql_ "SELECT count(*) FROM work_views")"
say "seeded: $CARDS_BEFORE cards, $MESSAGES_BEFORE messages, $VIEWS_BEFORE views"

say ""
say "step 1 — the project layer off: V1 is unaffected"
# The flag is read at import, so it cannot be flipped inside a running process — which is
# why `plan/26` needed a second deployment to test it and why this step asserts at the
# *data* layer instead. What it can prove here: turning the flag off removes no rows.
# `journeys.spec.ts::J16` is the half that drives a browser against a flag-off Central.
V1_TABLES="$(psql_ "SELECT count(*) FROM information_schema.tables WHERE table_name IN ('terminal_sessions','nodes','users','audit_logs')")"
[ "$V1_TABLES" = "4" ] && pass "V1 tables intact" || fail "V1 tables" "$V1_TABLES of 4"

say ""
say "step 2 — export saved views **before** anything is rolled back"
# `plan/26` D117's obligation. Written to a TSV rather than kept in the database: the
# point of the export is to survive a `downgrade` that drops the table, and a copy inside
# the thing being downgraded is not a copy.
psql_ "COPY (SELECT id, project_id, owner_user_id, name, scope, layout FROM work_views ORDER BY id) TO STDOUT" \
  > "$OUT/work-views-before.tsv" 2>>"$LOG"
EXPORTED="$(wc -l < "$OUT/work-views-before.tsv")"
[ "$EXPORTED" = "$VIEWS_BEFORE" ] \
  && pass "exported $EXPORTED saved views" \
  || fail "view export" "$EXPORTED exported, $VIEWS_BEFORE in the table"

say ""
say "step 3 — downgrade past 0046 and 0045"
alem downgrade 0044_provider_ingestion >>"$LOG" 2>&1 && pass "downgrade to 0044" || fail "downgrade to 0044" "see $LOG"
# **This step demonstrates the documented irreversibility rather than contradicting it**,
# and the first version of it asserted the opposite — which is worth keeping in the record
# because the mistake is the easy one to make.
#
# ADR 0040's amendment says: a card blocked *after* `0046` went through `is_blocked` and
# has **no `legacy_blocked_at`**, because that column is written once, by `0045`, for the
# rows it moved. Downgrading leaves those cards `is_blocked = true` on their real stage —
# correct, and invisible to a six-lane board.
#
# The seeded fixture is entirely post-`HD-06` (it writes `is_blocked` directly), so *none*
# of its blocked cards should return to the stage. A drill that demanded they come back
# would be demanding the guess `0043` refused to make.
RESTORED_BLOCKED="$(psql_ "SELECT count(*) FROM tasks WHERE stage = 'blocked'")"
WITNESSED="$(psql_ "SELECT count(*) FROM tasks WHERE is_blocked")"
if [ "${RESTORED_BLOCKED:-0}" = "0" ] && [ "${WITNESSED:-0}" -gt 0 ]; then
  pass "post-HD-06 blocked cards stayed on their real stage ($WITNESSED still is_blocked)"
  say "         ← this is ADR 0040's stated irreversibility, demonstrated:"
  say "           no legacy_blocked_at means the downgrade correctly does not guess."
elif [ "${RESTORED_BLOCKED:-0}" -gt 0 ]; then
  pass "cards written by 0045 returned to the stage ($RESTORED_BLOCKED)"
else
  fail "blocked cards" "neither on the stage nor flagged — the data was lost"
fi

say ""
say "step 4 — downgrade past 0043: the view tables go, conversation stays"
alem downgrade 0042_knowledge_tables >>"$LOG" 2>&1 && pass "downgrade to 0042" || fail "downgrade to 0042" "see $LOG"
VIEWS_TABLE="$(psql_ "SELECT count(*) FROM information_schema.tables WHERE table_name = 'work_views'")"
[ "$VIEWS_TABLE" = "0" ] && pass "work_views is gone (expected)" || fail "work_views" "still present"
# **`alpha.2`'s data is product data and survives a `beta.1` rollback.** That is one of
# the five guarantees, and it is the one somebody would notice.
MESSAGES_AFTER="$(psql_ "SELECT count(*) FROM task_messages")"
[ "$MESSAGES_AFTER" = "$MESSAGES_BEFORE" ] \
  && pass "conversation intact ($MESSAGES_AFTER messages)" \
  || fail "conversation" "$MESSAGES_BEFORE → $MESSAGES_AFTER"

say ""
say "step 5 — upgrade back to head, data unharmed"
alem upgrade head >>"$LOG" 2>&1 && pass "upgrade head" || fail "upgrade head" "see $LOG"
CARDS_AFTER="$(psql_ "SELECT count(*) FROM tasks")"
[ "$CARDS_AFTER" = "$CARDS_BEFORE" ] \
  && pass "every card survived ($CARDS_AFTER)" \
  || fail "cards" "$CARDS_BEFORE → $CARDS_AFTER"
MESSAGES_FINAL="$(psql_ "SELECT count(*) FROM task_messages")"
[ "$MESSAGES_FINAL" = "$MESSAGES_BEFORE" ] \
  && pass "every message survived ($MESSAGES_FINAL)" \
  || fail "messages" "$MESSAGES_BEFORE → $MESSAGES_FINAL"

say ""
say "step 6 — what the round trip cost, stated rather than implied"
VIEWS_AFTER="$(psql_ "SELECT count(*) FROM work_views")"
say "         saved views: $VIEWS_BEFORE before, $VIEWS_AFTER after"
if [ "$VIEWS_AFTER" = "$VIEWS_BEFORE" ]; then
  pass "views were re-seeded to the same count"
else
  # Not a failure: `0043` seeds the default views on upgrade, and a user's *personal*
  # views are what the export in step 2 exists to restore. Saying so is the point — a
  # drill that reported this as clean would be hiding the reason step 2 is mandatory.
  say "  \033[33mNOTE\033[0m  personal views are not restored by upgrade — restore them from"
  say "         $OUT/work-views-before.tsv. This is why step 2 is not optional."
fi

say ""
if [ "$FAILED" = "0" ]; then
  say "=== rollback drill complete ==="
else
  say "=== rollback drill FAILED — see $LOG ==="
fi
exit "$FAILED"
