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
	"time"

	"github.com/google/uuid"
)

// Reasons reported when a runtime is not usable (mapped to protocol error codes).
const (
	ReasonDisabled      = "RUNTIME_DISABLED"
	ReasonNotFound      = "RUNTIME_NOT_FOUND"
	ReasonNotExecutable = "RUNTIME_NOT_EXECUTABLE"
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
}

type Runtime interface {
	ID() string
	Detect(ctx context.Context, now time.Time) DetectResult
	Validate(opts StartOptions) error
	BuildCommand(opts StartOptions) *exec.Cmd
	// Binary returns the configured binary name when the runtime is enabled, or
	// "" when disabled (used to resolve an allowlisted launch binary).
	Binary() string
}

// cliRuntime is a generic adapter for a version-flagged CLI (claude/codex).
type cliRuntime struct {
	id      string
	enabled bool
	binary  string
	timeout time.Duration
}

func (r *cliRuntime) ID() string { return r.id }

func (r *cliRuntime) Binary() string {
	if !r.enabled {
		return ""
	}
	return r.binary
}

func (r *cliRuntime) Detect(ctx context.Context, now time.Time) DetectResult {
	result := DetectResult{Runtime: r.id, CheckedAt: now}
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

// BuildCommand constructs the argv from the configured binary only — never from
// caller-supplied strings. Actual session launch lands in P2.
func (r *cliRuntime) BuildCommand(opts StartOptions) *exec.Cmd {
	cmd := exec.Command(r.binary)
	cmd.Dir = opts.Workspace
	return cmd
}

func firstLine(out []byte) string {
	line, _, _ := strings.Cut(strings.TrimSpace(string(out)), "\n")
	return line
}
