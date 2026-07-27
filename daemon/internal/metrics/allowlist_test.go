package metrics

import (
	"os"
	"strings"
	"testing"
)

// TestAnIdentifyingLabelIsRefused is the daemon half of the ADR 0018 label rule.
//
// Metrics are the one sink with no redaction: a node id or a path in a label is
// published verbatim to whoever can read them, and a high-cardinality label is how a
// metrics backend runs out of memory. A panic rather than a silent drop, because a
// metric that quietly loses its dimensions looks like it works and the mistake shows up
// much later as a dashboard that aggregated everything into one line.
func TestAnIdentifyingLabelIsRefused(t *testing.T) {
	for _, label := range []string{"node_id", "session_id", "path", "keyword", "filename", "username"} {
		t.Run(label, func(t *testing.T) {
			defer func() {
				recovered := recover()
				if recovered == nil {
					t.Fatalf("label %q was accepted", label)
				}
				err, ok := recovered.(LabelNotAllowed)
				if !ok {
					t.Fatalf("panicked with %T, want LabelNotAllowed", recovered)
				}
				if !strings.Contains(err.Error(), label) {
					t.Errorf("error does not name the label: %v", err)
				}
			}()
			Increment("x_total", map[string]string{label: "value"})
		})
	}
}

func TestAnAllowedLabelIsRecorded(t *testing.T) {
	Reset()
	Increment(DaemonSessionStartTotal, map[string]string{"runtime": "claude", "result": "started"})
	if got := CounterValue(DaemonSessionStartTotal, map[string]string{"runtime": "claude", "result": "started"}); got != 1 {
		t.Fatalf("counter = %d, want 1", got)
	}
}

// TestAGaugeIsOverwrittenNotAccumulated: a gauge answers "how many now". Adding to it
// would turn "3 active sessions" into a running total of every sample ever taken, which
// looks like a plausible number and is not one.
func TestAGaugeIsOverwrittenNotAccumulated(t *testing.T) {
	Reset()
	SetGauge(DaemonActiveSessions, 3, nil)
	SetGauge(DaemonActiveSessions, 1, nil)
	if got := GaugeValue(DaemonActiveSessions, nil); got != 1 {
		t.Fatalf("gauge = %v, want 1 (the latest value)", got)
	}
}

func TestRenderIsSortedAndIncludesEverySeriesKind(t *testing.T) {
	Reset()
	Increment(DaemonHeartbeatSent, nil)
	SetGauge(DaemonActiveSessions, 2, nil)
	Observe(FilesystemReadBytes, 1024, map[string]string{"op": "read"})

	rendered := Render()
	for _, want := range []string{
		DaemonHeartbeatSent + " 1",
		DaemonActiveSessions + " 2",
		FilesystemReadBytes + `{op=read} count 1`,
	} {
		if !strings.Contains(rendered, want) {
			t.Errorf("Render() is missing %q:\n%s", want, rendered)
		}
	}
	lines := strings.Split(strings.TrimSpace(rendered), "\n")
	for i := 1; i < len(lines); i++ {
		if lines[i-1] > lines[i] {
			t.Fatalf("Render() is not sorted: %q before %q", lines[i-1], lines[i])
		}
	}
}

// TestThisPackageCannotOpenAPort guards the decision that matters most about daemon
// metrics: the trust boundary is outbound-only (ADR 0008), so the daemon must never
// listen. A convenience Prometheus listener would invert that boundary on every node in
// the fleet at once — which is why the values Central needs travel on the heartbeat it
// already sends, and local inspection is `agentd metrics` on stdout.
//
// Structural rather than behavioural: a test that merely fails to connect would pass
// for the wrong reason. Nothing here can listen if nothing here imports a network
// package.
func TestThisPackageCannotOpenAPort(t *testing.T) {
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatal(err)
	}
	banned := []string{`"net"`, `"net/http"`, `"net/url"`}
	checked := 0
	for _, entry := range entries {
		name := entry.Name()
		// Production source only: this very file names the banned imports in order to
		// look for them.
		if entry.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		source, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		checked++
		for _, importPath := range banned {
			if strings.Contains(string(source), importPath) {
				t.Errorf("%s imports %s; the daemon must not be able to listen", name, importPath)
			}
		}
	}
	if checked == 0 {
		t.Fatal("no source files were checked")
	}
}
