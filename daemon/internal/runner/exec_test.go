package runner

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

type collector struct {
	mu     sync.Mutex
	chunks []string
	flags  []bool
	events int
}

func (c *collector) Chunk(data string, truncated bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.chunks = append(c.chunks, data)
	c.flags = append(c.flags, truncated)
}

func (c *collector) Event() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.events++
}

func (c *collector) joined() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return strings.Join(c.chunks, "\n")
}

// A chunk may never end mid-event. Half a JSON line cannot be rendered, so "do not
// split a line" outranks "fill the chunk" — which means chunks come out *under* the
// ceiling rather than exactly at it.
func TestPumpNeverSplitsALine(t *testing.T) {
	line := `{"type":"assistant","message":"` + strings.Repeat("x", 200) + `"}`
	script := "for i in $(seq 1 20); do echo '" + line + "'; done"
	cmd := exec.Command("sh", "-c", script)
	execution, out, err := Start(cmd, Options{ChunkBytes: 512, IdleTimeout: 5 * time.Second})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	sink := &collector{}
	if pumpErr := execution.Pump(context.Background(), out, sink); pumpErr != nil {
		t.Fatalf("pump: %v", pumpErr)
	}
	execution.Wait()

	sink.mu.Lock()
	defer sink.mu.Unlock()
	if len(sink.chunks) < 2 {
		t.Fatalf("expected several chunks, got %d", len(sink.chunks))
	}
	for i, chunk := range sink.chunks {
		if len(chunk) > 512 {
			t.Fatalf("chunk %d is %d bytes, over the ceiling", i, len(chunk))
		}
		for _, l := range strings.Split(chunk, "\n") {
			if l == "" {
				continue
			}
			if !strings.HasPrefix(l, "{") || !strings.HasSuffix(l, "}") {
				t.Fatalf("chunk %d contains a partial event: %.80s…", i, l)
			}
		}
	}
	if sink.events != 20 {
		t.Fatalf("counted %d events, want 20", sink.events)
	}
}

// A single line larger than a whole chunk is truncated and **flagged**, rather than
// split: the reader learns something was lost instead of seeing malformed JSON.
func TestPumpTruncatesAnOversizeLineAndSaysSo(t *testing.T) {
	cmd := exec.Command("sh", "-c", "printf 'a%.0s' $(seq 1 4000); echo")
	execution, out, err := Start(cmd, Options{ChunkBytes: 256, IdleTimeout: 5 * time.Second})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	sink := &collector{}
	if pumpErr := execution.Pump(context.Background(), out, sink); pumpErr != nil {
		t.Fatalf("pump: %v", pumpErr)
	}
	execution.Wait()

	sink.mu.Lock()
	defer sink.mu.Unlock()
	if len(sink.chunks) != 1 {
		t.Fatalf("expected one chunk, got %d", len(sink.chunks))
	}
	if !sink.flags[0] {
		t.Fatal("the oversize line was not flagged as truncated")
	}
	if len(sink.chunks[0]) >= 256 {
		t.Fatalf("chunk is %d bytes, over the ceiling", len(sink.chunks[0]))
	}
}

// The idle timer is the **primary** liveness judgement, and it measures silence on the
// event stream — not elapsed wall time. A child that keeps emitting must survive far
// past the idle window.
func TestIdleTimeoutFiresOnSilenceAndNotOnDuration(t *testing.T) {
	t.Run("silent child is stopped", func(t *testing.T) {
		cmd := exec.Command("sh", "-c", "sleep 30")
		execution, out, err := Start(cmd, Options{IdleTimeout: 300 * time.Millisecond})
		if err != nil {
			t.Fatalf("start: %v", err)
		}
		pumpErr := execution.Pump(context.Background(), out, &collector{})
		if !errors.Is(pumpErr, ErrIdleTimeout) {
			t.Fatalf("expected an idle timeout, got %v", pumpErr)
		}
		_ = execution.Cancel("idle")
		execution.Wait()
	})

	t.Run("a talkative child outlives the idle window", func(t *testing.T) {
		// Emits for well over the idle window, but never goes quiet for it. A wall
		// clock would have killed this; the event stream is what tells them apart.
		cmd := exec.Command("sh", "-c",
			`for i in 1 2 3 4 5 6; do echo '{"type":"progress"}'; sleep 0.15; done`)
		execution, out, err := Start(cmd, Options{IdleTimeout: 400 * time.Millisecond})
		if err != nil {
			t.Fatalf("start: %v", err)
		}
		sink := &collector{}
		if pumpErr := execution.Pump(context.Background(), out, sink); pumpErr != nil {
			t.Fatalf("a working child was killed: %v", pumpErr)
		}
		execution.Wait()
		if sink.events != 6 {
			t.Fatalf("counted %d events, want 6", sink.events)
		}
	})
}

