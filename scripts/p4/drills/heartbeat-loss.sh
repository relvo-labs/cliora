#!/usr/bin/env bash
# Drill: ClioraNodeHeartbeatLoss / ClioraFleetOffline.
#
# Stops the daemon on this node. The node keeps its DB row and its tmux sessions, so this
# also demonstrates the property the runbook promises: **stopping the daemon does not
# stop the CLI sessions**. Check `tmux ls` before and after.
. "$(dirname "$0")/_common.sh"

UNIT="${CLIORA_DRILL_UNIT:-agentd}"

if ! systemctl cat "${UNIT}" >/dev/null 2>&1; then
  echo "-- skipped: ${UNIT}.service is not installed on this host"
  exit 77
fi

confirm "This stops the '${UNIT}' service on THIS machine. Terminal streaming will break;
running CLI sessions will NOT be affected."

banner "Before"
metric active_daemon_connections
metric online_nodes
tmux ls 2>/dev/null || echo "(no tmux sessions on this host)"

banner "Stopping ${UNIT}"
sudo systemctl stop "${UNIT}"
echo "Stopped. The heartbeat gap must exceed node_online_within_seconds (30s) before"
echo "the node leaves 'online', then 2 more minutes for the alert's for-duration."

follow_up "cliora_online_nodes < cliora_active_daemon_connections" "docs/runbooks/heartbeat-loss.md"

banner "Restore"
echo "sudo systemctl start ${UNIT} && sudo agentd doctor"
echo "Then confirm tmux sessions are still listed and reattachable."
