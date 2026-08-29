"""In-process metrics registry (tech §18.1, ADR 0018).

Counters and duration histograms held in memory, read by the Prometheus exporter
in `app/api/http/metrics.py`. Gauges are deliberately *not* stored here: a gauge is
a question about the present ("how many nodes are online?") and is answered at
scrape time, so a stored copy could only ever be stale.

**Label keys come from a closed allowlist, enforced at the call site.** Two
independent reasons, either sufficient:

* a high-cardinality label (a node id, a path, a search keyword) multiplies the
  series count without bound and is how a metrics backend runs out of memory;
* metrics are the one sink with **no redaction** — `app/logging.py` redacts, audit
  metadata is minimized, but a metric label is published verbatim to whoever can
  scrape. A user id or a filename in a label is a disclosure.

`increment`/`observe` raise on an unknown label key rather than dropping it. A
metric that silently loses its labels looks like it is working, and the mistake
would only be found by someone reading a dashboard that had quietly aggregated
everything together.
"""

from __future__ import annotations

import threading
from typing import Any

# Filesystem relay (P3-09).
FILESYSTEM_REQUEST_TOTAL = "filesystem_request_total"
FILESYSTEM_REQUEST_DURATION = "filesystem_request_duration_seconds"
FILESYSTEM_RELAY_TIMEOUT_TOTAL = "filesystem_relay_timeout_total"
FILESYSTEM_RELAY_CANCEL_TOTAL = "filesystem_relay_cancel_total"
FILESYSTEM_NODE_DISCONNECT_TOTAL = "filesystem_node_disconnect_total"
FILESYSTEM_DENIED_TOTAL = "filesystem_denied_total"
FILESYSTEM_AUDIT_ERROR_TOTAL = "filesystem_audit_error_total"

# Authorization refusals (P4-03). Labelled by coarse action name, role name and
# reason ("action" = role never holds it, "scope" = holds it but not for this
# resource). A sudden rise is either an attack or a misconfigured role, which is
# why ADR 0018 alerts on it. Never labelled by user, session or node id.
AUTHZ_DENIED_TOTAL = "authz_denied_total"

# Audit-chain failures (P4-04). A failing audit write silently breaks
# accountability, so ADR 0018 treats any non-zero value as a critical alert.
AUDIT_ERROR_TOTAL = "audit_error_total"

# Daemon update outcomes as Central saw them (P4-10). Labelled by coarse status
# only; ADR 0018 alerts on any failure, including whether the rollback worked.
NODE_UPDATE_TOTAL = "node_update_total"

# Node metric history (P4-06). A failed sample write is deliberately swallowed so
# it cannot slow or break heartbeat processing — which means this counter is the
# *only* signal that the resource history has gaps.
METRIC_PERSIST_ERROR_TOTAL = "metric_persist_error_total"

# Dashboard per-block degradation (P4-06). One failing aggregate degrades its own
# block instead of failing the response, so without this counter a permanently
# broken block looks like a working page with one quiet "unavailable" card.
# Labelled by block name only — a fixed, low-cardinality set.
DASHBOARD_BLOCK_ERROR_TOTAL = "dashboard_block_error_total"

# --- V2-C1 conversation (plan/23/05-…md §5) ---------------------------------
#
# `CONVERSATION_DUPLICATE_TURN_TOTAL` is the one to watch, and its alert threshold is
# **greater than zero** rather than a rate. The question CAS already serialises
# answers, so a non-zero value means a path reached continuation without going through
# it — and that bug has no other symptom: the system keeps working and somebody's agent
# answers twice.
CONVERSATION_MESSAGES_TOTAL = "conversation_messages_total"
CONVERSATION_TURNS_TOTAL = "conversation_turns_total"
CONVERSATION_DUPLICATE_TURN_TOTAL = "conversation_duplicate_turn_total"
CONVERSATION_QUESTION_EXPIRED_TOTAL = "conversation_question_expired_total"

