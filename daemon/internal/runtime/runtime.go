// Package runtime detects and describes the allowlisted CLI runtimes
// (claude, codex). The renderer never supplies a command; the daemon builds the
// exact argv from the configured binary for the allowlisted id only
// (FR-RUNTIME-001/003/004, SEC-002).
package runtime

import (
	"context"
	"errors"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

// Reasons reported when a runtime is not usable (mapped to protocol error codes).
const (
	ReasonDisabled      = "RUNTIME_DISABLED"
	ReasonNotFound      = "RUNTIME_NOT_FOUND"
	ReasonNotExecutable = "RUNTIME_NOT_EXECUTABLE"
	// ReasonSandboxFlagUnsupported is reported alongside an *available* runtime: the
	// node asked for the sandbox to be off but the installed binary does not know
	// the flag (ADR 0023 D3). It is not a protocol error code.
	ReasonSandboxFlagUnsupported = "RUNTIME_SANDBOX_FLAG_UNSUPPORTED"
)

// Validation errors returned by Runtime.Validate for a rejected StartOptions.
var (
	ErrRuntimeDisabled  = errors.New(ReasonDisabled)
	ErrRuntimeNotFound  = errors.New(ReasonNotFound)
	ErrInvalidSession   = errors.New("INVALID_SESSION")
	ErrInvalidWorkspace = errors.New("INVALID_WORKSPACE")
	ErrInvalidSize      = errors.New("INVALID_SIZE")
)

type StartOptions struct {
	SessionID uuid.UUID
	Workspace string
	Rows      uint16
	Columns   uint16
}

type DetectResult struct {
	Runtime    string
	Available  bool
	Version    string
	BinaryPath string
	Reason     string
	CheckedAt  time.Time
	// SandboxBypassRequested is what this node's config asked for; SandboxBypass is
	// what the binary will actually be launched with. They differ when the
	// installed CLI does not accept the flag, which is a third-party interface
	// change we report rather than assume away: reporting the requested value would
	// make the console claim a posture the machine is not in (ADR 0023 D3).
	SandboxBypassRequested bool
	SandboxBypass          bool
	// SandboxNote explains a requested-but-unavailable bypass. Separate from Reason
	// because the runtime is still usable; only doctor and the startup log read it.
	SandboxNote string
}

type Runtime interface {
	ID() string
	Detect(ctx context.Context, now time.Time) DetectResult
	Validate(opts StartOptions) error
	BuildCommand(opts StartOptions) *exec.Cmd
	// Binary returns the configured binary name when the runtime is enabled, or
	// "" when disabled (used to resolve an allowlisted launch binary).
	Binary() string
	// LaunchArgs returns the daemon-owned arguments for this runtime — never
	// anything a caller, message or config file supplied a string for (SEC-002).
	LaunchArgs() []string
}

// cliRuntime is a generic adapter for a version-flagged CLI (claude/codex).
type cliRuntime struct {
	id      string
	enabled bool
	binary  string
	timeout time.Duration
	// bypassRequested mirrors config's sandbox_bypass for this runtime.
	bypassRequested bool
	// bypassProbe caches whether the installed binary accepts the flag. Probed
	// once per process: the answer only changes when the CLI is upgraded, and an
	// upgrade is followed by a daemon restart or reconnect (runbook).
	probeMu     sync.Mutex
	bypassProbe *bool
}

func (r *cliRuntime) ID() string { return r.id }

func (r *cliRuntime) Binary() string {
	if !r.enabled {
		return ""
	}
	return r.binary
}

// LaunchArgs returns the sandbox-bypass flags when this node asked for them and
// the installed binary accepts them, and nil otherwise. A runtime with no entry in
// the flag table always returns nil.
func (r *cliRuntime) LaunchArgs() []string {
	if !r.enabled || !r.bypassRequested || !SupportsSandboxBypass(r.id) {
		return nil
	}
	if !r.bypassAvailable() {
		return nil
	}
	return SandboxBypassArgs(r.id)
}

// bypassAvailable probes `<binary> --help` once and reports whether the flag
// appears. There is no way to ask a CLI whether it knows a flag: --version does
// not list flags, and launching with the flag would start an interactive session.
func (r *cliRuntime) bypassAvailable() bool {
	r.probeMu.Lock()
	defer r.probeMu.Unlock()
	if r.bypassProbe != nil {
		return *r.bypassProbe
	}
	supported := flagAccepted(r.binary, SandboxBypassFlag, r.timeout)
	r.bypassProbe = &supported
	return supported
}

// flagAccepted reports whether a binary's help output mentions flag. Bounded the
// same way version detection is (tech §8.5): a hung --help must not be able to
// stall a session launch, and WaitDelay closes the pipes so an orphaned
// grandchild cannot hold CombinedOutput open past the timeout.
func flagAccepted(binary, flag string, timeout time.Duration) bool {
	path, err := exec.LookPath(binary)
	if err != nil {
		return false
	}
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, "--help")
	cmd.WaitDelay = 200 * time.Millisecond
	out, err := cmd.CombinedOutput()
	if err != nil && len(out) == 0 {
		return false
	}
	return strings.Contains(string(out), flag)
}

