// Package update performs a verified, reversible self-update of the agentd
// binary (P4-10, ADR 0017, SEC-002/SEC-007).
//
// The security property is in the type signature: Update takes a *version* and
// two booleans. There is no parameter — and no CLI flag, and no protocol field —
// for a URL, a filename, a digest or a path. Every one of those is derived from
// the release manifest Central publishes plus this node's own config file, so a
// caller who can ask for an update cannot ask for an arbitrary binary. A test
// asserts the signature stays that shape, because this is exactly the kind of
// boundary that a later "just add a --url for testing" quietly removes.
//
// The order of the six stages is the other half of the design. Nothing touches
// the installed binary until the download has been verified against the manifest
// digest *and* the staged binary has been executed in place to confirm it reports
// the version it claims. Verify-then-swap means a corrupt or wrong-version
// artifact fails while the running installation is still untouched.
//
// Privilege (SEC-007): the long-running daemon is non-root and therefore cannot
// replace /usr/local/bin/agentd or restart its own unit. It answers
// UPDATE_NOT_ALLOWED and says an operator must run `sudo agentd update` —
// deliberately, rather than being given a way to escalate. That also avoids the
// obvious hazard of the restart path: the process that runs `systemctl restart
// agentd` must not *be* the unit being restarted, or it dies before it can health
// check and roll back. Under `sudo agentd update` it is a separate process, so it
// survives to do both.
package update

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"

	"github.com/cliora/cliora/daemon/internal/metrics"
)

// Stages, matching contracts/v1/schemas/messages/daemon-update-result.schema.json.
// Reported verbatim so an operator's stage in the audit trail is the stage in the
// protocol vocabulary, not a paraphrase.
const (
	StageManifest    = "manifest"
	StageDownload    = "download"
	StageChecksum    = "checksum"
	StageSwap        = "swap"
	StageRestart     = "restart"
	StageHealthcheck = "healthcheck"
)

// Statuses.
const (
	StatusSucceeded  = "succeeded"
	StatusFailed     = "failed"
	StatusRolledBack = "rolled_back"
)

// Error codes (protocol v1.4).
const (
	CodeNotAllowed       = "UPDATE_NOT_ALLOWED"
	CodeDownloadFailed   = "UPDATE_DOWNLOAD_FAILED"
	CodeChecksumMismatch = "UPDATE_CHECKSUM_MISMATCH"
	CodeHealthcheckFail  = "UPDATE_HEALTHCHECK_FAILED"
	CodeRolledBack       = "UPDATE_ROLLED_BACK"
	CodeInProgress       = "UPDATE_IN_PROGRESS"
)

// DaemonUpdateTotal is the daemon-side outcome counter. Labelled by status and
// stage only — both closed vocabularies, so the series count is bounded.
const DaemonUpdateTotal = "daemon_update_total"

// Result is what the caller reports to Central (and prints for an operator).
//
// Status distinguishes the two failure outcomes that matter operationally:
// `rolled_back` means the previous binary is back in place and running, `failed`
// means it is not. Collapsing them would leave an operator unable to tell a
// contained failure from one that needs hands on the box.
type Result struct {
	FromVersion string
	ToVersion   string
	Status      string
	Stage       string
	ErrorCode   string
	// Set when a rollback was attempted but did not restore the previous binary.
	// Not on the wire (the schema is closed); it drives the log line and the
	// operator-facing message, which is where it is actionable.
	RollbackFailed bool
	// Human-readable detail for the operator's terminal and the daemon log. Never
	// sent to Central: a daemon internal string must not reach an API response
	// (ADR 0017).
	Detail string
}

func (r Result) Failed() bool { return r.Status != StatusSucceeded }

// Restarter restarts the agentd unit. Injected so the logic is testable without
// systemd, which is not available in every environment the tests run in.
type Restarter interface {
	// Available reports why this process cannot restart the unit, or nil if it can.
	// Checked before anything is downloaded: an update that cannot be installed
	// should cost nothing.
	Available() error
	Restart(ctx context.Context) error
}

// HealthChecker decides whether the freshly restarted daemon is well. It is
// polled until it returns nil or the budget expires.
type HealthChecker interface {
	Check(ctx context.Context) error
}

