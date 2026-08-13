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
| `CLIORA_ARTIFACTS_DIR` | ❌ **leave unset** | — | The image sets it to `/srv/artifacts`, which is where the image puts the release. Override it only to point at a different directory, and only if something is mounted there — a wrong path means `/api/downloads` and `/api/install-script` answer 404 and the manifest goes empty (not 404) |
| `CLIORA_METRICS_ENABLED` | — | `false` | `true` without a ≥16-character `CLIORA_METRICS_SCRAPE_TOKEN` → startup fails (deliberate). The endpoint is also refused at the edge either way |
| `CLIORA_PROJECTS_ENABLED` | — | `false` | The V2 project layer. Off means every `/api/projects*` path answers 404 and the rail is unchanged. On grants **every role** a new read: project names, bound node names and absolute workspace paths. No per-project membership yet — see `docs/release-note-project-layer.md` |
| `CLIORA_AGENT_RUNS_ENABLED` | — | `false` | The V2.2+ runner layer, **nested inside `CLIORA_PROJECTS_ENABLED`** — on alone it does nothing, because `features` only carries `agent_runs` when both are on. Off means `/api/agents*`, `/api/runs*` and the secrets routes all answer 404 and the rail shows neither **Projects** nor **Agents**. ⚠️ **This row was missing until V2.3**, which is why a deployment can look "exactly like V1" after a successful V2 deploy: nothing is broken, the flags are simply off. On grants unattended execution on enrolled nodes — read `docs/release-note-agent-runner.md` and `docs/release-note-secrets-and-dispatch.md` before turning it on |
| `CLIORA_SESSION_TOKEN_TTL_H` | — | `24` | Hours a session credential stays valid (V2.1, ADR 0028). It is revoked the moment its session ends, so this only bounds a session left open for days. The credential is readable by anyone who can read the workspace — see `docs/security-review-v21.md` §1 |
| `CLIORA_METRICS_SCRAPE_TOKEN` | — | unset | See above |
| `CLIORA_SECRET_MASTER_KEY` | ✅ **when `CLIORA_AGENT_RUNS_ENABLED` is true** | unset | `openssl rand -base64 32`. Wraps every project secret's data key (ADR 0032). **Central refuses to start without a usable one when the runner layer is on**, and names which of four ways it is unusable — checked at startup rather than at first use, because the alternative fails on a node three minutes into a run. **Keep it somewhere other than the database backup**: the backup cannot restore a secret without it, and losing it loses every secret irrecoverably. Deliberately **not** the same key as `CLIORA_SECRET_ENCRYPTION_KEY` — the two rotate for different reasons, and sharing makes each rotation hostage to the other |
| `CLIORA_SECRET_MASTER_KEY_VERSION` | — | `1` | Which version a newly written secret is stamped with. Rotation is: old key into `CLIORA_SECRET_MASTER_KEY_V<n>`, new key into `CLIORA_SECRET_MASTER_KEY`, raise this. Existing rows keep opening under their own version |
| `CLIORA_GIT_SECRET_DELIVERY_ENABLED` | — | `false` | Whether the platform delivers git credentials to runners at all. **Off by default** (2026-08-13 ruling): at this stage git authentication is configured on the node by its owner. With it off, `git_pat`/`git_ssh_key` secrets cannot be created and a repository may only use the machine's existing credentials. ⚠️ The platform still **pushes** on a card's behalf either way — with this off it does so using a credential it cannot revoke, bounded by the five constraints in ADR 0031's amendment |

### Checking which layer is actually on

The two flags are not observable from the navigation alone — an empty rail looks the same
as a broken deploy. `GET /api/auth/me` answers it directly:

```
features: []                          both off — the console is V1, by design
features: ["projects"]                board on, runner off
features: ["projects","agent_runs"]   both on
```

`features` says what the **deployment** has; `permissions` says what the **person** may
do. The server checks both independently, and neither alone is authorization (ADR 0027).

Build-time only (Docker build args, read by `deploy/backend.Dockerfile`):

| Variable | Value | Notes |
|---|---|---|
| `AGENTD_RELEASE_BASE_URL` | unset, or `https://github.com/<owner>/<repo>/releases/download/v<version>` | **Unset (default)**: the image compiles `agentd` from the commit being deployed at the version in `daemon/VERSION`, and generates `checksums.txt` itself (ADR 0020 §8). **Set**: it downloads that release instead and **fails** unless every SHA-256 matches the release's own `checksums.txt`. Must be https, must be fetchable without credentials (a private repository's assets answer 404), and its version must equal `daemon/VERSION` or the digest lookup fails the build |

**The daemon version is not set here.** It lives in `daemon/VERSION`, next to the code it
names, and the release the image serves is built from that. Bump that file when the daemon
changes: reusing a version republishes different bytes under a version nodes already believe
they are running, and `agentd update` compares versions — so the fix would never reach the
fleet. `main.go`'s fallback and `make release`'s tag check are both pinned to that file, so it
cannot drift silently.

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
