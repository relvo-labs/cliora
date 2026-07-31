# ADR 0017: P4 daemon release/update & deployment baseline

Status: accepted (2026-07-25). Governs Phase 4 (Operations & Hardening); confirmed defaults per product decision (see `plan/05`). Extends ADR 0011 (installer), which deferred `agentd update` to P4.

## Context

`agentd update` has been a CLI stub since P1 (`daemon/cmd/agentd/service.go`), printing "deferred to P4". The artifact pipeline exists (`.goreleaser.yaml` → per-arch tarballs + `checksums.txt`; `app/api/http/downloads.py` serves them behind a closed allowlist regex), but there is **no version manifest**, so "only accept an allowlisted release" — the actual security requirement — cannot currently be expressed or verified. Separately, the repository contains **no deployment assets at all**: no compose file, no Dockerfile, no nginx config, while tech §17.1 specifies the MVP topology. Graceful shutdown disposes the DB engine but does not drain terminal WebSockets.

The dominant tension in this ADR is that self-update needs privilege while SEC-007 requires the daemon not to run as root long-term.

## Decisions

### Release manifest is the definition of "allowlisted"

`GET /api/releases/manifest` (public, same rationale as `/api/downloads`: the daemon needs it before it holds any credential, and it contains no secret) returns `latest`, plus one entry per `(version, architecture)` with `filename`, `sha256` and `size`.

`services/releases.py` derives it from the **actual contents** of `artifacts_dir` cross-checked against `checksums.txt`, and **shares the allowlist regex constant with `downloads.py`** rather than restating it. An entry appears only if the filename matches the allowlist, `checksums.txt` has a matching digest, and the file exists with the recorded size. Anything that cannot be fully reconciled is **omitted** — omitted means uninstallable, i.e. fail closed. An unset or empty `artifacts_dir` returns `{"latest": null, "artifacts": []}`, not 404, so the daemon can distinguish "no update available" from "endpoint missing".

### No artifact signing in MVP; the residual risk is recorded

tech §23 #12 requires checksum verification, which `install.sh`, `internal/install/verify.go` and the update path all perform. MVP ships **`checksums.txt` + HTTPS transport + closed filename allowlist** and no cryptographic signature.

**Residual risk:** anyone able to write to `artifacts_dir` can publish a poisoned binary together with a matching digest, and every node will install it. `checksums.txt` protects against corruption and against substitution *in transit*, not against a compromised release directory.

**Mitigations required by this decision:** `artifacts_dir` is writable only by the release process (documented filesystem permissions in `docs/deployment.md`); artifact publication is part of the deployment procedure, not an ad-hoc copy; the reproducible-build check below lets anyone re-derive the expected digest from source.

**Revisit trigger:** adopt cosign or minisign (with daemon-side verification) if the platform is deployed outside a single trusted operator boundary, or if artifact hosting moves to shared/third-party storage. Listed as an open item in `docs/security-review-p4.md`.

### Builds are reproducible and release is tag-triggered

`-trimpath` is added to the GoReleaser build flags alongside the existing `CGO_ENABLED=0` and pinned `-s -w -X main.version=`. CI verifies reproducibility the only way that matters: **build the same commit twice and assert identical checksums**, storing both in the evidence pack. `release.disable` is lifted so a version tag produces the release; snapshot builds stay available for local verification.

### `agentd update`: six stages, one lock, rollback on any failure

One `Updater` owns the flow and holds a process-level lock (a concurrent attempt gets `UPDATE_IN_PROGRESS`).

| Stage | On failure |
|---|---|
| `manifest` — fetch from the **server URL in the local config**, confirm `target_version` + architecture exist, compare with current; downgrade refused unless `--allow-downgrade` | `UPDATE_NOT_ALLOWED` / `UPDATE_DOWNLOAD_FAILED` |
| `download` — fetch the manifest-named file into `/var/lib/agentd/update/<version>/` (0700), bounded size and time | `UPDATE_DOWNLOAD_FAILED`, temp cleared |
| `checksum` — SHA256 vs manifest; **mismatch aborts before extraction**, nothing reaches `/usr/local/bin` | `UPDATE_CHECKSUM_MISMATCH` |
| `swap` — extract, verify the new binary runs and reports the expected version **in the temp location**, back up the current binary, then `rename(2)` atomically | restore backup; `UPDATE_ROLLED_BACK` |
| `restart` — `systemctl restart agentd` | restore backup, restart old version |
| `healthcheck` — within 30 s (monotonic): `doctor` passes **and** the node re-registers with Central | **rollback**; `UPDATE_HEALTHCHECK_FAILED` / `UPDATE_ROLLED_BACK` |

**Rollback boundary:** binary and unit restart only. Config and credentials are never rewritten or reverted by update — they are node identity, not release payload.

### Privilege: the operator elevates, the daemon never does

`agentd update` is run by an operator with `sudo` (exactly the form PRD FR-INSTALL-005 specifies). The long-running `agentd run` process stays non-root (SEC-007).

When Central sends a `daemon.update` control frame and the daemon has no route to elevate, it replies `UPDATE_NOT_ALLOWED` and logs/audits that operator action is required. **The daemon is never granted long-term root, and no restricted sudoers fragment or privileged helper unit is installed, in order to make a UI button work.** The Central-side "Update to x.y.z" control therefore reports "operator action required" on such nodes rather than silently doing nothing.

Rejected: a helper unit or narrow sudoers rule permitting "replace this file + restart this unit". It would enable one-click updates but widens the attack surface on every node for a convenience the MVP does not need — an operator already has shell access to run the installer.

