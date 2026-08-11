// Package runner owns the daemon's side of an agent run: the isolated directory it
// happens in, the git fetch that fills it, and the bounded, reclaimed disk it uses.
//
// Two trees exist on a node that serves both purposes, and **nothing joins them**:
//
//	/var/lib/agentd/.cliora/runs/<run_id>/   the agent's ground (this package)
//	  repo/            the checkout; the child process's cwd
//	  .cliora/         the context pack and the run token, siblings of the checkout
//	  artifacts/       what the run produced
//	/home/<user>/projects/<repo>/            an interactive session's ground
//
// `repo/` and `.cliora/` are siblings rather than parent and child on purpose: the
// context pack is then not inside the clone, so it cannot appear in `git status`,
// cannot be committed by accident, and needs no gitignore to protect it. The `cliora`
// CLI finds it with no code change, because it already searches upward from the cwd.
//
// **What this package does not claim.** It does not prevent the run's child process
// from reading an allowed root. Nothing implements that: the child runs as the same
// OS user as agentd, the allowed roots must be readable by that user or interactive
// sessions cannot start, and the unit deliberately does not hide the home directory.
// What is real and enforced here is the *other* direction plus one refusal:
//
//  1. the run root may not overlap any allowed root, checked at startup, and the
//     daemon **refuses to start** rather than warning (ADR 0031 §3.6);
//  2. the existing file APIs cannot reach the run directory, because it is outside
//     every allowed root;
//  3. the platform writes nothing into an allowed root on a run's behalf.
//
// The rest is carried by deployment posture, and `Dedicated` is how that posture
// becomes a visible cell in the console rather than a sentence in a runbook.
package runner

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

// Layout names the four paths inside one run directory. A struct rather than four
// string concatenations at the call sites, so "where does the context pack go" has
// exactly one answer.
type Layout struct {
	Root      string
	Repo      string
	Cliora    string
	Artifacts string
}

// NewLayout composes the paths for a run. It does not touch the filesystem.
func NewLayout(workDir, runID string) Layout {
	root := filepath.Join(workDir, runID)
	return Layout{
		Root:      root,
		Repo:      filepath.Join(root, "repo"),
		Cliora:    filepath.Join(root, ".cliora"),
		Artifacts: filepath.Join(root, "artifacts"),
	}
}

// Overlaps reports whether two directory paths intersect in either direction.
//
// `filepath.Rel` rather than a string prefix, for the reason `authorize_workspace`
// already documents on the Central side: `/a/projects` and `/a/projects-other` share
// a prefix and are unrelated directories. The two implementations are deliberately
// **not** shared — that one answers "may this user use this path", this one answers
// "do these two trees intersect", and merging them would give one function two
// meanings.
func Overlaps(a, b string) bool {
	a = filepath.Clean(a)
	b = filepath.Clean(b)
	return contains(a, b) || contains(b, a)
}

func contains(parent, child string) bool {
	if parent == child {
		return true
	}
	rel, err := filepath.Rel(parent, child)
	if err != nil {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

// ErrRunRootInsideAllowedRoot is returned by CheckIsolation and is fatal at startup.
var ErrRunRootInsideAllowedRoot = errors.New("run root overlaps an allowed root")

// CheckIsolation is the startup self-check, and it **refuses** rather than warning.
//
// The failure it prevents is not a small one: with the run root inside an allowed
// root, the agent's intermediate files appear in the user's file browser and the
// user's `filesystem.store` can write into a live run's directory — red lines 2 and 3
// bypassed at once, by a single line of configuration. A daemon that logged a warning
// and started anyway would leave that true on a machine for months.
//
// The error names the offending root, because "your configuration is wrong" without
// saying which line is a message nobody can act on.
func CheckIsolation(workDir string, allowedRoots []string) error {
	if workDir == "" {
		return errors.New("runner.work_dir is empty")
	}
	if !filepath.IsAbs(workDir) {
		return fmt.Errorf("runner.work_dir must be absolute: %s", workDir)
	}
	for _, root := range allowedRoots {
		if root == "" {
			continue
		}
		if Overlaps(workDir, root) {
			return fmt.Errorf(
				"%w: runner.work_dir %s overlaps workspace.allowed_roots entry %s — "+
					"move the run root outside every allowed root, or remove that root",
				ErrRunRootInsideAllowedRoot, workDir, root,
			)
		}
	}
	return nil
}

// Dedicated reports the one condition of "dedicated runner node" that a machine can
// check about itself: it declares no allowed root, so there is no second tree for an
// agent to read.
//
// **Reported, never enforced.** A mixed-use node is a legitimate and common setup —
// one person, one dev VM, both uses, informed consent — and refusing to run there
// would break the most common case to protect against a risk the operator accepted.
// This follows ADR 0023 D3's rule exactly: report the machine's actual posture, never
// the one you wish it had.
func Dedicated(cfg *config.Config) bool {
	return len(cfg.Workspace.AllowedRoots) == 0
}

// Create makes one run's directory tree, 0700 throughout.
//
// The run id is validated rather than trusted even though it comes from Central: it
// becomes a path segment, and "the other end is ours" is exactly the assumption that
// stops being true the day something else speaks this protocol.
func Create(workDir, runID string) (Layout, error) {
	if !validRunID(runID) {
		return Layout{}, fmt.Errorf("invalid run id: %q", runID)
	}
	layout := NewLayout(workDir, runID)
	for _, dir := range []string{layout.Root, layout.Repo, layout.Cliora, layout.Artifacts} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return Layout{}, fmt.Errorf("create run directory: %w", err)
		}
	}
	return layout, nil
}

