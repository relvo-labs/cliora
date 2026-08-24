"""The filter language: an allowlist with a compiler, not a query DSL (PX-23, D54).

**One model serves three consumers** (D113): the `f=` query parameter, a saved view's
`filter_json`, and `work-counts`. That is not tidiness — it is the type-level half of
"counts and items use the same predicate", and the two halves only mean something
together. kintra's `BoardFilterCriteria` docstring says it in one line: *written twice, it
drifts.*

Three node kinds — `and`, `or`, and a leaf. **There is no `not`.** `neq` and `not_in`
cover the real need, and a `not` node would turn "does this filter exclude resources the
caller may not see" into a question requiring recursive reasoning.

**No dynamic SQL.** Every `(field, op)` pair has one entry in `_COMPILERS`, and
`GATE-PX-NO-DYNAMIC-SQL` scans this package for `text()`, an f-string reaching `where()`,
or string concatenation building SQL. The value of that gate is not that anybody was
about to write string SQL; it is that `attention`'s two-phase compilation (below) is the
one place where SQL is not the whole answer, and a reader has to be able to trust that it
is the *only* one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fastapi import status
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, case, false, or_, true

from app.api.errors import ApiError
from app.db.models import Task
from app.services.tasks import CARD_KINDS, DELIVERIES, PRIORITIES, RISKS
from app.services.work.attention import ATTENTION_ORDER, RUNTIME_LEVELS
from app.services.work.projection import (
    BLOCKING_REASONS,
    EXECUTION_STATUSES,
    LIFECYCLE_ORDER,
    READINESS_STATES,
)

# --- limits ------------------------------------------------------------------------

MAX_DEPTH = 3
MAX_TERMS = 20
MAX_VALUES = 50

# --- the fifteen fields ------------------------------------------------------------

EQUALITY = ("eq", "neq")
MEMBERSHIP = ("in", "not_in")
COMPARISON = ("gt", "lt")
NULLABILITY = ("is_null",)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One filterable field: its operators, and how a value is checked.

    ``values`` is the closed set for an enum and None for everything else. A field whose
    values are open (a uuid, a timestamp) is checked by parsing rather than by
    membership, and the difference matters for the error: an unparseable uuid is a 422
    about a *value*, while an unknown field name is `FILTER_FIELD_NOT_ALLOWED`.
    """

    ops: tuple[str, ...]
    kind: Literal["enum", "uuid", "bool", "timestamp", "labels"]
    values: frozenset[str] | None = None


FIELDS: dict[str, FieldSpec] = {
    # Projected in phase A, not stored (ADR 0040 §1).
    "lifecycle": FieldSpec(EQUALITY + MEMBERSHIP, "enum", frozenset(LIFECYCLE_ORDER)),
    "readiness": FieldSpec(EQUALITY + MEMBERSHIP, "enum", frozenset(READINESS_STATES)),
    # **The only two-phase field.** See `split_attention_terms`.
    "attention": FieldSpec(EQUALITY + MEMBERSHIP, "enum", frozenset(ATTENTION_ORDER)),
    "execution_status": FieldSpec(EQUALITY + MEMBERSHIP, "enum", frozenset(EXECUTION_STATUSES)),
    "is_blocked": FieldSpec(EQUALITY, "bool"),
    "blocking_reason": FieldSpec(
        EQUALITY + MEMBERSHIP + NULLABILITY, "enum", frozenset(BLOCKING_REASONS)
    ),
    "owner": FieldSpec(EQUALITY + MEMBERSHIP + NULLABILITY, "uuid"),
    "assigned_runner": FieldSpec(EQUALITY + MEMBERSHIP + NULLABILITY, "uuid"),
    # `contains` and nothing else: the column is a JSONB array, so equality against it
    # would mean "this card asks for exactly these tags", which nobody wants to express.
    "required_labels": FieldSpec(("contains",), "labels"),
    "risk": FieldSpec(EQUALITY + MEMBERSHIP, "enum", RISKS),
    "priority": FieldSpec(EQUALITY + MEMBERSHIP, "enum", PRIORITIES),
    "delivery": FieldSpec(EQUALITY + MEMBERSHIP, "enum", DELIVERIES),
    "card_kind": FieldSpec(EQUALITY + MEMBERSHIP, "enum", CARD_KINDS),
    "requirement": FieldSpec(EQUALITY + MEMBERSHIP + NULLABILITY, "uuid"),
    "epic": FieldSpec(EQUALITY + MEMBERSHIP + NULLABILITY, "uuid"),
    "user_story": FieldSpec(EQUALITY + MEMBERSHIP + NULLABILITY, "uuid"),
    "updated_at": FieldSpec(COMPARISON, "timestamp"),
    "created_at": FieldSpec(COMPARISON, "timestamp"),
}

