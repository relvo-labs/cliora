# Deploying Cliora on Railway

The second supported target, alongside the single-host compose topology in
[deployment.md](./deployment.md). Same images, same security properties, different mechanisms.
Decisions and their reasoning: [ADR 0020](./adr/0020-railway-deployment-topology.md). Variable
contract: [`deploy/railway/env.md`](../deploy/railway/env.md).

```
browser ──HTTPS/WSS──▶ Railway edge ──▶ console (public)  ──private IPv6──▶ central ──▶ Postgres
                                        nginx + dist              /api /ws
agentd, on the user's own Linux host ──outbound WSS──▶ the same public origin
```

**Nothing about `agentd` changes.** It runs on the user's machines, holds the tmux sessions,
and dials Central outbound (FR-CONN-001), so Railway hosts only the control plane. That is why
this system fits a PaaS at all: the stateful part is the customer's, not the platform's.

## What is different from the compose topology, and why

| Compose | Railway | Reason |
|---|---|---|
| `stop_grace_period: 30s` | `drainingSeconds: 25` | The platform default is **0**: SIGTERM then immediate SIGKILL. The drain would never complete and every deploy would disconnect browsers without explanation |
| `depends_on: migrate: service_completed_successfully` | `preDeployCommand: alembic upgrade head` | Non-zero exit stops the deploy and is not retried. Migrations still never run from the app's lifespan |
| healthcheck parses `/readyz`'s body | `healthcheckPath: /readyz`, and `/readyz` answers **503** when degraded | The platform reads the status code only |
| nginx `server backend:8000` | `resolver` + `proxy_pass http://$variable$request_uri` | Service IPs change every deploy and nginx caches a static upstream for the life of the process |
| TLS terminated by our nginx | Terminated at the platform edge; console 301s on `X-Forwarded-Proto: http` | No certificate exists inside the container |
| `CLIORA_ARTIFACTS_DIR` on a mounted host directory | Baked into the image at build time, digests verified | The container filesystem is ephemeral |
| `--host 0.0.0.0` | `--host ""` | The private network is IPv6, so IPv4-only is unreachable from `console` — but `::` alone is IPv6-only (asyncio sets `IPV6_V6ONLY`) and the platform's health check never arrives. An empty host binds both families |
| Prometheus/Grafana profile | Off; scrape over the private network if wanted | An always-on public metrics endpoint is a permanent read surface |

## First deployment

Order matters, and two steps are one-way doors.

1. **Create the project and the three services** in the same region (`asia-southeast1`):
   `Postgres`, `central` (Dockerfile), `console` (Dockerfile). Set each service's
   *Config as code path*:
   - `central` → `deploy/railway/central.railway.json`
   - `console` → `deploy/railway/console.railway.json`
2. **Bind the custom domain to `console`** and wait for the certificate.
   *Do this before step 4.* `CLIORA_PUBLIC_BASE_URL` is written into every node's config file.
3. **Give `central` no public domain.** It is reached only over the private network.
4. **Set the variables** per [`deploy/railway/env.md`](../deploy/railway/env.md), then check
   them before deploying:
   ```bash
   scripts/railway/check-env.sh --domain cliora.example.com
   ```
5. **Deploy.** Watch that the migration runs before the app starts:
   ```bash
   railway logs --service central | grep -E "alembic|central_startup"
   ```
6. **Create the first administrator.** The password must not become a service variable:
   ```bash
   railway ssh --service central
     read -rs CLIORA_ADMIN_PASSWORD && export CLIORA_ADMIN_PASSWORD
     python -m app.bootstrap create-admin --username admin
     unset CLIORA_ADMIN_PASSWORD; exit
   ```
   If `railway ssh` is unavailable, temporarily enable the Postgres public TCP proxy and run
   the same command locally against `CLIORA_DATABASE_URL=postgresql+asyncpg://…@<proxy>/…`,
   then **disable the proxy again**.
