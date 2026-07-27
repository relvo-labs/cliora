//go:build integration

// Reproduction harness for the P0 recovery blocker (docs/p0-report.md, ADR 0004):
// after a cross-process daemon restart a lingering `tmux attach` client can block
// the recovered reattach. Guarded by the `integration` tag; skipped without tmux.
package session

import (
	"context"
	"io"
	"os/exec"
	"strings"
	"testing"
	"time"

	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/creack/pty"
	"github.com/google/uuid"
)

// countClients reports how many attach clients tmux sees for the session's
// server socket. The Gate invariant is exactly one live client after recovery
// (the recovered daemon's own), i.e. the orphan was evicted, not leaked.
func countClients(t *testing.T, socket string) int {
	t.Helper()
	out, err := exec.Command("tmux", "-L", socket, "list-clients").Output()
	if err != nil {
		return 0 // no server / no clients
	}
	trimmed := strings.TrimSpace(string(out))
	if trimmed == "" {
		return 0
	}
	return len(strings.Split(trimmed, "\n"))
}

// liveOrphan is an independent attach client whose PTY master stays open (a
// goroutine drains it), so tmux sees a fully-alive competing client — the worst
// case for a recovered daemon that must evict it before reattaching.
func liveOrphan(t *testing.T, socket, name string) func() {
	t.Helper()
	cmd := exec.Command("tmux", "-L", socket, "attach-session", "-t", name)
	ptmx, err := pty.Start(cmd)
	if err != nil {
		t.Fatalf("spawn live orphan: %v", err)
	}
	go func() { _, _ = io.Copy(io.Discard, ptmx) }()
	time.Sleep(300 * time.Millisecond) // let tmux register the client
	return func() { _ = ptmx.Close(); _ = cmd.Process.Kill(); _, _ = cmd.Process.Wait() }
}

func attachWithin(t *testing.T, m *Manager, id uuid.UUID, out *sink, d time.Duration) {
	t.Helper()
	done := make(chan error, 1)
	go func() { _, err := m.Attach(context.Background(), id, 24, 80, out.write, nil); done <- err }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("attach returned error: %v", err)
		}
	case <-time.After(d):
		t.Fatalf("attach BLOCKED for >%s (recovery blocker)", d)
	}
}

// Worst case: a fully-alive competing attach client at the moment a fresh
// (cross-process) manager recovers.
func TestRecoveredReattachEvictsLiveOrphan(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	id := uuid.New()
	socket := uniqueSocket(id)
	ctx := context.Background()

	mgrA := New(ctmux.Client{Socket: socket}, t.TempDir(), bin)
	if err := mgrA.Start(ctx, id, 24, 80); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer func() { _ = New(ctmux.Client{Socket: socket}, t.TempDir(), bin).Stop(ctx, id) }()

	name, _ := ctmux.Name(id)
	stopOrphan := liveOrphan(t, socket, name)
	defer stopOrphan()

	// Fresh manager (no in-process previous Process to detach) must recover.
	mgrB := New(ctmux.Client{Socket: socket}, t.TempDir(), bin)
	out := &sink{}
	attachWithin(t, mgrB, id, out, 8*time.Second)
	out.waitFor(t, "FAKECLI_READY")

	// No leaked client: the orphan was evicted, exactly the recovered client remains.
	time.Sleep(200 * time.Millisecond)
	if n := countClients(t, socket); n != 1 {
		t.Fatalf("expected exactly 1 live client after recovery, got %d (leaked orphan)", n)
	}

	// After recovery, stop must also complete (the p0-report's "subsequent stop").
	done := make(chan error, 1)
	go func() { done <- mgrB.Stop(ctx, id) }()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("post-recovery stop: %v", err)
		}
	case <-time.After(8 * time.Second):
		t.Fatal("post-recovery stop BLOCKED")
	}
}

// Rapid reattach churn must not leak clients or block.
func TestRapidReattachChurn(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	id := uuid.New()
	socket := uniqueSocket(id)
	ctx := context.Background()
	mgr := New(ctmux.Client{Socket: socket}, t.TempDir(), bin)
	if err := mgr.Start(ctx, id, 24, 80); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer func() { _ = mgr.Stop(ctx, id) }()

	for i := 0; i < 20; i++ {
		out := &sink{}
		attachWithin(t, mgr, id, out, 5*time.Second)
	}
	if mgr.ActiveCount() != 1 {
		t.Fatalf("expected 1 active session after churn, got %d", mgr.ActiveCount())
	}
}