# The columns the SQL-compilable fields map onto. `lifecycle`, `readiness`, `attention`
# and `execution_status` are **absent on purpose** — they are projections, so their
# compilers below build an expression instead of naming a column.
_COLUMNS: dict[str, Any] = {
    "is_blocked": Task.is_blocked,
    "blocking_reason": Task.blocking_reason,
    "owner": Task.owner_user_id,
    "assigned_runner": Task.assigned_runner_id,
    "required_labels": Task.required_labels,
    "risk": Task.risk,
    "priority": Task.priority,
    "delivery": Task.delivery,
    "card_kind": Task.card_kind,
    "requirement": Task.requirement_id,
    "epic": Task.epic_id,
    "user_story": Task.user_story_id,
    "updated_at": Task.updated_at,
    "created_at": Task.created_at,
}

# `tasks.stage` values per lifecycle value. The inverse of
# `projection._LIFECYCLE_FOR_STAGE`, written out rather than derived so that a filter on
# a projection is a plain `IN` over a column and stays indexable by
# `ix_tasks_project_stage`.
_STAGES_FOR_LIFECYCLE: dict[str, tuple[str, ...]] = {
    "backlog": ("backlog",),
    "ready": ("ready", "blocked"),
    "in_progress": ("implementing",),
    "review": ("verify",),
    "done": ("done",),
}

# --- sort ordering -----------------------------------------------------------------

ORDER_FIELDS = ("rank", "updated_at", "created_at", "priority", "risk", "title", "card_ref")
MAX_ORDER_DEPTH = 2

# `priority` and `risk` are string enums, and a board must sort them by **meaning**, not
# alphabetically ("high" < "low" < "normal" is nonsense on a screen). Compiled to a CASE;
# `test_the_semantic_orders_cover_their_value_sets` pins these against the frozensets in
# `services/tasks.py`, so adding a value there without a rank here fails.
_PRIORITY_ORDER = ("low", "normal", "high")
_RISK_ORDER = ("low", "medium", "high", "critical")


def _semantic_order(column: Any, values: Sequence[str]) -> Any:
    return case(
        {value: index for index, value in enumerate(values)}, value=column, else_=len(values)
    )


# `Any` rather than `ColumnElement[Any]`: SQLAlchemy's mapped attributes are
# `InstrumentedAttribute`, which is usable in `order_by` but is not that type.
ORDER_EXPRESSIONS: dict[str, Callable[[], Any]] = {
    "rank": lambda: Task.rank,
    "updated_at": lambda: Task.updated_at,
    "created_at": lambda: Task.created_at,
    "title": lambda: Task.title,
    "card_ref": lambda: Task.card_ref,
    "priority": lambda: _semantic_order(Task.priority, _PRIORITY_ORDER),
    "risk": lambda: _semantic_order(Task.risk, _RISK_ORDER),
}


# --- the request model -------------------------------------------------------------


