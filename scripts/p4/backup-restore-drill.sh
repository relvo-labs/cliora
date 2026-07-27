#!/usr/bin/env bash
# Backup / restore drill (P4-12).
#
# Proves three things about a real dump of a real database, not about the code that
# writes it:
#
#   1. **it restores.** Roles, users, nodes, sessions, audit rows, metric samples and
#      favourites all come back with the same counts and the same content, into a fresh
#      database, and Central starts against it and reports /readyz ready.
#   2. **the schema version travels with the data.** `alembic current` on the restored
#      database matches head. A dump that restores into a schema the application does not
#      expect is not a backup, it is a puzzle for whoever is holding the pager.
#   3. **it contains no terminal output, file content, or credential.** This is the one
#      the research brief asks for explicitly, and it is the only place the data-model
#      promise ("PostgreSQL never stores terminal bytes", ADR 0004) is checked against
#      the artifact that actually leaves the building. Code comments cannot be grepped by
#      an auditor; a dump can.
#
# Usage:
#   scripts/p4/backup-restore-drill.sh [output-dir]      # default artifacts/p4/local
#
# Requires: docker (PostgreSQL container), uv. Creates and drops two throwaway databases
# and never touches an existing one — a drill that writes to a shared database is how a
# later, unrelated test starts failing mysteriously.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OUT="${1:-$ROOT/artifacts/p4/local}"
mkdir -p "$OUT"
# Made absolute immediately. Several commands below run inside `(cd backend && ...)`, and a
# redirection to a *relative* path resolves against `backend/` — so with a relative $OUT the
# log redirect silently failed and the whole subshell died before starting anything. The
# symptom was "Central did not become ready" with no log to explain why. Standalone runs
# passed an absolute path and never saw it; the evidence pack passes a relative one.
OUT="$(cd "$OUT" && pwd)"
PG_CONTAINER="${PG_CONTAINER:-cliora-pg}"
PG_USER="${PG_USER:-cliora}"
PG_PASSWORD="${PG_PASSWORD:-cliora}"
PG_PORT="${PG_PORT:-5432}"
# Defined up here because `cleanup`/`stop_app` reference it from the EXIT trap.
PORT="${DRILL_PORT:-8134}"
STAMP="$(date -u +%Y%m%d%H%M%S)"
SOURCE_DB="cliora_drill_src_${STAMP}"
TARGET_DB="cliora_drill_dst_${STAMP}"
DUMP="$OUT/backup-${STAMP}.sql"
REPORT="$OUT/backup-restore.md"
FAILURES=0

mkdir -p "$OUT"

note() { printf '%s\n' "$*" >>"$REPORT"; }
fail() { FAILURES=$((FAILURES + 1)); note "- **FAIL** — $*"; echo "FAIL: $*" >&2; }
ok()   { note "- ok — $*"; echo "ok: $*"; }

