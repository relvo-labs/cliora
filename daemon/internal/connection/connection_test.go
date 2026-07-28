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
		if len(p.Runtimes) != 2 {
			t.Errorf("expected 2 runtimes, got %d", len(p.Runtimes))
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
	manager.resolveBinary = func(string) (string, error) { return "/bin/true", nil }

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
