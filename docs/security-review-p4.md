# Security review — P4 (MVP release gate)

Sign-off against the fifteen baselines in tech §23, plus the attack suite and dependency
scans required by `research/01/05` §P4-W6.

**Evidence rule.** Every row names a test, a file, or a drill artifact. "Implemented" is
not evidence — it is the claim the evidence is supposed to support. Where a baseline is only
partly covered, the row says so and the gap appears in [Findings](#findings) rather than
being smoothed over in prose.

The point of doing this item by item is that it finds things. It found two here: a missing
per-user session cap (#14) and an unbounded connection after terminal-queue overflow (#15).
Both are fixed in this phase; both are recorded below with what let them survive.

---

## 1. Fifteen baselines

| # | Baseline | Verdict | Evidence |
|---:|---|---|---|
| 1 | HTTPS / WSS only | **pass** | `deploy/nginx/nginx.conf`: port 80 returns 301 (ACME path excepted); TLS 1.2+ only; HSTS, CSP with no external origin, `X-Frame-Options: DENY`. `Settings.reject_dev_secrets_in_production` refuses production startup on dev secrets (`backend/tests/test_settings.py::test_development_secrets_fail_closed_in_production`). **Executed, not reviewed:** `scripts/p4/verify-edge.sh` makes 25 assertions over the wire against the real nginx image using the shipped config — 301, every security header on both the HTML page and a hashed asset, the CSP's load-bearing clauses, `/api/metrics` refused at the edge, and an authenticated idle WebSocket surviving past 60 s. It found three defects review had missed; see [Observation 2](#observation-2-the-edge-is-now-executed). |
| 2 | Daemon not long-running as root | **pass** | `config.EnsureNonRoot()` called from `daemon/cmd/agentd/run.go`; `User=` in `internal/install/systemd.go`; `agentd doctor` reports the running user; P4-10's update requires privilege *at the moment of the swap* and refuses otherwise (`daemon/internal/update/update.go`, privilege gate first). |
| 3 | Enrollment token single-use or time-limited | **pass** | `backend/tests/db/test_enrollment_api.py` — expiry, `max_uses` exhaustion, explicit revoke, and reuse after exhaustion all refused. |
| 4 | Node secret never stored in plaintext centrally | **pass** | Migration `0003_ed25519_node_credentials` stores a public key only; the private key is generated on the node and never transmitted. `backend/tests/db/test_node_credentials.py`. Verified independently against a real dump by `scripts/p4/backup-restore-drill.sh` (no private-key headers). |
| 5 | Workspace re-validated on every operation | **pass** | Central: `services/sessions.authorize_workspace` (prefix, with `relative_to` so `/a/projects-other` is not inside `/a/projects`). Daemon: `internal/workspace/root.go` + `FuzzOpenFile` (`root_test.go`). P4-13 favourites reuse the *same* Central function rather than a copy — `backend/tests/db/test_favorites_api.py::test_a_prefix_collision_is_not_treated_as_a_root`. |
| 6 | Symlinks resolved | **pass** | `daemon/internal/workspace/root_test.go` — chains, swap-after-check, broken links, and escape via symlink all refused; `os.Root` containment. |
| 7 | Frontend cannot send arbitrary commands | **pass** | Contract schemas are `additionalProperties: false` and carry no argv, no shell string, no URL, no path: `contracts/v1/schemas/`, round-tripped in all three languages by `backend/tests/contract/test_contract.py`. `daemon.update` takes a version string only, validated against a closed regex (`services/node_update.py`). |
| 8 | Terminal content never written to logs | **pass** | P2/P3 log assertions; `backend/tests/test_audit_redaction.py`; metrics label allowlist (`app/metrics.py`, `FORBIDDEN_LABELS`); and the dump scan in `scripts/p4/backup-restore-drill.sh`, which is the only check performed on the artifact that actually leaves the building. |
| 9 | Sensitive files not previewable by default | **pass** | `daemon/internal/files/files_test.go::TestReadPolicyMatrix`, plus the regression test for the P3 defect where the installer's default policy differed from the code's. |
| 10 | Session create / takeover / terminate audited | **pass** | `backend/tests/db/test_audit_coverage.py` — one row per event, no duplicates (`test_successful_login_writes_exactly_one_row` is the pattern), metadata forbidden-key list enforced. |
| 11 | WebSocket identity and permission checks | **pass** | Daemon socket: Ed25519 challenge–response, single-use nonce (`app/api/ws/nodes.py`). Browser socket: single-use ws-ticket bound to (user, session), **plus** a resource-scope re-check at handshake and again on every inbound frame, so a demotion mid-session takes effect on the next keystroke (`app/api/ws/terminal.py`). |
| 12 | Binary downloads checksum-verified | **pass** | `deploy/install.sh`, `daemon/internal/install/verify.go`, and P4-10's update path: `parse_checksums` is fail-closed (`services/releases.py`), and a mismatch triggers rollback rather than a swap (`daemon/internal/update/update_test.go`). |
| 13 | Daemon config / credential files 0600 | **pass** | `daemon/internal/config/config.go` and `credentials.go` write 0600; the update staging root requires 0700; `agentd doctor` checks and reports both. |
| 14 | Per-user **and** per-node session limits | **pass (gap found and closed in P4)** | Per-node: `sessions_per_node_max` (P2). Per-user: `sessions_per_user_max` — **added in this phase**, see [Finding 1](#finding-1-no-per-user-session-cap). `backend/tests/db/test_sessions_api.py::test_a_user_is_capped_across_the_whole_fleet`. |
| 15 | Terminal queue and frame size bounded | **pass (gap found and closed in P4)** | Byte- and frame-bounded `BrowserChannel` (`services/terminal_queue.py`); contract frame ceiling; and the live proof in `scripts/p4/load/terminal_clients.py` (`slow_client_queue_bounded`, `slow_client_gets_exactly_one_gap`, `slow_client_is_disconnected`). The disconnect half was **not** happening — see [Finding 2](#finding-2-connection-left-open-after-queue-overflow). |

---

## 2. Attack suite

| Attack | Result | Evidence |
|---|---|---|
| Stolen / expired token | 401. Expired access token and a logged-out refresh token are rejected (`test_logout_invalidates_refresh_token`); a ws-ticket is single-use and bound to (user, resource), so another user's ticket does not authorise a connection (`test_ws_ticket_single_use_and_resource_bound`); a password rotation bumps `token_version`, invalidating that user's outstanding refresh tokens (`test_bootstrap.py`). | `backend/tests/db/test_auth_api.py`, `backend/tests/test_security.py`, `backend/tests/db/test_bootstrap.py` |
| Replay | Refused. Enrollment token past `max_uses`, a reused challenge id, and a consumed ws-ticket all fail. | `backend/tests/db/test_enrollment_api.py`, `backend/tests/db/test_node_ws.py`, `backend/tests/test_security.py` |
| Forged frames | Dropped or refused, with no state change and no hang. A daemon socket sending a user-level mutation, a browser sending a daemon-only type, unknown types, oversized frames (explicit `FRAME_TOO_LARGE`, not a hang), illegal binary kinds, and a forged or late `request_id` are all handled. | `backend/tests/test_correlation.py`, `tests/contract/test_contract.py`, `app/protocol/codec.py` |
| Path attacks | Refused at both layers. `..`, relative, prefix collision, NUL, control characters, symlink chain and swap, broken link, non-regular file. Both P4 entry points are covered: favourite paths (`test_favorites_api.py`) and update version strings (closed regex, `services/node_update.py`). | as above + `daemon/internal/workspace/root_test.go` |
| Viewer forged input | Dropped with no side effect, and audited. Binary input from a viewer never reaches the node; every mutation endpoint refuses with a uniform 403 that reveals nothing about existence or ownership. | `backend/tests/test_authz.py`, `tests/db/test_permission_matrix.py`, and the live check `viewer_flood_reaches_no_node` in `scripts/p4/load/terminal_clients.py` |
| WebSocket flood | Bounded. Slow client → queue capped, one `terminal.gap`, connection closed 1013. Flood client → input dropped at Central, so it costs nothing downstream. Excess concurrency → shed with a retryable 503 rather than queued. Other users unaffected (`normal_clients_unaffected`). | `artifacts/p4/local/capacity.json` |
| Log / audit / DB / metrics leakage | Clean. No terminal bytes, file content, search keyword, password, token or private key in Central logs, the audit table, a real database dump, or the metrics output. Metrics labels are allowlisted, which matters because metrics are the only sink with no redaction. | `test_audit_redaction.py`, `test_metrics_export.py`, `scripts/p4/backup-restore-drill.sh` |

**Uniform refusals.** Worth stating separately because it is easy to lose: every
authorization refusal is the same 403 with the same message, and a favourite belonging to
another user answers **404, not 403** — a 403 there would confirm the id exists, turning a
per-user list into an oracle for other users' rows
(`test_deleting_another_users_favourite_is_404_not_403`).

---

## 3. Dependency and artifact scans

| Target | Command | Status |
|---|---|---|
| Python | `pip-audit` against the `uv` lock | run by the `security` job in `.github/workflows/p4.yml` |
| Node (production only) | `npm audit --omit=dev` | same |
| Go | `govulncheck ./...` | same |
| Release artifacts | reproducible-build check: same commit built twice, checksums compared | `daemon` job in `.github/workflows/p4.yml` |

These run in CI rather than being pasted here as a point-in-time result. A dependency
advisory published tomorrow makes a table in a document wrong tomorrow; a CI job catches it.
Findings are triaged by the rule below.

---

## Findings

### Finding 1 — no per-user session cap

**Severity: medium.** tech §23 #14 requires limiting sessions per **user and** per node.
Only `sessions_per_node_max` existed. One account could therefore hold
`nodes x (per_node - 1)` sessions without tripping any limit — with 100 nodes, 900
sessions. A bound that grows with the fleet is not a bound, and this is the shape a
runaway script or a stolen credential takes.

**Resolution:** `sessions_per_user_max` (default 20), checked in `SessionService.create`
against an active count across the whole fleet. Same `SESSION_LIMIT_REACHED` code as the
per-node cap: from the caller's side it is the same situation, and a distinct code would
only tell them which ceiling to work around.

**Why it survived to P4:** every existing test exercised one node. A per-node check passes
a single-node scenario perfectly. The new test asserts the cap **across two nodes**, which
is the only arrangement that can tell the two rules apart.

### Finding 2 — connection left open after queue overflow

**Severity: medium.** On terminal-queue overflow, `pump()` sent `terminal.gap` and
returned — without closing the socket. The browser had its gap notice and would never
receive another byte, while remaining counted in `active_terminal_connections`, remaining
subscribed in the relay, and — if it was the **writer** — holding the writer marker it
could no longer use, so no one else could take over by the normal path. The documented
contract (gap **plus** a 1013 close) was not met.

**Resolution:** the overflow branch now closes with 1013 ("try again later", which is
accurate — the session is still running on the node). Regression coverage:
`slow_client_is_disconnected` in the P4-11 harness, which drives a real non-reading socket
through a real Central, plus structural assertions in
`backend/tests/test_terminal_overflow_close.py`.

**Why it survived to P4:** every existing test asserted the gap was *sent*. None asserted
what happened next. It took a load harness with a genuinely non-reading client to notice —
and that client had to be hand-rolled on a raw socket with a shrunken receive buffer,
because the `websockets` library drains into its own buffer and would have looked like a
healthy reader.

### Observation 1: `pending_requests_max` is unreachable over HTTP

**Severity: none (documented behaviour).** `pending_requests_max` is 128, but
`db_pool_size + db_max_overflow` is 20. A request cannot occupy a pending slot without
first holding a database connection, so the pool ceiling binds first by a wide margin:
excess concurrency is shed with a retryable 503 and the pending bound is never approached
through the HTTP surface.

This is correct behaviour — a bounded wait then a clear answer beats an unbounded queue —
but it means the pending bound's *only* coverage is its own unit test, not the load harness.
Recorded rather than silently accepted, and the harness prints both numbers in its notes so
a future pool increase makes the probe meaningful instead of vacuous.

### Observation 2: the edge is now executed

**Severity: was low as a verification gap; the three defects it uncovered were medium.**

This was originally recorded as "implemented and reviewed, not executed" — honest, but it did
not close anything. `scripts/p4/verify-edge.sh` (CI job `edge`) now brings up the real nginx
image with the shipped config, a self-signed certificate and the real built console in front
of a throwaway Central, and makes **25 assertions over the wire**. Doing so turned three
review-invisible defects into failing assertions. All three read as correct on inspection:

1. **All security headers were absent on the HTML page and the JS bundle.** nginx's
   `add_header` does not inherit into a location that declares its own, and both
   `location /` and `location /assets/` set `Cache-Control`. HSTS, CSP and `X-Frame-Options`
   were dropped on precisely the responses that need them, while the server-level block read
   as though they applied. The set is now repeated per location and asserted in both places.
2. **The CSP was an invalid HTTP/2 header.** It was written across lines with trailing
   backslashes; nginx has no line continuation inside a quoted string, so those characters
   entered the header *value*. curl rejects the whole response (error 92) and so does a
   browser — the page breaks **and** the policy does not apply. Now a single line.
3. **`/api/metrics` was reachable from outside.** `location /api/` is a prefix match, so it
   proxied `/api/metrics` while a comment two lines above claimed the endpoint was
   "deliberately not exposed here". A comment is not a rule; an exact-match `return 404` is.

**The check itself was vacuous at first**, which is worth recording separately. It claimed to
verify that an idle WebSocket survives the proxy — but uvicorn pings every 20 s by default
and each ping resets `proxy_read_timeout`, so it **passed with the timeout set to 20 s**.
Central now runs with the server ping pushed out of the way, and the check is negatively
verified: it fails at exactly 20.0 s against a 20 s timeout and passes at 70 s against the
shipped 3600 s. The invariant is `proxy_read_timeout > ws_ping_interval`, not "greater than a
human pause" — which is what the config's own comment used to assert, and it was wrong.

**Residual:** the certificate is self-signed in the test, so `ssl_stapling` is inert there
(nginx warns and ignores it). Certificate provisioning and stapling remain an operator
concern, documented in `docs/deployment.md`.

---

## Triage rule

Unresolved **Critical** or **High** findings block the release
(`research/01/05` §stage exit). Medium and below are recorded with an owner and a target
phase. Both findings above are **resolved in P4**, so neither blocks.

Full Go/No-Go: `docs/p4-report.md`.
