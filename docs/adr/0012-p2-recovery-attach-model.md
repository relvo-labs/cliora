# ADR 0012: P2 recovery / attach model

Status: accepted (2026-07-24); closes the P0 recovery blocker (No-Go item in `docs/p0-report.md`).

## Context

P0 exited No-Go on one item: after a browser/daemon interruption a lingering `tmux attach` client was reported to block the recovered reattach, and `attach-session -d` / `detach-client` / non-blocking PTY cancel were said to remain reproducible. P1 required this be closed by an independent spike before P2 (ticket P2-01, Gate-0).

## Spike outcome

The blocker is **resolved by the attach model already in `daemon/internal/session/manager.go`**: on every attach the manager (a) detaches the previous in-process `terminal.Process` for reattach, and (b) runs `tmux attach-session -d -t <name>` in a fresh PTY, whose `-d` evicts any other client — including a fully-alive competing client left by a dead daemon. No new attach architecture was needed; the **tmux control-mode pipe bridge alternative is deferred** (not required for the MVP recovery guarantee).

Reproduction and regression evidence live in `daemon/internal/session/recovery_test.go` (`-tags integration`, skipped without tmux):

- `TestRecoveredReattachEvictsLiveOrphan`: a fresh (cross-process) manager recovers a session that has a fully-alive competing attach client; asserts the attach does not block, the Fake CLI banner survives, **exactly one** live client remains (`tmux list-clients`), and post-recovery `Stop` completes.
- `TestRapidReattachChurn`: 20× reattach with no block and no client leak.
- The invariant has teeth: removing `-d` makes the orphan leak (2 clients) and the test fails.

All pass under `go test -tags integration -race ./internal/session`.

## Exit-code fidelity

Per ADR 0004, P0's `terminal.exited.code` is the `tmux attach` client's status, not the runtime's own exit code. P2 will query `#{pane_dead_status}` before the session is reaped to report the runtime's real exit code (see ADR 0013 §exit-code). Until wired, the attach-client status remains a documented approximation.

## Consequences

- P2 may proceed past Gate-0. `manager.go`'s Detach + `-d` eviction is the sanctioned recovery mechanism; the regression suite guards it.
- Snapshot continuity stays "honest, not exact": reattach captures a bounded (≤2 MiB) `capture-pane` snapshot, marks `truncated`, and emits `terminal.gap{reattach_boundary}` when truncated (ADR 0004, unchanged).
- Control-mode bridge remains an option if a future requirement (e.g. lossless sequence replay) needs it; revisit then.
