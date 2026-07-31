package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const validConfig = `
server:
  url: wss://central.example.com/ws/nodes
node:
  name: dev-vm-01
runtime:
  claude:
    enabled: true
    binary: /usr/local/bin/claude
  codex:
    enabled: false
    binary: ""
workspace:
  allowed_roots:
    - /home/neil/work
heartbeat:
  interval_seconds: 10
session:
  backend: tmux
`

func writeFile(t *testing.T, name, content string, mode os.FileMode) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadValidConfig(t *testing.T) {
	cfg, err := Load(writeFile(t, "config.yaml", validConfig, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Node.Name != "dev-vm-01" {
		t.Errorf("node name = %q", cfg.Node.Name)
	}
	if !cfg.Runtime["claude"].Enabled || cfg.Runtime["codex"].Enabled {
		t.Errorf("runtime enable flags wrong: %+v", cfg.Runtime)
	}
}

func TestLoadRejectsGroupReadablePerms(t *testing.T) {
	if _, err := Load(writeFile(t, "config.yaml", validConfig, 0o644)); err == nil {
		t.Fatal("expected permission rejection for 0644")
	}
}

func TestLoadRejectsUnknownField(t *testing.T) {
	bad := validConfig + "\nunexpected_top: true\n"
	if _, err := Load(writeFile(t, "config.yaml", bad, 0o600)); err == nil {
		t.Fatal("expected unknown-field rejection")
	}
}

func TestValidateRejectsUnknownRuntime(t *testing.T) {
	bad := `
server: {url: "wss://x/ws"}
node: {name: n}
runtime:
  bash: {enabled: true, binary: /bin/bash}
heartbeat: {interval_seconds: 10}
`
	if _, err := Load(writeFile(t, "config.yaml", bad, 0o600)); err == nil {
		t.Fatal("expected unknown-runtime rejection")
	}
}

// withShell splices a runtime.shell block into validConfig. Appending to the
// string would land it under `session:`, where strict parsing rejects it — and
// the test would then "pass" on a YAML error rather than on the behaviour.
func withShell(body string) string {
	const anchor = "  codex:\n    enabled: false\n    binary: \"\"\n"
	if !strings.Contains(validConfig, anchor) {
		panic("validConfig no longer has the codex runtime block")
	}
	return strings.Replace(validConfig, anchor, anchor+body, 1)
}

// ADR 0021 / D6. Three cases, because the interesting one is the third: a
// default that quietly overrides an operator's "no" would hand out remote shells
// on the nodes whose owners specifically refused them.
func TestShellRuntimeDefaultsToEnabledWhenAbsent(t *testing.T) {
	// validConfig names claude and codex only.
	cfg, err := Load(writeFile(t, "config.yaml", validConfig, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	shell := cfg.Runtime[ShellRuntimeID]
	if !shell.Enabled {
		t.Error("an absent runtime.shell block must default to enabled")
	}
	if shell.Binary != DefaultShellBinary {
		t.Errorf("binary = %q, want %q", shell.Binary, DefaultShellBinary)
	}
	if !cfg.ShellFromDefault {
		t.Error("ShellFromDefault must record that this came from the default")
	}
}

func TestShellRuntimeHonoursExplicitConfig(t *testing.T) {
	cfg, err := Load(writeFile(t, "config.yaml",
		withShell("  shell:\n    enabled: true\n    binary: /usr/bin/zsh\n"), 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Runtime[ShellRuntimeID].Binary != "/usr/bin/zsh" {
		t.Errorf("binary = %q", cfg.Runtime[ShellRuntimeID].Binary)
	}
	if cfg.ShellFromDefault {
		t.Error("an explicit block is not the default")
	}
}

func TestShellRuntimeDisabledIsNotOverwrittenByTheDefault(t *testing.T) {
	cfg, err := Load(writeFile(t, "config.yaml",
		withShell("  shell:\n    enabled: false\n    binary: \"\"\n"), 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Runtime[ShellRuntimeID].Enabled {
		t.Fatal("an explicit `enabled: false` must survive the default")
	}
	if cfg.ShellFromDefault {
		t.Error("ShellFromDefault must be false when the operator wrote the block")
	}
}

func TestValidateRejectsEnabledShellWithoutBinary(t *testing.T) {
	bad := withShell("  shell:\n    enabled: true\n    binary: \"\"\n")
	if _, err := Load(writeFile(t, "config.yaml", bad, 0o600)); err == nil {
		t.Fatal("expected rejection: enabled runtime with no binary")
	}
}

func TestValidateRejectsInsecureURL(t *testing.T) {
	bad := `
server: {url: "ws://x/ws"}
node: {name: n}
heartbeat: {interval_seconds: 10}
`
	if _, err := Load(writeFile(t, "config.yaml", bad, 0o600)); err == nil {
		t.Fatal("expected ws:// rejection without allow_insecure")
	}
	ok := `
server: {url: "ws://x/ws", allow_insecure: true}
node: {name: n}
heartbeat: {interval_seconds: 10}
`
	if _, err := Load(writeFile(t, "config.yaml", ok, 0o600)); err != nil {
		t.Fatalf("allow_insecure ws:// should pass: %v", err)
	}
}

func TestValidateRejectsRelativeRoot(t *testing.T) {
	bad := `
server: {url: "wss://x/ws"}
node: {name: n}
workspace: {allowed_roots: ["relative/path"]}
heartbeat: {interval_seconds: 10}
`
	if _, err := Load(writeFile(t, "config.yaml", bad, 0o600)); err == nil {
		t.Fatal("expected relative-root rejection")
	}
}

func TestLoadCredentials(t *testing.T) {
	_, privateKey, err := GenerateKeypair()
	if err != nil {
		t.Fatal(err)
	}
	content := "node_id: 00000000-0000-4000-8000-000000000001\nprivate_key: " + privateKey + "\n"
	creds, err := LoadCredentials(writeFile(t, "credentials.yaml", content, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if _, err := creds.SigningKey(); err != nil {
		t.Errorf("private key: %v", err)
	}
	if _, err := LoadCredentials(writeFile(t, "c2.yaml", "node_id: \"\"\n", 0o600)); err == nil {
		t.Fatal("expected rejection of empty credentials")
	}
	if _, err := LoadCredentials(writeFile(t, "c3.yaml", content, 0o644)); err == nil {
		t.Fatal("expected permission rejection")
	}
}

func TestFilesystemMaxPreviewSizeDefault(t *testing.T) {
	// validConfig omits filesystem, so the documented default is applied.
	cfg, err := Load(writeFile(t, "config.yaml", validConfig, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Filesystem.MaxPreviewSize != DefaultMaxPreviewSize {
		t.Errorf("max_preview_size = %d, want default %d", cfg.Filesystem.MaxPreviewSize, DefaultMaxPreviewSize)
	}
}

func TestFilesystemMaxPreviewSizeExplicit(t *testing.T) {
	content := validConfig + "\nfilesystem:\n  max_preview_size: 1048576\n"
	cfg, err := Load(writeFile(t, "config.yaml", content, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.Filesystem.MaxPreviewSize != 1048576 {
		t.Errorf("max_preview_size = %d, want 1048576", cfg.Filesystem.MaxPreviewSize)
	}
}

func TestFilesystemMaxPreviewSizeRejectsNegative(t *testing.T) {
	content := validConfig + "\nfilesystem:\n  max_preview_size: -1\n"
	if _, err := Load(writeFile(t, "config.yaml", content, 0o600)); err == nil {
		t.Fatal("expected rejection of negative max_preview_size")
	}
}

func TestFilesystemRejectsUnknownField(t *testing.T) {
	content := validConfig + "\nfilesystem:\n  max_preview_size: 1024\n  bogus: 1\n"
	if _, err := Load(writeFile(t, "config.yaml", content, 0o600)); err == nil {
		t.Fatal("expected unknown-field rejection under filesystem")
	}
}

func TestEnsureNonRoot(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("running as root")
	}
	if err := EnsureNonRoot(); err != nil {
		t.Errorf("expected nil for non-root, got %v", err)
	}
}

// An *empty* denied list must not disable the sensitive-file policy. This is the
// shape a generated config takes: yaml.Marshal writes a nil slice as `[]`, which
// decodes back non-nil but empty, so a nil-only default check shipped nodes with
// no sensitive-file protection at all (found by the P3-10 full-stack E2E).
func TestEmptyDeniedListsFallBackToDefaults(t *testing.T) {
	content := validConfig + "\nfilesystem:\n  denied_patterns: []\n  denied_directories: []\n"
	cfg, err := Load(writeFile(t, "config.yaml", content, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Filesystem.DeniedPatterns) != len(DefaultDeniedPatterns) {
		t.Errorf("denied_patterns = %v, want the defaults", cfg.Filesystem.DeniedPatterns)
	}
	if len(cfg.Filesystem.DeniedDirectories) != len(DefaultDeniedDirectories) {
		t.Errorf("denied_directories = %v, want the defaults", cfg.Filesystem.DeniedDirectories)
	}
}

func TestExplicitDeniedListsReplaceDefaults(t *testing.T) {
	content := validConfig + "\nfilesystem:\n  denied_patterns:\n    - \"*.custom\"\n"
	cfg, err := Load(writeFile(t, "config.yaml", content, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Filesystem.DeniedPatterns) != 1 || cfg.Filesystem.DeniedPatterns[0] != "*.custom" {
		t.Errorf("denied_patterns = %v, want the operator's list", cfg.Filesystem.DeniedPatterns)
	}
}

// excluded_directories is an ignore rule, not a security control: an explicit
// empty list means "load everything" and must be honoured.
func TestExplicitEmptyExcludedDirectoriesIsHonoured(t *testing.T) {
	content := strings.Replace(
		validConfig,
		"    - /home/neil/work\n",
		"    - /home/neil/work\n  excluded_directories: []\n",
		1,
	)
	cfg, err := Load(writeFile(t, "config.yaml", content, 0o600))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Workspace.ExcludedDirectories) != 0 {
		t.Errorf("excluded_directories = %v, want none", cfg.Workspace.ExcludedDirectories)
	}
}
