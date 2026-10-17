package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
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
		for _, key := range []string{"permission_mode"} {
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
			for _, bypass := range []string{"true", "false", "[true]"} {
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

// Verify yaml.v3 applies merges and explicit-key precedence to the node map
// before using that view for permission-key validation.
func TestRuntimeMergedNodeView(t *testing.T) {
	var document yaml.Node
	if err := yaml.Unmarshal([]byte(`base: &base
  enabled: true
  binary: codex
  permission_mode: null
runtime:
  <<: *base
  permission_mode: cli_default
`), &document); err != nil {
		t.Fatal(err)
	}
	var root map[string]yaml.Node
	if err := document.Decode(&root); err != nil {
		t.Fatal(err)
	}
	node := root["runtime"]
	var merged map[string]yaml.Node
	if err := node.Decode(&merged); err != nil {
		t.Fatal(err)
	}
	if len(merged) != 3 || merged["enabled"].Value != "true" || merged["binary"].Value != "codex" || merged["permission_mode"].Value != "cli_default" {
		t.Fatalf("merged node view = %+v", merged)
	}
}

func TestRuntimePermissionMergeDecoding(t *testing.T) {
	for _, tc := range []struct {
		name, body string
		mode       PermissionMode
		errorText  string
	}{
		{"legacy refusal", "runtime:\n  codex: {<<: {enabled: true, binary: codex}, sandbox_bypass: false}\n", PermissionCLIDefault, ""},
		{"merged mode", "runtime:\n  codex: {<<: {enabled: true, binary: codex, permission_mode: full_access}}\n", PermissionFullAccess, ""},
		{"merged conflict", "runtime:\n  codex: {<<: {sandbox_bypass: false}, permission_mode: auto}\n", "", "keep only permission_mode"},
		{"merge sequence conflict", "runtime:\n  codex: {<<: [{permission_mode: auto}, {sandbox_bypass: false}]}\n", "", "keep only permission_mode"},
		{"merged legacy null beside mode", "runtime:\n  codex: {<<: {sandbox_bypass: null}, permission_mode: full_access}\n", PermissionFullAccess, ""},
		{"merged unknown", "runtime:\n  codex: {<<: {args: [--evil]}}\n", "", "field args not found in type config.RuntimeConfig"},
		{"merged null mode", "runtime:\n  codex: {<<: {permission_mode: null}}\n", "", "permission_mode must not be null"},
		{"merged legacy null bypass", "runtime:\n  codex: {<<: {sandbox_bypass: null}}\n", PermissionAuto, ""},
		{"explicit overrides null", "runtime:\n  codex: {<<: {permission_mode: null}, permission_mode: cli_default}\n", PermissionCLIDefault, ""},
		{"explicit null overrides mode", "runtime:\n  codex: {<<: {permission_mode: auto}, permission_mode: null}\n", "", "permission_mode must not be null"},
		{"explicit refusal overrides legacy true", "runtime:\n  codex: {<<: {sandbox_bypass: true}, sandbox_bypass: false}\n", PermissionCLIDefault, ""},
		{"merge sequence first wins", "runtime:\n  codex: {<<: [{permission_mode: cli_default}, {permission_mode: full_access}]}\n", PermissionCLIDefault, ""},
		{"nested merge", "runtime:\n  codex: {<<: {<<: {permission_mode: full_access}}}\n", PermissionFullAccess, ""},
		{"whole mapping alias", "runtime:\n  shell: &base {enabled: true, binary: codex}\n  codex: *base\n", PermissionAuto, ""},
		{"non mapping scalar", "runtime:\n  codex: invalid\n", "", "cannot unmarshal !!str"},
		{"non mapping sequence", "runtime:\n  codex: [auto]\n", "", "cannot unmarshal !!seq"},
		{"merged mode on claude", "runtime:\n  claude: {<<: {permission_mode: auto}}\n", "", "does not support permission_mode"},
		{"merged bypass on claude", "runtime:\n  claude: {<<: {sandbox_bypass: false}}\n", "", "does not support sandbox_bypass"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			cfg, err := Load(writeConfig(t, tc.body))
			if tc.errorText != "" {
				if err == nil || !strings.Contains(err.Error(), tc.errorText) {
					t.Fatalf("Load error = %v, want %s", err, tc.errorText)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got := cfg.Runtime["codex"].CodexPermissionMode(); got != tc.mode {
				t.Fatalf("mode = %s, want %s", got, tc.mode)
			}
		})
	}
}

func TestRuntimeMergedPermissionKeysRejectNull(t *testing.T) {
	for _, id := range []string{"codex", "claude", "shell"} {
		for _, key := range []string{"permission_mode"} {
			for _, value := range []string{"null", "~", ""} {
				t.Run(id+"/"+key+"/"+value, func(t *testing.T) {
					body := "runtime:\n  " + id + ": {<<: {" + key + ": " + value + "}}\n"
					_, err := Load(writeConfig(t, body))
					if err == nil || !strings.Contains(err.Error(), key+" must not be null") {
						t.Fatalf("Load error = %v, want merged null rejection", err)
					}
				})
			}
		}
	}
}

// Installers before 0.8.0 wrote `sandbox_bypass: null` into every runtime block
// (the field had no omitempty). Upgraded nodes must keep starting (#159): a null
// legacy key is treated as absent, including beside permission_mode.
func TestLegacyNullSandboxBypassIsAbsent(t *testing.T) {
	for _, value := range []string{"null", "~", ""} {
		t.Run("installer-0.7/"+value, func(t *testing.T) {
			cfg, err := Load(writeConfig(t, "runtime:\n"+
				"  shell:\n    enabled: true\n    binary: /usr/bin/bash\n    sandbox_bypass: "+value+"\n"+
				"  claude:\n    enabled: true\n    binary: claude\n    sandbox_bypass: "+value+"\n"+
				"  codex:\n    enabled: true\n    binary: codex\n    sandbox_bypass: "+value+"\n"))
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if got := cfg.Runtime["codex"].CodexPermissionMode(); got != PermissionAuto {
				t.Fatalf("codex mode = %q, want auto", got)
			}
			if cfg.Runtime["shell"].SandboxBypass != nil || cfg.Runtime["claude"].SandboxBypass != nil {
				t.Fatal("null legacy key must not survive as a value on non-codex runtimes")
			}
		})
		t.Run("beside-permission_mode/"+value, func(t *testing.T) {
			cfg, err := Load(writeConfig(t, "runtime:\n  codex:\n    enabled: true\n    binary: codex\n"+
				"    sandbox_bypass: "+value+"\n    permission_mode: full_access\n"))
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if got := cfg.Runtime["codex"].CodexPermissionMode(); got != PermissionFullAccess {
				t.Fatalf("codex mode = %q, want full_access", got)
			}
		})
		t.Run("merged/"+value, func(t *testing.T) {
			cfg, err := Load(writeConfig(t, "runtime:\n  codex: {<<: {sandbox_bypass: "+value+"}, enabled: true, binary: codex}\n"))
			if err != nil {
				t.Fatalf("Load: %v", err)
			}
			if got := cfg.Runtime["codex"].CodexPermissionMode(); got != PermissionAuto {
				t.Fatalf("codex mode = %q, want auto", got)
			}
		})
	}
}
