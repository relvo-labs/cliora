package runner

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os/exec"
	"sync"
	"syscall"
	"time"
)

// Running one agent, and knowing when it has stopped being one (ADR 0029 §4).
//
// Three timers exist and they answer three different questions. Conflating any two of
// them is the mistake this file is shaped to avoid:
//
//	lease   is the runner alive?        Central judges it; expiry re-queues the card
//	idle    is the child progressing?   **this file** judges it, from the event stream
//	wall    will it ever stop?          a backstop, six hours, nothing more
//
// The first draft of this phase had only a wall clock, and that was wrong in a
// specific way: *a one-shot command exceeding a deadline does not mean it stopped
// working.* It usually means the agent is still thinking. So liveness is judged from
// the CLI's JSONL event stream — every line resets the idle timer — and the wall clock
// only catches the run that will never end.
//
// **Byte-level activity would be weaker than event-level.** A spinner redrawing proves
// the renderer is alive and nothing else; an event proves the agent did something.

// Sink receives a run's output. The daemon's implementation forwards chunks to
// Central; tests collect them.
type Sink interface {
	// Chunk is called with one slice of output. Never with a partial line: half a
	// JSON event cannot be rendered, and "do not split a line" outranks "fill the
	// chunk" (ADR 0030 Part A).
	Chunk(data string, truncated bool)
	// Event is called once per parsed event line, so the caller can advance its own
	// notion of "last activity" without re-reading the stream.
	Event()
}

// Outcome is how a run ended, as the daemon saw it.
type Outcome struct {
	ExitCode  int
	ErrorCode string
	Err       error
}

// Options bound one execution.
type Options struct {
	// ChunkBytes is the wire ceiling for one `run.log_chunk`. 32 KiB, and the type is
	// deliberately not in the large-frame set: this socket also carries interactive
	// terminal bytes.
	ChunkBytes int
	// IdleTimeout is the **primary** liveness judgement.
	IdleTimeout time.Duration
	// WallClock is the backstop.
	WallClock time.Duration
	// GraceKill is how long SIGINT is given before SIGKILL.
	GraceKill time.Duration
	// Now is injectable so the timers can be tested without sleeping.
	Now func() time.Time
}

func (o Options) withDefaults() Options {
	if o.ChunkBytes <= 0 {
		o.ChunkBytes = 32 * 1024
	}
	if o.IdleTimeout <= 0 {
		o.IdleTimeout = 300 * time.Second
	}
	if o.WallClock <= 0 {
		o.WallClock = 6 * time.Hour
	}
	if o.GraceKill <= 0 {
		o.GraceKill = 10 * time.Second
	}
	if o.Now == nil {
		o.Now = time.Now
	}
	return o
}

// Execution is a started child plus the means to stop it.
type Execution struct {
	cmd  *exec.Cmd
	opts Options

	mu           sync.Mutex
	lastEvent    time.Time
	cancelledFor string
}

// Start launches the child in **its own process group**.
//
// The process group is what makes cancellation complete. An agent spawns a shell,
// which spawns a test runner, which spawns compilers; signalling only the child leaves
// that tree running and the node's capacity accounting wrong. `Setpgid` plus a
// negative pid on the signal is the whole mechanism, and it is why exit condition 11
// can be asserted by scanning `/proc` rather than by looking at a screenshot.
func Start(cmd *exec.Cmd, opts Options) (*Execution, io.ReadCloser, error) {
	opts = opts.withDefaults()
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	// The same convention `runtime.go` already uses: force the pipes closed shortly
	// after the process is killed, so an orphaned grandchild holding the write end
	// cannot keep a read blocked forever.
	cmd.WaitDelay = 2 * time.Second

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, nil, err
	}
	cmd.Stderr = cmd.Stdout
	if err := cmd.Start(); err != nil {
		return nil, nil, err
	}
	return &Execution{cmd: cmd, opts: opts, lastEvent: opts.Now()}, stdout, nil
}

// Pump reads the child's output, chunks it on line boundaries, and enforces the idle
// timer.
//
// It returns when the stream closes or when a timer fires. The caller waits for the
// process separately, because a killed process still has to be reaped.
func (e *Execution) Pump(ctx context.Context, out io.Reader, sink Sink) error {
	scanner := bufio.NewScanner(out)
	// A single JSON event can be large — a tool result carrying a file, for instance.
	// The buffer is generous, and a line beyond it is truncated by the scanner rather
	// than dropping the rest of the stream.
	scanner.Buffer(make([]byte, 64*1024), 4*1024*1024)

	lines := make(chan string, 64)
	scanErr := make(chan error, 1)
	go func() {
		defer close(lines)
		for scanner.Scan() {
			lines <- scanner.Text()
		}
		scanErr <- scanner.Err()
	}()

	var pending []byte
	flush := func(truncated bool) {
		if len(pending) == 0 {
			return
		}
		sink.Chunk(string(pending), truncated)
		pending = pending[:0]
	}

	idle := time.NewTimer(e.opts.IdleTimeout)
	defer idle.Stop()
	wall := time.NewTimer(e.opts.WallClock)
	defer wall.Stop()
	// Flushing on a tick as well as on size: a run that emits one small event a minute
	// would otherwise be invisible until it filled a chunk.
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			flush(false)
			return ctx.Err()
		case line, ok := <-lines:
			if !ok {
				flush(false)
				select {
				case err := <-scanErr:
					return err
				default:
					return nil
				}
			}
			e.markEvent()
			sink.Event()
			if !idle.Stop() {
				select {
				case <-idle.C:
				default:
				}
			}
			idle.Reset(e.opts.IdleTimeout)
			// Whole lines only. If adding this one would exceed the ceiling, the
			// buffer goes first — a chunk that ends mid-event is a chunk the UI
			// cannot render.
			if len(pending)+len(line)+1 > e.opts.ChunkBytes {
				flush(false)
			}
			if len(line)+1 > e.opts.ChunkBytes {
				// One line larger than a whole chunk. Truncated here rather than
				// split, and flagged, so the reader knows something was lost instead
				// of seeing malformed JSON.
				sink.Chunk(line[:e.opts.ChunkBytes-1], true)
				continue
			}
			if len(pending) > 0 {
				pending = append(pending, '\n')
			}
			pending = append(pending, line...)
		case <-ticker.C:
			flush(false)
		case <-idle.C:
			flush(false)
			return ErrIdleTimeout
		case <-wall.C:
			flush(false)
			return ErrWallClock
		}
	}
}

