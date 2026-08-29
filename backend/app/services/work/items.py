"""`work-items` and `work-counts`, over one predicate and one project scope (PX-25).

Two functions and they take **the same two objects**: a :class:`ProjectScope` instance and
a :class:`CompiledFilter` instance. Not "the same logic" — the same objects, because the
signatures require the caller to pass them in. That is the mechanism behind SR-3's first
item; a shared helper that each endpoint called separately would be two call sites that
agree until one of them is edited.

**Where the SQL stops.** Fifteen fields are filterable and eleven of them are columns.
`lifecycle` maps onto `tasks.stage` values, so it stays a column comparison. The other
three — `attention`, `readiness`, `execution_status` — are derived, and they are applied
to the derived rows by `filters.matches()`. Both functions here call that same function,
so the boundary does not create a second answer; what it does create is a cost, and the
cost is stated in :func:`work_items`.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fastapi import status
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import Project, Task
from app.services.work.attention import AttentionDTO, derive_attention
from app.services.work.filters import (
    CompiledFilter,
    matches,
)
from app.services.work.projection import WorkRow
from app.services.work.rows import CountRow, WorkRowReader
from app.services.work.scope import ProjectScope

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

# The eight things a board may be grouped by. `attention` is here and **not** in the sort
# allowlist, and the asymmetry is the point: grouping happens within a page that has
# already been derived, while sorting happens in SQL where two of the eight attention
# levels do not exist (ADR 0040 §2).
GROUPS = (
    "lifecycle",
    "owner",
    "epic",
    "risk",
    "requirement",
    "execution_status",
    "attention",
    "blocking_reason",
)

# What a group with no value is called. A key rather than `null`, because a JSON object
# cannot have a null key and because "unassigned" is a group people deliberately look at.
UNGROUPED = "__none__"


@dataclass(frozen=True, slots=True)
class DerivedItem:
    """One card with its attention resolved, ready to shape into a DTO."""

    row: WorkRow
    attention: AttentionDTO


@dataclass(frozen=True, slots=True)
class ItemGroup:
    key: str
    count: int
    items: tuple[DerivedItem, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ItemPage:
    groups: tuple[ItemGroup, ...]
    runtime_signals_available: bool


def encode_cursor(sort_values: Sequence[object], task_id: uuid.UUID) -> str:
    """`(sort key…, id)`, base64url of JSON.

    **Not an offset**: an offset skips a card whenever one is inserted above the window,
    and on a board that people are editing while they read it that happens constantly.
    **Not the sort key alone**: `updated_at` changes under the reader, so `id` is the
    tiebreak — and it is also what keeps paging deterministic while a rebalance is making
    ranks temporarily equal.
    """
    payload = {"k": [str(value) for value in sort_values], "id": str(task_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[list[str], uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return [str(value) for value in payload["k"]], uuid.UUID(str(payload["id"]))
    except (ValueError, KeyError, TypeError, binascii.Error) as bad:
        raise ApiError(
            "INVALID_QUERY",
            "cursor is not valid",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"parameter": "cursor"},
        ) from bad


def group_key_for(item: DerivedItem, group: str) -> str:
    """Which bucket a card falls in. Never None — see :data:`UNGROUPED`."""
    row = item.row
    if group == "lifecycle":
        return row.lifecycle
    if group == "owner":
        return str(row.owner_user_id) if row.owner_user_id else UNGROUPED
    if group == "epic":
        return str(row.epic_id) if row.epic_id else UNGROUPED
    if group == "requirement":
        return str(row.requirement_id) if row.requirement_id else UNGROUPED
    if group == "risk":
        return row.risk
    if group == "execution_status":
        return row.execution
    if group == "attention":
        return item.attention.primary or UNGROUPED
    if group == "blocking_reason":
        return row.blocking_reason or UNGROUPED
    raise AssertionError(f"unhandled group {group}")  # pragma: no cover


def _scoped_select(
    scope: ProjectScope, compiled: CompiledFilter, project_id: uuid.UUID | None
) -> Select[tuple[uuid.UUID]]:
    """The one place a `Task` select is built for the read model.

    Both the project predicate and the filter clause are applied here, and
    `GATE-PX-ONE-PROJECT-SCOPE` scans for any other `select(Task…)` in this package. The
    `project_id` argument narrows *within* the scope — it never replaces it, because
    "which one do you want" and "which may you see" are different questions (D93).
    """
    statement = select(Task.id).where(scope.predicate(Task.project_id), compiled.sql)
    if project_id is not None:
        statement = statement.where(Task.project_id == project_id)
    return statement


async def _derived(
    session: AsyncSession,
    *,
    scope: ProjectScope,
    compiled: CompiledFilter,
    project_id: uuid.UUID | None,
    is_online: Callable[[uuid.UUID], bool] | None,
) -> tuple[list[DerivedItem], bool]:
    """Every card the SQL half admits, derived and then filtered by the derived half.

    **The cost, stated plainly.** This loads the whole SQL-admitted set before paging,
    because three of the filterable fields are not columns and a cursor cannot slice
    around a predicate it has not applied yet. At the sizes this phase targets — a few
    hundred cards a project — that is one page's worth of rows either way, and the
    measurement is in `plan/26/12` §5. It stops being acceptable somewhere above a
    thousand cards *with a derived filter*, and the honest response then is to make
    `execution_status` and `readiness` into real columns rather than to paginate a lie.
    """
    ids = set((await session.execute(_scoped_select(scope, compiled, project_id))).scalars())
    if not ids:
        return [], is_online is not None

    reader = WorkRowReader(session)
    projects = (
        [project_id]
        if project_id is not None
        else list(
            (
                await session.execute(
                    select(Project.id).where(scope.predicate(Project.id)).order_by(Project.id)
                )
            ).scalars()
        )
    )
    items: list[DerivedItem] = []
    runtime_available = is_online is not None
    for candidate in projects:
        project = await session.get(Project, candidate)
        if project is None:  # pragma: no cover - the id came from the same database
            continue
        rows, runtime = await reader.for_project(project, is_online=is_online)
        if runtime is None:
            runtime_available = False
        for row in rows:
            if row.task_id not in ids:
                continue
            attention = derive_attention(row, runtime)
            if not matches(
                compiled,
                lifecycle=row.lifecycle,
                readiness=row.readiness,
                execution=row.execution,
                attention_signals=attention.signals,
            ):
                continue
            items.append(DerivedItem(row=row, attention=attention))
    return items, runtime_available


def _rank_in(values: Sequence[str], value: str) -> int:
    """Semantic position, with an unknown value sorting last.

    Last rather than first, and it matters: an unrecognised risk level is a card nobody
    has classified, and putting it at the top of a risk-sorted board would give it the
    attention that belongs to the ones somebody did classify.
    """
    return values.index(value) if value in values else len(values)


def _sort_key(order: Sequence[tuple[str, bool]]) -> Callable[[DerivedItem], tuple]:
    """The Python-side ordering, matching what SQL would have done.

    Sorting here rather than in SQL because the derived filter has already forced the
    whole set into memory; doing it twice would be the worse of both. The **expressions**
    stay in `filters.ORDER_EXPRESSIONS` so that the allowlist has one definition — the
    day a derived filter is absent and the SQL path is used, the two must agree.
    """
    from app.services.work.filters import _PRIORITY_ORDER, _RISK_ORDER

    def key(item: DerivedItem) -> tuple:
        values: list[object] = []
        for name, descending in order:
            row = item.row
            raw: object
            if name == "rank":
                raw = row.rank or ""
            elif name == "updated_at":
                raw = row.updated_at.timestamp() if row.updated_at else 0.0
            elif name == "created_at":
                raw = row.created_at.timestamp() if row.created_at else 0.0
            elif name == "title":
                raw = row.title
            elif name == "card_ref":
                raw = row.card_ref
            elif name == "priority":
                raw = _rank_in(_PRIORITY_ORDER, row.priority)
            elif name == "risk":
                raw = _rank_in(_RISK_ORDER, row.risk)
            else:  # pragma: no cover - the allowlist is closed
                raise AssertionError(name)
            values.append(_Reversed(raw) if descending else raw)
        values.append(str(item.row.task_id))
        return tuple(values)

    return key


@dataclass(frozen=True, slots=True)
class _Reversed:
    """Descending order for a mixed-type key, without `reverse=` per component."""

    value: object

    def __lt__(self, other: _Reversed) -> bool:
        return bool(other.value < self.value)  # type: ignore[operator]


async def work_items(
    session: AsyncSession,
    *,
    scope: ProjectScope,
    compiled: CompiledFilter,
    project_id: uuid.UUID | None = None,
    group: str | None = None,
    order: Sequence[tuple[str, bool]] = (("rank", False),),
    limit: int = DEFAULT_LIMIT,
    cursors: dict[str, str] | None = None,
    is_online: Callable[[uuid.UUID], bool] | None = None,
) -> ItemPage:
    """One page per group, each with a **server** count and its own cursor.

    `count` is the size of the group, not `len(items)`. That distinction is the one the
    upstream plan called "the commonest lie on a board like this", and it is asserted on
    the server rather than only in the browser.
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError(
            "INVALID_QUERY",
            f"limit must be between 1 and {MAX_LIMIT}",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"parameter": "limit", "maximum": MAX_LIMIT},
        )
    items, runtime_available = await _derived(
        session, scope=scope, compiled=compiled, project_id=project_id, is_online=is_online
    )
    ordered = sorted(items, key=_sort_key(order))
    buckets: dict[str, list[DerivedItem]] = {}
    for item in ordered:
        buckets.setdefault(group_key_for(item, group) if group else "all", []).append(item)

    groups: list[ItemGroup] = []
    for key, bucket in buckets.items():
        start = 0
        cursor = (cursors or {}).get(key)
        if cursor:
            _, after_id = decode_cursor(cursor)
            position = next(
                (index for index, item in enumerate(bucket) if item.row.task_id == after_id),
                None,
            )
            # A cursor whose card has since been filtered out is **not an error**: the
            # card moved or was edited, which is ordinary. Restarting the group is the
            # only answer that cannot silently skip the rest of it.
            start = position + 1 if position is not None else 0
        window = bucket[start : start + limit]
        next_cursor = (
            encode_cursor([], window[-1].row.task_id)
            if window and start + limit < len(bucket)
            else None
        )
        groups.append(
            ItemGroup(key=key, count=len(bucket), items=tuple(window), next_cursor=next_cursor)
        )
    groups.sort(key=lambda entry: entry.key)
    return ItemPage(groups=tuple(groups), runtime_signals_available=runtime_available)


