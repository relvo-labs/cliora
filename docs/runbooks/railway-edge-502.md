# Runbook — the console answers 502 (Railway)

**Symptom:** the console loads, but `/api` calls fail and terminals do not connect. Or
everything fails with 502. Frequently noticed right after a Central deploy.

**What this is usually not:** a Central fault. Central will often be perfectly healthy. The four
steps below are ordered by how often each turns out to be the cause, and step 1 exists so that
step 2 onwards is not wasted effort.

## 1. Which service is broken?

```bash
D=https://cliora.example.com
curl -sS -o /dev/null -w 'edge   %{http_code}\n' "$D/edge-health"   # console, no Central involved
curl -sS -o /dev/null -w 'ready  %{http_code}\n' "$D/readyz"        # Central, through the console
```

| `/edge-health` | `/readyz` | Meaning | Go to |
|---|---|---|---|
| 200 | 502 | The console is up; it cannot reach Central | step 2 |
| 200 | 503 | The console reaches Central; **Central is not ready** — database or migration | step 5 |
| not 200 | — | The console itself is down or misconfigured | step 4 |

## 2. Did Central just deploy?

The most common cause. nginx resolves a static upstream once and caches it, and a Railway
service's private IP changes on every deploy — so a Central rollout can leave the console
talking to an address that no longer exists.

The shipped config avoids this (`resolver` plus `proxy_pass` through a variable, ADR 0020 §6).
Confirm the deployed config is the shipped one:

```bash
railway ssh --service console -- grep -n 'proxy_pass\|resolver' /etc/nginx/nginx.conf
```

Expect `resolver <addresses> valid=10s ipv6=on;` and
`proxy_pass http://$cliora_upstream$request_uri;`. If instead you see an `upstream` block or a
literal hostname in `proxy_pass`, that is the bug — restore the template. Redeploying the
console clears the symptom immediately and hides the cause, so check first.

If `resolver` is present but empty, `NGINX_ENTRYPOINT_LOCAL_RESOLVERS` is not set on the
service; nginx then fails to start rather than serving, so this shows up as step 4.

## 3. Are the two services talking about the same port?

```bash
railway variables --service console | grep CLIORA_BACKEND
railway variables --service central | grep '^PORT'
```

`CLIORA_BACKEND_PORT` must equal Central's `PORT`, and `CLIORA_BACKEND_HOST` must be
`central.railway.internal`. `scripts/railway/check-env.sh` catches both before a deploy.

Note that a `/etc/hosts` entry cannot be used to work around a wrong hostname here: the config
resolves the upstream at request time through the resolver, which does not consult
`/etc/hosts`.

## 4. Is the console container actually serving?

```bash
railway logs --service console | tail -40
```

Two failures produce a container that never serves:

- `invalid parameter` / `host not found in resolver` — the rendered config has an empty
  `resolver`. Set `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1`.
- nothing rendered at all — `NGINX_ENVSUBST_OUTPUT_DIR` is not `/etc/nginx`, so the template
  landed in `conf.d/` where a full `http {}` block is invalid.

## 5. Is Central bound to the right interface?

If `/edge-health` is 200 and Central's own logs say "Uvicorn running" while every proxied
request 502s, Central is almost certainly listening on IPv4 only. The private network is IPv6.

```bash
railway ssh --service central -- sh -c 'ss -ltn 2>/dev/null || netstat -ltn'
```

Expect `:::8080`. If it shows `0.0.0.0:8080`, the start command is not the one in
`deploy/railway/central.railway.json` — it must pass `--host ::`. This happens when the service
has a start command typed into its settings that overrides config-as-code.

## 6. Central answers 503

Not an edge problem. `/readyz` returning 503 means the database is unreachable **or** the applied
migration is not head (ADR 0020 §3). The body says which:

```bash
curl -sS "$D/readyz"
# {"status":"degraded","database":false,...}  → database: see runbooks/db-exhaustion.md
# {"status":"degraded","database":true,...}   → migration: the pre-deploy step did not run
railway ssh --service central -- alembic current
```

An unmigrated schema after a deploy means `preDeployCommand` is missing from the service's
config — the deploy should have been blocked. Restore
`deploy/railway/central.railway.json` and redeploy; Central will stay out of rotation until the
migration lands, which is the intended behaviour, not a second fault.

## After the incident

If the cause was configuration rather than the platform, add the case to
`scripts/railway/check-env.sh` or `scripts/railway/check-edge-parity.sh`. Every check in those
two scripts exists because something got past a reading of the config.
