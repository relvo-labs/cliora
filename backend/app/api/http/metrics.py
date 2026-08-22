"""Prometheus text exporter (P4-09, ADR 0018).

Three decisions shape this endpoint, all recorded in ADR 0018:

* **Off by default, and never unauthenticated.** An always-on metrics endpoint is a
  permanent read surface on the control plane, and most deployments do not scrape at
  all. Enabling it requires a dedicated `metrics_scrape_token` — deliberately *not*
  the `audit.view` permission, because reusing that would mean creating a service
  account able to read the audit trail just to fetch numbers, and Prometheus holds no
  user session.
* **Rendered with the standard library.** No client library: the process already has a
  registry (`app/metrics.py`), and adding a second one would mean two sources of truth
  for the same series.
* **A scrape degrades rather than fails.** Gauges are computed live, so one slow query
  must not take the whole response down — losing every number is worse than losing
  one, and it happens precisely when something is already wrong. A gauge that times
  out is omitted and counted in `cliora_scrape_error_total`.

The histogram conversion matters: `app/metrics.py` stores **non-cumulative** buckets
(a sample lands in exactly one bound) because that keeps recording O(1). The
exposition format requires cumulative `_bucket` values, so they are accumulated here,
and `le="+Inf"` must equal `_count`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.clock import now_utc
from app.db.engine import get_database, get_session
from app.db.models import KnowledgeJob, Node, TerminalSession
from app.logging import get_logger
from app.repositories.sessions import ACTIVE_STATES
from app.services.registry import ONLINE, compute_status, get_node_registry
from app.services.terminal_relay import get_terminal_relay
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["metrics"])
_logger = get_logger("cliora.metrics")

# Prometheus convention: one namespace prefix for everything this service exports, so
# a shared Prometheus can tell Cliora's series from anything else scraped alongside it.
PREFIX = "cliora_"

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label(value: str) -> str:
    """Escape a label value per the exposition format.

    Every value here comes from the allowlist-checked label set, so none of these
    characters is expected — but an unescaped newline would let one label value forge
    additional metric lines, and that is not a property to leave to convention.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(key: tuple[tuple[str, str], ...], extra: dict[str, str] | None = None) -> str:
    pairs = list(key) + sorted((extra or {}).items())
    if not pairs:
        return ""
    rendered = ",".join(f'{name}="{_escape_label(value)}"' for name, value in pairs)
    return "{" + rendered + "}"


async def _bounded[T](
    name: str, compute: Callable[[], Awaitable[T]], budget_seconds: float
) -> T | None:
    """Run one gauge query under a budget; None means "omit this metric".

    Broad exception handling on purpose: the endpoint's job is visibility, so a gauge
    that raises or hangs must cost only itself. The counter is what makes the omission
    visible rather than making it look like a metric that simply does not exist.
    """
    try:
        async with asyncio.timeout(budget_seconds):
            return await compute()
    except Exception:  # noqa: BLE001 - see docstring
        metrics.increment(metrics.SCRAPE_ERROR_TOTAL, block=name)
        _logger.warning("metrics_gauge_failed", extra={"event": "metrics_gauge_failed", "op": name})
        return None


