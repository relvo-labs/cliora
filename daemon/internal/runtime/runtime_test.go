package runtime

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/config"
)

func writeScript(t *testing.T, name, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestDetectAvailable(t *testing.T) {
	binary := writeScript(t, "claude", `echo "claude version 1.2.3"`)
	rt := &cliRuntime{id: "claude", enabled: true, binary: binary, timeout: 2 * time.Second}
	now := time.Unix(1_700_000_000, 0)
	result := rt.Detect(context.Background(), now)
	if !result.Available || result.Version != "claude version 1.2.3" {
		t.Fatalf("unexpected result: %+v", result)
	}
	if result.BinaryPath != binary || !result.CheckedAt.Equal(now) {
		t.Errorf("path/time wrong: %+v", result)
	}
}

func TestDetectDisabled(t *testing.T) {
	rt := &cliRuntime{id: "codex", enabled: false, timeout: time.Second}
	if r := rt.Detect(context.Background(), time.Now()); r.Available || r.Reason != ReasonDisabled {
		t.Fatalf("expected disabled, got %+v", r)
	}
}

func TestDetectNotFound(t *testing.T) {
	rt := &cliRuntime{id: "claude", enabled: true, binary: "/nonexistent/claude", timeout: time.Second}
	if r := rt.Detect(context.Background(), time.Now()); r.Available || r.Reason != ReasonNotFound {
		t.Fatalf("expected not-found, got %+v", r)
	}
}

func TestDetectNotExecutableOnError(t *testing.T) {
	binary := writeScript(t, "claude", "exit 3")
	rt := &cliRuntime{id: "claude", enabled: true, binary: binary, timeout: 2 * time.Second}
	if r := rt.Detect(context.Background(), time.Now()); r.Available || r.Reason != ReasonNotExecutable {
		t.Fatalf("expected not-executable, got %+v", r)
	}
}

func TestDetectTimeoutDoesNotHang(t *testing.T) {
	binary := writeScript(t, "claude", "sleep 5")
	rt := &cliRuntime{id: "claude", enabled: true, binary: binary, timeout: 100 * time.Millisecond}
	start := time.Now()
	r := rt.Detect(context.Background(), time.Now())
	if r.Available {
		t.Fatal("hung binary must not be reported available")
	}
	if time.Since(start) > 2*time.Second {
		t.Fatal("detection did not honour the timeout")
	}
}

func TestValidate(t *testing.T) {
	binary := writeScript(t, "claude", `echo ok`)
	goodOpts := StartOptions{
		SessionID: uuid.MustParse("00000000-0000-4000-8000-000000000002"),
		Workspace: "/home/neil/work",
		Rows:      24,
		Columns:   80,
	}
	cases := []struct {
		name    string
		rt      *cliRuntime
		opts    StartOptions
		wantErr error
	}{
		{"ok", &cliRuntime{id: "claude", enabled: true, binary: binary}, goodOpts, nil},
		{"disabled", &cliRuntime{id: "claude", enabled: false, binary: binary}, goodOpts, ErrRuntimeDisabled},
		{"empty binary", &cliRuntime{id: "claude", enabled: true, binary: ""}, goodOpts, ErrRuntimeNotFound},
		{"binary not on path", &cliRuntime{id: "claude", enabled: true, binary: "/nonexistent/claude"}, goodOpts, ErrRuntimeNotFound},
		{"nil session", &cliRuntime{id: "claude", enabled: true, binary: binary}, func() StartOptions { o := goodOpts; o.SessionID = uuid.Nil; return o }(), ErrInvalidSession},
		{"relative workspace", &cliRuntime{id: "claude", enabled: true, binary: binary}, func() StartOptions { o := goodOpts; o.Workspace = "rel/path"; return o }(), ErrInvalidWorkspace},
		{"empty workspace", &cliRuntime{id: "claude", enabled: true, binary: binary}, func() StartOptions { o := goodOpts; o.Workspace = ""; return o }(), ErrInvalidWorkspace},
		{"rows too small", &cliRuntime{id: "claude", enabled: true, binary: binary}, func() StartOptions { o := goodOpts; o.Rows = 1; return o }(), ErrInvalidSize},
		{"cols too large", &cliRuntime{id: "claude", enabled: true, binary: binary}, func() StartOptions { o := goodOpts; o.Columns = 501; return o }(), ErrInvalidSize},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if err := c.rt.Validate(c.opts); err != c.wantErr {
				t.Fatalf("Validate() = %v, want %v", err, c.wantErr)
			}
		})
	}
}

func TestRegistryAllowlist(t *testing.T) {
	reg := NewRegistry(map[string]config.RuntimeConfig{
		"claude": {Enabled: true, Binary: "/usr/local/bin/claude"},
	})
	if _, ok := reg.Get("claude"); !ok {
		t.Error("claude should be registered")
	}
	if _, ok := reg.Get("codex"); !ok {
		t.Error("codex should always be present (disabled)")
	}
	if _, ok := reg.Get("bash"); ok {
		t.Error("bash must never be registered")
	}
	results := reg.DetectAll(context.Background(), time.Now())
	if len(results) != 2 || results[0].Runtime != "claude" || results[1].Runtime != "codex" {
		t.Fatalf("expected ordered [claude, codex], got %+v", results)
	}
}