class FilterNode(BaseModel):
    """One node, in the only three shapes there are.

    A single permissive model rather than a discriminated union, because the shape is
    validated by :func:`compile_filter` anyway and a union would report a Pydantic error
    where the API contract promises `FILTER_FIELD_NOT_ALLOWED` with the field named.
    """

    and_: list[FilterNode] | None = Field(default=None, alias="and")
    or_: list[FilterNode] | None = Field(default=None, alias="or")
    field: str | None = None
    op: str | None = None
    value: Any = None

    model_config = {"populate_by_name": True}


FilterNode.model_rebuild()


# Fields whose value is **derived rather than stored**, and which therefore cannot be a
# column comparison. `lifecycle` is not among them: it maps onto `tasks.stage` values, so
# it compiles to an `IN` that `ix_tasks_project_stage` still serves.
#
# The other three do not, and each for its own reason:
#
# * `attention` is eight predicates over six other facts, two of which are not in the
#   database at all (ADR 0040 §2);
# * `readiness` depends on the **project's** effective process, so the same JSONB
#   contents mean different things in two projects;
# * `execution_status` is the newest active run, else the newest run — a window function
#   over `task_runs` that the read model already computes once per page.
#
# They are applied to the derived rows instead, by :func:`matches`. **Both `work-items`
# and `work-counts` call that one function**, which is what keeps "counts and items use
# the same predicate" true across the SQL boundary rather than only up to it.
DERIVED_FIELDS = frozenset({"attention", "readiness", "execution_status"})


@dataclass(frozen=True, slots=True)
class DerivedTerm:
    """One condition that is evaluated after the rows are derived.

    Data rather than a closure, so a caller can ask *what* is still outstanding — which
    is how `work-items` knows whether it needs the node registry at all, and how the size
    of the candidate set it must load is decided.
    """

    field: str
    op: str
    values: frozenset[str]

    @property
    def negated(self) -> bool:
        return self.op in ("neq", "not_in")

    @property
    def needs_runtime(self) -> bool:
        return self.field == "attention" and bool(self.values & RUNTIME_LEVELS)

    def holds(self, actual: str | None) -> bool:
        hit = actual is not None and actual in self.values
        return not hit if self.negated else hit


@dataclass(frozen=True, slots=True)
class CompiledFilter:
    """The SQL half and the derived half, as **one object**.

    Passed whole to both `work_items` and `work_counts` rather than as a bare clause,
    because the two must not each remember to apply the second half. A caller that used
    only `sql` would get *more* rows than asked for — the direction that leaks — and
    nothing would fail.
    """

    sql: ColumnElement[bool]
    derived_terms: tuple[DerivedTerm, ...] = ()

    @property
    def needs_runtime(self) -> bool:
        """Whether phase B has to run for this filter to be answerable.

        Distinct from "the caller would like runtime signals": a filter naming
        `no_eligible_runner` is **unanswerable** without the registry, and the endpoint
        says so rather than returning a plausible subset.
        """
        return any(term.needs_runtime for term in self.derived_terms)

    @property
    def has_derived(self) -> bool:
        return bool(self.derived_terms)


def matches(
    term_holder: CompiledFilter,
    *,
    lifecycle: str,
    readiness: str,
    execution: str,
    attention_signals: Sequence[str],
) -> bool:
    """Evaluate the derived half against one derived row.

    `attention` is checked against the **whole signal set**, not only the primary: a
    person asking for "cards where a run failed" means cards where that is true, not
    cards where it is the single most urgent thing. The primary is a presentation
    decision (D107); the filter is a question about facts.
    """
    for term in term_holder.derived_terms:
        if term.field == "readiness":
            if not term.holds(readiness):
                return False
        elif term.field == "execution_status":
            if not term.holds(execution):
                return False
        elif term.field == "attention":
            hit = any(signal in term.values for signal in attention_signals)
            if (not hit) if not term.negated else hit:
                return False
    del lifecycle  # applied in SQL; named so the signature documents the full set
    return True


def _not_allowed_field(name: str) -> ApiError:
    return ApiError(
        "FILTER_FIELD_NOT_ALLOWED",
        f"`{name}` is not a filterable field",
        status.HTTP_400_BAD_REQUEST,
        details={"field": name, "allowed_fields": sorted(FIELDS)},
    )