# --- V2-K1 project memory (plan/25/03-…md §5) --------------------------------
#
# `KNOWLEDGE_INGEST_LAG_SECONDS` is the one the exit criterion reads: the gap between a
# fact happening and it being findable, whose budget is P95 < 10s. It gets its own
# bucket scale because the duration buckets top out at 10s and "how far past the budget
# are we" is the question that matters once it is breached.
#
# The two gauges — pending depth and dead-letter age — are deliberately **not** here.
# This module's docstring says why: a gauge is a question about the present and is
# answered at scrape time, so a stored copy could only ever be stale.
KNOWLEDGE_JOBS_TOTAL = "knowledge_jobs_total"
KNOWLEDGE_JOB_DURATION = "knowledge_job_duration_seconds"
KNOWLEDGE_INGEST_LAG_SECONDS = "knowledge_ingest_lag_seconds"

# Provider ingestion (`beta.2`, ADR 0043 §6). Labelled by host and the existing `status`
# key rather than a new `outcome` one — the allowlist refused `outcome` at the call site
# and it was right to: two label names for one idea is how a dashboard ends up with two
# series that should have been one. Labelled by host and a coarse status —
# never by repository, project or path, all of which are identifying and none of which a
# dashboard needs to answer "is sync still alive".
#
# **`PROVIDER_RECONCILE_LAG_SECONDS` is the only evidence for the phase's one product
# promise.** ADR 0043 §2 gives up freshness deliberately and puts a number on it: a merge
# is visible within one reconcile interval. Without this histogram that sentence is a
# claim; with it, it is a measurement somebody can disagree with.
PROVIDER_READ_TOTAL = "provider_read_total"
PROVIDER_RECONCILE_LAG_SECONDS = "provider_reconcile_lag_seconds"

# Queue depth, by state. The symptom of a backed-up knowledge queue is "search results are
# a bit old", which is invisible on screen — this is the only thing that says so.
KNOWLEDGE_QUEUE_DEPTH_TOTAL = "knowledge_queue_depth_total"

# Which authority levels actually get cited (`plan/27` D134). **Metadata only**: the label
# is the level's name and nothing else. A level that is never cited across a release
# window is the evidence for merging it, which is the measurement ADR 0038 §2 said it
# would need before anybody argued about ten being too many.
CONTEXT_CITATION_TOTAL = "context_citation_total"

# `LEGACY_ROUTE_HIT_TOTAL` was planned here for the `?tab=` sunset (`plan/27` D126) and
# **deliberately not added**. The redirect runs in vue-router, and the SPA is served by
# nginx (`deploy/nginx/nginx.conf`, `location /`) — the FastAPI app never sees the query
# string, so nothing here could increment it.
#
# A metric with no writer is the same defect as a machine code with no raise point
# (`plan/26` D97): it reads as instrumentation and measures nothing. The `?tab=` deletion
# condition was rewritten instead — see ADR 0044 §4.

# --- tech §18.1: the control-plane series (P4-09) ---
# Relay generalized from the P3 filesystem-only pair: every Central→daemon request
# is timed and counted by message type, so a slow or unanswered `session.start` is as
# visible as a slow `filesystem.read` was.
DAEMON_REQUEST_DURATION = "daemon_request_duration_seconds"
DAEMON_REQUEST_TOTAL = "daemon_request_total"
DAEMON_REQUEST_TIMEOUT_TOTAL = "daemon_request_timeout_total"

# WebSocket traffic, split by direction/channel/kind. Bytes and messages are separate
# series because they answer different questions: a flood of tiny control frames and
# one large output burst are both worth seeing, and a single series hides one of them.
WEBSOCKET_MESSAGES_TOTAL = "websocket_messages_total"
WEBSOCKET_BYTES_TOTAL = "websocket_bytes_total"

