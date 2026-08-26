#!/usr/bin/env bash
# Run every alert drill and record whether each alert could actually be triggered (P4-09).
#
# The research brief asks for alerts that "can be triggered in a drill environment and
# handled per the runbook". This script is what makes that a checked claim rather than an
# intention: it brings up a disposable Central with metrics enabled, runs each drill, and
# writes `drills.md` with the trigger time, the metric before and after, and whether the
# runbook's diagnostic step actually produced the number it says it will.
#
# A drill that cannot fire its alert is a FAIL. An alert nobody has ever seen fire is
# indistinguishable from one that is wired up wrong, and the first time you find out is
# during the incident it was supposed to warn you about.
#
#   scripts/p4/drills/run-all.sh [output-dir]     # default artifacts/p4/local
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

# Shared `confirm`, so this orchestrator is held to the same rule as the drills it runs —
# and it needs to be: it creates a database and then deliberately saturates queues, exhausts
# a connection pool and stops a daemon. Asking once for the batch is the point, rather than
# five times in a row (each child then runs with CLIORA_DRILL_YES=1 set below).
# shellcheck source=scripts/p4/drills/_common.sh
. "$ROOT/scripts/p4/drills/_common.sh"
# _common.sh turns on `-e`; turn it back off. Every drill's result has to be recorded, so a
# failing one must not abort the run — a partial report that stops at the first failure is
# exactly the artifact this script exists to avoid.
set +e

confirm "About to run every alert drill against a disposable Central on port ${DRILL_PORT:-8145}.
This creates and drops its own database, and deliberately saturates queues, exhausts the
connection pool and stops a daemon. Do not point it at anything you care about."

OUT="${1:-$ROOT/artifacts/p4/local}"
mkdir -p "$OUT"
# Made absolute immediately. Several commands below run inside `(cd backend && ...)`, and a
# redirection to a *relative* path resolves against `backend/` — so with a relative $OUT the
# log redirect silently failed and the whole subshell died before starting anything. The
# symptom was "Central did not become ready" with no log to explain why. Standalone runs
# passed an absolute path and never saw it; the evidence pack passes a relative one.
OUT="$(cd "$OUT" && pwd)"
REPORT="$OUT/drills.md"
PORT="${DRILL_PORT:-8145}"
TOKEN="drill-scrape-token-0123456789"
DB="cliora_drills_$(date -u +%Y%m%d%H%M%S)"
PG_CONTAINER="${PG_CONTAINER:-cliora-pg}"
PG_USER="${PG_USER:-cliora}"
FAILURES=0

mkdir -p "$OUT"
note() { printf '%s\n' "$*" >>"$REPORT"; }
fail() { FAILURES=$((FAILURES + 1)); note "- **FAIL** — $*"; echo "FAIL: $*" >&2; }
ok()   { note "- ok — $*"; echo "ok: $*"; }

stop_app() {
  pkill -f "uvicorn app.main:app --host 127.0.0.1 --port $PORT" 2>/dev/null
  for _ in $(seq 1 20); do pgrep -f "port $PORT" >/dev/null || break; sleep 0.25; done
}
cleanup() {
  stop_app
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$DB\"" >/dev/null 2>&1
}
trap cleanup EXIT

if ! docker exec "$PG_CONTAINER" true 2>/dev/null; then
  echo "PostgreSQL container '$PG_CONTAINER' is not running" >&2
  exit 2
fi

: >"$REPORT"
note "# Alert drills"
note ""
note "- generated (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
note "- host: $(uname -srm)"
note ""
note "Each drill triggers one alert condition against a **disposable** Central and checks"
note "that the metric the alert rule reads actually moves. Alert *firing* itself is"
note "Prometheus's job and is covered by \`promtool check rules\`; what cannot be checked"
note "statically is whether the signal exists at all, which is what this measures."
note ""

# --- disposable Central with metrics enabled ---
docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
  -c "CREATE DATABASE \"$DB\" OWNER $PG_USER" >/dev/null || { echo "cannot create $DB" >&2; exit 1; }
DB_URL="postgresql+asyncpg://${PG_USER}:cliora@127.0.0.1:5432/${DB}"
ADMIN_PW="Drill-$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"

(cd backend && CLIORA_DATABASE_URL="$DB_URL" uv run --project . alembic upgrade head) \
  >"$OUT/drills-setup.log" 2>&1 || { fail "could not migrate the drill database"; exit 1; }
(cd backend && CLIORA_DATABASE_URL="$DB_URL" uv run --project . python -m app.bootstrap \
  create-admin --username drilladmin --password "$ADMIN_PW") >>"$OUT/drills-setup.log" 2>&1 \
  || fail "could not create the drill admin"

if pgrep -f "port $PORT" >/dev/null; then
  fail "port $PORT is in use; the drills would measure another process"
  exit 1
