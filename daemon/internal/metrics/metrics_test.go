package metrics

import "testing"

func TestCounterAccumulatesPerLabelSet(t *testing.T) {
	Reset()
	Increment(FilesystemRequestTotal, map[string]string{"op": "list", "code": "OK"})
	Increment(FilesystemRequestTotal, map[string]string{"op": "list", "code": "OK"})
	Increment(FilesystemRequestTotal, map[string]string{"op": "read", "code": "FILE_DENIED"})

	if got := CounterValue(FilesystemRequestTotal, map[string]string{"op": "list", "code": "OK"}); got != 2 {
		t.Fatalf("list/OK = %d, want 2", got)
	}
	if got := CounterValue(FilesystemRequestTotal, map[string]string{"op": "read", "code": "FILE_DENIED"}); got != 1 {
		t.Fatalf("read/FILE_DENIED = %d, want 1", got)
	}
	// An unseen series reads as zero.
	if got := CounterValue(FilesystemRequestTotal, map[string]string{"op": "search", "code": "OK"}); got != 0 {
		t.Fatalf("search/OK = %d, want 0", got)
	}
}

func TestLabelOrderIsStable(t *testing.T) {
	Reset()
	Increment("x_total", map[string]string{"op": "list", "code": "OK"})
	Increment("x_total", map[string]string{"code": "OK", "op": "list"})
	if got := CounterValue("x_total", map[string]string{"op": "list", "code": "OK"}); got != 2 {
		t.Fatalf("value = %d, want 2 (label order must not split the series)", got)
	}
}

func TestHistogramCountsAndSums(t *testing.T) {
	Reset()
	for _, v := range []float64{1, 50, 5000, 50_000_000} {
		Observe(FilesystemListEntries, v, nil)
	}
	count, sum := HistogramCount(FilesystemListEntries, nil)
	if count != 4 {
		t.Fatalf("count = %d, want 4", count)
	}
	if sum != 50_005_051 {
		t.Fatalf("sum = %v, want 50005051", sum)
	}
	// The out-of-range sample lands in the overflow bucket, not a real one.
	mu.Lock()
	s := histograms[key(FilesystemListEntries, nil)]
	mu.Unlock()
	if s.Inf != 1 {
		t.Fatalf("inf = %d, want 1", s.Inf)
	}
}

func TestSnapshotAndReset(t *testing.T) {
	Reset()
	Increment(FilesystemDeniedTotal, map[string]string{"reason": "dotenv"})
	Observe(FilesystemReadBytes, 12, nil)

	counters, hists := Snapshot()
	if counters[`filesystem_denied_total{reason=dotenv}`] != 1 {
		t.Fatalf("snapshot counters = %v", counters)
	}
	if hists[FilesystemReadBytes].Count != 1 {
		t.Fatalf("snapshot histograms = %v", hists)
	}

	Reset()
	counters, hists = Snapshot()
	if len(counters) != 0 || len(hists) != 0 {
		t.Fatalf("reset left %v / %v", counters, hists)
	}
}
