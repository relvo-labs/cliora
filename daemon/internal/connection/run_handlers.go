package connection

import (
	"context"
	"encoding/json"
	"log/slog"
	"os"
	"sort"
	"sync"
	"time"

	"github.com/cliora/cliora/daemon/internal/config"

	"github.com/cliora/cliora/daemon/internal/gitfetch"
	"github.com/cliora/cliora/daemon/internal/protocol"
	"github.com/cliora/cliora/daemon/internal/runner"
	"github.com/cliora/cliora/daemon/internal/runtime"
)

// The daemon's side of an agent run (AR-07, ADR 0029/0031).
//
// Everything here is one-way. The daemon **sends** `runner.poll` and receives an
// offer as a separate frame with its own id; it never waits for a correlated reply,
// because it keeps no pending map for requests it originates. That asymmetry is not an
// oversight on either side — Central cannot answer from inside its own receive loop
// either, so the claim happens when the poll arrives and the offer is a statement of
// fact rather than a question (ADR 0029 §2).

// runnerReady reports whether this node may advertise itself as a runner.
//
// Two conditions, and the second is why this is not just a config lookup: runner mode
// has to be enabled **and** the run root must have passed `CheckIsolation`. A node
// that would refuse to start a run must not tell Central it can take one — otherwise
// cards queue against a machine that will never claim them, and the reason lives only
// in that machine's startup log.
func (m *Manager) runnerReady() bool {
	return m.runner != nil
}

// runnerRegisterPayload is everything the machine reports about itself.
//
// `dedicated` is the one condition of "dedicated runner node" the platform can check,
// and it is **reported, never enforced** — a mixed-use dev VM is the common case, and
// refusing to run there would break it to guard a risk its owner accepted (ADR 0031
// §6). `enabled` is deliberately absent: that is an administrator's switch on Central,
// and a re-registration must not be able to turn a disabled runner back on.
func (m *Manager) runnerRegisterPayload(ctx context.Context) map[string]any {
	return map[string]any{
		"name":           m.cfg.Node.Name,
		"runtimes":       m.runnerRuntimes(ctx),
		"labels":         []string{},
		"max_concurrent": m.cfg.Runner.MaxConcurrent,
		"max_waiting":    m.cfg.Runner.MaxWaiting,
		"dedicated":      runner.Dedicated(m.cfg),
	}
}

// runnerRuntimes is the list of CLIs this machine can actually drive unattended.
//
// A machine whose CLI is installed but too old reports an **empty list and registers
// successfully**. That is deliberate: a failed registration reads as "the machine is
// broken", while an empty list plus a reason on the Agents page reads as what it is.
// The same applies when `git` is missing — without it a `source: repo` card could
// never be fetched, so advertising a runtime would be advertising a run that always
// fails at its first step.
func (m *Manager) runnerRuntimes(ctx context.Context) []string {
	m.runCapMu.Lock()
	defer m.runCapMu.Unlock()
	if m.runCapability != nil {
		return append([]string(nil), m.runCapability...)
	}
	var capable []string
	if _, err := gitfetch.Available(ctx); err != nil {
		slog.Warn("runner disabled: git is unavailable",
			"hint", "git is a runner-mode prerequisite; agentd doctor reports it")
		m.runCapability = []string{}
		return nil
	}
	for _, id := range sortedRuntimeIDs() {
		rt, ok := m.registry.Get(id)
		if !ok {
			continue
		}
		probe := runtime.ProbeRunCapable(ctx, rt, 5*time.Second)
		if probe.Capable {
			capable = append(capable, id)
			continue
		}
		slog.Info("runtime is not runner-capable", "runtime", id, "reason", probe.Reason)
	}
	// Cached for **one connection**, not for the process. `bypassProbe` caches per
	// process and a reconnect does not re-probe; here that would be worse, because a
	// stale "not capable" means this runner silently never claims a card while the
	// console shows a reason that is no longer true (plan/18/04-…md §5.3).
	m.runCapability = append([]string(nil), capable...)
	return capable
}

// resetRunCapability drops the per-connection probe cache. Called when a connection
// ends, so the next one re-probes.
func (m *Manager) resetRunCapability() {
	m.runCapMu.Lock()
	m.runCapability = nil
	m.runCapMu.Unlock()
}

