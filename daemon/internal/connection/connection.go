// Package connection manages the daemon's outbound WSS link to Central: the
// auth handshake, node.register announce, heartbeats, reconnect with backoff +
// jitter, and graceful shutdown (P1-11). One goroutine reads; writes are
// serialized behind a mutex (gorilla allows a single concurrent writer).
package connection

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/rand/v2"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/files"
	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/session"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/cliora/cliora/daemon/internal/tunnel"
	"github.com/cliora/cliora/daemon/internal/update"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

var backoff = []time.Duration{time.Second, 2 * time.Second, 5 * time.Second, 10 * time.Second, 30 * time.Second}

const maxBackoff = 60 * time.Second

type Manager struct {
	cfg      *config.Config
	creds    *config.Credentials
	registry *runtime.Registry
	info     systeminfo.Info
	sampler  *systeminfo.ResourceSampler
	version  string
	dialer   *websocket.Dialer
	now      func() time.Time

	// P2 session/terminal lifecycle. The manager persists across reconnects so
	// tmux-backed sessions survive a Central restart; the guard/resolver enforce
	// allowed-root workspaces and the runtime-id allowlist (SEC-001/002).
	sessions *session.Manager
	guard    *workspace.Guard
	// resolveLaunch turns an allowlisted runtime id into the binary *and* the
	// daemon's own launch flags (runtime.ResolveLaunch). A test seam, and the only
	// path from a session.start to an argv.
	resolveLaunch func(string) (runtime.LaunchSpec, error)
	// files performs the P3 read-only filesystem relay (list/read/search),
	// confined to a session's workspace via the workspace guard (ADR 0014).
	files *files.Service

	// P11 port forwarding (ADR 0022). The supervisor owns the ssh child processes; this
	// manager only translates between it and the protocol. `tunnelSend` is set for the life
	// of a connection so unsolicited tunnel.status frames have somewhere to go — a tunnel
	// outlives any single request, and the free tier changes its URL roughly hourly.
	tunnels   *tunnel.Supervisor
	tunnelMu  sync.Mutex
	tunnelOut func([]byte) error
	// Cached provider reachability. Guarded by tunnelMu; refreshed off the hot path so a
	// five-second dial never sits in front of the control connection's handshake.
	egressOK        bool
	egressCheckedAt time.Time
	egressProbing   bool
	probeEgress     func() bool
	// The runtime items last sent to Central, guarded by tunnelMu. Kept because a refreshed
	// tunnel report travels on node.runtime_status, and Central replaces a node's runtime
	// rows wholesale from that frame — a tunnel-only push with an empty list would erase them.
	lastRuntimes []map[string]any

	// P4 self-update. `configPath` is needed because the post-restart health check
	// runs `agentd doctor --config <path>`; `newUpdaterFn` is a test seam so the
	// update handler can be exercised without systemd or a real binary swap.
	configPath   string
	newUpdaterFn func() *update.Updater
}

func New(cfg *config.Config, creds *config.Credentials, reg *runtime.Registry, info systeminfo.Info, version string) *Manager {
	// Sample disk usage against the first allowed workspace root, falling back to
	// the filesystem root; the sampler is best-effort and never blocks the link.
	diskPath := "/"
	if len(cfg.Workspace.AllowedRoots) > 0 {
		diskPath = cfg.Workspace.AllowedRoots[0]
	}
	m := &Manager{
		cfg:           cfg,
		creds:         creds,
		registry:      reg,
		info:          info,
		sampler:       systeminfo.NewResourceSampler(diskPath),
		version:       version,
		dialer:        websocket.DefaultDialer,
		now:           time.Now,
		sessions:      session.New(newTmuxClient(cfg), "", ""),
		guard:         workspace.New(cfg.Workspace.AllowedRoots),
		resolveLaunch: reg.ResolveLaunch,
		files:         files.NewService(cfg, time.Now),
		probeEgress:   dialProvider,
		configPath:    config.DefaultConfigPath,
	}
	m.tunnels = tunnel.NewSupervisor(tunnel.NewPinggyProvider(), m)
	// Anything left by a previous daemon generation is still serving traffic, with nothing
	// in any log to say so. Central is the authority on which tunnels should exist and
	// re-opens them after reconnecting, so the old generation is always the wrong one to
	// keep (ADR 0022).
	if reaped := m.tunnels.ReapOrphans(); reaped > 0 {
		slog.Warn("reaped port-forwarding tunnels left by a previous run", "count", reaped)
	}
	return m
}