func TestWallClockIsABackstopWithItsOwnError(t *testing.T) {
	cmd := exec.Command("sh", "-c", `while true; do echo '{"t":1}'; sleep 0.05; done`)
	execution, out, err := Start(cmd, Options{
		IdleTimeout: 10 * time.Second,
		WallClock:   400 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	pumpErr := execution.Pump(context.Background(), out, &collector{})
	if !errors.Is(pumpErr, ErrWallClock) {
		t.Fatalf("expected the wall clock, got %v", pumpErr)
	}
	_ = execution.Cancel("wall")
	execution.Wait()
}

// Exit condition 11, as a machine assertion rather than a screenshot: after a cancel
// **the run's process group is empty**. An agent spawns a shell which spawns children;
// signalling only the child would leave that tree running and the node's capacity
// accounting wrong.
func TestCancelLeavesNothingInTheProcessGroup(t *testing.T) {
	// A shell whose grandchildren outlive it unless the whole group is signalled.
	cmd := exec.Command("sh", "-c", "sleep 300 & sleep 300 & echo '{\"t\":1}'; wait")
	execution, out, err := Start(cmd, Options{
		IdleTimeout: 10 * time.Second,
		GraceKill:   300 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("start: %v", err)
	}
	pid := execution.Pid()
	go func() { _ = execution.Pump(context.Background(), out, &collector{}) }()
	time.Sleep(200 * time.Millisecond)

	if err := execution.Cancel("user_cancelled"); err != nil {
		t.Fatalf("cancel: %v", err)
	}
	execution.Wait()

	deadline := time.Now().Add(3 * time.Second)
	for {
		remaining := processGroupMembers(t, pid)
		if len(remaining) == 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("processes survived the cancel in pgid %d: %v", pid, remaining)
		}
		time.Sleep(50 * time.Millisecond)
	}

	if execution.CancelledFor() != "user_cancelled" {
		t.Fatal("the cancellation reason was lost")
	}
}

// processGroupMembers scans /proc for live processes in one group, which is the same
// instrument the exit condition names — `ps` is how a person checks, not how a test
// re-runs.
func processGroupMembers(t *testing.T, pgid int) []int {
	t.Helper()
	entries, err := os.ReadDir("/proc")
	if err != nil {
		t.Skipf("/proc is unavailable: %v", err)
	}
	var members []int
	for _, entry := range entries {
		pid, convErr := strconv.Atoi(entry.Name())
		if convErr != nil {
			continue
		}
		stat, readErr := os.ReadFile("/proc/" + entry.Name() + "/stat")
		if readErr != nil {
			continue
		}
		// Field 5 is pgrp, and the fields before it include a comm that may contain
		// spaces and parentheses — so the split starts after the final ')'.
		close := strings.LastIndex(string(stat), ")")
		if close < 0 {
			continue
		}
		fields := strings.Fields(string(stat)[close+1:])
		if len(fields) < 3 {
			continue
		}
		// state, ppid, pgrp — index 2 here is field 5 overall.
		if fields[2] == strconv.Itoa(pgid) && fields[0] != "Z" {
			members = append(members, pid)
		}
	}
	return members
}
