# Cliora MVP release checklist

Derived from `docs/p4-report.md` §5 (the four conditions on the Go) and §4 (the verification
gaps). Every box is a **command you run** or a **decision you record** — nothing here is
satisfied by reading a document.

Two rules for using it:

- **A box you cannot tick is a release decision, not a formality.** Either fix it, or write
  down in §6 below who accepted the risk and why. That is the whole point of a phase where
  "defer to next phase" is not available.
- **Do not tick a box on the strength of a previous run.** Capacity numbers, dump scans and
  edge behaviour are all properties of a specific build on a specific machine.

---

## 1. Before you start

- [ ] Working tree is at the commit you intend to release, with nothing uncommitted
      (`git status --porcelain` empty).
- [ ] `docker` and the `cliora-pg` container are up (several gates create throwaway
      databases and will refuse to run without it).
- [ ] Go on PATH (`export PATH=$PATH:/usr/local/go/bin`) — the daemon gates skip silently
      otherwise, and a skipped gate is listed but easy to overlook.
- [ ] Both database URLs exported. **Both**, not just the test one: the denial-audit
      middleware writes on its own session through the process-wide engine, so with only
      `CLIORA_TEST_DATABASE_URL` set those tests fail for an environmental reason and look
      like real failures.
      ```bash
      export CLIORA_TEST_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test
      export CLIORA_DATABASE_URL=$CLIORA_TEST_DATABASE_URL
      ```

## 2. Local gates

- [ ] `make check` exits 0 (format, lint, typecheck, unit, contract, build — three languages).
- [ ] `uv run --project backend pytest backend/tests -q` — all pass, PostgreSQL reachable.
- [ ] `npx vitest run --exclude 'tests/e2e/**'` in `frontend/` — all pass.
- [ ] `cd daemon && go test -race ./...` and the `-tags integration` suites — all pass
      (needs tmux).
- [ ] Migrations reverse: `alembic upgrade head` → `downgrade 0007_seed_file_browse` →
      `upgrade head`. Note the revision id is `0007_seed_file_browse`; guessing
      `0007_file_browse_action` broke both `p4.yml` and `evidence.sh` once already.

## 3. The evidence pack

- [ ] `make traceability` exits 0 (schema, anchors, links, selectors, generated views,
      changed-scope coverage and the traceability tool tests).
- [ ] `traceability/baseline-debt.json` is still empty. It is checked in both directions, so an
      entry is a deliberate, reviewable step down from full release blocking — never a quiet way
      to land a gap.
- [ ] No criterion is `needs_rewrite`. That state means the requirement text cannot be decided,
      and the fix is a product decision, not a test.
- [ ] Required gate shards produced `gate-results.json` for the release commit and the resolved
      `trace-snapshot.json` has no stale/dirty/hash/digest/skip/manual-pending error.
      `scripts/traceability/dogfood.sh artifacts/traceability/<run-id>` does the whole sequence.
- [ ] No criterion resolved to `environment-incomplete`. A gate that declares a browser or
      platform matrix must report every leg as executed; a partial matrix is not a pass.
- [ ] `scripts/p4/evidence.sh artifacts/p4/<run-id>` exits 0.
- [ ] **Read `skipped.txt`.** A green pack with three skipped legs is not a green release;
      the pack lists skips precisely so they cannot pass silently.
- [ ] `commands.txt` shows `exit=0` for every gate that ran.

Included in the pack, each with its own artifact — check the verdict line of each:

- [ ] `capacity.json` — `verdict.status: pass`. Also read `scenarios[].notes[]`: they name
      paths a run did **not** exercise (e.g. `pending_requests_max` is unreachable over HTTP
      because the DB pool binds first).
- [ ] `backup-restore.md` — **PASS**, including the dump leakage scan and the reverse
      assertion that the dump does contain this deployment's data.
- [ ] `drills.md` — no **FAILED** rows. Skipped rows are acceptable only if you accept, in
      writing, that those alert paths are unexercised (see §5).
- [ ] `edge-verification.md` — **PASS**. This is the one that executes nginx rather than
      reading it.

## 4. Conditions on the Go (from `docs/p4-report.md` §5)

### 4.1 `p4.yml` green on a release branch

- [ ] All **12** jobs green, on a **release branch** so the full-scale capacity profile runs.
- [ ] `browser` matrix green on **all three** engines — chromium, firefox **and webkit**.
      "Works in Chromium" is not the claim the PRD makes, and WebKit is the engine that
      historically differs on WebSocket behaviour.
- [ ] `daemon` job's reproducible-build step green (same commit, two builds, same checksum).
      An update path that verifies checksums is only meaningful if the checksum is
      deterministic.
- [ ] The `evidence` job produced a pack. It `needs` every other job, so a pack exists only
      for a run whose gates passed.

### 4.2 Production secrets set

- [ ] `CLIORA_JWT_SECRET` and `CLIORA_TOKEN_PEPPER` set to real values, with
      `CLIORA_ENVIRONMENT=production`. Startup refuses the dev defaults, so this is
      enforced — but confirm it *started*, do not assume.
- [ ] `CLIORA_TOKEN_PEPPER` stored somewhere it will survive the loss of this host, next to
      the backups. **Rotating it forces every node to re-enroll**, and losing it makes every
      dump useless for restoring node credentials. Treat as a one-way door.
- [ ] `CLIORA_PUBLIC_BASE_URL` is the URL daemons will connect back to. It ends up in every
      node's config; changing it later means reconfiguring every node.
- [ ] If metrics are enabled: `CLIORA_METRICS_SCRAPE_TOKEN` is ≥ 16 characters and is not
      an `audit.view` credential.

### 4.3 Backup taken and verified before first use of the retention prune

