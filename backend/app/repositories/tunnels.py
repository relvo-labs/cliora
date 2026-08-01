"""Persistence for `node_tunnels` (P11, FR-TUNNEL-001, ADR 0022).

Every query here is about *live* tunnels, and "live" is one predicate — `closed_at IS
NULL AND expires_at > now` — used by the three independent limits (fleet budget, node cap,
user cap) and by the duplicate-port guard. It is written once, in `_live()`, because three
copies of it would eventually disagree, and the way they disagree is that one of them counts
an expired tunnel and refuses a legitimate request nobody can explain.

There is no `status` column to filter on (see `NodeTunnel`), so nothing here derives state:
the service does that from `closed_at`, `expires_at`, `state_error_code` and whether the
node is currently connected.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Node, NodeTunnel, User


@dataclass(frozen=True)
class TunnelRow:
    """One tunnel with the display names its ids resolve to.

    Joined rather than stored, for the same reason as `AuditRow`: a renamed node or user
    still reads correctly, and a row whose subject was deleted keeps its ids with `None`
    names instead of vanishing from the list.
    """

    tunnel: NodeTunnel
    node_name: str | None
    created_by_username: str | None


def _live(now: datetime) -> ColumnElement[bool]:
    return (NodeTunnel.closed_at.is_(None)) & (NodeTunnel.expires_at > now)


class TunnelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, tunnel: NodeTunnel) -> None:
        self._session.add(tunnel)

    async def remove(self, tunnel: NodeTunnel) -> None:
        """Delete a row that never became a tunnel.

        Used only on the creation path when the node refuses or does not answer: a row for
        a tunnel that does not exist would be listed, counted against every limit, and
        never closed by anyone.
        """
        await self._session.delete(tunnel)
        await self._session.flush()

    async def get(self, tunnel_id: uuid.UUID) -> NodeTunnel | None:
        return await self._session.get(NodeTunnel, tunnel_id)

    async def list(
        self,
        *,
        now: datetime,
        node_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        include_ended: bool = False,
        limit: int = 100,
    ) -> list[TunnelRow]:
        statement = (
            select(NodeTunnel, Node.name, User.username)
            .outerjoin(Node, Node.id == NodeTunnel.node_id)
            .outerjoin(User, User.id == NodeTunnel.created_by)
            .order_by(NodeTunnel.created_at.desc())
            .limit(limit)
        )
        if not include_ended:
            statement = statement.where(_live(now))
        if node_id is not None:
            statement = statement.where(NodeTunnel.node_id == node_id)
        if created_by is not None:
            statement = statement.where(NodeTunnel.created_by == created_by)
        result = await self._session.execute(statement)
        return [
            TunnelRow(tunnel=tunnel, node_name=node_name, created_by_username=username)
            for tunnel, node_name, username in result.all()
        ]

    async def row(self, tunnel_id: uuid.UUID) -> TunnelRow | None:
        """One tunnel with its joined names, for the single-tunnel responses.

        Separate from `get` because the names are only needed where a response is built: the
        limit checks and the status path work on the row alone, and joining for them would be
        two extra tables per check.
        """
        result = await self._session.execute(
            select(NodeTunnel, Node.name, User.username)
            .outerjoin(Node, Node.id == NodeTunnel.node_id)
            .outerjoin(User, User.id == NodeTunnel.created_by)
            .where(NodeTunnel.id == tunnel_id)
        )
        found = result.first()
        if found is None:
            return None
        tunnel, node_name, username = found
        return TunnelRow(tunnel=tunnel, node_name=node_name, created_by_username=username)

    async def live_for_node(self, node_id: uuid.UUID, *, now: datetime) -> Sequence[NodeTunnel]:
        """Every live tunnel on one node, oldest first.

        Oldest first so a partial failure while tearing a node down leaves the newest — the
        one most likely still in use — for last, matching `list_active_for_node` for
        sessions.
        """
        result = await self._session.execute(
            select(NodeTunnel)
            .where(NodeTunnel.node_id == node_id, _live(now))
            .order_by(NodeTunnel.created_at.asc())
        )
        return result.scalars().all()

    async def live_on_port(
        self, node_id: uuid.UUID, port: int, *, now: datetime
    ) -> NodeTunnel | None:
        """The live tunnel already forwarding this port, if any.

        Mirrors `uq_node_tunnels_live_port`. The index is the real guarantee; this is what
        turns a would-be IntegrityError into a 409 that can name the existing tunnel.
        """
        result = await self._session.execute(
            select(NodeTunnel).where(
                NodeTunnel.node_id == node_id, NodeTunnel.port == port, _live(now)
            )
        )
        return result.scalars().first()

    async def count_live(self, *, now: datetime) -> int:
        """Fleet-wide live count — the provider-plan budget (ADR 0022 D17b).

        Deliberately separate from the per-node count: folding the two into one minimum
        would make a budget of 8 unreachable while every node allowed 3, so the fleet could
        hold 3xN tunnels against a plan that permits 8.
        """
        result = await self._session.execute(
            select(func.count()).select_from(NodeTunnel).where(_live(now))
        )
        return int(result.scalar_one())

    async def count_live_for_node(self, node_id: uuid.UUID, *, now: datetime) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(NodeTunnel)
            .where(NodeTunnel.node_id == node_id, _live(now))
        )
        return int(result.scalar_one())

    async def count_live_for_user(self, user_id: uuid.UUID, *, now: datetime) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(NodeTunnel)
            .where(NodeTunnel.created_by == user_id, _live(now))
        )
        return int(result.scalar_one())
