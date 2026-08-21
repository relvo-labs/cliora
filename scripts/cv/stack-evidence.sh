#!/usr/bin/env bash
# The half of `scripts/cv/evidence.sh` that needs a running stack: the seven journeys, the
# 0.12.0 compatibility check, and the five measurements (`CE-03`).
#
#   scripts/cv/stack-evidence.sh
#
# **One stack for all of it**, deliberately. Three stacks would triple the setup, and
# worse: each step's "is this database quiet" guard would be answering for a database an
# earlier step had already filled, so the guard that exists to stop contention being
# recorded as latency would stop working (`plan/23/10` §5).
#
# The steps themselves are in `_stack-evidence-inner.sh` — a second file rather than a
# quoted string, because the inner script is what runs *inside* the stack and nesting it
# in `bash -c '…'` made every apostrophe in a comment a syntax error.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

export PATH="$HOME/.local/bin:/usr/local/go/bin:$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"
DB_NAME="${CE_E2E_DB:-cliora_e2e}"
export CLIORA_DATABASE_URL="${CE_E2E_URL:-postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/$DB_NAME}"
export CLIORA_TEST_DATABASE_URL="$CLIORA_DATABASE_URL"
mkdir -p artifacts/cv/local/journeys

# A fresh database, by whichever route exists: `dropdb` on a host with the client tools,
# `docker exec` for this repo's compose container, and otherwise a direct connection —
# CI runners have PostgreSQL as a *service* with no `psql` installed, and refusing there
# would mean this script only ever ran on a laptop, which is what `CE-08` set out to change.
echo "==> resetting $DB_NAME"
if command -v dropdb >/dev/null 2>&1; then
  dropdb --if-exists "$DB_NAME" && createdb "$DB_NAME"
elif docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${CE_PG_CONTAINER:-cliora-pg}"; then
  docker exec "${CE_PG_CONTAINER:-cliora-pg}" psql -U cliora -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME';" \
    -c "DROP DATABASE IF EXISTS $DB_NAME;" -c "CREATE DATABASE $DB_NAME OWNER cliora;" >/dev/null
else
  uv run --project backend python scripts/cv/reset_database.py "$CLIORA_DATABASE_URL"
fi

E2E_RUNNER=1 E2E_CONVERSATION=1 exec scripts/e2e/run-stack.sh scripts/cv/_stack-evidence-inner.sh
