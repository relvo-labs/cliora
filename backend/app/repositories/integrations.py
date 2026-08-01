"""Persistence for the port-forwarding integration settings (P11, ADR 0022).

Two tables, one row each in practice: the platform-level integration and one row per node
that has ever had its port-forwarding settings touched.

`get_integration` deliberately does **not** create a row. A read with a side effect would
mean the first person to open the settings page leaves a record that looks like an
administrator went through it, and `acknowledged_at` — which is a person's decision — would
be indistinguishable from a default.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_utc
from app.db.models import NodeTunnelSettings, TunnelIntegration


class IntegrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_integration(self) -> TunnelIntegration | None:
        result = await self._session.execute(select(TunnelIntegration).limit(1))
        return result.scalar_one_or_none()

    async def get_or_create_integration(self, *, actor_id: uuid.UUID) -> TunnelIntegration:
        """Return the settings row, creating it on first *write*.

        Called only from mutating paths. The unique `singleton` column means a concurrent
        create loses at the database rather than producing a second row nobody would notice.
        """
        existing = await self.get_integration()
        if existing is not None:
            return existing
        row = TunnelIntegration(singleton=True, updated_at=now_utc(), updated_by=actor_id)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_node_settings(self, node_id: uuid.UUID) -> NodeTunnelSettings | None:
        result = await self._session.execute(
            select(NodeTunnelSettings).where(NodeTunnelSettings.node_id == node_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create_node_settings(
        self, node_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> NodeTunnelSettings:
        existing = await self.get_node_settings(node_id)
        if existing is not None:
            return existing
        # `enabled` defaults to true in the model: the platform switch is the gate, and a
        # per-node row exists to turn one machine off (ADR 0022 D3).
        row = NodeTunnelSettings(node_id=node_id, updated_at=now_utc(), updated_by=actor_id)
        self._session.add(row)
        await self._session.flush()
        return row
