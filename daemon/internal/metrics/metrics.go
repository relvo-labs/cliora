// Package metrics is the daemon's in-process counter/histogram registry
// (tech §18.1-18.2). tech §18.2 defers exposing a Prometheus port, so this is
// the collection point: tests assert on Snapshot(), and a later exporter reads
// the same structure.
//
// Only low-cardinality labels are allowed — operation names, coarse reasons,
// error codes. A path, a file name, a search keyword or file content must never
// reach a label or a value here.
package metrics

import (
	"sort"
	"strconv"
	"strings"
	"sync"
)

// Filesystem relay (P3-09).
const (
	FilesystemListEntries        = "filesystem_list_entries"
	FilesystemSearchScanned      = "filesystem_search_scanned"
	FilesystemSearchStoppedTotal = "filesystem_search_stopped_total"
	FilesystemReadBytes          = "filesystem_read_bytes"
	FilesystemDeniedTotal        = "filesystem_denied_total"
	FilesystemRequestTotal       = "filesystem_request_total"
	// Image drop (P13, ADR 0024). Bytes written, not requests: the quota that
	// matters is cumulative size, so that is what the series has to show.
	FilesystemUploadBytes = "filesystem_upload_bytes"
)

// tech §18.2, the daemon's own series (P4-09).
//
// These are read by `agentd metrics` and by `agentd doctor`; the daemon **does not
// open a Prometheus port**. That is the point: the trust boundary is outbound-only
// (ADR 0008), and a listening socket on every node would invert it for the sake of
// convenience. The values that Central needs travel on the heartbeat it is already
// sending, and Central persists them (`node_metric_samples`, P4-06).
const (
	DaemonReconnectTotal    = "daemon_reconnect_total"
	DaemonHeartbeatSent     = "daemon_heartbeat_sent_total"
	DaemonSessionStartTotal = "daemon_session_start_total"
	// Port forwarding (P11, ADR 0022). Labels are coarse on purpose: no port, no URL, no
	// tunnel id and no credential — a metric label is the easiest place for an identifier to
	// escape into a scrape target, and none of these questions need one.
	DaemonTunnelStartTotal        = "daemon_tunnel_start_total"
	DaemonTunnelReconnectTotal    = "daemon_tunnel_reconnect_total"
	DaemonTunnelURLChangedTotal   = "daemon_tunnel_url_changed_total"
	DaemonTunnelOrphanReapedTotal = "daemon_tunnel_orphan_reaped_total"
	DaemonTunnelActive            = "daemon_tunnel_active"
	DaemonActiveSessions          = "daemon_active_sessions"
	DaemonUptimeSeconds           = "daemon_uptime_seconds"
)

// The label keys this registry accepts, mirroring the backend's allowlist
// (`backend/app/metrics.py`) and ADR 0018. A node id, a session id, a path or a
// keyword must never become a label: metrics are the one sink with no redaction, and a
// high-cardinality label is how a metrics backend runs out of memory.
var allowedLabels = map[string]bool{
	"op": true, "type": true, "code": true, "reason": true, "runtime": true,
	"status": true, "stage": true, "result": true, "state": true, "kind": true,
	"direction": true, "channel": true,
	// "sandbox" is bypassed|enforced on daemon_session_start_total (ADR 0023). Two
	// values, neither identifying, and it answers a question that gets asked after the
	// fact: were the sessions on this node running without a sandbox?
	"sandbox": true,
	// "mime" is one of exactly four accepted image types on filesystem_upload_bytes
	// (ADR 0024 §2.1). The set is closed by the wire contract, so this cannot grow
	// with user input — which is the only reason a content-derived label is safe here.
	"mime": true,
}

// LabelNotAllowed names a rejected label key. Recording panics rather than silently
// dropping the label: a metric that quietly loses its dimensions looks like it works,
// and the mistake surfaces later as a dashboard that aggregated everything into one
// line. A panic in a metrics call is caught by the tests, never by a user — nothing on
// a request path adds a label that is not already in the allowlist.
type LabelNotAllowed struct {
	Metric string
	Label  string
}

func (e LabelNotAllowed) Error() string {
	return "metrics: label " + e.Label + " on " + e.Metric + " is not in the label allowlist"
}

func checkLabels(name string, labels map[string]string) {
	for key := range labels {
		if !allowedLabels[key] {
			panic(LabelNotAllowed{Metric: name, Label: key})
		}
	}
}

// Buckets for volume histograms (entries, scanned files, bytes are all counts,
// so the same coarse powers-of-ten scale fits).
var buckets = []float64{1, 10, 100, 1000, 10000, 100000, 1000000, 10000000}

