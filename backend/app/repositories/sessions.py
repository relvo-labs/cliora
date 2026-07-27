"""Persistence for terminal_sessions and session_connections (P2-05).

The only place P2 writes durable session state. Terminal bytes are never
written here (ADR 0004) — only lifecycle metadata and connection roles.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SessionConnection, TerminalSession

# Non-terminal states count against a node's active-session budget.
ACTIVE_STATES = ("starting", "running", "disconnected", "terminating")


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, session: TerminalSession) -> None:
        self._session.add(session)

    async def get(self, session_id: uuid.UUID) -> TerminalSession | None:
        return await self._session.get(TerminalSession, session_id)

    async def list(
        self,
        *,
        node_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[TerminalSession]:
        query = select(TerminalSession)
        if node_id is not None:
            query = query.where(TerminalSession.node_id == node_id)
        if status is not None:
            query = query.where(TerminalSession.status == status)
        query = query.order_by(TerminalSession.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return result.scalars().all()

    async def active_count_for_node(self, node_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(TerminalSession)
            .where(
                TerminalSession.node_id == node_id,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
        )
        return int(result.scalar() or 0)

    async def active_count_for_user(self, user_id: uuid.UUID) -> int:
        """Active sessions this user owns, **across the whole fleet** (P4-14, tech §23 #14).

        Deliberately not scoped to a node: the per-node cap already covers a single
        machine, and the risk this one addresses is one account spreading a hundred
        sessions thinly over a hundred nodes — never tripping the per-node limit while
        consuming the fleet.
        """
        result = await self._session.execute(
            select(func.count())
            .select_from(TerminalSession)
            .where(
                TerminalSession.user_id == user_id,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
        )
        return int(result.scalar() or 0)


class SessionConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, connection: SessionConnection) -> None:
        self._session.add(connection)

    async def open_for_session(self, session_id: uuid.UUID) -> Sequence[SessionConnection]:
        result = await self._session.execute(
            select(SessionConnection).where(
                SessionConnection.session_id == session_id,
                SessionConnection.closed_at.is_(None),
            )
        )
        return result.scalars().all()