# Terminal backpressure. The queue depth is a histogram rather than a gauge because
# what matters is the distribution over time — a gauge sampled every 15 s misses the
# spike that actually caused the overflow.
TERMINAL_QUEUE_BYTES = "terminal_client_queue_bytes"
TERMINAL_QUEUE_FRAMES = "terminal_client_queue_frames"
TERMINAL_QUEUE_OVERFLOW_TOTAL = "terminal_queue_overflow_total"

# HTTP latency, labelled by the route *template*. The actual path would put every
# session and node id into the label set (see the module docstring).
HTTP_REQUEST_DURATION = "http_request_duration_seconds"

# Connection-pool exhaustion, counted where a checkout times out. The live pool
# occupancy is a gauge and is read at scrape time.
DATABASE_POOL_TIMEOUT_TOTAL = "database_pool_timeout_total"

# Raised when a gauge could not be computed during a scrape. The scrape still
# succeeds without that metric — a monitoring endpoint that fails as a whole because
# one query was slow takes away the visibility exactly when it is needed.
SCRAPE_ERROR_TOTAL = "scrape_error_total"

# Duration buckets in seconds, chosen around the P3 NFR thresholds (directory
# listing < 2 s, ≤2 MB preview < 3 s) so a breach is visible in the histogram.
_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)

# Byte/frame buckets for the terminal queue depth, spanning empty to the configured
# 4 MiB / 1024-frame bounds so "approaching the limit" is distinguishable from "idle".
_SIZE_BUCKETS: tuple[float, ...] = (
    1,
    16,
    64,
    256,
    1024,
    4096,
    16384,
    65536,
    262144,
    1048576,
    4194304,
)

# Histograms whose values are counts or bytes rather than seconds.
_SIZE_HISTOGRAMS: frozenset[str] = frozenset({TERMINAL_QUEUE_BYTES, TERMINAL_QUEUE_FRAMES})

# Ingest freshness spans a wider range than a request does: knowledge jobs budget 10s and
# provider reconciliation budgets 300s. The interesting range is therefore minutes or
# hours, which `_BUCKETS` ending at 10s cannot express.
_LAG_BUCKETS: tuple[float, ...] = (1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0, 1800.0, 7200.0)
_LAG_HISTOGRAMS: frozenset[str] = frozenset(
    {KNOWLEDGE_INGEST_LAG_SECONDS, PROVIDER_RECONCILE_LAG_SECONDS}
)

# The closed label allowlist (ADR 0018). Adding a key here is a deliberate decision
# that it is low-cardinality *and* carries no identifying information.
ALLOWED_LABELS: frozenset[str] = frozenset(
    {
        "action",
        "block",
        "channel",
        "code",
        "direction",
        "kind",
        "method",
        "op",
        "reason",
        "role",
        "route",
        "runtime",
        "stage",
        "state",
        "status",
        "status_class",
        "type",
        # `beta.2`. `host` is the provider's API host from the deployment allowlist — a
        # closed, tiny set, never a repository address. `authority` is one of ten fixed
        # level names.
        "host",
        "authority",
    }
)

# Label keys that must never appear. Redundant with the allowlist — anything not
# allowed is already refused — but named explicitly so the intent survives someone
# widening the allowlist without thinking about why it is narrow.
FORBIDDEN_LABELS: frozenset[str] = frozenset(
    {
        "node_id",
        "user_id",
        "session_id",
        "request_id",
        "path",
        "rel_path",
        "filename",
        "keyword",
        "username",
        "workspace",
        "message",
    }
)


class LabelNotAllowed(ValueError):
    """Raised for a label key outside `ALLOWED_LABELS`.

    An exception, not a silent drop: a metric that quietly loses its labels looks
    like it works, and the mistake surfaces much later as a dashboard that has
    aggregated everything into one line.
    """


def _check_labels(name: str, labels: dict[str, str]) -> None:
    unknown = sorted(set(labels) - ALLOWED_LABELS)
    if unknown:
        raise LabelNotAllowed(
            f"{name}: label(s) {unknown} are not in the metrics label allowlist "
            "(app/metrics.py ALLOWED_LABELS). High-cardinality or identifying labels "
            "are refused: metrics are published without redaction."
        )


