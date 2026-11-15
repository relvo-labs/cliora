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

## Trusted client IP: required post-deploy verification (#59)

The console uses nginx `real_ip_header X-Real-IP` with recursion off. Railway's
[public networking specifications](https://docs.railway.com/networking/public-networking/specs-and-limits)
identify `X-Real-IP` as the client's remote address. This is a deployment assumption that
must be verified over the live ingress, including custom and platform domains if both
are enabled. No live Railway request was observed while implementing this contract.

`CLIORA_TRUSTED_PROXY_CIDRS` on console is a comma/whitespace-separated numeric allowlist
of **Railway ingress peers**, rendered into `set_real_ip_from` by
`19-trusted-proxies.sh`. **Empty/unset is a startup and preflight error**: deploying
shared per-ingress-peer limits is forbidden. The error links to the runbook below. Do not
use `0.0.0.0/0`, `::/0`, or an entire private address space as a substitute for discovering
the actual ingress range. Obtain the supported source ranges from Railway and confirm
observed peers in console access logs (`peer=…`, the original socket address); a single
observed address alone does not establish a stable platform range.

Central's `FORWARDED_ALLOW_IPS` is a **different** comma-separated allowlist: only the
console nginx's private source IP(s), normally `/128` IPv6 and `/32` IPv4. It is required
by the start command. Determine it from console's private address and Central's observed
peer, verify it after either service redeploys, and update it before taking traffic if the
address changes. Uvicorn does not resolve service hostnames in this setting. Never use
`*`. CIDRs must be canonical networks with no host bits (e.g. `fd00:59::/64`,
not `fd00:59::1/64`); prefer the exact console `/128` or `/32`. Central must have no public domain or TCP proxy, and private peers other than the
allowlisted console must not be able to assert client addresses. The private-only topology
prevents bypassing nginx admission limits; the explicit uvicorn allowlist prevents another
private service from forging client identity. Platform health probes need no trust.

After nginx resolves the address it **overwrites**, rather than appends, both forwarding
headers with the single `$remote_addr`. Application handlers consume only Starlette's
client host. All admission limits match the [Compose table](deployment.md#client-ip-and-edge-admission-limits-59).

<a id="trust-upgrade-runbook-59"></a>
## Trust upgrade runbook (#59)

This change requires coordinated configuration before code promotion. A healthy
`/readyz`, `/edge-health` or `/edge-client-ip` does **not** establish Central's client
identity. Keep a maintenance/ingress admission gate closed to ordinary clients until
both protocols pass from **two independent public egresses**. Allow only the operator's
probes through that gate. Do not disable the approved limits to perform the upgrade.

1. **Hold automatic promotion for both services.** Stop push-triggered platform deploys
   and variable-triggered automatic restarts/promotion while preparing the change. Record
   the previous immutable image/config revisions and both current allowlists privately.
   Drain existing connections or hold reconnects behind the maintenance gate. Keep
   Central private, with no public domain or TCP proxy, throughout the operation.
2. **Obtain both allowlists before upgrading.** Get the supported ingress source ranges
   from Railway, and verify observed console socket peers (`peer=…` in console logs, or
   private socket inspection on the old image). Obtain console's allocated private
   IPv4/IPv6 source addresses and confirm the peer Central actually receives. Record
   which address belongs to which hop; one observed ingress IP is not proof of a stable
   platform range. If either set cannot be established, keep the old deployment held and
   stop the upgrade. Never substitute all private space or global trust.
3. **Set variables before deploying the candidate.** On console set nonempty
   `CLIORA_TRUSTED_PROXY_CIDRS` to the verified Railway ingress ranges. On Central set
   `FORWARDED_ALLOW_IPS` to only the verified console source IPs (normally `/32` and
   `/128`, comma separated without whitespace). Reject host-bit CIDRs. Run
   `scripts/railway/check-env.sh --domain <domain>` against the staged variable set and
   `make railway-check` against the candidate revision. Changing variables must not
   automatically admit a partially upgraded pair of services.
4. **Deploy Central, then console, with traffic still held.** Central first installs
   the explicit console-only trust policy; console then installs real-IP resolution and
   the limits. The console entrypoint must reject absent/empty ingress trust. Wait for
   migration/readiness and edge health, but keep the admission gate closed. Confirm the
   newly deployed console's actual private source addresses: if allocation changed,
   perform the source-change procedure below before continuing. For initial provisioning
   where the future console IP is not allocated yet, first allocate/stage that service
   privately; if an exact future address is still unavailable, keep traffic held, observe
   its source after staging, and redeploy Central with that exact address before probes.
5. **Verify nginx and Central HTTP + WebSocket scopes from two egresses.** Use the
   bounded, operator-only log procedure below. Independently establish each probe
   client's public source address; never learn it from our echo. Confirm Railway replaces
   caller-supplied `X-Real-IP`, and that console's original `peer=…` belongs to its verified
   ingress range. Every HTTP and WS probe must appear at Central with that egress address,
   including forged-header probes. A missing record, a console/ingress peer address, an
   unexpected third address or a skipped check blocks admission. Also check that a request
   from a different private service cannot assert the forwarded client identity.
6. **Finish acceptance, then admit traffic.** On disposable staging run the online limit
   probe from the Compose guide, including 51 distinct enrollments, 50 authenticated and
   registered/heartbeating nodes / distinct 51st 429, HTTP bursts,
   generic API and terminal exclusions. Measure normal login and WS handshake latency.
   Keep the default 10+10 database pool: the probe waits for `node.registered` after each
   authentication, avoiding the pre-registration idle-transaction issue [#183](https://github.com/relvo-labs/cliora/issues/183). Confirm all
   probe sockets/tasks are closed and nodes/credentials/enrollment are removed/revoked.
   Save the two-egress HTTP/WS receipts/log verdicts, peer-range evidence and deployed
   revisions. Remove temporary probe access, then open admission and restore automatic
   promotion only if it preserves this coordinated gate for future source changes.

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

Both must exit 0 (six correlated scopes each). To check the untrusted private-peer boundary,
run `central_client_probe.py send http://<central-private-host>:8080 <actual-private-peer-IP>
<receipt-path>` from a different private service outside `FORWARDED_ALLOW_IPS`, then verify
its receipt against the same Central logs. Despite the forged headers, all six logged
scopes must retain that private peer's real address. This uses only private networking.
Where the client's machine already has a
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

### Console source-IP changes and routine redeploys

Treat every console redeploy as a potential source-address change; health and the nginx
echo may stay green while Central sees console's address. Hold automatic promotion and
admission first. Obtain the new exact private address(es); stage them alongside the old
ones in Central's `FORWARDED_ALLOW_IPS` **before** switching if the platform allocates them
in advance. Otherwise stage console with admission held, inspect its actual source, then
update/redeploy Central. Never widen to a whole unrelated private subnet to bridge the gap.
Repeat the two-egress HTTP/WS checks after either service changes. Once no old console
connections remain, remove obsolete addresses, redeploy Central, and repeat the scope
checks before opening admission. Apply the same ordering to an ingress-range change:
stage verified replacement ranges, verify new peers and two-egress scopes, then remove
retired ranges. Missing trust stays a failed deployment.

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
redeploys. `watchPatterns` can restart services independently, so a push or a green health
check must not automatically promote an unverified console/Central pair.

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
last known hardened **code/start configuration first**, retaining the verified nonempty
ingress trust and console-source variables while any running image still consumes them.
Removing variables first can prevent candidate images from starting or silently revert an
older edge to shared budgets. Roll back Central and console as a coordinated pair, inspect
console's actual source again, update Central's exact allowlist if it changed, and repeat
both egresses' HTTP/WS scope checks before admitting traffic. A revision predating these
limits or using wildcard uvicorn trust is not an acceptable promoted rollback target;
keep maintenance held and choose a hardened compatible target or repair forward.

Only after the selected pair is running and verified may obsolete console addresses or
retired ingress ranges be removed, one hop at a time. Redeploy their consumer and recheck
both protocols after each cleanup. Never clear Railway's ingress trust while the edge
still enforces per-client limits, and never remove `FORWARDED_ALLOW_IPS` while the selected
start command requires it. This repair introduces no schema change; no migration downgrade
is needed for its rollback. Rehearse upgrade, console-source change and rollback in staging
with the same receipts before the production operation.

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
