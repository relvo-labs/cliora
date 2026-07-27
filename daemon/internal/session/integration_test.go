//go:build integration

// Vertical-slice integration: Fake CLI <-> tmux <-> PTY <-> session manager.
// Guarded by the `integration` build tag and skipped when tmux is unavailable,
// so the plain unit suite stays hermetic. Run via `make integration`.
package session

import (
	"bytes"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/google/uuid"
)

// uniqueSocket derives a per-test tmux socket *name* (used with `tmux -L`, not a
// path) so tests never touch a developer's default tmux server.
func uniqueSocket(id uuid.UUID) string {
	return "cliora-test-" + id.String()[:8]
}

func buildFakeCLI(t *testing.T) string {
	t.Helper()
	out := filepath.Join(t.TempDir(), "fakecli")
	build := exec.Command("go", "build", "-o", out, "github.com/cliora/cliora/daemon/cmd/fakecli")
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build fakecli: %v\n%s", err, output)
	}
	return out
}

// sink is a concurrency-safe output collector for the attach stream.
type sink struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (s *sink) write(b []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.buf.Write(b)
	return nil
}

func (s *sink) waitFor(t *testing.T, substr string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		s.mu.Lock()
		got := s.buf.String()
		s.mu.Unlock()
		if strings.Contains(got, substr) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	t.Fatalf("timed out waiting for %q; got:\n%q", substr, s.buf.String())
}

func TestVerticalSlicePreservesBytesAndReportsExit(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	id := uuid.New()
	manager := New(ctmux.Client{Socket: uniqueSocket(id)}, t.TempDir(), bin)
	ctx := context.Background()

	if err := manager.Start(ctx, id, 24, 80); err != nil {
		t.Fatalf("start: %v", err)
	}
	// Teardown deletes only this test's own tmux server socket.
	defer func() { _, _ = manager.Stop(ctx, id) }()

	out := &sink{}
	exited := make(chan int, 1)
	if _, err := manager.Attach(ctx, id, 24, 80, out.write, func(code int) { exited <- code }); err != nil {
		t.Fatalf("attach: %v", err)
	}
	out.waitFor(t, "FAKECLI_READY v1")

	// ANSI escape bytes survive round trip unmodified.
	_ = manager.Input(id, []byte(":ansi\n"))
	out.waitFor(t, "\x1b[31m")

	// UTF-8 multibyte survives round trip.
	_ = manager.Input(id, []byte(":unicode\n"))
	out.waitFor(t, "中文")

	// Resize is observed by the Fake CLI via SIGWINCH.
	if err := manager.Resize(id, 40, 120); err != nil {
		t.Fatalf("resize: %v", err)
	}
	out.waitFor(t, "RESIZE")

	// Process exit is surfaced as an exit event (the code is the tmux attach
	// client's status, a documented P0 limitation — see ADR 0004).
	_ = manager.Input(id, []byte(":exit 0\n"))
	select {
	case <-exited:
	case <-time.After(5 * time.Second):
		t.Fatal("no exit event delivered after Fake CLI exit")
	}

	if manager.ActiveCount() != 0 {
		t.Fatalf("expected no active sessions after exit, got %d", manager.ActiveCount())
	}
}

func TestReattachAfterDetachKeepsSessionAlive(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	bin := buildFakeCLI(t)
	id := uuid.New()
	manager := New(ctmux.Client{Socket: uniqueSocket(id)}, t.TempDir(), bin)
	ctx := context.Background()
	if err := manager.Start(ctx, id, 24, 80); err != nil {
		t.Fatalf("start: %v", err)
	}
	defer func() { _, _ = manager.Stop(ctx, id) }()

	first := &sink{}
	if _, err := manager.Attach(ctx, id, 24, 80, first.write, nil); err != nil {
		t.Fatalf("first attach: %v", err)
	}
	first.waitFor(t, "FAKECLI_READY")

	// Reattaching (as on browser refresh) must not kill the tmux session.
	second := &sink{}
	if _, err := manager.Attach(ctx, id, 24, 80, second.write, nil); err != nil {
		t.Fatalf("reattach: %v", err)
	}
	// Snapshot from capture-pane should carry the earlier ready banner.
	second.waitFor(t, "FAKECLI_READY")
	if manager.ActiveCount() != 1 {
		t.Fatalf("expected session still active, got %d", manager.ActiveCount())
	}
}