LabelKey = tuple[tuple[str, str], ...]

_lock = threading.Lock()
_counters: dict[str, dict[LabelKey, int]] = {}
_histograms: dict[str, dict[LabelKey, dict[str, Any]]] = {}


def _key(labels: dict[str, str]) -> LabelKey:
    return tuple(sorted((name, str(value)) for name, value in labels.items()))


def buckets_for(name: str) -> tuple[float, ...]:
    """The bucket bounds a histogram uses. Exported so the exporter renders the same
    bounds it was recorded with rather than assuming the duration scale."""
    if name in _SIZE_HISTOGRAMS:
        return _SIZE_BUCKETS
    if name in _LAG_HISTOGRAMS:
        return _LAG_BUCKETS
    return _BUCKETS


def increment(name: str, amount: int = 1, **labels: str) -> None:
    _check_labels(name, labels)
    with _lock:
        series = _counters.setdefault(name, {})
        key = _key(labels)
        series[key] = series.get(key, 0) + amount


def observe(name: str, value: float, **labels: str) -> None:
    """Record one sample in a bucketed histogram.

    Buckets here are **non-cumulative**: a sample lands in exactly one bound. The
    Prometheus exposition format requires cumulative `_bucket` values, so the exporter
    accumulates on the way out (`app/api/http/metrics.py`). Storing them non-cumulative
    keeps the recording path O(1) instead of O(buckets) per sample, and the conversion
    is asserted by `test_histogram_buckets_are_cumulative_in_the_exposition`.
    """
    _check_labels(name, labels)
    bounds = buckets_for(name)
    with _lock:
        series = _histograms.setdefault(name, {})
        entry = series.setdefault(
            _key(labels),
            {"count": 0, "sum": 0.0, "buckets": dict.fromkeys(bounds, 0), "inf": 0},
        )
        entry["count"] += 1
        entry["sum"] += value
        placed = False
        for bound in bounds:
            if value <= bound:
                entry["buckets"][bound] += 1
                placed = True
                break
        if not placed:
            entry["inf"] += 1


def counter_value(name: str, **labels: str) -> int:
    with _lock:
        return _counters.get(name, {}).get(_key(labels), 0)


def histogram_value(name: str, **labels: str) -> dict[str, Any] | None:
    with _lock:
        entry = _histograms.get(name, {}).get(_key(labels))
        return dict(entry) if entry is not None else None


def snapshot() -> dict[str, Any]:
    """A plain-data view of every series, for assertions and future export."""
    with _lock:
        return {
            "counters": {
                name: {dict(key).__repr__(): value for key, value in series.items()}
                for name, series in _counters.items()
            },
            "histograms": {
                name: {
                    dict(key).__repr__(): {
                        "count": entry["count"],
                        "sum": entry["sum"],
                    }
                    for key, entry in series.items()
                }
                for name, series in _histograms.items()
            },
        }


def reset() -> None:
    """Clear every series. Tests only."""
    with _lock:
        _counters.clear()
        _histograms.clear()


def export_series() -> tuple[
    list[tuple[str, LabelKey, int]],
    list[tuple[str, LabelKey, dict[str, Any]]],
]:
    """Every series as flat, sorted data for the exporter.

    Sorted so a scrape is byte-stable for the same state, which makes the exporter's
    output diffable in tests. Copies the histogram entries because the caller
    accumulates their buckets and must not mutate the live registry.
    """
    with _lock:
        counters = sorted(
            (name, key, value)
            for name, series in _counters.items()
            for key, value in series.items()
        )
        histograms = sorted(
            (
                (name, key, {**entry, "buckets": dict(entry["buckets"])})
                for name, series in _histograms.items()
                for key, entry in series.items()
            ),
            key=lambda item: (item[0], item[1]),
        )
    return counters, histograms
