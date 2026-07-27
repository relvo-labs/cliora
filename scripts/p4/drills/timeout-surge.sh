#!/usr/bin/env bash
# Drill: ClioraDaemonRequestTimeoutSurge.
#
# Suspends the daemon process with SIGSTOP: the socket stays open, so Central keeps
# relaying and every request times out. That is a truer reproduction than stopping the
# service, which would present as NODE_OFFLINE instead.
. "$(dirname "$0")/_common.sh"

UNIT="${CLIORA_DRILL_UNIT:-agentd}"
REQUESTS="${CLIORA_DRILL_REQUESTS:-12}"
ADMIN_TOKEN="${CLIORA_ADMIN_TOKEN:-}"
SESSION_ID="${CLIORA_DRILL_SESSION_ID:-}"

if [ -z "$ADMIN_TOKEN" ] || [ -z "$SESSION_ID" ]; then
  echo "Set CLIORA_ADMIN_TOKEN and CLIORA_DRILL_SESSION_ID (a session on this node)." >&2
  exit 1
fi

confirm "This SIGSTOPs the '${UNIT}' daemon so its requests time out, then issues
${REQUESTS} file-listing requests. The daemon is resumed at the end."

MAIN_PID=$(systemctl show -p MainPID --value "${UNIT}")
if [ -z "${MAIN_PID}" ] || [ "${MAIN_PID}" = "0" ]; then
  echo "Could not find the ${UNIT} main PID; is it running?" >&2
  exit 1
fi

banner "Before"
metric daemon_request_timeout_total

banner "Suspending PID ${MAIN_PID}"
sudo kill -STOP "${MAIN_PID}"
# shellcheck disable=SC2064
trap "echo; echo 'Resuming PID ${MAIN_PID}'; sudo kill -CONT ${MAIN_PID}" EXIT

for _ in $(seq "${REQUESTS}"); do
  curl -s -o /dev/null -w '%{http_code} ' --max-time 30 \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    "${CENTRAL}/api/sessions/${SESSION_ID}/files/tree?path=." || true
done
echo

banner "After"
metric daemon_request_timeout_total

follow_up "cliora_daemon_request_timeout_total (check the 'type' label)" \
  "docs/runbooks/timeout-surge.md"
