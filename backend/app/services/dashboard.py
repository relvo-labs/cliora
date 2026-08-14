"""Dashboard aggregates with an explicit freshness contract (P4-06, PRD §10.2).

The whole point of this module is what it refuses to do: **it never presents a
stale or partial view as a live one.** Two mechanisms carry that.

**Per-block ownership.** Each block has its own fetch function and its own status.
One failing aggregate degrades one card (`data: null` + an `error_code`); the
response still succeeds and the other five blocks still show real numbers. A
single try/except around the whole summary would turn one bad query into a blank
page, and the alternative — swallowing the error and returning zeros — would
report a healthy empty fleet, which is worse than an error.

**Freshness, not optimism.** Node status is recomputed from the live connection
registry through `compute_status()`, the same function the node list uses; it is
never read from `nodes.status`, which is a snapshot column no code has updated
since P1. Where the live view cannot be trusted — just after a restart, or when
heartbeats have gone quiet — the block says `stale` and the UI marks the numbers
as possibly out of date rather than hiding the doubt.

Caching is process-local and short (`dashboard_cache_ttl_seconds`). The cached
`generated_at` is the instant the data was **fetched**, never the instant the
request arrived: back-filling it to `now()` would make a five-second-old number
claim to be current, which is exactly the deception the contract exists to
prevent. The cache holds full-fidelity data and role projection happens after, so
one viewer's permissions can never widen or narrow another's.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.clock import now_utc, process_uptime_seconds
from app.db.models import (
    ActivityEvent,
    AuditLog,
    Node,
    NodeRuntime,
    Task,
    TaskRun,
    TerminalSession,
    User,
    VerificationReport,
)
from app.repositories.node_metrics import NodeMetricRepository
from app.repositories.sessions import ACTIVE_STATES
from app.services import audit as audit_actions
from app.services.registry import (
    DEGRADED,
    DISABLED,
    OFFLINE,
    ONLINE,
    NodeConnectionRegistry,
    compute_status,
    get_node_registry,
)
from app.settings import Settings, get_settings

# Block names. Fixed and low-cardinality, so they are safe as a metric label.
NODES = "nodes"
SESSIONS = "sessions"
RUNTIMES = "runtimes"
RESOURCES = "resources"
RECENT_ACTIVITY = "recent_activity"
UNHEALTHY_NODES = "unhealthy_nodes"
# V2.4. One block, six numbers — rather than six blocks — because they answer one
# question together ("is the delivery loop working") and a reader who sees five of them
# has no way to tell which one is missing. The per-block degradation contract still
# applies: this block fails alone (ADR 0033 §Consequences).
DELIVERY = "delivery"

BLOCKS: tuple[str, ...] = (
    NODES,
    SESSIONS,
    RUNTIMES,
    RESOURCES,
    RECENT_ACTIVITY,
    UNHEALTHY_NODES,
    DELIVERY,
)

OK = "ok"
STALE = "stale"
DEGRADED_BLOCK = "degraded"

# The runtimes always reported, so an empty fleet still shows the rows an operator
# expects rather than an empty list they cannot interpret (PRD §10.2 names Claude
# and Codex explicitly). Any other runtime a node reports is added on top.
BASE_RUNTIMES: tuple[str, ...] = ("claude", "codex")

# Why a node is listed as unhealthy. Coarse codes, so the UI owns the wording and
# the set stays assertable.
REASON_OFFLINE = "offline_but_enabled"
REASON_DEGRADED = "heartbeat_degraded"
REASON_NO_RUNTIME = "no_runtime_available"
REASON_RECENT_FAILURE = "recent_session_failure"


@dataclass(frozen=True, slots=True)
class Block:
    status: str
    # When the data was fetched. Preserved through the cache; never back-filled.
    generated_at: datetime
    data: dict[str, Any] | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class Summary:
    generated_at: datetime
    blocks: dict[str, Block] = field(default_factory=dict)


@dataclass
class _CacheEntry:
    summary: Summary
    # Monotonic, so a wall-clock adjustment cannot extend or expire the entry.
    stored_at: float


class DashboardService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: NodeConnectionRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or get_node_registry()
        self._settings = settings or get_settings()
        self._metrics = NodeMetricRepository(session)

    def _fetchers(self) -> dict[str, Callable[[], Awaitable[Block]]]:
        """One owner per block. A name in `BLOCKS` without an entry here renders a
        card that is permanently absent rather than visibly degraded, so
        `test_every_declared_block_has_a_fetcher` asserts the two agree."""
        return {
            NODES: self._nodes_block,
            SESSIONS: self._sessions_block,
            RUNTIMES: self._runtimes_block,
            RESOURCES: self._resources_block,
            RECENT_ACTIVITY: self._recent_activity_block,
            UNHEALTHY_NODES: self._unhealthy_nodes_block,
            DELIVERY: self._delivery_block,
        }

    async def summary(self) -> Summary:
        """Fetch every block, each isolated from the others' failures."""
        # Sequential, not gathered: the blocks share one AsyncSession, and
        # concurrent statements on a single session are not safe. Every query here
        # is an indexed aggregate, so the win would be small and the failure mode
        # (interleaved statements on one connection) severe.
        blocks: dict[str, Block] = {}
        for name, fetch in self._fetchers().items():
            blocks[name] = await self._guarded(name, fetch)
        return Summary(generated_at=now_utc(), blocks=blocks)

    async def _guarded(self, name: str, fetch: Callable[[], Awaitable[Block]]) -> Block:
        """Contain one block's failure to that block.

        Broad on purpose: any exception a fetcher can raise — a database error, a
        bad row, a bug — must degrade one card rather than fail the page. The
        exception type is not surfaced to the client (it could name a table or a
        column); the counter and the log carry the detail.
        """
        try:
            return await fetch()
        except Exception:  # noqa: BLE001 - see docstring
            metrics.increment(metrics.DASHBOARD_BLOCK_ERROR_TOTAL, block=name)
            return Block(
                status=DEGRADED_BLOCK,
                generated_at=now_utc(),
                data=None,
                error_code="BLOCK_UNAVAILABLE",
            )

    # --- Blocks ---------------------------------------------------------- #

    async def _delivery_block(self) -> Block:
        """The six numbers V2.4 asks for, over the last 30 days.

        **Every one of them is read-only.** They are queries, never inputs to a state
        machine: there is no "failure rate too high, stop dispatching" anywhere, and
        `GATE-DV-METRICS-READ-ONLY` asserts no service imports this. A metric that can
        block work becomes a number people optimise (ADR 0033).

        Each carries a sentence, and the sentences are here rather than in the console
        because the third one is dangerous without it: a count of forced cards reads as
        "who is cheating" and actually asks "are our completion criteria wrong".
        """
        since = now_utc() - timedelta(days=30)

        created = await self._scalar(
            select(func.count()).select_from(Task).where(Task.created_at >= since)
        )
        with_run = await self._scalar(
            select(func.count(func.distinct(TaskRun.task_id))).where(TaskRun.queued_at >= since)
        )
        done = await self._scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.stage == "done", Task.updated_at >= since)
        )
        done_with_report = await self._scalar(
            select(func.count(func.distinct(VerificationReport.task_id)))
            .select_from(VerificationReport)
            .join(Task, Task.id == VerificationReport.task_id)
            .where(Task.stage == "done", VerificationReport.reported_at >= since)
        )
        forced = await self._scalar(
            select(func.count())
            .select_from(ActivityEvent)
            .where(ActivityEvent.kind == "task.forced_done", ActivityEvent.occurred_at >= since)
        )
        failures = (
            await self._session.execute(
                select(TaskRun.error_code, func.count())
                .where(TaskRun.status == "failed", TaskRun.finished_at >= since)
                .group_by(TaskRun.error_code)
            )
        ).all()
        finished = await self._scalar(
            select(func.count())
            .select_from(TaskRun)
            .where(TaskRun.finished_at.is_not(None), TaskRun.finished_at >= since)
        )
        waiting_seconds = await self._scalar(
            select(
                func.coalesce(
                    func.avg(func.extract("epoch", TaskRun.last_event_at - TaskRun.waiting_since)),
                    0,
                )
            ).where(TaskRun.waiting_since.is_not(None), TaskRun.waiting_since >= since)
        )
        card_checks, project_checks = await self._check_origin_split(since)

        return Block(
            status=OK,
            generated_at=now_utc(),
            data={
                "window_days": 30,
                "tasks_created": created,
                "tasks_with_a_run": with_run,
                "tasks_done": done,
                "tasks_done_with_a_report": done_with_report,
                "forced_done": forced,
                "runs_finished": finished,
                "run_failures": {code or "unknown": count for code, count in failures},
                "avg_waiting_seconds": round(float(waiting_seconds or 0), 1),
                "checks_by_origin": {"project": project_checks, "card": card_checks},
            },
        )

    async def _check_origin_split(self, since: datetime) -> tuple[int, int]:
        """How much of the verification is the card's own (M-DV-1b).

        **A high share is not a fault.** It may mean the project's settings are too
        coarse; what to do about it depends on whether the card-declared commands are
        all the same one — which is a question for a person, not a threshold.
        """
        reports = (
            await self._session.execute(
                select(VerificationReport.checks).where(VerificationReport.reported_at >= since)
            )
        ).scalars()
        card = project = 0
        for checks in reports:
            for check in checks or []:
                if isinstance(check, dict) and check.get("origin") == "card":
                    card += 1
                else:
                    project += 1
        return card, project

    async def _scalar(self, statement: Any) -> int:
        return int((await self._session.execute(statement)).scalar() or 0)

    async def _active_nodes(self) -> Sequence[Node]:
        result = await self._session.execute(select(Node).where(Node.deleted_at.is_(None)))
        return result.scalars().all()

    def _live_status(self, node: Node) -> str:
        return compute_status(
            is_enabled=node.is_enabled,
            seconds_since_heartbeat=self._registry.seconds_since_heartbeat(node.id),
            online_within=self._settings.node_online_within_seconds,
            degraded_within=self._settings.node_degraded_within_seconds,
        )

    async def _nodes_block(self) -> Block:
        nodes = await self._active_nodes()
        counts = dict.fromkeys((ONLINE, DEGRADED, OFFLINE, DISABLED), 0)
        for node in nodes:
            counts[self._live_status(node)] += 1
        data = {**counts, "total": len(nodes)}
        return Block(status=self._nodes_freshness(nodes), generated_at=now_utc(), data=data)

    def _nodes_freshness(self, nodes: Sequence[Node]) -> str:
        """`ok` only when this process's view can be trusted.

        Three ways it cannot be:

        1. **Central restarted moments ago.** No daemon has necessarily reconnected
           yet, so "everything offline" is indistinguishable from "we have not heard
           from anyone yet".
        2. **A connected node has gone quiet** past the freshness threshold. It is
           still counted (its socket is open) but the numbers it contributes are
           older than the contract allows to pass as current.
        3. **The stored snapshot claims more liveness than the registry can back
           up.** `nodes.status` is not maintained today — it stays "offline" from
           creation — so this cannot fire yet. It is checked in the one direction
           that matters, because if a future writer starts persisting status, a
           restart would otherwise let the page report a node as online with no
           connection behind it.

        An empty fleet is exempt from (1), and that exemption matters: on a fresh
        install the count is 0 because the table is empty, which no amount of waiting
        for heartbeats can change. Marking it `stale` would put "possibly out of date"
        next to a number that is certain, and it would do so on exactly the screen
        where a new operator is deciding whether the product works.
        """
        if not nodes:
            return OK
        if process_uptime_seconds() < self._settings.heartbeat_interval_seconds:
            return STALE
        threshold = self._settings.dashboard_stale_after_seconds
        for node in nodes:
            gap = self._registry.seconds_since_heartbeat(node.id)
            if gap is not None and gap > threshold:
                return STALE
            if gap is None and node.status in (ONLINE, DEGRADED):
                return STALE
        return OK

    async def _sessions_block(self) -> Block:
        by_status = await self._session.execute(
            select(TerminalSession.status, func.count())
            .where(TerminalSession.status.in_(ACTIVE_STATES))
            .group_by(TerminalSession.status)
        )
        statuses = dict.fromkeys(ACTIVE_STATES, 0)
        for status_value, count in by_status.all():
            statuses[status_value] = int(count)

        by_runtime = await self._session.execute(
            select(TerminalSession.runtime, func.count())
            .where(TerminalSession.status.in_(ACTIVE_STATES))
            .group_by(TerminalSession.runtime)
        )
        # Only runtimes that actually have active sessions. A zero here would be
        # indistinguishable from a runtime that does not exist.
        per_runtime = {runtime: int(count) for runtime, count in by_runtime.all()}
        data = {
            **statuses,
            "total_active": sum(statuses.values()),
            "per_runtime": per_runtime,
        }
        return Block(status=OK, generated_at=now_utc(), data=data)

    async def _runtimes_block(self) -> Block:
        """Per-runtime availability across the fleet.

        `unknown` is a first-class outcome, not folded into `unavailable`: a node
        that has never reported a runtime has not said it is missing, and treating
        silence as a negative would show a fresh fleet as broken.
        """
        rows = await self._session.execute(
            select(NodeRuntime.runtime, NodeRuntime.available, NodeRuntime.checked_at, Node.id)
            .join(Node, Node.id == NodeRuntime.node_id)
            .where(Node.deleted_at.is_(None), Node.is_enabled.is_(True))
        )
        eligible = await self._session.execute(
            select(func.count())
            .select_from(Node)
            .where(Node.deleted_at.is_(None), Node.is_enabled.is_(True))
        )
        total_nodes = int(eligible.scalar() or 0)

        seen: dict[str, dict[str, Any]] = {
            runtime: {"available": 0, "unavailable": 0, "unknown": 0, "checked_at": None}
            for runtime in BASE_RUNTIMES
        }
        reporting: dict[str, set[uuid.UUID]] = {runtime: set() for runtime in BASE_RUNTIMES}
        oldest_check: datetime | None = None
        for runtime, available, checked_at, node_id in rows.all():
            entry = seen.setdefault(
                runtime, {"available": 0, "unavailable": 0, "unknown": 0, "checked_at": None}
            )
            reporting.setdefault(runtime, set()).add(node_id)
            entry["available" if available else "unavailable"] += 1
            if checked_at is not None and (oldest_check is None or checked_at < oldest_check):
                oldest_check = checked_at
            current = entry["checked_at"]
            if checked_at is not None and (current is None or checked_at > current):
                entry["checked_at"] = checked_at

        for runtime, entry in seen.items():
            entry["unknown"] = max(total_nodes - len(reporting.get(runtime, set())), 0)

        status = OK
        if oldest_check is not None:
            age = (now_utc() - oldest_check).total_seconds()
            if age > self._settings.node_degraded_within_seconds:
                # Detection is refreshed on register / runtime_status; a check older
                # than the degraded window means some node stopped reporting.
                status = STALE
        return Block(
            status=status,
            generated_at=now_utc(),
            data={"runtimes": seen, "eligible_nodes": total_nodes},
        )

    async def _resources_block(self) -> Block:
        window = timedelta(seconds=self._settings.dashboard_resource_window_seconds)
        fleet = await self._metrics.fleet_summary(since=now_utc() - window)
        data = {
            "measurements": {
                name: {
                    "average": summary.average,
                    "maximum": summary.maximum,
                    "nodes": summary.nodes,
                }
                for name, summary in fleet.measurements.items()
            },
            "sampled_nodes": fleet.sampled_nodes,
            "latest_sample_at": fleet.latest_sample_at,
            "window_seconds": self._settings.dashboard_resource_window_seconds,
        }
        # No samples is `ok` and empty, not `degraded`: nothing failed, there is
        # simply nothing to report yet. The UI must say "no data", never 0%.
        return Block(status=OK, generated_at=now_utc(), data=data)

    async def _recent_activity_block(self) -> Block:
        """The newest audit entries, safe fields only.

        No metadata: this block is rendered for every role that can see the
        Dashboard, while the metadata is only cleared for release through the
        Admin-only audit endpoint. Actor identity is carried here but stripped for
        viewers without `audit.view` (see `project_for`).
        """
        limit = self._settings.dashboard_recent_activity_limit
        rows = await self._session.execute(
            select(
                AuditLog.id,
                AuditLog.action,
                AuditLog.created_at,
                AuditLog.user_id,
                User.display_name,
                AuditLog.node_id,
                Node.name,
            )
            .outerjoin(User, User.id == AuditLog.user_id)
            .outerjoin(Node, Node.id == AuditLog.node_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        items = [
            {
                "id": entry_id,
                "action": action,
                "created_at": created_at,
                "actor_id": actor_id,
                "actor_name": actor_name,
                "node_id": node_id,
                "node_name": node_name,
            }
            for entry_id, action, created_at, actor_id, actor_name, node_id, node_name in rows
        ]
        return Block(status=OK, generated_at=now_utc(), data={"items": items, "limit": limit})

    async def _unhealthy_nodes_block(self) -> Block:
        nodes = await self._active_nodes()
        node_ids = [node.id for node in nodes]

        available_runtimes: dict[uuid.UUID, int] = {}
        if node_ids:
            counts = await self._session.execute(
                select(NodeRuntime.node_id, func.count())
                .where(NodeRuntime.node_id.in_(node_ids), NodeRuntime.available.is_(True))
                .group_by(NodeRuntime.node_id)
            )
            available_runtimes = {node_id: int(count) for node_id, count in counts.all()}

        recent_failures: set[uuid.UUID] = set()
        if node_ids:
            since = now_utc() - timedelta(hours=1)
            failed = await self._session.execute(
                select(AuditLog.node_id).where(
                    AuditLog.action == audit_actions.SESSION_FAILED,
                    AuditLog.created_at >= since,
                    AuditLog.node_id.in_(node_ids),
                )
            )
            recent_failures = {node_id for (node_id,) in failed.all() if node_id is not None}

        items: list[dict[str, Any]] = []
        for node in nodes:
            live = self._live_status(node)
            reasons: list[str] = []
            if live == OFFLINE and node.is_enabled:
                reasons.append(REASON_OFFLINE)
            if live == DEGRADED:
                reasons.append(REASON_DEGRADED)
            # A disabled node is an operator decision, not a fault, so it is not
            # listed for having no runtime available.
            if node.is_enabled and available_runtimes.get(node.id, 0) == 0:
                reasons.append(REASON_NO_RUNTIME)
            if node.id in recent_failures:
                reasons.append(REASON_RECENT_FAILURE)
            if reasons:
                items.append(
                    {
                        "id": node.id,
                        "name": node.name,
                        "status": live,
                        "reasons": reasons,
                        "last_seen_at": node.last_seen_at,
                    }
                )

        limit = self._settings.dashboard_unhealthy_limit
        return Block(
            status=OK,
            generated_at=now_utc(),
            data={
                "items": items[:limit],
                # The count before truncation, so "10 of 37 unhealthy nodes" is
                # honest instead of implying the list is complete.
                "total": len(items),
                "limit": limit,
            },
        )


# --- Role projection ---------------------------------------------------- #


def project_for(summary: Summary, *, can_view_audit: bool) -> Summary:
    """Narrow a cached, full-fidelity summary to what this viewer may see.

    Applied after the cache so one viewer's permissions cannot leak into another's
    response — the alternative, caching per role, multiplies the queries and still
    risks serving the wrong variant.

    Without `audit.view`, recent activity keeps the action and the instant but
    loses who did it: knowing *that* a node was removed is operational context,
    knowing *who* removed it is the audit trail (FR-AUTH-002).
    """
    if can_view_audit:
        return summary
    activity = summary.blocks.get(RECENT_ACTIVITY)
    if activity is None or activity.data is None:
        return summary
    redacted = [
        {**item, "actor_id": None, "actor_name": None} for item in activity.data.get("items", [])
    ]
    blocks = dict(summary.blocks)
    blocks[RECENT_ACTIVITY] = Block(
        status=activity.status,
        generated_at=activity.generated_at,
        data={**activity.data, "items": redacted, "actors_hidden": True},
        error_code=activity.error_code,
    )
    return Summary(generated_at=summary.generated_at, blocks=blocks)


# --- Process-local cache ------------------------------------------------ #

_cache: _CacheEntry | None = None
_cache_lock = asyncio.Lock()


async def cached_summary(service: DashboardService, *, ttl_seconds: float, clock: Any) -> Summary:
    """Return a summary no older than `ttl_seconds`.

    The lock makes concurrent requests share one fetch instead of stampeding the
    database with six aggregates each. The returned `generated_at` values are the
    fetch instants, so a cache hit is visibly a cache hit.
    """
    global _cache
    async with _cache_lock:
        now = clock()
        if _cache is not None and now - _cache.stored_at < ttl_seconds:
            return _cache.summary
        summary = await service.summary()
        _cache = _CacheEntry(summary=summary, stored_at=now)
        return summary


def reset_cache() -> None:
    """Drop the cached summary. Tests and process shutdown only."""
    global _cache
    _cache = None
