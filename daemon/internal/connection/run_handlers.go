package connection

import (
	"context"
	"encoding/json"
	"fmt"
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
// `labels`, `run_untagged` and `accept_secrets` are the machine's declarations about
// itself (V2.3). **`labels` was a hard-coded empty slice until this phase** — the
// column existed on Central and the field was on the wire, but nothing could ever put
// a value in it. Shipping Central's tag matching without this would have made every
// card that declares a tag permanently unclaimable, with the Agents page showing every
// runner as having no tags: a symptom that reads like a missing setting rather than a
// missing feature (plan/20/00-…md D13).
func (m *Manager) runnerRegisterPayload(ctx context.Context) map[string]any {
	return map[string]any{
		"name":     m.cfg.Node.Name,
		"runtimes": m.runnerRuntimes(ctx),
		// Never nil: a nil slice marshals to `null`, the contract says array, and a
		// frame that fails validation is dropped silently by the receiver.
		"labels":         m.cfg.Runner.TagList(),
		"run_untagged":   m.cfg.Runner.RunUntaggedValue(),
		"accept_secrets": m.cfg.Runner.AcceptSecretsValue(),
		// What this binary can do, not what this machine wants to do — so a constant
		// rather than a setting. Central puts feature-gated content into an offer only
		// for a node that named the feature, and **absent means the empty set**: the
		// opposite default from the two booleans above, because those are refusals and
		// this is support (ADR 0029 amendment C).
		"features":       runner.Features,
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
		return append([]string{}, m.runCapability...)
	}
	// **Never nil.** A nil slice marshals to `null`, the contract says `runtimes` is an
	// array, and Central's decoder drops a frame that fails validation *silently* —
	// which is the exact failure D2 warns about: the message disappears and nothing
	// reports an error. The empty-set case is not an edge case here either, it is the
	// designed one: a node whose CLIs are too old registers successfully with no
	// runtimes (ADR 0029 §7).
	capable := []string{}
	if _, err := gitfetch.Available(ctx); err != nil {
		slog.Warn("runner disabled: git is unavailable",
			"hint", "git is a runner-mode prerequisite; agentd doctor reports it")
		m.runCapability = capable
		return capable
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
	m.runCapability = append([]string{}, capable...)
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

	// Optional string fields are **omitted when empty**, never sent as "". The
	// contract gives them `minLength: 1`, because an empty string is not a summary —
	// and a frame that fails validation is dropped by the receiver *silently*
	// (ADR 0029 D2). `summary` is empty on the common path: a run with nothing awkward
	// to report has nothing to say, so sending "" would have meant that **every clean
	// run's completion frame vanished** and the lease expired instead.
	//
	// Caught by `GATE-AR-DISPATCH-COVERAGE` rather than by a person, which is what
	// that gate is for.
	// Sorted by kind before anything else runs, because where a value goes decides what
	// the rest of this function may do with it (ADR 0032 §4).
	secrets := runner.SortSecrets(spec.Secrets)
	// **The redactor wraps `send`, not the log sink.** `run.failed` carries git's
	// stderr and `run.complete` carries free text, so the credential-shaped path out of
	// a run is an error message rather than a log line. Wrapping here covers every
	// frame this function will ever add without anybody remembering to (D6).
	redactor := runner.NewRedactor(secrets.All)

	send := func(kind string, payload map[string]any) {
		payload["run_id"] = runID
		// Optional strings are **omitted when empty, never sent as ""**: the contract
		// gives them `minLength: 1`, and a frame that fails validation is dropped by the
		// receiver *silently*. `pushed_branch` joins the list in 1.13.0 — an empty one
		// would take the whole `run.complete` with it, and the symptom would be an
		// expired lease rather than an error (plan/18 D2).
		for _, key := range []string{"summary", "message", "pushed_branch"} {
			if value, ok := payload[key].(string); ok && value == "" {
				delete(payload, key)
			}
		}
		_ = write(kind, protocol.NewID(), redactor.Payload(payload))
	}

	send("run.progress", map[string]any{"phase": "preparing"})
	source := runner.Source{Kind: spec.Source.Kind, URL: spec.Source.URL, Ref: spec.Source.Ref}

	// The directory first, then the credentials that have to live inside it, then the
	// fetch that uses them. The order is the reason `PrepareIn` exists.
	layout, err := runner.Create(m.cfg.Runner.WorkDir, runID)
	if err != nil {
		send("run.failed", map[string]any{
			"error_code": "RUN_INTERNAL_ERROR", "message": "could not create the run directory",
		})
		return
	}

	// The platform's git credentials, if this deployment delivers any. With none —
	// **the default** (2026-08-13 ruling) — `fetch` is byte-for-byte the V2.2 Fetcher,
	// the machine's own credentials are used, and nothing about them is hidden.
	fetch := m.runner.Fetch
	var agent *gitfetch.Agent
	var isolation []string
	if len(secrets.Git) > 0 {
		send("run.progress", map[string]any{"phase": "authenticating"})
		fetch, agent = m.prepareGitCredentials(ctx, layout, secrets, fetch)
		defer agent.Close()
		if home, homeErr := runner.PrepareIsolatedHome(layout.Cliora); homeErr == nil {
			isolation = secrets.IsolateAmbient(home, m.cfg.Runner.Git.IsolateAmbient())
		}
	}
	// Swapped for the length of this run only. Two runs on one node can hold different
	// credentials, and neither may inherit the other's.
	previous := m.runner.Fetch
	m.runner.Fetch = fetch
	defer func() { m.runner.Fetch = previous }()

	if source.Kind != "none" {
		send("run.progress", map[string]any{"phase": "fetching"})
	}
	commit, err := m.runner.PrepareIn(ctx, layout, source)
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
	// The run's own branch, created before the agent starts so that whatever it commits
	// lands there rather than on the base branch. Central composed the name; the prefix
	// is re-checked inside `CreateBranch`, because a constraint that trusts the frame it
	// was sent is not a constraint (ADR 0031 amendment A2/A4).
	//
	// `existing_branch` continues a branch instead of creating one, and dispatch has
	// already refused that combination unless it is inside the namespace.
	if spec.Branch != "" && source.Kind == "repo" {
		if err := m.runner.Fetch.CreateBranch(ctx, layout.Repo, spec.Branch); err != nil {
			send("run.failed", map[string]any{
				"error_code": "RUN_INTERNAL_ERROR",
				"message":    "could not create the run's branch",
			})
			_ = runner.MarkFinished(layout, "failed", time.Now())
			return
		}
		_ = m.runner.Fetch.SetCommitTrailers(ctx, layout.Repo, runID, offer.CardRef)
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
	// **The child's environment gets the `env` secrets and never the git ones** (D5).
	// The isolation overrides are appended after, so `HOME` points inside the run
	// directory only when this run actually received a platform credential.
	childEnv := append(secrets.ChildEnv(os.Environ()), isolation...)
	cmd := runtime.BuildRunCommand(rt, runtime.RunOptions{
		Dir: layout.Repo, Context: spec.Context, Env: childEnv,
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

	startedAt := time.Now()
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

	// **The platform's own checks, after the agent and before the summary.** The
	// ordering is a decision: a check that formats or builds leaves its own marks in
	// `git status`, and hiding a verification step's side effects would make the
	// evidence disagree with the diff for reasons nobody could see (ADR 0033 §3b).
	//
	// The commands were assembled by Central from two platform-side stores; nothing in
	// a request payload names one, and declaring one on a card takes `task.approve`,
	// which a run token never holds. That is what the exit codes below are worth.
	var verification []runner.CheckResult
	if checks := runner.DecodeChecks(spec.AllowedVerificationCommands); len(checks) > 0 {
		send("run.progress", map[string]any{"phase": "verifying"})
		verification = runner.RunChecks(ctx, checks, runner.VerifyOptions{
			Dir: cmd.Dir,
			Env: childEnv,
			// What is left of the run's wall clock. The group does not extend it: a run
			// that spent nearly six hours agent-side does not get another fifteen
			// minutes because it also declared checks.
			Remaining: time.Duration(spec.TimeoutSeconds)*time.Second - time.Since(startedAt),
		})
	}

	send("run.progress", map[string]any{"phase": "finishing"})
	summary := m.runner.Inspect(ctx, layout, source.Kind != "none")

	// **The honesty rule, before the token is dropped** (ADR 0031 §7). If the card
	// declared no delivery and the tree changed anyway, that work disappears when the
	// directory is reclaimed and nobody would know it had existed. The upload uses the
	// same endpoint and the same credential `cliora task attach` uses.
	//
	// A failure here does not fail the run — but it is **said out loud** in the
	// summary, because an artifact that silently failed to attach is the exact thing
	// this rule exists to prevent.
	summaryText := runner.SummaryText(offer.Delivery, summary)

	// **The platform's only remote write.** The five hard constraints live inside
	// `Push`, and they hold whichever credential is in use — they constrain *what* is
	// pushed (ADR 0031 amendment A2). On the default deployment that credential is the
	// machine's own, which the platform can neither manage nor revoke; the constraints
	// are what still applies there.
	//
	// The platform does **not** commit on the agent's behalf. With nothing committed
	// there is nothing to push, and the honesty rule below takes over — deciding what
	// counts as a commit is not the platform's to make.
	pushedBranch := ""
	if spec.Branch != "" && offer.Delivery == "branch" && source.Kind != "none" {
		hasCommits, checkErr := m.runner.Fetch.HasCommitsToPush(ctx, layout.Repo)
		switch {
		case checkErr != nil || !hasCommits:
			summaryText += fmt.Sprintf(" 沒有可推送的提交，因此分支 %s 未建立於遠端。", spec.Branch)
		default:
			pushErr := m.runner.Fetch.Push(ctx, gitfetch.PushOptions{
				Dir:        layout.Repo,
				Branch:     spec.Branch,
				RemoteURL:  spec.Source.URL,
				BaseBranch: spec.Source.Ref,
			})
			if pushErr != nil {
				// A push failure does not fail the run — the work is still in the
				// directory and the diff can still be attached — but it is said out
				// loud, because a wrong "pushed" is far harder to diagnose than a
				// "not pushed". The message goes through the redactor with everything
				// else: git's stderr is the likeliest place a credential surfaces.
				summaryText += " ⚠ 分支未能推送：" + pushErr.Error()
			} else {
				summaryText += fmt.Sprintf(" 已推送分支 %s。", spec.Branch)
				// **A fact, not an intention.** Central composed this name and could
				// recompute it; only this daemon knows the push succeeded, and a pull
				// request may only be opened on a branch that is really there
				// (ADR 0031 amendment B4).
				pushedBranch = spec.Branch
			}
		}
	}

	if runner.ShouldAttachDiff(offer.Delivery, summary) {
		uploader := runner.Uploader{
			APIBase:    runner.APIBaseFromWebsocketURL(m.cfg.Server.URL),
			Credential: spec.Credential,
		}
		name := fmt.Sprintf("changes-%s.patch", runID)
		if _, err := uploader.AttachDiff(ctx, name, summary.Diff,
			"本卡宣告不交付，但工作目錄有變更；這是那份變更的 diff。"); err != nil {
			slog.Warn("could not attach the run's diff", "run_id", runID, "error", err)
			summaryText += " ⚠ diff 未能附加為產物；那份變更只存在於這台機器上，而執行目錄有保留期。"
		}
	}
	_ = runner.DropToken(layout)

	if pumpErr != nil {
		_ = runner.MarkFinished(layout, "failed", time.Now())
		send("run.failed", map[string]any{
			"error_code": pumpErr.Error(),
			"message":    "the run was stopped by the daemon",
			"summary":    summaryText,
			"disk_bytes": summary.DiskBytes,
		})
		return
	}
	if outcome.ExitCode != 0 {
		_ = runner.MarkFinished(layout, "failed", time.Now())
		send("run.failed", map[string]any{
			"error_code": outcome.ErrorCode,
			"message":    "the runtime exited non-zero",
			"summary":    summaryText,
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
	complete := map[string]any{
		"result":           result,
		"summary":          summaryText,
		"disk_bytes":       summary.DiskBytes,
		"git_remotes":      summary.Remotes,
		"unpushed_commits": summary.UnpushedCommits,
		"untracked_files":  summary.UntrackedFiles,
		"pushed_branch":    pushedBranch,
	}
	if len(verification) > 0 {
		// Omitted when empty rather than sent as `[]`: an empty array is
		// indistinguishable from "neither store declared a check", and that is what
		// absence already means.
		//
		// **`CheckPayload` rather than the slice itself**: the redactor recurses through
		// maps and `[]any` and returns anything else untouched, so a typed slice here
		// would carry a command's output verbatim past it (`runner.CheckPayload`).
		complete["verification"] = runner.CheckPayload(verification)
	}
	send("run.complete", complete)
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

// prepareGitCredentials turns the delivered git secrets into a Fetcher that can use
// them, without either value ever reaching a file.
//
// **Only ever called when a git secret was actually delivered**, which on the default
// deployment is never: `CLIORA_GIT_SECRET_DELIVERY_ENABLED` is a Central setting, and
// with it off `spec.secrets` carries no git kind. The daemon therefore has no flag to
// read — it reacts to what it was handed, which is the shape that cannot drift out of
// step with Central.
//
// A failure here is logged and the base Fetcher is returned rather than failing the
// run: the machine may still have its own credentials, and refusing to try would turn a
// missing `ssh-agent` into a failed card.
func (m *Manager) prepareGitCredentials(
	ctx context.Context, layout runner.Layout, secrets runner.Secrets, base gitfetch.Fetcher,
) (gitfetch.Fetcher, *gitfetch.Agent) {
	fetch := base
	var agent *gitfetch.Agent
	if token, ok := secrets.Git["git_pat"]; ok {
		path, err := gitfetch.WriteAskpass(layout.Cliora)
		if err != nil {
			slog.Warn("could not install the credential helper", "error", err)
		} else {
			// The helper itself contains no secret; the value travels in the
			// environment of the git process and nowhere else.
			fetch.AskpassPath = path
			fetch.Password = token
		}
	}
	if key, ok := secrets.Git["git_ssh_key"]; ok {
		started, err := gitfetch.StartAgent(ctx, layout.Cliora, key)
		if err != nil {
			// Never the key, and never ssh-add's stderr verbatim.
			slog.Warn("could not load the run's ssh key", "error", err)
		} else {
			agent = started
			fetch.AuthSock = started.SocketPath()
		}
	}
	return fetch, agent
}