psql_db() { docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$1" -qtA -v ON_ERROR_STOP=1; }
url_for() { echo "postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/$1"; }

# Killed by port pattern, not by a stored pid. `uv run uvicorn ...` inside a subshell means
# the pid `$!` yields is the *subshell*, so killing it leaves uvicorn holding the port and
# a live connection to the database this script is about to drop. The first version did
# exactly that, and the next run's readiness probe was then answered by the previous run's
# server — still healthy, still holding the previous run's admin password. The credential
# check failed for a reason that had nothing to do with the restore, and PostgreSQL had
# quietly refused to drop the database because of the surviving connection.
stop_app() {
  pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $PORT" 2>/dev/null
  for _ in $(seq 1 20); do
    pgrep -f "port $PORT" >/dev/null || break
    sleep 0.25
  done
}

cleanup() {
  stop_app
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$SOURCE_DB\"" \
    -c "DROP DATABASE IF EXISTS \"$TARGET_DB\"" >/dev/null 2>&1
}
trap cleanup EXIT

if ! docker exec "$PG_CONTAINER" true 2>/dev/null; then
  echo "PostgreSQL container '$PG_CONTAINER' is not running" >&2
  exit 2
fi

: >"$REPORT"
note "# Backup / restore drill"
note ""
note "- generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
note "- host: $(uname -srm)"
note "- pg_dump: $(docker exec "$PG_CONTAINER" pg_dump --version | head -1)"
note "- server: $(docker exec "$PG_CONTAINER" postgres --version | head -1)"
note "- source db: \`$SOURCE_DB\` → dump → target db: \`$TARGET_DB\`"
note ""

# --------------------------------------------------------------------------- #
# 1. Build a source database with recognisable data in every table that matters
# --------------------------------------------------------------------------- #
note "## 1. Seed"
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
  -c "CREATE DATABASE \"$SOURCE_DB\" OWNER $PG_USER" >/dev/null || {
  echo "could not create $SOURCE_DB" >&2; exit 1; }

(cd backend && CLIORA_DATABASE_URL="$(url_for "$SOURCE_DB")" \
  uv run --project . alembic upgrade head) >"$OUT/seed-migrate.log" 2>&1 \
  && ok "migrations applied to the source database" \
  || fail "could not migrate the source database (see seed-migrate.log)"

ADMIN_PW="Drill-$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
(cd backend && CLIORA_DATABASE_URL="$(url_for "$SOURCE_DB")" \
  uv run --project . python -m app.bootstrap create-admin \
    --username drilladmin --password "$ADMIN_PW") >>"$OUT/seed-migrate.log" 2>&1 \
  && ok "admin user created" || fail "could not create the admin user"

# Deliberately distinctive literals. The leakage scan below looks for the *absence* of
# terminal-shaped and secret-shaped content; these markers prove the scan is looking at a
# dump that really does contain this deployment's data, so an empty dump cannot pass it.
psql_db "$SOURCE_DB" <<'SQL' >/dev/null
INSERT INTO nodes (id,name,hostname,os,os_version,architecture,daemon_version,run_user,status,metadata,is_enabled,registered_at,last_seen_at)
VALUES ('dd000000-0000-0000-0000-000000000001','drill-node','drill.host','linux','6.0','amd64','0.1.0','agentd','online','{}',true,now(),now());
INSERT INTO node_workspace_roots (id,node_id,path,is_enabled)
VALUES (gen_random_uuid(),'dd000000-0000-0000-0000-000000000001','/srv/drill-workspaces',true);
INSERT INTO node_metric_samples (id,node_id,sampled_at,cpu_usage,memory_usage,load_average,disk_usage,daemon_uptime,active_sessions)
VALUES (gen_random_uuid(),'dd000000-0000-0000-0000-000000000001',now(),12.5,34.5,0.7,56.5,3600,2);
INSERT INTO terminal_sessions (id,node_id,user_id,name,runtime,workspace,status,rows,columns,created_at)
SELECT 'dd000000-0000-0000-0000-0000000000a1','dd000000-0000-0000-0000-000000000001',u.id,'drill-session','claude','/srv/drill-workspaces/proj','exited',24,80,now()
FROM users u WHERE u.username='drilladmin';
INSERT INTO workspace_favorites (id,user_id,node_id,path,display_name,created_at)
SELECT gen_random_uuid(),u.id,'dd000000-0000-0000-0000-000000000001','/srv/drill-workspaces/proj','Drill Project',now()
FROM users u WHERE u.username='drilladmin';
INSERT INTO audit_logs (id,action,user_id,node_id,session_id,metadata,created_at)
SELECT gen_random_uuid(),'session.create',u.id,'dd000000-0000-0000-0000-000000000001','dd000000-0000-0000-0000-0000000000a1','{"runtime":"claude"}',now()
FROM users u WHERE u.username='drilladmin';
SQL
[ $? -eq 0 ] && ok "seeded nodes, roots, metric samples, sessions, favourites and audit rows" \
             || fail "could not seed the source database"

declare -A COUNTS
for table in roles users nodes node_workspace_roots node_metric_samples terminal_sessions workspace_favorites audit_logs; do
  COUNTS[$table]=$(psql_db "$SOURCE_DB" <<<"SELECT count(*) FROM $table;")
done
note ""
note "| table | source rows |"
note "|---|---:|"
for table in "${!COUNTS[@]}"; do note "| \`$table\` | ${COUNTS[$table]} |"; done
note ""

# Counts are captured *after* seeding, so a seed that failed half way would make every
# count comparison below pass against zero — which is exactly what happened the first
# time this ran (a wrong column name aborted the insert block). Every table the drill
# claims to verify must actually have rows.
for table in "${!COUNTS[@]}"; do
  [ "${COUNTS[$table]}" -gt 0 ] 2>/dev/null \
    || fail "\`$table\` is empty in the source database: its restore check would be vacuous"
done

# --------------------------------------------------------------------------- #
# 2. Dump
# --------------------------------------------------------------------------- #
note "## 2. Dump"
DUMP_CMD="pg_dump -U $PG_USER -d $SOURCE_DB --no-owner --no-privileges"
note ""
note '```'
note "docker exec $PG_CONTAINER $DUMP_CMD > $(basename "$DUMP")"
note '```'
START=$(date +%s)
if docker exec "$PG_CONTAINER" $DUMP_CMD >"$DUMP" 2>"$OUT/dump.err"; then
  ok "dump written ($(wc -c <"$DUMP") bytes, $(( $(date +%s) - START ))s)"
else
  fail "pg_dump failed (see dump.err)"
fi

# --------------------------------------------------------------------------- #
# 3. Restore into a brand-new database
# --------------------------------------------------------------------------- #
note ""
note "## 3. Restore"
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
  -c "CREATE DATABASE \"$TARGET_DB\" OWNER $PG_USER" >/dev/null \
  && ok "empty target database created" || fail "could not create the target database"

if docker exec -i "$PG_CONTAINER" psql -U "$PG_USER" -d "$TARGET_DB" -q \
      >"$OUT/restore.log" 2>&1 <"$DUMP"; then
  ok "dump restored"
else
  fail "restore reported errors (see restore.log)"
fi

# --------------------------------------------------------------------------- #
# 4. Verify: counts, content, schema version, and a live application
# --------------------------------------------------------------------------- #
note ""
note "## 4. Verification"
for table in "${!COUNTS[@]}"; do
  restored=$(psql_db "$TARGET_DB" <<<"SELECT count(*) FROM $table;")
  if [ "$restored" = "${COUNTS[$table]}" ]; then
    ok "\`$table\`: ${COUNTS[$table]} rows restored"
  else
    fail "\`$table\`: expected ${COUNTS[$table]} rows, restored $restored"
  fi
done

# Permissions are the part a count cannot check: three roles each with their action list
# intact. A restore that brought back the rows but flattened `permissions` would leave a
# system where everyone can do everything.
for role in Admin Developer Viewer; do
  actions=$(psql_db "$TARGET_DB" <<<"SELECT jsonb_array_length(permissions->'actions') FROM roles WHERE name='$role';")
  source_actions=$(psql_db "$SOURCE_DB" <<<"SELECT jsonb_array_length(permissions->'actions') FROM roles WHERE name='$role';")
  if [ -n "$actions" ] && [ "$actions" = "$source_actions" ]; then
    ok "role \`$role\` restored with $actions actions"
  else
    fail "role \`$role\`: expected $source_actions actions, restored '${actions:-none}'"
  fi
done

fav=$(psql_db "$TARGET_DB" <<<"SELECT path FROM workspace_favorites LIMIT 1;")
[ "$fav" = "/srv/drill-workspaces/proj" ] \
  && ok "favourite content restored verbatim (\`$fav\`)" \
  || fail "favourite content wrong after restore: '${fav:-none}'"

current=$(cd backend && CLIORA_DATABASE_URL="$(url_for "$TARGET_DB")" \
  uv run --project . alembic current 2>/dev/null | tail -1)
head_rev=$(cd backend && uv run --project . alembic heads 2>/dev/null | head -1)
if [ -n "$current" ] && [ "${current%% *}" = "${head_rev%% *}" ]; then
  ok "restored schema is at head (\`${current%% *}\`)"
else
  fail "restored schema '${current:-unknown}' does not match head '${head_rev:-unknown}'"
fi

# The end-to-end check: the application itself, against the restored database.
# The port must be free first. If something else is listening, the probes below would be
# answered by that something else and a green result would mean nothing.
if pgrep -f "port $PORT" >/dev/null; then
  fail "port $PORT is already in use; the readiness and login checks would be answered by another process"
else
(cd backend && CLIORA_DATABASE_URL="$(url_for "$TARGET_DB")" \
  uv run --project . uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$OUT/restored-app.log" 2>&1) &
APP_PID=$!
READY=""
for _ in $(seq 1 40); do
  body=$(curl -fsS "http://127.0.0.1:$PORT/readyz" 2>/dev/null) && READY="$body" && break
  sleep 0.5
done
if [ -n "$READY" ] && grep -q '"status":"ready"' <<<"$READY"; then
  ok "Central started against the restored database and reports ready: \`$READY\`"
  login=$(curl -fsS -X POST "http://127.0.0.1:$PORT/api/auth/login" \
    -H 'content-type: application/json' \
    -d "{\"username\":\"drilladmin\",\"password\":\"$ADMIN_PW\"}" 2>/dev/null)
  grep -q access_token <<<"$login" \
    && ok "the restored admin credential still authenticates" \
    || fail "the restored admin credential does not authenticate"
else
  fail "Central did not become ready against the restored database: '${READY:-no response}'"
fi
fi
stop_app

# --------------------------------------------------------------------------- #
# 5. Leakage scan on the dump itself
# --------------------------------------------------------------------------- #
note ""
note "## 5. Leakage scan of the dump"
note ""
note "Run against the dump file, not the source tree. This is where the data-model"
note "promise — PostgreSQL holds no terminal output and no file content (ADR 0004) — is"
note "checked against the artifact that actually leaves the building."
note ""

scan() {
  local label="$1" pattern="$2" hits
  hits=$(grep -aEc "$pattern" "$DUMP" 2>/dev/null || true)
  hits=${hits:-0}
  if [ "$hits" = "0" ]; then
    ok "no $label"
  else
    fail "$label found in the dump ($hits matching line(s)) — pattern: \`$pattern\`"
  fi
}

# ANSI CSI sequences are the signature of captured terminal output. A single stray escape
# could be legitimate text, so this looks for three or more on one line.
scan "terminal control sequences" $'(\x1b\\[[0-9;]*[A-Za-z].*){3,}'
scan "Ed25519 or RSA private keys" '-----BEGIN [A-Z ]*PRIVATE KEY-----'
scan "JWTs" 'eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.'
scan "bearer tokens" 'Bearer [A-Za-z0-9._-]{16,}'
scan "database connection strings with credentials" 'postgres(ql)?(\+[a-z]+)?://[^:@ ]+:[^@ ]+@'
# The seeded password is a real secret this deployment holds. Argon2 hashes are expected
# and fine; the plaintext must not appear anywhere.
scan "the plaintext admin password" "$ADMIN_PW"
# Sanity check in the other direction: the scan must be reading a dump that does contain
# this deployment's data. Otherwise an empty file would pass every check above.
if grep -aq 'drill-node' "$DUMP"; then
  ok "the scan ran against a dump that does contain this deployment's data"
else
  fail "the dump does not contain the seeded data — every clean scan above is vacuous"
fi
# Password hashes SHOULD be present (they are how login works) and must be Argon2id.
if grep -aq '\$argon2id\$' "$DUMP"; then
  ok "password hashes are Argon2id (present, as expected, and not reversible)"
else
  fail "no Argon2id hash found: passwords may be stored in a weaker form"
fi

note ""
note "## Verdict"
note ""
if [ "$FAILURES" -eq 0 ]; then
  note "**PASS** — restore verified and the dump contains no terminal output, file"
  note "content, or plaintext credential."
else
  note "**FAIL** — $FAILURES check(s) failed. See the entries above."
fi
note ""
note "Retention, frequency and the ordering against the P4-04 retention prune are in"
note "\`docs/runbooks/backup-restore.md\`."

echo
echo "report: $REPORT"
[ "$FAILURES" -eq 0 ] || exit 1