// newTmuxClient builds the tmux client for this node: Cliora's own server plus the
// generated config that makes the browser terminal scrollable (ADR 0023, PV-04).
// A config that cannot be written is logged and then ignored — the sessions still
// work, they just fall back to tmux's defaults, and doctor reports the gap rather
// than the daemon refusing to start over a comfort feature.
func newTmuxClient(cfg *config.Config) ctmux.Client {
	client, err := ctmux.Prepare(cfg.Session.ScrollbackLimit)
	if err != nil {
		slog.Warn("tmux config not written; sessions fall back to tmux defaults",
			"dir", ctmux.ResolveConfigDir(), "error", err)
	}
	return client
}

// SetConfigPath records where this daemon's config lives. The post-restart health
// check runs `agentd doctor --config <path>`, so a node installed with a
// non-default config path would otherwise have its update rolled back by a health
// check that failed for the wrong reason.
func (m *Manager) SetConfigPath(path string) {
	if path != "" {
		m.configPath = path
	}
}

func (m *Manager) url() string {
	return strings.TrimRight(m.cfg.Server.URL, "/") + "/" + m.creds.NodeID.String()
}

// Run connects and reconnects until the context is cancelled.
func (m *Manager) Run(ctx context.Context) error {
	for attempt := 0; ctx.Err() == nil; attempt++ {
		conn, _, err := m.dialer.DialContext(ctx, m.url(), nil)
		if err == nil {
			attempt = 0
			err = m.session(ctx, conn)
			_ = conn.Close()
		}
		if ctx.Err() != nil {
			return nil
		}
		delay := backoff[min(attempt, len(backoff)-1)]
		if delay > maxBackoff {
			delay = maxBackoff
		}
		delay += time.Duration(rand.IntN(250)) * time.Millisecond
		// Counted by coarse reason (tech §18.2). A rising reconnect rate is the first
		// visible symptom of a flapping link, and it is invisible from Central: each
		// reconnect there just looks like a fresh, healthy connection.
		metrics.Increment(metrics.DaemonReconnectTotal, map[string]string{"reason": safeErr(err)})
		slog.Warn("central disconnected", "retry_ms", delay.Milliseconds(), "error", safeErr(err))
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-timer.C:
		}
	}
	return nil
}

func (m *Manager) session(ctx context.Context, conn *websocket.Conn) error {
	var writeMu sync.Mutex
	write := func(msgType string, requestID string, payload any) error {
		frame, err := protocol.BuildControl(msgType, m.creds.NodeID, requestID, payload, m.now())
		if err != nil {
			return err
		}
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(websocket.TextMessage, frame)
	}
	// send/sendBinary share the single-writer mutex so session responses and
	// terminal output never interleave with control writes on the socket.
	send := func(frame []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(websocket.TextMessage, frame)
	}
	sendBinary := func(frame []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(websocket.BinaryMessage, frame)
	}

	// Unsolicited tunnel status frames (URL changes, failures) travel on whichever
	// connection is current. Registered before anything can produce one.
	m.tunnelMu.Lock()
	m.tunnelOut = send
	m.tunnelMu.Unlock()
	defer func() {
		m.tunnelMu.Lock()
		m.tunnelOut = nil
		m.tunnelMu.Unlock()
	}()

	if err := m.authenticate(conn, write); err != nil {
		return err
	}
	// Detect runtimes once and reuse the result for both node.register and the
	// dedicated node.runtime_status frame (avoids a second round of --version).
	detected := m.registry.DetectAll(ctx, m.now())
	runtimes := runtimeItems(detected)
	m.rememberRuntimes(runtimes)
	if err := write("node.register", protocol.NewID(), m.registerPayload(detected)); err != nil {
		return err
	}
	slog.Info("registered with central", "node_id", m.creds.NodeID.String())
	// Emit the dedicated control-plane frames so the system/runtime facts also
	// arrive via their own message types (P1-12), each with a fresh event ULID.
	if err := write("node.system_info", protocol.NewID(), m.systemInfoPayload()); err != nil {
		return err
	}
	// The tunnel report rides along, as the contract has always allowed: this frame is the
	// only channel that can correct a prerequisite without a reconnect, and the background
	// egress probe publishes through it.
	if err := write("node.runtime_status", protocol.NewID(), map[string]any{
		"runtimes": runtimes,
		"tunnel":   m.tunnelReport(),
	}); err != nil {
		return err
	}

	sctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		m.heartbeatLoop(sctx, write)
	}()

	readErr := make(chan error, 1)
	go func() { readErr <- m.dispatch(sctx, conn, send, sendBinary) }()

	select {
	case <-ctx.Done():
		// Graceful shutdown: best-effort deregister, then tear down. Tunnels are closed
		// explicitly rather than left to the process dying, so nothing keeps serving after
		// the daemon is gone.
		m.tunnels.CloseAll()
		_ = write("node.shutdown", protocol.NewID(), map[string]any{"reason": "shutdown"})
		_ = conn.Close()
		<-readErr
		cancel()
		wg.Wait()
		return nil
	case err := <-readErr:
		cancel()
		wg.Wait()
		return err
	}
}

