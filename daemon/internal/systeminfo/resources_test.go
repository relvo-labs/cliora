package systeminfo

import (
	"math"
	"testing"
)

func TestParseLoadAvg(t *testing.T) {
	v, ok := parseLoadAvg([]byte("0.42 0.31 0.25 1/234 5678\n"))
	if !ok || math.Abs(v-0.42) > 1e-9 {
		t.Fatalf("parseLoadAvg = %v,%v want 0.42,true", v, ok)
	}
	if _, ok := parseLoadAvg([]byte("")); ok {
		t.Error("empty loadavg should not parse")
	}
	if _, ok := parseLoadAvg([]byte("notanumber\n")); ok {
		t.Error("non-numeric loadavg should not parse")
	}
}

func TestParseMemUsage(t *testing.T) {
	meminfo := "MemTotal:       1000 kB\nMemFree:         100 kB\nMemAvailable:    250 kB\nBuffers:          10 kB\n"
	v, ok := parseMemUsage([]byte(meminfo))
	if !ok {
		t.Fatal("expected mem usage to parse")
	}
	// used = 1000 - 250 = 750 => 75%.
	if math.Abs(v-75.0) > 1e-9 {
		t.Fatalf("memory usage = %v, want 75", v)
	}
	if _, ok := parseMemUsage([]byte("MemTotal: 0 kB\nMemAvailable: 0 kB\n")); ok {
		t.Error("zero MemTotal must not parse")
	}
	if _, ok := parseMemUsage([]byte("MemFree: 100 kB\n")); ok {
		t.Error("missing MemTotal/MemAvailable must not parse")
	}
}

func TestParseCPUTotals(t *testing.T) {
	// user nice system idle iowait irq softirq ...
	stat := "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0\n"
	idle, total, ok := parseCPUTotals([]byte(stat))
	if !ok {
		t.Fatal("expected cpu totals to parse")
	}
	if idle != 800 { // idle(700) + iowait(100)
		t.Errorf("idle = %d, want 800", idle)
	}
	if total != 1000 { // 100+0+100+700+100
		t.Errorf("total = %d, want 1000", total)
	}
	if _, _, ok := parseCPUTotals([]byte("nocpu here\n")); ok {
		t.Error("missing cpu line must not parse")
	}
}

func TestCPUDelta(t *testing.T) {
	s := NewResourceSampler("")
	// First sample primes state and reports nothing.
	if _, ok := s.cpuDelta(800, 1100); ok {
		t.Fatal("first cpuDelta call must report ok=false")
	}
	// Next: idle +100, total +200 => busy 100/200 = 50%.
	v, ok := s.cpuDelta(900, 1300)
	if !ok {
		t.Fatal("second cpuDelta call must report a figure")
	}
	if math.Abs(v-50.0) > 1e-9 {
		t.Fatalf("cpu usage = %v, want 50", v)
	}
}

func TestSampleAlwaysReportsUptime(t *testing.T) {
	s := NewResourceSampler("")
	res := s.Sample()
	if res.DaemonUptime == nil || *res.DaemonUptime < 0 {
		t.Fatalf("daemon_uptime must always be present and non-negative, got %v", res.DaemonUptime)
	}
}