7. **Verify the deployment over the wire:**
   ```bash
   scripts/railway/verify-deployment.sh https://cliora.example.com artifacts/rw/$(date -u +%Y%m%d%H%M%S)
   # add the idle-WebSocket leg (it enrolls and then removes a probe node):
   CLIORA_VERIFY_ADMIN=admin CLIORA_VERIFY_PASSWORD=… \
     scripts/railway/verify-deployment.sh https://cliora.example.com
   ```
8. **Set up external monitoring** (see below). The platform health check does not run after the
   deploy completes.

## Publishing a daemon release

Artifacts live in the Central image, so publishing a release is a Central redeploy — and by
default there is nothing to configure. The image compiles `agentd` for amd64 and arm64 from
`daemon/` at the commit being deployed, at the version `daemon/VERSION` declares, with the same
flags as `daemon/.goreleaser.yaml`, and generates `checksums.txt`.

**Publishing a new daemon release is therefore: edit `daemon/VERSION`, merge, redeploy.**

Bump that file on every daemon change. The bytes come from the commit, so reusing a version
republishes different bytes under a version nodes already think they run — and `agentd update`
compares versions, so nothing would reach the fleet. Three things are pinned to that file so it
cannot drift: `main.go`'s fallback version (a Go test), the git tag `make release` will accept,
and the version the download route below looks for.

### Optional: serve a published release instead of building one

Set `AGENTD_RELEASE_BASE_URL=https://github.com/<owner>/<repo>/releases/download/v1.2.3` on
`central` after `make release` has published the assets, and the build downloads and verifies
them instead of compiling. **A digest mismatch fails the build**, which is the point — it fails
before any node can download a bad artifact.

This needs the assets to be fetchable **without credentials**; a private repository's release
assets answer 404 and fail the build. The URL's version must also equal `daemon/VERSION`, or the
digest lookup fails with `checksums.txt has no digest for …`.

### Confirming

Confirm, then publish the one-line install command:

```bash
curl -sS https://cliora.example.com/api/releases/manifest | python -m json.tool
curl -sS https://cliora.example.com/api/install-script | head -3
# GET, not HEAD: the download route is registered for GET only and answers 405 to a HEAD.
curl -sS -o /dev/null -w '%{http_code}\n' https://cliora.example.com/api/downloads/checksums.txt
sudo agentd update --dry-run     # on a real node: manifest → download → digest → stop
```

If those answer 404, the artifacts directory is empty or elsewhere — check that
`CLIORA_ARTIFACTS_DIR` has not been overridden away from the `/srv/artifacts` the image sets.
The manifest answers `{"latest": null, "artifacts": []}` rather than 404 in that state, so a
daemon can still tell "no update" from "no endpoint", but **do not publish the one-line install
command while it holds**; enroll nodes by installing `agentd` manually and running
`agentd install`.

## `pg_trgm`, and the one migration that can be refused

Migration `0041` runs `CREATE EXTENSION pg_trgm`. It is **the only line in the V2 series
that a database can refuse**, and this section exists because "it worked on compose" says
nothing about a managed database.

### What actually decides it

**Not superuser.** `pg_trgm` is a *trusted* extension (`trusted = true` in
`pg_trgm.control`), and since PostgreSQL 13 a trusted extension can be installed by any
role holding **`CREATE` on the database** — no superuser needed. The extension ends up
owned by the installing role.

So the predicate is one query, and it is worth running before the first deploy:

```bash
psql "$DATABASE_URL" -tAc \
  "SELECT has_database_privilege(current_user, current_database(), 'CREATE');"
#   t → 0041 will succeed
#   f → 0041 will stop, with the message below
```

Railway's default database user owns the database it provisions, so **`t` is the expected
answer**. `f` happens when a deployment was given a scoped role instead — a reasonable
thing for an operator to have done, and the reason this section is not "it will be fine".

### What the refusal looks like

`0041` checks availability and permission **separately**, because they need different
actions from whoever reads the log:

```text
RuntimeError: pg_trgm is not available on this PostgreSQL server. It is a contrib
extension and ships with postgres:16-alpine; a managed database may need it enabled by
the provider first. Install it, then re-run `alembic upgrade head`. Nothing has been
changed.
```

```text
RuntimeError: CREATE EXTENSION pg_trgm was refused. The migration role usually needs to
be a superuser, or pg_trgm has to be on the provider's extension allowlist. Ask an
administrator to run `CREATE EXTENSION pg_trgm;` once against this database, then re-run
`alembic upgrade head`.
```

**Nothing has been changed** in either case: `0041` is a revision of its own precisely so
that the failure is atomic and the log line names the right file, rather than reporting
"0042 failed" three hundred lines of `create_table` later.

### The remedy, once, by an administrator

```bash
psql "$ADMIN_DATABASE_URL" -c "CREATE EXTENSION pg_trgm;"   # against the app's database
# then re-run the deploy, or:
cd backend && alembic upgrade head
```

The extension only has to be created once per database. `0041` uses
`CREATE EXTENSION IF NOT EXISTS`, so re-running after an administrator has installed it
is a no-op that proceeds to the two `projects` columns.

### Downgrade order

Dropping `pg_trgm` requires that nothing depends on it, and `0042` builds the
`gin_trgm_ops` index that does. **`0042` down, then `0041` down** — the revision chain
enforces this, so it is not something to remember.

### Verified how

Against PostgreSQL 16.14, three roles, on 2026-08-28 (`plan/27` `HD-00`):

| Role | `CREATE` on database | Result |
|---|---|---|
| `cliora` (superuser) | yes | `0041`–`0043` succeed |
| `cliora_limited` (owns its database, **not** superuser) | yes | **`0041`–`0043` succeed** — this is the case `plan/25` expected to fail |
| `cliora_norights` (schema rights only) | no | `0041` stops with the second message; after an administrator runs `CREATE EXTENSION pg_trgm`, `alembic upgrade head` reaches `0043` and the `gin_trgm_ops` index is built |

**This was not run against Railway itself.** What it establishes is that the deciding
factor is `CREATE` on the database rather than superuser, that both refusal paths produce
their intended message, and that the documented remedy works. What it does not establish
is Railway's own extension allowlist, if it has one. The one-line predicate above is what
closes that gap on a real deployment, and it costs a `psql` invocation.

## Upgrading

`git push` → CI → deploy. `watchPatterns` keeps a backend change from restarting the console
and vice versa.

During the drain, Central:

1. sends every subscribed browser `terminal.server_shutdown` with `session_preserved: true`;
2. closes daemon sockets with 1012, which their backoff handles (FR-CONN-003);
3. fails in-flight daemon requests as `NODE_OFFLINE`.

**No CLI session is terminated by a deploy.** Verify it, once, deliberately:

```bash
# with a session running and a browser attached, trigger a redeploy, then:
railway logs --service central | grep -E "shutdown_drained|shutdown_drain_timeout"
#   expect shutdown_drained with duration_ms < 15000 and no timeout line
#   expect the browser to log terminal.server_shutdown
#   expect `tmux ls` on the node to still list the session, and re-attach to have scrollback
```

If there is no `shutdown_drained` line, `drainingSeconds` is not set — the platform default is
0 and SIGKILL arrived first.

## Rollback

Application rollback is cheap; schema rollback is not. Try the first.

**Application only** — roll back to the previous deployment in Railway, or redeploy the previous
commit. Safe whenever the previous version understands the current schema; migrations 0008–0011
are additive, so this usually holds.

**With a schema downgrade** — only when the new revision is itself the problem:

```bash
# back up first; a downgrade drops what the newer revision added, including rows written since
railway ssh --service central -- alembic current
railway ssh --service central -- alembic downgrade <revision>
```

Read that migration's `downgrade()` docstring first: every P4 migration is reversible, and
reversible is not harmless. Then deploy the previous image and confirm `/readyz` is 200.

