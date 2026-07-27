# P1 — Node Control Plane: Go / No-Go report

**Phase:** P1 (Node Control Plane) · **Status:** ⏳ Conditional — local backend, PostgreSQL, frontend and Chromium/Firefox gates pass; **No-Go until CI/OS-matrix/WebKit are green.**

## Outcome

The P1 vertical is substantially implemented and locally verified: durable PostgreSQL data layer, real auth + RBAC, enrollment tokens, revocable node credentials, outbound-WSS daemon credential handshake, Central-computed node status, the one-line installer + `agentd` lifecycle, and the Vue node-control UI. The remaining release work is executing the real-runner gates (multi-OS systemd install matrix, WebKit, updated CI workflow).

## What was verified locally

| Area | Evidence |
| --- | --- |
| Backend unit (hermetic) | `pytest` 73 passed, 32 DB-skipped; ruff + mypy clean |
| Backend DB-backed | PostgreSQL 16: upgrade → create Admin → downgrade base → upgrade OK after fixing role-seed rollback; `pytest tests/db` **32 passed** |
| Admin bootstrap | `python -m app.bootstrap create-admin` idempotent (`created`→`unchanged`); password verify + refresh-revocation tested |
| Daemon | `go build`, `go vet`, and `go test -race ./...` green with Go 1.26.5 |
| Installer contract | download → SHA256 verify → extract → `agentd version` end-to-end against a local artifact server; checksum-mismatch aborts; `agentd doctor` diagnoses unreachable-Central / bad-root / missing-credential |
| Artifact endpoints | `/api/downloads/{file}` + `/api/install-script`: allowlisted, path-traversal-proof, 404 when unconfigured (7 tests) |
| Frontend | format, lint, typecheck, production build; **58 unit tests**; Chromium/Firefox smoke **8 passed** and full-stack login→nodes→enrollment **4 passed** |

## Measured parameters (as configured)

- Enrollment token: TTL 1 h, `max_uses` 1, plaintext shown once (hash-only at rest).
- Node credential: Ed25519; daemon private key is generated locally and stored `0600`, Central stores only the public key. Each WSS connection signs a fresh 32-byte nonce bound to node id and challenge id. Legacy credentials are revoked by migration 0003 and must re-enrol.
- JWT: access 15 min, refresh 14 d (revocable via `token_version`); browser ws-ticket TTL 60 s.
- Node status (monotonic since last heartbeat): Online ≤ 30 s, Degraded 31–90 s, Offline > 90 s, Disabled by admin. Heartbeat 10 s.
- Reconnect backoff ladder `[1s, 2s, 5s, 10s, 30s]` + ≤ 250 ms jitter; graceful shutdown sends `node.shutdown`.

## Exit-gate checklist

Legend: ✅ implemented + locally verified · ◐ implemented, gate runs in CI / on VM runners (not executable in this sandbox).

**Functional**
- ◐ Admin creates a one-time token and installs a non-root daemon with one command — installer + UI + bootstrap done; full systemd install verified only in the OS matrix.
- ✅ Daemon verifies checksum, writes `0600` config/credential, authenticates over WSS, `node.register`, heartbeats 10 s — Ed25519 nonce challenge path is tested.
- ✅ Central computes Online/Degraded/Offline/Disabled and Claude/Codex state; disable node + revoke credential.
- ✅ Deploy/diagnose/observe the control plane without any terminal-session feature (`agentd doctor`).

**Contract & security**
- ✅ Shared v1.1 fixtures pass across Python/Go/TS; forbidden-field / naive-time / bad-arch rejected (contract tests).
- ✅ Enrollment expiry / replay / over-use / concurrency / post-revoke rejected and audited (DB tests).
- ✅ Credential revoke disconnects and rejects re-auth; disabled node stays connected but rejects new ops.
- ✅ HTTP + browser ws-ticket + daemon Ed25519 success/failure/replay paths tested; no secret/token in logs/audit.
- ✅ Production forces WSS + TLS verify; `ws://` only behind an explicit dev flag (config validation).

**Data & reliability**
- ✅ Alembic clean upgrade / rerun / downgrade; transaction rollback leaves no partial write; tz-aware round-trip + expiry boundary.
- ✅ `go test -race ./...` green; pytest no pending-task/leak; duplicate-connection / late-response / timeout cleanup covered.
- ◐ Central-restart re-connect + re-register — daemon reconnect/re-register logic + tests present; full restart path in integration.

**Engineering baseline**
- ◐ Clean checkout bootstraps (incl. DB), migrates, builds, tests, runs — `make bootstrap/migrate/create-admin/test-db/check` provided; end-to-end on a clean runner is the CI gate.
- ◐ CI gates green, artifacts traceable to commit — `.github/workflows/p1.yml` added (backend-DB, daemon cross-arch + checksums, install-smoke, security); first run needs validation.
- ✅ `research/01/06-requirement-traceability.md` updated with actual local evidence and explicit external blockers.

## Adopted ADRs

0007 (auth), 0008 (node credential + protocol), 0009 (data layer), 0010 (status timing), 0011 (installer). 0006 (auth handoff) is accepted and superseded for the control plane by 0007/0008.

## Gaps found and closed / open

- **Closed:** no production admin-bootstrap existed (only test helpers) — added `app.bootstrap` CLI + tests. Without it a fresh deployment could not sign in.
- **Closed:** Alembic role-seed downgrade failed once an Admin referenced the role; downgrade now preserves stable roles until the base schema is dropped, and CI creates a user before rollback.
- **Closed:** Playwright specs were outside the frontend package, lacked a base URL, raced login navigation, and leaked into Vitest discovery; all four issues are fixed.
- **Closed:** requirement traceability now links actual evidence; ADR 0006 is accepted and superseded by ADR 0007/0008.

## Limitations (why this is not yet a Go)

The remaining external or unresolved gates are:
1. **OS install matrix** — Ubuntu 22.04/24.04 + Debian 12 × amd64/arm64 with real systemd. This host has no root/systemd matrix.
2. **Browser E2E matrix** — Chromium/Firefox smoke and full-stack login→nodes→enrollment pass locally. WebKit is blocked here by system packages requiring sudo; CI installs them.
3. **CI workflow** — PostgreSQL rollback-with-data, frontend quality, full-stack three-browser, daemon race/cross-arch, artifact and security jobs are wired but do not yet have a confirmed remote green run.

## P2 follow-ups

- Close the **P0 recovery blocker** (leftover tmux attach client blocks recovered reattach) via an independent spike **before** P2 starts; P1 reconnect/re-register must not depend on terminal reattach.
- Terminal session lifecycle, workspace browsing, and 500-WS terminal scale (deferred from P1).
- `agentd update` self-update/rollback (P4 stub today).

## Recommendation

**No-Go for formal P1 exit:** flip to Go only after `p1.yml`, WebKit, and the OS install matrix are green. No exemptions for the auth, enrollment, migration, redaction, or race gates.
