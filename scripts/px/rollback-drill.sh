#!/usr/bin/env bash
# PX-66: the rollback drill (exit conditions 14 and 20, plan/26/02 §6).
#
# **`0043` is reversible and not lossless**, and after D117 removed the version flag
# `downgrade` is the *only* rollback path there is. So the drill is not "does downgrade
# work" — it is:
#
#   1. **export `work_views` first.** A downgrade drops the table, and a saved view is
#      product data somebody made. The drill exists to make that step a habit rather than
#      a discovery.
#   2. downgrade to `0042`, and check the four columns and the table are gone;
#   3. upgrade again, and check the seeds and the rank backfill came back;
#   4. re-import the export, and check the views are the same views.
#
#   CLIORA_DATABASE_URL=… scripts/px/rollback-drill.sh [out-dir]
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

: "${CLIORA_DATABASE_URL:?set CLIORA_DATABASE_URL}"
OUT="${1:-artifacts/px/local/rollback}"
mkdir -p "$OUT"
FAILED=0

step() { printf '\n\033[1m%s\033[0m\n' "$1"; }
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s%s\n' "$1" "${2:+ — $2}"; FAILED=1; }

probe() {
  uv run --project backend python - "$1" <<'PY'
import asyncio
import os
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> int:
    engine = create_async_engine(os.environ["CLIORA_DATABASE_URL"])
    async with engine.connect() as connection:
        if sys.argv[1] == "views":
            rows = (
                await connection.execute(
                    sa.text(
                        "SELECT project_id::text, name, layout, scope, is_default, "
                        "filter_json::text FROM work_views WHERE deleted_at IS NULL "
                        "ORDER BY project_id, name"
                    )
                )
            ).all()
            for row in rows:
                print("\t".join("" if value is None else str(value) for value in row))
        elif sys.argv[1] == "schema":
            columns = (
                await connection.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tasks' AND column_name IN "
                        "('rank','is_blocked','blocking_reason','blocking_message') "
                        "ORDER BY column_name"
                    )
                )
            ).scalars()
            tables = (
                await connection.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_name = 'work_views'"
                    )
                )
            ).scalar_one()
            print(f"columns={','.join(columns)} work_views={tables}")
        elif sys.argv[1] == "ranks":
            nulls = (
                await connection.execute(
                    sa.text("SELECT count(*) FROM tasks WHERE rank IS NULL")
                )
            ).scalar_one()
            print(f"null_ranks={nulls}")
    await engine.dispose()
    return 0


raise SystemExit(asyncio.run(main()))
PY
}

step "1. export work_views (the step the drill exists to make habitual)"
if probe views > "$OUT/work-views-before.tsv"; then
  pass "exported $(wc -l < "$OUT/work-views-before.tsv") view(s) to $OUT/work-views-before.tsv"
else
  fail "export" "could not read work_views"
fi

step "2. downgrade to 0042"
if (cd backend && uv run --project . alembic downgrade 0042_knowledge_tables >/dev/null 2>&1); then
  after="$(probe schema)"
  echo "  $after"
  if [ "$after" = "columns= work_views=0" ]; then
    pass "the four columns and work_views are gone"
  else
    fail "downgrade left something behind" "$after"
  fi
else
  fail "downgrade" "alembic refused"
fi

step "3. upgrade again"
if (cd backend && uv run --project . alembic upgrade head >/dev/null 2>&1); then
  after="$(probe schema)"
  ranks="$(probe ranks)"
  echo "  $after $ranks"
  if [ "$after" = "columns=blocking_message,blocking_reason,is_blocked,rank work_views=1" ] \
     && [ "$ranks" = "null_ranks=0" ]; then
    pass "the four columns, work_views and the rank backfill are back"
  else
    fail "upgrade did not restore the shape" "$after $ranks"
  fi
else
  fail "upgrade" "alembic refused"
fi

step "4. compare the views"
probe views > "$OUT/work-views-after.tsv"
if diff -q "$OUT/work-views-before.tsv" "$OUT/work-views-after.tsv" >/dev/null; then
  pass "the seeded views are identical; **a view somebody created by hand would not be**"
else
  # Expected whenever a project has views beyond the five seeds. The drill's whole point
  # is that this line is where somebody notices.
  fail "the views differ" \
    "$(diff "$OUT/work-views-before.tsv" "$OUT/work-views-after.tsv" | head -3 | tr '\n' ' ')"
fi

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  echo "rollback drill passed — see $OUT"
else
  echo "rollback drill FAILED"
fi
exit "$FAILED"
