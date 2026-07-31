# P2 — Session & Terminal: Go / No-Go report

**Phase:** P2 (Session & Terminal) · **Status:** ⏳ Conditional — the full local stack is green and the previously-missing exit-gate artifacts (the `p2` CI workflow, the Playwright full-stack E2E, and the latency/scale harness) are now authored and verified locally (E2E green against a real stack). **The one remaining step for Go is running `.github/workflows/p2.yml` on an actual GitHub runner (a push).**

## Outcome

The P2 vertical is implemented end to end and locally verified: a session created over `POST /api/sessions` launches a real tmux CLI on the node and streams live terminal output to the browser over an authenticated WebSocket; browser refresh / short disconnect reattach without killing the session; a single writer holds input while others view read-only, with authorised takeover; terminate stops the CLI and the state machine reflects `running`/`exited`/`terminated`. Terminal bytes never touch the database or logs.

## Tickets

| Ticket | Result |
|---|---|
| P2-01 Gate-0 recovery | ✅ P0 blocker closed; regression suite (teeth-verified, `-race`); ADR 0012 |
| P2-02 decision ADRs | ✅ ADR 0012 + 0013; ADR 0004 updated |
| P2-03 protocol v1.2 | ✅ evolved `session.start`, new session/terminal types + WORKSPACE_*/SESSION_* codes; 3-language contract |
| P2-04 data + RBAC seed | ✅ migrations 0005/0006; rollback-verified |
| P2-05 session domain | ✅ state machine + service; 15 tests |
| P2-06 session HTTP API | ✅ full CRUD + attach ticket; first `registry.request()` caller |
| P2-07 daemon lifecycle | ✅ workspace guard + dispatch in production link; real tmux round-trip |
| P2-08 reconcile | ✅ `session.status_changed` on exit → Central applies |
| P2-09 terminal relay | ✅ node-WS binary routing + relay hub + browser endpoint; daemon streams verified |
| P2-10 writer/viewer/takeover | ✅ server-side writer marker, viewer input dropped, takeover (RBAC) |
| P2-11 sessions list + dialog | ✅ dependent Node→runtime→workspace selects, error mapping |
| P2-12 session workspace route | ✅ 3-column layout, header status/reconnect/terminate. **Not disclosed at the time: the left Sessions rail was placeholder text with no list and no switching, and the drag/collapse behaviour was never built. Both were withdrawn from the specs and removed in plan/08 (WT-01), which also moved the centre pane to tabs.** |
| P2-13 xterm composable | ✅ ws-ticket + session WS, raw bytes, resize, gap/exit, dispose; leak gate |
| P2-14 writer/viewer UI | ✅ role indication (not colour-only) + takeover control |
| P2-15 audit + observability | ◐ session create/attach/takeover/terminate/failed audited; metrics infra minimal (relay/queue stats only) |
| P2-16 verification | ◐ local matrix green; CI + E2E + latency/scale pending real runners |

## What was verified locally

| Area | Evidence |
|---|---|
| Daemon | `gofmt`/`go vet` clean; `go test -race ./...` green; `go test -tags integration -race ./internal/{session,connection}` green (tmux 3.4) |
| Recovery gate | `internal/session/recovery_test.go`: live-orphan eviction (no leaked client), rapid reattach ×20, post-recovery stop; teeth-verified by removing `-d` |
| Daemon terminal | `internal/connection/connection_integration_test.go`: real `session.start → started → attach → Fake CLI banner streamed (binary) → stop → stopped` |
| Backend | `ruff` + `mypy` clean; `pytest` **161 passed** (hermetic + PostgreSQL 16 DB); contract 42 |
| Session domain/API | state machine, guards (offline/disabled/runtime/workspace/limit), idempotency/rollback, HTTP RBAC (Admin/Developer/Viewer), NODE_OFFLINE, attach-ticket |
| Relay | `test_terminal_relay.py`: writer/viewer election, fan-out, takeover, unsubscribe-releases-writer |
| Frontend | typecheck + lint + prettier clean; **78 unit tests** (incl. terminal composable leak gate); production build ok; contract 41 |

