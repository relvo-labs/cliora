package files

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/cliora/cliora/daemon/internal/workspace"
)

// P3-10 latency measurement for the daemon legs of the two P3 NFRs:
// directory listing < 2 s and ≤2 MB preview < 3 s (ADR 0015). This measures the
// real confined implementation (os.Root handle → policy → bounded read) against
// generated fixtures; the Central relay leg is measured separately by
// backend/perf/files_bench.py, and docs/p3-report.md sums the two.
//
// Set CLIORA_PERF_OUT (an *absolute* path — `go test` runs in the package
// directory) to write a JSON artifact:
//
//	CLIORA_PERF_OUT=$PWD/../artifacts/p3/local/fs-latency.json \
//	  go test ./internal/files -run TestFilesystemLatencyBudget -v

// Budgets, in milliseconds, for the daemon leg alone. They are deliberately a
// fraction of the end-to-end NFR so the relay leg has room; a breach here is a
// hard failure because the daemon is the expensive part.
const (
	listBudgetMs   = 1500 // of the 2 s directory-list NFR
	readBudgetMs   = 2500 // of the 3 s ≤2 MB preview NFR
	searchBudgetMs = 12000
)

type perfCase struct {
	Name       string  `json:"name"`
	Iterations int     `json:"iterations"`
	P50Ms      float64 `json:"p50_ms"`
	P95Ms      float64 `json:"p95_ms"`
	MaxMs      float64 `json:"max_ms"`
	BudgetMs   float64 `json:"budget_ms"`
	Detail     string  `json:"detail"`
	OK         bool    `json:"ok"`
}

func measure(name, detail string, budgetMs float64, iterations int, fn func()) perfCase {
	samples := make([]float64, 0, iterations)
	for i := 0; i < iterations; i++ {
		start := time.Now()
		fn()
		samples = append(samples, float64(time.Since(start).Microseconds())/1000)
	}
	sort.Float64s(samples)
	pick := func(q float64) float64 {
		idx := int(q * float64(len(samples)-1))
		return samples[idx]
	}
	c := perfCase{
		Name:       name,
		Iterations: iterations,
		P50Ms:      pick(0.5),
		P95Ms:      pick(0.95),
		MaxMs:      samples[len(samples)-1],
		BudgetMs:   budgetMs,
		Detail:     detail,
	}
	c.OK = c.P95Ms < budgetMs
	return c
}

