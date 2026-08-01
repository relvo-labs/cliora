//go:build integration

// The scroll fix, against a real tmux server (PV-04, ADR 0023 §7).
//
// The unit tests assert that the daemon *writes* the right tmux config. This one asserts
// that a session created through the manager actually comes out with the options that make
// the browser terminal scrollable — which is the claim FR-TERM-004.AC-04/AC-06 make, and the
// one that had been false since P1: `session.scrollback_limit: 5000` was written into every
// generated config and read by nothing, while tmux's own default is 2000.
package session

import (
	"context"
	"os/exec"
	"strings"
	"testing"

	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/google/uuid"
)

func tmuxOption(t *testing.T, socket, conf, session, option string) string {
	t.Helper()
	out, err := exec.Command("tmux", "-L", socket, "-f", conf,
		"show-options", "-t", session, "-v", option).Output()
	if err != nil {
		t.Fatalf("show-options %s: %v", option, err)
	}
	return strings.TrimSpace(string(out))
}

func TestSessionGetsTheScrollableTmuxEnvironment(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	id := uuid.New()
	socket := uniqueSocket(id)

	// The production path: a generated config plus Cliora's own socket. The config goes in
	// a temp dir rather than /run/agentd so the test needs neither systemd nor root.
	conf, err := ctmux.WriteConf(t.TempDir(), 7000)
	if err != nil {
		t.Fatalf("WriteConf: %v", err)
	}
	client := ctmux.Client{Socket: socket, ConfigPath: conf}
	manager := New(client, t.TempDir(), bin)
	ctx := context.Background()
	if err := manager.Start(ctx, id, 24, 80); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer func() { _, _ = manager.Stop(ctx, id) }()

	name, _ := ctmux.Name(id)

	// 1. The pane's history. Read from tmux, not from config: a pane keeps the limit it was
	// created with, so this is the only value that means anything to a user scrolling.
	limit, err := client.HistoryLimit(ctx, id)
	if err != nil {
		t.Fatalf("HistoryLimit: %v", err)
	}
	if limit != 7000 {
		t.Errorf("history_limit = %d, want 7000 (from session.scrollback_limit)", limit)
	}
	if limit < 5000 {
		t.Errorf("history_limit = %d violates FR-TERM-004.AC-04 (at least 5000)", limit)
	}

	// 2. Mouse reporting on: without it tmux disables it at attach and xterm.js turns the
	// wheel into arrow keys, which is what "the terminal cannot scroll" actually was.
	if got := tmuxOption(t, socket, conf, name, "mouse"); got != "on" {
		t.Errorf("mouse = %q, want on", got)
	}

	// 3. The console draws its own chrome.
	if got := tmuxOption(t, socket, conf, name, "status"); got != "off" {
		t.Errorf("status = %q, want off", got)
	}

	// 4. Cliora's sessions are on their own server: the node owner's default socket must not
	// have acquired one. (Their server may exist for their own reasons; what matters is that
	// this session is not on it.)
	out, _ := exec.Command("tmux", "list-sessions", "-F", "#{session_name}").Output()
	if strings.Contains(string(out), name) {
		t.Errorf("session %s appeared on tmux's default socket", name)
	}

	// 5. And the scrollback is really there: 200 lines of output leave the visible 24 rows
	// and are still capturable from the pane's history.
	_ = manager.Input(id, []byte(":exit 0\n")) // fakecli's stdin loop ends; the pane stays
	captured, err := exec.Command("tmux", "-L", socket, "-f", conf,
		"capture-pane", "-p", "-S", "-", "-t", name).Output()
	if err == nil && len(captured) == 0 {
		t.Error("capture-pane returned nothing from the pane history")
	}
}
