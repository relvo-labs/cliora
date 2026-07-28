package install

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/runtime"
	"github.com/cliora/cliora/daemon/internal/systeminfo"
)

func TestServerWSURL(t *testing.T) {
	cases := []struct {
		in       string
		wantURL  string
		wantInse bool
		wantErr  bool
	}{
		{"https://platform.example.com", "wss://platform.example.com/ws/nodes", false, false},
		{"https://platform.example.com/", "wss://platform.example.com/ws/nodes", false, false},
		{"http://10.0.0.5:8000", "ws://10.0.0.5:8000/ws/nodes", true, false},
		{"wss://p.example.com", "wss://p.example.com/ws/nodes", false, false},
		{"ftp://p.example.com", "", false, true},
		{"https://", "", false, true},
	}
	for _, c := range cases {
		got, inse, err := ServerWSURL(c.in)
		if c.wantErr {
			if err == nil {
				t.Errorf("ServerWSURL(%q): expected error", c.in)
			}
			continue
		}
		if err != nil {
			t.Errorf("ServerWSURL(%q): unexpected error %v", c.in, err)
			continue
		}
		if got != c.wantURL || inse != c.wantInse {
			t.Errorf("ServerWSURL(%q) = %q,%v want %q,%v", c.in, got, inse, c.wantURL, c.wantInse)
		}
	}
}

func detected(now time.Time) []runtime.DetectResult {
	return []runtime.DetectResult{
		{Runtime: "claude", Available: true, Version: "claude 1.2.3", BinaryPath: "/usr/bin/claude", CheckedAt: now},
		{Runtime: "codex", Available: false, Reason: runtime.ReasonNotFound, CheckedAt: now},
	}
}

func TestBuildConfigValidAndSelective(t *testing.T) {
	now := time.Unix(1700000000, 0).UTC()
	p := Params{
		Server:         "https://platform.example.com",
		NodeName:       "dev-vm-01",
		RunUser:        "neil",
		WorkspaceRoots: []string{"/home/neil/projects"},
		DaemonVersion:  "0.2.0",
	}
	cfg, err := BuildConfig(p, detected(now))
	if err != nil {
		t.Fatalf("BuildConfig: %v", err)
	}
	if cfg.Server.URL != "wss://platform.example.com/ws/nodes" {
		t.Errorf("server url = %q", cfg.Server.URL)
	}
	if cfg.Server.AllowInsecure {
		t.Error("https base must not set allow_insecure")
	}
	if rc, ok := cfg.Runtime["claude"]; !ok || !rc.Enabled || rc.Binary != "/usr/bin/claude" {
		t.Errorf("claude runtime = %+v", rc)
	}
	if _, ok := cfg.Runtime["codex"]; ok {
		t.Error("unavailable codex runtime must be omitted")
	}
	if cfg.Node.Name != "dev-vm-01" || cfg.Heartbeat.IntervalSeconds != 10 {
		t.Errorf("node/heartbeat = %+v / %d", cfg.Node, cfg.Heartbeat.IntervalSeconds)
	}
	// A generated config must round-trip through the real validator.
	if err := cfg.Validate(); err != nil {
		t.Fatalf("generated config invalid: %v", err)
	}
	if out, err := MarshalConfig(cfg); err != nil || !strings.Contains(string(out), "wss://") {
		t.Fatalf("marshal = %q err=%v", out, err)
	}
}

func TestBuildConfigInsecureDevBase(t *testing.T) {
	cfg, err := BuildConfig(Params{Server: "http://127.0.0.1:8000", NodeName: "n"}, nil)
	if err != nil {
		t.Fatalf("BuildConfig: %v", err)
	}
	if !cfg.Server.AllowInsecure || cfg.Server.URL != "ws://127.0.0.1:8000/ws/nodes" {
		t.Errorf("dev base = %q insecure=%v", cfg.Server.URL, cfg.Server.AllowInsecure)
	}
}

