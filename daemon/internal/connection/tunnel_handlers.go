package connection

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/tunnel"
)

// Port-forwarding handlers (P11, ADR 0022). Central asks for a tunnel; the supervisor runs
// it; this file is only the translation between the two.
//
// Two rules run through everything here:
//
//   - The credential arrives in the request and is never written anywhere. It is not logged,
//     not echoed in an error, and not put in a pid file. The only place it goes is the
//     supervisor, which puts it in the child's argv (the provider's interface) and nowhere
//     else.
//   - The node's own configuration wins. A veto or a narrower port list is applied here even
//     though Central checked the same things: this is the layer that cannot be talked out of
//     it (ADR 0022 D17).
type tunnelOpenFields struct {
	TunnelID   uuid.UUID `json:"tunnel_id"`
	Port       int       `json:"port"`
	Protection string    `json:"protection"`
	Credential string    `json:"credential"`
	BasicAuth  *struct {
		Username string `json:"username"`
		Password string `json:"password"`
	} `json:"basic_auth"`
	AllowedIPs  []string `json:"allowed_ips"`
	RewriteHost bool     `json:"rewrite_host"`
	TTLSeconds  int      `json:"ttl_seconds"`
}

type tunnelIDFields struct {
	TunnelID uuid.UUID `json:"tunnel_id"`
}

func (m *Manager) handleTunnelOpen(
	ctx context.Context, env protocol.Envelope, data []byte, send func([]byte) error,
) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, tunnel.CodeInvalidMessage)
		return
	}
	var p tunnelOpenFields
	if json.Unmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil {
		m.replyError(send, env.RequestID, tunnel.CodeInvalidMessage)
		return
	}
	// The node owner's veto. Checked here rather than trusted from Central, because this is
	// the only copy of it the platform cannot edit.
	if !m.cfg.TunnelEnabled() {
		slog.Warn("refused a tunnel: port forwarding is disabled on this node")
		m.replyError(send, env.RequestID, tunnel.CodeNodeVetoed)
		return
	}
	// The node's own port policy, on top of the platform's. The floor (>=1024) is inside
	// TunnelPortAllowed and no configuration can lower it.
	if !m.cfg.TunnelPortAllowed(p.Port) {
		slog.Warn("refused a tunnel: port is not allowed on this node", "port", p.Port)
		m.replyError(send, env.RequestID, tunnel.CodePortNotAllowed)
		return
	}
	if max := m.cfg.Tunnel.MaxTunnels; max > 0 && m.tunnels.Count() >= max {
		m.replyError(send, env.RequestID, tunnel.CodeLimitReached)
		return
	}

	opts := tunnel.Options{
		Port:           p.Port,
		Credential:     p.Credential,
		Protection:     p.Protection,
		AllowedIPs:     p.AllowedIPs,
		RewriteHost:    p.RewriteHost,
		KnownHostsPath: m.cfg.Tunnel.KnownHostsPath,
	}
	if p.BasicAuth != nil {
		opts.BasicUser = p.BasicAuth.Username
		opts.BasicPass = p.BasicAuth.Password
	}
	ttl := time.Duration(p.TTLSeconds) * time.Second

	result, err := m.tunnels.Open(ctx, p.TunnelID, opts, ttl)
	if err != nil {
		// Only the stable code travels. The provider's and ssh's own strings stay on this
		// node: they can quote the destination argument, which carries the credential.
		m.replyError(send, env.RequestID, tunnelErrorCode(err))
		return
	}
	frame, buildErr := protocol.BuildResponse(
		"tunnel.opened", m.creds.NodeID, env.RequestID, true,
		tunnelOpenedPayload(p.TunnelID, m.tunnels.ProviderName(), result),
		m.now(),
	)
	if buildErr != nil {
		m.replyError(send, env.RequestID, tunnel.CodeInternal)
		return
	}
	_ = send(frame)
}

func tunnelOpenedPayload(id uuid.UUID, provider string, result tunnel.Result) map[string]any {
	payload := map[string]any{
		"tunnel_id":     id.String(),
		"url":           result.URL,
		"provider":      provider,
		"authenticated": result.Authenticated,
	}
	if result.ExpiresAt != "" {
		payload["upstream_expires_at"] = result.ExpiresAt
	}
	return payload
}

// tunnelErrorCode maps a supervisor failure to the stable code Central understands.
func tunnelErrorCode(err error) string {
	var provErr *tunnel.ProviderError
	switch {
	case errors.As(err, &provErr):
		return provErr.Code
	case errors.Is(err, tunnel.ErrKnownHostsMissing):
		// Not "unavailable": a node with no pinned key is not a network problem, and the
		// operator must not be sent to check their firewall.
		return tunnel.CodeUntrusted
	case errors.Is(err, tunnel.ErrNoURL):
		return tunnel.CodeUnavailable
	default:
		return tunnel.CodeUnavailable
	}
}