func (m *Manager) authenticate(conn *websocket.Conn, write func(string, string, any) error) error {
	_ = conn.SetReadDeadline(m.now().Add(15 * time.Second))
	_, data, err := conn.ReadMessage()
	if err != nil {
		return err
	}
	if err := protocol.ValidateControl(data); err != nil {
		return fmt.Errorf("invalid authentication challenge")
	}
	challenge, err := protocol.DecodeControl(data)
	if err != nil || challenge.Type != "node.challenge" {
		return fmt.Errorf("invalid authentication challenge")
	}
	var payload struct {
		Nonce string `json:"nonce"`
	}
	if json.Unmarshal(challenge.Payload, &payload) != nil || payload.Nonce == "" {
		return fmt.Errorf("invalid authentication challenge")
	}
	key, err := m.creds.SigningKey()
	if err != nil {
		return err
	}
	message := []byte("cliora-node-auth-v1\n" + m.creds.NodeID.String() + "\n" + challenge.RequestID + "\n" + payload.Nonce)
	signature := base64.StdEncoding.EncodeToString(ed25519.Sign(key, message))
	if err := write("node.auth", challenge.RequestID, map[string]any{"challenge_id": challenge.RequestID, "signature": signature}); err != nil {
		return err
	}
	_, data, err = conn.ReadMessage()
	_ = conn.SetReadDeadline(time.Time{})
	if err != nil {
		return err
	}
	env, err := protocol.DecodeControl(data)
	if err != nil {
		return err
	}
	if env.Type != "node.authenticated" {
		return fmt.Errorf("authentication rejected")
	}
	return nil
}

func (m *Manager) heartbeatLoop(ctx context.Context, write func(string, string, any) error) {
	interval := time.Duration(m.cfg.Heartbeat.IntervalSeconds) * time.Second
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			active := m.sessions.ActiveCount()
			payload := map[string]any{"daemon_version": m.version, "active_sessions": active}
			sample := m.sampler.Sample()
			if res := resourcesPayload(sample); len(res) > 0 {
				payload["resources"] = res
			}
			if err := write("node.heartbeat", protocol.NewID(), payload); err != nil {
				return
			}
			// Recorded locally as well as sent: `agentd metrics` has to be answerable on
			// a node that cannot currently reach Central, which is exactly when someone
			// is standing at it asking what is wrong.
			metrics.Increment(metrics.DaemonHeartbeatSent, nil)
			metrics.SetGauge(metrics.DaemonActiveSessions, float64(active), nil)
			if sample.DaemonUptime != nil {
				metrics.SetGauge(metrics.DaemonUptimeSeconds, *sample.DaemonUptime, nil)
			}
			// What actually gives the egress probe its five-minute cadence. Nothing else asks
			// for the value, so without this tick it would run once per daemon start and the
			// answer Central holds could never change. The call is non-blocking and
			// rate-limits itself to egressProbeInterval, so a one-second heartbeat does not
			// become a one-second dial.
			if m.cfg.TunnelEnabled() {
				m.refreshEgress()
			}
		}
	}
}

