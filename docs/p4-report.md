# P4 report — MVP release gate

P4 is the **last** phase. Per `plan/05/00-execution-plan.md` §8, "defer to the next phase"
is not an available disposition here: anything not fixed has to be written down as an
explicit release decision. That is what §4 and §5 of this document are for.

---

## 1. Go / No-Go

**Recommendation: Go**, subject to the conditions in §5.

Nothing in the blocking categories is outstanding. Two defects that *would* have blocked
were found during this phase and fixed (§3). What remains is a set of verification gaps —
places where a property is implemented and reviewed but not exercised by an automated
check — each listed in §4 with what it would take to close.

The honest summary: every claim about Central, the daemon protocol, authorization, auditing,
bounds, the console **and now the edge** is backed by an executed test. What remains
unverified is the set in §4 — chiefly things that need a host this one is not (systemd, a
real enrolled node, a GitHub runner).

§4.1 is worth reading even though it is closed: executing the edge config found three
defects that reviewing it had missed, and disproved the gap's own stated premise.

---

## 2. PRD §19 — the twenty acceptance conditions

| # | Condition | Status | Evidence |
|---:|---|---|---|
| 1 | Admin can generate an install token | pass | `backend/tests/db/test_enrollment_api.py`; E2E enrollment flow |
| 2 | One-line daemon install | pass | `deploy/install.sh`; `daemon/internal/install/` tests |
| 3 | Daemon auto-starts and registers | pass | `internal/install/systemd.go`; `tests/db/test_node_registration.py` |
| 4 | Node online/offline shown | pass | `services/registry.compute_status` (derived from the heartbeat gap, never self-reported); `tests/test_registry.py`; dashboard E2E |
| 5 | Claude / Codex availability shown | pass | `tests/db/test_node_api.py`; runtime detection in `internal/runtime/` |
| 6 | User can select a node | pass | `NewSessionDialog.vue` + its tests |
| 7 | User can switch runtime | pass | as above; `_require_runtime` refuses an unavailable one |
| 8 | User can browse workspace roots | pass | `tests/db/test_files_api.py`; `FileTree.test.ts` |
| 9 | User can specify a legal working directory | pass | `authorize_workspace` (prefix, collision-safe) + daemon `os.Root`; `FuzzOpenFile` |
| 10 | Daemon starts the CLI in that directory | pass | `daemon/internal/session/` integration (real tmux) |
| 11 | Web terminal fully operates the CLI | pass | P2 relay + E2E terminal interaction |
| 12 | Native approval screens display and work | pass | raw PTY passthrough — no interpretation layer exists to break it (ADR 0004); E2E |
| 13 | Closing the browser does not end the session | pass | `tests/test_session_state.py`; E2E close-and-check. **Also now true of a Central restart** — see §3 |
| 14 | User can reattach to a running session | pass | reattach snapshot + `tests/db/test_sessions_api.py`; E2E |
| 15 | User can view the workspace tree | pass | `tests/db/test_files_api.py`; `FileTree.test.ts` |
| 16 | Read-only preview of code files | pass | P3 preview; Monaco read-only, no write path exists |
| 17 | Sensitive files not previewable | pass | `daemon/internal/files/files_test.go::TestReadPolicyMatrix` + the installer-default regression test |
| 18 | No new session while a node is offline | pass | `SessionService.create` refuses `NODE_OFFLINE`; the UI also filters to online nodes, and both are tested — the UI filter is a courtesy, the server check is the rule |
| 19 | User can terminate a session | pass | `tests/db/test_sessions_api.py`; E2E |
| 20 | All important operations audited | pass | `tests/db/test_audit_coverage.py` — exactly one row per event, closed action vocabulary, forbidden-metadata list, redaction |

Favourites and recents (FR-WORKSPACE-004/005) are **not** among the twenty. They are
delivered anyway (P4-13) and are not load-bearing for the release.

---

## 3. Defects found in P4 and fixed

Both were found by running the software rather than by reading it, and neither had a failing
test before it was found. That is the part worth keeping.

### 3.1 No per-user session cap (tech §23 #14)

Only `sessions_per_node_max` existed. One account could hold
`nodes x (per_node - 1)` sessions — 900 on a 100-node fleet — without tripping any limit.
A bound that grows with the fleet is not a bound.

Fixed: `sessions_per_user_max` (default 20), checked across the whole fleet in
`SessionService.create`. It survived to P4 because every existing test used a single node,
and a per-node check passes a single-node scenario perfectly; the new test asserts the cap
**across two nodes**, which is the only arrangement that can distinguish the two rules.

### 3.2 Connection left open after terminal-queue overflow (tech §23 #15)