def _not_allowed_op(name: str, op: str, spec: FieldSpec) -> ApiError:
    return ApiError(
        "FILTER_OP_NOT_ALLOWED",
        f"`{op}` is not available on `{name}`",
        status.HTTP_400_BAD_REQUEST,
        # **`allowed_ops` is the point of this error.** What the reader has to do is pick
        # a different operator, and telling them which ones exist saves the round trip
        # to the documentation — the same reasoning as `_smallest_missing_tags` in
        # `services/runs.py`.
        details={"field": name, "op": op, "allowed_ops": list(spec.ops)},
    )


def _too_complex(limit: str, actual: int, maximum: int) -> ApiError:
    return ApiError(
        "FILTER_TOO_COMPLEX",
        f"this filter exceeds the {limit} limit ({actual} > {maximum})",
        status.HTTP_400_BAD_REQUEST,
        details={"limit": limit, "actual": actual, "maximum": maximum},
    )


def _invalid_value(name: str, reason: str) -> ApiError:
    # `INVALID_QUERY`, the code this deployment already uses for "a value in a query is
    # outside the permitted bounds" — **not** one of the three new codes. A malformed
    # uuid is a problem with the value, and calling it `FILTER_FIELD_NOT_ALLOWED` would
    # send the reader to change a field name that was correct (plan/26/04 §3).
    return ApiError(
        "INVALID_QUERY",
        f"`{name}`: {reason}",
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        details={"field": name},
    )


def _coerce(name: str, spec: FieldSpec, value: Any) -> Any:
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise _invalid_value(name, "expected true or false")
        return value
    if spec.kind == "enum":
        assert spec.values is not None
        if not isinstance(value, str) or value not in spec.values:
            raise _invalid_value(name, f"expected one of {sorted(spec.values)}")
        return value
    if spec.kind == "uuid":
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError) as bad:
            raise _invalid_value(name, "expected a uuid") from bad
    if spec.kind == "timestamp":
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError) as bad:
            raise _invalid_value(name, "expected an ISO 8601 timestamp") from bad
    if spec.kind == "labels":
        if not isinstance(value, str) or not value:
            raise _invalid_value(name, "expected a single label")
        return value
    raise AssertionError(f"unhandled field kind {spec.kind}")  # pragma: no cover


def _leaf_sql(name: str, op: str, value: Any) -> ColumnElement[bool]:
    """One `(field, op)` pair. Every branch names its column or its expression."""
    if name == "lifecycle":
        stages = (
            _STAGES_FOR_LIFECYCLE[value]
            if op in EQUALITY
            else tuple(stage for level in value for stage in _STAGES_FOR_LIFECYCLE[level])
        )
        clause = Task.stage.in_(stages)
        return ~clause if op in ("neq", "not_in") else clause
    if name in DERIVED_FIELDS:  # pragma: no cover - routed above
        raise AssertionError(f"{name} is a derived field and has no column")

    column = _COLUMNS[name]
    if op == "eq":
        return column.is_(None) if value is None else column == value
    if op == "neq":
        return column.isnot(None) if value is None else column != value
    if op == "in":
        return column.in_(value)
    if op == "not_in":
        return ~column.in_(value)
    if op == "gt":
        return column > value
    if op == "lt":
        return column < value
    if op == "is_null":
        return column.is_(None) if value else column.isnot(None)
    if op == "contains":
        return column.contains([value])
    raise AssertionError(f"unhandled operator {op}")  # pragma: no cover


@dataclass
class _Walk:
    """Mutable accounting for one compilation: term count and the derived conditions."""

    terms: int = 0
    derived: list[DerivedTerm] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.derived = []


