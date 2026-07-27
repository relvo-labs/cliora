"""Persistence for workspace favourites and the derived recent list (P4-13)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Node, TerminalSession, WorkspaceFavorite


@dataclass(frozen=True, slots=True)
class FavoriteRow:
    """A favourite plus its node's display name.

    Deliberately carries no `is_enabled`/liveness copy. It used to, and the service
    read it as a shortcut before fetching the node — which is how the create path came
    to report a different verdict than the listing for the same row. The usability
    verdict now has exactly one source (`services.favorites.usability`), so there is
    nothing here for a caller to decide it from.
    """

    favorite: WorkspaceFavorite
    node_name: str


@dataclass(frozen=True, slots=True)
class RecentWorkspace:
    node_id: uuid.UUID
    node_name: str
    node_enabled: bool
    path: str
    last_used_at: datetime


class FavoriteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int) -> list[FavoriteRow]:
        """One user's favourites, newest first, excluding soft-deleted nodes.

        Joined to `nodes` rather than fetched separately: the UI has to say whether each
        entry is usable *now*, and a favourite whose node was removed is not.
        """
        result = await self._session.execute(
            select(WorkspaceFavorite, Node.name)
            .join(Node, Node.id == WorkspaceFavorite.node_id)
            .where(WorkspaceFavorite.user_id == user_id, Node.deleted_at.is_(None))
            .order_by(WorkspaceFavorite.created_at.desc())
            .limit(limit)
        )
        return [FavoriteRow(favorite=favorite, node_name=name) for favorite, name in result.all()]

    async def find(
        self, user_id: uuid.UUID, node_id: uuid.UUID, path: str
    ) -> WorkspaceFavorite | None:
        result = await self._session.execute(
            select(WorkspaceFavorite).where(
                WorkspaceFavorite.user_id == user_id,
                WorkspaceFavorite.node_id == node_id,
                WorkspaceFavorite.path == path,
            )
        )
        return result.scalars().first()

    async def get_owned(
        self, favorite_id: uuid.UUID, user_id: uuid.UUID
    ) -> WorkspaceFavorite | None:
        """Fetch scoped to the owner in one query.

        Ownership is part of the lookup rather than a check afterwards: that way there is
        no code path where a row is loaded and the check is forgotten, and "not yours" and
        "does not exist" are indistinguishable to the caller by construction.
        """
        result = await self._session.execute(
            select(WorkspaceFavorite).where(
                WorkspaceFavorite.id == favorite_id,
                WorkspaceFavorite.user_id == user_id,
            )
        )
        return result.scalars().first()

    def add(self, favorite: WorkspaceFavorite) -> None:
        self._session.add(favorite)

    async def delete(self, favorite: WorkspaceFavorite) -> None:
        await self._session.delete(favorite)

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count(WorkspaceFavorite.id)).where(WorkspaceFavorite.user_id == user_id)
        )
        return int(result.scalar_one())

    async def recent_for_user(self, user_id: uuid.UUID, *, limit: int) -> list[RecentWorkspace]:
        """Distinct `(node, workspace)` pairs this user most recently started a session in.

        Derived from `terminal_sessions`, with no table of its own. Two consequences worth
        stating because they are deliberate:

        * a **terminated** session still counts. "Recently used" is history, not a list of
          what is running — the whole point is to get back to somewhere you were.
        * a soft-deleted node is excluded, so the list cannot offer a machine that is gone.
        """
        latest = (
            select(
                TerminalSession.node_id.label("node_id"),
                TerminalSession.workspace.label("workspace"),
                func.max(TerminalSession.created_at).label("last_used_at"),
            )
            .where(TerminalSession.user_id == user_id)
            .group_by(TerminalSession.node_id, TerminalSession.workspace)
            .subquery()
        )
        result = await self._session.execute(
            select(
                latest.c.node_id,
                Node.name,
                Node.is_enabled,
                latest.c.workspace,
                latest.c.last_used_at,
            )
            .join(Node, Node.id == latest.c.node_id)
            .where(Node.deleted_at.is_(None))
            .order_by(latest.c.last_used_at.desc())
            .limit(limit)
        )
        return [
            RecentWorkspace(
                node_id=node_id,
                node_name=name,
                node_enabled=enabled,
                path=path,
                last_used_at=last_used_at,
            )
            for node_id, name, enabled, path, last_used_at in result.all()
        ]
