package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Reuses writeConfig from tunnel_test.go: one minimal valid config in this package
// is enough, and a second copy would drift.

// Both upgrades and explicit choices retain their source; legacy true must
// never remain an opt-in to full access (ADR 0030).
func TestCodexPermissionModes(t *testing.T) {
	for _, tc := range []struct {
		name, keys        string
		mode              PermissionMode
		source, errorText string
	}{
		{"absent", "", PermissionAuto, "default", ""},
		{"legacy true", "    sandbox_bypass: true\n", PermissionAuto, "legacy-key", ""},
		{"legacy false", "    sandbox_bypass: false\n", PermissionCLIDefault, "legacy-key", ""},
		{"auto", "    permission_mode: auto\n", PermissionAuto, "config", ""},
		{"cli default", "    permission_mode: cli_default\n", PermissionCLIDefault, "config", ""},
		{"full access", "    permission_mode: full_access\n", PermissionFullAccess, "config", ""},
		{"both", "    permission_mode: auto\n    sandbox_bypass: false\n", "", "", "keep only permission_mode"},
		{"unknown", "    permission_mode: --evil\n", "", "", "unknown"},
		{"empty", "    permission_mode: \"\"\n", "", "", "unknown"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			cfg, err := Load(writeConfig(t, "runtime:\n  codex:\n    enabled: true\n    binary: codex\n"+tc.keys))
			if tc.errorText != "" {
				if err == nil || !strings.Contains(err.Error(), tc.errorText) {
					t.Fatalf("Load error = %v, want %s", err, tc.errorText)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			rc := cfg.Runtime["codex"]
			if rc.CodexPermissionMode() != tc.mode || rc.CodexPermissionSource() != tc.source {
				t.Fatalf("got %+v, want %s from %s", rc, tc.mode, tc.source)
			}
		})
	}
}

func TestPermissionModeIsRefusedOnOtherRuntimes(t *testing.T) {
	for _, id := range []string{"claude", "shell"} {
		_, err := Load(writeConfig(t, "runtime:\n  "+id+":\n    enabled: true\n    binary: x\n    permission_mode: auto\n"))
		if err == nil || !strings.Contains(err.Error(), "does not support permission_mode") {
			t.Fatalf("runtime %s: %v", id, err)
		}
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
		{"", MinScrollbackLimit}, // absent
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

func TestRuntimePermissionKeysRejectNull(t *testing.T) {
	for _, id := range []string{"codex", "claude", "shell"} {
		for _, key := range []string{"permission_mode", "sandbox_bypass"} {
			for _, value := range []string{"null", "~", ""} {
				t.Run(id+"/"+key+"/"+value, func(t *testing.T) {
					_, err := Load(writeConfig(t, "runtime:\n  "+id+":\n    enabled: true\n    binary: x\n    "+key+": "+value+"\n"))
					if err == nil || !strings.Contains(err.Error(), key) || !strings.Contains(err.Error(), "null") {
						t.Fatalf("Load error = %v, want %s null rejection", err, key)
					}
				})
			}
		}
	}
}

func TestRuntimePermissionKeyConflictsIncludeNull(t *testing.T) {
	for _, id := range []string{"codex", "claude", "shell"} {
		for _, mode := range []string{"auto", "cli_default", "full_access", "null", "~", "", "unknown", "[auto]"} {
			for _, bypass := range []string{"true", "false", "null", "~", "", "[true]"} {
				t.Run(id+"/"+mode+"/"+bypass, func(t *testing.T) {
					keys := "    permission_mode: " + mode + "\n    sandbox_bypass: " + bypass + "\n"
					_, err := Load(writeConfig(t, "runtime:\n  "+id+":\n    enabled: true\n    binary: x\n"+keys))
					if err == nil || !strings.Contains(err.Error(), "keep only permission_mode") {
						t.Fatalf("Load error = %v, want both-keys rejection", err)
					}
				})
			}
		}
	}
}

func TestRuntimeConfigStillRejectsUnknownFields(t *testing.T) {
	_, err := Load(writeConfig(t, "runtime:\n  codex:\n    enabled: true\n    binary: codex\n    permission_mode: auto\n    args: [--evil]\n"))
	if err == nil || !strings.Contains(err.Error(), "args") {
		t.Fatalf("Load error = %v, want unknown field rejection", err)
	}
}
