package tmux

import (
	"context"
	"errors"
	"log/slog"
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
	// Args are the daemon-owned launch flags for RuntimeID (runtime.LaunchSpec).
	// They are appended as separate argv elements after Binary and are checked
	// against flagPattern below — see Start for why that check exists even though
	// the only caller is the daemon itself.
	Args []string
	Size Size
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

// Client addresses one tmux server. Socket keeps Cliora's sessions off the node
// owner's default server (see DefaultSocket) and ConfigPath is the generated
// config that server starts with (see conf.go). Both are empty in tests that only
// care about session mechanics.
type Client struct {
	Socket     string
	ConfigPath string
}

func (c Client) args(args ...string) []string {
	prefix := []string{}
	if c.Socket != "" {
		prefix = append(prefix, "-L", c.Socket)
	}
	// `-f` only takes effect on the invocation that starts the server, and tmux
	// accepts it on every subcommand, so it is passed unconditionally: which call
	// starts the server is a race we do not want to reason about.
	if c.ConfigPath != "" {
		prefix = append(prefix, "-f", c.ConfigPath)
	}
	if len(prefix) == 0 {
		return args
	}
	return append(prefix, args...)
}

// AttachArgs is the argv for attaching to a session, including this client's
// socket and config. The attach path used to build these by hand, which meant a
// client with a socket could create a session on one server and attach to
// another — the symptom being a session that exists and an attach that exits
// immediately.
func (c Client) AttachArgs(name string) []string {
	return c.args("attach-session", "-d", "-t", name)
}

func allowedRuntimeID(id string) bool {
	return id == "claude" || id == "codex" || id == "shell" || id == "fake"
}

// flagPattern is the shape a launch argument may take. The daemon is the only
// caller, so this is not defence against a hostile input — it is what makes the
// argument list safe under *either* reading of how tmux treats a multi-word
// shell-command (execvp directly, or joined and handed to a shell). A list that
// only ever contains flag tokens means the same thing both ways.
var flagPattern = regexp.MustCompile(`^--?[A-Za-z0-9][A-Za-z0-9._-]*$`)

func validArgs(args []string) bool {
	for _, a := range args {
		if !flagPattern.MatchString(a) {
			return false
		}
	}
	return true
}

func (c Client) Start(ctx context.Context, s StartSpec) error {
	if !allowedRuntimeID(s.RuntimeID) || !validSize(s.Size) || s.Binary == "" || s.Workspace == "" {
		return errors.New("invalid start spec")
	}
	if !validArgs(s.Args) {
		return errors.New("invalid start spec")
	}
	name, err := Name(s.SessionID)
	if err != nil {
		return err
	}
	argv := append(c.args("new-session", "-d", "-x", strconv.Itoa(int(s.Size.Columns)), "-y", strconv.Itoa(int(s.Size.Rows)), "-s", name, "-c", s.Workspace, s.Binary), s.Args...)
	cmd := exec.CommandContext(ctx, "tmux", argv...)
	cmd.Env = Env()
	if cmd.Run() != nil {
		return errors.New("tmux start failed")
	}
	c.applySessionOptions(ctx, name)
	return nil
}

// applySessionOptions repairs a server that was started before this config
// existed — an upgraded node whose tmux server is still running, for instance.
// `mouse` and `status` are session options and take effect immediately;
// history-limit cannot be fixed this way (a pane reads it when it is created), so
// scrollback depth on such a server stays at whatever it was until the last
// session ends. That gap is in the runbook rather than papered over here.
//
// Failure is logged, not returned: the session is already running, and a terminal
// that cannot scroll beats a terminal that would not open.
func (c Client) applySessionOptions(ctx context.Context, name string) {
	for _, opt := range [][2]string{{"mouse", "on"}, {"status", "off"}} {
		if err := exec.CommandContext(ctx, "tmux",
			c.args("set-option", "-t", name, opt[0], opt[1])...).Run(); err != nil {
			slog.Warn("tmux set-option failed", "session", name, "option", opt[0], "error", err)
		}
	}
}

// LegacySessionNames lists cliora-* sessions left on tmux's *default* socket by a
// daemon that predates DefaultSocket. They cannot be adopted — a tmux session
// belongs to its server — so this exists only so the fact reaches a log and
// `agentd doctor` instead of looking like sessions that vanished for no reason.
// Nothing is killed: those panes may hold work the user has not finished with.
func LegacySessionNames(ctx context.Context) []string {
	out, err := exec.CommandContext(ctx, "tmux",
		"list-sessions", "-F", "#{session_name}").Output()
	if err != nil {
		// No server on the default socket is the normal, healthy case.
		return nil
	}
	names := []string{}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if ValidName(strings.TrimSpace(line)) {
			names = append(names, strings.TrimSpace(line))
		}
	}
	return names
}

// HistoryLimit reports the scrollback depth the live server actually gives a
// session's pane. It is read from tmux rather than from config because those two
// can disagree (see applySessionOptions), and the number that matters to a user is
// this one.
func (c Client) HistoryLimit(ctx context.Context, id uuid.UUID) (int, error) {
	name, err := Name(id)
	if err != nil {
		return 0, err
	}
	out, err := exec.CommandContext(ctx, "tmux",
		c.args("display-message", "-p", "-t", name, "-F", "#{history_limit}")...).Output()
	if err != nil {
		return 0, errors.New("tmux history limit unavailable")
	}
	return strconv.Atoi(strings.TrimSpace(string(out)))
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
