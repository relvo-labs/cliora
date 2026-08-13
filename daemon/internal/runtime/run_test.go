package runtime

import (
	"context"
	"io"
	"os/exec"
	"strings"
	"testing"
	"time"
)

type fakeRuntime struct {
	id     string
	binary string
	args   []string
}

func (f fakeRuntime) ID() string                          { return f.id }
func (f fakeRuntime) Binary() string                      { return f.binary }
func (f fakeRuntime) LaunchArgs() []string                { return f.args }
func (f fakeRuntime) Validate(StartOptions) error         { return nil }
func (f fakeRuntime) BuildCommand(StartOptions) *exec.Cmd { return nil }
func (f fakeRuntime) Detect(context.Context, time.Time) DetectResult {
	return DetectResult{Runtime: f.id}
}

// The property SEC-002 exists to protect, asserted rather than reviewed: a run's argv
// is composed **only** of the configured binary and the daemon's own closed tables.
// The task itself never appears in it.
func TestBuildRunCommandKeepsTheTaskOutOfArgv(t *testing.T) {
	rt := fakeRuntime{id: "claude", binary: "claude"}
	secret := "please rm -rf / --no-preserve-root"
	cmd := BuildRunCommand(rt, RunOptions{Dir: "/var/lib/agentd/.cliora/runs/x/repo", Context: secret})
	if cmd == nil {
		t.Fatal("expected a command")
	}
	for _, arg := range cmd.Args {
		if strings.Contains(arg, "rm -rf") || arg == secret {
			t.Fatalf("the task context reached argv: %v", cmd.Args)
		}
	}
	// It reached stdin instead, which is what makes D7 hold: both CLIs read their
	// prompt from there, so the platform never had to choose.
	if cmd.Stdin == nil {
		t.Fatal("the task context was not written to stdin")
	}
	stdin, err := io.ReadAll(cmd.Stdin)
	if err != nil {
		t.Fatal(err)
	}
	if string(stdin) != secret {
		t.Fatalf("stdin carried %q", stdin)
	}
}

// The streaming flags are part of the table, not an option: liveness is judged from
// the event stream, so a runtime without one is reported as not runner-capable rather
// than run against a wall clock that misjudges a working agent.
func TestRunArgsCarryTheEventStreamFlags(t *testing.T) {
	claude := strings.Join(RunArgs("claude"), " ")
	if !strings.Contains(claude, "--output-format stream-json") {
		t.Fatalf("claude's table has no event stream: %s", claude)
	}
	codex := strings.Join(RunArgs("codex"), " ")
	if !strings.Contains(codex, "--json") {
		t.Fatalf("codex's table has no event stream: %s", codex)
	}
	// The permission mode is not optional for unattended execution. Measured
	// 2026-08-11: with default permissions `claude -p` refuses Bash and the run still
	// reports success, handing back a conclusion it could not have reached.
	if !strings.Contains(claude, "--permission-mode") {
		t.Fatalf("claude's table has no permission mode: %s", claude)
	}
}

// A runtime the daemon has no table for produces no command at all, which is how
// "this node cannot run agent work with that CLI" reaches the caller without a second
// error path.
func TestBuildRunCommandRefusesAnUnknownRuntime(t *testing.T) {
	if cmd := BuildRunCommand(fakeRuntime{id: "gemini", binary: "gemini"}, RunOptions{}); cmd != nil {
		t.Fatal("composed a command for a runtime with no argument table")
	}
	if cmd := BuildRunCommand(fakeRuntime{id: "claude", binary: ""}, RunOptions{}); cmd != nil {
		t.Fatal("composed a command for a disabled runtime")
	}
}

// The probe is a **regression guard**, not discovery: the flags were measured. What it
// protects against is a third-party CLI changing its interface — those binaries are
// installed by the node's owner and are not versioned with `node_update`, so nothing
// else would notice. The failure it prevents looks like "the agent is slow".
func TestProbeRunCapableReportsAReasonRatherThanJustFalse(t *testing.T) {
	probe := ProbeRunCapable(context.Background(),
		fakeRuntime{id: "claude", binary: "definitely-not-installed-cliora"}, time.Second)
	if probe.Capable {
		t.Fatal("a missing binary is not runner-capable")
	}
	if probe.Reason == "" {
		t.Fatal("a bare false is what the Agents page cannot explain to anybody")
	}
}
