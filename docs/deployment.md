# Deploying Cliora

Reference topology: **one host**, nginx terminating TLS, one Central, one PostgreSQL.

Stated plainly because it constrains what you can do with it: Central's connection
registry and terminal relay are **process-local** (see the module docstrings in
`app/services/registry.py` and `app/services/terminal_relay.py`). A second backend
replica would hold half the daemon sockets, and neither replica would know about the
other's — a node would appear offline to whichever replica served the request. Scaling out
needs a shared store for both, which is not in the MVP. Scale up, not out.

## Prerequisites

- Docker with Compose v2
- A TLS certificate and key for the hostname daemons will connect to
- DNS pointing at the host (daemons connect *outbound* to Central; Central never dials a
  node, so no inbound firewall rules are needed on the node side)

## First deployment

```bash
cd deploy/compose
cp .env.example .env
$EDITOR .env                 # every REQUIRED value; there are no usable defaults
docker compose up -d --build
```

`docker compose up` enforces the ordering itself:

```
postgres healthy → migrate runs to completion → backend starts → healthy → nginx serves
```

The `migrate` service is one-shot, and `backend` declares
`depends_on: migrate: service_completed_successfully`. This is why migrations are not run
from the application's lifespan: a replica that migrates on boot races its siblings, and a
restart becomes an unplanned schema change.

Getting the order wrong is *detected*, not merely discouraged: `/readyz` compares the
applied Alembic revision against the expected head and reports `degraded` with
`"migration": false` when they differ. The backend healthcheck uses `/readyz`, so a
container started against an unmigrated database never takes traffic.

Create the first administrator once the stack is up:

```bash
docker compose exec backend python -m app.bootstrap create-admin --username admin
# reads CLIORA_ADMIN_PASSWORD from the environment so it stays out of shell history
```

## Secrets