fi

(cd backend && CLIORA_DATABASE_URL="$DB_URL" \
  CLIORA_METRICS_ENABLED=true CLIORA_METRICS_SCRAPE_TOKEN="$TOKEN" \
  uv run --project . uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$OUT/drills-central.log" 2>&1) &

READY=""
for _ in $(seq 1 60); do
  READY=$(curl -fsS "http://127.0.0.1:$PORT/readyz" 2>/dev/null) && break
  sleep 0.5
done
[ -n "$READY" ] && ok "drill Central is up with metrics enabled" \
                || { fail "drill Central did not start"; exit 1; }

export CLIORA_CENTRAL_URL="http://127.0.0.1:$PORT"
export CLIORA_METRICS_SCRAPE_TOKEN="$TOKEN"
export CLIORA_DRILL_YES=1
export CLIORA_DRILL_ADMIN=drilladmin
export CLIORA_DRILL_PASSWORD="$ADMIN_PW"
# An access token too, so drills that call the API directly do not each have to log in.
CLIORA_ADMIN_TOKEN=$(curl -fsS -X POST "http://127.0.0.1:$PORT/api/auth/login" \
  -H 'content-type: application/json' \
  -d "{\"username\":\"drilladmin\",\"password\":\"$ADMIN_PW\"}" 2>/dev/null \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["tokens"]["access_token"])' 2>/dev/null)
export CLIORA_ADMIN_TOKEN
[ -n "$CLIORA_ADMIN_TOKEN" ] && ok "obtained an admin token for the drills" \
                            || fail "could not obtain an admin token"

# --- run each drill ---
note ""
note "| drill | alert | runbook | result | elapsed |"
note "|---|---|---|---|---:|"

SKIPPED=0

# Three outcomes, not two. A drill whose *prerequisite* is absent — systemd, a real daemon
# process, a published release artifact — has not failed; it has not run, and a host that
# cannot provide those is a normal development machine. Recording that as FAIL would train
# everyone to ignore the report, and recording it as a pass would be a lie. So it is a third
# state, counted separately and named in the verdict.
run_drill() {
  local script="$1" alert="$2" runbook="$3"
  local start elapsed status log
  log="$OUT/drill-${script%.sh}.log"
  echo "==> $script"
  start=$(date +%s)
  if bash "scripts/p4/drills/$script" >"$log" 2>&1; then
    status="triggered"
    echo "ok: $script"
  else
    rc=$?
    if [ "$rc" -eq 77 ] || grep -qiE "^Set CLIORA_|a terminal is required|password is required|not present yet|command not found" "$log"; then
      status="skipped (prerequisite absent)"
      SKIPPED=$((SKIPPED + 1))
      echo "-- skipped: $script"
    else
      status="**FAILED**"
      FAILURES=$((FAILURES + 1))
      echo "FAIL: $script" >&2
    fi
  fi
  elapsed=$(( $(date +%s) - start ))
  note "| \`$script\` | \`$alert\` | [$runbook](../../docs/runbooks/$runbook) | $status | ${elapsed}s |"
}

run_drill heartbeat-loss.sh    NodeHeartbeatLoss      heartbeat-loss.md
run_drill queue-saturation.sh  TerminalQueueSaturated queue-saturation.md
run_drill timeout-surge.sh     DaemonTimeoutSurge     timeout-surge.md
run_drill db-exhaustion.sh     DatabasePoolExhausted  db-exhaustion.md
run_drill update-failure.sh    DaemonUpdateFailed     update-failure.md

note ""
note "## Verdict"
note ""
if [ "$FAILURES" -ne 0 ]; then
  note "**FAIL** — $FAILURES drill(s) failed. An alert that cannot be triggered on demand"
  note "cannot be trusted to fire when it matters; see the per-drill logs in this directory."
elif [ "$SKIPPED" -ne 0 ]; then
  note "**PASS with $SKIPPED skipped.** Nothing failed, but $SKIPPED drill(s) never ran"
  note "because their prerequisites were absent on this host — typically systemd (to stop a"
  note "real \`agentd\`), a connected daemon, or a published release artifact. Those alert"
  note "paths are therefore **unexercised by this run**: read the table above before treating"
  note "it as full coverage, and run the drills job on a host that can provide them."
else
  note "**PASS** — every alert condition could be produced on demand, and each drill's"
  note "runbook diagnostic step returned the metric it claims to."
fi

# Held to the same rule as the individual drills: say what to watch and where the
# procedure lives, so the run leaves the operator somewhere rather than just finishing.
follow_up \
  "all five alert series (see deploy/prometheus/alerts.yml)" \
  "docs/runbooks/ — one per alert, each named in the table above"

echo
echo "report: $REPORT"
[ "$FAILURES" -eq 0 ] || exit 1