On overflow, `pump()` sent `terminal.gap` and returned without closing the socket. The
browser had its gap notice and would never receive another byte, while remaining counted in
`active_terminal_connections`, remaining subscribed in the relay, and — if it was the
**writer** — holding the writer marker it could no longer use, so nobody else could take
over by the normal path.

Fixed: the overflow branch closes with 1013. It survived because every test asserted the gap
was *sent* and none asserted what happened next. Finding it needed a load client that
genuinely stops reading, which in turn had to be hand-rolled on a raw socket with a shrunken
receive buffer — the `websockets` library drains into its own buffer and would have presented
as a healthy reader.

### 3.3 Empty fleet reported as stale (P4-08)

A fresh Central with no nodes marked the dashboard's node block `stale`, putting "possibly
out of date" next to a certain number on the first screen a new operator sees. Fixed with an
empty-fleet exemption plus a reverse test that a *populated* fleet on a fresh restart is
still stale. Found by loading the page, not by a test.

### 3.4 `agentd update --dry-run` unusable as a non-root user (P4-10)

The privilege gate plus a `/var/lib/agentd` staging root made rehearsal impossible for the
operator most likely to want it. Fixed: dry run skips the privilege gate (reporting the
verdict in its output) and falls back to a temporary directory; the real path still requires
the doctor-checked 0700 root. No unit test could have found this — it needed the real binary
run by an unprivileged user.

---

## 4. Verification gaps — recorded, not deferred

Each of these is a property that is implemented and reviewed but not *executed* by an
automated check. None is a known defect. All are release decisions.

### 4.1 ~~nginx behaviour is reviewed, not executed~~ — **closed**

This was recorded as a medium-impact gap and has since been closed by
`scripts/p4/verify-edge.sh` (CI job `edge`): the real nginx image, the shipped config file,
a self-signed certificate and the real built console in front of a throwaway Central, with
**25 assertions made over the wire**.

Closing it found three defects. All three read as correct on inspection; none survived being
executed:

1. **Every security header was absent on the HTML page and on the JS bundle.** nginx's
   `add_header` does **not** inherit into a location that declares its own `add_header`, and
   both `location /` and `location /assets/` set `Cache-Control`. So HSTS, CSP,
   `X-Frame-Options` and the rest were silently dropped on exactly the responses that need
   them, while the server-level block read as though they were present.
2. **The CSP produced an invalid HTTP/2 header.** It was written across several lines with
   trailing backslashes; nginx has **no line continuation inside a quoted string**, so the
   backslashes and newlines went into the header *value*. curl rejects the whole response
   with error 92 and so does a browser — the page breaks *and* the policy is not applied.
3. **`/api/metrics` was proxied straight through** while a comment two lines above claimed
   it was "deliberately not exposed here". `location /api/` is a prefix match; only an
   exact-match block refuses it.

**And the gap's own premise turned out to be wrong.** It claimed a 60 s `proxy_read_timeout`
"kills idle terminals on the minute". It does not: uvicorn pings every 20 s by default and
each ping resets the timeout, so an idle terminal survives the nginx default fine. The first
version of the check therefore **passed with `proxy_read_timeout 20s`** — it was measuring
nothing. The real invariant is `proxy_read_timeout > ws_ping_interval`, and the check now
runs Central with the server ping pushed out of the way so the proxy is the only thing that
can close the connection. Negatively verified: it fails at exactly 20.0 s with a 20 s
timeout and passes at 70 s with the shipped 3600 s.

**Residual:** TLS is exercised with a self-signed certificate, and `ssl_stapling` is
therefore inert in the test (nginx warns and ignores it). Certificate provisioning and
stapling remain an operator concern documented in `docs/deployment.md`.

### 4.2 Full-scale capacity runs only on main

**Impact: low.** `capacity` runs the smoke profile (5 nodes, 10 sockets) on every push and
the full NFR-003 profile (100 nodes, 500 sockets) only on main and release branches. A
100-node run on a shared hosted runner measures the runner; the numbers would be noise and
the gate would flap.

Every assertion runs at both magnitudes, so a bound regression is caught on every push. What
the smoke profile cannot catch is a limit that only appears at scale.

**To close:** a dedicated runner. Not an MVP requirement.

### 4.3 `pending_requests_max` is unreachable through HTTP

**Impact: none — documented behaviour.** The bound is 128; `db_pool_size + db_max_overflow`
is 20. A request cannot occupy a pending slot without first holding a database connection,
so the pool ceiling binds first by a wide margin. Excess concurrency is shed with a
retryable 503, which is the right behaviour.

Consequence: the pending bound's only coverage is its own unit test. The load harness prints
both numbers in its notes so a future pool increase makes the probe meaningful rather than
silently vacuous.

### 4.4 The multi-replica limitation is a constraint, not a bug

