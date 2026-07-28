//go:build integration

// End-to-end P3-04/05 over the production connection dispatch: a real session is
// launched (tmux + Fake CLI) so the daemon knows its workspace, then
// filesystem.list / read / search are driven over the wire exactly as Central
// sends them. Asserts the real responses, the denial policy, and that no
// server absolute path appears in any frame. Guarded by the `integration` tag;
// skipped without tmux.
package connection

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/metrics"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/session"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/cliora/cliora/daemon/internal/workspace"
)

// fsFixture lays out a workspace with previewable, sensitive, binary and
// oversize files plus an excluded directory and a symlink pointing at the
// sensitive file.
func fsFixture(t *testing.T) string {
	t.Helper()
	ws := t.TempDir()
	for _, d := range []string{"src", "node_modules/pkg"} {
		if err := os.MkdirAll(filepath.Join(ws, d), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	write := func(rel, body string) {
		if err := os.WriteFile(filepath.Join(ws, rel), []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write("main.go", "package main\n\nfunc main() {}\n")
	write("src/app.py", "print('hello')\n")
	write(".env", "SECRET_TOKEN=super-secret-value\n")
	write("bin.dat", "\x00\x01\x02\x00binary\x00")
	write("node_modules/pkg/index.js", "module.exports = 1\n")
	// Oversize relative to the 1 KiB cap this test configures.
	write("big.log", strings.Repeat("x", 4096))
	if err := os.Symlink(filepath.Join(ws, ".env"), filepath.Join(ws, "link.txt")); err != nil {
		t.Fatal(err)
	}
	return ws
}

// fsResponse is one correlated daemon reply.
type fsResponse struct {
	typ     string
	success bool
	payload map[string]any
	code    string
	raw     string
}

// fsHarness runs a fake Central that authenticates the daemon, starts one real
// session, and then lets the test drive filesystem requests synchronously.
type fsHarness struct {
	t         *testing.T
	nodeID    uuid.UUID
	sessionID uuid.UUID
	conn      *websocket.Conn
	writeMu   sync.Mutex
	replies   chan fsResponse
	seq       int
}

// requestID returns a fresh 26-character ULID-shaped id; the daemon echoes it
// back so each reply is correlated to its request.
func (h *fsHarness) requestID() string {
	h.seq++
	return fmt.Sprintf("01K0FSTEST%016d", h.seq)
}

func (h *fsHarness) request(typ string, payload map[string]any) fsResponse {
	h.t.Helper()
	frame, err := protocol.BuildControl(typ, h.nodeID, h.requestID(), payload, time.Now())
	if err != nil {
		h.t.Fatalf("build %s: %v", typ, err)
	}
	h.writeMu.Lock()
	err = h.conn.WriteMessage(websocket.TextMessage, frame)
	h.writeMu.Unlock()
	if err != nil {
		h.t.Fatalf("send %s: %v", typ, err)
	}
	select {
	case reply := <-h.replies:
		return reply
	case <-time.After(10 * time.Second):
		h.t.Fatalf("no reply to %s", typ)
		return fsResponse{}
	}
}

func startFsHarness(t *testing.T, ws string) *fsHarness {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	nodeID := uuid.New()
	sessionID := uuid.New()
	h := &fsHarness{t: t, nodeID: nodeID, sessionID: sessionID, replies: make(chan fsResponse, 8)}
	started := make(chan struct{}, 1)
	ready := make(chan *websocket.Conn, 1)

	upgrader := websocket.Upgrader{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		challenge, _ := protocol.BuildControl("node.challenge", nodeID, "01K0FSCHALLENGE0000000000A",
			map[string]any{"nonce": base64.StdEncoding.EncodeToString(make([]byte, 32))}, time.Now())
		_ = conn.WriteMessage(websocket.TextMessage, challenge)
		for {
			mt, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if mt == websocket.BinaryMessage {
				continue
			}
			env, err := protocol.DecodeControl(data)
			if err != nil {
				continue
			}
			switch env.Type {
			case "node.auth":
				f, _ := protocol.BuildControl("node.authenticated", nodeID, env.RequestID,
					map[string]any{"node_id": nodeID.String()}, time.Now())
				h.writeMu.Lock()
				_ = conn.WriteMessage(websocket.TextMessage, f)
				h.writeMu.Unlock()
			case "node.register":
				ack, _ := protocol.BuildControl("node.registered", nodeID, env.RequestID,
					map[string]any{"node_id": nodeID.String()}, time.Now())
				h.writeMu.Lock()
				_ = conn.WriteMessage(websocket.TextMessage, ack)
				h.writeMu.Unlock()
				ready <- conn
			case "session.started":
				started <- struct{}{}
			case "filesystem.entries", "filesystem.content", "filesystem.search_result", "error":
				payload := map[string]any{}
				_ = json.Unmarshal(env.Payload, &payload)
				// The Envelope type carries no error field; read it off the wire.
				var wire struct {
					Error struct {
						Code string `json:"code"`
					} `json:"error"`
				}
				_ = json.Unmarshal(data, &wire)
				h.replies <- fsResponse{
					typ:     env.Type,
					success: env.Success != nil && *env.Success,
					payload: payload,
					code:    wire.Error.Code,
					raw:     string(data),
				}
			}
		}
	}))
	t.Cleanup(server.Close)

	socket := "cliora-fs-" + sessionID.String()[:8]
	cfg := &config.Config{
		Server:    config.ServerConfig{URL: strings.Replace(server.URL, "http", "ws", 1) + "/ws/nodes"},
		Node:      config.NodeConfig{Name: "vm"},
		Workspace: config.WorkspaceConfig{AllowedRoots: []string{ws}},
		Heartbeat: config.HeartbeatConfig{IntervalSeconds: 1},
	}
	// A small preview cap so the fixture's 4 KiB file is oversize.
	cfg.Filesystem.MaxPreviewSize = 1024
	cfg.Filesystem.DeniedPatterns = config.DefaultDeniedPatterns
	cfg.Filesystem.DeniedDirectories = config.DefaultDeniedDirectories
	cfg.Workspace.ExcludedDirectories = config.DefaultExcludedDirs
	cfg.Filesystem.Search = config.SearchConfig{
		MaxDepth:       config.DefaultSearchMaxDepth,
		MaxResults:     config.DefaultSearchMaxResults,
		MaxScanned:     config.DefaultSearchMaxScanned,
		TimeoutSeconds: config.DefaultSearchTimeoutSec,
	}

	_, private, _ := ed25519.GenerateKey(rand.Reader)
	creds := &config.Credentials{NodeID: nodeID, PrivateKey: base64.StdEncoding.EncodeToString(private)}
	manager := New(cfg, creds, runtime.NewRegistry(cfg.Runtime), systeminfo.Gather(), "1.0.0")
	manager.sessions = session.New(ctmux.Client{Socket: socket}, "", "")
	manager.guard = workspace.New([]string{ws})
	manager.resolveBinary = func(string) (string, error) { return bin, nil }
	t.Cleanup(func() { _, _ = manager.sessions.Stop(context.Background(), sessionID) })

	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go func() { _ = manager.Run(ctx) }()

	var conn *websocket.Conn
	select {
	case conn = <-ready:
	case <-time.After(10 * time.Second):
		t.Fatal("daemon did not register")
	}
	h.conn = conn

	start, _ := protocol.BuildControl("session.start", nodeID, "01K0FSSTART00000000000000A",
		map[string]any{
			"session_id": sessionID.String(), "runtime": "fake",
			"workspace": ws, "rows": 24, "columns": 80,
		}, time.Now())
	h.writeMu.Lock()
	_ = conn.WriteMessage(websocket.TextMessage, start)
	h.writeMu.Unlock()
	select {
	case <-started:
	case <-time.After(10 * time.Second):
		t.Fatal("session.started not received")
	}
	return h
}

func TestFilesystemListOverConnection(t *testing.T) {
	ws := fsFixture(t)
	h := startFsHarness(t, ws)

	reply := h.request("filesystem.list", map[string]any{
		"session_id": h.sessionID.String(), "path": ".",
	})
	if reply.typ != "filesystem.entries" {
		t.Fatalf("type = %s (code %s)", reply.typ, reply.code)
	}
	entries, _ := reply.payload["entries"].([]any)
	byName := map[string]map[string]any{}
	for _, raw := range entries {
		e, _ := raw.(map[string]any)
		byName[e["name"].(string)] = e
	}
	// Directories first, deterministic ordering.
	if entries[0].(map[string]any)["type"] != "directory" {
		t.Fatalf("expected directories first, got %v", entries[0])
	}
	// node_modules is listed but not expandable (shown-not-loaded, ADR 0015).
	nm := byName["node_modules"]
	if nm["excluded"] != true || nm["expandable"] != false {
		t.Fatalf("node_modules = %v, want excluded and non-expandable", nm)
	}
	if byName[".env"]["hidden"] != true {
		t.Fatalf(".env should be marked hidden: %v", byName[".env"])
	}
	if byName["link.txt"]["symlink"] != true {
		t.Fatalf("link.txt should be marked symlink: %v", byName["link.txt"])
	}
	// No server absolute path in the listing.
	if strings.Contains(reply.raw, ws) {
		t.Fatal("listing leaked the workspace absolute path")
	}
	if got := metrics.CounterValue(metrics.FilesystemRequestTotal,
		map[string]string{"op": "list", "code": "OK"}); got == 0 {
		t.Fatal("list was not counted")
	}
}

func TestFilesystemReadPolicyOverConnection(t *testing.T) {
	ws := fsFixture(t)
	h := startFsHarness(t, ws)

	// 1. A normal source file previews with content, language and encoding.
	ok := h.request("filesystem.read", map[string]any{
		"session_id": h.sessionID.String(), "path": "src/app.py",
	})
	if ok.typ != "filesystem.content" || !ok.success {
		t.Fatalf("read src/app.py = %s success=%v", ok.typ, ok.success)
	}
	if ok.payload["content"] != "print('hello')\n" {
		t.Fatalf("content = %v", ok.payload["content"])
	}
	if ok.payload["language_hint"] != "python" || ok.payload["encoding"] != "utf-8" {
		t.Fatalf("metadata = %v", ok.payload)
	}

	cases := []struct {
		name, path, wantCode, wantReason string
	}{
		{"dotenv", ".env", "FILE_DENIED", "dotenv"},
		{"symlink to dotenv", "link.txt", "FILE_DENIED", ""},
		{"binary", "bin.dat", "FILE_BINARY", ""},
		{"oversize", "big.log", "FILE_TOO_LARGE", ""},
		{"traversal", "../etc/passwd", "", ""},
		{"missing", "nope.txt", "FILE_NOT_FOUND", "not_found"},
	}
	for _, tc := range cases {
		reply := h.request("filesystem.read", map[string]any{
			"session_id": h.sessionID.String(), "path": tc.path,
		})
		// A traversal attempt is rejected outright (invalid message / workspace).
		if tc.wantCode == "" {
			if reply.success {
				t.Fatalf("%s: expected rejection, got success", tc.name)
			}
			continue
		}
		if reply.typ != "filesystem.content" || reply.success {
			t.Fatalf("%s: type=%s success=%v code=%s", tc.name, reply.typ, reply.success, reply.code)
		}
		errObj, _ := reply.payload["error"].(map[string]any)
		if errObj["code"] != tc.wantCode {
			t.Fatalf("%s: code = %v, want %s", tc.name, errObj["code"], tc.wantCode)
		}
		if tc.wantReason != "" && errObj["reason"] != tc.wantReason {
			t.Fatalf("%s: reason = %v, want %s", tc.name, errObj["reason"], tc.wantReason)
		}
		// No content and no absolute path in any denial.
		if _, has := reply.payload["content"]; has {
			t.Fatalf("%s: denial carried content", tc.name)
		}
		if strings.Contains(reply.raw, ws) {
			t.Fatalf("%s: denial leaked the workspace absolute path", tc.name)
		}
		if strings.Contains(reply.raw, "SECRET_TOKEN") {
			t.Fatalf("%s: denial leaked file content", tc.name)
		}
	}
}

func TestFilesystemSearchOverConnection(t *testing.T) {
	ws := fsFixture(t)
	h := startFsHarness(t, ws)

	reply := h.request("filesystem.search", map[string]any{
		"session_id": h.sessionID.String(), "keyword": "app",
	})
	if reply.typ != "filesystem.search_result" {
		t.Fatalf("type = %s (code %s)", reply.typ, reply.code)
	}
	results, _ := reply.payload["results"].([]any)
	if len(results) != 1 {
		t.Fatalf("results = %v, want just src/app.py", results)
	}
	first := results[0].(map[string]any)
	if first["rel_path"] != "src/app.py" {
		t.Fatalf("rel_path = %v", first["rel_path"])
	}
	// The excluded directory is not descended, so its index.js never matches.
	deep := h.request("filesystem.search", map[string]any{
		"session_id": h.sessionID.String(), "keyword": "index",
	})
	if got, _ := deep.payload["results"].([]any); len(got) != 0 {
		t.Fatalf("search descended into an excluded directory: %v", got)
	}
	// Bounded: max_results caps the reply and marks it partial.
	capped := h.request("filesystem.search", map[string]any{
		"session_id": h.sessionID.String(), "keyword": ".", "max_results": 1,
	})
	got, _ := capped.payload["results"].([]any)
	if len(got) != 1 || capped.payload["partial"] != true {
		t.Fatalf("capped search = %v partial=%v", got, capped.payload["partial"])
	}
	if capped.payload["stopped_reason"] != "results" {
		t.Fatalf("stopped_reason = %v, want results", capped.payload["stopped_reason"])
	}
	if strings.Contains(reply.raw, ws) {
		t.Fatal("search result leaked the workspace absolute path")
	}
}