// The two timers a caller has to tell apart, because they mean different things to a
// person: one is "it is stuck, look at the last event", the other is "it cannot
// finish, look at whether the card is too big".
var (
	ErrIdleTimeout = errors.New("RUN_IDLE_TIMEOUT")
	ErrWallClock   = errors.New("RUN_TIMEOUT")
)

func (e *Execution) markEvent() {
	e.mu.Lock()
	e.lastEvent = e.opts.Now()
	e.mu.Unlock()
}

// LastEvent is when the child last emitted something. Reported to Central so the Run
// detail page can say "last activity: 3 minutes ago" — **not** so Central can judge
// idleness, which stays here where the stream is.
func (e *Execution) LastEvent() time.Time {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.lastEvent
}

// Cancel terminates the whole process group in three phases.
//
//	SIGINT → wait GraceKill for the **group** to empty → SIGKILL the group
//
// SIGINT first because both CLIs treat it as "stop cleanly", which gives an agent the
// chance to finish writing a file it had open. SIGKILL after a bounded wait because
// "cleanly" cannot be waited on forever. Both signals go to **-pgid**, not to the
// child: the agent's own children are the ones that would otherwise survive.
//
// **The wait is on the group, not on the leader**, and that distinction is the whole
// difference between this working and appearing to work. An agent's shell exits on
// SIGINT while the `sleep`s it backgrounded keep running: waiting for the leader and
// then returning leaves those behind, the node's capacity accounting is wrong, and
// nothing looks broken. The first version of this function did exactly that, and the
// process-group scan in the test is what caught it.
//
// It also does not reap: `Wait` owns that. Two waits on one process make the second
// fail with "no child processes", which would turn a successful cancel into a
// reported error.
func (e *Execution) Cancel(reason string) error {
	e.mu.Lock()
	e.cancelledFor = reason
	e.mu.Unlock()
	if e.cmd.Process == nil {
		return nil
	}
	pgid, err := syscall.Getpgid(e.cmd.Process.Pid)
	if err != nil {
		// Already gone; there is nothing to signal, and that is a success rather than
		// an error the caller should report.
		return nil
	}
	_ = syscall.Kill(-pgid, syscall.SIGINT)

	deadline := time.Now().Add(e.opts.GraceKill)
	for time.Now().Before(deadline) {
		if !groupAlive(pgid) {
			return nil
		}
		time.Sleep(20 * time.Millisecond)
	}
	// Unconditional, and its error is ignored when the group has emptied in the
	// meantime: "nothing to kill" is the outcome we wanted.
	if err := syscall.Kill(-pgid, syscall.SIGKILL); err != nil && !errors.Is(err, syscall.ESRCH) {
		return err
	}
	return nil
}

// groupAlive reports whether any process remains in the group. Signal 0 performs the
// permission and existence checks without delivering anything.
func groupAlive(pgid int) bool {
	err := syscall.Kill(-pgid, 0)
	return err == nil
}

// CancelledFor reports the reason Cancel was called with, or "".
func (e *Execution) CancelledFor() string {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.cancelledFor
}

// Wait reaps the child and maps its exit into an outcome.
func (e *Execution) Wait() Outcome {
	err := e.cmd.Wait()
	if err == nil {
		return Outcome{ExitCode: 0}
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		code := exitErr.ExitCode()
		if reason := e.CancelledFor(); reason != "" {
			return Outcome{ExitCode: code, ErrorCode: "RUN_CANCELLED", Err: err}
		}
		return Outcome{ExitCode: code, ErrorCode: "RUN_INTERNAL_ERROR", Err: err}
	}
	return Outcome{ExitCode: -1, ErrorCode: "RUN_INTERNAL_ERROR", Err: err}
}

// Pid exposes the child's pid so a test can assert the process group is empty after a
// cancel — the machine form of exit condition 11.
func (e *Execution) Pid() int {
	if e.cmd.Process == nil {
		return 0
	}
	return e.cmd.Process.Pid
}
