from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_id_for_update(self, user_id: uuid.UUID) -> User | None:
        # `of=User` is load-bearing: `User.role` is a joined eager load, so the
        # statement carries a LEFT OUTER JOIN onto `roles`, and Postgres refuses
        # a bare FOR UPDATE on the nullable side of an outer join. Only the user
        # row needs locking here anyway.
        result = await self._session.execute(
            select(User).where(User.id == user_id).with_for_update(of=User)
        )
        return result.scalar_one_or_none()

    async def bump_token_version(self, user: User) -> None:
        user.token_version += 1