type series struct {
	Count   int64
	Sum     float64
	Buckets []int64
	Inf     int64
}

var (
	mu         sync.Mutex
	counters   = map[string]int64{}
	gauges     = map[string]float64{}
	histograms = map[string]*series{}
)

// key renders a metric name plus sorted labels into a stable series key.
func key(name string, labels map[string]string) string {
	if len(labels) == 0 {
		return name
	}
	parts := make([]string, 0, len(labels))
	for k, v := range labels {
		parts = append(parts, k+"="+v)
	}
	sort.Strings(parts)
	return name + "{" + strings.Join(parts, ",") + "}"
}

// Increment adds one to a labelled counter.
func Increment(name string, labels map[string]string) {
	checkLabels(name, labels)
	mu.Lock()
	defer mu.Unlock()
	counters[key(name, labels)]++
}

// SetGauge records a point-in-time value. Stored separately from counters because a
// gauge is overwritten, not accumulated — adding to it would turn "3 sessions" into a
// running total of every sample ever taken.
func SetGauge(name string, value float64, labels map[string]string) {
	checkLabels(name, labels)
	mu.Lock()
	defer mu.Unlock()
	gauges[key(name, labels)] = value
}

// GaugeValue returns a gauge's current value (0 if never set).
func GaugeValue(name string, labels map[string]string) float64 {
	mu.Lock()
	defer mu.Unlock()
	return gauges[key(name, labels)]
}

// Observe records one sample in a labelled histogram.
func Observe(name string, value float64, labels map[string]string) {
	checkLabels(name, labels)
	mu.Lock()
	defer mu.Unlock()
	k := key(name, labels)
	s := histograms[k]
	if s == nil {
		s = &series{Buckets: make([]int64, len(buckets))}
		histograms[k] = s
	}
	s.Count++
	s.Sum += value
	for i, bound := range buckets {
		if value <= bound {
			s.Buckets[i]++
			return
		}
	}
	s.Inf++
}

// CounterValue returns a counter's current value (0 if never incremented).
func CounterValue(name string, labels map[string]string) int64 {
	mu.Lock()
	defer mu.Unlock()
	return counters[key(name, labels)]
}

// HistogramCount returns how many samples a histogram holds, and their sum.
func HistogramCount(name string, labels map[string]string) (int64, float64) {
	mu.Lock()
	defer mu.Unlock()
	s := histograms[key(name, labels)]
	if s == nil {
		return 0, 0
	}
	return s.Count, s.Sum
}

// Snapshot copies every series for logging or export.
func Snapshot() (map[string]int64, map[string]struct {
	Count int64
	Sum   float64
}) {
	mu.Lock()
	defer mu.Unlock()
	cs := make(map[string]int64, len(counters))
	for k, v := range counters {
		cs[k] = v
	}
	hs := make(map[string]struct {
		Count int64
		Sum   float64
	}, len(histograms))
	for k, s := range histograms {
		hs[k] = struct {
			Count int64
			Sum   float64
		}{Count: s.Count, Sum: s.Sum}
	}
	return cs, hs
}

// Reset clears every series. Tests only.
func Reset() {
	mu.Lock()
	defer mu.Unlock()
	counters = map[string]int64{}
	gauges = map[string]float64{}
	histograms = map[string]*series{}
}

// Render writes every series as sorted `name{labels} value` lines.
//
// For `agentd metrics` and `agentd doctor --metrics`: a human- and grep-readable dump
// on stdout, not an HTTP endpoint. Sorted so two runs are diffable.
func Render() string {
	mu.Lock()
	keys := make([]string, 0, len(counters)+len(gauges)+len(histograms)*2)
	values := map[string]string{}
	for k, v := range counters {
		keys = append(keys, k)
		values[k] = strconv.FormatInt(v, 10)
	}
	for k, v := range gauges {
		keys = append(keys, k)
		values[k] = strconv.FormatFloat(v, 'f', -1, 64)
	}
	for k, s := range histograms {
		countKey, sumKey := k+" count", k+" sum"
		keys = append(keys, countKey, sumKey)
		values[countKey] = strconv.FormatInt(s.Count, 10)
		values[sumKey] = strconv.FormatFloat(s.Sum, 'f', -1, 64)
	}
	mu.Unlock()

	sort.Strings(keys)
	var out strings.Builder
	for _, k := range keys {
		out.WriteString(k)
		out.WriteString(" ")
		out.WriteString(values[k])
		out.WriteString("\n")
	}
	return out.String()
}