// writeScript drops an executable shell script in a temp dir and returns its path.
// tmux runs the session command through the shell, but the manager takes a single
// binary path, so a script is how a test supplies behaviour the Fake CLI does not
// have.
func writeScript(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "script.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body+"\n"), 0o700); err != nil {
		t.Fatalf("write script: %v", err)
	}
	return path
}

// TestStopSignalsFirstAndOnlyForcesWhenIgnored covers both halves of
// FR-SESSION-005: the daemon sends a normal termination signal, waits the
// configured number of seconds, and forces only if the process is still there.
//
// Both directions matter. Only asserting the graceful path would pass against an
// implementation that never escalates and hangs forever on a wedged CLI; only
// asserting the forced path would pass against one that always kills immediately
// and never lets a CLI flush its state.
func TestStopSignalsFirstAndOnlyForcesWhenIgnored(t *testing.T) {
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not installed")
	}
	ctx := context.Background()

	t.Run("a CLI that honours the signal exits on its own", func(t *testing.T) {
		// Default `sh` behaviour: SIGTERM terminates it.
		bin := writeScript(t, "while :; do sleep 0.1; done")
		id := uuid.New()
		manager := New(ctmux.Client{Socket: uniqueSocket(id)}, t.TempDir(), bin).
			WithStopGrace(5 * time.Second)
		if err := manager.Start(ctx, id, 24, 80); err != nil {
			t.Fatalf("start: %v", err)
		}

		started := time.Now()
		outcome, err := manager.Stop(ctx, id)
		elapsed := time.Since(started)
		if err != nil {
			t.Fatalf("stop: %v", err)
		}
		if outcome != ctmux.StopGraceful {
			t.Errorf("outcome = %q, want %q", outcome, ctmux.StopGraceful)
		}
		// It must not have been billed the whole grace period: that would mean the
		// wait is a fixed sleep rather than a wait for the process to go.
		if elapsed >= 4*time.Second {
			t.Errorf("graceful stop took %v; the grace period is not being cut short on exit", elapsed)
		}
	})

	t.Run("a CLI that ignores the signal is forced after the grace period", func(t *testing.T) {
		bin := writeScript(t, `trap "" TERM; while :; do sleep 0.1; done`)
		id := uuid.New()
		grace := 700 * time.Millisecond
		manager := New(ctmux.Client{Socket: uniqueSocket(id)}, t.TempDir(), bin).
			WithStopGrace(grace)
		if err := manager.Start(ctx, id, 24, 80); err != nil {
			t.Fatalf("start: %v", err)
		}

		started := time.Now()
		outcome, err := manager.Stop(ctx, id)
		elapsed := time.Since(started)
		if err != nil {
			t.Fatalf("stop: %v", err)
		}
		if outcome != ctmux.StopForced {
			t.Errorf("outcome = %q, want %q", outcome, ctmux.StopForced)
		}
		if elapsed < grace {
			t.Errorf("forced after %v, which is inside the %v grace period: it was never given a chance", elapsed, grace)
		}
		// Forced or not, the session must be gone.
		exists, err := ctmux.Client{Socket: uniqueSocket(id)}.Exists(ctx, id)
		if err != nil {
			t.Fatalf("exists: %v", err)
		}
		if exists {
			t.Error("session survived a forced stop")
		}
	})

	t.Run("stopping something that is not running is not an error", func(t *testing.T) {
		id := uuid.New()
		manager := New(ctmux.Client{Socket: uniqueSocket(id)}, t.TempDir(), "/bin/true")
		outcome, err := manager.Stop(ctx, id)
		if err != nil {
			t.Fatalf("stop: %v", err)
		}
		if outcome != ctmux.StopNotRunning {
			t.Errorf("outcome = %q, want %q", outcome, ctmux.StopNotRunning)
		}
	})
}
