package main

import (
	"bytes"
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
