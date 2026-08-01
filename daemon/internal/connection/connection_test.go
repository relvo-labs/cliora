package connection

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	"github.com/cliora/cliora/daemon/internal/tunnel"
)

type received struct {
	types    chan string
	register chan protocol.Envelope
	frames   chan capturedFrame
}

type capturedFrame struct {
	typ string
	raw []byte
}

func newReceived() *received {
	return &received{
		types:    make(chan string, 64),
		register: make(chan protocol.Envelope, 1),
		frames:   make(chan capturedFrame, 128),
	}
}

// collectFrame consumes frames in arrival order until one of the wanted type is
// found, returning its raw bytes.
func collectFrame(t *testing.T, rx *received, want string, timeout time.Duration) []byte {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case f := <-rx.frames:
			if f.typ == want {
				return f.raw
			}
		case <-deadline:
			t.Fatalf("timed out waiting for frame %q", want)
		}
	}
}

func fakeCentral(t *testing.T, nodeID uuid.UUID, acceptAuth bool, rx *received) *httptest.Server {
	t.Helper()
	upgrader := websocket.Upgrader{}
	handler := func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		challenge, _ := protocol.BuildControl("node.challenge", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXYZ", map[string]any{"nonce": base64.StdEncoding.EncodeToString(make([]byte, 32))}, time.Now())
		_ = conn.WriteMessage(websocket.TextMessage, challenge)
		for {
			_, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			env, err := protocol.DecodeControl(data)
			if err != nil {
				t.Errorf("central received invalid frame: %v", err)
				return
			}
			select {
			case rx.types <- env.Type:
			default:
			}
			select {
			case rx.frames <- capturedFrame{typ: env.Type, raw: append([]byte(nil), data...)}:
			default:
			}
			switch env.Type {
			case "node.auth":
				if !acceptAuth {
					_ = conn.WriteMessage(websocket.TextMessage, []byte(`{"type":"error","success":false,"error":{"code":"NODE_AUTH_FAILED","message":"x"}}`))
					return
				}
				frame, _ := protocol.BuildControl("node.authenticated", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, frame)
			case "node.register":
				select {
				case rx.register <- env:
				default:
				}
				frame, _ := protocol.BuildControl("node.registered", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, frame)
			}
		}
	}
	return httptest.NewServer(http.HandlerFunc(handler))
}

func protocolUnmarshal(env protocol.Envelope, v any) error {
	return json.Unmarshal(env.Payload, v)
}

func waitFor(t *testing.T, ch <-chan string, want string, timeout time.Duration) {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case got := <-ch:
			if got == want {
				return
			}
		case <-deadline:
			t.Fatalf("timed out waiting for %q", want)
		}
	}
}

func TestSessionAuthRegisterHeartbeatShutdown(t *testing.T) {
	nodeID := uuid.New()
	rx := newReceived()
	server := fakeCentral(t, nodeID, true, rx)
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm-test"},
		Runtime:   map[string]config.RuntimeConfig{"claude": {Enabled: false}},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{"/home/neil"}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- manager.Run(ctx) }()

	waitFor(t, rx.types, "node.auth", 3*time.Second)
	select {
	case env := <-rx.register:
		var p struct {
			Name     string `json:"name"`
			RunUser  string `json:"run_user"`
			Runtimes []any  `json:"runtimes"`
		}
		if protocolUnmarshal(env, &p) != nil || p.Name != "vm-test" {
			t.Fatalf("bad register payload: %+v", p)
		}
		// claude, codex and shell: every allowlisted runtime is reported, whether
		// or not it is enabled, so Central can tell "off" from "never heard of".
		if len(p.Runtimes) != 3 {
			t.Errorf("expected 3 runtimes, got %d", len(p.Runtimes))
		}
	case <-time.After(3 * time.Second):
		t.Fatal("no node.register received")
	}

	waitFor(t, rx.types, "node.heartbeat", 3*time.Second)

	cancel()
	waitFor(t, rx.types, "node.shutdown", 3*time.Second)
	if err := <-done; err != nil {
		t.Errorf("Run returned error: %v", err)
	}
}

