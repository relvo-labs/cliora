package runtime

import (
	"context"
	"os/exec"
	"strings"
	"time"
)

// Non-interactive execution for an agent run (ADR 0029, plan/18/04-…md §5).
//
// **This is a new file, and `runtime.go` and `launch.go` are byte-identical to the
// version before this phase.** That is not tidiness: `launch.go` already carries the
// judgement this phase had to satisfy — *"adding a caller-supplied string to this
// table is the change SEC-002 exists to prevent"* — and a separate file lets a gate
// assert those two files did not move, rather than asking a reviewer to confirm it.
//
// **The task context goes in on stdin, never in argv.** M-AR-1 measured both CLIs on
// 2026-08-10: `claude -p` documents itself as "print response and exit (useful for
// pipes)", and `codex exec` documents that "if not provided as an argument … the
// instructions are read from stdin". Because both read from stdin, the platform never
// has to choose between passing the task to the agent and keeping argv closed.
//
// So a run's argv is composed of exactly three things, all of them the daemon's:
//
//	<binary from the config file> <runArgs table> <sandbox flags from launch.go>
//
// Nothing from a wire payload, a card, or the agent reaches it.

// runArgs is the closed table of non-interactive arguments, measured rather than
// guessed (M-AR-1, plan/18/10-…md §1.1).
//
// The streaming flags are part of the table, not an option: liveness is judged from
// the event stream (ADR 0029 §4), so a runtime without one is treated as **not
// runner-capable** rather than falling back to a wall clock that misjudges a working
// agent. Byte-level activity would be weaker still — a spinner redrawing proves only
// that the renderer is alive.
var runArgs = map[string][]string{
	"claude": {"-p", "--output-format", "stream-json", "--verbose"},
	"codex":  {"exec", "--json"},
}

// permissionArgs is the second closed table, and it exists because of a finding
// rather than a preference.
//
// Measured on 2026-08-11: with default permissions `claude -p` **refuses the Bash
// tool and the run still succeeds** — it ends with `result/success` having produced a
// report it could not have obtained. That is worse than a timeout: a "successful" run
// hands back an unfounded conclusion. So a permission mode is not optional for
// unattended execution, and it is spelled out here where a security review reads the
// complete set of arguments in one place.
//
// The value is the node's, through `runtime.<id>.sandbox_bypass`, exactly as the
// interactive path already works: the platform reports the posture and never sets it
// (ADR 0023 D3). A node that has not opted in gets a runtime reported as
// **not runner-capable**, which is visible on the Agents page, rather than a run that
// silently cannot use its tools.
var permissionArgs = map[string][]string{
	"claude": {"--permission-mode", "bypassPermissions"},
	// codex's own `exec` already runs without approvals; its sandbox is chosen by
	// `-s`, and `workspace-write` scopes it to the run directory — which is a
	// stronger guarantee than the platform itself provides, given to us by the
	// runtime rather than promised by us (ADR 0031 §6).
	"codex": {"-s", "workspace-write"},
}

// RunOptions is what the daemon knows about one run. Deliberately not a wire type:
// the fields it does *not* have (command, args, env, workspace) are the point.
type RunOptions struct {
	// Dir is the run's own directory — the checkout, never an allowed root.
	Dir string
	// Context is the task context pack, written to the child's stdin.
	Context string
	// Env is the child's environment. The daemon's three git fail-fast variables are
	// **not** added here: their purpose is to stop the daemon's own clone hanging on a
	// prompt, and putting them in the agent's environment would break a push that the
	// second ruling of 2026-08-10 deliberately allows.
	Env []string
}

