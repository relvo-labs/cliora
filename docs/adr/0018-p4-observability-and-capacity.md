# ADR 0018: P4 observability, alerting & capacity baseline

Status: accepted (2026-07-25). Governs Phase 4 (Operations & Hardening); confirmed defaults per product decision (see `plan/05`).

## Context

P3 created the collection points and said so explicitly: `backend/app/metrics.py` and `daemon/internal/metrics` both carry a comment that tech §18.1/§18.2 defers a Prometheus port and that "a future exporter (P4) reads the same structure". What exists today is only the filesystem series — 7 backend, 6 daemon — and **no export path at all**. Of tech §18.1's eleven metrics, most are absent; of §18.2's six, none reach a registry (daemon resources are sampled and shipped inside `node.heartbeat`, then held only in Central's in-process `NodeConnectionRegistry`, so they vanish on restart). `database_pool_usage` is currently meaningless because the engine uses SQLAlchemy's default pool with no configured bounds. There are no alert rules and no runbooks, and the PRD's scale target (NFR-003) has never been exercised.

## Decisions

### The existing in-process registries stay the only collection point

No Prometheus client library is introduced. Both registries are already thread-safe, already tested via `snapshot()`, and adding a library would create two parallel truths. The exporter renders the existing structures into Prometheus text format using the standard library.

### Metric inventory

**Backend** — completing tech §18.1: `online_nodes`, `active_daemon_connections`, `active_terminal_connections`, `running_sessions{runtime}`, `websocket_messages_total{direction,channel,kind}`, `websocket_bytes_total{…}`, `daemon_request_duration_seconds{type}` (generalizing P3's filesystem-only duration), `daemon_request_timeout_total{type}`, `terminal_client_queue_size` (bytes and frames), `terminal_queue_overflow_total{reason}`, `http_request_duration_seconds{method,route,status_class}`, `database_pool_usage{state}`, plus `audit_error_total{action}`, `metric_persist_error_total` and `authz_denied_total{action,role,reason}`.

**Daemon** — completing tech §18.2: `daemon_uptime_seconds`, `daemon_active_sessions`, `daemon_cpu_usage` / `memory_usage` / `load_average` / `disk_usage`, `daemon_reconnect_total{reason}`, `daemon_heartbeat_sent_total`, `daemon_session_start_total{runtime,result}`, `daemon_update_total{status,stage}`.

### Label whitelist is a hard rule

Permitted label keys: `op`, `type`, `code`, `reason`, `runtime`, `status`, `status_class`, `role`, `direction`, `channel`, `kind`, `method`, `route`, `state`, `stage`. **Forbidden: `node_id`, `user_id`, `session_id`, `path`, `filename`, `keyword`, `username`, or any free text.** `route` must be the route *template* (`/api/sessions/{session_id}/files/content`), never the concrete path.

Two reasons, both load-bearing: high-cardinality labels are how a metrics backend runs out of memory, and metrics are the one sink with **no redaction layer** — an id or a path placed in a label is exfiltrated verbatim to whoever can scrape. A test scans every series key in `snapshot()` against the whitelist; a violation is a build failure, not a review comment.

### Exporter: off by default, authorized, text format

`GET /api/metrics` is gated by `metrics_enabled` (default **false**). When enabled it requires a dedicated `metrics_scrape_token` — Prometheus does not hold a user session, so reusing `audit.view` would mean creating a service account with audit-read rights just to scrape. Whether to additionally bind it to an internal interface is a deployment concern documented in `docs/deployment.md`.

Gauges (`online_nodes`, pool usage, running sessions) are computed at scrape time with a short timeout; on timeout the metric is skipped and `cliora_scrape_error{block=…} 1` is emitted so **a slow query degrades one metric rather than failing the scrape**. The endpoint writes no audit row and no per-request log.

**Implementation note that will otherwise cause a silent bug:** `app/metrics.py::observe()` places a sample in the *first matching* bucket, so the stored buckets are **not cumulative**. The exporter must accumulate them, and a test must assert `_bucket` values are monotonic with `le=+Inf` equal to `_count`.

### The daemon does not open a port

Daemon metrics travel inside the existing `node.heartbeat` (`resources` + `active_sessions`), consistent with tech §18.2 and with the outbound-only trust boundary: opening a listener on every node to be scraped would invert the connection model the whole architecture rests on. The daemon's local registry is exposed only through the CLI (`agentd metrics` / `doctor` snapshot output) for on-box debugging.

### Resource history is persisted, downsampled, and non-critical

`node_metric_samples` (`node_id`, `sampled_at`, cpu/memory/load/disk/uptime — all nullable, `active_sessions`) receives **one row per node per 60 s**, decided in memory from a monotonic last-persisted timestamp so the heartbeat path never queries the database. Retention 30 days, pruned by the manual procedure in ADR 0016. A write failure increments `metric_persist_error_total` and is otherwise ignored: **heartbeat handling must never fail or slow down because metrics persistence did**.

Rationale for persisting at all: without it, a Central restart erases all fleet health history, so neither the dashboard's resource block nor any post-incident question ("was this node healthy yesterday?") can be answered. Raw 60 s samples with aggregation at query time, rather than pre-aggregated rollups — 100 nodes × 30 days ≈ 4.3 M rows, which PostgreSQL handles trivially at this scale and which keeps the door open to changing the aggregation later.

### Database pool bounds become explicit

`db_pool_size` 10, `db_max_overflow` 10, `db_pool_timeout_seconds` 5, `db_pool_recycle_seconds` 1800. Exhaustion surfaces as a 503 with a safe message and a metric, never as an unbounded wait — which is also what makes the DB-exhaustion alert meaningful.

### Alert thresholds

| Alert | Warning | Critical |
|---|---|---|
| Heartbeat loss | node silent > 90 s for 2 min | > 5 min, or > 20% of the fleet |
| Queue saturation | terminal queue > 80% for 1 min | any overflow event (`terminal.gap` + 1013) |
| Timeout surge | `*_timeout_total` +10 over 5 min | +50 over 5 min |
| DB exhaustion | pool > 80% for 2 min | checkout wait > 1 s |
| Update failure | — | any `UPDATE_*` failure (with rollback outcome) |
| Authz denial spike | `authz_denied_total` sudden rise | — |
| Audit chain failure | — | `audit_error_total` > 0 |

The last two are additions: a burst of authorization denials is either an attack or a misconfigured role, and a failing audit write is itself a security event, since it silently breaks accountability.

Rules live in `deploy/prometheus/alerts.yml` and are syntax-checked in CI (`promtool check rules`). All durations are monotonic.

### Every alert has a runbook, and every runbook is rehearsed

`docs/runbooks/`: `heartbeat-loss.md`, `queue-saturation.md`, `timeout-surge.md`, `db-exhaustion.md`, `update-failure.md`, `backup-restore.md`. Fixed structure: symptom → triggering alert → immediate impact → diagnosis (which metric, which log query, which audit action) → mitigation → root cause → verify recovery → follow-up.

`scripts/p4/drills/` triggers each alert deliberately (stop a daemon; flood a terminal; wedge a daemon's responses; shrink the pool to 1 and hammer it; corrupt a checksum). Each drill records trigger time, whether the runbook steps were actually executable, and recovery time into `artifacts/p4/<run>/drills.md`. **An alert that cannot be triggered on demand is not considered delivered** — this is the difference between having monitoring and believing you have monitoring.

### Capacity is measured with a protocol-level fleet

NFR-003 (100 nodes, 10 sessions/node, 500 terminal WebSockets) is exercised by `scripts/p4/load/`: 100 simulated daemons speaking the real protocol (real Ed25519 handshake, heartbeats, request responses) without launching real tmux, plus 500 browser terminal clients including deliberate **slow** and **flooding** clients, plus a session-churn driver. Real tmux behaviour is already covered by the P2/P3 integration suites; the point of this harness is the relay, the registry and the bounds, which is precisely what a protocol-level fleet exercises — and it runs on one machine.

Must be proven bounded: Central RSS bounded and recovering after load; per-client terminal queues within `terminal_queue_max_bytes` / `max_frames` with overflow closing only the offending client; per-node pending requests capped at 128 (`NODE_BUSY`) and cleared on disconnect; pool usage bounded with no leaked connections; asyncio tasks and goroutines returning to baseline; terminal round-trip latency recorded against the < 200 ms target.

The harness enforces budgets and **exits non-zero on regression** (the pattern proven by P2's `relay_bench.py` and P3's `files_bench.py` / `bench_test.go`), so it can live in CI rather than being a one-off measurement. A small-scale smoke runs per PR; full scale runs on merge and RC.

## Consequences

- Metrics are opt-in, so a deployment that never enables the exporter has no monitoring. The alert rules and runbooks are shipped regardless, so enabling it is configuration rather than development.
- The label whitelist means some questions cannot be answered from metrics ("which node timed out?"). That is deliberate: those questions belong to logs and audit, which have redaction and access control. Correlation is via `request_id`.
- `node_metric_samples` grows without a scheduler; if the manual prune is skipped, the table grows. Bounded by the 60 s downsample and documented in the runbook.
- Rejected: a Prometheus client library (dual registries); a daemon-side scrape port (inverts the outbound-only model); pre-aggregated rollup tables (premature at this scale); tracing/APM integration (out of MVP scope); alerting on raw latency percentiles instead of saturation and error signals (noisier and slower to act on at this size).
