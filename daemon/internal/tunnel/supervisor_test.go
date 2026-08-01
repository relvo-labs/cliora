package tunnel

import (
	"bytes"
	"context"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
)

// recorder collects the status reports the supervisor makes, which is the only way Central
// learns anything about a tunnel after it opens.
type recorder struct {
	mu      sync.Mutex
	reports []report
}

type report struct {
	state string
	url   string
	code  string
}

func (r *recorder) TunnelStatus(_ uuid.UUID, state, url, _ string, code string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.reports = append(r.reports, report{state: state, url: url, code: code})
}

func (r *recorder) all() []report {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]report(nil), r.reports...)
}

func (r *recorder) waitFor(t *testing.T, want string, timeout time.Duration) report {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		for _, item := range r.all() {
			if item.state == want {
				return item
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("no %q report within %s; got %+v", want, timeout, r.all())
	return report{}
}

func newSupervisor(t *testing.T, mode string) (*Supervisor, *recorder) {
	t.Helper()
	t.Setenv("FAKE_MODE", mode)
	rec := &recorder{}
	sup := NewSupervisor(&PinggyProvider{SSHPath: writeFake(t)}, rec)
	sup.SetRunDir(filepath.Join(t.TempDir(), "tunnels"))
	t.Cleanup(sup.CloseAll)
	return sup, rec
}

func TestOpenReturnsTheURLAndTracksTheTunnel(t *testing.T) {
	sup, _ := newSupervisor(t, "ok")
	id := uuid.New()
	result, err := sup.Open(context.Background(), id, baseOptions(t), time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if result.URL == "" || sup.Count() != 1 {
		t.Fatalf("unexpected state: url=%q count=%d", result.URL, sup.Count())
	}
	if sup.URLOf(id) != result.URL {
		t.Errorf("URLOf disagrees with the open result")
	}
}

func TestOpeningTheSameTunnelTwiceDoesNotStartASecondProcess(t *testing.T) {
	// Central re-opens its live tunnels after a restart. That must be idempotent, or a
	// reconnect would double every tunnel on the node.
	sup, _ := newSupervisor(t, "ok")
	id := uuid.New()
	if _, err := sup.Open(context.Background(), id, baseOptions(t), time.Minute); err != nil {
		t.Fatal(err)
	}
	if _, err := sup.Open(context.Background(), id, baseOptions(t), time.Minute); err == nil {
		t.Fatal("expected the second open of the same id to be refused")
	}
	if sup.Count() != 1 {
		t.Fatalf("expected one tunnel, got %d", sup.Count())
	}
}

func TestCloseStopsTheProcessAndReports(t *testing.T) {
	sup, rec := newSupervisor(t, "ok")
	id := uuid.New()
	if _, err := sup.Open(context.Background(), id, baseOptions(t), time.Minute); err != nil {
		t.Fatal(err)
	}
	if !sup.Close(id) {
		t.Fatal("close should report that it acted")
	}
	rec.waitFor(t, StateClosed, 3*time.Second)
	if sup.Count() != 0 {
		t.Fatalf("tunnel should be forgotten, count=%d", sup.Count())
	}
	// Closing an unknown id is not an error: Central retrying a close it already sent must
	// not produce one.
	if sup.Close(uuid.New()) {
		t.Error("closing an unknown tunnel should report that it did nothing")
	}
}

func TestAReconnectReportsTheNewURL(t *testing.T) {
	// The measured behaviour that shapes the whole design: the free tier issues a new URL
	// every time, so a user who pasted the old one has to be told.
	sup, rec := newSupervisor(t, "shortlived")
	t.Setenv("FAKE_SLUG", "first")
	id := uuid.New()
	if _, err := sup.Open(context.Background(), id, baseOptions(t), 30*time.Second); err != nil {
		t.Fatal(err)
	}
	// The process exits immediately, so the supervisor backs off and reconnects. The fake
	// issues a different slug once the env changes.
	t.Setenv("FAKE_SLUG", "second")
	rec.waitFor(t, StateReconnecting, 3*time.Second)
	running := rec.waitFor(t, StateRunning, 6*time.Second)
	if running.url == "" {
		t.Fatal("a reconnect must report the URL it got")
	}
}

func TestAnUntrustedHostKeyFailsWithoutRetrying(t *testing.T) {
	sup, _ := newSupervisor(t, "hostkey")
	_, err := sup.Open(context.Background(), uuid.New(), baseOptions(t), time.Minute)
	if err == nil {
		t.Fatal("expected the open to fail")
	}
	var provErr *ProviderError
	if !asProviderError(err, &provErr) || provErr.Code != CodeUntrusted {
		t.Fatalf("expected %s, got %v", CodeUntrusted, err)
	}
	if sup.Count() != 0 {
		t.Fatal("a failed open must not leave a tracked tunnel")
	}
}

func TestTheTTLEndsTheTunnelWithoutCentral(t *testing.T) {
	// A node that lost its control connection must not keep a forgotten tunnel open.
	sup, rec := newSupervisor(t, "ok")
	if _, err := sup.Open(context.Background(), uuid.New(), baseOptions(t), 300*time.Millisecond); err != nil {
		t.Fatal(err)
	}
	rec.waitFor(t, StateClosed, 3*time.Second)
	if sup.Count() != 0 {
		t.Fatalf("expired tunnel should be gone, count=%d", sup.Count())
	}
}

func TestAPidFileIsWrittenAndRemoved(t *testing.T) {
	sup, _ := newSupervisor(t, "ok")
	id := uuid.New()
	if _, err := sup.Open(context.Background(), id, baseOptions(t), time.Minute); err != nil {
		t.Fatal(err)
	}
	path := sup.pidPath(id)
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("expected a pid file at %s: %v", path, err)
	}
	sup.Close(id)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(path); os.IsNotExist(err) {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("the pid file should be removed when the tunnel closes")
}

func TestReapOrphansKillsAPreviousGenerationsTunnel(t *testing.T) {
	// A daemon restart leaves the old ssh processes serving, with nothing in any log to say
	// so. Central is the authority on which tunnels exist and re-opens them, so the previous
	// generation is always the wrong one to keep.
	sup, _ := newSupervisor(t, "ok")
	id := uuid.New()
	if _, err := sup.Open(context.Background(), id, baseOptions(t), time.Minute); err != nil {
		t.Fatal(err)
	}
	pid := 0
	sup.mu.Lock()
	if e, ok := sup.tunnels[id]; ok {
		pid = e.handle.PID()
	}
	sup.mu.Unlock()
	if pid == 0 {
		t.Fatal("no pid recorded")
	}
	// Simulate the restart: a fresh supervisor over the same run directory, with the old
	// process still alive and its pid file still present.
	fresh := NewSupervisor(&PinggyProvider{SSHPath: "ssh"}, &recorder{})
	fresh.SetRunDir(sup.runDir)
	killed := fresh.ReapOrphans()
	if killed != 1 {
		t.Fatalf("expected to reap one orphan, got %d", killed)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if !processAlive(pid) {
			// And the pid file is gone, so a second restart does not try again.
			if _, err := os.Stat(fresh.pidPath(id)); !os.IsNotExist(err) {
				t.Fatal("the pid file should have been removed")
			}
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("orphan %d survived reaping", pid)
}

func TestReapOrphansLeavesUnrelatedProcessesAlone(t *testing.T) {
	// Pids are reused. Killing a process that merely inherited the number would be a far
	// worse bug than leaving a stale file behind, so the command line has to match too.
	sup, _ := newSupervisor(t, "ok")
	runDir := sup.runDir
	if err := os.MkdirAll(runDir, 0o750); err != nil {
		t.Fatal(err)
	}
	// Our own pid: alive, but its command line is a test binary, not a tunnel.
	stray := filepath.Join(runDir, uuid.New().String()+".pid")
	if err := os.WriteFile(stray, []byte(itoa(os.Getpid())), 0o640); err != nil {
		t.Fatal(err)
	}
	fresh := NewSupervisor(&PinggyProvider{SSHPath: "ssh"}, &recorder{})
	fresh.SetRunDir(runDir)
	if killed := fresh.ReapOrphans(); killed != 0 {
		t.Fatalf("an unrelated process must not be killed, reaped=%d", killed)
	}
	if _, err := os.Stat(stray); !os.IsNotExist(err) {
		t.Error("the stale pid file should still be cleaned up")
	}
}

func TestCloseAllStopsEverything(t *testing.T) {
	sup, _ := newSupervisor(t, "ok")
	for i := 0; i < 3; i++ {
		if _, err := sup.Open(context.Background(), uuid.New(), baseOptions(t), time.Minute); err != nil {
			t.Fatal(err)
		}
	}
	if sup.Count() != 3 {
		t.Fatalf("expected three tunnels, got %d", sup.Count())
	}
	sup.CloseAll()
	if sup.Count() != 0 {
		t.Fatalf("CloseAll should leave nothing, got %d", sup.Count())
	}
}

func TestTheCredentialIsNeverWrittenToDiskOrLogged(t *testing.T) {
	// Security review P11 row 3c / finding F-2. The credential legitimately lives in two
	// places — this process's memory and the child's argv, because that is the provider's
	// interface — and in no third place. The individual write paths (the pid file, the log
	// lines, `doctor`) are each covered elsewhere; what this asserts is the negative that
	// covers the paths nobody thought of: after a full open, the value appears in **no file
	// this daemon wrote** and in **nothing it logged**.
	//
	// The log is captured rather than trusted: the realistic way this leaks is somebody
	// adding one `slog.Info("opening", "opts", opts)` while debugging, which no other test
	// here would notice.
	const credential = "CREDENTIALMUSTNOTBEONDISK1234"

	var logged bytes.Buffer
	previous := slog.Default()
	slog.SetDefault(slog.New(slog.NewTextHandler(&logged, &slog.HandlerOptions{Level: slog.LevelDebug})))
	t.Cleanup(func() { slog.SetDefault(previous) })

	// `authenticated`: with a credential supplied, the anonymous banner would (correctly) make
	// the open fail as a downgrade, and this test needs a *successful* open to have anything
	// to inspect.
	sup, _ := newSupervisor(t, "authenticated")
	runDir := filepath.Join(t.TempDir(), "tunnels")
	sup.SetRunDir(runDir)

	options := baseOptions(t)
	options.Credential = credential
	options.Protection = ProtectionBasic
	options.BasicUser = "preview"
	options.BasicPass = "abcdefghijklmnop"

	id := uuid.New()
	if _, err := sup.Open(context.Background(), id, options, time.Minute); err != nil {
		t.Fatalf("open: %v", err)
	}
	t.Cleanup(func() { sup.Close(id) })

	// Everything this daemon wrote: the run directory holds the pid files, and it is the only
	// place the supervisor creates anything.
	walked := 0
	err := filepath.WalkDir(runDir, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		walked++
		content, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		if strings.Contains(string(content), credential) {
			t.Errorf("the credential was written to %s", path)
		}
		if strings.Contains(string(content), options.BasicPass) {
			t.Errorf("the tunnel password was written to %s", path)
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walking the run directory: %v", err)
	}
	if walked == 0 {
		t.Fatal("no file was written at all, so this test would pass without checking anything")
	}
	if strings.Contains(logged.String(), credential) {
		t.Errorf("the credential reached the log: %s", logged.String())
	}
	if strings.Contains(logged.String(), options.BasicPass) {
		t.Errorf("the tunnel password reached the log: %s", logged.String())
	}
}
