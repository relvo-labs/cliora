from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EnrollmentToken


class EnrollmentTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        token_hash: str,
        created_by: uuid.UUID,
        expires_at: datetime,
        max_uses: int,
    ) -> EnrollmentToken:
        token = EnrollmentToken(
            token_hash=token_hash,
            created_by=created_by,
            expires_at=expires_at,
            max_uses=max_uses,
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_id(self, token_id: uuid.UUID) -> EnrollmentToken | None:
        return await self._session.get(EnrollmentToken, token_id)

    async def lock_by_hash(self, token_hash: str) -> EnrollmentToken | None:
        """Fetch a token FOR UPDATE so concurrent uses cannot exceed max_uses."""
        result = await self._session.execute(
            select(EnrollmentToken)
            .where(EnrollmentToken.token_hash == token_hash)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[EnrollmentToken]:
        result = await self._session.execute(
            select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc())
        )
        return result.scalars().all()