func TestBuildRegisterRequest(t *testing.T) {
	now := time.Unix(1700000000, 0).UTC()
	p := Params{
		Token: "enroll_secret", NodeName: "dev-vm-01", RunUser: "neil",
		WorkspaceRoots: []string{"/srv/work"}, DaemonVersion: "0.2.0",
	}
	info := systeminfo.Info{Hostname: "host-a", OS: "linux", OSVersion: "Ubuntu 24.04", Architecture: "amd64"}
	req := BuildRegisterRequest(p, info, detected(now))
	if req.RunUser != "neil" {
		t.Errorf("run_user must be the --user value, got %q", req.RunUser)
	}
	if req.Hostname != "host-a" || req.Architecture != "amd64" || req.DaemonVersion != "0.2.0" {
		t.Errorf("req = %+v", req)
	}
	if len(req.Runtimes) != 2 || req.Runtimes[0].Version == nil || *req.Runtimes[0].Version != "claude 1.2.3" {
		t.Errorf("runtimes = %+v", req.Runtimes)
	}
	if req.Runtimes[1].Available || req.Runtimes[1].Version != nil {
		t.Errorf("unavailable runtime should have no version: %+v", req.Runtimes[1])
	}
	if len(req.WorkspaceRoots) != 1 || !req.WorkspaceRoots[0].IsEnabled {
		t.Errorf("workspace roots = %+v", req.WorkspaceRoots)
	}
}

func TestBuildRegisterRequestHostnameFallback(t *testing.T) {
	req := BuildRegisterRequest(Params{NodeName: "fallback"}, systeminfo.Info{}, nil)
	if req.Hostname != "fallback" {
		t.Errorf("hostname fallback = %q", req.Hostname)
	}
}

func TestUnitFile(t *testing.T) {
	unit := UnitFile(UnitParams{User: "neil", BinaryPath: "/usr/local/bin/agentd", ConfigPath: "/etc/agentd/config.yaml"})
	for _, want := range []string{
		"User=neil", "Group=neil",
		"ExecStart=/usr/local/bin/agentd run --config /etc/agentd/config.yaml",
		"Restart=always", "RestartSec=5", "LimitNOFILE=65535",
		"NoNewPrivileges=true", "PrivateTmp=true",
		"Environment=TERM=xterm-256color",
		"Wants=network-online.target", "WantedBy=multi-user.target",
	} {
		if !strings.Contains(unit, want) {
			t.Errorf("unit missing %q\n%s", want, unit)
		}
	}
	if strings.Contains(unit, "PrivateHome") {
		t.Error("PrivateHome must not be set (would hide user CLI config/workspaces)")
	}
}

func TestRegisterSuccess(t *testing.T) {
	nodeID := uuid.New()
	var gotToken string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/nodes/register" || r.Method != http.MethodPost {
			t.Errorf("unexpected request %s %s", r.Method, r.URL.Path)
		}
		body, _ := io.ReadAll(r.Body)
		var req RegisterRequest
		_ = json.Unmarshal(body, &req)
		gotToken = req.Token
		w.WriteHeader(http.StatusCreated)
		_ = json.NewEncoder(w).Encode(RegisterResponse{
			NodeID: nodeID, ServerURL: "https://platform.example.com",
		})
	}))
	defer srv.Close()

	resp, err := Register(context.Background(), srv.Client(), srv.URL,
		RegisterRequest{Token: "enroll_abc", Name: "n"})
	if err != nil {
		t.Fatalf("Register: %v", err)
	}
	if resp.NodeID != nodeID {
		t.Errorf("resp = %+v", resp)
	}
	if gotToken != "enroll_abc" {
		t.Errorf("token not sent, got %q", gotToken)
	}
}

func TestRegisterRejectedIsSafe(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":{"code":"ENROLLMENT_TOKEN_INVALID","message":"token invalid"}}`))
	}))
	defer srv.Close()

	_, err := Register(context.Background(), srv.Client(), srv.URL,
		RegisterRequest{Token: "enroll_should_not_leak", Name: "n"})
	if err == nil {
		t.Fatal("expected rejection error")
	}
	if !strings.Contains(err.Error(), "ENROLLMENT_TOKEN_INVALID") {
		t.Errorf("error should carry the stable code: %v", err)
	}
	if strings.Contains(err.Error(), "enroll_should_not_leak") {
		t.Error("token must never appear in the error")
	}
}

