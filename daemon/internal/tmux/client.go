package tmux

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/google/uuid"
)

const Prefix = "cliora-"

// DefaultTerm is the TERM handed to tmux when the daemon's own environment has
// nothing usable. agentd runs as a systemd service, which starts with TERM
// unset; tmux then falls back to the `unknown` terminfo entry, which has no
// `clear` capability, and the client dies with "open terminal failed: terminal
// does not support clear" the moment a session is attached. `dumb` fails the
// same way, so both are treated as absent.
const DefaultTerm = "xterm-256color"

// Env returns the daemon environment with TERM guaranteed to name a terminal
// tmux can open. An operator-supplied TERM is left alone.
func Env() []string {
	env := os.Environ()
	switch os.Getenv("TERM") {
	case "", "dumb", "unknown":
	default:
		return env
	}
	out := make([]string, 0, len(env)+1)
	for _, kv := range env {
		if !strings.HasPrefix(kv, "TERM=") {
			out = append(out, kv)
		}
	}
	return append(out, "TERM="+DefaultTerm)
}

var namePattern = regexp.MustCompile(`^cliora-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type Size struct {
	Rows    uint16
	Columns uint16
}
type StartSpec struct {
	SessionID   uuid.UUID
	RuntimeID   string
	WorkspaceID uuid.UUID
	Workspace   string
	Binary      string
	Size        Size
}
type Snapshot struct {
	Bytes     []byte
	Truncated bool
}

func Name(id uuid.UUID) (string, error) {
	if id == uuid.Nil {
		return "", errors.New("invalid session")
	}
	return Prefix + strings.ToLower(id.String()), nil
}
func ValidName(name string) bool { return namePattern.MatchString(name) }
func validSize(s Size) bool {
	return s.Rows >= 2 && s.Rows <= 300 && s.Columns >= 2 && s.Columns <= 500
}

type Client struct{ Socket string }

func (c Client) args(args ...string) []string {
	if c.Socket == "" {
		return args
	}
	return append([]string{"-L", c.Socket}, args...)
}

func allowedRuntimeID(id string) bool {
	return id == "claude" || id == "codex" || id == "shell" || id == "fake"
}

func (c Client) Start(ctx context.Context, s StartSpec) error {
	if !allowedRuntimeID(s.RuntimeID) || !validSize(s.Size) || s.Binary == "" || s.Workspace == "" {
		return errors.New("invalid start spec")
	}
	name, err := Name(s.SessionID)
	if err != nil {
		return err
	}
	cmd := exec.CommandContext(ctx, "tmux", c.args("new-session", "-d", "-x", strconv.Itoa(int(s.Size.Columns)), "-y", strconv.Itoa(int(s.Size.Rows)), "-s", name, "-c", s.Workspace, s.Binary)...)
	cmd.Env = Env()
	if cmd.Run() != nil {
		return errors.New("tmux start failed")
	}
	return nil
}
func (c Client) Exists(ctx context.Context, id uuid.UUID) (bool, error) {
	name, err := Name(id)
	if err != nil {
		return false, err
	}
	err = exec.CommandContext(ctx, "tmux", c.args("has-session", "-t", name)...).Run()
	if err == nil {
		return true, nil
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return false, nil
	}
	return false, errors.New("tmux unavailable")
}

// StopOutcome records which half of the FR-SESSION-005 sequence ended the
// session. A caller that cannot tell them apart cannot report an unresponsive CLI.
type StopOutcome string

const (
	// StopNotRunning: nothing to stop.
	StopNotRunning StopOutcome = "not-running"
	// StopGraceful: the pane process exited after SIGTERM, within the grace period.
	StopGraceful StopOutcome = "graceful"
	// StopForced: the grace period elapsed and the session was killed.
	StopForced StopOutcome = "forced"
)

// DefaultStopGrace is how long a CLI gets to exit on its own. It has to stay well
// inside Central's stop relay budget, or the relay gives up first and the caller
// never learns which outcome it got.
const DefaultStopGrace = 5 * time.Second

// stopPoll is how often the session is re-checked while waiting. Short enough that
// a fast exit is not billed the whole grace period.
const stopPoll = 100 * time.Millisecond

// Stop ends a session in the two stages FR-SESSION-005 describes: a normal
// termination signal to the pane process, a bounded wait, and a forced kill only
// if the process is still there.
//
// The signal goes to the pane process rather than straight to `kill-session`,
// because a CLI that is asked to exit can flush its state; one that has its
// session torn out from under it cannot. `grace` <= 0 uses DefaultStopGrace.
func (c Client) Stop(ctx context.Context, id uuid.UUID, grace time.Duration) (StopOutcome, error) {
	name, err := Name(id)
	if err != nil {
		return StopNotRunning, err
	}
	exists, err := c.Exists(ctx, id)
	if err != nil || !exists {
		return StopNotRunning, err
	}
	if grace <= 0 {
		grace = DefaultStopGrace
	}

	// A pane PID we cannot read means we cannot signal politely; fall through to
	// the forced kill rather than leaving the session running.
	if pid, err := c.panePID(ctx, name); err == nil && pid > 0 {
		if syscall.Kill(pid, syscall.SIGTERM) == nil {
			deadline := time.Now().Add(grace)
			for time.Now().Before(deadline) {
				select {
				case <-ctx.Done():
					return StopForced, c.kill(ctx, name)
				case <-time.After(stopPoll):
				}
				still, err := c.Exists(ctx, id)
				if err != nil {
					return StopForced, c.kill(ctx, name)
				}
				if !still {
					return StopGraceful, nil
				}
			}
		}
	}
	return StopForced, c.kill(ctx, name)
}

func (c Client) kill(ctx context.Context, name string) error {
	// The session may have exited between the last check and here, which is a
	// success, not a failure — so re-check rather than trusting the exit code.
	if exec.CommandContext(ctx, "tmux", c.args("kill-session", "-t", name)...).Run() != nil {
		if exec.CommandContext(ctx, "tmux", c.args("has-session", "-t", name)...).Run() == nil {
			return errors.New("tmux stop failed")
		}
	}
	return nil
}

func (c Client) panePID(ctx context.Context, name string) (int, error) {
	out, err := exec.CommandContext(ctx, "tmux",
		c.args("display-message", "-p", "-t", name, "-F", "#{pane_pid}")...).Output()
	if err != nil {
		return 0, errors.New("tmux pane pid unavailable")
	}
	return strconv.Atoi(strings.TrimSpace(string(out)))
}
func (c Client) Capture(ctx context.Context, id uuid.UUID, max int) (Snapshot, error) {
	name, err := Name(id)
	if err != nil {
		return Snapshot{}, err
	}
	out, err := exec.CommandContext(ctx, "tmux", c.args("capture-pane", "-p", "-e", "-S", "-", "-t", name)...).Output()
	if err != nil {
		return Snapshot{}, errors.New("tmux capture failed")
	}
	result := Snapshot{Bytes: out}
	if len(out) > max {
		result.Bytes = append([]byte(nil), out[len(out)-max:]...)
		result.Truncated = true
	}
	return result, nil
}