@dataclass(frozen=True, slots=True)
class Counts:
    by_lifecycle: dict[str, int]
    by_attention: dict[str, int]
    total: int
    runtime_signals_available: bool


_CountFlightKey = tuple[object, ...]
_COUNT_FLIGHTS: dict[_CountFlightKey, asyncio.Task[Counts]] = {}


def _count_flight_key(
    scope: ProjectScope, compiled: CompiledFilter, project_id: uuid.UUID | None
) -> _CountFlightKey | None:
    """Identify equal project polls without retaining a completed answer.

    ``work-counts`` is polled on a twenty-second cadence, so a team viewing one project
    produces bursts of identical requests. Sharing only an *in-flight* computation keeps
    every later poll fresh while preventing one event-loop process from decoding the same
    2,000 rows fifty times in succession. The scope and literal filter are part of the
    key: coalescing must never widen either authorization or the requested predicate.
    """
    if project_id is None:
        return None
    literal_sql = str(compiled.sql.compile(compile_kwargs={"literal_binds": True}))
    derived = tuple(
        (term.field, term.op, tuple(sorted(term.values))) for term in compiled.derived_terms
    )
    return (
        project_id,
        scope.all_projects,
        tuple(sorted(str(value) for value in scope.project_ids)),
        literal_sql,
        derived,
    )