func TestEmitsSystemInfoRuntimeStatusAndHeartbeatResources(t *testing.T) {
	nodeID := uuid.New()
	rx := newReceived()
	server := fakeCentral(t, nodeID, true, rx)
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm-test"},
		Runtime:   map[string]config.RuntimeConfig{"claude": {Enabled: false}},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{"/"}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	// Both dedicated frames must be emitted after register and pass the shared
	// contract validator.
	if raw := collectFrame(t, rx, "node.system_info", 3*time.Second); protocol.ValidateControl(raw) != nil {
		t.Errorf("node.system_info failed contract validation: %v", protocol.ValidateControl(raw))
	}
	if raw := collectFrame(t, rx, "node.runtime_status", 3*time.Second); protocol.ValidateControl(raw) != nil {
		t.Errorf("node.runtime_status failed contract validation: %v", protocol.ValidateControl(raw))
	}

	hbRaw := collectFrame(t, rx, "node.heartbeat", 3*time.Second)
	if err := protocol.ValidateControl(hbRaw); err != nil {
		t.Fatalf("node.heartbeat failed contract validation: %v", err)
	}
	env, err := protocol.DecodeControl(hbRaw)
	if err != nil {
		t.Fatalf("decode heartbeat: %v", err)
	}
	var p struct {
		Resources *struct {
			DaemonUptime *float64 `json:"daemon_uptime"`
		} `json:"resources"`
	}
	if err := json.Unmarshal(env.Payload, &p); err != nil {
		t.Fatalf("unmarshal heartbeat payload: %v", err)
	}
	if p.Resources == nil {
		t.Fatal("heartbeat payload missing resources object")
	}
	if p.Resources.DaemonUptime == nil || *p.Resources.DaemonUptime < 0 {
		t.Fatalf("heartbeat resources missing/invalid daemon_uptime: %+v", p.Resources)
	}
}

// TestReconnectReregistersAfterCentralDrop covers NFR-002: after Central drops
// the connection (e.g. a restart), the daemon reconnects, re-authenticates, and
// re-registers. This exercises the reconnect + backoff-reset path at unit level
// (a full TLS/revoked-credential integration scenario needs real infra).
func TestReconnectReregistersAfterCentralDrop(t *testing.T) {
	nodeID := uuid.New()
	var mu sync.Mutex
	var connCount, authCount, registerCount int
	reregistered := make(chan struct{})

	upgrader := websocket.Upgrader{}
	handler := func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		mu.Lock()
		connCount++
		myConn := connCount
		mu.Unlock()

		challenge, _ := protocol.BuildControl("node.challenge", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXYZ",
			map[string]any{"nonce": base64.StdEncoding.EncodeToString(make([]byte, 32))}, time.Now())
		_ = conn.WriteMessage(websocket.TextMessage, challenge)
		for {
			_, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			env, err := protocol.DecodeControl(data)
			if err != nil {
				t.Errorf("central received invalid frame: %v", err)
				return
			}
			switch env.Type {
			case "node.auth":
				mu.Lock()
				authCount++
				mu.Unlock()
				frame, _ := protocol.BuildControl("node.authenticated", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, frame)
			case "node.register":
				mu.Lock()
				registerCount++
				n := registerCount
				mu.Unlock()
				frame, _ := protocol.BuildControl("node.registered", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, frame)
				if myConn == 1 {
					// Simulate a Central restart: drop the socket right after the
					// first registration so the daemon must reconnect.
					return
				}
				if n >= 2 {
					select {
					case <-reregistered:
					default:
						close(reregistered)
					}
				}
			}
		}
	}
	server := httptest.NewServer(http.HandlerFunc(handler))
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm-test"},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	select {
	case <-reregistered:
	case <-time.After(6 * time.Second):
		t.Fatal("daemon did not reconnect and re-register after Central dropped the connection")
	}
	mu.Lock()
	defer mu.Unlock()
	if authCount < 2 {
		t.Errorf("expected re-authentication on reconnect, got authCount=%d", authCount)
	}
	if connCount < 2 {
		t.Errorf("expected a second connection on reconnect, got connCount=%d", connCount)
	}
}