func (r *cliRuntime) Detect(ctx context.Context, now time.Time) DetectResult {
	result := DetectResult{
		Runtime:                r.id,
		CheckedAt:              now,
		SandboxBypassRequested: r.bypassRequested && SupportsSandboxBypass(r.id),
	}
	if !r.enabled {
		result.Reason = ReasonDisabled
		return result
	}
	path, err := exec.LookPath(r.binary)
	if err != nil {
		result.Reason = ReasonNotFound
		return result
	}
	result.BinaryPath = path

	// Bound detection so a hung binary cannot block startup (tech §8.5).
	detectCtx, cancel := context.WithTimeout(ctx, r.timeout)
	defer cancel()
	cmd := exec.CommandContext(detectCtx, path, "--version")
	// WaitDelay forces the I/O pipes closed shortly after the context is
	// cancelled, so an orphaned grandchild (e.g. a `sleep` under `sh`) holding
	// the write end cannot make CombinedOutput block past the timeout.
	cmd.WaitDelay = 200 * time.Millisecond
	out, err := cmd.CombinedOutput()
	if err != nil {
		result.Reason = ReasonNotExecutable
		return result
	}
	result.Available = true
	result.Version = firstLine(out)
	// Only probe the flag on a runtime that is otherwise usable: an unavailable
	// runtime has nothing to report, and the probe costs another process.
	result.SandboxBypass = len(r.LaunchArgs()) > 0
	if result.SandboxBypassRequested && !result.SandboxBypass {
		// Deliberately not Reason: Reason explains why a runtime is *unusable*, and
		// this one launches fine. The console shows "sandbox: enforced" for it, which
		// is the truth, and doctor prints this note to explain why (ADR 0023 D3).
		result.SandboxNote = ReasonSandboxFlagUnsupported
	}
	return result
}

// Validate checks that a launch request is admissible without starting anything
// (P1 scope): the runtime must be enabled with a resolvable binary, and the
// caller-supplied options must be well-formed. The command itself is always
// derived from the configured binary — never from caller strings (SEC-002) — so
// there is nothing here to sanitise beyond the typed StartOptions.
func (r *cliRuntime) Validate(opts StartOptions) error {
	if !r.enabled {
		return ErrRuntimeDisabled
	}
	if r.binary == "" {
		return ErrRuntimeNotFound
	}
	if _, err := exec.LookPath(r.binary); err != nil {
		return ErrRuntimeNotFound
	}
	if opts.SessionID == uuid.Nil {
		return ErrInvalidSession
	}
	if opts.Workspace == "" || !filepath.IsAbs(opts.Workspace) {
		return ErrInvalidWorkspace
	}
	if opts.Rows < 2 || opts.Rows > 300 || opts.Columns < 2 || opts.Columns > 500 {
		return ErrInvalidSize
	}
	return nil
}

// BuildCommand constructs the argv from the configured binary plus the daemon's
// own flag table — never from caller-supplied strings.
func (r *cliRuntime) BuildCommand(opts StartOptions) *exec.Cmd {
	cmd := exec.Command(r.binary, r.LaunchArgs()...)
	cmd.Dir = opts.Workspace
	return cmd
}

func firstLine(out []byte) string {
	line, _, _ := strings.Cut(strings.TrimSpace(string(out)), "\n")
	return line
}
