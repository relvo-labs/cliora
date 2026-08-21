#!/usr/bin/env bash
# Stop and start the e2e stack's daemon **as the same node**, for the chaos journey
# (`plan/24/03` §4, J5, exit condition 5).
#
#   scripts/cv/daemon-ctl.sh kill          # SIGKILL the whole process group
#   scripts/cv/daemon-ctl.sh start         # launch it again, same config and credentials
#   scripts/cv/daemon-ctl.sh wait-online   # block until Central lists the node online
#
# Reads the handles `scripts/e2e/run-stack.sh` exports (`E2E_DAEMON_*`). Run it inside a
# stack started with `E2E_RUNNER=1`.
#
# **SIGKILL, and the group, not the process** (D75). SIGTERM would take the daemon down
# its graceful path, and a clean shutdown is not a crash — what J5 asserts is that an
# answer survives the daemon *dying*. The group matters because `setsid` made the daemon
# a group leader with the run's child process under it; killing only the daemon leaves an
# orphan still writing events at a parent that no longer exists, which is a different
# question from the one being asked.
set -uo pipefail

: "${E2E_DAEMON_BIN:?not inside a runner-mode stack (E2E_DAEMON_BIN unset)}"
: "${E2E_DAEMON_CONFIG:?E2E_DAEMON_CONFIG unset}"
: "${E2E_DAEMON_CREDENTIALS:?E2E_DAEMON_CREDENTIALS unset}"
: "${E2E_DAEMON_PGID_FILE:?E2E_DAEMON_PGID_FILE unset}"
BASE="${E2E_BASE_URL:-http://127.0.0.1:8000}"
ADMIN_USER="${E2E_ADMIN_USER:-e2e-admin}"
ADMIN_PASS="${E2E_ADMIN_PASSWORD:-e2e-admin-pw}"
LOG="${E2E_DAEMON_LOG:-/dev/null}"

case "${1:-}" in
  kill)
    pgid="$(cat "$E2E_DAEMON_PGID_FILE")"
    [ -n "$pgid" ] || { echo "!! no pgid recorded" >&2; exit 1; }
    kill -9 -- "-$pgid" 2>/dev/null || kill -9 "$pgid" 2>/dev/null || true
    # Wait for it to actually be gone. Returning while the process is still dying would
    # let the journey's next step race a daemon that is still polling.
    for _ in $(seq 1 50); do
      kill -0 -- "-$pgid" 2>/dev/null || { echo "daemon group $pgid is gone"; exit 0; }
      sleep 0.2
    done
    echo "!! daemon group $pgid still alive after 10s" >&2
    exit 1
    ;;
  start)
    setsid env CLIORA_TUNNEL_PROVIDER_COMMAND_FOR_TESTS="${E2E_DAEMON_PROVIDER_COMMAND:-}" \
      CLIORA_FAKECLI_SCRIPT="${CLIORA_FAKECLI_SCRIPT:-${E2E_AGENT_SCRIPT:-}}" \
      "$E2E_DAEMON_BIN" run --config "$E2E_DAEMON_CONFIG" \
      --credentials "$E2E_DAEMON_CREDENTIALS" >>"$LOG" 2>&1 &
    pid=$!
    # The replacement's group, written where teardown and the next `kill` will look. The
    # stack's own PIDS array cannot learn about this process.
    printf '%s\n' "$pid" >"$E2E_DAEMON_PGID_FILE"
    echo "daemon restarted as group $pid"
    ;;
  wait-online)
    token="$(curl -fsS -X POST "$BASE/api/auth/login" -H 'content-type: application/json' \
      -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["tokens"]["access_token"])')"
    for _ in $(seq 1 30); do
      nodes="$(curl -fsS "$BASE/api/nodes" -H "authorization: Bearer $token" 2>/dev/null || echo '[]')"
      online="$(python3 -c 'import json,sys
try: nodes = json.load(sys.stdin)
except Exception: nodes = []
print("1" if any(n.get("status") == "online" for n in nodes) else "")' <<<"$nodes")"
      [ -n "$online" ] && { echo "node online again"; exit 0; }
      sleep 1
    done
    # A restart that never came back has to say so in its own words. Reported as "the
    # turn was never created", it would send the reader looking at Central.
    echo "!! the daemon did not come back online within 30s; agentd.log tail:" >&2
    tail -n 20 "$LOG" >&2 || true
    exit 1
    ;;
  *)
    echo "usage: $0 {kill|start|wait-online}" >&2
    exit 2
    ;;
esac
