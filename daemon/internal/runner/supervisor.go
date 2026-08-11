package runner

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
	"github.com/cliora/cliora/daemon/internal/gitfetch"
)

// The runner loop: poll for work, fetch the code, run the agent, report.
//
// Everything here is **pull-side**. Nothing pushes work at this node, and this file
// contains no path that accepts one — a run arrives only as the answer to a poll this
// daemon sent, and the platform has already claimed it by then, so `run.offer` means
// "this is yours and the lease has started" (ADR 0029 §2).
//
// Capacity is expressed by **not polling**. A runner at `max_concurrent` simply stops
// asking, which is why there is no "capacity: 0" frame and no scheduler on the
// platform. Disk works the same way: over the node's total quota, the loop stops
// polling and says so on the heartbeat rather than pretending the machine is offline —
// "out of disk" and "machine is gone" are different facts and a person reacts to them
// differently.

// Transport is the daemon's link to Central, as this package needs it. An interface so
// the supervisor can be tested without a WebSocket, and deliberately one-way: there is
// no `Request` method, because nothing here may wait for Central to answer.
type Transport interface {
	Send(messageType string, payload any) error
}

// Runner drives one node's share of the queue.
type Runner struct {
	Cfg     config.RunnerConfig
	Node    string
	Fetch   gitfetch.Fetcher
	Build   func(runtime string, opts BuildOptions) (Started, error)
	Send    Transport
	Now     func() time.Time
	Runtime []string

	mu     sync.Mutex
	active map[string]*Execution
	// waiting counts runs parked on a human's reply. They hold no process, so they do
	// not occupy execution capacity — but they are not free either, or one card could
	// park a node indefinitely.
	waiting int
	// blocked records why polling stopped, so the heartbeat can carry a reason
	// instead of the node simply going quiet.
	blocked string
}

// BuildOptions is what the supervisor hands to the runtime layer. It carries no
// command and no argv: composing those is `runtime.BuildRunCommand`'s job, from two
// closed tables.
type BuildOptions struct {
	Dir     string
	Context string
}

// Started is a running child plus its output.
type Started struct {
	Execution *Execution
	Output    interface{ Read([]byte) (int, error) }
}

// New prepares a runner. It does **not** start polling: `CheckIsolation` has to pass
// first, and that is the caller's decision to make loudly at startup.
func New(cfg config.RunnerConfig, node string) *Runner {
	return &Runner{
		Cfg:    cfg,
		Node:   node,
		active: map[string]*Execution{},
		Now:    time.Now,
	}
}

// Capacity is how many runs this node will take right now, and 0 means "do not poll".
//
// Three separate reasons produce 0, and they are kept apart because they need
// different words on the Agents page: at concurrency, too many parked runs, or out of
// disk.
func (r *Runner) Capacity() (int, string) {
	r.mu.Lock()
	active := len(r.active)
	waiting := r.waiting
	r.mu.Unlock()

	if active >= r.Cfg.MaxConcurrent {
		return 0, "at_capacity"
	}
	if waiting >= r.Cfg.MaxWaiting {
		return 0, "waiting_limit"
	}
	if reason := r.diskPressure(); reason != "" {
		return 0, reason
	}
	free := r.Cfg.MaxConcurrent - active
	if free > 16 {
		free = 16
	}
	return free, ""
}

// diskPressure applies the node-wide quota and the free-space floor.
//
// The floor deliberately reuses image drop's default: the agent's clones and the
// user's uploads compete for one disk, and two different floors would let one starve
// the other.
func (r *Runner) diskPressure() string {
	used, err := DirSize(r.Cfg.WorkDir)
	if err == nil && used >= r.Cfg.TotalQuotaBytes {
		return "disk_quota"
	}
	floor := r.Cfg.MinFree()
	if floor <= 0 {
		return ""
	}
	if free, statErr := freeBytes(r.Cfg.WorkDir); statErr == nil && free < floor {
		return "disk_low"
	}
	return ""
}

// BlockedReason is what the heartbeat reports when the loop has stopped polling.
func (r *Runner) BlockedReason() string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.blocked
}

