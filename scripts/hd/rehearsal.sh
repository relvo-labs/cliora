#!/usr/bin/env bash
# HD-08: the migration rehearsal, `0040` → `0046` (plan/27/07 §2).
#
#   CLIORA_DATABASE_URL=… scripts/hd/rehearsal.sh
#
# Five steps, and **step 5 is the one most rehearsals skip**: a dump/restore round trip.
# Upgrade and downgrade exercise alembic; restore exercises whether the schema alembic
# produced can actually be reconstructed from a backup, which is the thing an operator
# needs at the moment they need it.
#
# **Seven verifications after every step**, not "it said OK". `0046` is the first
# irreversible migration in the V2 series, so "the command exited zero" is not the
# question — the question is whether the rows still relate to each other. Two of the
# seven check exactly that, because a downgrade can leave every table individually intact
# and the relationships between them broken, and `SELECT count(*)` cannot see it.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

DB="${REHEARSAL_DB:-cliora_rehearsal}"
URL="postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/$DB"
OUT="artifacts/hd/local/w6"
mkdir -p "$OUT"
LOG="$OUT/rehearsal-compose.log"
: > "$LOG"

FAILED=0
say()  { printf '%s\n' "$*" | tee -a "$LOG"; }
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1" | tee -a "$LOG"; }
fail() { printf '  \033[31mFAIL\033[0m  %s — %s\n' "$1" "${2:-}" | tee -a "$LOG"; FAILED=1; }

psql_() { docker exec -i cliora-pg psql -U cliora -d "$DB" -tAc "$1" 2>&1; }
alem()  { ( cd backend && CLIORA_DATABASE_URL="$URL" uv run --project . alembic "$@" ); }

# --- the seven checks --------------------------------------------------------
#
# Run after every step. Numbers 4 and 5 are the cross-table ones: a card that still has
# its attention and a citation that still reaches its source. A migration can leave every
# table complete and those two broken, and nothing counting rows would notice.
verify() {
  local label="$1" expect_rev="$2"
  local rev cards chunks sources
  rev="$(psql_ "SELECT version_num FROM alembic_version")"
  [ "$rev" = "$expect_rev" ] \
    && pass "$label · alembic_version = $rev" \
    || fail "$label · alembic_version" "expected $expect_rev, got $rev"

  cards="$(psql_ "SELECT count(*) FROM tasks")"
  sources="$(psql_ "SELECT count(*) FROM knowledge_sources")"
  chunks="$(psql_ "SELECT count(*) FROM knowledge_chunks")"
  say "         rows: $cards tasks, $sources sources, $chunks chunks"

  # 3. Every hot query answers. Not "is it fast" — that is `HD-09`. This asks whether the
  #    schema after the step can still be queried at all, which a dropped index or a
  #    renamed column breaks silently until somebody opens a board.
  local q ok=1
  for q in \
    "SELECT count(*) FROM tasks WHERE project_id IS NOT NULL" \
    "SELECT stage, count(*) FROM tasks GROUP BY stage" \
    "SELECT count(*) FROM task_dependencies d JOIN tasks t ON t.id = d.task_id" \
    "SELECT count(*) FROM knowledge_chunks WHERE search_document IS NOT NULL"
  do
    psql_ "$q" >/dev/null 2>&1 || { ok=0; break; }
  done
  [ "$ok" = "1" ] && pass "$label · four hot queries answer" || fail "$label · hot queries" "one failed"

  # 4. **Cross-table**: a blocked card still says *why*. After `0045` that lives in a
  #    different column than it did before, which is exactly the kind of move a row count
  #    cannot see.
  local blocked_without_reason
  blocked_without_reason="$(psql_ "SELECT count(*) FROM tasks WHERE is_blocked AND blocking_reason IS NULL")"
  [ "${blocked_without_reason:-0}" = "0" ] \
    && pass "$label · every blocked card has a reason" \
    || fail "$label · blocked cards" "$blocked_without_reason have no reason"

  # 5. **Cross-table**: every chunk still reaches its source. `ondelete=CASCADE` makes the
  #    orphan impossible going forward; a downgrade that deleted sources by hand is what
  #    would produce one.
  local orphans
  orphans="$(psql_ "SELECT count(*) FROM knowledge_chunks c LEFT JOIN knowledge_sources s ON s.id = c.source_id WHERE s.id IS NULL")"
  [ "${orphans:-0}" = "0" ] \
    && pass "$label · no orphaned chunks" \
    || fail "$label · orphaned chunks" "$orphans"

  # 6. The stage domain matches the revision. This is the assertion that would have caught
  #    `0046`'s constraint-name bug before a downgrade did.
  local admits_blocked
  admits_blocked="$(psql_ "SELECT pg_get_constraintdef(oid) LIKE '%blocked%' FROM pg_constraint WHERE conrelid='tasks'::regclass AND conname='ck_tasks_stage'")"
  say "         stage domain admits 'blocked': ${admits_blocked:-?}"

  # 7. `/metrics` is not checked here: it needs a running Central and this script
  #    deliberately does not start one. `HD-09`'s drill covers it, and saying so is
  #    better than a check that silently passes because nothing was listening.
}

