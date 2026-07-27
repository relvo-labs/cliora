package session

import (
	"context"
	"errors"
	"log/slog"
	"os/exec"
	"sync"
	"time"

	"github.com/cliora/cliora/daemon/internal/terminal"
	ctmux "github.com/cliora/cliora/daemon/internal/tmux"
	"github.com/google/uuid"
)

type State string

const (
	Starting State = "starting"
	Running  State = "running"
	Stopping State = "stopping"
	Exited   State = "exited"
	Failed   State = "failed"
)

type entry struct {
	state     State
	process   *terminal.Process
	workspace string
}
type Manager struct {
	mu                sync.Mutex
	tmux              ctmux.Client
	workspace, binary string
	stopGrace         time.Duration
	sessions          map[uuid.UUID]*entry
}

func New(client ctmux.Client, workspace, binary string) *Manager {
	return &Manager{
		tmux:      client,
		workspace: workspace,
		binary:    binary,
		stopGrace: ctmux.DefaultStopGrace,
		sessions:  make(map[uuid.UUID]*entry),
	}
}

// WithStopGrace overrides how long a CLI gets to exit on its own before the
// session is killed. Zero or negative restores the default.
func (m *Manager) WithStopGrace(grace time.Duration) *Manager {
	if grace > 0 {
		m.stopGrace = grace
	}
	return m
}

// Start launches a session on the manager's own workspace/binary with the "fake"
// runtime. A test convenience over StartSession — the P0 dispatcher that was its
// production caller was retired in P4-07, and the recovery/integration suites use it
// so they do not have to restate a runtime, workspace and binary they do not care
// about. Every production path calls StartSession with an explicitly allowlisted
// runtime and a guard-canonicalised workspace.
func (m *Manager) Start(ctx context.Context, id uuid.UUID, rows, columns uint16) error {
	return m.StartSession(ctx, id, "fake", m.workspace, m.binary, rows, columns)
}

// StartSession launches a session with an explicit allowlisted runtime, an
// already-canonicalised workspace, and the resolved binary (P2-07). The daemon
// never receives a command string; the caller resolves the binary from the
// runtime allowlist and validates the workspace via the workspace guard.
func (m *Manager) StartSession(
	ctx context.Context, id uuid.UUID, runtimeID, workspace, binary string, rows, columns uint16,
) error {
	m.mu.Lock()
	if _, exists := m.sessions[id]; exists {
		m.mu.Unlock()
		return errors.New("SESSION_ALREADY_EXISTS")
	}
	m.sessions[id] = &entry{state: Starting, workspace: workspace}
	m.mu.Unlock()
	err := m.tmux.Start(ctx, ctmux.StartSpec{
		SessionID: id,
		RuntimeID: runtimeID,
		Workspace: workspace,
		Binary:    binary,
		Size:      ctmux.Size{Rows: rows, Columns: columns},
	})
	m.mu.Lock()
	defer m.mu.Unlock()
	if err != nil {
		delete(m.sessions, id)
		return err
	}
	m.sessions[id].state = Running
	return nil
}
func (m *Manager) Attach(ctx context.Context, id uuid.UUID, rows, columns uint16, output func([]byte) error, onExit func(int)) (ctmux.Snapshot, error) {
	exists, err := m.tmux.Exists(ctx, id)
	if err != nil || !exists {
		return ctmux.Snapshot{}, errors.New("SESSION_NOT_FOUND")
	}
	slog.Info("attach session exists", "session_id", id)
	snapshot, err := m.tmux.Capture(ctx, id, 2*1024*1024)
	slog.Info("attach snapshot captured", "session_id", id, "snapshot_bytes", len(snapshot.Bytes))
	if err != nil {
		return ctmux.Snapshot{}, err
	}
	name, _ := ctmux.Name(id)
	args := []string{"attach-session", "-d", "-t", name}
	if m.tmux.Socket != "" {
		args = append([]string{"-L", m.tmux.Socket}, args...)
	}
	m.mu.Lock()
	currentBeforeAttach := m.sessions[id]
	var previousBeforeAttach *terminal.Process
	if currentBeforeAttach != nil {
		previousBeforeAttach = currentBeforeAttach.process
	}
	m.mu.Unlock()
	if previousBeforeAttach != nil {
		previousBeforeAttach.Detach()
	}
	exit := func(code int) {
		m.mu.Lock()
		if e := m.sessions[id]; e != nil {
			e.state = Exited
			e.process = nil
		}
		m.mu.Unlock()
		if onExit != nil {
			onExit(code)
		}
	}
	process, err := terminal.Attach(ctx, exec.CommandContext(ctx, "tmux", args...), rows, columns, output, exit)
	if err != nil {
		return ctmux.Snapshot{}, err
	}
	m.mu.Lock()
	current := m.sessions[id]
	var previous *terminal.Process
	if current != nil {
		previous = current.process
		current.process = process
		current.state = Running
	} else {
		m.sessions[id] = &entry{state: Running, process: process}
	}
	m.mu.Unlock()
	if previous != nil {
		go previous.Close()
	}
	return snapshot, nil
}

// ActiveCount reports sessions that are starting or running (for heartbeat).
// Workspace returns the launch workspace of a live session, used by the P3
// filesystem relay to confine list/read/search to that directory. The second
// result is false when the session is unknown.
func (m *Manager) Workspace(id uuid.UUID) (string, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.sessions[id]
	if !ok {
		return "", false
	}
	return e.workspace, true
}

func (m *Manager) ActiveCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	count := 0
	for _, e := range m.sessions {
		if e.state == Starting || e.state == Running {
			count++
		}
	}
	return count
}

func (m *Manager) Input(id uuid.UUID, payload []byte) error {
	m.mu.Lock()
	current := m.sessions[id]
	m.mu.Unlock()
	if current == nil || current.process == nil {
		return errors.New("SESSION_NOT_RUNNING")
	}
	return current.process.Write(payload)
}
func (m *Manager) Resize(id uuid.UUID, rows, columns uint16) error {
	m.mu.Lock()
	current := m.sessions[id]
	m.mu.Unlock()
	if current == nil || current.process == nil {
		return errors.New("SESSION_NOT_RUNNING")
	}
	return current.process.Resize(rows, columns)
}
func (m *Manager) Detach(id uuid.UUID) {
	m.mu.Lock()
	current := m.sessions[id]
	var process *terminal.Process
	if current != nil {
		process = current.process
		current.process = nil
	}
	m.mu.Unlock()
	if process != nil {
		process.Close()
	}
}

// Stop ends a session and reports which half of the FR-SESSION-005 sequence did
// it: the CLI exited on its own after the termination signal, or the grace period
// ran out and it was killed. An operator watching a runtime that never exits
// cleanly needs to see the difference, so the outcome is returned and logged
// rather than collapsed into "stopped".
func (m *Manager) Stop(ctx context.Context, id uuid.UUID) (ctmux.StopOutcome, error) {
	m.mu.Lock()
	current := m.sessions[id]
	if current != nil {
		current.state = Stopping
	}
	m.mu.Unlock()
	if current != nil && current.process != nil {
		current.process.Close()
	}
	outcome, err := m.tmux.Stop(ctx, id, m.stopGrace)
	if err != nil {
		return outcome, err
	}
	if outcome == ctmux.StopForced {
		slog.Warn("session_stop_forced", "session_id", id, "grace", m.stopGrace)
	}
	m.mu.Lock()
	delete(m.sessions, id)
	m.mu.Unlock()
	return outcome, nil
}
