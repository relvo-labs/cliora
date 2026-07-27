# P0 exit report

Date: 2026-07-22  
Decision: **No-Go (one recovery blocker remains)**

## Implemented

- Reproducible Python/Go/Node toolchains, root tasks, locks, and GitHub Actions gates.
- Protocol v1 schema/fixtures plus Python, Go, and TypeScript codecs; 64 KiB control/binary limits and stable safe errors.
- Deterministic Go Fake CLI, typed UUID-derived tmux operations, PTY byte forwarding, resize, bounded daemon writer, and explicit stop.
- Development-only FastAPI daemon/browser gateways, fixed identities, single writer, bounded browser queue, and production fail-closed setting.
- Vue/xterm lifecycle composable, retry schedule, semantic tokens, Cliora shell, terminal states, token showcase, unit and browser test scaffolding.

## Verified evidence

- Python: Ruff and strict mypy pass; pytest 36 passed (protocol contract, bounded channel, relay routing, settings).
- Go: vet/build pass; `go test -race ./...` passes; tagged `go test -tags integration -race ./internal/session` passes on tmux.
- Frontend: npm audit reports zero vulnerabilities; lint, format, typecheck, 34 unit tests, and production build pass.
- Contract: the Python, Go, and TypeScript consumers all run the same `contracts/v1/fixtures/manifest.json`, with identical accept/reject across 15 JSON and 6 binary golden fixtures.
- Vertical slice (integration test): Fake CLI → tmux → PTY → session manager preserves ANSI escape and UTF-8 bytes, observes resize via SIGWINCH, survives in-process reattach, and emits an exit event on `:exit`.

## Fixes applied during review

- **Central relay routing (correctness):** daemon→browser control frames (`session.attached`, `terminal.gap`, `terminal.exited`) were previously dropped (no correlation was ever registered) and terminal output bypassed the bounded queue entirely. The registry now owns a per-session `BrowserChannel`; a single writer drains control and byte-accounted output in order, and overflow emits `terminal.gap` + close 1013. Covered by `backend/tests/test_relay.py`.
- **Exit signalling:** the daemon now detects Fake CLI exit on the PTY and emits `terminal.exited`; the UI reaches the terminal `exited` state instead of reconnecting forever (see ADR 0004 for the exit-code limitation).
- **Attach gap policy:** `terminal.gap` is now sent only when the reattach snapshot is truncated, so a clean first attach no longer forces the client into manual-retry.
- **Contract hardening:** `protocol.ValidateControl` gates daemon request messages with strict payload decoding, rejecting unknown/forbidden fields and out-of-range sizes to match the schema authoritative validator.
- Removed daemon dead code, made heartbeat report the live session count, and migrated the Python validator off the deprecated `jsonschema.RefResolver`.

## Blocking exit item

After a browser/daemon interruption leaves a tmux attach client behind, a recovered daemon reaches `Exists` and bounded `Capture` but blocks while starting the replacement PTY attach. `tmux detach-client`, `attach-session -d`, and non-blocking local PTY cancellation were tested; the recovered path remains reproducible. The tmux session and Fake CLI stay alive, so data ownership is safe, but refresh/restart recovery and subsequent stop cannot pass the P0 gate.

Next spike: isolate `creack/pty.StartWithSize(tmux attach)` in a process-level integration test, identify the orphan client/process relationship, and choose either a tmux control-mode pipe bridge or an attach subprocess group cleanup strategy. Do not advance to P1 until rapid reattach and daemon restart pass without leaked clients.

## Limits measured

Configured limits match ADR 0003. Queue accounting unit tests prove byte/frame release on overflow and close. The required 16 MiB end-to-end slow-consumer RSS artifact and multi-browser Playwright run remain release-candidate gates.
