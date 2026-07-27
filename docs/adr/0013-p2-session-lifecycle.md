# ADR 0013: P2 session lifecycle, writer policy, and limits

Status: accepted (2026-07-24). Governs Phase 2 (Session & Terminal); confirmed defaults per product decision.

## Session state machine

States (FR-SESSION-002): `STARTING, RUNNING, DISCONNECTED, EXITED, FAILED, TERMINATING, TERMINATED`. Legal transitions:

```
(create) → STARTING
STARTING → RUNNING              daemon session.started
STARTING → FAILED               session.start_failed / start timeout / daemon error
RUNNING → DISCONNECTED          writer hold window expired with no attach client, or daemon transport gap
DISCONNECTED → RUNNING          reattach succeeds
RUNNING|DISCONNECTED → EXITED   daemon terminal.exited (CLI ended)
RUNNING|DISCONNECTED → TERMINATING   user terminate
TERMINATING → TERMINATED        daemon session.stopped / after force kill
(any non-terminal) → FAILED     unrecoverable error (record safe error_message)
```

Terminal states (`EXITED, FAILED, TERMINATED`) are immutable; illegal transitions return `SESSION_INVALID_STATE`. Transition sources are distinct: HTTP mutation, daemon `session.status_changed`/response, and Central monotonic timeout. `DISCONNECTED` (no attach client) is separate from node offline (node-level status).

## Writer / viewer / takeover policy

- The session **owner is the default writer**; at most one writer at a time; all other connections are read-only viewers.
- **Writer hold window: 30 s** (monotonic). Within the window the same user reconnecting resumes writer seamlessly; after it, the writer is released and the session becomes takeover-eligible.
- **Takeover is explicit**: a user holding `terminal.takeover` may acquire control; the server transfers the writer marker, notifies the incumbent (if connected), and writes one audit entry. Incumbent consent is **not** required; no separate admin override is needed beyond the RBAC action.
- Only `terminal.resize` and input frames from the current writer are relayed to the daemon; **viewer/forged input is dropped server-side** (UI hiding never substitutes for this).

## session_connections model

Durable, minimal, for audit and writer/viewer tracking: `id, session_id (FK), user_id (FK), role (writer|viewer), connected_at, last_seen_at, closed_at, close_reason`. No terminal bytes are stored anywhere (ADR 0004).

## Browser terminal WS authentication

`/ws/sessions/{session_id}/terminal` consumes a single-use ws-ticket bound to `(user_id, session_id)` (reuses P1 `WsTicketService`, monotonic TTL 60 s), then enforces session-level RBAC. No long-lived JWT in query string or logs. `ws://` only behind an explicit dev flag.

## P2 limits (configurable; measured, not hard-coded)

| Item | Initial | On breach/timeout |
|---|---:|---|
| Sessions per node | 10 | `SESSION_LIMIT_REACHED` |
| Terminal WS platform-wide | 500 | measured (NFR-003); no unbounded growth |
| session.start / stop / attach / list timeout | 30 / 20 / 15 / 15 s | `REQUEST_TIMEOUT`, clear correlation |
| Terminate graceful wait | 10 s | then force kill |
| Writer hold window | 30 s | release writer |
| Reattach snapshot | 2 MiB | `truncated=true` + `terminal.gap` |
| Control frame | 64 KiB | `FRAME_TOO_LARGE` |
| Per-node pending requests | 128 (P1) | `NODE_BUSY` |
| Reconnect backoff | 1/2/5/10/30 s + ≤250 ms jitter | reset on success |

## exit-code fidelity

P2 queries tmux `#{pane_dead_status}` before reaping to report the runtime's real exit code in `terminal.exited.code`; if unavailable, fall back to the attach-client status and mark it as an approximation (supersedes the P0 limitation in ADR 0004).

## Scope

MVP uses tmux scrollback for reattach snapshots (no daemon ring buffer). `workspace_favorites` / recent-workspace (FR-WORKSPACE-004/005) and arbitrary launch args/env are out of P2 scope.
