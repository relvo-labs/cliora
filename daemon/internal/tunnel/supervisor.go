package tunnel

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math/rand/v2"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"

	"github.com/cliora/cliora/daemon/internal/metrics"
)

// Backoff for reconnects, matching the control connection's table (connection.go) rather
// than inventing a second policy for the same problem.
var backoff = []time.Duration{time.Second, 2 * time.Second, 5 * time.Second, 10 * time.Second, 30 * time.Second}

const (
	// How long to wait for the provider to announce a URL. Deliberately shorter than
	// Central's own budget (20 s) so that whoever gives up first is the side that knows
	// why: "the node could not get a URL" is more useful than "Central timed out".
	urlWait = 15 * time.Second
	// Consecutive failures before a tunnel is declared failed. The free tier reconnects
	// roughly hourly by design, so ten failures in a row is an environment that is broken,
	// not a time limit being hit — and an unbounded retry against a provider that has
	// stopped answering would keep dialling it all night.
	maxReconnects = 10
	// Where pid files live. /run is a tmpfs, so a reboot clears them; what they exist for is
	// the daemon restarting, not the machine.
	defaultRunDir = "/run/agentd/tunnels"
)

// StatusReporter receives state changes. The supervisor never speaks the protocol itself:
// it hands facts to the connection layer, which decides how to frame them.
type StatusReporter interface {
	TunnelStatus(tunnelID uuid.UUID, state string, url string, expiresAt string, errorCode string)
}

// State values reported upward; they mirror tunnel-status.schema.json.
const (
	StateRunning      = "running"
	StateReconnecting = "reconnecting"
	StateFailed       = "failed"
	StateClosed       = "closed"
)

// Supervisor owns every tunnel process on this node.
//
// One goroutine per tunnel watches its process, reconnects it, and reports the URL changes
// that follow (the free tier issues a new URL every time). Nothing here is shared with the
// control connection: a tunnel that flaps must not disturb the terminal path.
type Supervisor struct {
	provider Provider
	reporter StatusReporter
	runDir   string

	mu      sync.Mutex
	tunnels map[uuid.UUID]*entry
}

type entry struct {
	id       uuid.UUID
	port     int
	opts     Options
	cancel   context.CancelFunc
	handle   ProcessHandle
	url      string
	done     chan struct{}
	stopping bool
}

func NewSupervisor(provider Provider, reporter StatusReporter) *Supervisor {
	return &Supervisor{
		provider: provider,
		reporter: reporter,
		runDir:   defaultRunDir,
		tunnels:  map[uuid.UUID]*entry{},
	}
}

// SetRunDir overrides where pid files are written (tests, and packagers who move /run).
func (s *Supervisor) SetRunDir(dir string) {
	if dir != "" {
		s.runDir = dir
	}
}

// Provider is exposed so the connection layer can report the provider name it opened with.
func (s *Supervisor) ProviderName() string { return s.provider.Name() }

// Open starts a tunnel and returns the URL the provider assigned. ttl bounds the tunnel's
// life on this node even if Central never asks for it to be closed — a node that lost its
// control connection must not keep a forgotten tunnel open indefinitely.
func (s *Supervisor) Open(
	ctx context.Context, id uuid.UUID, opts Options, ttl time.Duration,
) (Result, error) {
	s.mu.Lock()
	if _, exists := s.tunnels[id]; exists {
		s.mu.Unlock()
		// Idempotent from Central's point of view: reopening the same id is what happens
		// after a Central restart, and it must not produce a second process.
		return Result{}, errors.New("tunnel is already running")
	}
	s.mu.Unlock()

	startCtx, cancelStart := context.WithTimeout(ctx, urlWait)
	defer cancelStart()
	result, handle, err := s.provider.Start(startCtx, opts)
	if err != nil {
		metrics.Increment(metrics.DaemonTunnelStartTotal, map[string]string{"result": "failed"})
		return Result{}, err
	}
	metrics.Increment(metrics.DaemonTunnelStartTotal, map[string]string{"result": "started"})

	// A background context: the tunnel outlives the request that created it. Only Close,
	// the TTL, or the reconnect limit end it.
	runCtx, cancel := context.WithCancel(context.Background())
	e := &entry{
		id:     id,
		port:   opts.Port,
		opts:   opts,
		cancel: cancel,
		handle: handle,
		url:    result.URL,
		done:   make(chan struct{}),
	}
	s.mu.Lock()
	s.tunnels[id] = e
	s.mu.Unlock()
	s.writePID(id, handle.PID())
	metrics.SetGauge(metrics.DaemonTunnelActive, float64(s.Count()), nil)

	go s.supervise(runCtx, e, ttl)
	return result, nil
}

