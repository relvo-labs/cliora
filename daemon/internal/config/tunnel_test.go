package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The node's port-forwarding settings are a veto and a narrowing, never a second enable
// switch (ADR 0022 D3/D17). These tests hold that shape, because every one of them describes
// a way the platform could otherwise end up deciding something the node owner did not.

func writeConfig(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	full := `server:
  url: wss://central.example.com/ws/nodes
node:
  name: dev-1
workspace:
  allowed_roots:
    - /home/dev
heartbeat:
  interval_seconds: 10
` + body
	if err := os.WriteFile(path, []byte(full), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestAnAbsentTunnelBlockDoesNotVeto(t *testing.T) {
	// A plain bool here would read every existing node as vetoed after an upgrade, and
	// nobody would remember vetoing anything. Absent means "do not veto".
	cfg, err := Load(writeConfig(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.TunnelEnabled() {
		t.Fatal("an absent tunnel block must not read as a veto")
	}
	if cfg.Tunnel.KnownHostsPath != DefaultKnownHostsPath {
		t.Errorf("expected the packaged known_hosts default, got %q", cfg.Tunnel.KnownHostsPath)
	}
}

func TestAnExplicitFalseIsAnAbsoluteVeto(t *testing.T) {
	cfg, err := Load(writeConfig(t, "tunnel:\n  enabled: false\n"))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.TunnelEnabled() {
		t.Fatal("an explicit false must survive defaulting; the platform cannot override it")
	}
	// And it stays vetoed no matter how often defaults are applied.
	cfg.applyTunnelDefaults()
	cfg.applyTunnelDefaults()
	if cfg.TunnelEnabled() {
		t.Fatal("re-applying defaults must not clear a veto")
	}
}

func TestALegacyTokenKeyIsIgnoredRatherThanFatal(t *testing.T) {
	// The credential moved to the platform. A node whose file still carries the old key must
	// still start: refusing would take a node offline over a setting that no longer means
	// anything, and the owner needs to be told, not stopped.
	cfg, err := Load(writeConfig(t, "tunnel:\n  token: leftoverfromtheoldshape\n"))
	if err != nil {
		t.Fatalf("a leftover token key must not stop the daemon: %v", err)
	}
	if cfg.Tunnel.Token != "" {
		t.Error("the token must be cleared, not carried around")
	}
	if !cfg.LegacyTunnelToken {
		t.Error("the daemon must be able to tell the owner the key is dead")
	}
}

func TestPortsBelow1024AreNeverAllowed(t *testing.T) {
	// Not configurable in either direction: below this live system services, and the cost of
	// getting it wrong is publishing one of them.
	cfg, err := Load(writeConfig(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	for _, port := range []int{0, 22, 80, 443, 1023} {
		if cfg.TunnelPortAllowed(port) {
			t.Errorf("port %d must never be forwardable", port)
		}
	}
	if !cfg.TunnelPortAllowed(5173) {
		t.Error("an unconfigured node should allow ordinary high ports")
	}
}

func TestAConfiguredAllowlistCanOnlyNarrow(t *testing.T) {
	cfg, err := Load(writeConfig(t, "tunnel:\n  allowed_ports:\n    - 3000-3999\n    - \"5173\"\n"))
	if err != nil {
		t.Fatal(err)
	}
	allowed := []int{3000, 3500, 3999, 5173}
	refused := []int{2999, 4000, 5174, 8080}
	for _, port := range allowed {
		if !cfg.TunnelPortAllowed(port) {
			t.Errorf("port %d should be allowed", port)
		}
	}
	for _, port := range refused {
		if cfg.TunnelPortAllowed(port) {
			t.Errorf("port %d should be refused: the local list narrows, it does not extend", port)
		}
	}
}

func TestAnAllowlistBelowTheFloorIsRejectedAtStartup(t *testing.T) {
	// Startup is the right place: a node that would have forwarded port 22 should never get
	// as far as being asked to.
	_, err := Load(writeConfig(t, "tunnel:\n  allowed_ports:\n    - 20-30\n"))
	if err == nil {
		t.Fatal("an allowlist reaching below 1024 must be refused")
	}
	if !strings.Contains(err.Error(), "1024") {
		t.Errorf("the error should say what the floor is, got %v", err)
	}
}

func TestAMalformedPortSpecIsRejected(t *testing.T) {
	for _, spec := range []string{"abc", "3999-3000", "3000-", "-4000", "70000"} {
		if _, err := Load(writeConfig(t, "tunnel:\n  allowed_ports:\n    - \""+spec+"\"\n")); err == nil {
			t.Errorf("spec %q should be refused", spec)
		}
	}
}

func TestANegativeMaxTunnelsIsRejected(t *testing.T) {
	if _, err := Load(writeConfig(t, "tunnel:\n  max_tunnels: -1\n")); err == nil {
		t.Fatal("a negative cap should be refused")
	}
}

func TestAnUnknownTunnelKeyIsRefused(t *testing.T) {
	// KnownFields(true) is what stops a typo from silently disabling a control: a config
	// saying `enable: false` must fail loudly rather than read as "not vetoed".
	if _, err := Load(writeConfig(t, "tunnel:\n  enable: false\n")); err == nil {
		t.Fatal("a misspelled key must be refused, not ignored")
	}
}
