package runner

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"
)

// The startup self-check is the phase's one hard refusal on the daemon side, and the
// case that matters most is the near-miss: two directories that share a *string*
// prefix and are unrelated. A prefix comparison would refuse `/srv/agentd-runs`
// because `/srv/agentd` is an allowed root, and — far worse in the other direction —
// would accept a real overlap spelled with a trailing slash.
func TestCheckIsolationRefusesOverlapInBothDirections(t *testing.T) {
	cases := []struct {
		name     string
		workDir  string
		roots    []string
		wantFail bool
	}{
		{"run root inside an allowed root", "/home/n/projects/.cliora/runs", []string{"/home/n/projects"}, true},
		{"allowed root inside the run root", "/var/lib/agentd", []string{"/var/lib/agentd/.cliora/runs"}, true},
		{"identical", "/var/lib/agentd/runs", []string{"/var/lib/agentd/runs"}, true},
		{"trailing slash still overlaps", "/var/lib/agentd/runs/", []string{"/var/lib/agentd/runs"}, true},
		{"shared string prefix, unrelated trees", "/srv/agentd-runs", []string{"/srv/agentd"}, false},
		{"disjoint", "/var/lib/agentd/.cliora/runs", []string{"/home/n/projects"}, false},
		{"no allowed roots at all", "/var/lib/agentd/.cliora/runs", nil, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := CheckIsolation(tc.workDir, tc.roots)
			if tc.wantFail && err == nil {
				t.Fatalf("expected a refusal for %s vs %v", tc.workDir, tc.roots)
			}
			if !tc.wantFail && err != nil {
				t.Fatalf("unexpected refusal: %v", err)
			}
		})
	}
}

// The message has to name the offending root. "Your configuration is wrong" without
// saying which line is a message nobody can act on.
func TestCheckIsolationNamesTheOffendingRoot(t *testing.T) {
	err := CheckIsolation("/home/n/projects/runs", []string{"/tmp/other", "/home/n/projects"})
	if err == nil {
		t.Fatal("expected a refusal")
	}
	// `strings.Contains`, not this package's `contains` — that one answers a question
	// about paths, and calling it here would silently test the wrong thing.
	if got := err.Error(); !strings.Contains(got, "/home/n/projects") {
		t.Fatalf("error does not name the root: %s", got)
	}
}

func TestCheckIsolationRefusesRelativeWorkDir(t *testing.T) {
	if err := CheckIsolation("runs", nil); err == nil {
		t.Fatal("a relative run root must be refused: it would depend on the working directory")
	}
}

// `repo/` and `.cliora/` are **siblings**. If they were parent and child, the context
// pack would live inside the clone, appear in `git status`, and need a gitignore to
// protect it.
func TestCreateMakesTheContextPackASiblingOfTheCheckout(t *testing.T) {
	work := t.TempDir()
	runID := "9f3c1a20-4e7b-4c11-9a55-0123456789ab"
	layout, err := Create(work, runID)
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if filepath.Dir(layout.Cliora) != layout.Root || filepath.Dir(layout.Repo) != layout.Root {
		t.Fatalf("expected siblings under %s, got %s and %s", layout.Root, layout.Repo, layout.Cliora)
	}
	for _, dir := range []string{layout.Root, layout.Repo, layout.Cliora, layout.Artifacts} {
		info, statErr := os.Stat(dir)
		if statErr != nil {
			t.Fatalf("missing %s: %v", dir, statErr)
		}
		if perm := info.Mode().Perm(); perm != 0o700 {
			t.Fatalf("%s is %o, want 0700", dir, perm)
		}
	}
}

// The run id becomes a path segment, so it is validated rather than trusted — "the
// other end is ours" is exactly the assumption that stops being true the day
// something else speaks this protocol.
func TestCreateRefusesARunIdThatIsNotAUuid(t *testing.T) {
	work := t.TempDir()
	for _, bad := range []string{"../escape", "9f3c1a20", "9f3c1a20-4e7b-4c11-9a55-0123456789AB", ""} {
		if _, err := Create(work, bad); err == nil {
			t.Fatalf("accepted %q as a run id", bad)
		}
	}
}

