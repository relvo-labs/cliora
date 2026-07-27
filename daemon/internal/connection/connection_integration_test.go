//go:build integration

// End-to-end P2-07: the production connection dispatch launches a real tmux
// session via the Fake CLI on session.start and tears it down on session.stop.
// Guarded by the `integration` tag; skipped without tmux.
package connection

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/session"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

func buildFakeCLI(t *testing.T) string {
	t.Helper()
	out := filepath.Join(t.TempDir(), "fakecli")
	build := exec.Command("go", "build", "-o", out, "github.com/cliora/cliora/daemon/cmd/fakecli")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build fakecli: %v\n%s", err, output)
	}
	return out
}

func TestSessionStartStopRoundTripOverConnection(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	nodeID := uuid.New()
	sessionID := uuid.New()
	workspaceDir := t.TempDir()
	started := make(chan struct{}, 1)
	stopped := make(chan struct{}, 1)

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
				f, _ := protocol.BuildControl("node.authenticated", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, f)
			case "node.register":
				ack, _ := protocol.BuildControl("node.registered", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, ack)
				start, _ := protocol.BuildControl("session.start", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXY7",
					map[string]any{"session_id": sessionID.String(), "runtime": "fake", "workspace": workspaceDir, "rows": 24, "columns": 80}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, start)
			case "session.started":
				var p struct {
					SessionID string `json:"session_id"`
				}
				_ = json.Unmarshal(env.Payload, &p)
				if p.SessionID == sessionID.String() {
					started <- struct{}{}
				}
				stop, _ := protocol.BuildControl("session.stop", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXY8",
					map[string]any{"session_id": sessionID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, stop)
			case "session.stopped":
				stopped <- struct{}{}
			}
		}
	}
	server := httptest.NewServer(http.HandlerFunc(handler))
	defer server.Close()

	socket := "cliora-conn-" + sessionID.String()[:8]
	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm"},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{workspaceDir}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")
	// Real tmux over a private socket + the Fake CLI as the resolved binary.
	manager.sessions = session.New(ctmux.Client{Socket: socket}, "", "")
	manager.guard = workspace.New([]string{workspaceDir})
	manager.resolveBinary = func(string) (string, error) { return bin, nil }
	defer func() { _ = manager.sessions.Stop(context.Background(), sessionID) }()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	select {
	case <-started:
	case <-time.After(8 * time.Second):
		t.Fatal("session.started not received")
	}
	select {
	case <-stopped:
	case <-time.After(8 * time.Second):
		t.Fatal("session.stopped not received")
	}
	if exists, _ := (ctmux.Client{Socket: socket}).Exists(context.Background(), sessionID); exists {
		t.Fatal("tmux session should be gone after stop")
	}
}

// TestSessionAttachStreamsOutput proves the daemon streams the Fake CLI banner
// as binary terminal output (kind=2) after session.attach, and replies with a
// contract session.attached frame.
func TestSessionAttachStreamsOutput(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	nodeID := uuid.New()
	sessionID := uuid.New()
	workspaceDir := t.TempDir()
	attached := make(chan struct{}, 1)
	output := make(chan []byte, 64)

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
			mt, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if mt == websocket.BinaryMessage {
				if _, _, payload, e := protocol.DecodeBinary(data); e == nil {
					select {
					case output <- payload:
					default:
					}
				}
				continue
			}
			env, err := protocol.DecodeControl(data)
			if err != nil {
				continue
			}
			switch env.Type {
			case "node.auth":
				f, _ := protocol.BuildControl("node.authenticated", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, f)
			case "node.register":
				ack, _ := protocol.BuildControl("node.registered", nodeID, env.RequestID, map[string]any{"node_id": nodeID.String()}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, ack)
				start, _ := protocol.BuildControl("session.start", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXY7",
					map[string]any{"session_id": sessionID.String(), "runtime": "fake", "workspace": workspaceDir, "rows": 24, "columns": 80}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, start)
			case "session.started":
				at, _ := protocol.BuildControl("session.attach", nodeID, "01K0ABCDEFGHJKMNPQRSTVWXY9",
					map[string]any{"session_id": sessionID.String(), "rows": 24, "columns": 80}, time.Now())
				_ = conn.WriteMessage(websocket.TextMessage, at)
			case "session.attached":
				attached <- struct{}{}
			}
		}
	}
	server := httptest.NewServer(http.HandlerFunc(handler))
	defer server.Close()

	socket := "cliora-att-" + sessionID.String()[:8]
	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm"},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{workspaceDir}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")
	manager.sessions = session.New(ctmux.Client{Socket: socket}, "", "")
	manager.guard = workspace.New([]string{workspaceDir})
	manager.resolveBinary = func(string) (string, error) { return bin, nil }
	defer func() { _ = manager.sessions.Stop(context.Background(), sessionID) }()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() { _ = manager.Run(ctx) }()

	select {
	case <-attached:
	case <-time.After(8 * time.Second):
		t.Fatal("session.attached not received")
	}
	deadline := time.After(8 * time.Second)
	var buf []byte
	for {
		select {
		case chunk := <-output:
			buf = append(buf, chunk...)
			if strings.Contains(string(buf), "FAKECLI_READY") {
				return
			}
		case <-deadline:
			t.Fatalf("did not receive Fake CLI banner as terminal output; got %q", string(buf))
		}
	}
}