Everything sensitive arrives from the environment; the images contain no credential
(tech §23 #4). With `CLIORA_ENVIRONMENT=production`, `Settings` **refuses to start** on
the development defaults for `CLIORA_JWT_SECRET` or `CLIORA_TOKEN_PEPPER`, so a forgotten
value is a failed deploy rather than a forgeable token in production.

Rotation is not symmetric, and the difference matters:

| Secret | Rotating it costs |
|---|---|
| `CLIORA_JWT_SECRET` | Every live session is invalidated; users log in again. Routine. |
| `CLIORA_TOKEN_PEPPER` | Every enrollment token **and every node credential** stops verifying. **Every node must re-enroll.** Treat as a one-way door, not a rotation. |

## TLS and WebSockets

`deploy/nginx/nginx.conf` terminates TLS, redirects HTTP with 301, and proxies `/api` and
`/ws` to the backend. Two settings there are easy to get wrong and expensive to diagnose:

- **`proxy_read_timeout 3600s` on `/ws/` must stay above uvicorn's `ws_ping_interval`**
  (default 20 s). Not "above human idle time" — that was this document's original claim and
  it was wrong: uvicorn's server pings travel through the proxy and reset the timeout on
  every one, so an idle terminal survives even nginx's 60 s default. `verify-edge.sh` proved
  this by passing with `proxy_read_timeout 20s` before the check was corrected.

  The real failure mode is narrower and nastier: raise `ws_ping_interval` above this timeout
  (or lower this below it) and **every** WebSocket dies on a fixed cycle regardless of
  activity — terminals and daemon connections alike. Keep a wide margin.
- **`client_max_body_size 16m`.** At or above the 8 MiB filesystem contract. A lower value
  turns a legal file read into a 413 from a component that knows nothing about the
  protocol.

The CSP allows **no external origin**. It also carries `worker-src 'self' blob:`, which
Monaco requires for its language workers — without it the editor renders blank with only a
console error. If a CDN reference is ever reintroduced to the frontend, the page breaks
here rather than silently reaching a third party from an operator's browser.

`/api/metrics` is **refused at the edge** — nginx answers 404 for it via an exact-match
location, and `scripts/p4/verify-edge.sh` asserts that. It is off by default anyway; when
enabled it should be reachable only by the scraper on the internal network (the
`observability` compose profile does exactly that).

That exact-match block has to exist. `location /api/` is a prefix match, so for a while this
was a comment claiming the endpoint was not exposed while the config proxied it through.

## Upgrading

```bash
cd deploy/compose
git pull
docker compose build
deploy/migrate.sh                 # or: docker compose run --rm migrate
docker compose up -d
```

`docker compose up -d` sends SIGTERM and waits `stop_grace_period` (30 s, above the 15 s
`CLIORA_SHUTDOWN_DRAIN_SECONDS`). During the drain Central:

1. sends every subscribed browser a `terminal.server_shutdown` control frame carrying
   `reason` and `session_preserved: true`, so the console can say "reconnecting" instead
   of showing an unexplained disconnect;
2. closes daemon sockets with 1012, which their existing backoff handles (FR-CONN-003);
3. fails in-flight daemon requests with `NODE_OFFLINE` rather than leaving them to time
   out after the process is gone.

**No CLI session is terminated by a deploy.** NFR-002 says a browser disconnect must not
end a session; a Central restart is the same promise from the other side. The drain never
touches tmux and never sends `session.stop` — asserted by
`backend/tests/test_shutdown_drain.py::test_the_drain_sends_no_stop_to_any_node`.

Keep `stop_grace_period` above `CLIORA_SHUTDOWN_DRAIN_SECONDS`. If SIGKILL lands mid-drain
you get exactly the unexplained disconnect the drain exists to prevent.

## Rollback

Application rollback is cheap; schema rollback is not. Decide which you need.

**Application only** (the usual case — a bad build, a UI regression):

```bash
cd deploy/compose
git checkout <previous-tag>
docker compose build && docker compose up -d
```

Safe whenever the previous version understands the current schema. Migrations `0008`–`0011`
are additive, so the previous release generally runs fine against the newer schema — which
is why this path should be tried first.

**With a schema downgrade** (only when the new revision is itself the problem):

```bash
deploy/migrate.sh downgrade <revision>   # interactive; asks you to retype the revision
```

Every P4 migration is reversible and each has an up→down→up test. **Reversible is not
harmless**: a downgrade drops the columns and tables the newer revision added, including
any rows written since the upgrade. Each migration's `downgrade()` docstring states what
its own reversal loses. Read it before running this during an incident, and take a backup
first (`scripts/p4/backup-restore-drill.sh` shows the exact `pg_dump` invocation).

Order for a full rollback: stop the backend → downgrade → deploy the previous image →
verify `/readyz`.

## Backups

See `docs/runbooks/backup-restore.md` for frequency, retention, and the restore procedure.
One ordering rule belongs here too: **back up before running the retention prune**
(`python -m app.retention prune`). The prune is the only operation that deliberately
deletes audit history, and audit history is the thing you cannot reconstruct.

`scripts/p4/backup-restore-drill.sh` performs the whole cycle against throwaway databases
and verifies the restore — including a scan proving the dump contains no terminal output,
file content, or plaintext credential. Run it after any change to the schema or the backup
procedure.

## Health endpoints

| Endpoint | Use |
|---|---|
| `/healthz` | Liveness. The process is up. Says nothing about the database. |
| `/readyz` | Readiness. Database reachable **and** the applied migration matches head. This is the one to gate traffic on. |

## Observability

Off by default. To enable:

```bash
# .env
CLIORA_METRICS_ENABLED=true
CLIORA_METRICS_SCRAPE_TOKEN=<at least 16 characters>

docker compose --profile observability up -d
```

Enabling metrics without a token **fails at startup** — the endpoint is never served
unauthenticated. The token is deliberately not the `audit.view` permission: reusing it
would mean creating a service account that can read the audit trail in order to read
numbers, and Prometheus holds no user session (ADR 0018).

Alert rules are in `deploy/prometheus/alerts.yml`; every rule names its runbook in
`docs/runbooks/`. `scripts/p4/drills/` can trigger each alert in a drill environment so the
runbooks are exercised rather than assumed.

## Capacity

Measured limits and the evidence for them: `artifacts/p4/*/capacity.json`, produced by
`scripts/p4/load/capacity.py`. The harness README explains what each number proves and,
importantly, which paths a given run did **not** exercise.