// Poll sends one `runner.poll` when there is capacity, and records why when there is
// not. Called on a ticker by the connection.
func (r *Runner) Poll(runnerID string) error {
	capacity, blocked := r.Capacity()
	r.mu.Lock()
	r.blocked = blocked
	r.mu.Unlock()
	if capacity <= 0 {
		return nil
	}
	return r.Send.Send("runner.poll", map[string]any{
		"runner_id": runnerID,
		"capacity":  capacity,
	})
}

// Prepare creates a run's directory and fetches its code.
//
// It reports `RUN_SOURCE_UNAVAILABLE` with a cause the caller can pass on, because
// supplying a credential, allowing a host and correcting a branch are three different
// actions for a person. **The message never echoes the URL**: somebody may have pasted
// a credential into it, and this string ends up in an API response.
func (r *Runner) Prepare(ctx context.Context, runID string, source Source) (Layout, string, error) {
	layout, err := Create(r.Cfg.WorkDir, runID)
	if err != nil {
		return Layout{}, "", err
	}
	if source.Kind == "none" {
		// No checkout at all. The agent has no code, and that is the card's choice
		// rather than a failure.
		return layout, "", nil
	}
	commit, err := r.Fetch.Clone(ctx, source.URL, source.Ref, layout.Repo)
	if err != nil {
		return layout, "", classifySource(err)
	}
	if err := r.Fetch.SetRunIdentity(ctx, layout.Repo, r.Node); err != nil {
		// Not fatal: the run can still do its work, and the identity only matters if
		// the agent commits. Reported rather than raised.
		return layout, commit, nil
	}
	return layout, commit, nil
}

// Source is the fetch half of a run's spec.
type Source struct {
	Kind string
	URL  string
	Ref  string
}

func classifySource(err error) error {
	switch {
	case errors.Is(err, gitfetch.ErrCredentials):
		return fmt.Errorf("RUN_SOURCE_UNAVAILABLE: no usable credential on this node")
	case errors.Is(err, gitfetch.ErrHostNotAllowed):
		return fmt.Errorf("RUN_SOURCE_UNAVAILABLE: this node does not allow that host")
	case errors.Is(err, gitfetch.ErrRefNotFound):
		return fmt.Errorf("RUN_SOURCE_UNAVAILABLE: that branch does not exist")
	case errors.Is(err, gitfetch.ErrInvalidArgument):
		return fmt.Errorf("RUN_SOURCE_UNAVAILABLE: the repository is not usable from here")
	default:
		return fmt.Errorf("RUN_SOURCE_UNAVAILABLE: the fetch failed")
	}
}

// WriteContext puts the task context and the run credential into the run's own
// `.cliora/`, **directly**.
//
// Not through `VerbProject`, not through any protocol round trip, and not through
// `internal/files` — that package is off limits for this phase. The destination is the
// daemon's own directory, so the write path that exists for *the user's* workspace has
// nothing to do here (plan/18/00-…md, success criterion 6).
func WriteContext(layout Layout, context, token string) error {
	dir := filepath.Join(layout.Cliora, "context")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "task.md"), []byte(context), 0o600); err != nil {
		return err
	}
	if token == "" {
		return nil
	}
	// 0600, and deleted the moment the run ends rather than at the retention
	// deadline: a credential's lifetime is the run, not the directory.
	return os.WriteFile(filepath.Join(dir, "run.token"), []byte(token), 0o600)
}