// runtimeItems converts detection results into the wire item shape shared by
// node.register and node.runtime_status (matches runtime-item.schema.json).
func runtimeItems(detected []runtime.DetectResult) []map[string]any {
	runtimes := []map[string]any{}
	for _, r := range detected {
		item := map[string]any{"runtime": r.Runtime, "available": r.Available}
		if r.Version != "" {
			item["version"] = r.Version
		}
		if r.BinaryPath != "" {
			item["binary_path"] = r.BinaryPath
		}
		if !r.CheckedAt.IsZero() {
			item["checked_at"] = r.CheckedAt.UTC().Format("2006-01-02T15:04:05.000000Z07:00")
		}
		// Only sent for a runtime the daemon can actually bypass, and only as the
		// measured outcome — a node that asked for the bypass but has a CLI that does
		// not know the flag reports false, because that is what will happen when a
		// session starts (contract 1.7.0, ADR 0023 D3).
		if r.SandboxBypassRequested || r.SandboxBypass {
			item["sandbox_bypass"] = r.SandboxBypass
		}
		runtimes = append(runtimes, item)
	}
	return runtimes
}

func (m *Manager) registerPayload(detected []runtime.DetectResult) map[string]any {
	roots := []map[string]any{}
	for _, root := range m.cfg.Workspace.AllowedRoots {
		roots = append(roots, map[string]any{"path": root, "is_enabled": true})
	}
	hostname := m.info.Hostname
	if hostname == "" {
		hostname = m.cfg.Node.Name
	}
	return map[string]any{
		"tunnel": m.tunnelReport(),
		// The posture of this machine, reported so the console can show it. Never
		// settable from Central: a message that could turn this on would be a message
		// that could grant root (ADR 0023 D11).
		"privileged_terminal": m.cfg.Node.PrivilegedTerminal,
		"name":                m.cfg.Node.Name,
		"hostname":            hostname,
		"os":                  m.info.OS,
		"os_version":          m.info.OSVersion,
		"architecture":        m.info.Architecture,
		"daemon_version":      m.version,
		"run_user":            m.info.RunUser,
		"runtimes":            runtimeItems(detected),
		"workspace_roots":     roots,
	}
}

// systemInfoPayload conforms to node-system-info.schema.json (os, os_version,
// architecture, run_user required; kernel optional).
func (m *Manager) systemInfoPayload() map[string]any {
	payload := map[string]any{
		"os":           m.info.OS,
		"os_version":   m.info.OSVersion,
		"architecture": m.info.Architecture,
		"run_user":     m.info.RunUser,
	}
	if m.info.Kernel != "" {
		payload["kernel"] = m.info.Kernel
	}
	return payload
}

// resourcesPayload renders a best-effort resources object for node.heartbeat,
// omitting any metric that could not be sampled (node-heartbeat.schema.json).
func resourcesPayload(r systeminfo.Resources) map[string]any {
	res := map[string]any{}
	if r.CPUUsage != nil {
		res["cpu_usage"] = *r.CPUUsage
	}
	if r.MemoryUsage != nil {
		res["memory_usage"] = *r.MemoryUsage
	}
	if r.LoadAverage != nil {
		res["load_average"] = *r.LoadAverage
	}
	if r.DiskUsage != nil {
		res["disk_usage"] = *r.DiskUsage
	}
	if r.DaemonUptime != nil {
		res["daemon_uptime"] = *r.DaemonUptime
	}
	return res
}

type startFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Runtime   string    `json:"runtime"`
	Workspace string    `json:"workspace"`
	Rows      uint16    `json:"rows"`
	Columns   uint16    `json:"columns"`
}
type idFields struct {
	SessionID uuid.UUID `json:"session_id"`
}
type sizeFields struct {
	SessionID uuid.UUID `json:"session_id"`
	Rows      uint16    `json:"rows"`
	Columns   uint16    `json:"columns"`
}

