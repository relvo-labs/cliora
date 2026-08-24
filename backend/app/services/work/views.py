"""The five views every project has before anybody asks for one (PX-22, ADR 0042 §3).

**One definition, two callers.** Migration `0043` seeds existing projects and
``ProjectService.create()`` seeds new ones, and both go through the statement built here.
The alternative — a loop in the migration and a second one in the service — produces the
split nobody notices until a customer has projects on both sides of an upgrade and only
half of them open onto a board.

Seeding is **idempotent**: both callers can reach the same project (a project created
during a deployment, a re-run after a failure), and ``ON CONFLICT DO NOTHING`` against
the two unique indexes makes the second attempt a no-op rather than a duplicate-name
error. The conflict target is left unnamed on purpose — `uq_work_views_name` is a partial
expression index and `uq_work_views_default` is a different one, and an unnamed
`DO NOTHING` covers both without restating either.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text


@dataclass(frozen=True, slots=True)
class DefaultView:
    """One seeded project view.

    Every one of these is `scope='project'` with no owner and no `created_by`: the
    platform made it, not a person, and an audit trail that named a user would be
    claiming somebody chose this.
    """

    name: str
    layout: str
    filter: dict[str, Any]
    order_by: list[dict[str, str]]
    group_by: str | None = None
    is_default: bool = False
    position: int = 0
    visible_fields: list[str] = field(default_factory=list)


# The four lanes of the Active Board are **a grouped view, not four hardcoded columns**
# (plan/26/06 §3.1): changing `group_by` changes the grouping without a second piece of
# layout code. `backlog` is deliberately absent — it has its own view.
DEFAULT_VIEWS: tuple[DefaultView, ...] = (
    DefaultView(
        name="Active Work",
        layout="board",
        filter={
            "op": "in",
            "field": "lifecycle",
            "value": ["ready", "in_progress", "review", "done"],
        },
        group_by="lifecycle",
        order_by=[{"field": "rank", "direction": "asc"}],
        is_default=True,
        position=0,
    ),
    DefaultView(
        name="Backlog",
        layout="list",
        filter={"op": "eq", "field": "lifecycle", "value": "backlog"},
        order_by=[{"field": "rank", "direction": "asc"}],
        position=1,
    ),
    DefaultView(
        name="Waiting for Me",
        layout="list",
        filter={"op": "eq", "field": "attention", "value": "waiting_for_your_input"},
        order_by=[{"field": "updated_at", "direction": "desc"}],
        position=2,
    ),
    DefaultView(
        name="Blocked",
        layout="list",
        filter={"op": "eq", "field": "is_blocked", "value": True},
        group_by="blocking_reason",
        order_by=[{"field": "updated_at", "direction": "desc"}],
        position=3,
    ),
    DefaultView(
        name="Verification",
        layout="list",
        filter={"op": "eq", "field": "lifecycle", "value": "review"},
        order_by=[{"field": "updated_at", "direction": "desc"}],
        position=4,
    ),
)

# `INSERT … SELECT` over `projects` rather than a Python loop, so that seeding every
# existing project is one statement per view instead of one per (project × view). The
# `:project_id IS NULL` branch is what lets the migration and the service share it.
_SEED_SQL = """
INSERT INTO work_views (
  id, project_id, owner_user_id, name, layout, scope, filter_json,
  group_by, order_by_json, visible_fields_json, is_default, position
)
SELECT
  gen_random_uuid(), p.id, NULL, :name, :layout, 'project', CAST(:filter AS jsonb),
  :group_by, CAST(:order_by AS jsonb), CAST(:visible_fields AS jsonb),
  :is_default, :position
FROM projects p
WHERE (CAST(:project_id AS uuid) IS NULL OR p.id = CAST(:project_id AS uuid))
ON CONFLICT DO NOTHING
"""


def seed_statements(project_id: uuid.UUID | None = None) -> list[tuple[Any, dict[str, Any]]]:
    """One `(statement, params)` pair per default view.

    Returns statements rather than executing them because the two callers hold different
    kinds of connection — a synchronous Alembic bind and an `AsyncSession` — and a
    function that tried to serve both would either take an executor argument or exist
    twice.
    """
    statement = text(_SEED_SQL)
    return [
        (
            statement,
            {
                "project_id": str(project_id) if project_id is not None else None,
                "name": view.name,
                "layout": view.layout,
                "filter": json.dumps(view.filter),
                "group_by": view.group_by,
                "order_by": json.dumps(view.order_by),
                "visible_fields": json.dumps(view.visible_fields),
                "is_default": view.is_default,
                "position": view.position,
            },
        )
        for view in DEFAULT_VIEWS
    ]