// DropToken removes the run credential. Called at the end of every run, including the
// failed ones — the directory survives for 14 days and the token must not.
func DropToken(layout Layout) error {
	err := os.Remove(filepath.Join(layout.Cliora, "context", "run.token"))
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// Summary is what a finished run reports about its own working tree.
//
// The last two fields are what **replaced blocking the agent from pushing**. The
// second ruling of 2026-08-10 made that freedom deliberate, and these two lines —
// costing nothing and assuming nothing — make "did this run touch a remote" a visible
// fact on the Run detail page instead of a guess.
type Summary struct {
	DiskBytes       int64
	Dirty           bool
	UntrackedFiles  int
	Remotes         []string
	UnpushedCommits int
	Diff            string
}

// Inspect gathers the end-of-run facts.
func (r *Runner) Inspect(ctx context.Context, layout Layout, hasRepo bool) Summary {
	summary := Summary{}
	if size, err := DirSize(layout.Root); err == nil {
		summary.DiskBytes = size
	}
	if !hasRepo {
		return summary
	}
	if status, err := r.Fetch.Status(ctx, layout.Repo); err == nil {
		for _, line := range strings.Split(strings.TrimSpace(status), "\n") {
			if line == "" {
				continue
			}
			summary.Dirty = true
			if strings.HasPrefix(strings.TrimSpace(line), "??") {
				summary.UntrackedFiles++
			}
		}
	}
	if remotes, err := r.Fetch.Remotes(ctx, layout.Repo); err == nil {
		summary.Remotes = remotes
	}
	if count, err := r.Fetch.UnpushedCommits(ctx, layout.Repo); err == nil {
		summary.UnpushedCommits = count
	}
	if summary.Dirty {
		if diff, err := r.Fetch.Diff(ctx, layout.Repo); err == nil {
			summary.Diff = diff
		}
	}
	return summary
}

// ShouldAttachDiff reports whether the honesty rule applies (ADR 0031 §7).
//
// A run that declared no delivery and changed files anyway would otherwise lose that
// work when the directory is reclaimed — **and nobody would know it had existed**. The
// second ruling narrows where this bites without removing it: an agent that pushed a
// branch has not lost its work, an agent that did not still will, and the platform
// cannot tell them apart. So the rule is unconditional on `dirty`.
func ShouldAttachDiff(delivery string, summary Summary) bool {
	if delivery != "none" && delivery != "artifact" {
		return false
	}
	return summary.Dirty && summary.Diff != ""
}

// SummaryText is the human sentence that goes on the run.
//
// It says the awkward thing out loud when it applies: the card declared no delivery
// and files changed anyway. It also reports the untracked count without packaging
// those files — one `node_modules/` would blow the artifact quota, so the person
// decides.
func SummaryText(delivery string, summary Summary) string {
	var parts []string
	if summary.Dirty && delivery == "none" {
		parts = append(parts, "本卡宣告不交付，但工作目錄有變更；diff 已附為產物。")
	}
	if summary.UntrackedFiles > 0 {
		parts = append(parts,
			fmt.Sprintf("另有 %d 個未追蹤的新檔案未附加。", summary.UntrackedFiles))
	}
	if len(summary.Remotes) > 0 {
		parts = append(parts, fmt.Sprintf("遠端 %d 條，未推送的 commit %d 個。",
			len(summary.Remotes), summary.UnpushedCommits))
	}
	return strings.Join(parts, " ")
}

// Track and Untrack maintain the occupancy counters the capacity check reads.
func (r *Runner) Track(runID string, execution *Execution) {
	r.mu.Lock()
	r.active[runID] = execution
	r.mu.Unlock()
}

func (r *Runner) Untrack(runID string) {
	r.mu.Lock()
	delete(r.active, runID)
	r.mu.Unlock()
}

// SetWaiting moves a run between the two counters.
func (r *Runner) SetWaiting(runID string, waiting bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if waiting {
		r.waiting++
		delete(r.active, runID)
		return
	}
	if r.waiting > 0 {
		r.waiting--
	}
}

// CancelRun stops one run's whole process group, or reports that it is unknown here.
func (r *Runner) CancelRun(runID, reason string) error {
	r.mu.Lock()
	execution := r.active[runID]
	r.mu.Unlock()
	if execution == nil {
		return errors.New("RUN_NOT_FOUND")
	}
	return execution.Cancel(reason)
}

// EnforceRunQuota checks one run's directory against the per-run allowance.
func (r *Runner) EnforceRunQuota(layout Layout) error {
	used, err := DirSize(layout.Root)
	if err != nil {
		return nil
	}
	if used >= r.Cfg.RunQuotaBytes {
		return gitfetch.Quota{Name: "runner.run_quota_bytes", Limit: r.Cfg.RunQuotaBytes}.
			Exceeded(used)
	}
	return nil
}
