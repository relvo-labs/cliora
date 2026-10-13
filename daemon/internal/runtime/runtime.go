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
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/google/uuid"
)

// Reasons reported when a runtime is not usable (mapped to protocol error codes).
const (
	ReasonDisabled      = "RUNTIME_DISABLED"
	ReasonNotFound      = "RUNTIME_NOT_FOUND"
	ReasonNotExecutable = "RUNTIME_NOT_EXECUTABLE"
	// ReasonSandboxFlagUnsupported is reported alongside an *available* runtime: the
	// node selected a permission flag but the installed binary does not know
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
	// PermissionMode is the requested node mode; EffectivePermissionMode becomes
	// cli_default when its flag is unsupported. These are local diagnostics only.
	PermissionMode          config.PermissionMode
	EffectivePermissionMode config.PermissionMode
	PermissionSource        string
	FlagApplied             bool
	// SandboxBypass is measured: true only for an applied full_access flag.
	// Auto retains the sandbox, so its existing wire report is false.
	SandboxBypass bool
	// SandboxNote explains an unsupported flag on an otherwise usable runtime.
	// Only doctor and the startup log read it; it is not a protocol error.
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
	// permissionMode selects only an entry in the daemon-owned table.
	permissionMode   config.PermissionMode
	permissionSource string
	// permissionProbe caches whether the installed binary accepts the flag. Probed
	// once per process: the answer only changes when the CLI is upgraded, and an
	// upgrade is followed by a daemon restart or reconnect (runbook).
	probeMu         sync.Mutex
	permissionProbe *bool
}

func (r *cliRuntime) ID() string { return r.id }

func (r *cliRuntime) Binary() string {
	if !r.enabled {
		return ""
	}
	return r.binary
}

// LaunchArgs returns the selected flags only when the installed CLI accepts them.
// Unsupported auto never falls back to full access: the only fallback is no flag.
func (r *cliRuntime) LaunchArgs() []string {
	args := PermissionArgs(r.id, r.permissionMode)
	if !r.enabled || len(args) == 0 || !r.permissionAvailable() {
		return nil
	}
	return args
}

// permissionAvailable probes `<binary> --help` once for the selected flag.
// Launching with a flag to test it would start an interactive session instead.
func (r *cliRuntime) permissionAvailable() bool {
	r.probeMu.Lock()
	defer r.probeMu.Unlock()
	if r.permissionProbe != nil {
		return *r.permissionProbe
	}
	args := PermissionArgs(r.id, r.permissionMode)
	supported := len(args) > 0 && flagAccepted(r.binary, args[0], r.timeout)
	r.permissionProbe = &supported
	return supported
}

// flagAccepted reports whether a binary's help output declares the exact flag token.
// The line must start with the option, optionally after one short alias and a
// comma; prose mentions and longer lookalikes are not evidence of support. Bounded the
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
	option := regexp.MustCompile(`(?m)^[[:space:]]*(-[A-Za-z0-9],[[:space:]]+)?` + regexp.QuoteMeta(flag) + `([[:space:],=<\[]|$)`)
	return option.Match(out)
}

func (r *cliRuntime) Detect(ctx context.Context, now time.Time) DetectResult {
	result := DetectResult{
		Runtime:                 r.id,
		CheckedAt:               now,
		PermissionMode:          r.permissionMode,
		EffectivePermissionMode: config.PermissionCLIDefault,
		PermissionSource:        r.permissionSource,
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
	result.FlagApplied = len(r.LaunchArgs()) > 0
	if result.FlagApplied {
		result.EffectivePermissionMode = r.permissionMode
	}
	result.SandboxBypass = result.FlagApplied && r.permissionMode == config.PermissionFullAccess
	if len(PermissionArgs(r.id, r.permissionMode)) > 0 && !result.FlagApplied {
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
