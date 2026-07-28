# ADR 0020 — Railway deployment topology

- Status: accepted
- Date: 2026-07-27
- Supersedes: nothing. `deploy/compose/` and ADR 0017's deployment section remain the
  reference single-host topology; this adds a second target.
- Related: ADR 0011 (installer/artifacts), ADR 0016 (audit/retention), ADR 0017
  (release/update/deployment), ADR 0018 (observability, pool bounds, graceful shutdown)
- Plan: `plan/07/`

## Context

Cliora already deploys to a single host: nginx terminating TLS, one Central, one PostgreSQL,
migrations as a one-shot job (`deploy/compose/`, `docs/deployment.md`). Deploying the same
system to Railway is not a matter of pointing the same compose file at a PaaS, because the
compose topology leans on three things the platform does not provide:

1. **A dependency graph.** `depends_on: migrate: service_completed_successfully` is what stops
   a long-running container from migrating on boot.
2. **A health check that reads a body.** The compose check parses `/readyz` to compare the
   applied Alembic revision against head.
3. **A host filesystem.** `CLIORA_ARTIFACTS_DIR` points at a directory of release tarballs
   that `/api/downloads` and the release manifest read locally.

It also has platform behaviours that turn correct-looking configuration into incidents:
`drainingSeconds` defaults to **0** (SIGTERM then immediate SIGKILL), the private network is
IPv6, service IPs change on every deploy, and the deploy-time health check is not repeated
afterwards.

## Decision

### 1. Three services, one public origin

`console` (public: static console **and** reverse proxy for `/api` and `/ws`), `central`
(private only), `Postgres`. Region `asia-southeast1` for all three.

Single-origin is not a preference. `frontend/src/composables/useTerminalSession.ts` builds the
terminal WebSocket URL from `location.host` and ignores `VITE_API_BASE_URL`; the CSP is
`connect-src 'self' wss: ws:`; and `app/main.py` mounts no CORS middleware. The application
is same-origin by construction, and a split-origin deployment produces the worst kind of
failure — login, node list, file tree and search all work, and only terminals fail.

Rejected alternatives:

- **FastAPI serving the console** (`StaticFiles` + a header middleware). One service, no
  private-networking work. Rejected because it creates a *second* implementation of the
  security header set and the CSP, which would then drift from `deploy/nginx/nginx.conf`;
  the whole point of `scripts/p4/verify-edge.sh` was that a configuration nobody executes is
  a configuration nobody can trust, and two of them is worse than one. Retained as the
  fallback if the private-network reverse proxy proves unworkable, with the condition that
  the CSP must come from one shared constant.
- **Two public domains plus CORS.** Requires changing the terminal WebSocket URL construction,
  adding CORS, and widening `connect-src`. That is an architecture change, not a deployment
  option.

### 2. Single replica, deliberately

Both services run one replica. `app/services/registry.py` and
`app/services/terminal_relay.py` hold process-local state, so a second Central would own half
the daemon sockets and neither would know about the other's — a node would appear offline to
whichever replica served the request. This is a correctness constraint, not a cost decision
(tech §17.2, §17.3). `overlapSeconds` is 0 for the same reason: an overlap window means two
Centrals, briefly, for no benefit.

### 3. Readiness is expressed in the status code

`/readyz` now answers **503** when the database is unreachable or the applied migration is not
head. Previously readiness was in the body only, and Railway's health check — like most —
reads the status code and nothing else, so the rule "an unready Central does not serve" would
have existed only in the compose healthcheck.

This also settles a disagreement already in the tree: `scripts/p4/drills/db-exhaustion.sh`
tells the operator to expect 503s when the pool is saturated, while `_database_ready()`
swallowed the checkout timeout and returned 200. The drill's stated expectation had never
held.

`/healthz` is unchanged: liveness, no database opinion.

### 4. Migrations run as a pre-deploy step