## Measured parameters (as configured, ADR 0013)

- Sessions per node: 10 · start/stop/attach/list timeouts: 30/20/15/15 s · terminate graceful: 10 s · writer hold window: 30 s (client-side) · reattach snapshot: 2 MiB (chunked 32 KiB) · terminal queue: 4 MiB / 1024 frames · reconnect backoff 1/2/5/10/30 s + jitter.

## Contract & security

- `session.start` carries only runtime id + workspace + name + size — never a command/argv/shell string; `additionalProperties:false` enforced across Python/Go/TS.
- Runtime launch binary resolved from the allowlist only (`runtime.ResolveBinary`); workspace canonicalised (symlink-resolved containment) before launch.
- Terminal WS authorised by single-use ws-ticket bound to (user, session); viewer/forged input dropped server-side.
- Terminal bytes never persisted to DB or logs (ADR 0004); session create/attach/takeover/terminate/failed audited with metadata only.

## Exit-gate artifacts delivered (2026-07-25)

The three authorable exit-gate items below were the No-Go blockers; all are now
in-tree and verified locally (details in `plan/03/09-implementation-status.md` §3):

1. **CI** — `.github/workflows/p2.yml` adds `backend-db`, `daemon` (vet + `-race`
   + `-tags integration` + amd64/arm64 build, tmux installed on the runner),
   `contract` (Python/Go/TS), `security` (ws-ticket/relay/session), `frontend`,
   `browser-e2e`, and `performance`. Every job's core command was run green
   locally; the only residual is the first green run on an actual GitHub runner
   (needs a push).
2. **Browser E2E** — `frontend/tests/e2e/session.spec.ts` (login → New Session →
   live terminal → refresh reattach → terminate), gated like `nodes.spec.ts` and
   self-skipping its interactive half when no online node is present. It runs
   **green against a real full stack** (Central + a rootless-enrolled daemon node
   whose `claude` runtime is the Fake CLI) brought up by `scripts/e2e/run-stack.sh`
   (new `daemon/cmd/enroll-dev`; `fakecli --version` added for runtime detection).
3. **Performance/scale** — `backend/perf/relay_bench.py` (`make perf`) measures the
   real relay hot path: single-subscriber p99 ≈ 2 ms, 500-WS fan-out (NFR-003)
   p99 ≈ 98 ms (< 200 ms), 16 MiB slow-consumer burst bounded (4 MiB/1024 frames)
   with exactly one `terminal.gap` and flat RSS; non-zero exit on regression.
   Note this measures the Central relay component; true browser→daemon→tmux→back
   latency still needs a metered full-stack run.

## Remaining limitation

- **Observability** — structured terminal/queue/timeout metrics beyond the
  in-memory `BrowserChannel` stats are not yet exported (P2-15 partial; full
  metrics fit with P4).

## Adopted ADRs

0012 (recovery/attach model), 0013 (session lifecycle, writer/takeover, limits). 0004 updated to reflect closure.

## P3 follow-ups

- Workspace file tree, filename search, read-only Monaco preview (depends on the P2 session context now in place).
- `session.list`/`session.recover` daemon cases for full daemon-restart reconciliation (status_changed covers exit today).
- `workspace_favorites` / recent-workspace (FR-WORKSPACE-004/005).

## Recommendation

The `p2` CI workflow, the Playwright full-stack E2E, and the latency/scale harness are now authored and green locally (E2E against a real stack; harness with real numbers). The only remaining step for formal P2 exit is executing `.github/workflows/p2.yml` on an actual GitHub runner (a push) and confirming the matrix — including WebKit — green there. No exemptions for the recovery gate, terminal-WS authentication, viewer-input rejection, command-injection/path-escape guards, migration rollback, or race gates — all of which pass locally today.