// Retention is asymmetric on purpose: a failed run's directory is the one somebody
// comes back to look at.
func TestReclaimKeepsAFailedRunLongerThanASuccessfulOne(t *testing.T) {
	work := t.TempDir()
	cfg := config.RunnerConfig{RetentionSuccessDays: 3, RetentionFailedDays: 14}
	now := time.Now()

	ok := mustCreate(t, work, "00000000-0000-4000-8000-00000000000a")
	bad := mustCreate(t, work, "00000000-0000-4000-8000-00000000000b")
	if err := MarkFinished(ok, "succeeded", now.Add(-5*24*time.Hour)); err != nil {
		t.Fatal(err)
	}
	if err := MarkFinished(bad, "failed", now.Add(-5*24*time.Hour)); err != nil {
		t.Fatal(err)
	}

	removed, err := Reclaim(work, cfg, now)
	if err != nil {
		t.Fatalf("reclaim: %v", err)
	}
	if removed != 1 {
		t.Fatalf("removed %d directories, want 1", removed)
	}
	if _, statErr := os.Stat(ok.Root); !os.IsNotExist(statErr) {
		t.Fatal("the successful run's directory outlived its three days")
	}
	if _, statErr := os.Stat(bad.Root); statErr != nil {
		t.Fatal("the failed run's directory was reclaimed early; that is the one worth keeping")
	}
}

// A directory with no outcome marker is either still running or the remains of a
// daemon that died mid-run. Deleting it would be deleting the evidence of exactly the
// failure worth investigating.
func TestReclaimLeavesUnfinishedRunsAlone(t *testing.T) {
	work := t.TempDir()
	layout := mustCreate(t, work, "00000000-0000-4000-8000-00000000000c")
	removed, err := Reclaim(work, config.RunnerConfig{RetentionSuccessDays: 1, RetentionFailedDays: 1},
		time.Now().Add(365*24*time.Hour))
	if err != nil {
		t.Fatalf("reclaim: %v", err)
	}
	if removed != 0 {
		t.Fatal("an unfinished run directory was reclaimed")
	}
	if _, statErr := os.Stat(layout.Root); statErr != nil {
		t.Fatal("an unfinished run directory was removed")
	}
}

// `dedicated` is the one condition of "dedicated runner node" a machine can check
// about itself, and it is **reported, never enforced**: a mixed-use dev VM is the
// common case, and refusing to run there would break it to guard a risk its owner
// accepted.
func TestDedicatedIsTrueOnlyWithNoAllowedRoots(t *testing.T) {
	empty := &config.Config{}
	if !Dedicated(empty) {
		t.Fatal("a node with no allowed roots is dedicated")
	}
	mixed := &config.Config{}
	mixed.Workspace.AllowedRoots = []string{"/home/n/projects"}
	if Dedicated(mixed) {
		t.Fatal("a node that also serves sessions is not dedicated")
	}
}

func TestDirSizeCountsFileBytes(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "a"), make([]byte, 1024), 0o600); err != nil {
		t.Fatal(err)
	}
	nested := filepath.Join(dir, "n")
	if err := os.MkdirAll(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(nested, "b"), make([]byte, 2048), 0o600); err != nil {
		t.Fatal(err)
	}
	size, err := DirSize(dir)
	if err != nil {
		t.Fatalf("dir size: %v", err)
	}
	if size != 3072 {
		t.Fatalf("size %d, want 3072", size)
	}
}

func mustCreate(t *testing.T, work, runID string) Layout {
	t.Helper()
	layout, err := Create(work, runID)
	if err != nil {
		t.Fatalf("create %s: %v", runID, err)
	}
	return layout
}