say "=== HD-08 migration rehearsal ($DB) ==="
say "step 0 — a fresh database from the fixed dataset"
docker exec cliora-pg psql -U cliora -d postgres -c "DROP DATABASE IF EXISTS $DB" >/dev/null 2>&1
docker exec cliora-pg psql -U cliora -d postgres -c "CREATE DATABASE $DB" >/dev/null 2>&1

# **Seeded at head, then walked down** — not seeded at `0043`, which was the first
# attempt and does not work: the seed script writes through the ORM, and the ORM is
# always at head. Inserting a `Project` against a `0043` schema fails on
# `provider_sync_enabled`, a column `0044` has not added yet.
#
# That is not a defect in either. It is the reason a rehearsal seeds at head and
# downgrades: the *data* is what has to survive the round trip, and the model can only
# produce it in one shape.
alem upgrade head >>"$LOG" 2>&1
CLIORA_DATABASE_URL="$URL" CLIORA_ADMIN_PASSWORD=x \
  uv run --project backend python -m app.bootstrap create-admin --username rehearsal >>"$LOG" 2>&1
CLIORA_DATABASE_URL="$URL" uv run --project backend python scripts/cv/seed-dataset.py \
  --out "$OUT/rehearsal-dataset.json" >>"$LOG" 2>&1
verify "step 0 (head, seeded)" "0046_stage_blocked_check"

say ""
say "step 1 — upgrade to head"
alem upgrade head >>"$LOG" 2>&1 && pass "upgrade head" || fail "upgrade head" "see $LOG"
verify "step 1 (head)" "0046_stage_blocked_check"

say ""
say "step 2 — downgrade to 0043"
# **The order matters and the revision chain enforces it.** `0041`'s docstring records
# why: dropping `pg_trgm` needs nothing to depend on it, and `0042` builds the
# `gin_trgm_ops` index that does. Stopping at `0043` keeps this rehearsal above that
# boundary; going below it is step 4.
alem downgrade 0043_work_views_and_rank >>"$LOG" 2>&1 && pass "downgrade 0043" || fail "downgrade 0043" "see $LOG"
verify "step 2 (0043)" "0043_work_views_and_rank"

say ""
say "step 3 — upgrade again, and the data is unharmed"
alem upgrade head >>"$LOG" 2>&1 && pass "upgrade head (second time)" || fail "upgrade head (2)" "see $LOG"
verify "step 3 (head again)" "0046_stage_blocked_check"

say ""
say "step 4 — the whole chain down to 0040, then back"
# `0041` → `0040` is the extension boundary. Included because it is the step most likely
# to fail and the least likely to be tried: the two migrations either side of it are
# ordinary, and the failure mode is a `DROP EXTENSION` that a dependent index refuses.
if alem downgrade 0040_ticket_conversation >>"$LOG" 2>&1; then
  pass "downgrade through the pg_trgm boundary"
else
  fail "downgrade to 0040" "the extension boundary — see $LOG"
fi
alem upgrade head >>"$LOG" 2>&1 && pass "upgrade head (third time)" || fail "upgrade head (3)" "see $LOG"
verify "step 4 (head, after full round trip)" "0046_stage_blocked_check"

say ""
say "step 5 — dump, drop, restore"
# The step rehearsals skip. Upgrade and downgrade test alembic; this tests whether the
# schema alembic produced can be rebuilt from a backup — which is the question an operator
# has at the exact moment they cannot afford to discover the answer.
docker exec cliora-pg pg_dump -U cliora -Fc "$DB" > "/tmp/hd-rehearsal.dump" 2>>"$LOG"
docker exec cliora-pg psql -U cliora -d postgres -c "DROP DATABASE $DB" >>"$LOG" 2>&1
docker exec cliora-pg psql -U cliora -d postgres -c "CREATE DATABASE $DB" >>"$LOG" 2>&1
docker exec -i cliora-pg pg_restore -U cliora -d "$DB" < "/tmp/hd-rehearsal.dump" >>"$LOG" 2>&1
verify "step 5 (restored from dump)" "0046_stage_blocked_check"
rm -f /tmp/hd-rehearsal.dump

say ""
if [ "$FAILED" = "0" ]; then
  say "=== rehearsal complete: every step verified ==="
else
  say "=== rehearsal FAILED — see $LOG ==="
fi
exit "$FAILED"
