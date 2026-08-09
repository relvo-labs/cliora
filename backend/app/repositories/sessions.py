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
        project_id: uuid.UUID | None = None,
        ad_hoc_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[TerminalSession]:
        # System terminals are excluded (D13/ADR 0021). They are a view of the CLI
        # session that owns them, not a unit of work: opening one from this list
        # would land the user in a workspace with no CLI. They are still counted
        # everywhere capacity is reported — `active_count_*` and
        # `list_active_for_node` below deliberately do *not* filter — because a
        # list that disagrees with the node's own occupancy is worse than a long list.
        query = select(TerminalSession).where(TerminalSession.parent_session_id.is_(None))
        if node_id is not None:
            query = query.where(TerminalSession.node_id == node_id)
        if status is not None:
            query = query.where(TerminalSession.status == status)
        if project_id is not None:
            query = query.where(TerminalSession.project_id == project_id)
        elif ad_hoc_only:
            query = query.where(TerminalSession.project_id.is_(None))
        query = query.order_by(TerminalSession.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return result.scalars().all()

    async def list_active_for_node(self, node_id: uuid.UUID) -> Sequence[TerminalSession]:
        """Every session on a node that has not ended, oldest first.

        Used when an administrator disables a node and asks for its sessions to be
        torn down (FR-NODE-005). Oldest first so a partial failure leaves the
        newest — most likely still in use — for last.
        """
        result = await self._session.execute(
            select(TerminalSession)
            .where(
                TerminalSession.node_id == node_id,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
            .order_by(TerminalSession.created_at.asc())
        )
        return result.scalars().all()

    async def live_shell_for_parent(self, parent_id: uuid.UUID) -> TerminalSession | None:
        """The parent's system terminal, if one is still alive.

        Mirrors the partial unique index in migration 0013; the index is the real
        guarantee, this is the check that turns a would-be IntegrityError into a
        `SHELL_ALREADY_OPEN` the caller can act on.
        """
        result = await self._session.execute(
            select(TerminalSession).where(
                TerminalSession.parent_session_id == parent_id,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
        )
        return result.scalars().first()

    async def live_sessions_for_runtime(self, runtime: str) -> Sequence[TerminalSession]:
        """Every session of one runtime that has not ended, fleet-wide.

        Exists for the shell reaper's startup reconciliation: its timers live in
        one process's memory and are dropped on shutdown, so a restart used to
        leave a detached terminal with nothing left to collect it. The runtime is
        a parameter rather than a hardcoded `"shell"` so this layer keeps knowing
        nothing about which runtime is special — the caller owns that.
        """
        result = await self._session.execute(
            select(TerminalSession).where(
                TerminalSession.runtime == runtime,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
        )
        return result.scalars().all()

    async def live_children(self, parent_id: uuid.UUID) -> Sequence[TerminalSession]:
        """Every live child of a session, for the terminate cascade."""
        result = await self._session.execute(
            select(TerminalSession).where(
                TerminalSession.parent_session_id == parent_id,
                TerminalSession.status.in_(ACTIVE_STATES),
            )
        )
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