// dispatch is the daemon's inbound control loop (P2-07): decode each frame and
// route session/terminal requests to the session manager, replying via the
// single-writer send/sendBinary closures. Acks (node.registered/authenticated)
// and malformed frames are ignored so the link stays up.
func (m *Manager) dispatch(
	ctx context.Context, conn *websocket.Conn, send, sendBinary func([]byte) error,
) error {
	for {
		kind, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		if kind == websocket.BinaryMessage {
			frameKind, id, payload, decErr := protocol.DecodeBinary(data)
			if decErr == nil && frameKind == 1 {
				_ = m.sessions.Input(id, payload)
			}
			continue
		}
		env, decErr := protocol.DecodeControl(data)
		if decErr != nil {
			continue
		}
		switch env.Type {
		case "session.start":
			m.handleStart(ctx, env, data, send)
		case "session.stop":
			m.handleStop(ctx, env, send)
		case "session.attach":
			m.handleAttach(ctx, env, send, sendBinary)
		case "terminal.resize":
			var p sizeFields
			if json.Unmarshal(env.Payload, &p) == nil {
				_ = m.sessions.Resize(p.SessionID, p.Rows, p.Columns)
			}
		case "filesystem.list":
			m.handleFsList(env, data, send)
		case "filesystem.read":
			m.handleFsRead(env, data, send)
		case "filesystem.search":
			m.handleFsSearch(ctx, env, data, send)
		case "daemon.update":
			m.handleUpdate(ctx, env, data, send)
		case "tunnel.open":
			m.handleTunnelOpen(ctx, env, data, send)
		case "tunnel.close":
			m.handleTunnelClose(env, send)
		}
	}
}

func (m *Manager) handleStart(
	ctx context.Context, env protocol.Envelope, data []byte, send func([]byte) error,
) {
	if protocol.ValidateControl(data) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	var p startFields
	if json.Unmarshal(env.Payload, &p) != nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	// Resolve the launch binary from the runtime allowlist — never from a
	// caller-supplied command (SEC-002) — then canonicalise the workspace
	// against the allowed roots (SEC-001) before starting anything.
	launch, err := m.resolveLaunch(p.Runtime)
	if err != nil {
		m.replyError(send, env.RequestID, err.Error())
		return
	}
	resolved, err := m.guard.Resolve(p.Workspace)
	if err != nil {
		m.replyError(send, env.RequestID, workspaceCode(err))
		return
	}
	// "bypassed" vs "enforced" is the same fact the console shows and the audit
	// trail records, so it is derived from the resolved launch rather than from
	// config: this is what the process will actually be started with.
	sandbox := "enforced"
	if len(launch.Args) > 0 {
		sandbox = "bypassed"
	}
	if startErr := m.sessions.StartSession(
		ctx, p.SessionID, p.Runtime, resolved, launch.Path, launch.Args, p.Rows, p.Columns,
	); startErr != nil {
		code := "SESSION_START_FAILED"
		if startErr.Error() == "SESSION_ALREADY_EXISTS" {
			code = "SESSION_ALREADY_EXISTS"
		}
		// Labelled by runtime, sandbox posture and outcome only. "claude starts fail
		// but codex does not" is the shape of the question this answers, and none of
		// the labels is identifying.
		metrics.Increment(metrics.DaemonSessionStartTotal,
			map[string]string{"runtime": p.Runtime, "result": "failed", "sandbox": sandbox})
		m.replyError(send, env.RequestID, code)
		return
	}
	metrics.Increment(metrics.DaemonSessionStartTotal,
		map[string]string{"runtime": p.Runtime, "result": "started", "sandbox": sandbox})
	frame, _ := protocol.BuildResponse(
		"session.started", m.creds.NodeID, env.RequestID, true,
		map[string]any{"session_id": p.SessionID.String(), "runtime": p.Runtime, "workspace": resolved},
		m.now(),
	)
	_ = send(frame)
}

// terminalChunk keeps each binary frame within the 64 KiB control/binary cap;
// the reattach snapshot can be up to 2 MiB, so it is split across frames.
const terminalChunk = 32 * 1024

func (m *Manager) sendChunked(sendBinary func([]byte) error, sid uuid.UUID, data []byte) {
	for i := 0; i < len(data); i += terminalChunk {
		end := i + terminalChunk
		if end > len(data) {
			end = len(data)
		}
		if frame, err := protocol.EncodeBinary(2, sid, data[i:end]); err == nil {
			_ = sendBinary(frame)
		}
	}
}