async def _gauges(session: AsyncSession, settings: Settings) -> list[str]:
    """Compute the point-in-time series.

    Gauges are answered here rather than stored in the registry: "how many nodes are
    online" is a question about *now*, and a stored copy could only ever be stale.
    """
    lines: list[str] = []
    registry = get_node_registry()
    relay = get_terminal_relay()
    timeout = settings.metrics_gauge_timeout_seconds

    # Live, in-memory: no query, so no timeout needed.
    lines += _gauge(
        "active_daemon_connections",
        "Authenticated daemon WebSocket connections currently held by this process.",
        float(registry.connection_count),
    )
    lines += _gauge(
        "active_terminal_connections",
        "Browser terminal WebSocket subscribers currently held by this process.",
        float(relay.connection_count()),
    )

    async def count_online() -> float:
        result = await session.execute(select(Node).where(Node.deleted_at.is_(None)))
        online = 0
        for node in result.scalars():
            # The same `compute_status` the node list and the Dashboard use, so a
            # graph and the page cannot disagree about what "online" means.
            if (
                compute_status(
                    is_enabled=node.is_enabled,
                    seconds_since_heartbeat=registry.seconds_since_heartbeat(node.id),
                    online_within=settings.node_online_within_seconds,
                    degraded_within=settings.node_degraded_within_seconds,
                )
                == ONLINE
            ):
                online += 1
        return float(online)

    online_nodes = await _bounded("online_nodes", count_online, timeout)
    if online_nodes is not None:
        lines += _gauge(
            "online_nodes", "Nodes whose heartbeat is within the online window.", online_nodes
        )

    async def running_by_runtime() -> dict[str, int]:
        result = await session.execute(
            select(TerminalSession.runtime, func.count())
            .where(TerminalSession.status.in_(ACTIVE_STATES))
            .group_by(TerminalSession.runtime)
        )
        return {runtime: int(count) for runtime, count in result.all()}

    per_runtime = await _bounded("running_sessions", running_by_runtime, timeout)
    if per_runtime is not None:
        lines.append(f"# HELP {PREFIX}running_sessions Sessions in a non-terminal state.")
        lines.append(f"# TYPE {PREFIX}running_sessions gauge")
        for runtime, count in sorted(per_runtime.items()):
            lines.append(f'{PREFIX}running_sessions{{runtime="{_escape_label(runtime)}"}} {count}')

    # V2-K1 (ADR 0038 §3). Both are questions about *now* and both are one indexed
    # query, so they belong here rather than in the registry. The dead-letter age is the
    # one that matters most: it is the only number that says whether anybody is reading
    # the Source health panel, and its alert threshold is an hour rather than a rate.
    async def knowledge_queue() -> tuple[int, float]:
        pending = await session.scalar(
            select(func.count()).select_from(KnowledgeJob).where(KnowledgeJob.state == "pending")
        )
        oldest = await session.scalar(
            select(func.min(KnowledgeJob.dead_lettered_at)).where(KnowledgeJob.state == "dead")
        )
        age = 0.0 if oldest is None else max(0.0, (now_utc() - oldest).total_seconds())
        return int(pending or 0), age

    knowledge = await _bounded("knowledge_queue", knowledge_queue, timeout)
    if knowledge is not None:
        pending, dead_age = knowledge
        lines += _gauge(
            "knowledge_pending_jobs",
            "Ingestion hints waiting to be processed.",
            float(pending),
        )
        lines += _gauge(
            "knowledge_dead_letter_age_seconds",
            "Age of the oldest ingestion job that gave up. Zero when there are none.",
            dead_age,
        )

    # Pool occupancy is read from the pool itself, not counted by us — a parallel
    # counter would drift the first time a connection was invalidated behind our back.
    pool = get_database().pool_usage()
    lines.append(f"# HELP {PREFIX}database_pool_usage Connections by state in the SQLAlchemy pool.")
    lines.append(f"# TYPE {PREFIX}database_pool_usage gauge")
    for state in ("checked_out", "available", "overflow", "size"):
        lines.append(f'{PREFIX}database_pool_usage{{state="{state}"}} {pool[state]}')

    return lines


def _gauge(name: str, help_text: str, value: float) -> list[str]:
    return [
        f"# HELP {PREFIX}{name} {help_text}",
        f"# TYPE {PREFIX}{name} gauge",
        f"{PREFIX}{name} {_number(value)}",
    ]


