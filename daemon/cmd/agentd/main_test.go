package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/cliora/cliora/daemon/internal/config"
)

func runCommand(t *testing.T, args ...string) (string, error) {
	t.Helper()
	cmd := newRootCommand()
	out := &bytes.Buffer{}
	cmd.SetOut(out)
	cmd.SetErr(out)
	cmd.SetArgs(args)
	err := cmd.Execute()
	return out.String(), err
}

func TestVersionCommand(t *testing.T) {
	out, err := runCommand(t, "version")
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(out) != version {
		t.Errorf("version output = %q", out)
	}
}

// The unstamped development version and both CLI formats must follow the declared
// release base while retaining -dev. Derive the expectation rather than duplicating
// the patch number in the regression.
func TestVersionMatchesTheVersionFile(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "VERSION"))
	if err != nil {
		t.Fatal(err)
	}
	want := strings.TrimSpace(string(raw)) + "-dev"
	if version != want {
		t.Errorf("main.version = %q, but daemon/VERSION implies %q", version, want)
	}
	t.Run("plain", func(t *testing.T) {
		out, err := runCommand(t, "version")
		if err != nil {
			t.Fatal(err)
		}
		if out != want+"\n" {
			t.Errorf("version output = %q, want %q", out, want+"\n")
		}
	})
	t.Run("json", func(t *testing.T) {
		out, err := runCommand(t, "version", "--json")
		if err != nil {
			t.Fatal(err)
		}
		var payload map[string]string
		if err := json.Unmarshal([]byte(out), &payload); err != nil {
			t.Fatal(err)
		}
		if payload["version"] != want {
			t.Errorf("JSON version = %q, want %q", payload["version"], want)
		}
	})
}

func TestConfigValidateCommand(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	content := "server:\n  url: wss://x/ws\nnode:\n  name: n\nheartbeat:\n  interval_seconds: 10\n"
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	out, err := runCommand(t, "config", "validate", "--config", path)
	if err != nil {
		t.Fatalf("unexpected error: %v (%s)", err, out)
	}
	if !strings.Contains(out, "config OK") {
		t.Errorf("output = %q", out)
	}
}

func TestConfigValidateRejectsBadConfig(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte("server:\n  url: ''\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := runCommand(t, "config", "validate", "--config", path); err == nil {
		t.Fatal("expected validation error")
	}
}

// TestInstallLayoutMatchesTheDocumentedPaths pins the filesystem layout that
// PRD FR-INSTALL-003 promises. Moving any of these is a user-visible change to
// the install contract, not an implementation detail.
func TestInstallLayoutMatchesTheDocumentedPaths(t *testing.T) {
	for _, tc := range []struct{ name, got, want string }{
		{"binary", binaryInstallPath, "/usr/local/bin/agentd"},
		{"state", stateDir, "/var/lib/agentd"},
		{"unit", systemdUnitPath, "/etc/systemd/system/agentd.service"},
		{"config", config.DefaultConfigPath, "/etc/agentd/config.yaml"},
	} {
		if tc.got != tc.want {
			t.Errorf("%s path = %q, the documented install layout is %q", tc.name, tc.got, tc.want)
		}
	}
}
