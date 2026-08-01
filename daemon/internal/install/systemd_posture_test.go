package install

import (
	"strings"
	"testing"
)

// The default posture must keep today's unit exactly as it is: an existing node that
// is reinstalled without asking for the privileged terminal must not quietly lose a
// hardening option.
func TestUnitKeepsNoNewPrivilegesUnlessPrivileged(t *testing.T) {
	unit := UnitFile(UnitParams{User: "neil", BinaryPath: "/usr/local/bin/agentd", ConfigPath: "/etc/agentd/config.yaml"})
	if !strings.Contains(unit, "NoNewPrivileges=true") {
		t.Errorf("unprivileged unit lost NoNewPrivileges:\n%s", unit)
	}
	if UnitIsPrivileged(unit) {
		t.Error("UnitIsPrivileged says yes for a unit that sets NoNewPrivileges")
	}
}

func TestPrivilegedUnitExplainsTheMissingHardening(t *testing.T) {
	unit := UnitFile(UnitParams{
		User: "neil", BinaryPath: "/usr/local/bin/agentd", ConfigPath: "/etc/agentd/config.yaml",
		PrivilegedTerminal: true,
	})
	if strings.Contains(unit, "NoNewPrivileges=true") {
		t.Errorf("privileged unit still sets NoNewPrivileges (sudo would fail):\n%s", unit)
	}
	// A hardening option that simply vanished reads as an oversight; the next
	// reviewer adds it back and sudo stops working with nothing to point at.
	for _, want := range []string{
		"NoNewPrivileges is deliberately NOT set",
		"ADR 0023",
		"posture --privileged-terminal=false",
	} {
		if !strings.Contains(unit, want) {
			t.Errorf("privileged unit does not explain itself (%q missing):\n%s", want, unit)
		}
	}
	// Everything else about the service identity must be untouched: non-root is not
	// traded away for sudo (ADR 0023 D8).
	for _, want := range []string{"User=neil", "Group=neil", "PrivateTmp=true"} {
		if !strings.Contains(unit, want) {
			t.Errorf("privileged unit changed more than the hardening line (%q missing):\n%s", want, unit)
		}
	}
	if !UnitIsPrivileged(unit) {
		t.Error("UnitIsPrivileged does not recognise its own output")
	}
}

// The generated tmux config lives in /run/agentd, which only exists because systemd
// creates it for the service user.
func TestUnitAlwaysCreatesTheRuntimeDirectory(t *testing.T) {
	for _, privileged := range []bool{false, true} {
		unit := UnitFile(UnitParams{
			User: "neil", BinaryPath: "/usr/local/bin/agentd", ConfigPath: "/etc/agentd/config.yaml",
			PrivilegedTerminal: privileged,
		})
		if !strings.Contains(unit, "RuntimeDirectory=agentd") {
			t.Errorf("privileged=%t unit has no RuntimeDirectory:\n%s", privileged, unit)
		}
	}
}