// perfWorkspace builds a representative workspace: a wide directory, a deep
// tree, an excluded directory, and a file just under the 2 MiB preview cap.
func perfWorkspace(t *testing.T, wide, depth int) (root, ws string) {
	t.Helper()
	base := t.TempDir()
	root = filepath.Join(base, "projects")
	ws = filepath.Join(root, "app")
	wideDir := filepath.Join(ws, "wide")
	if err := os.MkdirAll(wideDir, 0o755); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < wide; i++ {
		name := filepath.Join(wideDir, fmt.Sprintf("file_%05d.py", i))
		if err := os.WriteFile(name, []byte("x = 1\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	// Deep tree for the search pass, plus an excluded directory that must be
	// skipped rather than walked.
	deep := ws
	for i := 0; i < depth; i++ {
		deep = filepath.Join(deep, fmt.Sprintf("level%02d", i))
		if err := os.MkdirAll(deep, 0o755); err != nil {
			t.Fatal(err)
		}
		for j := 0; j < 20; j++ {
			f := filepath.Join(deep, fmt.Sprintf("mod_%02d.go", j))
			if err := os.WriteFile(f, []byte("package x\n"), 0o644); err != nil {
				t.Fatal(err)
			}
		}
	}
	excluded := filepath.Join(ws, "node_modules", "pkg")
	if err := os.MkdirAll(excluded, 0o755); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2000; i++ {
		f := filepath.Join(excluded, fmt.Sprintf("dep_%05d.js", i))
		if err := os.WriteFile(f, []byte("module.exports=1\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	// 2 MiB minus a margin: the largest previewable file (FR-FILE-003).
	body := strings.Repeat("const answer = 42;\n", (2<<20)/19-16)
	if err := os.WriteFile(filepath.Join(ws, "large.ts"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return root, ws
}

func TestFilesystemLatencyBudget(t *testing.T) {
	root, ws := perfWorkspace(t, 5000, 8)
	svc := testService()
	guard := workspace.New([]string{root})
	open := func() *workspace.Root {
		handle, err := guard.OpenWorkspace(ws)
		if err != nil {
			t.Fatalf("open workspace: %v", err)
		}
		return handle
	}

	cases := []perfCase{}

	// 1. Directory listing of a 5000-entry directory (paged at the 2000 cap).
	cases = append(cases, measure(
		"list_wide_directory", "5000 entries, entry_limit 2000", listBudgetMs, 20, func() {
			handle := open()
			defer handle.Close()
			res, err := svc.List(handle, "wide", "", 0)
			if err != nil {
				t.Fatalf("list: %v", err)
			}
			if len(res.Entries) != DefaultEntryLimit || !res.Truncated {
				t.Fatalf("unexpected page: %d entries truncated=%v", len(res.Entries), res.Truncated)
			}
		}))

	// 2. Preview of a file just under the 2 MiB cap, through the full policy.
	cases = append(cases, measure(
		"read_2mib_preview", "~2 MiB text file, sensitive+binary policy applied",
		readBudgetMs, 20, func() {
			handle := open()
			defer handle.Close()
			res, err := svc.Read(handle, "large.ts")
			if err != nil {
				t.Fatalf("read: %v", err)
			}
			if res.Denied || len(res.Content) == 0 {
				t.Fatalf("expected a previewable file, got denied=%v", res.Denied)
			}
		}))

	// 3. Bounded filename search across the deep tree (excluded dirs skipped).
	cases = append(cases, measure(
		"search_deep_tree", "8 levels x 20 files + 2000-file excluded dir skipped",
		searchBudgetMs, 5, func() {
			handle := open()
			defer handle.Close()
			res, err := svc.Search(context.Background(), handle, "mod_0", "", 0)
			if err != nil {
				t.Fatalf("search: %v", err)
			}
			if len(res.Results) == 0 {
				t.Fatal("search found nothing")
			}
			for _, r := range res.Results {
				if strings.Contains(r.RelPath, "node_modules") {
					t.Fatalf("search descended into an excluded directory: %s", r.RelPath)
				}
			}
		}))

	report := map[string]any{
		"component": "daemon",
		"nfr": map[string]any{
			"directory_list_ms": 2000,
			"preview_2mb_ms":    3000,
		},
		"cases": cases,
	}
	blob, _ := json.MarshalIndent(report, "", "  ")
	t.Logf("filesystem latency report:\n%s", blob)
	if out := os.Getenv("CLIORA_PERF_OUT"); out != "" {
		if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
			t.Fatalf("perf out dir: %v", err)
		}
		if err := os.WriteFile(out, append(blob, '\n'), 0o644); err != nil {
			t.Fatalf("write perf out: %v", err)
		}
	}
	for _, c := range cases {
		if !c.OK {
			t.Errorf("%s exceeded its budget: p95 %.1fms >= %.0fms", c.Name, c.P95Ms, c.BudgetMs)
		}
	}
}

// classifyBudgetMs bounds Classify over a full 2 MiB preview buffer
// (FR-FILE-008.AC-05). The point of the number is not that 5 ms is fast; it is
// that scanning the whole buffer instead of an 8 KiB prefix was never a
// performance decision. ADR 0015 allows 3 s for a ≤2 MB preview, so this is
// 0.17% of the budget at the limit and ~0.09% in practice.
const classifyBudgetMs = 5

func twoMiBMixedText() []byte {
	unit := "套件說明 package docs line with 中文 and ascii\n"
	return []byte(strings.Repeat(unit, (2*1024*1024)/len(unit)+1))
}

func TestClassifyLatencyBudget(t *testing.T) {
	if raceEnabled {
		t.Skip("latency budget is meaningless under the race detector; " +
			"GATE-WF-CLASSIFY-CORPUS runs this package without -race")
	}
	body := twoMiBMixedText()
	if v, _ := Classify(body); v != VerdictText {
		t.Fatalf("fixture must classify as text, got %s", verdictName(v))
	}
	// Best of five: this asserts a ceiling, and a single sample on a shared CI
	// runner measures the neighbours as much as the code.
	best := time.Duration(1<<62 - 1)
	for i := 0; i < 5; i++ {
		start := time.Now()
		Classify(body)
		if d := time.Since(start); d < best {
			best = d
		}
	}
	t.Logf("Classify over %d bytes: %.2f ms (budget %d ms)",
		len(body), float64(best.Microseconds())/1000, classifyBudgetMs)
	if best > classifyBudgetMs*time.Millisecond {
		t.Errorf("Classify took %v for 2 MiB, over the %d ms budget", best, classifyBudgetMs)
	}
}

func BenchmarkClassify2MiB(b *testing.B) {
	body := twoMiBMixedText()
	b.SetBytes(int64(len(body)))
	for b.Loop() {
		Classify(body)
	}
}