// BuildRunCommand composes the non-interactive command for a runtime.
//
// A free function rather than a method on Runtime, so the interface — which the
// interactive path also implements — does not grow a member for a mode it does not
// have. It returns nil for a runtime with no entry, which is how "this node cannot run
// agent work with that CLI" reaches the caller without a second error path.
func BuildRunCommand(rt Runtime, opts RunOptions) *exec.Cmd {
	if rt == nil {
		return nil
	}
	binary := rt.Binary()
	args, ok := runArgs[rt.ID()]
	if binary == "" || !ok {
		return nil
	}
	full := append([]string(nil), args...)
	full = append(full, permissionArgs[rt.ID()]...)
	// The interactive path's own table, unchanged and reused rather than copied:
	// whether this node runs its CLI without a sandbox is one decision, and it should
	// not be able to differ between a session and a run.
	full = append(full, rt.LaunchArgs()...)

	cmd := exec.Command(binary, full...)
	cmd.Dir = opts.Dir
	cmd.Env = opts.Env
	// The prompt, and then EOF. Closing stdin immediately after writing is part of the
	// contract with both CLIs: one that is still holding an open stdin can wait on it
	// forever, and that wait is indistinguishable from an agent thinking.
	cmd.Stdin = strings.NewReader(opts.Context)
	return cmd
}

// RunArgs exposes the closed table for tests and for `agentd doctor`, copied so a
// caller cannot mutate it.
func RunArgs(id string) []string {
	args, ok := runArgs[id]
	if !ok {
		return nil
	}
	out := append([]string(nil), args...)
	return append(out, permissionArgs[id]...)
}

// RunCapable reports whether this runtime can be driven non-interactively **with an
// event stream**, by probing the installed binary's help output.
//
// Its role is a regression guard rather than discovery: the flags themselves were
// measured (M-AR-1). What the probe protects against is a third-party CLI changing its
// interface — those two binaries are installed by the node's owner and are not
// versioned with `node_update`, so nothing else would notice. Without it the failure
// looks like "the agent is slow": the process opens an interactive session and sits
// there until a timer.
//
// **The result is cached per connection, not per process.** `bypassProbe` caches for
// the life of the process, and a reconnect does not re-probe — that comment is
// slightly optimistic even for its own case, and here it would be worse: a stale
// "not capable" means a runner never claims a card, while the console shows a reason
// that is no longer true (plan/18/04-…md §5.3).
type RunCapability struct {
	Runtime string
	Capable bool
	// Reason is empty when capable, and otherwise says what a person can do about it.
	Reason string
}

// ProbeRunCapable checks one runtime. Callers hold the result for one connection.
func ProbeRunCapable(ctx context.Context, rt Runtime, timeout time.Duration) RunCapability {
	result := RunCapability{Runtime: rt.ID()}
	binary := rt.Binary()
	if binary == "" {
		result.Reason = "runtime is disabled in this node's configuration"
		return result
	}
	args, ok := runArgs[rt.ID()]
	if !ok {
		result.Reason = "the daemon has no non-interactive argument table for this runtime"
		return result
	}
	path, err := exec.LookPath(binary)
	if err != nil {
		result.Reason = "the binary is not on PATH"
		return result
	}
	probeCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(probeCtx, path, "--help")
	cmd.WaitDelay = 200 * time.Millisecond
	out, err := cmd.CombinedOutput()
	if err != nil && len(out) == 0 {
		result.Reason = "the binary did not answer --help"
		return result
	}
	help := string(out)
	// Every flag in the table has to appear, the streaming one included: a CLI that
	// can run non-interactively but cannot emit events is reported as not capable
	// rather than run against a wall clock.
	for _, arg := range args {
		if !strings.HasPrefix(arg, "-") {
			continue
		}
		if !strings.Contains(help, arg) {
			result.Reason = "this version does not accept " + arg +
				"; update the CLI so the daemon can run it non-interactively with an event stream"
			return result
		}
	}
	for _, arg := range permissionArgs[rt.ID()] {
		if strings.HasPrefix(arg, "-") && !strings.Contains(help, arg) {
			result.Reason = "this version does not accept " + arg +
				"; without it an unattended run is refused its tools and still reports success"
			return result
		}
	}
	result.Capable = true
	return result
}