def _number(value: float) -> str:
    """Render a value without a trailing `.0` for whole numbers, which keeps counts
    reading as counts."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def render(counters: list[Any], histograms: list[Any], gauge_lines: list[str]) -> str:
    lines: list[str] = []

    grouped_counters: dict[str, list[tuple[tuple[tuple[str, str], ...], int]]] = {}
    for name, key, value in counters:
        grouped_counters.setdefault(name, []).append((key, value))
    for name in sorted(grouped_counters):
        lines.append(f"# TYPE {PREFIX}{name} counter")
        for key, value in grouped_counters[name]:
            lines.append(f"{PREFIX}{name}{_labels(key)} {value}")

    grouped_histograms: dict[str, list[tuple[tuple[tuple[str, str], ...], dict[str, Any]]]] = {}
    for name, key, entry in histograms:
        grouped_histograms.setdefault(name, []).append((key, entry))
    for name in sorted(grouped_histograms):
        lines.append(f"# TYPE {PREFIX}{name} histogram")
        for key, entry in grouped_histograms[name]:
            # Accumulate: the registry stores one bucket per sample, the format wants
            # "samples ≤ le". Without this every bucket would report only the samples
            # that landed exactly in it, and a quantile computed from it would be wrong.
            running = 0
            for bound in metrics.buckets_for(name):
                running += int(entry["buckets"].get(bound, 0))
                bound_label = _number(bound)
                lines.append(f"{PREFIX}{name}_bucket{_labels(key, {'le': bound_label})} {running}")
            running += int(entry["inf"])
            lines.append(f"{PREFIX}{name}_bucket{_labels(key, {'le': '+Inf'})} {running}")
            lines.append(f"{PREFIX}{name}_sum{_labels(key)} {repr(float(entry['sum']))}")
            lines.append(f"{PREFIX}{name}_count{_labels(key)} {int(entry['count'])}")

    lines.extend(gauge_lines)
    # A trailing newline is required by the exposition format.
    return "\n".join(lines) + "\n"


def _authorize(authorization: str | None, token: str | None, settings: Settings) -> None:
    """Accept the scrape token from either `Authorization: Bearer` or `X-Metrics-Token`.

    Two headers because Prometheus configures a bearer file naturally while ad-hoc
    curl checks are easier with a plain header; both compare the whole token with a
    constant-time comparison so a wrong token cannot be found byte by byte.
    """
    import hmac

    expected = settings.metrics_scrape_token
    presented = token or ""
    if authorization and authorization.startswith("Bearer "):
        presented = authorization[len("Bearer ") :]
    if not expected or not hmac.compare_digest(presented, expected):
        raise ApiError(
            "UNAUTHENTICATED",
            "Missing bearer token",
            status.HTTP_401_UNAUTHORIZED,
        )


@router.get("/metrics")
async def scrape(
    authorization: str | None = Header(default=None),
    x_metrics_token: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Prometheus text exposition of every series.

    Not audited and not logged per request: a scrape happens every few seconds, and
    auditing it would swamp the trail it shares a table with. A refused scrape is a
    401 like any other unauthenticated request.
    """
    if not settings.metrics_enabled:
        # 404, not 403: a disabled endpoint should be indistinguishable from one that
        # does not exist, so a probe learns nothing about the deployment's configuration.
        raise ApiError("NOT_FOUND", "Not found", status.HTTP_404_NOT_FOUND)
    _authorize(authorization, x_metrics_token, settings)

    # Gauges first, then the snapshot. Order matters: computing a gauge can *record* a
    # series (`scrape_error_total` when one times out), and snapshotting before that
    # would leave the failure out of the very response reporting it — surfacing only on
    # the next scrape, which makes the counter quietly lag by one interval and is a trap
    # for anyone writing an alert on it.
    gauge_lines = await _gauges(session, settings)
    counters, histograms = metrics.export_series()
    return Response(content=render(counters, histograms, gauge_lines), media_type=CONTENT_TYPE)


# Re-exported for the tests that assert the exposition shape without an HTTP round trip.
__all__ = ["CONTENT_TYPE", "PREFIX", "render", "router"]