// Options carry the injectable collaborators. Note what is absent: no URL, no
// filename, no digest. `BinaryPath` and `StagingRoot` are local installation
// facts, resolved from the running executable and a fixed directory, never from
// an argument that crossed a trust boundary.
type Options struct {
	Fetcher       ManifestFetcher
	Downloader    Downloader
	Restarter     Restarter
	HealthChecker HealthChecker
	Now           func() time.Time
	Sleep         func(context.Context, time.Duration) error
	// Architecture of this node; defaults to runtime.GOARCH.
	Architecture string
	// Absolute path of the installed binary, and where downloads are staged.
	BinaryPath  string
	StagingRoot string
	// How long after the restart the health check may take to pass.
	HealthTimeout time.Duration
	// Interval between health-check attempts.
	HealthInterval time.Duration
	// Reports the version a candidate binary claims, by executing it.
	VersionProbe func(ctx context.Context, path string) (string, error)
}

// Updater owns one node's update flow.
type Updater struct {
	current string
	opts    Options
}

// DefaultStagingRoot is where candidate archives are unpacked. 0700 and outside
// any workspace root, so a staged binary is never reachable through the
// filesystem browse relay.
const DefaultStagingRoot = "/var/lib/agentd/update"

const (
	defaultHealthTimeout  = 30 * time.Second
	defaultHealthInterval = 2 * time.Second
)

// New builds an Updater. `serverBaseURL` is derived from the config file by the
// caller (internal/update/manifest.go turns the ws:// link into its http:// twin);
// `currentVersion` is this binary's own version.
func New(currentVersion string, opts Options) *Updater {
	if opts.Now == nil {
		opts.Now = time.Now
	}
	if opts.Sleep == nil {
		opts.Sleep = sleepCtx
	}
	if opts.Architecture == "" {
		opts.Architecture = runtime.GOARCH
	}
	if opts.StagingRoot == "" {
		opts.StagingRoot = DefaultStagingRoot
	}
	if opts.HealthTimeout == 0 {
		opts.HealthTimeout = defaultHealthTimeout
	}
	if opts.HealthInterval == 0 {
		opts.HealthInterval = defaultHealthInterval
	}
	if opts.VersionProbe == nil {
		opts.VersionProbe = probeVersion
	}
	return &Updater{current: currentVersion, opts: opts}
}

// One update at a time, process-wide. Not a per-Updater lock: two Updaters would
// still be replacing the same file on the same box, so the exclusion has to be as
// wide as the resource.
var (
	running   bool
	runningMu sync.Mutex
)

func acquire() bool {
	runningMu.Lock()
	defer runningMu.Unlock()
	if running {
		return false
	}
	running = true
	return true
}

func release() {
	runningMu.Lock()
	running = false
	runningMu.Unlock()
}

// Update runs the flow to completion and returns what happened.
//
// It returns a Result rather than an error because every outcome is reportable:
// the caller must send a `daemon.update_result` for a refusal just as much as for
// a rollback, and an error return would tempt a caller to drop that.
func (u *Updater) Update(
	ctx context.Context, targetVersion string, allowDowngrade bool, dryRun bool,
) Result {
	if !acquire() {
		// Not a lock wait: a second concurrent update is a caller mistake, and
		// queueing it would mean two swaps of the same file back to back.
		return u.result(targetVersion, StatusFailed, StageManifest, CodeInProgress,
			"another update is already running")
	}
	defer release()

	result := u.run(ctx, targetVersion, allowDowngrade, dryRun)
	metrics.Increment(DaemonUpdateTotal, map[string]string{
		"status": result.Status,
		"stage":  result.Stage,
	})
	return result
}

