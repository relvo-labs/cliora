"""The single place that decides **which projects** a query may touch (PX-23, D93).

Today the answer is one line: hold `project.view` and you see every project that has not
been deleted; hold nothing and you see none. RBAC is three global roles and
`_VIEWER_ACTIONS` already contains `PROJECT_VIEW` — there is no `project_members` table
and `services/authz.py` has no project-scope function at all.

**So this module's reason for existing is not today's logic.** It exists so that when
per-project membership arrives, the number of places to edit is one rather than nine, and
`GATE-PX-ONE-PROJECT-SCOPE` is what asserts that it stays one.

That also settles how "no cross-project leakage" is tested in this phase. Written
literally, the upstream exit condition produces a test that gives a role without
`project.view` a 403 — which measures `require_action` and says nothing about the read
model's query boundary. **A frictionless isolation test is worse than none**: it makes the
next reader believe the thing is guarded. So the tests here assert that *the predicate is
applied*, the gate asserts that there is no second path, and the half that cannot be
proved on this deployment — "with membership, counts do not leak existence" — is written
down as an open measurement instead of being covered by a test that always passes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, User
from app.services.authz import may_view_any_project


@dataclass(frozen=True, slots=True)
class ProjectScope:
    """Which projects this caller's query may touch.

    ``all_projects`` is not an optimisation of ``project_ids`` — it is the difference
    between "no predicate is needed" and "these ids". Collapsing the two would mean
    either materialising every project id on every request or emitting no predicate when
    the set is empty, and the second is how a scope check becomes a no-op.
    """

    all_projects: bool
    project_ids: frozenset[uuid.UUID]

    def predicate(self, column: Any) -> ColumnElement[bool]:
        """The `WHERE` fragment. **Never absent, even when it is trivially true.**

        With `all_projects` this is `column IS NOT NULL`, which the planner discards —
        but a call site that receives a real clause every time cannot develop a branch
        that skips it, and that branch is the whole failure mode this type is defending
        against.
        """
        if self.all_projects:
            return column.isnot(None)
        if not self.project_ids:
            # An explicit `false`, never an empty clause. An empty clause would widen
            # the query to everything, which is the exact inversion of what an empty
            # scope means.
            return false()
        return column.in_(self.project_ids)

    def permits(self, project_id: uuid.UUID) -> bool:
        return self.all_projects or project_id in self.project_ids


EMPTY = ProjectScope(all_projects=False, project_ids=frozenset())


async def visible_project_ids(session: AsyncSession, user: User) -> ProjectScope:
    """Today: holding `project.view` means all of them.

    The decision lives in `services/authz.py` — this module composes the predicate but
    does not decide it, which is both what
    `test_authorization_logic_is_confined_to_two_modules` requires and the right split:
    "may this caller see projects" and "which `WHERE` clause expresses that" are two
    different things that will change at different times.

    The `session` parameter is unused on this path and is **kept**: the day membership
    arrives this function needs it, and a signature change would touch every call site —
    which is precisely the fan-out this module exists to prevent. It is also why the
    function is `async` for a body that awaits nothing.
    """
    if not may_view_any_project(user):
        return EMPTY
    return ProjectScope(all_projects=True, project_ids=frozenset())


async def scope_for_project(
    session: AsyncSession, user: User, project_id: uuid.UUID
) -> ProjectScope:
    """The caller's scope, narrowed to the one project they asked for.

    **Two different questions, and the narrowing keeps them apart.** The `project_id` in
    the path is "which one do you want to look at"; the scope is "which ones may you look
    at". Answering the first without the second is how a single-project endpoint becomes
    the hole in a set of otherwise scoped queries — so even here the predicate comes from
    a `ProjectScope`, never from the path parameter directly.
    """
    visible = await visible_project_ids(session, user)
    if not visible.permits(project_id):
        return EMPTY
    return ProjectScope(all_projects=False, project_ids=frozenset({project_id}))


async def project_ids_in_scope(session: AsyncSession, scope: ProjectScope) -> list[uuid.UUID]:
    """Materialise the scope, for the paths that genuinely need a list of ids.

    Only the cross-project counts need this — everything else composes the predicate into
    its own query instead. Kept here rather than at the call site so that "how do I turn
    a scope into ids" has one answer too.
    """
    if not scope.all_projects:
        return sorted(scope.project_ids)
    rows = (await session.execute(select(Project.id).order_by(Project.id))).scalars()
    return list(rows)