- [ ] A real `pg_dump` of the production database exists, off-host, with the `pg_dump`
      version recorded next to it.
- [ ] `scripts/p4/backup-restore-drill.sh` passes against this build's schema.
- [ ] Understood: **backup → verify → prune**, never prune first. The prune is the only
      operation that deliberately deletes audit history.

### 4.4 Edge configuration

Backed by an executed gate as of P4 (`docs/p4-report.md` §4.1 is closed). Closing that gap
found three defects and disproved its own premise, so the boxes below are not formalities.

- [ ] `scripts/p4/verify-edge.sh` passes (25 checks) — HTTP 301, all security headers on **both** the
      HTML page and a hashed asset, the CSP's `worker-src blob:` clause, `/api/metrics`
      refused at the edge, and an authenticated idle WebSocket surviving past 60 s.
- [ ] If you terminate TLS with anything **other** than the shipped `deploy/nginx/nginx.conf`,
      you own all of the above yourself. Three findings from this file are worth knowing
      before you write your own:
      - nginx `add_header` does **not** inherit into a location that declares its own
        `add_header` — every security header was silently absent on the HTML page;
      - nginx has **no line continuation inside a quoted string** — a "tidy" multi-line CSP
        put literal backslashes and newlines into the header value, producing an invalid
        HTTP/2 header that browsers reject outright;
      - `location /api/` is a prefix match, so `/api/metrics` was proxied while a comment
        two lines above claimed it was not exposed.
      All three read as correct on inspection. None survived being executed.
- [ ] Understood that the invariant is **`proxy_read_timeout > ws_ping_interval`**, not
      "longer than a human pause". uvicorn pings every 20 s by default and each ping resets
      the timeout; if you raise the ping interval above the proxy timeout, *every* WebSocket
      dies on a fixed cycle regardless of activity.

## 4.5 The system terminal (plan/08, ADR 0021)

Only two of these are commands; the rest are decisions that have to be made before
an upgrade rather than discovered after one. The reason they are a numbered gate
and not advice: **upgrading a daemon enables the shell on that node**, because an
absent `runtime.shell` block counts as enabled. Nothing in CI can notice that a
fleet gained a capability.

- [ ] **`agentd` does not run as root on any node.** Not hygiene — the shell
      escalates nothing, so the daemon's execution identity is the ceiling of the
      feature. `systemctl show agentd -p User` on each node. `agentd run` refuses
      to start as root and the shipped unit sets `User=`, so this is only reachable
      through a hand-edited unit or a container running the binary directly.
- [ ] **`docs/release-note-system-terminal.md` has been sent to node owners**, and
      they have had the chance to answer. This is the notice for a capability
      change, so it goes out *before* the upgrade, not with it.
- [ ] Understood that `terminal.shell` is held by **Admin and Developer**, and that
      the boundary is therefore **ownership**, not role scarcity: a shell can only
      be opened on a session the user owns, and nobody can attach to anybody
      else's. If that is not the boundary you want, change the role grant before
      release, not after.
- [ ] Decided on `CLIORA_SHELL_IDLE_TERMINATE_SECONDS` (default **900**). After a
      browser crash, an unattended shell exists on the node for up to that long.
      The default is a trade against reload/suspend churn with **no usage data
      behind it yet** (security review Finding 3) — 300 is a defensible starting
      point for a stricter environment.
- [ ] Accepted that **commands are not recorded** (ADR 0004, `TECH-SEC-08`): the
      audit trail says a shell existed, never what ran in it. If an auditor needs
      the latter, host-level auditing has to be in place *before* this ships,
      because there is nothing to backfill.
- [ ] `docs/runbooks/system-terminal.md` is reachable by whoever is on call. §6 is
      the part that matters at 3am.

## 5. Accepted-and-unexercised (tick only if you accept each)

These cannot be closed on a normal host. Ticking means you accept them for this release.

- [ ] **`heartbeat-loss` drill unexercised** — needs systemd to stop a real `agentd`.
- [ ] **`timeout-surge` drill unexercised** — needs a connected daemon to go silent.
- [ ] **`update-failure` drill unexercised** — needs a published release artifact.
- [ ] **Real systemd restart / six-platform install-update matrix** for the daemon update
      path (P4-10) — covered locally only through injectable `Restarter`/`HealthChecker`.
- [ ] **Single-instance only.** Central's connection registry and terminal relay are
      process-local; a second backend replica would hold half the daemon sockets with
      neither aware of the other. Scale up, not out.

## 6. Sign-off

| Item | Who | Date | Note |
|---|---|---|---|
| Gates in §2–§3 green |  |  | evidence pack path: |
| §4 conditions met |  |  |  |
| §5 items accepted |  |  |  |
| Go / No-Go decision |  |  | see `docs/p4-report.md` §1 |

Anything not ticked and not accepted here **blocks the release**. Unresolved Critical or High
security findings block unconditionally (`research/01/05` §stage exit); both findings in
`docs/security-review-p4.md` are Medium and both are resolved in P4.

---

## Quick sequence

```bash
export PATH=$PATH:/usr/local/go/bin
export CLIORA_TEST_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test
export CLIORA_DATABASE_URL=$CLIORA_TEST_DATABASE_URL

make check
RUN=$(date -u +%Y%m%d%H%M%S)
scripts/p4/verify-edge.sh          "artifacts/p4/$RUN"   # ~3 min; 70 s of it is the idle WS
CLIORA_DRILL_YES=1 \
scripts/p4/evidence.sh             "artifacts/p4/$RUN"   # runs capacity, backup, drills

cat "artifacts/p4/$RUN/summary.md"
cat "artifacts/p4/$RUN/skipped.txt"     # read this one
```

Then push a release branch and confirm `p4.yml` — §4.1 is the only part this sequence cannot
give you.