func (u *Updater) run(
	ctx context.Context, targetVersion string, allowDowngrade bool, dryRun bool,
) Result {
	// --- Stage 1: manifest ---
	// Checked first, before any network or disk work: an update this process cannot
	// install must cost nothing and must say so plainly. Answering NOT_ALLOWED here
	// is what keeps the daemon non-root (SEC-007) instead of acquiring privilege to
	// satisfy a remote request.
	//
	// A dry run continues anyway. Its question is "is this artifact installable?",
	// and refusing on privilege answers a different one — while making the rehearsal
	// harder to perform than the real thing. The privilege verdict is reported in the
	// dry run's own outcome instead, so nothing is hidden.
	privilege := u.opts.Restarter.Available()
	if privilege != nil && !dryRun {
		return u.result(targetVersion, StatusFailed, StageManifest, CodeNotAllowed, privilege.Error())
	}
	if u.opts.BinaryPath == "" {
		return u.result(targetVersion, StatusFailed, StageManifest, CodeNotAllowed,
			"cannot determine the installed binary path")
	}

	manifest, err := u.opts.Fetcher.Fetch(ctx)
	if err != nil {
		// A manifest we cannot read is a transport problem, which is what
		// DOWNLOAD_FAILED means; it is retryable, unlike NOT_ALLOWED.
		return u.result(targetVersion, StatusFailed, StageManifest, CodeDownloadFailed, err.Error())
	}
	artifact, ok := manifest.Find(targetVersion, u.opts.Architecture)
	if !ok {
		// Covers an unknown version, an architecture that was not built, and a
		// release whose digest did not line up on the server. All three mean the
		// same thing here: it is not an allowlisted release.
		return u.result(targetVersion, StatusFailed, StageManifest, CodeNotAllowed,
			fmt.Sprintf("version %s is not an allowlisted release for %s", targetVersion, u.opts.Architecture))
	}
	if targetVersion == u.current {
		// Already there. Reported as success so a fleet-wide "update to X" is
		// idempotent rather than producing failures for the nodes already on X.
		return u.result(targetVersion, StatusSucceeded, StageManifest, "",
			"already running "+targetVersion)
	}
	if !allowDowngrade && CompareVersions(targetVersion, u.current) < 0 {
		return u.result(targetVersion, StatusFailed, StageManifest, CodeNotAllowed,
			fmt.Sprintf("%s is older than the running %s (pass --allow-downgrade to force)",
				targetVersion, u.current))
	}

	// --- Stage 2: download ---
	staging, err := u.stagingDir(targetVersion, dryRun)
	if err != nil {
		return u.result(targetVersion, StatusFailed, StageDownload, CodeDownloadFailed, err.Error())
	}
	// Always cleaned: a leftover archive is both wasted disk and a stale candidate
	// a later run might trust.
	defer func() { _ = os.RemoveAll(staging) }()
	archivePath := filepath.Join(staging, artifact.Filename)
	if err := u.opts.Downloader.Download(ctx, artifact, archivePath); err != nil {
		return u.result(targetVersion, StatusFailed, StageDownload, CodeDownloadFailed, err.Error())
	}

	// --- Stage 3: checksum ---
	digest, err := sha256File(archivePath)
	if err != nil {
		return u.result(targetVersion, StatusFailed, StageChecksum, CodeDownloadFailed, err.Error())
	}
	if digest != artifact.SHA256 {
		// Nothing has been extracted and nothing installed. The digest is never
		// logged in full — a mismatch is the fact, and the value is not useful to
		// an operator reading a log line.
		return u.result(targetVersion, StatusFailed, StageChecksum, CodeChecksumMismatch,
			"downloaded artifact does not match the manifest digest")
	}

	// --- Stage 4: swap (verify first) ---
	candidate := filepath.Join(staging, "agentd")
	if err := extractBinary(archivePath, candidate); err != nil {
		return u.result(targetVersion, StatusFailed, StageSwap, CodeNotAllowed, err.Error())
	}
	reported, err := u.opts.VersionProbe(ctx, candidate)
	if err != nil {
		return u.result(targetVersion, StatusFailed, StageSwap, CodeNotAllowed,
			"staged binary is not executable: "+err.Error())
	}
	if reported != targetVersion {
		// The digest matched, so the artifact is the one the server published — but
		// the server's filename and the binary's own version disagree. Installing it
		// would leave the fleet reporting a version it is not running.
		return u.result(targetVersion, StatusFailed, StageSwap, CodeNotAllowed,
			fmt.Sprintf("staged binary reports %q, expected %q", reported, targetVersion))
	}
	if dryRun {
		// Everything verifiable has been verified; nothing was replaced.
		detail := "dry run: manifest, checksum and version verified; binary not replaced"
		if privilege != nil {
			detail += " (note: " + privilege.Error() + ")"
		}
		return u.result(targetVersion, StatusSucceeded, StageSwap, "", detail)
	}
	backup, err := swapBinary(u.opts.BinaryPath, candidate, u.current)
	if err != nil {
		// The rename either happened or it did not; a failure here means the
		// installed binary is untouched, so there is nothing to roll back.
		return u.result(targetVersion, StatusFailed, StageSwap, CodeNotAllowed, err.Error())
	}

	// --- Stage 5: restart ---
	if err := u.opts.Restarter.Restart(ctx); err != nil {
		return u.rollback(targetVersion, backup, StageRestart, CodeRolledBack, ctx, err.Error())
	}

	// --- Stage 6: health check ---
	if err := u.awaitHealthy(ctx); err != nil {
		return u.rollback(targetVersion, backup, StageHealthcheck, CodeHealthcheckFail, ctx, err.Error())
	}

	slog.Info("daemon updated",
		"from_version", u.current, "to_version", targetVersion, "backup", filepath.Base(backup))
	return u.result(targetVersion, StatusSucceeded, StageHealthcheck, "",
		"updated to "+targetVersion)
}

