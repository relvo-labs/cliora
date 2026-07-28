# Railway variable contract (RW-06)

There is no committable `.env` for this deployment — variables live in the platform — so the
contract is this file plus `scripts/railway/check-env.sh`, which enforces it before a deploy.
That script prints variable *names* and the property that failed, never values.

Two rules apply to everything below:

- **Secrets arrive from the environment.** The images contain none (tech §23 #4), and with
  `CLIORA_ENVIRONMENT=production` Central refuses to start on the development defaults, so a
  forgotten value is a failed deploy rather than a forgeable token.
- **Two values are one-way doors.** `CLIORA_TOKEN_PEPPER` and `CLIORA_PUBLIC_BASE_URL` are
  cheap to set and expensive to change; see the table.

## Service: `central`

Private only — **do not give this service a public domain.** A public domain would expose
`/readyz` and `/api/metrics` directly, bypassing the console's 404 and no-log rules.

| Variable | Required | Value | Getting it wrong |
|---|:--:|---|---|
| `CLIORA_ENVIRONMENT` | ✅ | `production` | Anything else disables the dev-secret refusal, so a placeholder JWT secret can reach production |
| `CLIORA_DATABASE_URL` | ✅ | `postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.POSTGRES_PASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}` | Railway's own `DATABASE_URL` is `postgresql://` and fails at startup with a driver error that never mentions the variable. Reference variables are **not** percent-encoded, so a password containing `@` or `:` yields a URL that parses and points at the wrong host — `check-env.sh` rejects both |
| `CLIORA_JWT_SECRET` | ✅ | `openssl rand -base64 48` | Left at the default → startup fails (deliberate). Rotating invalidates every live login; routine |
| `CLIORA_TOKEN_PEPPER` | ✅ | `openssl rand -base64 48` | **One-way door.** Rotating invalidates every enrollment token *and every node credential*: the whole fleet must re-enroll |
| `CLIORA_PUBLIC_BASE_URL` | ✅ | `https://<custom domain>` | **One-way door.** It is written into the installer and into every node's `/etc/agentd/config.yaml`; a platform-generated `*.up.railway.app` value means re-registering every node when the real domain arrives |
| `PORT` | ✅ | `8080` | Must equal the console's `CLIORA_BACKEND_PORT`, or every `/api` and `/ws` request answers 502 |
| `CLIORA_SHUTDOWN_DRAIN_SECONDS` | — | `15` (default) | Must stay **below** `drainingSeconds` in `central.railway.json` (25), or SIGKILL lands mid-drain and every deploy disconnects browsers without explanation |
| `CLIORA_ARTIFACTS_DIR` | — | empty, or `/srv/artifacts` once a release is baked in | Empty means `/api/downloads` and `/api/install-script` answer 404 and the manifest is empty (not 404). That is the documented pre-RW-08 state: correct, but the one-line install command must not be published while it holds |
| `CLIORA_METRICS_ENABLED` | — | `false` | `true` without a ≥16-character `CLIORA_METRICS_SCRAPE_TOKEN` → startup fails (deliberate). The endpoint is also refused at the edge either way |
| `CLIORA_METRICS_SCRAPE_TOKEN` | — | unset | See above |

Build-time only (Docker build args, read by `deploy/backend.Dockerfile`):

| Variable | Value | Notes |
|---|---|---|
| `AGENTD_VERSION` | e.g. `1.2.3`, or unset | Unset = no artifacts baked in. Set = the build downloads that release and **fails** unless every SHA-256 matches the release's own `checksums.txt` |
| `AGENTD_RELEASE_BASE_URL` | `https://github.com/<owner>/<repo>/releases/download/v<version>` | Required when `AGENTD_VERSION` is set. Must be https |

## Service: `console`

Public. This is the only service with a domain.

| Variable | Required | Value | Getting it wrong |
|---|:--:|---|---|
| `PORT` | ✅ | `8080` | The port nginx listens on, interpolated into the config at start |
| `CLIORA_BACKEND_HOST` | ✅ | `central.railway.internal` | A typo makes every `/api` and `/ws` request 502; a public hostname would route control-plane traffic back out through the internet |
| `CLIORA_BACKEND_PORT` | ✅ | `8080` | See `central.PORT` |
| `VITE_PRODUCT_NAME` | — | `Cliora` | Baked in by Vite at build time; changing it requires a rebuild |
| `VITE_API_BASE_URL` | ❌ **leave unset** | — | The one that half-works: API calls go to the other origin while the terminal socket stays on this one (it is built from `location.host`), so login, node list and file tree all work and only terminals fail |

## Service: `Postgres`

| Setting | Value | Notes |
|---|---|---|
| Version | 16 | Matches CI and the compose topology |
| Region | same as `central` | Cross-region means every query pays an RTT |
| Public TCP proxy | off | Enable only for a one-off task, and turn it off afterwards |
| Backups | platform backups **plus** an off-platform `pg_dump` | Platform backups share the platform's fate, and that is one of the things a backup is for |

Confirm on first use and record here: the exact variable names this service exposes, and its
`max_connections` (`SHOW max_connections;`). Central's pool is 10 + 10 overflow per replica;
if `max_connections` cannot cover ~60, lower `db_pool_size`/`db_max_overflow` **and note it**,
because those two values are the denominator of the `database_pool_usage` metric and its
pool-exhaustion alert (ADR 0018).

## Not variables, but part of the same contract

| Setting | Where | Value |
|---|---|---|
| `drainingSeconds` | `central.railway.json` | 25 (> `CLIORA_SHUTDOWN_DRAIN_SECONDS`) |
| `overlapSeconds` | both services | 0 — a second Central would hold half the daemon sockets, and the registry is process-local |
| Replicas | both services | 1, for the same reason |
| `healthcheckPath` | `central` | `/readyz` (503 when degraded, so the status code carries readiness) |
| `healthcheckPath` | `console` | `/edge-health` (answers without depending on Central) |
| Config as code path | each service's settings | `deploy/railway/central.railway.json` / `deploy/railway/console.railway.json` |

## Do not set

- `CLIORA_P0_*` — the endpoints were removed in P4-07. `Settings` has `extra="ignore"`, so a
  leftover value is silently accepted and does nothing, which is worse than an error: it
  reads as if something is enabled.
- Any timeout, queue bound or session limit. Those defaults are the measured values recorded
  in ADR 0013/0015/0017/0018; changing them here is changing a product limit without changing
  the ADR that justifies it.
