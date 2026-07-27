# Runbook — database pool exhaustion

**Alerts:** `ClioraDatabasePoolPressure` (warning, >80% checked out for 2 min),
`ClioraDatabasePoolExhausted` (critical, a checkout timed out),
`ClioraAuditWriteFailing` (critical — §8), `ClioraMetricPersistFailing` (warning — §9)
**Drill:** `scripts/p4/drills/db-exhaustion.sh`

---

## 1. Symptom

Requests wait for a database connection and, past `db_pool_timeout_seconds` (5 s), are
refused rather than left to hang. Users see `INTERNAL_ERROR` (503-class) with a
`request_id`.

The pool is bounded on purpose (`db_pool_size` 10 + `db_max_overflow` 10). Without the
bound and the timeout, saturation presents as requests that never return — far harder to
diagnose than ones that fail quickly and loudly.

## 2. Immediate impact

| | |
|---|---|
| Running CLI sessions | **Unaffected.** Terminal streaming does not touch the database. |
| Terminal input/output | Unaffected while the socket is up. |
| Everything else | Degrades: sign-in, session create/terminate, node list, audit, dashboard. |
| Node connections | **At risk.** The daemon handshake verifies a credential against the database, so a saturated pool eventually presents as a fleet-wide reconnect storm. |

That last row is why this runbook is upstream of `heartbeat-loss.md` and
`timeout-surge.md`: a database problem impersonates both.

## 3. Diagnose

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics \
  | grep -E 'database_pool_usage|database_pool_timeout_total'
```

| Pattern | Reading |
|---|---|
| `checked_out` pinned at `size`, timeouts rising | Genuine saturation. Continue below. |
| `checked_out` high, `overflow` > 0 | Working past the base pool into overflow — sustained load, not a spike. |
| `checked_out` high with low request volume | **A leak**: sessions are being held, not used. Look for a code path that opened a session without closing it. |
| Pool fine, requests still slow | Not the pool. See §7. |

Then look at the database itself:

```sql
-- Who is connected, and what are they doing?
SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state;
-- Anything long-running?
SELECT pid, now() - query_start AS age, state, left(query, 120)
FROM pg_stat_activity WHERE datname = current_database() AND state <> 'idle'
ORDER BY age DESC LIMIT 10;
-- Blocked on a lock?
SELECT * FROM pg_locks WHERE NOT granted;
```

A single slow query holding connections is the common case. `idle in transaction` is the
signature of a leak on our side.

## 4. Distinguish the three real causes

1. **Load** — request volume genuinely exceeds 20 concurrent database operations. Latency
   rises before timeouts appear; `http_request_duration_seconds` climbs across the board.
2. **A slow query** — one endpoint holds connections far longer than the rest. Find it by
   route: `cliora_http_request_duration_seconds` labelled by `route`.
3. **A leak** — `checked_out` grows monotonically and does not fall when traffic stops.
   This is the one that will not recover on its own.

The test for a leak: watch `checked_out` during a quiet minute. It should return toward
zero. If it does not, restart Central to restore service and treat it as a bug.

## 5. Mitigate

- **Slow query** → `SELECT pg_cancel_backend(<pid>)` for the offending query. Cancel
  before terminate; `pg_terminate_backend` drops the connection and the pool has to
  rebuild it.
- **Load** → raise `db_pool_size`/`db_max_overflow` *only* with the database's
  `max_connections` in view. Central's pool is per process: two processes with pool 20
  need 40 connections, and exceeding `max_connections` converts this into a hard
  connection refusal that also locks out `psql`.
- **Leak** → restart Central. Service returns immediately; capture
  `pg_stat_activity` first, because the restart destroys the evidence.
- Lowering `db_pool_timeout_seconds` does not help. It makes the failure faster, not
  rarer.

## 6. Verify recovery

```sh
curl -s -H "X-Metrics-Token: $TOKEN" https://<central>/api/metrics | grep database_pool_usage
curl -s https://<central>/readyz
```

`checked_out` well below `size`, `/readyz` reporting `ready`, and
`database_pool_timeout_total` no longer rising. Then confirm a real path: sign in and
load the node list.

## 7. If the pool is healthy but requests are slow

Look at `cliora_http_request_duration_seconds` by `route` and at the database's own
slow-query log. A missing index presents as slow requests with a *calm* pool, because
each request holds its one connection for a long time without ever exhausting the count.

## 8. On `ClioraAuditWriteFailing`

**Treat as a security incident until the cause is known.** Audit writes are deliberately
non-blocking: a failure is counted and swallowed so a refused request is still refused
and a successful operation still succeeds. The consequence is that operations proceed
**without being recorded**, and the gap cannot be reconstructed afterwards.

Almost always the same underlying database fault — work §3–§5 above. Then:

```sh
journalctl -u cliora-central | grep audit_write_failed
```

Record the outage window in the incident notes: that interval is a hole in the audit
trail, and anyone auditing it later needs to know it exists rather than concluding
nothing happened.

## 9. On `ClioraMetricPersistFailing`

Lower stakes and the same cause. Node resource samples are failing to persist; heartbeat
processing is unaffected by design (the write is wrapped in a savepoint so it cannot take
liveness down with it). The visible effect is a Dashboard `resources` block and a
diagnostic history with holes. Fix the database; nothing else to do.
