# ADR 0004: P0 recovery strategy

Status: accepted (2026-07-22); cross-process recovery blocker closed by ADR 0012 (2026-07-24). The exit-code approximation noted below is superseded by ADR 0013 (P2 queries `#{pane_dead_status}`).

Browser and Central restarts never stop tmux. The daemon reconnects outbound and scans only names matching `cliora-<canonical lowercase UUID>`. Reattach captures the latest bounded pane, marks truncation, sends `continuity=snapshot`, then a `reattach_boundary` gap before live output. This is honest continuity, not exact replay.

In-process reattach (browser refresh against a live daemon) is covered by `daemon/internal/session` integration tests: the prior PTY attach is detached, `attach-session -d` evicts any lingering client, and the tmux session/Fake CLI survive. Cross-process daemon-restart recovery remains the open spike recorded in `docs/p0-report.md`.

Process exit is surfaced as a `terminal.exited` event when the Fake CLI ends (via EOF/`:exit`). The reported `code` is the exit status of the `tmux attach-session` client, not the runtime's own exit code, because tmux does not propagate the pane process status to the attach client. P0 treats the event (session ended) as the contract; faithful runtime exit codes require querying `#{pane_dead_status}` before the session is reaped and are deferred to a later phase.

P1 must add authenticated durable session ownership and local reconciliation metadata. Sequence-based lossless replay remains a P2 decision.