func (m *Manager) handleAttach(
	ctx context.Context, env protocol.Envelope, send, sendBinary func([]byte) error,
) {
	var p sizeFields
	if json.Unmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	sid := p.SessionID
	output := func(b []byte) error {
		frame, err := protocol.EncodeBinary(2, sid, b)
		if err != nil {
			return err
		}
		return sendBinary(frame)
	}
	onExit := func(code int) {
		// Notify the browser (terminal.exited) and Central's durable state
		// (session.status_changed → terminal_sessions.status) that the CLI ended.
		exited, _ := protocol.BuildControl(
			"terminal.exited", m.creds.NodeID, protocol.NewID(),
			map[string]any{"session_id": sid.String(), "code": code}, m.now(),
		)
		_ = send(exited)
		changed, _ := protocol.BuildControl(
			"session.status_changed", m.creds.NodeID, protocol.NewID(),
			map[string]any{"session_id": sid.String(), "status": "exited", "exit_code": code},
			m.now(),
		)
		_ = send(changed)
	}
	snapshot, err := m.sessions.Attach(ctx, sid, p.Rows, p.Columns, output, onExit)
	if err != nil {
		m.replyError(send, env.RequestID, "SESSION_NOT_FOUND")
		return
	}
	attached, _ := protocol.BuildResponse(
		"session.attached", m.creds.NodeID, env.RequestID, true,
		map[string]any{
			"session_id":     sid.String(),
			"snapshot_bytes": len(snapshot.Bytes),
			"truncated":      snapshot.Truncated,
			"continuity":     "snapshot",
		}, m.now(),
	)
	_ = send(attached)
	if len(snapshot.Bytes) > 0 {
		m.sendChunked(sendBinary, sid, snapshot.Bytes)
	}
	// Only signal a gap when history was actually dropped (ADR 0004); a complete
	// snapshot must not push the client into the manual-retry gap state.
	if snapshot.Truncated {
		gap, _ := protocol.BuildControl(
			"terminal.gap", m.creds.NodeID, protocol.NewID(),
			map[string]any{"session_id": sid.String(), "reason": "reattach_boundary"}, m.now(),
		)
		_ = send(gap)
	}
}

func (m *Manager) handleStop(ctx context.Context, env protocol.Envelope, send func([]byte) error) {
	var p idFields
	if json.Unmarshal(env.Payload, &p) != nil || p.SessionID == uuid.Nil {
		m.replyError(send, env.RequestID, "INVALID_MESSAGE")
		return
	}
	outcome, err := m.sessions.Stop(ctx, p.SessionID)
	if err != nil {
		m.replyError(send, env.RequestID, "SESSION_NOT_RUNNING")
		return
	}
	// `forced` was hardcoded false while the stop path had only one stage. It now
	// reports whether the CLI exited on the termination signal or had to be killed,
	// which is the difference an operator needs to see (FR-SESSION-005).
	frame, _ := protocol.BuildResponse(
		"session.stopped", m.creds.NodeID, env.RequestID, true,
		map[string]any{
			"session_id": p.SessionID.String(),
			"forced":     outcome == ctmux.StopForced,
		}, m.now(),
	)
	_ = send(frame)
}

func (m *Manager) replyError(send func([]byte) error, requestID, code string) {
	frame, err := protocol.BuildError(
		m.creds.NodeID, requestID, code, "The daemon could not complete the request.", m.now(),
	)
	if err == nil {
		_ = send(frame)
	}
}

func workspaceCode(err error) string {
	switch {
	case errors.Is(err, workspace.ErrNotFound):
		return "WORKSPACE_NOT_FOUND"
	case errors.Is(err, workspace.ErrNotDir):
		return "WORKSPACE_NOT_DIRECTORY"
	case errors.Is(err, workspace.ErrPermision):
		return "WORKSPACE_PERMISSION_DENIED"
	case errors.Is(err, workspace.ErrInvalid):
		return "WORKSPACE_INVALID"
	default:
		return "WORKSPACE_OUTSIDE_ALLOWED_ROOT"
	}
}

func safeErr(err error) string {
	if err == nil {
		return "closed"
	}
	if errors.Is(err, context.Canceled) {
		return "shutdown"
	}
	return "connection failed"
}