func (m *Manager) handleTunnelClose(env protocol.Envelope, send func([]byte) error) {
	var p tunnelIDFields
	if json.Unmarshal(env.Payload, &p) != nil || p.TunnelID == uuid.Nil {
		m.replyError(send, env.RequestID, tunnel.CodeInvalidMessage)
		return
	}
	// Closing an unknown tunnel answers success. Central retrying a close it already sent —
	// or sending one after this daemon restarted — is not a failure, and reporting it as one
	// would leave a row that can never be closed.
	m.tunnels.Close(p.TunnelID)
	frame, err := protocol.BuildResponse(
		"tunnel.closed", m.creds.NodeID, env.RequestID, true,
		map[string]any{"tunnel_id": p.TunnelID.String(), "reason": "requested"},
		m.now(),
	)
	if err == nil {
		_ = send(frame)
	}
}

// TunnelStatus implements tunnel.StatusReporter: the supervisor's unsolicited reports
// (a new URL after a reconnect, a failure, a close) become tunnel.status frames.
//
// Dropped silently when no connection is up. The alternative — queueing — would deliver a
// stale URL after reconnecting, and Central re-opens its live tunnels then anyway, so the
// queue would only ever be wrong.
func (m *Manager) TunnelStatus(id uuid.UUID, state, url, expiresAt, errorCode string) {
	m.tunnelMu.Lock()
	out := m.tunnelOut
	m.tunnelMu.Unlock()
	if out == nil {
		slog.Info("tunnel status not sent: no connection to central",
			"tunnel_id", id.String(), "state", state)
		return
	}
	payload := map[string]any{"tunnel_id": id.String(), "state": state}
	if url != "" {
		payload["url"] = url
	}
	if expiresAt != "" {
		payload["upstream_expires_at"] = expiresAt
	}
	if errorCode != "" {
		payload["error_code"] = errorCode
	}
	frame, err := protocol.BuildControl(
		"tunnel.status", m.creds.NodeID, protocol.NewID(), payload, m.now(),
	)
	if err != nil {
		slog.Warn("could not build a tunnel status frame", "tunnel_id", id.String())
		return
	}
	_ = out(frame)
}

// tunnelReport is what node.register and node.runtime_status carry so Central can answer
// "can this node forward a port" before a user presses anything.
//
// It reports prerequisites, not a credential: the credential is the platform's, and this
// node has nothing to report about it. The three environment checks are what make the four
// possible failures distinguishable — without them every one of them arrives at the UI as
// "could not open a tunnel".
func (m *Manager) tunnelReport() map[string]any {
	sshAvailable := false
	if _, err := exec.LookPath("ssh"); err == nil {
		sshAvailable = true
	}
	knownHostsOK := false
	if info, err := os.Stat(m.cfg.Tunnel.KnownHostsPath); err == nil && info.Size() > 0 {
		knownHostsOK = true
	}
	egressOK := m.tunnelEgressOK()
	report := map[string]any{
		"veto":                   !m.cfg.TunnelEnabled(),
		"ssh_available":          sshAvailable,
		"egress_ok":              egressOK,
		"known_hosts_ok":         knownHostsOK,
		"daemon_supports_tunnel": true,
	}
	if len(m.cfg.Tunnel.AllowedPorts) > 0 {
		report["allowed_ports"] = m.cfg.Tunnel.AllowedPorts
	}
	if m.cfg.Tunnel.MaxTunnels > 0 {
		report["max_tunnels"] = m.cfg.Tunnel.MaxTunnels
	}
	return report
}

// egressProbeInterval bounds how often this node opens a TCP connection to the provider
// just to see whether it can. Per heartbeat would be every ten seconds per node, which
// looks like scanning from the other end; per registration would put a five-second dial in
// front of the control connection's handshake.
const egressProbeInterval = 5 * time.Minute

// tunnelEgressOK reports the last known reachability of the provider, refreshing it in the
// background when the value is stale.
//
// Never blocking. The first registration after start therefore reports `false` — "we have
// not checked" — and the platform pairs it with `tunnel_reported_at` so the UI can say the
// difference between "not ready" and "not known yet". A five-second dial in the handshake
// path would be the alternative, and it would delay every reconnect on every node for a
// value that is stale by construction anyway.
func (m *Manager) tunnelEgressOK() bool {
	// A stand-in provider is local, so probing the real provider would be both irrelevant and
	// the one thing the end-to-end stack must not do: the whole point of the fake is that the
	// suite needs no network and no account (plan/11 §2.6). Reported as reachable rather than
	// unknown, because what the report means here is "this node can reach the provider it is
	// configured to use".
	if tunnel.TestProviderCommandInUse() {
		return true
	}
	m.tunnelMu.Lock()
	fresh := m.now().Sub(m.egressCheckedAt) < egressProbeInterval
	value := m.egressOK
	probing := m.egressProbing
	if !fresh && !probing {
		m.egressProbing = true
	}
	m.tunnelMu.Unlock()

	if fresh || probing {
		return value
	}
	go func() {
		reachable := false
		if conn, err := net.DialTimeout("tcp", tunnel.ProviderDialAddress(), 5*time.Second); err == nil {
			reachable = true
			_ = conn.Close()
		}
		m.tunnelMu.Lock()
		m.egressOK = reachable
		m.egressCheckedAt = m.now()
		m.egressProbing = false
		m.tunnelMu.Unlock()
	}()
	return value
}