// validRunID accepts a canonical lowercase UUID and nothing else — no separators, no
// dots, so a traversal segment is unrepresentable rather than filtered.
func validRunID(value string) bool {
	if len(value) != 36 {
		return false
	}
	for i, r := range value {
		switch i {
		case 8, 13, 18, 23:
			if r != '-' {
				return false
			}
		default:
			if !((r >= '0' && r <= '9') || (r >= 'a' && r <= 'f')) {
				return false
			}
		}
	}
	return true
}

// DirSize walks a directory and returns its apparent size.
//
// Apparent size rather than blocks used: the quota exists to answer "is this run
// about to fill the disk", and the number that gets reported to Central is compared
// against a configured byte figure, not against the filesystem's allocation policy.
func DirSize(path string) (int64, error) {
	var total int64
	err := filepath.WalkDir(path, func(_ string, entry os.DirEntry, err error) error {
		if err != nil {
			// A file that vanished mid-walk is normal here: the run is still writing.
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		if entry.IsDir() {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}
		total += info.Size()
		return nil
	})
	return total, err
}

// Reclaim deletes finished run directories past their retention.
//
// Retention depends on the outcome, and the asymmetry is the point: a **failed** run's
// directory is the one somebody comes back to look at, so it is kept far longer than a
// successful one's. The outcome is recorded as a marker file inside the directory
// rather than held in memory, because the daemon restarts and the directory does not.
func Reclaim(workDir string, cfg config.RunnerConfig, now time.Time) (removed int, err error) {
	entries, readErr := os.ReadDir(workDir)
	if readErr != nil {
		if os.IsNotExist(readErr) {
			return 0, nil
		}
		return 0, readErr
	}
	for _, entry := range entries {
		if !entry.IsDir() || !validRunID(entry.Name()) {
			continue
		}
		dir := filepath.Join(workDir, entry.Name())
		outcome, finishedAt, ok := readOutcome(dir)
		if !ok {
			// Still running, or a directory whose marker was never written because the
			// daemon died mid-run. Left alone deliberately: deleting it would be
			// deleting evidence of exactly the failure worth investigating.
			continue
		}
		days := cfg.RetentionSuccessDays
		if outcome != "succeeded" {
			days = cfg.RetentionFailedDays
		}
		if now.Sub(finishedAt) < time.Duration(days)*24*time.Hour {
			continue
		}
		if rmErr := os.RemoveAll(dir); rmErr != nil {
			err = errors.Join(err, rmErr)
			continue
		}
		removed++
	}
	return removed, err
}

const outcomeFile = ".cliora/outcome"

// MarkFinished records how a run ended, so retention can be decided after a restart.
func MarkFinished(layout Layout, outcome string, at time.Time) error {
	line := fmt.Sprintf("%s %s\n", outcome, at.UTC().Format(time.RFC3339))
	return os.WriteFile(filepath.Join(layout.Root, outcomeFile), []byte(line), 0o600)
}

func readOutcome(dir string) (outcome string, at time.Time, ok bool) {
	data, err := os.ReadFile(filepath.Join(dir, outcomeFile))
	if err != nil {
		return "", time.Time{}, false
	}
	fields := strings.Fields(string(data))
	if len(fields) != 2 {
		return "", time.Time{}, false
	}
	parsed, err := time.Parse(time.RFC3339, fields[1])
	if err != nil {
		return "", time.Time{}, false
	}
	return fields[0], parsed, true
}
