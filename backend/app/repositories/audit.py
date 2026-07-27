from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Node, User


@dataclass(frozen=True)
class AuditRow:
    """One audit row with the display names its ids resolve to.

    The names are joined in, not stored, so a renamed user or a soft-deleted node
    still reads correctly — and a row whose subject was hard-deleted keeps its
    ids with `None` names rather than disappearing from the trail.
    """

    entry: AuditLog
    username: str | None
    display_name: str | None
    node_name: str | None


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int,
        actions: Sequence[str] | None = None,
        user_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        cursor: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[AuditRow]:
        """Newest-first keyset page over the trail.

        Ordering and paging are on `(created_at, id)` — the composite the query
        indexes cover (migration `0008`). `id` breaks ties because `created_at`
        alone is not unique: two rows written in the same transaction share a
        `now()`, and an offset- or timestamp-only cursor would then repeat or skip
        them. Rows inserted *after* the first page is fetched cannot shift a later
        page either, which an OFFSET would not survive.
        """
        statement = (
            select(AuditLog, User.username, User.display_name, Node.name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .outerjoin(Node, Node.id == AuditLog.node_id)
            .where(AuditLog.created_at >= start, AuditLog.created_at <= end)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        if actions:
            statement = statement.where(AuditLog.action.in_(list(actions)))
        if user_id is not None:
            statement = statement.where(AuditLog.user_id == user_id)
        if node_id is not None:
            statement = statement.where(AuditLog.node_id == node_id)
        if session_id is not None:
            statement = statement.where(AuditLog.session_id == session_id)
        if cursor is not None:
            # Spelled out rather than as a row comparison so the leading
            # `created_at` predicate stays usable by the composite indexes.
            cursor_at, cursor_id = cursor
            statement = statement.where(
                or_(
                    AuditLog.created_at < cursor_at,
                    and_(AuditLog.created_at == cursor_at, AuditLog.id < cursor_id),
                )
            )
        result = await self._session.execute(statement)
        return [
            AuditRow(entry=entry, username=username, display_name=display_name, node_name=node_name)
            for entry, username, display_name, node_name in result.all()
        ]

    async def add(
        self,
        action: str,
        *,
        user_id: uuid.UUID | None = None,
        node_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            node_id=node_id,
            session_id=session_id,
            audit_metadata=metadata or {},
        )
        self._session.add(entry)
        return entry