// stagingDir prepares the private directory a candidate is downloaded into.
//
// A real update always stages under `StagingRoot` (0700, root-owned, outside every
// workspace root): that directory is the one `agentd doctor` checks the permissions
// of, and a candidate binary sitting somewhere world-writable between the checksum
// and the swap is the one gap verify-then-swap cannot close on its own.
//
// A dry run falls back to a private temp directory when that root is not writable.
// Without the fallback a non-root rehearsal cannot run at all — the very thing
// `--dry-run` exists for — since `/var/lib/agentd` needs root to create. `MkdirTemp`
// gives a fresh 0700 directory with an unpredictable name, so the fallback is not a
// path a local user can pre-create and win a race on.
func (u *Updater) stagingDir(targetVersion string, dryRun bool) (string, error) {
	staging := filepath.Join(u.opts.StagingRoot, targetVersion)
	err := os.MkdirAll(staging, 0o700)
	if err == nil {
		return staging, nil
	}
	if !dryRun {
		return "", err
	}
	temp, tempErr := os.MkdirTemp("", "agentd-update-dry-run-")
	if tempErr != nil {
		return "", err
	}
	return temp, nil
}

// awaitHealthy polls until the restarted daemon reports healthy or the budget is
// spent. The deadline is monotonic (time.Since), so a wall-clock step during the
// restart cannot end the window early or extend it indefinitely.
func (u *Updater) awaitHealthy(ctx context.Context) error {
	start := time.Now()
	var last error
	for {
		last = u.opts.HealthChecker.Check(ctx)
		if last == nil {
			return nil
		}
		if time.Since(start) >= u.opts.HealthTimeout {
			return fmt.Errorf("not healthy within %s: %w", u.opts.HealthTimeout, last)
		}
		if err := u.opts.Sleep(ctx, u.opts.HealthInterval); err != nil {
			return fmt.Errorf("health check interrupted: %w", err)
		}
	}
}

// rollback restores the previous binary and restarts it.
//
// The rollback boundary is deliberately narrow (ADR 0017): the binary and the unit,
// nothing else. Config and credentials are not reverted, because a new version may
// legitimately have rewritten them and reverting could leave the old binary with a
// file it cannot parse — a worse state than the one being escaped.
func (u *Updater) rollback(
	target, backup, stage, code string, ctx context.Context, detail string,
) Result {
	restoreErr := restoreBinary(u.opts.BinaryPath, backup)
	if restoreErr == nil {
		restoreErr = u.opts.Restarter.Restart(ctx)
	}
	result := u.result(target, StatusRolledBack, stage, code, detail)
	if restoreErr != nil {
		// The box is now running a binary that failed its health check, and this is
		// the only place that fact is stated. It is a status, not just a log line,
		// because it is the difference between "contained" and "needs hands on it".
		result.Status = StatusFailed
		result.RollbackFailed = true
		result.Detail = detail + "; rollback failed: " + restoreErr.Error()
		slog.Error("daemon update rollback failed",
			"stage", stage, "error", restoreErr.Error())
		return result
	}
	slog.Warn("daemon update rolled back", "stage", stage, "restored_version", u.current)
	return result
}

func (u *Updater) result(target, status, stage, code, detail string) Result {
	return Result{
		FromVersion: u.current,
		ToVersion:   target,
		Status:      status,
		Stage:       stage,
		ErrorCode:   code,
		Detail:      detail,
	}
}

func sleepCtx(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

// ErrNoPrivilege is what a non-root Restarter reports. Exported so the daemon's
// control-frame handler can recognize the "operator must do this" case.
var ErrNoPrivilege = errors.New(
	"replacing the binary and restarting the unit require root; run `sudo agentd update`")