// pollLoop asks for work while there is capacity.
//
// A runner at capacity **stops sending** rather than sending a zero — backpressure is
// structural, and there is no frame that means "I am full". When the loop stops for a
// disk reason it records it, so the heartbeat can say why instead of the node simply
// going quiet.
func (m *Manager) pollLoop(ctx context.Context, write func(string, string, any) error) {
	interval := time.Duration(m.cfg.Runner.PollIntervalSeconds) * time.Second
	if interval <= 0 {
		interval = 5 * time.Second
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			capacity, blocked := m.runner.Capacity()
			if capacity <= 0 {
				if blocked != "" {
					slog.Debug("runner is not polling", "reason", blocked)
				}
				continue
			}
			payload := map[string]any{
				"runner_id": m.creds.NodeID.String(),
				"capacity":  capacity,
			}
			if err := write("runner.poll", protocol.NewID(), payload); err != nil {
				return
			}
		}
	}
}

// handleRunOffer starts a run, or declines it.
//
// `run_id: null` is the "nothing for you" answer and the common case, so it is checked
// first and costs nothing.
func (m *Manager) handleRunOffer(
	ctx context.Context, env protocol.Envelope, data []byte, write func(string, string, any) error,
) {
	if protocol.ValidateControl(data) != nil {
		return
	}
	var offer protocol.RunOffer
	if json.Unmarshal(env.Payload, &offer) != nil || offer.RunID == nil || offer.Spec == nil {
		return
	}
	runID := offer.RunID.String()

	capacity, blocked := m.runner.Capacity()
	if capacity <= 0 {
		reason := "at_capacity"
		if blocked == "disk_quota" || blocked == "disk_low" {
			reason = "disk_quota"
		}
		// A release, not a failure: `attempt` is untouched on the platform side, and
		// the card goes straight back into the queue for somebody else.
		_ = write("run.decline", protocol.NewID(), map[string]any{
			"run_id": runID, "reason": reason,
		})
		return
	}
	go m.executeRun(ctx, offer, write)
}

