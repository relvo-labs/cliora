# ADR 0006: P1 authentication handoff

Status: accepted (2026-07-24) — superseded for the P1 control plane by ADR 0007 and ADR 0008

P0 fixed identities and bearer credential are enabled only by an explicit development flag and fail closed in production. P1 must replace these with authenticated browser sessions plus resource authorization and revocable, rotated daemon credentials over WSS. Credentials must never use query strings or logs.

---

**Superseded by ADR 0016 (2026-07-25); the removal landed in P4-07 (2026-07-25).**
The P0 development relay this ADR governs
(`/ws/p0/daemon`, `/ws/p0/sessions/{id}/terminal`, `app/relay/*`, the shared static
`p0_token`) was fully replaced by the P2 relay (`services/terminal_relay.py` +
`api/ws/terminal.py`). It is removed in P4-07: "disabled in production" is a weaker
property than "absent", and it was the only WebSocket endpoint authorized by a shared
static token. The documented development path becomes `scripts/e2e/run-stack.sh`
(Central plus a real rootless-enrolled daemon node).
