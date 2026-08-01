package install

import (
	"fmt"
	"strings"
)

// UnitParams are the substitutions for the systemd unit template.
type UnitParams struct {
	User       string
	BinaryPath string
	ConfigPath string
	// PrivilegedTerminal drops NoNewPrivileges so sudo works inside the system
	// terminal (ADR 0023). It is a posture switch, not a tuning knob: with it set,
	// the ceiling of the shell runtime is root on this machine. The service itself
	// still runs as User — EnsureNonRoot is unchanged — and that is not cosmetic:
	// it keeps file ownership, the update health check's identity assumptions and
	// the OS-side sudo record (/var/log/auth.log) intact. See plan/12/00 D8.
	PrivilegedTerminal bool
}

// hardeningPrivileged replaces the NoNewPrivileges line on a privileged node. The
// directive is commented out rather than deleted on purpose: an absent hardening
// option reads as an oversight to the next person reviewing this unit, they add it
// back, and the symptom is "sudo stopped working" with nothing pointing at the
// change.
const hardeningPrivileged = `# NoNewPrivileges is deliberately NOT set on this node: the system terminal is
# allowed to escalate with sudo (ADR 0023, /etc/sudoers.d/60-agentd). Setting it
# would silently take sudo away — no_new_privs disables setuid, which is what sudo
# needs. To revoke the posture, run: agentd posture --privileged-terminal=false`

// UnitFile renders the systemd unit (ADR 0011 / tech §8.1). The service runs as
// the requested non-root user (SEC-007) and hardens with NoNewPrivileges and
// PrivateTmp. PrivateHome is deliberately NOT set: it would hide the user's CLI
// config and workspaces that the runtimes need. TERM is pinned because systemd
// starts services without one, and a TERM-less tmux client refuses to attach.
// RuntimeDirectory gives the non-root service a private /run/agentd, which is
// where the generated tmux config lives (PV-04).
func UnitFile(p UnitParams) string {
	hardening := "NoNewPrivileges=true"
	if p.PrivilegedTerminal {
		hardening = hardeningPrivileged
	}
	return fmt.Sprintf(`[Unit]
Description=Cliora node daemon (agentd)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=%[1]s
Group=%[1]s
ExecStart=%[2]s run --config %[3]s
Environment=TERM=xterm-256color
Restart=always
RestartSec=5
LimitNOFILE=65535
RuntimeDirectory=agentd
%[4]s
PrivateTmp=true

[Install]
WantedBy=multi-user.target
`, p.User, p.BinaryPath, p.ConfigPath, hardening)
}

// UnitIsPrivileged reports whether an already-installed unit grants the privileged
// posture. Read from the file rather than inferred from config, because the unit is
// the thing systemd acts on: `agentd posture` and `agentd doctor` both need to
// answer "what is actually installed here", not "what did we intend".
func UnitIsPrivileged(unit string) bool {
	for _, line := range strings.Split(unit, "\n") {
		if strings.TrimSpace(line) == "NoNewPrivileges=true" {
			return false
		}
	}
	return true
}