async def work_counts(
    session: AsyncSession,
    *,
    scope: ProjectScope,
    compiled: CompiledFilter,
    project_id: uuid.UUID | None = None,
    is_online: Callable[[uuid.UUID], bool] | None = None,
) -> Counts:
    """Coalesce an identical polling burst, then discard the shared computation."""
    key = _count_flight_key(scope, compiled, project_id)
    if key is None:
        return await _work_counts_once(
            session,
            scope=scope,
            compiled=compiled,
            project_id=project_id,
            is_online=is_online,
        )

    existing = _COUNT_FLIGHTS.get(key)
    if existing is not None:
        return await asyncio.shield(existing)

    flight = asyncio.create_task(
        _work_counts_once(
            session,
            scope=scope,
            compiled=compiled,
            project_id=project_id,
            is_online=is_online,
        )
    )
    _COUNT_FLIGHTS[key] = flight

    def clear(done: asyncio.Task[Counts]) -> None:
        if _COUNT_FLIGHTS.get(key) is done:
            _COUNT_FLIGHTS.pop(key, None)

    flight.add_done_callback(clear)
    return await asyncio.shield(flight)


async def _work_counts_once(
    session: AsyncSession,
    *,
    scope: ProjectScope,
    compiled: CompiledFilter,
    project_id: uuid.UUID | None = None,
    is_online: Callable[[uuid.UUID], bool] | None = None,
) -> Counts:
    """The two count breakdowns the board polls, over the same scope and filter.

    **The hottest endpoint in the phase** (D95): every open board tab asks every 20
    seconds. Its budget is P95 < 200 ms. Attention is not a column, so the endpoint uses
    a narrow projection and still calls the same ``derive_attention`` policy as items.
    Keeping one policy costs more than a lifecycle-only ``GROUP BY`` but prevents the
    polling badges and the visible cards from disagreeing.
    """
    ids = set((await session.execute(_scoped_select(scope, compiled, project_id))).scalars())
    if not ids:
        return Counts(
            by_lifecycle={},
            by_attention={},
            total=0,
            runtime_signals_available=is_online is not None,
        )

    projects = (
        [project_id]
        if project_id is not None
        else list(
            (
                await session.execute(
                    select(Project.id).where(scope.predicate(Project.id)).order_by(Project.id)
                )
            ).scalars()
        )
    )
    reader = WorkRowReader(session)
    counted: list[tuple[CountRow, AttentionDTO]] = []
    runtime_available = is_online is not None
    for candidate in projects:
        project = await session.get(Project, candidate)
        if project is None:  # pragma: no cover - selected from this database
            continue
        rows, runtime = await reader.for_project_counts(project, task_ids=ids, is_online=is_online)
        if runtime is None:
            runtime_available = False
        for row in rows:
            attention = derive_attention(row, runtime)
            if not matches(
                compiled,
                lifecycle=row.lifecycle,
                readiness=row.readiness,
                execution=row.execution,
                attention_signals=attention.signals,
            ):
                continue
            counted.append((row, attention))

    by_lifecycle: dict[str, int] = {}
    by_attention: dict[str, int] = {}
    for row, attention in counted:
        by_lifecycle[row.lifecycle] = by_lifecycle.get(row.lifecycle, 0) + 1
        for signal in attention.signals:
            by_attention[signal] = by_attention.get(signal, 0) + 1
    return Counts(
        by_lifecycle=by_lifecycle,
        by_attention=by_attention,
        total=len(counted),
        runtime_signals_available=runtime_available,
    )


async def scoped_task_count(
    session: AsyncSession, *, scope: ProjectScope, compiled: CompiledFilter
) -> int:
    """The SQL-only count, for the paths that have no derived term.

    Kept beside the others so that "how many cards match" has one place to look even when
    the answer takes a shortcut.
    """
    statement = select(func.count()).select_from(_scoped_select(scope, compiled, None).subquery())
    return int((await session.execute(statement)).scalar_one())