def split_attention_terms(
    op: str, levels: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Divide an `attention` condition into its phase-A and phase-B halves.

    **The one place in this compiler where the two phases are separated**, isolated into
    a function for exactly that reason: a reader auditing "where does this query stop
    being a query" has one place to look rather than a decision spread across the
    compiler.

    Four combinations, and the negations of two of them:

    ===============================  ================================================
    all levels are SQL levels        the derived rows answer it without the registry
    all levels are runtime levels    the registry is required; refuse without it
    mixed                            both, and the registry is still required
    negated, containing a runtime    the same split, complemented
    ===============================  ================================================
    """
    runtime = tuple(level for level in levels if level in RUNTIME_LEVELS)
    sql_levels = tuple(level for level in levels if level not in RUNTIME_LEVELS)
    del op  # the negation is carried by the term, not by the split
    return sql_levels, runtime


#: How long a search string may be. Not a safety limit — the value is a bind parameter
#: and cannot be anything but a string — but a sanity one: past this it is not a search.
MAX_SEARCH_LENGTH = 200


def search_clause(search: str | None) -> ColumnElement[bool] | None:
    """`q=` — **a parameter of its own, not a sixteenth field.**

    The filter language is a closed allowlist of fifteen fields with one compilation path
    per `(field, op)` pair, and `GATE-PX-NO-DYNAMIC-SQL` is what makes that checkable.
    Free text does not fit that shape: there is no enum to validate against and no
    operator that means "roughly". Adding it as a field would have meant one field whose
    values are unconstrained sitting inside the structure whose whole property is that
    they are not — so search is a separate parameter that compiles to a separate clause
    (`plan/26/04` §2 lists fifteen fields; `plan/26/06` §2 draws Search as its own
    control, beside Filter rather than inside it).

    **Title and card reference, and nothing else.** A description search sounds free and
    is not: descriptions are long, so it turns every keystroke into a sequential scan of
    the largest column on the table, and it matches text nobody was looking at. Somebody
    searching a board is looking for a card they can name.

    The three LIKE metacharacters are escaped, so a search for `100%` finds cards with
    `100%` in the title rather than every card. `ilike` with an explicit `escape` rather
    than a `text()` fragment: this module compiles to expressions, never to SQL strings.
    """
    if search is None:
        return None
    needle = search.strip()
    if not needle:
        # `None` rather than `true()`, so the caller can tell "no search" from "a search
        # that matches everything" and leave the clause out of the `AND` entirely. An
        # extra `AND true` is harmless in SQL and noise in a query plan somebody reads.
        return None
    if len(needle) > MAX_SEARCH_LENGTH:
        raise ApiError(
            "INVALID_QUERY",
            f"A search string is at most {MAX_SEARCH_LENGTH} characters",
            status.HTTP_400_BAD_REQUEST,
            details={"length": len(needle), "maximum": MAX_SEARCH_LENGTH},
        )
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        Task.title.ilike(pattern, escape="\\"),
        Task.card_ref.ilike(pattern, escape="\\"),
    )


def compile_filter(
    node: FilterNode | None,
    *,
    actor_id: uuid.UUID | None = None,
    search: str | None = None,
) -> CompiledFilter:
    """Validate and compile. Raises `ApiError` with a named field or operator.

    ``actor_id`` expands ``owner = "@me"``. **At validation time, not compilation time**
    (plan/26/04 §7): a shared project view stores the literal `@me`, and expanding it per
    request is what makes such a view show *each reader* their own cards. Bound at
    compile time it would be the author's cards forever, for everybody.

    ``search`` is folded in **here**, into the same object, for the reason `CompiledFilter`
    exists at all: `work_items` and `work_counts` take one instance, so a search that was
    a second parameter would be a second thing each of them had to remember to apply — and
    the failure of forgetting it in `work_counts` is a header that disagrees with the list
    below it. Exit condition 1 is that those two never disagree.
    """
    walk = _Walk()
    clause = _compile_node(node, walk=walk, depth=1, actor_id=actor_id)
    text_clause = search_clause(search)
    return CompiledFilter(
        sql=clause if text_clause is None else and_(clause, text_clause),
        derived_terms=tuple(walk.derived),
    )


def _compile_node(
    node: FilterNode | None, *, walk: _Walk, depth: int, actor_id: uuid.UUID | None
) -> ColumnElement[bool]:
    if node is None:
        return true()
    if depth > MAX_DEPTH:
        raise _too_complex("depth", depth, MAX_DEPTH)
    if node.and_ is None and node.or_ is None and node.field is None and node.op is None:
        # `{}` — an empty object. A saved view with no filter and a request with no `f=`
        # both arrive as this, and both mean unfiltered. Treating it as a malformed leaf
        # would make "show me everything" an error.
        return true()
    children = node.and_ if node.and_ is not None else node.or_
    if children is not None:
        if not children:
            # An empty group is not an error and not "match nothing": a view whose
            # filter is `{"and": []}` means unfiltered, which is what an empty
            # conjunction means anyway.
            return true() if node.and_ is not None else false()
        compiled = [
            _compile_node(child, walk=walk, depth=depth + 1, actor_id=actor_id)
            for child in children
        ]
        return and_(*compiled) if node.and_ is not None else or_(*compiled)

    walk.terms += 1
    if walk.terms > MAX_TERMS:
        raise _too_complex("terms", walk.terms, MAX_TERMS)
    if node.field is None or node.op is None:
        raise _not_allowed_field(str(node.field))
    spec = FIELDS.get(node.field)
    if spec is None:
        raise _not_allowed_field(node.field)
    if node.op not in spec.ops:
        raise _not_allowed_op(node.field, node.op, spec)

    value = node.value
    if node.op in MEMBERSHIP:
        if not isinstance(value, list):
            raise _invalid_value(node.field, "expected a list")
        if len(value) > MAX_VALUES:
            raise _too_complex("values", len(value), MAX_VALUES)
        if node.field == "owner" and actor_id is not None:
            value = [str(actor_id) if item == "@me" else item for item in value]
        coerced: Any = [_coerce(node.field, spec, item) for item in value]
    elif node.op == "is_null":
        if not isinstance(value, bool):
            raise _invalid_value(node.field, "expected true or false")
        coerced = value
    else:
        if node.field == "owner" and value == "@me" and actor_id is not None:
            value = str(actor_id)
        coerced = None if value is None else _coerce(node.field, spec, value)

    if node.field in DERIVED_FIELDS:
        levels = coerced if isinstance(coerced, list) else [coerced]
        walk.derived.append(DerivedTerm(field=node.field, op=node.op, values=frozenset(levels)))
        # `true()` here is not "match everything": the condition is carried in
        # `derived_terms` and applied by `matches()`. Returning a clause that pretended
        # to constrain would be worse than returning none, because it would be wrong.
        return true()
    return _leaf_sql(node.field, node.op, coerced)


def compile_order(spec: str | None) -> list[tuple[str, bool]]:
    """`"rank:asc,updated_at:desc"` → `[("rank", False), ("updated_at", True)]`.

    **`attention` is not in the allowlist** (D92): two of its eight levels are not in
    SQL, and an ordering that is *mostly* right is harder to debug than none. The product
    answer is to **group** by attention — grouping happens within a page — and the
    grouping vocabulary does include it.
    """
    if not spec:
        return [("rank", False)]
    parsed: list[tuple[str, bool]] = []
    for part in spec.split(","):
        name, _, direction = part.strip().partition(":")
        if name not in ORDER_FIELDS:
            raise ApiError(
                "FILTER_FIELD_NOT_ALLOWED",
                f"`{name}` is not a sortable field",
                status.HTTP_400_BAD_REQUEST,
                details={"field": name, "allowed_fields": list(ORDER_FIELDS)},
            )
        if direction not in ("", "asc", "desc"):
            raise _invalid_value(name, "direction must be asc or desc")
        parsed.append((name, direction == "desc"))
    if len(parsed) > MAX_ORDER_DEPTH:
        raise _too_complex("order", len(parsed), MAX_ORDER_DEPTH)
    return parsed