// supervise watches one tunnel: reconnect on retryable exits, stop at the TTL, report every
// state change upward.
func (s *Supervisor) supervise(ctx context.Context, e *entry, ttl time.Duration) {
	defer close(e.done)
	var deadline <-chan time.Time
	if ttl > 0 {
		timer := time.NewTimer(ttl)
		defer timer.Stop()
		deadline = timer.C
	}
	attempts := 0

	for {
		exited := make(chan Exit, 1)
		go func(h ProcessHandle) { exited <- h.Wait() }(e.handle)

		select {
		case <-ctx.Done():
			return
		case <-deadline:
			slog.Info("tunnel reached its time limit", "tunnel_id", e.id.String())
			s.closeEntry(e, "expired")
			return
		case exit := <-exited:
			if s.isStopping(e) {
				return
			}
			if !exit.Retryable {
				code := exit.Code
				if code == "" {
					code = CodeUnavailable
				}
				slog.Warn("tunnel failed", "tunnel_id", e.id.String(), "code", code)
				s.reporter.TunnelStatus(e.id, StateFailed, "", "", code)
				s.forget(e)
				return
			}
			attempts++
			metrics.Increment(metrics.DaemonTunnelReconnectTotal,
				map[string]string{"reason": reconnectReason(exit)})
			if attempts > maxReconnects {
				slog.Warn("tunnel giving up after repeated failures",
					"tunnel_id", e.id.String(), "attempts", attempts)
				s.reporter.TunnelStatus(e.id, StateFailed, "", "", CodeUnavailable)
				s.forget(e)
				return
			}
			s.reporter.TunnelStatus(e.id, StateReconnecting, "", "", "")
			if !s.sleepBackoff(ctx, attempts) {
				return
			}
			result, handle, err := s.reconnect(ctx, e)
			if err != nil {
				// Classified failures end the tunnel; everything else counts as another
				// attempt and loops.
				var provErr *ProviderError
				if errors.As(err, &provErr) && provErr.Code != CodeUnavailable {
					s.reporter.TunnelStatus(e.id, StateFailed, "", "", provErr.Code)
					s.forget(e)
					return
				}
				if errors.Is(err, ErrKnownHostsMissing) {
					s.reporter.TunnelStatus(e.id, StateFailed, "", "", CodeUntrusted)
					s.forget(e)
					return
				}
				continue
			}
			attempts = 0
			e.handle = handle
			s.writePID(e.id, handle.PID())
			// The URL changes on every reconnect on the free tier, and a user who pasted the
			// old one somewhere needs to see that. Reported even when unchanged, because
			// "running again" is itself the news.
			if result.URL != e.url {
				metrics.Increment(metrics.DaemonTunnelURLChangedTotal, nil)
				e.url = result.URL
			}
			s.reporter.TunnelStatus(e.id, StateRunning, result.URL, result.ExpiresAt, "")
		}
	}
}

func reconnectReason(exit Exit) string {
	if exit.Code == "" {
		return "provider_closed"
	}
	return "provider_error"
}

func (s *Supervisor) sleepBackoff(ctx context.Context, attempt int) bool {
	idx := attempt - 1
	if idx >= len(backoff) {
		idx = len(backoff) - 1
	}
	delay := backoff[idx] + time.Duration(rand.IntN(250))*time.Millisecond
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}

func (s *Supervisor) reconnect(ctx context.Context, e *entry) (Result, ProcessHandle, error) {
	startCtx, cancel := context.WithTimeout(ctx, urlWait)
	defer cancel()
	return s.provider.Start(startCtx, e.opts)
}

// Close stops a tunnel by id. Safe to call for an unknown id: Central retrying a close it
// already sent must not be an error.
func (s *Supervisor) Close(id uuid.UUID) bool {
	s.mu.Lock()
	e, ok := s.tunnels[id]
	if ok {
		e.stopping = true
	}
	s.mu.Unlock()
	if !ok {
		return false
	}
	s.closeEntry(e, "requested")
	return true
}

func (s *Supervisor) closeEntry(e *entry, reason string) {
	e.cancel()
	if e.handle != nil {
		e.handle.Stop()
	}
	s.forget(e)
	state := StateClosed
	code := ""
	if reason == "expired" {
		// Reported as closed with no error: expiry is the platform's own policy working,
		// not a fault to explain away.
		state = StateClosed
	}
	s.reporter.TunnelStatus(e.id, state, "", "", code)
}

