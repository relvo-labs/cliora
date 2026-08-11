package runner

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/cliora/cliora/daemon/internal/config"
)

// Exit condition 21's node half.
//
// The whole reason this exists is that a runner with no capacity says so by **not
// polling** — there is no "capacity: 0" frame. From Central, a full runner, a runner
// with nowhere to put a checkout and a machine somebody unplugged are the same silence,
// and only this process can tell them apart. So the heartbeat carries the reason, and
// these assert the two ways that could quietly stop being true: the wrong reason, or a
// disk figure that was never measured being reported as 0.

func newRunner(t *testing.T, cfg config.RunnerConfig) *Runner {
	t.Helper()
	runner := New(cfg, "dev-vm-01")
	return runner
}

func TestPressureNamesTheReasonRatherThanGoingQuiet(t *testing.T) {
	dir := t.TempDir()
	cfg := config.RunnerConfig{
		WorkDir:         dir,
		MaxConcurrent:   1,
		MaxWaiting:      5,
		TotalQuotaBytes: 8 << 30,
	}
	runner := newRunner(t, cfg)

	// Nothing running: no reason at all, and the disk figures still reported. Somebody
	// watching a node fill up should see it coming rather than learn about it when the
	// work stops.
	pressure := runner.Pressure()
	if _, present := pressure["blocked_reason"]; present {
		t.Fatalf("an idle runner reported a reason: %v", pressure)
	}
	if _, present := pressure["disk_used_bytes"]; !present {
		t.Fatal("disk usage is not reported until something is wrong, so nobody sees it coming")
	}
	if pressure["disk_quota_bytes"] != int64(8<<30) {
		t.Fatalf("quota = %v", pressure["disk_quota_bytes"])
	}

	// At concurrency. This must not read as "disk" — the two have different fixes.
	runner.mu.Lock()
	runner.active["run-1"] = &Execution{}
	runner.mu.Unlock()
	if got := runner.Pressure()["blocked_reason"]; got != "at_capacity" {
		t.Fatalf("blocked_reason = %v, want at_capacity", got)
	}

	// Parked runs hold no process, so they are a *separate* limit and a separate
	// sentence: the fix is answering a question, not adding a machine.
	runner.mu.Lock()
	delete(runner.active, "run-1")
	runner.waiting = 5
	runner.mu.Unlock()
	if got := runner.Pressure()["blocked_reason"]; got != "waiting_limit" {
		t.Fatalf("blocked_reason = %v, want waiting_limit", got)
	}
}

func TestPressureReportsTheQuotaItIsAbout(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "blob"), make([]byte, 4096), 0o600); err != nil {
		t.Fatal(err)
	}
	// A quota already exceeded by what is on disk.
	runner := newRunner(t, config.RunnerConfig{
		WorkDir:         dir,
		MaxConcurrent:   2,
		MaxWaiting:      5,
		TotalQuotaBytes: 1024,
	})

	pressure := runner.Pressure()
	if got := pressure["blocked_reason"]; got != "disk_quota" {
		t.Fatalf("blocked_reason = %v, want disk_quota", got)
	}
	// **Both** numbers, because the console shows「磁碟用盡（4.8 / 5.0 GB）」and a used
	// figure with no quota beside it does not say whether it is a lot.
	used, ok := pressure["disk_used_bytes"].(int64)
	if !ok || used < 4096 {
		t.Fatalf("disk_used_bytes = %v", pressure["disk_used_bytes"])
	}
	if pressure["disk_quota_bytes"] != int64(1024) {
		t.Fatalf("disk_quota_bytes = %v", pressure["disk_quota_bytes"])
	}
}

func TestPressureOmitsAMeasurementItCouldNotTake(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root can read an unreadable directory, so there is no failure to observe")
	}
	// A run root the daemon cannot walk — a wrong owner after a StateDirectory change is
	// the realistic way this happens. Reporting 0 bytes used would render as an empty
	// disk with plenty of room, which is the opposite of "we do not know", and the
	// person reading the page would rule out disk as the cause.
	dir := filepath.Join(t.TempDir(), "unreadable")
	if err := os.Mkdir(dir, 0o000); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(dir, 0o700) })

	runner := newRunner(t, config.RunnerConfig{
		WorkDir:         dir,
		MaxConcurrent:   1,
		MaxWaiting:      5,
		TotalQuotaBytes: 8 << 30,
	})
	if _, present := runner.Pressure()["disk_used_bytes"]; present {
		t.Fatal("a failed measurement was reported as a number")
	}
	// The quota is still reported: it is configuration, not a measurement, and it is
	// what makes the missing figure legible as "of 8 GB, unknown".
	if runner.Pressure()["disk_quota_bytes"] != int64(8<<30) {
		t.Fatal("the quota went missing with the measurement")
	}
}