**The healthcheck runs `doctor` as the unit's `User=`, not as the updater.** The
elevation above is what makes this necessary: the updater is root, so a plain child
process would be root too, and `doctor`'s first check is `EnsureNonRoot`. Every real
`sudo agentd update` therefore failed the healthcheck stage and rolled back, reporting
`agentd must not run as root` — a message about the wrong process entirely. The
identity comes from `systemctl show --property=User`, so it is what systemd resolved
including drop-ins, and the child carries that uid/gid, the user's supplementary
groups and a matching `HOME`. Skipping the root check instead was rejected: `doctor`'s
remaining checks — config readable, `credentials.yaml` at 0600, workspace roots
readable — are assertions about a *specific* identity, and root satisfies all of them
regardless of who owns what, so a root `doctor` run is a green light that means
nothing. If the process is root and the unit's user cannot be determined, the stage
fails rather than falling back to a root run.

### The update protocol carries a version, nothing else

`daemon.update` payload is `{target_version}` with `additionalProperties:false`; the version pattern is strict semver. **No URL, filename, path, checksum or binary ever crosses the wire, and the `Updater` API accepts none** — the CLI exposes only `--version` / `--allow-downgrade` / `--dry-run`. Download location and digest come exclusively from the manifest plus local config (SEC-002 extended to the release path). Contract fixtures assert that frames carrying `url` or a path are rejected by all three languages.

### Update state lives in explicit columns

Migration `0012` adds `update_status`, `update_target_version`, `update_last_result` and `update_updated_at` to `nodes` as **real columns**, not keys inside the existing `node_metadata` JSONB: the dashboard and the node list filter and sort on them, and "which nodes failed to update" must be an indexable query rather than a JSONB scan. A Central-side trigger that times out does **not** mark the update failed — the state converges from the daemon's `daemon.update_result` or from the next successful registration/heartbeat, because a slow update is not a failed one.

### tmux sessions survive an update

The tmux server is an independent process owned by the session user, not a child of the daemon (P2 design). An update therefore does not touch running CLI sessions: only the terminal stream is interrupted while the daemon restarts, after which P2's recovery path (ADR 0012 — scan tmux, reconcile against Central via `session.list` / `session.recover`, evict orphans) reattaches, and the browser reconnects via FR-TERM-006. The gap is surfaced honestly as `terminal.gap`, never as continuous output.

This is a **guarantee that must be tested, not assumed**: integration tests cover (a) two live sessions surviving a successful update, (b) the same sessions surviving a rollback, and (c) an attached browser reconnecting across the restart. `docs/runbooks/update-failure.md` states plainly what a user sees and whether sessions are lost.

### Deployment topology

`deploy/compose/` provides nginx + backend + frontend (static) + postgres, with **prometheus and grafana behind an optional `observability` profile** — not started by default, because a monitoring stack is an operator choice and the exporter (ADR 0018) is off by default anyway.

- **TLS:** nginx terminates TLS and upgrades WSS. The default documented path is **bring-your-own certificate** (mounted), because internal deployments frequently lack the public DNS an ACME challenge needs; an ACME companion is documented as an alternative but not wired in.
- **Long-lived WebSockets:** `proxy_read_timeout` must be set explicitly — nginx's 60 s default would sever idle terminal sessions. `client_max_body_size` and buffer limits are aligned with the contract's 8 MiB filesystem response bound (ADR 0015 amendment).
- **Security headers / CSP:** HSTS, `X-Content-Type-Options`, `Referrer-Policy`, frame options, and a CSP with **no external origins** and `worker-src 'self' blob:` for Monaco. This makes P4-07 (removing the Google Fonts CDN `@import` from `styles.css`) a **hard prerequisite**: enabling the CSP first would break fonts.
- **Secrets:** `CLIORA_JWT_SECRET`, `CLIORA_TOKEN_PEPPER`, `CLIORA_DATABASE_URL` and the optional metrics scrape token are injected from the environment; images contain no real values; `.env.example` carries descriptions only. The existing production validator (which rejects the `dev-only-change-me` defaults) gets a test.
- **Migrations run as a separate one-shot job** (`deploy/migrate.sh`), never from the FastAPI lifespan: automatic migration on boot races across replicas and upgrades a database as a side effect of a restart. Deployment order is migrate → start backend → `/readyz` green → route traffic; `/readyz` already compares the applied revision to the migration head, so a wrong order is caught by readiness.

### Graceful shutdown drains, and never kills a session

On SIGTERM: stop accepting new connections → send each browser terminal WS an explicit close reason (so the UI shows "server restarting, reconnecting" rather than an unexplained drop) and drain within `shutdown_drain_seconds` (15, monotonic) → close daemon WS connections, letting daemons reconnect via their existing backoff (FR-CONN-003) → dispose the DB engine. **No tmux session is terminated under any shutdown path** — NFR-002's "a browser disconnect must not end the CLI session" applies equally to a Central restart.

## Consequences

- One-click update works only on nodes where an operator has arranged elevation; on others the UI reports "operator action required". Accepted: security over convenience.
- Unsigned artifacts make the release directory a trust boundary. It must be treated as such in deployment docs and in the security review.
- Retiring the P0 dev relay (ADR 0016) removes `make dev-central` / `dev-daemon`; the documented development path becomes `scripts/e2e/run-stack.sh`.
- The `install-update` CI matrix (Ubuntu 22.04 / 24.04 / Debian 12 × amd64 / arm64) is the only place real systemd restart and rollback are exercised — the development sandbox has no root or PID-1 systemd. Local results must never be reported as covering the real path.