// executeRun is one run, start to finish, on its own goroutine.
func (m *Manager) executeRun(
	ctx context.Context, offer protocol.RunOffer, write func(string, string, any) error,
) {
	runID := offer.RunID.String()
	spec := offer.Spec

	send := func(kind string, payload map[string]any) {
		payload["run_id"] = runID
		_ = write(kind, protocol.NewID(), payload)
	}

	send("run.progress", map[string]any{"phase": "preparing"})
	source := runner.Source{Kind: spec.Source.Kind, URL: spec.Source.URL, Ref: spec.Source.Ref}
	if source.Kind != "none" {
		send("run.progress", map[string]any{"phase": "fetching"})
	}
	layout, commit, err := m.runner.Prepare(ctx, runID, source)
	if err != nil {
		// Seconds, not the wall clock. The three fail-fast git variables are what make
		// this a fast failure, and the idle timer could not have helped: the fetch
		// happens before there is any event stream to measure.
		send("run.failed", map[string]any{
			"error_code": "RUN_SOURCE_UNAVAILABLE",
			// Never the URL: somebody may have pasted a credential into it.
			"message": err.Error(),
		})
		_ = runner.MarkFinished(layout, "failed", time.Now())
		return
	}
	if commit != "" {
		send("run.progress", map[string]any{"phase": "checked_out", "commit_sha": commit})
	}
	if err := runner.WriteContext(layout, spec.Context, spec.Credential); err != nil {
		send("run.failed", map[string]any{
			"error_code": "RUN_INTERNAL_ERROR", "message": "could not write the task context",
		})
		_ = runner.MarkFinished(layout, "failed", time.Now())
		return
	}

	runtimeID := spec.Runtime
	if runtimeID == "" {
		if ids := m.runnerRuntimes(ctx); len(ids) > 0 {
			runtimeID = ids[0]
		}
	}
	rt, _ := m.registry.Get(runtimeID)
	cmd := runtime.BuildRunCommand(rt, runtime.RunOptions{
		Dir: layout.Repo, Context: spec.Context, Env: os.Environ(),
	})
	if cmd == nil {
		send("run.failed", map[string]any{
			"error_code": "RUN_RUNTIME_UNAVAILABLE",
			"message":    "this node cannot drive that runtime non-interactively",
		})
		_ = runner.MarkFinished(layout, "failed", time.Now())
		return
	}
	if source.Kind == "none" {
		// No checkout, so the run's own directory is the working directory.
		cmd.Dir = layout.Root
	}

	execution, out, err := runner.Start(cmd, runner.Options{
		ChunkBytes:  32 * 1024,
		IdleTimeout: time.Duration(spec.IdleTimeoutSeconds) * time.Second,
		WallClock:   time.Duration(spec.TimeoutSeconds) * time.Second,
	})
	if err != nil {
		send("run.failed", map[string]any{
			"error_code": "RUN_INTERNAL_ERROR", "message": "the runtime did not start",
		})
		_ = runner.MarkFinished(layout, "failed", time.Now())
		return
	}
	m.runner.Track(runID, execution)
	defer m.runner.Untrack(runID)

	send("run.accept", map[string]any{})
	send("run.progress", map[string]any{"phase": "running"})

	// The lease is renewed unconditionally while the process exists. It answers "is
	// the runner alive", and making it conditional on child activity would make a dead
	// runner and a hung child look identical to Central — while their recoveries
	// differ (ADR 0029 §4).
	renewCtx, stopRenew := context.WithCancel(ctx)
	defer stopRenew()
	go m.renewLease(renewCtx, runID, write)

	seq := 0
	sink := &chunkSink{send: func(payload map[string]any) {
		payload["seq"] = seq
		seq++
		send("run.log_chunk", payload)
	}}
	pumpErr := execution.Pump(ctx, out, sink)
	if pumpErr != nil {
		// The idle timer and the wall clock are separate codes because they mean
		// different things to a person: "it is stuck, look at the last event" and "it
		// cannot finish, look at whether the card is too big".
		_ = execution.Cancel(pumpErr.Error())
	}
	outcome := execution.Wait()
	stopRenew()

	send("run.progress", map[string]any{"phase": "finishing"})
	summary := m.runner.Inspect(ctx, layout, source.Kind != "none")
	_ = runner.DropToken(layout)

	if pumpErr != nil {
		_ = runner.MarkFinished(layout, "failed", time.Now())
		send("run.failed", map[string]any{
			"error_code": pumpErr.Error(),
			"message":    "the run was stopped by the daemon",
			"summary":    runner.SummaryText(offer.Delivery, summary),
			"disk_bytes": summary.DiskBytes,
		})
		return
	}
	if outcome.ExitCode != 0 {
		_ = runner.MarkFinished(layout, "failed", time.Now())
		send("run.failed", map[string]any{
			"error_code": outcome.ErrorCode,
			"message":    "the runtime exited non-zero",
			"summary":    runner.SummaryText(offer.Delivery, summary),
			"disk_bytes": summary.DiskBytes,
		})
		return
	}

	result := "succeeded"
	if !summary.Dirty {
		// Distinguished from `succeeded` because it leads somewhere different: it means
		// the card may have been a no-op, or the agent misread it.
		result = "no_changes"
	}
	_ = runner.MarkFinished(layout, "succeeded", time.Now())
	send("run.complete", map[string]any{
		"result":           result,
		"summary":          runner.SummaryText(offer.Delivery, summary),
		"disk_bytes":       summary.DiskBytes,
		"git_remotes":      summary.Remotes,
		"unpushed_commits": summary.UnpushedCommits,
		"untracked_files":  summary.UntrackedFiles,
	})
}

func (m *Manager) renewLease(ctx context.Context, runID string, write func(string, string, any) error) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := write("run.lease_renew", protocol.NewID(),
				map[string]any{"run_id": runID}); err != nil {
				return
			}
		}
	}
}

// handleRunCancel stops a run's whole process group.
func (m *Manager) handleRunCancel(env protocol.Envelope, data []byte) {
	if protocol.ValidateControl(data) != nil {
		return
	}
	var p struct {
		RunID  string `json:"run_id"`
		Reason string `json:"reason"`
	}
	if json.Unmarshal(env.Payload, &p) != nil || p.RunID == "" {
		return
	}
	if err := m.runner.CancelRun(p.RunID, p.Reason); err != nil {
		slog.Info("cancel for an unknown run", "run_id", p.RunID)
	}
}

// sortedRuntimeIDs is the allowlist in a stable order, so "which runtime did an
// unspecified card get" is deterministic rather than map-iteration order.
func sortedRuntimeIDs() []string {
	ids := make([]string, 0, len(config.AllowedRuntimeIDs))
	for id := range config.AllowedRuntimeIDs {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	return ids
}

type chunkSink struct {
	mu   sync.Mutex
	send func(map[string]any)
}

func (s *chunkSink) Chunk(data string, truncated bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.send(map[string]any{"data": data, "truncated": truncated})
}

// Event is a no-op on this side: the idle decision is taken inside the execution,
// where the stream is, and Central learns about activity from `run.progress` rather
// than from a frame per event.
func (s *chunkSink) Event() {}
