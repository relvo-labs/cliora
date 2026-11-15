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

Hold automatic promotion and external traffic while provisioning. Complete the
[trust upgrade runbook](#trust-upgrade-runbook-59) before admitting traffic; it applies
to first deployment too. Two steps below are one-way doors.

1. **Create the project and the three services** in the same region (`asia-southeast1`):
   `Postgres`, `central` (Dockerfile), `console` (Dockerfile), and **nothing else in this
   environment** — the client-IP trust depends on it (see
   [below](#trusted-client-ip-railway-edge-contract-184)). Set each service's
   *Config as code path*:
   - `central` → `deploy/railway/central.railway.json`
   - `console` → `deploy/railway/console.railway.json`
2. **Bind the custom domain to `console`** and wait for the certificate.
   *Do this before step 4.* `CLIORA_PUBLIC_BASE_URL` is written into every node's config file.
3. **Give `central` no public domain, and neither `central` nor `console` a TCP proxy.**
   Central is reached only over the private network; a TCP proxy bypasses Railway's HTTP
   edge and the header overwrite the trust relies on.
4. **Set the variables** per [`deploy/railway/env.md`](../deploy/railway/env.md), including
   `CLIORA_TRUSTED_PROXY_CIDRS=railway-edge` on console and
   `FORWARDED_ALLOW_IPS=railway-private-environment` on Central, then check them and the
   topology before deploying:
   ```bash
   scripts/railway/check-env.sh --domain cliora.example.com
   scripts/railway/check-trust-topology.sh --environment production --console-service console
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

<a id="trusted-client-ip-railway-edge-contract-184"></a>
<a id="trusted-client-ip-required-post-deploy-verification-59"></a>
## Trusted client IP: the Railway edge contract (#59, #184)

The client address crosses two hops: Railway's HTTP edge → console nginx → Central. Railway
does not publish stable or exclusive source ranges for its edge. The `100.64.0.0/10` peers
seen in console logs (`peer=…`) are not a contract and may change, even across redeploys.
There is no signed or authenticated ingress header and no mTLS identity. An allowlist of
edge addresses therefore cannot be obtained. An allowlist of console's private address
may go stale on every console redeploy. So **neither hop is configured by address.** Each
opts into a named platform contract instead:

| Service | Variable | Value | Effect |
|---|---|---|---|
| console | `CLIORA_TRUSTED_PROXY_CIDRS` | `railway-edge` | The startup renderer (`19-trusted-proxies.sh`) emits `set_real_ip_from 0.0.0.0/0;` and `set_real_ip_from ::/0;`. With `real_ip_header X-Real-IP` and `real_ip_recursive off`, nginx takes the client from `X-Real-IP`, whichever peer delivered the request |
| central | `FORWARDED_ALLOW_IPS` | `railway-private-environment` | The startCommand maps it to uvicorn's `--forwarded-allow-ips=*`, so Central accepts console's forwarded headers without knowing console's private address |

**What this trust rests on.** All of it, and nothing else:

1. **Railway's documented overwrite.** The HTTP edge replaces `X-Real-IP`,
   `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Forwarded-Host` on every request, for
   custom domains and `*.up.railway.app` alike. Copies sent by the caller do not survive.
   Railway documents `X-Real-IP` as the client address
   ([public networking specifications](https://docs.railway.com/networking/public-networking/specs-and-limits)).
2. **Environment isolation.** The project/environment private network is the boundary;
   other environments and projects cannot reach it. Traffic over `*.railway.internal` does
   **not** pass the edge and is not sanitized, so any service in the environment can
   claim any client address to console or Central.
3. **No TCP proxy on console or Central.** A TCP proxy bypasses the HTTP edge. A client
   could then send its own `X-Real-IP`.
4. **No other services in the environment:** only `Postgres`, Central and console.
5. **Central has no public domain** (service or custom), so only console reaches it.
6. **Railway's own caveat: these specifications may change.** The platform does not
   enforce 2–5 for us, and nothing signs the header. Re-check after any Railway networking
   announcement.

**Any of these changes breaks the trust:** adding a service to the environment (including
a debugging shell, worker or metrics scraper), adding a TCP proxy to console or Central,
or giving Central a domain. Run the [topology check](#pre-deploy-trust-topology-check)
again after any such change and before every promotion. Put other workloads in a separate
environment. A temporary Postgres TCP proxy (first-deployment step 6) reaches only
Postgres, which sends no HTTP; still turn it off afterwards.

The keywords are the **only** way to express global trust. An empty or unset value still
refuses startup and preflight. Hand-typed `0.0.0.0/0`, `::/0` and (on Central) `*` are
rejected, so global trust is always a recorded decision, never a typo or a default.
Numeric lists of canonical networks, with no host bits, are still accepted on both hops
for a topology where the peer addresses really are known. On Railway they are not.

After nginx resolves the client, it **overwrites** (does not append) both forwarding
headers sent to Central with the single `$remote_addr`. Application handlers use only
Starlette's client host. All admission limits match the
[Compose table](deployment.md#client-ip-and-edge-admission-limits-59).

**Cloudflare caveat (proxied custom domain).** For requests from Cloudflare's published
**IPv4** ranges, Railway derives `X-Real-IP` from `CF-Connecting-IP`. That handling is not
documented for Cloudflare's IPv6 ranges. If Cloudflare reaches Railway over IPv6,
`X-Real-IP` may hold a Cloudflare address. Clients behind it would then share one rate-limit
budget and one audit identity. With an orange-cloud domain, include an IPv6-capable egress
in the two-egress verification, or use DNS-only.

<a id="pre-deploy-trust-topology-check"></a>
### Pre-deploy trust topology check

```bash
scripts/railway/check-trust-topology.sh --environment production --console-service <console service name>
# staged, not yet deployed variables: add --central-vars central.json --console-vars console.json
# keep the topology responses (never variables) as evidence: add --record "$OUT/topology.json"
```

The check is read-only. It uses the logged-in `railway` CLI to find the linked project, or
`--project-id`. It then reads Railway's public GraphQL API with that CLI session's account
token, or with `RAILWAY_API_TOKEN`. It **fails** unless all of these hold:

- the environment holds exactly `Postgres`, Central and console. Service names default to
  `Postgres`/`central`/`console`; override them with `--*-service` or
  `CLIORA_RAILWAY_*_SERVICE`;
- neither console nor Central has a TCP proxy;
- Central has no service or custom domain;
- Central's `FORWARDED_ALLOW_IPS` is exactly `railway-private-environment`, and console's
  `CLIORA_TRUSTED_PROXY_CIDRS` is exactly `railway-edge`. These are the live values, or the
  staged files you pass.

Exit 1 means a condition does not hold. Exit 2 means the facts could not be established:
the CLI is not logged in, the API returned an error, or the response shape was not
recognised. Exit 2 is a failure, never a pass. Variable values are never printed.
The queries follow Railway's documented public API and have been tested only against
fixtures. If a live response is not recognised, the check blocks the promotion: fix the
parser using a recorded response, and do not bypass the check.

<a id="trust-upgrade-runbook-59"></a>
## Trust upgrade runbook (#59, #184)

This applies to first deployment, to the upgrade from the pre-#59 pair, and to every
promotion. A healthy `/readyz`, `/edge-health` or `/edge-client-ip` does **not** establish
Central's client identity. Keep a maintenance/ingress admission gate closed to ordinary
clients until both protocols pass from **two independent public egresses**. Let only the
operator's probes through that gate. Do not disable the approved limits to perform the
upgrade.

1. **Hold automatic promotion for both services.** Stop push-triggered platform deploys
   and variable-triggered automatic restarts or promotion. Privately record the previous
   immutable image and config revisions and variable values. Keep Central private, with
   no public domain or TCP proxy, throughout.
2. **Set both keyword variables.** On console:
   `CLIORA_TRUSTED_PROXY_CIDRS=railway-edge`. On Central:
   `FORWARDED_ALLOW_IPS=railway-private-environment`. Neither depends on an address, so
   nothing needs to be discovered first, and they survive redeploys. Changing variables
   must not automatically admit a partially upgraded pair.
3. **Check before deploying.** Run `scripts/railway/check-env.sh --domain <domain>`,
   [`scripts/railway/check-trust-topology.sh`](#pre-deploy-trust-topology-check) (with
   `--central-vars`/`--console-vars` while the values are only staged), and
   `make railway-check` against the candidate revision. Any failure stops the upgrade.
4. **Deploy Central, then console, with traffic still held.** Central installs the
   keyword trust first; console then installs real-IP resolution and the limits.
   Central-first does not widen trust beyond today's: the pre-#59 Central (`ad5ff52`)
   already runs `--forwarded-allow-ips="*"`, and the old console's appended chain begins
   with the edge-overwritten client. Wait for migration, readiness and edge health, but
   keep the admission gate closed.
5. **Verify nginx and Central HTTP + WebSocket scopes from two egresses** with the
   bounded, operator-only log procedure below. Establish each probe client's public
   source address independently; never learn it from our echo. Every HTTP and WS probe,
   including those with forged headers, must reach Central with that egress address. Any
   of these blocks admission: a missing record, console's private address, an edge-range
   address (`100.64.…`), an unexpected third address, or a skipped check.
6. **Finish acceptance, then admit traffic.** On disposable staging, run the online limit
   probe from the Compose guide. It covers 51 distinct enrollments; 50 authenticated,
   registered and heartbeating nodes with a distinct 51st getting 429; HTTP bursts; and
   the generic API and terminal exclusions. Measure normal login and WS handshake latency.
   Keep the default 10+10 database pool: the probe waits for `node.registered` after each
   authentication, avoiding the pre-registration idle-transaction issue [#183](https://github.com/relvo-labs/cliora/issues/183). Confirm all
   probe sockets/tasks are closed and nodes/credentials/enrollment are removed/revoked.
   Save the two-egress HTTP/WS receipts and log verdicts, the topology-check output
   (`--record`) and the deployed revisions. Remove temporary probe access. Then open
   admission, and restore automatic promotion only if the topology check still runs
   before each promotion.

### Central scope verification without a public diagnostic endpoint

The nginx echo cannot detect Central ignoring forwarded headers. There is no existing
API response exposing Starlette's client scope. Instead, `central_client_probe.py` sends
three unique HTTP requests to nonexistent `/api/edge-client-probe/<uuid>` paths (404) and
three node WS handshakes to random UUIDs, receives the public challenge, and disconnects
without credentials or registration. It sends forged XFF/X-Real-IP variants. Neither path
returns client metadata. Pinned uvicorn 0.35.0 logs the **post-proxy-middleware** client
from that same scope for HTTP access and WebSocket acceptance. The verifier correlates
all six exact paths in Central's operator-only logs and rejects missing/wrong client IPs.
It does not inspect console logs as a substitute for Central logs.

Ensure Central's uvicorn HTTP access logs and `uvicorn.error` INFO WebSocket acceptance
logs are enabled for this bounded maintenance window. Collect plain-text Central logs
privately (operator terminal; bounded foreground command), for example:

```bash
timeout 180 railway logs --service central > "$OUT/central.log" 2>&1
```

While collection runs, execute from **each** independent egress, with separate output
directories (run from repository root, Python dependencies installed via uv):

```bash
scripts/railway/verify-client-ip.sh https://cliora.example.com <known-egress-IP> "$OUT/egress-a"
# Repeat from egress B with its own independently known IP and output directory.
```

Without `CLIORA_VERIFY_CENTRAL_LOG` this returns **3 / PENDING**, after checking nginx and
writing `central-client-receipt.json`; it is not a pass. Transfer both receipts to the
operator and, after Central log export, run:

```bash
uv run --project backend python scripts/railway/central_client_probe.py verify \
  "$OUT/egress-a/central-client-receipt.json" "$OUT/central.log"
uv run --project backend python scripts/railway/central_client_probe.py verify \
  "$OUT/egress-b/central-client-receipt.json" "$OUT/central.log"
```

Both must exit 0 (six correlated scopes each). There is no private-peer probe any more.
Under `railway-private-environment`, Central trusts every private peer **by design**. The
defence is that no other peer exists, and `check-trust-topology.sh` establishes that. Do
not add a probe service to the environment to test it: the probe itself would break the
trust it is testing. Where the client's machine already has a
live, operator-owned Central log collector file, setting `CLIORA_VERIFY_CENTRAL_LOG` lets
`verify-client-ip.sh`, `verify-deployment.sh` and `verify-edge.sh --online` perform the
send-and-verify sequence directly. `verify-deployment.sh` also needs
`CLIORA_VERIFY_EXPECTED_IP`; requested verification fails while Central evidence is pending.
Missing expected-IP configuration is reported as a skip and cannot satisfy this runbook.

This design adds no public information surface or authentication bypass. Keep exported
logs access-controlled, retain the correlated non-secret probe lines/receipts as evidence,
and remove other captured log data under the site's retention policy. If the deployment
has replaced uvicorn's log format or disabled these logs, restore the stated format during
maintenance or privately instrument the actual Central ASGI boundary: record only
`scope['type']`, the unique probe path and `scope['client']` after proxy middleware for
these six paths, then manually compare both protocols for both egresses. Remove that
instrumentation before admission. Do not replace Central with an echo upstream: that
would test another process's trust settings. No app code/instrumentation is shipped here.

### Routine redeploys and topology changes

The keywords name no address, so a redeploy that changes console's private address or the
edge's peer range needs no variable change. Before each promotion, run
`check-trust-topology.sh`; after either service deploys, repeat the two-egress HTTP/WS
checks. Both are cheap compared with a silently shared rate-limit budget.

A **topology change** is different. Adding a service to the environment, adding a TCP proxy
to console or Central, or giving Central a domain each removes one of the facts the trust
rests on. Before making such a change, hold admission and decide whether the change
belongs in a separate environment; it almost always does. If it has already happened,
undo it, rerun the topology check, and repeat the two-egress verification before
reopening. A change in Railway's published networking behaviour (the header overwrite or
environment isolation) needs the same review. Missing or failing trust stays a failed
deployment.

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

## Upgrading

Use the ordered [trust upgrade runbook](#trust-upgrade-runbook-59), including for routine
redeploys: the [topology check](#pre-deploy-trust-topology-check) before promotion, the
two-egress verification after it. `watchPatterns` can restart services independently, so
a push or a green health check must not automatically promote an unverified console/Central
pair.

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

For this edge change, hold automatic promotion and public admission first. Restore the
last known hardened **code/start configuration first**, and keep the keyword variables
while any running image still consumes them. Removing variables first can stop images
from starting, or silently revert an older edge to shared budgets. Roll back Central and
console as a coordinated pair. Then rerun the topology check and repeat both egresses'
HTTP/WS scope checks before admitting traffic.

Choose the target with care. Revisions from #181 up to this change **cannot run under the
keywords**. Their console refuses `railway-edge`. Their Central passes
`railway-private-environment` to uvicorn as an unmatched literal and trusts nobody, so
every client would appear as console's private address. Do not roll back into that range.
A revision predating the #59 limits is not an acceptable promoted rollback target either.
Keep maintenance held and choose a revision that contains this change, or repair forward.

Never clear console's `CLIORA_TRUSTED_PROXY_CIDRS` while the edge still enforces
per-client limits, and never remove `FORWARDED_ALLOW_IPS` while the selected start command
requires it. This repair introduces no schema change, so its rollback needs no migration
downgrade. Rehearse upgrade and rollback in staging with the same receipts before the
production operation.

Application rollback is cheap; schema rollback is not. The general database procedure below
is separate from this trust-only repair.

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
