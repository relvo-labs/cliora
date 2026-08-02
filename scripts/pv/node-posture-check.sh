#!/usr/bin/env bash
# GATE-PV-NODE-POSTURE — the three facts this change is about, measured on a node.
#
#   scripts/pv/node-posture-check.sh [output-file]
#
# Run this on an enrolled node (as the service user, or with sudo for the unit read).
# Everything it prints is an observation, not an assertion about intent: the point is
# that "codex has no sandbox", "the terminal scrolls" and "sudo works" are claims the
# console makes to users, and they have to be checkable against the machine.
#
# It is release-triggered rather than part of `make check` because it needs a real node
# — and, following GATE-TUNNEL-PROVIDER, its absence is recorded rather than assumed.
set -uo pipefail

OUT="${1:-/dev/stdout}"
SOCKET="cliora"
FLAG="--dangerously-bypass-approvals-and-sandbox"

value() { printf '%-24s: %s\n' "$1" "$2" >>"$OUT"; }

: >"$OUT"
{
  echo "# cliora node posture (plan/12, ADR 0023)"
  echo "generated_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -srm)"
} >>"$OUT"

# --- scrolling (PV-04) -------------------------------------------------------
value "tmux version" "$(tmux -V 2>/dev/null || echo 'not installed')"
session="$(tmux -L "$SOCKET" list-sessions -F '#{session_name}' 2>/dev/null | head -n1)"
if [ -n "$session" ]; then
  value "tmux socket" "$SOCKET ($(tmux -L "$SOCKET" list-sessions 2>/dev/null | wc -l) session(s))"
  value "history_limit" "$(tmux -L "$SOCKET" display-message -p -t "$session" '#{history_limit}' 2>/dev/null) (want >= 5000)"
  value "mouse" "$(tmux -L "$SOCKET" show-options -gv mouse 2>/dev/null) (want on)"
  value "status" "$(tmux -L "$SOCKET" show-options -gv status 2>/dev/null) (want off)"
else
  value "tmux socket" "$SOCKET has no sessions — start one first, these are per-pane facts"
fi
# Sessions left behind by a daemon that predates the dedicated socket. Not an error;
# they are simply no longer served, and the runbook says how to clear them.
legacy="$(tmux list-sessions -F '#{session_name}' 2>/dev/null | grep -c '^cliora-' || true)"
value "legacy default socket" "${legacy:-0} cliora-* session(s)"

# --- sandbox (PV-03) --------------------------------------------------------
if command -v codex >/dev/null 2>&1; then
  value "codex version" "$(codex --version 2>&1 | head -n1)"
  if codex --help 2>&1 | grep -q -- "$FLAG"; then
    value "codex flag" "supported"
  else
    # The console will show the sandbox as enforced for this node. That is correct,
    # and it is the case a reader of this file needs to be able to tell apart from
    # "somebody turned the bypass off".
    value "codex flag" "NOT supported by this build — console will show sandbox=enforced"
  fi
  value "codex argv (live)" "$(ps -o args= -C codex 2>/dev/null | head -n1 || echo 'no codex process running')"
else
  value "codex" "not installed on this node"
fi
value "config sandbox_bypass" "$(grep -A3 '^  codex:' /etc/agentd/config.yaml 2>/dev/null | grep sandbox_bypass || echo 'unreadable (need sudo?)')"

# --- privileged terminal (PV-05) --------------------------------------------
value "NoNewPrivs (this shell)" "$(grep -m1 '^NoNewPrivs' /proc/self/status 2>/dev/null | awk '{print $2}')"
if sudo -n true 2>/dev/null; then
  value "sudo -n true" "succeeds (uid=$(sudo -n id -u 2>/dev/null))"
else
  value "sudo -n true" "fails: $(sudo -n true 2>&1 | head -n1)"
fi
value "sudoers drop-in" "$([ -f /etc/sudoers.d/60-agentd ] && stat -c '%n mode=%a owner=%U' /etc/sudoers.d/60-agentd || echo absent)"
# These two lines belong together: the posture is "non-root but able to escalate", and
# either line alone tells half the story.
value "agentd service user" "$(systemctl show -p User --value agentd 2>/dev/null || echo 'systemd unavailable')"
value "agentd running as" "$(ps -o user= -C agentd 2>/dev/null | head -n1 || echo 'not running')"
value "unit NoNewPrivileges" "$(grep -c '^NoNewPrivileges=true' /etc/systemd/system/agentd.service 2>/dev/null || echo 'unreadable')"

echo "" >>"$OUT"
echo "agentd doctor:" >>"$OUT"
agentd doctor 2>&1 | sed 's/^/  /' >>"$OUT" || true