func (s *Supervisor) forget(e *entry) {
	s.mu.Lock()
	delete(s.tunnels, e.id)
	s.mu.Unlock()
	s.removePID(e.id)
	metrics.SetGauge(metrics.DaemonTunnelActive, float64(s.Count()), nil)
}

func (s *Supervisor) isStopping(e *entry) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return e.stopping
}

// CloseAll stops every tunnel; called on daemon shutdown so nothing is left behind.
func (s *Supervisor) CloseAll() {
	s.mu.Lock()
	ids := make([]uuid.UUID, 0, len(s.tunnels))
	for id, e := range s.tunnels {
		e.stopping = true
		ids = append(ids, id)
	}
	s.mu.Unlock()
	for _, id := range ids {
		s.mu.Lock()
		e, ok := s.tunnels[id]
		s.mu.Unlock()
		if !ok {
			continue
		}
		e.cancel()
		if e.handle != nil {
			e.handle.Stop()
		}
		s.forget(e)
	}
}

func (s *Supervisor) Count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.tunnels)
}

// URLOf reports the last URL known for a tunnel, for diagnostics.
func (s *Supervisor) URLOf(id uuid.UUID) string {
	s.mu.Lock()
	defer s.mu.Unlock()
	if e, ok := s.tunnels[id]; ok {
		return e.url
	}
	return ""
}

// --- pid files and orphan reaping ------------------------------------------------------
//
// A daemon restart leaves the previous generation's ssh processes running, and they keep
// serving. Nothing about that looks like an error: no log line, no failed request, just a
// live public URL that the platform believes is gone. Central is the authority on which
// tunnels should exist and re-opens them after reconnecting, so the previous generation is
// always the wrong one to keep.

func (s *Supervisor) pidPath(id uuid.UUID) string {
	return filepath.Join(s.runDir, id.String()+".pid")
}

func (s *Supervisor) writePID(id uuid.UUID, pid int) {
	if pid <= 0 {
		return
	}
	if err := os.MkdirAll(s.runDir, 0o750); err != nil {
		slog.Warn("could not create tunnel run directory", "error", err)
		return
	}
	if err := os.WriteFile(s.pidPath(id), []byte(strconv.Itoa(pid)+"\n"), 0o640); err != nil {
		slog.Warn("could not record tunnel pid", "error", err)
	}
}

func (s *Supervisor) removePID(id uuid.UUID) {
	if err := os.Remove(s.pidPath(id)); err != nil && !os.IsNotExist(err) {
		slog.Warn("could not remove tunnel pid file", "error", err)
	}
}

// ReapOrphans kills tunnel processes left by a previous daemon generation. Returns how many
// were killed, so startup can say so.
//
// A pid whose command line no longer looks like one of ours is left alone and only its pid
// file is removed: pids are reused, and killing an unrelated process would be a far worse
// bug than leaving a stale file.
func (s *Supervisor) ReapOrphans() int {
	entries, err := os.ReadDir(s.runDir)
	if err != nil {
		return 0
	}
	killed := 0
	for _, item := range entries {
		if item.IsDir() || !strings.HasSuffix(item.Name(), ".pid") {
			continue
		}
		path := filepath.Join(s.runDir, item.Name())
		raw, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
		if err != nil || pid <= 1 {
			_ = os.Remove(path)
			continue
		}
		if looksLikeTunnelProcess(pid) {
			if killProcessGroup(pid) {
				killed++
				slog.Warn("killed a tunnel left by a previous daemon run", "pid", pid)
			}
		}
		_ = os.Remove(path)
	}
	if killed > 0 {
		metrics.Increment(metrics.DaemonTunnelOrphanReapedTotal,
			map[string]string{"result": "killed"})
	}
	return killed
}

// looksLikeTunnelProcess checks /proc for a command line that matches what this package
// starts. The remote-forward argument is the distinguishing part: an unrelated ssh session
// on the machine does not carry it.
func looksLikeTunnelProcess(pid int) bool {
	raw, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
	if err != nil {
		return false
	}
	cmdline := strings.ReplaceAll(string(raw), "\x00", " ")
	if !strings.Contains(cmdline, "0:localhost:") {
		return false
	}
	return strings.Contains(cmdline, freeHost) || strings.Contains(cmdline, proHost)
}
