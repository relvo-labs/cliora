package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Reuses writeConfig from tunnel_test.go: one minimal valid config in this package
// is enough, and a second copy would drift.

// Absent means enabled, and the source of that value is recorded: "the operator
// chose this" and "an upgrade defaulted into this" are different facts about a
// machine that now runs codex without a sandbox (ADR 0023 D2).
func TestSandboxBypassDefaultsToEnabledAndRecordsThat(t *testing.T) {
	cfg, err := Load(writeConfig(t, "runtime:\n  codex:\n    enabled: true\n    binary: codex\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !cfg.Runtime["codex"].BypassSandbox() {
		t.Error("an absent sandbox_bypass must mean enabled")
	}
	if !cfg.SandboxBypassFromDefault["codex"] {
		t.Error("the default source was not recorded")
	}
}

func TestExplicitSandboxBypassIsNotTreatedAsADefault(t *testing.T) {
	cfg, err := Load(writeConfig(t,
		"runtime:\n  codex:\n    enabled: true\n    binary: codex\n    sandbox_bypass: false\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Runtime["codex"].BypassSandbox() {
		t.Error("an explicit false must survive")
	}
	if cfg.SandboxBypassFromDefault["codex"] {
		t.Error("an explicit value must not be recorded as a default")
	}
}

// A key that does nothing is worse than a key that is refused: the operator walks
// away believing they turned something off.
func TestSandboxBypassIsRefusedOnRuntimesThatCannotBypass(t *testing.T) {
	for _, id := range []string{"shell", "claude"} {
		_, err := Load(writeConfig(t,
			"runtime:\n  "+id+":\n    enabled: true\n    binary: x\n    sandbox_bypass: true\n"))
		if err == nil {
			t.Errorf("runtime %q accepted sandbox_bypass", id)
			continue
		}
		if !strings.Contains(err.Error(), "sandbox_bypass") {
			t.Errorf("error for %q does not name the offending key: %v", id, err)
		}
	}
}

// A runtime the node does not have must not acquire the key in memory.
func TestSandboxBypassIsNotInventedForAbsentRuntimes(t *testing.T) {
	cfg, err := Load(writeConfig(t, "runtime:\n  claude:\n    enabled: true\n    binary: claude\n"))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if _, present := cfg.Runtime["codex"]; present {
		t.Error("codex was invented by defaulting")
	}
}

func TestScrollbackLimitHonoursTheRequirementFloor(t *testing.T) {
	cases := []struct {
		body string
		want int
	}{
		{"", MinScrollbackLimit},                                        // absent
		{"session:\n  scrollback_limit: 3000\n", MinScrollbackLimit},    // below the floor
		{"session:\n  scrollback_limit: 5000\n", 5000},                  // exactly the floor
		{"session:\n  scrollback_limit: 20000\n", 20000},                // honoured
		{"session:\n  scrollback_limit: 9999999\n", MaxScrollbackLimit}, // clamped
	}
	for _, tc := range cases {
		cfg, err := Load(writeConfig(t, tc.body))
		if err != nil {
			t.Fatalf("Load(%q): %v", tc.body, err)
		}
		if cfg.Session.ScrollbackLimit != tc.want {
			t.Errorf("scrollback for %q = %d, want %d", tc.body, cfg.Session.ScrollbackLimit, tc.want)
		}
	}
}

func TestPrivilegedTerminalDefaultsToFalseWhenAbsent(t *testing.T) {
	// Absent is *not* privileged: the posture is granted by the unit and sudoers, and
	// a node that has not said anything must not be reported as privileged.
	cfg, err := Load(writeConfig(t, ""))
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Node.PrivilegedTerminal {
		t.Error("an absent privileged_terminal must read as false")
	}
}

func TestPrivilegedTerminalRoundTrips(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.yaml")
	body := `server:
  url: wss://central.example.com/ws/nodes
node:
  name: dev-vm-01
  privileged_terminal: true
heartbeat:
  interval_seconds: 10
`
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !cfg.Node.PrivilegedTerminal {
		t.Error("privileged_terminal did not round trip")
	}
}
