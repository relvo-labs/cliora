package install

import "fmt"

// UnitParams are the substitutions for the systemd unit template.
type UnitParams struct {
	User       string
	BinaryPath string
	ConfigPath string
}

// UnitFile renders the systemd unit (ADR 0011 / tech §8.1). The service runs as
// the requested non-root user (SEC-007) and hardens with NoNewPrivileges and
// PrivateTmp. PrivateHome is deliberately NOT set: it would hide the user's CLI
// config and workspaces that the runtimes need. TERM is pinned because systemd
// starts services without one, and a TERM-less tmux client refuses to attach.
func UnitFile(p UnitParams) string {
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
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
`, p.User, p.BinaryPath, p.ConfigPath)
}
