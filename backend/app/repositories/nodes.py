from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Node, NodeCredential


class NodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, node: Node) -> None:
        self._session.add(node)

    async def get(self, node_id: uuid.UUID, *, include_deleted: bool = False) -> Node | None:
        node = await self._session.get(
            Node,
            node_id,
            options=[selectinload(Node.runtimes), selectinload(Node.workspace_roots)],
        )
        if node is None:
            return None
        if node.deleted_at is not None and not include_deleted:
            return None
        return node

    async def list_active(self) -> Sequence[Node]:
        result = await self._session.execute(
            select(Node)
            .where(Node.deleted_at.is_(None))
            .options(selectinload(Node.runtimes), selectinload(Node.workspace_roots))
            .order_by(Node.registered_at.desc())
        )
        return result.scalars().all()

    async def touch_last_seen(self, node_id: uuid.UUID, when: datetime) -> None:
        await self._session.execute(
            update(Node).where(Node.id == node_id).values(last_seen_at=when)
        )


class NodeCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, credential: NodeCredential) -> None:
        self._session.add(credential)

    async def active_for_node(self, node_id: uuid.UUID) -> NodeCredential | None:
        """The current (non-revoked, highest-version) credential for a node."""
        result = await self._session.execute(
            select(NodeCredential)
            .where(
                NodeCredential.node_id == node_id,
                NodeCredential.revoked_at.is_(None),
            )
            .order_by(NodeCredential.version.desc())
        )
        return result.scalars().first()

    async def revoke_all(self, node_id: uuid.UUID, when: datetime) -> None:
        await self._session.execute(
            update(NodeCredential)
            .where(NodeCredential.node_id == node_id, NodeCredential.revoked_at.is_(None))
            .values(revoked_at=when)
        )

    async def next_version(self, node_id: uuid.UUID) -> int:
        """The version to assign to a freshly-rotated credential (max + 1)."""
        result = await self._session.execute(
            select(func.max(NodeCredential.version)).where(NodeCredential.node_id == node_id)
        )
        return (result.scalar() or 0) + 1