// A generated config must carry the P3 filesystem policy explicitly and survive
// a marshal → Load round trip with it intact. Regression for the P3-10 finding:
// the generated config left the policy lists nil, yaml wrote them as `[]`, and
// load-time defaulting (nil-only at the time) skipped them — so an enrolled node
// denied *nothing* and excluded *nothing* (SEC-004 / FR-FILE-005).
func TestGeneratedConfigCarriesFilesystemPolicy(t *testing.T) {
	cfg, err := BuildConfig(Params{
		Server:         "https://platform.example.com",
		NodeName:       "dev-vm-01",
		WorkspaceRoots: []string{"/home/neil/projects"},
	}, nil)
	if err != nil {
		t.Fatalf("BuildConfig: %v", err)
	}
	if len(cfg.Filesystem.DeniedPatterns) != len(config.DefaultDeniedPatterns) {
		t.Errorf("denied_patterns = %v", cfg.Filesystem.DeniedPatterns)
	}
	if len(cfg.Filesystem.DeniedDirectories) != len(config.DefaultDeniedDirectories) {
		t.Errorf("denied_directories = %v", cfg.Filesystem.DeniedDirectories)
	}
	if len(cfg.Workspace.ExcludedDirectories) != len(config.DefaultExcludedDirs) {
		t.Errorf("excluded_directories = %v", cfg.Workspace.ExcludedDirectories)
	}
	if cfg.Filesystem.Search.MaxDepth != config.DefaultSearchMaxDepth ||
		cfg.Filesystem.Search.MaxResults != config.DefaultSearchMaxResults ||
		cfg.Filesystem.Search.MaxScanned != config.DefaultSearchMaxScanned ||
		cfg.Filesystem.Search.TimeoutSeconds != config.DefaultSearchTimeoutSec {
		t.Errorf("search bounds = %+v", cfg.Filesystem.Search)
	}

	// Round trip exactly as enrollment does: marshal to config.yaml, load back.
	out, err := MarshalConfig(cfg)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if !strings.Contains(string(out), ".env") || !strings.Contains(string(out), "node_modules") {
		t.Fatalf("generated config lost its policy:\n%s", out)
	}
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, out, 0o600); err != nil {
		t.Fatal(err)
	}
	loaded, err := config.Load(path)
	if err != nil {
		t.Fatalf("load generated config: %v", err)
	}
	if len(loaded.Filesystem.DeniedPatterns) == 0 || len(loaded.Workspace.ExcludedDirectories) == 0 {
		t.Fatalf("policy did not survive the round trip: %+v", loaded.Filesystem)
	}
}

// TestGeneratedConfigCarriesThePublishedScrollback pins FR-TERM-004: the daemon a
// one-line install produces keeps at least the scrollback the PRD promises, on
// the tmux backend the PRD says MVP uses. Reconnect replays that buffer, so a
// change here shortens what every returning user can see.
func TestGeneratedConfigCarriesThePublishedScrollback(t *testing.T) {
	now := time.Unix(1700000000, 0).UTC()
	cfg, err := BuildConfig(Params{
		Server:         "https://platform.example.com",
		NodeName:       "dev-vm-01",
		RunUser:        "neil",
		WorkspaceRoots: []string{"/home/neil/projects"},
		DaemonVersion:  "0.2.0",
	}, detected(now))
	if err != nil {
		t.Fatalf("BuildConfig: %v", err)
	}
	if cfg.Session.Backend != "tmux" {
		t.Errorf("session backend = %q, PRD FR-TERM-004 uses tmux scrollback", cfg.Session.Backend)
	}
	if cfg.Session.ScrollbackLimit < 5000 {
		t.Errorf("scrollback limit = %d, PRD FR-TERM-004 promises at least 5000 lines",
			cfg.Session.ScrollbackLimit)
	}
}
