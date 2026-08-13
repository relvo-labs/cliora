"""Persistence for projects, their workspace bindings and their activity timeline (PJ-02/PJ-04)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActivityEvent, Node, Project, ProjectWorkspace, TerminalSession, User
from app.repositories.sessions import ACTIVE_STATES
from app.services.activity import ActivityItem


@dataclass(frozen=True, slots=True)
class BindingRow:
    """A binding plus the node's display name and current enablement.

    Carries no usability verdict. That is computed by the service from the live node
    and the allowed-root check, and `services/favorites.py` records what happens when
    a row carries a shortcut copy instead: the create path and the listing began
    disagreeing about the same binding.
    """

    binding: ProjectWorkspace
    node_name: str
    node_enabled: bool


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    project: Project
    owner_name: str
    binding_count: int
    node_count: int
    active_session_count: int
    last_activity_at: datetime | None


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: uuid.UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_by_slug(self, slug: str) -> Project | None:
        return (
            await self._session.execute(select(Project).where(Project.slug == slug))
        ).scalar_one_or_none()

    async def list_summaries(
        self,
        *,
        status: str | None,
        owner_user_id: uuid.UUID | None,
        limit: int,
        offset: int,
        project_id: uuid.UUID | None = None,
    ) -> list[ProjectSummary]:
        """Projects with their counts, newest first.

        The three counts are computed as correlated subqueries rather than stored on
        `projects`. A stored count is a second source of truth for a fact the rows
        already carry, and `0011_workspace_favorites.py` records the same judgement
        for "recently used workspaces": a second store can only ever disagree.
        """
        bindings = (
            select(func.count())
            .select_from(ProjectWorkspace)
            .join(Node, Node.id == ProjectWorkspace.node_id)
            .where(ProjectWorkspace.project_id == Project.id, Node.deleted_at.is_(None))
            .scalar_subquery()
        )
        nodes = (
            select(func.count(func.distinct(ProjectWorkspace.node_id)))
            .select_from(ProjectWorkspace)
            .join(Node, Node.id == ProjectWorkspace.node_id)
            .where(ProjectWorkspace.project_id == Project.id, Node.deleted_at.is_(None))
            .scalar_subquery()
        )
        sessions = (
            select(func.count())
            .select_from(TerminalSession)
            .where(
                TerminalSession.project_id == Project.id,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
            .scalar_subquery()
        )
        last_activity = (
            select(func.max(ActivityEvent.occurred_at))
            .where(ActivityEvent.project_id == Project.id)
            .scalar_subquery()
        )

        stmt = (
            select(Project, User.display_name, bindings, nodes, sessions, last_activity)
            .join(User, User.id == Project.owner_user_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(Project.status == status)
        if owner_user_id is not None:
            stmt = stmt.where(Project.owner_user_id == owner_user_id)
        if project_id is not None:
            stmt = stmt.where(Project.id == project_id)

        rows = (await self._session.execute(stmt)).all()
        return [
            ProjectSummary(
                project=row[0],
                owner_name=row[1],
                binding_count=int(row[2] or 0),
                node_count=int(row[3] or 0),
                active_session_count=int(row[4] or 0),
                last_activity_at=row[5],
            )
            for row in rows
        ]

    async def summary(self, project: Project) -> ProjectSummary:
        # Filter in SQL. The previous implementation loaded the newest 1,000 rows
        # and searched them in Python, which made a perfectly valid older project
        # turn into a 500 once the deployment crossed that arbitrary count.
        summaries = await self.list_summaries(
            status=None,
            owner_user_id=None,
            limit=1,
            offset=0,
            project_id=project.id,
        )
        if not summaries:  # pragma: no cover - caller already loaded the row
            raise LookupError(project.id)
        return summaries[0]

    async def list_bindings(self, project_id: uuid.UUID) -> list[BindingRow]:
        """A project's bindings, **excluding soft-deleted nodes**.

        This filter is the reason exit condition 4 reads the way it does: node removal
        is a soft delete (ADR 0011), so `ON DELETE CASCADE` never fires on the normal
        path and the row survives. It disappears from the UI because of this `WHERE`,
        which also means re-enabling a node removed by mistake brings its bindings
        back.
        """
        rows = (
            await self._session.execute(
                select(ProjectWorkspace, Node.name, Node.is_enabled)
                .join(Node, Node.id == ProjectWorkspace.node_id)
                .where(ProjectWorkspace.project_id == project_id, Node.deleted_at.is_(None))
                .order_by(ProjectWorkspace.is_primary.desc(), ProjectWorkspace.created_at)
            )
        ).all()
        return [
            BindingRow(binding=row[0], node_name=row[1], node_enabled=bool(row[2])) for row in rows
        ]

    async def get_binding(
        self, project_id: uuid.UUID, binding_id: uuid.UUID
    ) -> ProjectWorkspace | None:
        return (
            await self._session.execute(
                select(ProjectWorkspace).where(
                    ProjectWorkspace.id == binding_id,
                    ProjectWorkspace.project_id == project_id,
                )
            )
        ).scalar_one_or_none()

    async def find_binding(
        self, project_id: uuid.UUID, *, node_id: uuid.UUID, path: str
    ) -> ProjectWorkspace | None:
        """The row a repeat bind would duplicate.

        Paired with the unique constraint, not trusted instead of it: this makes the
        common case a 200 with the existing row, while the constraint is what makes
        two concurrent binds impossible.
        """
        return (
            await self._session.execute(
                select(ProjectWorkspace).where(
                    ProjectWorkspace.project_id == project_id,
                    ProjectWorkspace.node_id == node_id,
                    ProjectWorkspace.path == path,
                )
            )
        ).scalar_one_or_none()

    async def binding_exists(self, project_id: uuid.UUID, *, node_id: uuid.UUID, path: str) -> bool:
        return (await self.find_binding(project_id, node_id=node_id, path=path)) is not None

    async def list_activity(
        self,
        project_id: uuid.UUID,
        *,
        limit: int,
        before: tuple[datetime, uuid.UUID] | None,
        task_id: uuid.UUID | None = None,
    ) -> list[ActivityItem]:
        """One page of the timeline, newest first.

        Keyset rather than offset, and the tiebreaker is not decoration: ordering by
        `occurred_at` alone leaves rows written in the same millisecond in an
        unspecified order between the two queries, so a page boundary landing mid-tie
        drops or repeats entries. `(occurred_at DESC, id DESC)` makes the order total.
        """
        stmt = (
            select(ActivityEvent, User.display_name)
            .outerjoin(User, User.id == ActivityEvent.actor_user_id)
            .where(ActivityEvent.project_id == project_id)
            .order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc())
            .limit(limit)
        )
        if before is not None:
            occurred_at, last_id = before
            stmt = stmt.where(
                func.row(ActivityEvent.occurred_at, ActivityEvent.id)
                < func.row(occurred_at, last_id)
            )
        if task_id is not None:
            stmt = stmt.where(ActivityEvent.task_id == task_id)
        rows = (await self._session.execute(stmt)).all()
        return [
            ActivityItem(
                id=event.id,
                kind=event.kind,
                occurred_at=event.occurred_at,
                payload=dict(event.activity_payload or {}),
                actor_id=event.actor_user_id,
                actor_name=actor_name,
                session_id=event.session_id,
                # Carried through redaction: it says what *kind* of actor, never which
                # one, and without it an agent's write is indistinguishable from a
                # system event and from a user event the reader may not attribute.
                actor_kind=event.actor_kind,
            )
            for event, actor_name in rows
        ]