`preDeployCommand: alembic upgrade head`. A non-zero exit stops the deploy and is not retried,
which is the property `service_completed_successfully` provides on compose. Migrations still
never run from the application lifespan.

### 5. The drain window is part of the configuration

`drainingSeconds: 25` against `CLIORA_SHUTDOWN_DRAIN_SECONDS=15`. The platform default of 0
would mean `app.main._drain()` never completes: browsers would not receive
`terminal.server_shutdown`, daemon sockets would not be closed with 1012, and in-flight daemon
requests would die with the process instead of failing as `NODE_OFFLINE`. NFR-002 says a
browser disconnect must not end a session; a deploy is the same promise from the other side.

### 6. The upstream address is resolved per request

The console's nginx reaches Central through a variable (`proxy_pass
http://$cliora_upstream$request_uri`) with a `resolver` supplied by the nginx image's own
`15-local-resolvers.envsh`. A static `upstream { server … }` is resolved once at config load
and cached for the process lifetime, so with per-deploy IPs the failure mode is "Central
deployed successfully; the console now 502s until it is also redeployed".

`$request_uri` is explicit because a variable `proxy_pass` no longer forwards the URI
implicitly, and the terminal handshake carries its single-use ws-ticket in the query string.

### 7. TLS: terminated at the platform edge, enforced at the console

Public traffic is HTTPS/WSS; the console redirects with 301 when `X-Forwarded-Proto` says
`http`, and continues to send HSTS and the full header set. The redirect is deliberately
**fail-open** — a request with no `X-Forwarded-Proto` is not redirected — so that
platform-internal probes are not redirected into a health-check failure. That is why
`scripts/railway/verify-deployment.sh` asserts the redirect against the real domain rather
than trusting the rule.

**Accepted boundary:** the private hops (edge → console → central, central → Postgres) are
plaintext inside the platform's network. This is accepted rather than papered over: adding TLS
inside the private network would mean managing certificates for internal names, and the
threat model that would address is "an attacker already inside the project's private
network". FR-CONN-002 and SEC-005 are about the public path, and that path is TLS-only.

### 8. Artifacts are put into the image at build time

`deploy/backend.Dockerfile` gained an optional step: given `AGENTD_VERSION` and
`AGENTD_RELEASE_BASE_URL`, it downloads that release, verifies every SHA-256 against the
release's own `checksums.txt`, and writes the files read-only into `/srv/artifacts`. With no
version it writes nothing and exits 0, so the compose build is unchanged and acquires no
build-time network dependency.

**Amended: a second route, for when the release cannot be fetched.** The download route needs
the assets to be reachable without credentials. This repository is private, so an
unauthenticated fetch of its release assets answers 404 — which fails the image build and
leaves `/api/downloads` and `/api/install-script` answering 404 permanently. With
`AGENTD_VERSION` set and **no** base URL, the image instead compiles `agentd` for both
architectures from `daemon/` at the commit being deployed and generates `checksums.txt` itself
(`scripts/railway/pack-agentd.sh`), using the same flags as `daemon/.goreleaser.yaml` so
`-trimpath` reproducibility (ADR 0017) still holds. Both routes remain supported; the gate is
inside a build stage so the no-op case still compiles nothing and downloads no modules.

Rejected for that case: publishing the assets to a second, public repository (an extra
artifact-hosting surface to keep in step with the private one, and a manual step per release),
and threading a read token into the build (a credential in the build environment and its layer
cache, to authenticate a fetch of bytes the build already has in source form).

What changes about the trust model, precisely. On the download route the digest check proves
the bytes match what the release published. On the build route there is no external digest,
because there is no external source — `checksums.txt` records what this build produced. The
guarantee the *node* depends on is unchanged either way: `deploy/install.sh` and
`daemon/internal/update` verify the tarball against that file before executing anything, which
is what tech §23 #12 requires. What the build route drops is the ability to detect a mismatch
between the image and a separately published release, which on this route does not exist.
Release signing remains the separate decision it already was (ADR 0017).