// dispatchCentral drives the daemon through auth+register, then sends one
// session.start frame and captures the daemon's reply so the P2-07 dispatch
// (runtime allowlist + workspace guard + response framing) can be asserted.
func dispatchCentral(
	t *testing.T, nodeID uuid.UUID, startPayload map[string]any, reply chan<- []byte,
) *httptest.Server {
	t.Helper()
	upgrader := websocket.Upgrader{}
	handler := func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		challenge, _ := protocol.BuildControl("node.challenge", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXYZ",
			map[string]any{"nonce": base64.StdEncoding.EncodeToString(make([]byte, 32))}, time.Now())
		_ = conn.WriteMessage(websocket.TextMessage, challenge)
		for {
			_, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			env, err := protocol.DecodeControl(data)
			if err != nil {
				continue
			}
			switch env.Type {
			case "node.auth":
				frame, _ := protocol.BuildControl("node.authenticated", nodeID, env.RequestID,
					map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, frame)
			case "node.register":
				ack, _ := protocol.BuildControl("node.registered", nodeID, env.RequestID,
					map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, ack)
				start, _ := protocol.BuildControl("session.start", nodeID,
					"01K0ABCDEFGHJKMNPQRSTVWXY7", startPayload, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, start)
			case "error", "session.started", "session.stopped":
				select {
				case reply <- append([]byte(nil), data...):
				default:
				}
			}
		}
	}
	return httptest.NewServer(http.HandlerFunc(handler))
}

