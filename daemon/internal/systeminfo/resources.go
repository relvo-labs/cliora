package systeminfo

import (
	"os"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Resources is a best-effort snapshot of node load reported inside
// node.heartbeat (tech §18.2). Every field is optional: a field is nil when it
// could not be sampled cheaply, so a sampling failure never blocks or fails the
// heartbeat. Percentages are 0-100.
type Resources struct {
	CPUUsage     *float64
	MemoryUsage  *float64
	LoadAverage  *float64
	DiskUsage    *float64
	DaemonUptime *float64
}

// ResourceSampler samples node resources periodically. It is safe for
// concurrent use. daemon_uptime is derived from a monotonic start time; cpu
// usage is a delta between successive /proc/stat reads so a single sample is
// cheap and non-blocking (the first call reports no cpu figure until it has two
// points to diff).
type ResourceSampler struct {
	started  time.Time
	diskPath string

	mu        sync.Mutex
	haveCPU   bool
	prevIdle  uint64
	prevTotal uint64
}

// NewResourceSampler starts the uptime clock. diskPath is the path whose
// filesystem usage is reported (typically "/"); an empty path disables the disk
// figure.
func NewResourceSampler(diskPath string) *ResourceSampler {
	return &ResourceSampler{started: time.Now(), diskPath: diskPath}
}

// Sample returns a fresh best-effort snapshot. It never blocks on network or
// heavy work and swallows per-metric errors (leaving that metric nil).
func (s *ResourceSampler) Sample() Resources {
	res := Resources{}

	uptime := time.Since(s.started).Seconds()
	if uptime < 0 {
		uptime = 0
	}
	res.DaemonUptime = &uptime

	if data, err := os.ReadFile("/proc/loadavg"); err == nil {
		if v, ok := parseLoadAvg(data); ok {
			res.LoadAverage = &v
		}
	}
	if data, err := os.ReadFile("/proc/meminfo"); err == nil {
		if v, ok := parseMemUsage(data); ok {
			res.MemoryUsage = &v
		}
	}
	if data, err := os.ReadFile("/proc/stat"); err == nil {
		if idle, total, ok := parseCPUTotals(data); ok {
			if v, ok := s.cpuDelta(idle, total); ok {
				res.CPUUsage = &v
			}
		}
	}
	if s.diskPath != "" {
		if v, ok := diskUsagePercent(s.diskPath); ok {
			res.DiskUsage = &v
		}
	}
	return res
}

// cpuDelta records the latest /proc/stat totals and returns the busy percentage
// since the previous sample. The first call primes the state and reports no
// figure (ok=false) because a rate needs two points.
func (s *ResourceSampler) cpuDelta(idle, total uint64) (float64, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	prevIdle, prevTotal, have := s.prevIdle, s.prevTotal, s.haveCPU
	s.prevIdle, s.prevTotal, s.haveCPU = idle, total, true
	if !have || total <= prevTotal {
		return 0, false
	}
	dTotal := float64(total - prevTotal)
	dIdle := float64(idle - prevIdle)
	usage := (dTotal - dIdle) / dTotal * 100
	if usage < 0 {
		usage = 0
	}
	if usage > 100 {
		usage = 100
	}
	return usage, true
}

// parseLoadAvg extracts the 1-minute load from /proc/loadavg ("0.42 0.31 ...").
func parseLoadAvg(data []byte) (float64, bool) {
	fields := strings.Fields(string(data))
	if len(fields) == 0 {
		return 0, false
	}
	v, err := strconv.ParseFloat(fields[0], 64)
	if err != nil || v < 0 {
		return 0, false
	}
	return v, true
}

// parseMemUsage computes used-memory percentage from /proc/meminfo using
// MemTotal and MemAvailable (used = total - available).
func parseMemUsage(data []byte) (float64, bool) {
	var total, available uint64
	var haveTotal, haveAvail bool
	for _, line := range strings.Split(string(data), "\n") {
		key, rest, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		fields := strings.Fields(rest)
		if len(fields) == 0 {
			continue
		}
		v, err := strconv.ParseUint(fields[0], 10, 64)
		if err != nil {
			continue
		}
		switch key {
		case "MemTotal":
			total, haveTotal = v, true
		case "MemAvailable":
			available, haveAvail = v, true
		}
	}
	if !haveTotal || !haveAvail || total == 0 || available > total {
		return 0, false
	}
	used := total - available
	return float64(used) / float64(total) * 100, true
}

// parseCPUTotals reads the aggregate "cpu" line of /proc/stat and returns idle
// (idle+iowait) and total jiffies.
func parseCPUTotals(data []byte) (idle, total uint64, ok bool) {
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, "cpu ") {
			continue
		}
		fields := strings.Fields(line)[1:]
		if len(fields) < 5 {
			return 0, 0, false
		}
		var sum uint64
		for i, f := range fields {
			v, err := strconv.ParseUint(f, 10, 64)
			if err != nil {
				return 0, 0, false
			}
			sum += v
			// Field 3 is idle, field 4 is iowait (0-indexed within fields).
			if i == 3 || i == 4 {
				idle += v
			}
		}
		return idle, sum, true
	}
	return 0, 0, false
}

// diskUsagePercent returns the used percentage of the filesystem holding path.
func diskUsagePercent(path string) (float64, bool) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(path, &st); err != nil {
		return 0, false
	}
	total := st.Blocks
	if total == 0 {
		return 0, false
	}
	used := total - st.Bavail
	return float64(used) / float64(total) * 100, true
}