Central's connection registry and terminal relay are process-local. A second backend replica
would hold half the daemon sockets with neither replica aware of the other's. The reference
deployment is therefore single-instance, and `docs/deployment.md` says so in its first
paragraph rather than leaving it to be discovered by someone scaling out under load.

**To close:** a shared store for both. Post-MVP.

### 4.5 Three of five alert drills need a host this one is not

**Impact: low.** `scripts/p4/drills/run-all.sh` runs all five drills and reports three
outcomes, not two: triggered, failed, or **skipped because a prerequisite is absent**. On a
sandbox or a plain development machine, `heartbeat-loss` needs systemd to stop a real
`agentd`, `timeout-surge` needs a connected daemon to go silent, and `update-failure` needs a
published release artifact. Those three skip; `queue-saturation` and `db-exhaustion` run.

The skip is counted separately and named in the verdict rather than folded into a pass —
"PASS with 3 skipped" plus the explicit statement that those alert paths are unexercised by
that run. Recording it as a failure would train everyone to ignore the report; recording it
as a pass would be a lie.

**To close:** run the `drills` job on a host with systemd and a real enrolled node. The
alert *rules* themselves are validated statically by `promtool check rules` on every push, so
what is missing is confirmation that the signal moves, not that the rule parses.

While wiring this up, `queue-saturation.sh` turned out to be calling the load harness with a
CLI that never existed — it was written in P4-09 against a guessed interface, and the harness
landed in P4-11 with different flags. A drill that cannot start is indistinguishable from an
alert that cannot fire, so `test_drill_harness_flags_exist` now compares the two on every
push.

### 4.6 P3's real-runner gap

`p3.yml` never ran on a runner with the browsers and tmux actually installed for its full
matrix, so parts of the P3 suite were green by virtue of not running. `p4.yml` closes this
for P4: the `browser` job installs each engine explicitly and runs all three as a matrix,
and the `daemon` job installs tmux before the integration suites. Recorded because the P3
evidence pack should be read with it in mind.

---

## 5. Conditions on the Go

1. **Run `p4.yml` green on a release branch**, which includes the full-scale capacity
   profile and all three browser engines. The local evidence pack covers everything except
   the browser matrix.
2. **Set both production secrets.** `Settings` refuses to start on the dev defaults with
   `CLIORA_ENVIRONMENT=production`, so this is enforced — but note the asymmetry in
   `docs/deployment.md`: rotating `CLIORA_TOKEN_PEPPER` later forces every node to re-enroll.
3. **Take and verify a backup before first use of the retention prune.**
   `scripts/p4/backup-restore-drill.sh` is the check; the prune is the only operation that
   deliberately deletes audit history.
4. **Run `scripts/p4/verify-edge.sh` against whatever actually terminates TLS.** With the
   shipped `deploy/nginx/nginx.conf` it passes and is part of the `edge` CI job. If you
   replace that config, read §4.1 first: three of its findings generalise to any nginx —
   `add_header` does not inherit into a location that has its own, quoted strings have no
   line continuation, and prefix locations catch more than they appear to.

`docs/release-checklist.md` turns all four into boxes you tick against real command output,
together with the §4 items that must be explicitly accepted rather than fixed.

---

## 6. Traceability

`research/01/06-requirement-traceability.md` §10 records per-requirement status. P4 changed
these rows:

| Requirement | Change |
|---|---|
| FR-WORKSPACE-004 / 005 | Deferred from P3 → **delivered** in P4-13 |
| tech §23 #14 | Partial (per-node only) → **complete** (per-user cap added) |
| tech §23 #15 | Partial (bounded but not disconnected) → **complete** |
| NFR-003 | Unmeasured → **measured**, `artifacts/p4/*/capacity.json` |
| NFR-004 | Partial → **complete** (metrics export, alerts, six runbooks, drills) |
| tech §23 #1 | **Partial** — implemented and reviewed, not executed; see §4.1 |

---

## 7. Evidence

| Artifact | Produced by |
|---|---|
| `artifacts/p4/*/summary.md` | `scripts/p4/evidence.sh` — every gate with its exit status, and an explicit list of what was skipped |
| `artifacts/p4/*/capacity.json` | `scripts/p4/load/capacity.py` — per-NFR pass/fail plus the environment it was measured on |
| `artifacts/p4/*/backup-restore.md` | `scripts/p4/backup-restore-drill.sh` — including the dump leakage scan |
| `artifacts/p4/*/drills.md` | `scripts/p4/drills/run-all.sh` — each alert triggered on demand |
| `docs/security-review-p4.md` | the fifteen-baseline sign-off, attack suite, and findings |
| `docs/error-catalog.md`, `docs/permission-matrix.md` | generated from source; CI fails if they drift |

Every one of these is generated from a run. None is hand-maintained prose, which is the
property that makes the pack worth reading a release later.