**Configuration rollback.** Fixing `CLIORA_PUBLIC_BASE_URL` after nodes have enrolled against
the wrong value requires `sudo agentd register --server https://<correct>/ --token …` on each
node. Fixing `CLIORA_TOKEN_PEPPER` is not possible: every node must re-enroll.

## Backups

- Enable platform backups on the Postgres service.
- **Also** keep an off-platform `pg_dump`. Platform backups share the platform's fate, and that
  is one of the things a backup is for.
- Verify a dump with the existing drill rather than assuming: `scripts/p4/backup-restore-drill.sh`
  restores into a throwaway database and scans the dump to prove it contains no terminal output,
  file content or plaintext credential. Run it against a Railway dump after any schema change.
- Back up **before** running the retention prune — it is the only operation that deliberately
  deletes audit history.

## Audit retention

Not scheduled, on purpose (ADR 0016, reaffirmed in ADR 0020 §10). A mis-scheduled deletion of
the audit trail is worse than manual retention:

```bash
# 1. take a backup
# 2. report only (no --yes)
railway ssh --service central -- python -m app.retention prune
# 3. apply, once the numbers look right
railway ssh --service central -- python -m app.retention prune --yes
```

## Monitoring

The platform queries `healthcheckPath` **only while a deployment is going live** and never
again. With a single replica there is nothing to fail over to either. So an external check is
required, not optional:

| Check | Endpoint | Alert when | Runbook |
|---|---|---|---|
| Readiness | `https://<domain>/readyz` | not 200 (degraded now answers 503) | [db-exhaustion](./runbooks/db-exhaustion.md) |
| Liveness | `https://<domain>/healthz` | not 200 | — |
| Edge | `https://<domain>/edge-health` | not 200 | [railway-edge-502](./runbooks/railway-edge-502.md) |
| Certificate | the custom domain | expiry < 14 days | platform renews it; you still need to know if it does not |

Checking the edge separately from Central is what makes a 502 diagnosable in one step instead of
four.

## Capacity and latency

Two PRD numbers are deployment-dependent here and must be measured on the instance size and
region actually used, not inherited from the host measurements in `artifacts/p4/`:

- **NFR-001** (terminal added latency < 200 ms): report the network RTT and Cliora's added
  latency as two numbers. A user in Taiwan is ~40–60 ms from `asia-southeast1` before Cliora
  does anything.
- **NFR-003** (500 concurrent terminal WebSockets): re-run `scripts/p4/load/capacity.py`
  against the deployment. If the instance cannot reach 500, record the measured number and the
  size that would, and take a release decision — do not restate the threshold.

## Worker count

**Nothing in this repository sets one, so every deployment gets uvicorn's default of one.**
That default has never been chosen; it has only never been questioned.

`HD-09` re-measured `work-counts` after narrowing its row projection and coalescing
identical in-flight polls on a 2000-card project (`artifacts/hd/local/w6/perf-2000.md`):

| Workers | Concurrency 10 P95 | Concurrency 50 P95 | Concurrency 100 |
|---:|---:|---:|---|
| 1 | **132.18ms** | **401.45ms** | 500 of 500, P95 **802.96ms** |

The coalescing is deliberately only for simultaneous identical requests. It is not a
completed-result cache: the next poll recomputes, so task changes are not hidden for a TTL.
Counts and items still use the same attention policy.

**Pick a worker count from the whole workload, not this one endpoint.** D95 polls
`work-counts` every 20 seconds per open board tab and the measured single worker now meets
both the 10- and 50-concurrency budgets. Other CPU-bound endpoints and WebSocket capacity
still need the deployment-specific measurements above.

```bash
uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers "${WEB_CONCURRENCY:-4}"
```

Two constraints on the number:

- **Each worker holds its own connection pool.** `workers x pool_size` must stay under
  PostgreSQL's `max_connections`, which on a managed instance is often 100 or lower.
- **Scaling is sublinear.** Workers share cores and one database; do not assume a linear
  multiplier without measuring the deployed instance.