func TestSessionStartDisabledRuntimeRepliesError(t *testing.T) {
	nodeID := uuid.New()
	reply := make(chan []byte, 1)
	payload := map[string]any{
		"session_id": uuid.New().String(),
		"runtime":    "claude",
		"workspace":  "/home/neil/app",
		"rows":       24,
		"columns":    80,
	}
	server := dispatchCentral(t, nodeID, payload, reply)
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm"},
		Runtime:   map[string]config.RuntimeConfig{"claude": {Enabled: false}}, // disabled → RUNTIME_DISABLED
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{"/home/neil"}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	select {
	case raw := <-reply:
		// The reply must be a contract-valid error envelope with a stable code.
		env, err := protocol.DecodeControl(raw)
		if err != nil || env.Type != "error" {
			t.Fatalf("expected error envelope, got type=%q err=%v", env.Type, err)
		}
		var body struct {
			Success bool `json:"success"`
			Error   struct {
				Code string `json:"code"`
			} `json:"error"`
		}
		if json.Unmarshal(raw, &body) != nil || body.Success {
			t.Fatalf("error frame must carry success:false")
		}
		if body.Error.Code != "RUNTIME_DISABLED" {
			t.Fatalf("expected RUNTIME_DISABLED, got %q", body.Error.Code)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("no reply to session.start")
	}
}

func TestSessionStartWorkspaceEscapeRepliesError(t *testing.T) {
	nodeID := uuid.New()
	reply := make(chan []byte, 1)
	payload := map[string]any{
		"session_id": uuid.New().String(),
		"runtime":    "fake",
		"workspace":  "/etc", // outside the allowed root
		"rows":       24,
		"columns":    80,
	}
	server := dispatchCentral(t, nodeID, payload, reply)
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm"},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{"/home/neil"}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")
	// Make the "fake" runtime resolvable so the workspace guard is the gate.
	manager.resolveLaunch = func(string) (runtime.LaunchSpec, error) {
		return runtime.LaunchSpec{Path: "/bin/true"}, nil
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	select {
	case raw := <-reply:
		var body struct {
			Error struct {
				Code string `json:"code"`
			} `json:"error"`
		}
		if json.Unmarshal(raw, &body) != nil {
			t.Fatalf("bad reply")
		}
		if body.Error.Code != "WORKSPACE_OUTSIDE_ALLOWED_ROOT" {
			t.Fatalf("expected WORKSPACE_OUTSIDE_ALLOWED_ROOT, got %q", body.Error.Code)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("no reply to session.start")
	}
}

func TestSessionAuthFailureStops(t *testing.T) {
	nodeID := uuid.New()
	rx := newReceived()
	server := fakeCentral(t, nodeID, false, rx)
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm"},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	// Auth fails; the manager must not proceed to register (it reconnects/backs off).
	go func() { _ = manager.Run(ctx) }()
	waitFor(t, rx.types, "node.auth", 2*time.Second)
	select {
	case <-rx.register:
		t.Fatal("register must not be sent after auth failure")
	case <-time.After(500 * time.Millisecond):
	}
}

// tunnelEgressReport pulls the `tunnel.egress_ok` a frame carries, failing if the frame does
// not validate or carries no report at all.
func tunnelEgressReport(t *testing.T, raw []byte) bool {
	t.Helper()
	if err := protocol.ValidateControl(raw); err != nil {
		t.Fatalf("frame failed contract validation: %v", err)
	}
	env, err := protocol.DecodeControl(raw)
	if err != nil {
		t.Fatalf("decode frame: %v", err)
	}
	var p struct {
		Tunnel *struct {
			EgressOK *bool `json:"egress_ok"`
		} `json:"tunnel"`
	}
	if err := json.Unmarshal(env.Payload, &p); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if p.Tunnel == nil || p.Tunnel.EgressOK == nil {
		t.Fatalf("frame %q carried no tunnel report", env.Type)
	}
	return *p.Tunnel.EgressOK
}

// TestEgressRefreshPublishesCorrectedTunnelReport covers the gap between what a node knows
// about its own port-forwarding prerequisites and what Central has been told (P11, ADR 0022).
//
// The egress probe is deliberately kept out of the handshake path, so node.register always
// reports "we have not checked". Nothing then re-sent the corrected value, so a node with
// working egress read as blocked in the UI until its control connection happened to drop —
// while `agentd doctor` on that same node reported the provider reachable, because doctor
// dials synchronously. The refresh has to publish the answer itself.
func TestEgressRefreshPublishesCorrectedTunnelReport(t *testing.T) {
	t.Setenv(tunnel.TestProviderCommandEnv, "")
	nodeID := uuid.New()
	rx := newReceived()
	server := fakeCentral(t, nodeID, true, rx)
	defer server.Close()

	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm-test"},
		Runtime:   map[string]config.RuntimeConfig{"claude": {Enabled: false}},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{"/"}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")
	// A reachable provider, without a network or an account.
	manager.probeEgress = func() bool { return true }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	// The register-time report is the pre-probe value by construction: no dial has run yet.
	if tunnelEgressReport(t, collectFrame(t, rx, "node.register", 3*time.Second)) {
		t.Error("node.register reported egress_ok before anything had probed the provider")
	}

	// The correction arrives on the heartbeat tick. Loop, because the handshake has already
	// sent one node.runtime_status carrying the same pre-probe value.
	deadline := time.After(5 * time.Second)
	for {
		select {
		case f := <-rx.frames:
			if f.typ != "node.runtime_status" || !tunnelEgressReport(t, f.raw) {
				continue
			}
			env, err := protocol.DecodeControl(f.raw)
			if err != nil {
				t.Fatalf("decode runtime_status: %v", err)
			}
			var p struct {
				Runtimes []any `json:"runtimes"`
			}
			if err := json.Unmarshal(env.Payload, &p); err != nil {
				t.Fatalf("unmarshal runtime_status: %v", err)
			}
			// Central clears and re-inserts a node's runtime rows from this frame, so a
			// tunnel-only push would silently erase them.
			if len(p.Runtimes) == 0 {
				t.Fatal("the corrected report carried no runtimes; Central would erase them")
			}
			return
		case <-deadline:
			t.Fatal("the egress refresh never published a corrected tunnel report")
		}
	}
}

// TestReconnectBackoffScheduleMatchesThePRD pins the reconnect schedule to the
// steps PRD FR-CONN-003 lists. TestReconnectReregistersAfterCentralDrop proves
// the daemon comes back; this proves it comes back on the published cadence,
// which is what the criteria for each step actually claim.
func TestReconnectBackoffScheduleMatchesThePRD(t *testing.T) {
	want := []time.Duration{
		1 * time.Second,
		2 * time.Second,
		5 * time.Second,
		10 * time.Second,
		30 * time.Second,
	}
	if len(backoff) != len(want) {
		t.Fatalf("backoff has %d steps, PRD FR-CONN-003 lists %d: %v", len(backoff), len(want), backoff)
	}
	for i, step := range want {
		if backoff[i] != step {
			t.Errorf("backoff step %d = %v, PRD says %v", i+1, backoff[i], step)
		}
	}
	if maxBackoff != 60*time.Second {
		t.Errorf("maxBackoff = %v, PRD FR-CONN-003 caps it at 60s", maxBackoff)
	}
	// The ceiling has to actually bound the table, or the last step wins silently.
	for i, step := range backoff {
		if step > maxBackoff {
			t.Errorf("backoff step %d (%v) exceeds the %v ceiling", i+1, step, maxBackoff)
		}
	}
}
