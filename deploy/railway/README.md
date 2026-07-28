# Cliora on Railway (plan/07)

A second deployment target, alongside `deploy/compose/`. Same images, same security
properties, different mechanisms — because Railway provides none of the three things the
compose topology leans on: a dependency graph, a body-parsing health check, and a host
filesystem. `docs/deployment-railway.md` is the operator guide; ADR 0020 records the
decisions; this file is the map of what is here.

```
central.railway.json          Central service: start command, pre-deploy migration,
                              readiness, drain window
console.railway.json          Console service: static build + reverse proxy
console.Dockerfile            node build → nginx runtime (no node in the runtime image)
nginx.conf.template           edge config, envsubst-ed at container start (the
                              resolver addresses come from the nginx image's own
                              15-local-resolvers.envsh)
env.md                        the variable contract (there is no committable .env here)
```

Three services, one public origin:

```
browser ──HTTPS/WSS──▶ Railway edge ──▶ console (public)  ──private IPv6──▶ central ──▶ Postgres
                                         nginx + dist            /api, /ws
agentd on the user's own host ──outbound WSS──▶ same public origin
```

## The four things most likely to be got wrong

1. **`drainingSeconds` defaults to 0.** SIGTERM is followed immediately by SIGKILL, so
   `app.main._drain()` never completes and every deploy hands browsers the unexplained
   disconnect the drain exists to prevent. `central.railway.json` sets 25, which must stay
   above `CLIORA_SHUTDOWN_DRAIN_SECONDS` (15) — the same pairing as compose's
   `stop_grace_period`.
2. **Bind both families — `--host ""`, not `0.0.0.0` and not `::`.** The private network is
   IPv6, so the image's own `--host 0.0.0.0` is unreachable from `console`. But `--host ::`
   is not the answer either: asyncio sets `IPV6_V6ONLY` on an `AF_INET6` socket, so it
   refuses IPv4 no matter what `net.ipv6.bindv6only` says, and the platform health check
   then never reaches the process — no access-log line, and a 503 that came from the
   platform's proxy rather than from `/readyz`. An empty host is `None` to asyncio, which
   binds every family: one IPv6 socket for the private network, one IPv4 socket for the
   probe. The start command overrides the ENTRYPOINT.
3. **The upstream must be resolved per request.** Railway service IPs change on every
   deploy and nginx caches a static `upstream` for the life of the process, so a static
   upstream means "Central redeployed, console now 502s until it is also redeployed".
   Hence `resolver` + `proxy_pass http://$variable$request_uri`.
4. **One origin only.** `frontend/src/composables/useTerminalSession.ts` builds the
   terminal WebSocket URL from `location.host` and ignores `VITE_API_BASE_URL`. Split the
   frontend and API across two domains and everything works except terminals.

## Applying it

Config-as-code is per service — set each service's *Config as code path* to its JSON file
(Railway does not pick these up by name). Everything else is in `env.md`.

Before deploying: `make railway-check` (parity + baker tests) and, against the target
environment, `scripts/railway/check-env.sh`. After deploying:
`scripts/railway/verify-deployment.sh https://<domain>`.
