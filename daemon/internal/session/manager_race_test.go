package session

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/google/uuid"
)

// fakeTmux puts a `tmux` stand-in first on PATH so the manager's real Attach and
// Stop paths run without a tmux server. The session always "exists", capture is
// empty, the attach client records its PID and becomes a long sleep (so it exits
// only when killed), and the pane PID is unreadable so Stop falls straight through
// to kill-session, which succeeds. It returns the directory the attach PIDs are
// written to, one `<session name>.pid` each.
func fakeTmux(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	script := `#!/bin/sh
case "$1" in
  attach-session)
    echo $$ > "$FAKE_TMUX_DIR/$4.pid.tmp" && mv "$FAKE_TMUX_DIR/$4.pid.tmp" "$FAKE_TMUX_DIR/$4.pid"
    exec sleep 30 ;;
  display-message) exit 1 ;;
  *) exit 0 ;;
esac
`
	if err := os.WriteFile(filepath.Join(dir, "tmux"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("FAKE_TMUX_DIR", dir)
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(io.Discard, nil)))
	t.Cleanup(func() { slog.SetDefault(previous) })
	return dir
}

// attachPID waits for the fake attach client of id to record its PID.
func attachPID(t *testing.T, dir string, id uuid.UUID) int {
	t.Helper()
	name, _ := ctmux.Name(id)
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if b, err := os.ReadFile(filepath.Join(dir, name+".pid")); err == nil {
			pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
			if err != nil {
				t.Fatalf("attach pid: %v", err)
			}
			return pid
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("fake attach client never recorded its pid")
	return 0
}

// TestStopWhileAttachedProcessExits is the #95 regression. The attach exit
// callback clears entry.process under m.mu when the attach client exits on its
// own; Stop used to release m.mu and only then read entry.process to close it.
//
// The hook runs in exactly that gap and makes the client exit there: it kills
// the client and sleeps long enough for terminal.Process to reap it and run the
// exit callback. It synchronises only through a syscall and a sleep — never a Go
// primitive — so the race detector sees no happens-before edge between the
// callback's write and whatever Stop does next. On the unfixed manager Stop then
// reads the field the callback just wrote and -race reports it every run; fixed,
// Stop already holds its own copy and closes a process that has exited, which
// must be safe.
func TestStopWhileAttachedProcessExits(t *testing.T) {
	dir := fakeTmux(t)
	m := New(ctmux.Client{}, "", "").WithStopGrace(time.Second)
	id := uuid.New()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	exited := make(chan int, 1)
	if _, err := m.Attach(ctx, id, 24, 80, func([]byte) error { return nil }, func(code int) { exited <- code }); err != nil {
		t.Fatalf("attach: %v", err)
	}
	pid := attachPID(t, dir, id)

	m.stopUnlockedHook = func() {
		if err := syscall.Kill(pid, syscall.SIGKILL); err != nil {
			t.Errorf("kill attach client: %v", err)
			return
		}
		deadline := time.Now().Add(5 * time.Second)
		for !errors.Is(syscall.Kill(pid, 0), syscall.ESRCH) && time.Now().Before(deadline) {
			time.Sleep(time.Millisecond)
		}
		// Reaping happens immediately before the exit callback takes m.mu; give it
		// ample time to finish without synchronising with it.
		time.Sleep(100 * time.Millisecond)
	}
	outcome, err := m.Stop(context.Background(), id)
	if err != nil {
		t.Fatalf("stop: %v", err)
	}
	if outcome != ctmux.StopForced {
		t.Errorf("outcome = %q, want %q from the fake tmux", outcome, ctmux.StopForced)
	}
	if _, ok := m.Workspace(id); ok {
		t.Error("session still registered after Stop")
	}
	select {
	case <-exited:
	case <-time.After(5 * time.Second):
		t.Error("the client's own exit was never reported")
	}
	if err := m.Input(id, []byte("x")); err == nil {
		t.Error("Input after Stop succeeded")
	}
}

// TestInputResizeWhileAttachedProcessExits covers the same unlocked read in Input
// and Resize. A goroutine hammers both while the attach client is killed, until
// the exit is reported; on the unfixed manager -race catches a read in flight
// when the callback clears entry.process. This one is timing-based (no seam: the
// read sits inside the hot loop), so it aims rather than forces; in practice it
// caught the unfixed manager on every run. -race reports a given pair of racing
// accesses once per test binary, so judge it per process, not per -count.
func TestInputResizeWhileAttachedProcessExits(t *testing.T) {
	dir := fakeTmux(t)
	const rounds = 20
	for i := 0; i < rounds; i++ {
		m := New(ctmux.Client{}, "", "").WithStopGrace(time.Second)
		id := uuid.New()
		ctx, cancel := context.WithCancel(context.Background())
		exited := make(chan struct{})
		if _, err := m.Attach(ctx, id, 24, 80, func([]byte) error { return nil }, func(int) { close(exited) }); err != nil {
			cancel()
			t.Fatalf("round %d: attach: %v", i, err)
		}
		pid := attachPID(t, dir, id)

		var wg sync.WaitGroup
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-exited:
					return
				default:
				}
				_ = m.Input(id, []byte("x"))
				_ = m.Resize(id, 24, 80)
			}
		}()
		_ = syscall.Kill(pid, syscall.SIGKILL)
		select {
		case <-exited:
		case <-time.After(5 * time.Second):
			t.Errorf("round %d: exit never reported", i)
		}
		wg.Wait()
		if err := m.Input(id, []byte("x")); err == nil {
			t.Errorf("round %d: Input succeeded after the client exited", i)
		}
		if _, err := m.Stop(context.Background(), id); err != nil {
			t.Errorf("round %d: stop: %v", i, err)
		}
		cancel()
	}
}