The cost, stated because it is paid on every build: the runtime stage's `COPY --from` cannot be
conditional, so the `golang` base image is pulled even when no version is set — including by
CI's image-exec check. That is the same class of dependency as the existing `python:3.12-slim`
and `uv` pulls, and unlike the thing the original no-op property protects: no *release* is
fetched at build time.

Rejected: a platform volume. A volume forbids replicas (already true here) but also makes
**every deploy incur downtime**, since two deployments cannot mount it at once — and it turns a
security-relevant directory into mutable state that no build reviewed. Baking costs one Central
redeploy per daemon release, which is a low-frequency event. `plan/07/04` records the volume
route as the fallback if artifacts ever need to change without a redeploy.

What the digest check proves is bounded and stated in `scripts/railway/bake_artifacts.py`: the
bytes match the digests the release published. It does not authenticate the release host —
the same trust model as `deploy/install.sh`.

Until a version is in the image, `CLIORA_ARTIFACTS_DIR` stays empty: `/api/downloads` and
`/api/install-script` answer 404 and the manifest answers `{"latest": null, "artifacts": []}`
rather than 404, so a daemon can still distinguish "no update available" from "no such
endpoint". The one-line install command must not be published while that holds.

### 9. `CLIORA_PUBLIC_BASE_URL` and `CLIORA_TOKEN_PEPPER` are one-way doors

The first is written into the installer and every node's config file; the second keys the hash
of every enrollment token and node credential. Both are cheap before the first node enrolls and
expensive afterwards. Therefore: bind the custom domain **before** enrolling anything, and
treat a pepper rotation as a fleet-wide re-enrollment, not a routine rotation.

### 10. Retention is still not scheduled

ADR 0016 decided that audit expiry is applied by an explicit operator command, because a
mis-scheduled deletion of the audit trail is worse than manual retention. Railway makes a cron
service trivial to add, which is precisely why this ADR records that we are **not** adding one.
Changing that requires amending ADR 0016 and adding a "successful backup first" precondition.

### 11. Metrics stay off, and stay off the edge

`CLIORA_METRICS_ENABLED=false`, and the console answers 404 for `/api/metrics` via an exact-match
location. If scraping is wanted, the scraper belongs inside the project and reaches Central over
the private network (ADR 0018).

### 12. Post-deploy monitoring is a deliverable, not an option

The platform health check runs at deploy time and is **not** repeated afterwards, and with one
replica there would be nothing to fail over to anyway. An external uptime check on `/readyz`
(now meaningful because of decision 3), `/healthz` and `/edge-health` is therefore part of the
deployment, not an optional extra.

## Consequences

- Two edge configurations now exist. They must not drift on the security policy, so
  `scripts/railway/check-edge-parity.sh` compares the CSP, the header set and the load-bearing
  numbers, and runs in `make check`. Behaviour is still asserted over the wire by
  `scripts/p4/verify-edge.sh` (host) and `scripts/railway/verify-deployment.sh` (platform).
- `/readyz` returning 503 changes what every readiness wait in the repo observes. All of them
  (`scripts/p4/verify-edge.sh`, `scripts/e2e/run-stack.sh`, `scripts/p4/backup-restore-drill.sh`,
  `scripts/p4/drills/*`, `scripts/p4/load/capacity.py`, `.github/workflows/p1.yml`) poll with
  `curl -fsS` or catch `URLError`, so they now wait for genuine readiness instead of mere
  liveness — strictly stronger, and no change was needed in them.
- NFR-001's 200 ms budget now includes a cross-sea RTT for users in Taiwan (~40–60 ms to
  Singapore) plus one extra proxy hop. This must be measured and reported as two numbers
  (network RTT vs Cliora's added latency), and a shortfall is a release decision or a named
  waiver — not a redefinition of the threshold.
- NFR-003's 500 concurrent terminal WebSockets becomes a function of the chosen instance size
  and must be re-measured on it.
