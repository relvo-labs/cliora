from __future__ import annotations

import hashlib
import unicodedata
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LoginLockout, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_id_for_update(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id).with_for_update(of=User)
        )
        return result.scalar_one_or_none()

    async def bump_token_version(self, user: User) -> None:
        user.token_version += 1


def username_key(username: str) -> str:
    # Authentication still uses the exact username. Variants share the protection
    # bucket so changing case/Unicode representation cannot bypass a lock.
    normalized = unicodedata.normalize("NFKC", username).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class LoginLockoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_update(self, username: str) -> LoginLockout:
        key = username_key(username)
        # Concurrent first attempts serialize on the unique key as well. Keep
        # this lock through verify + commit to avoid lost failures/success resets.
        await self._session.execute(
            insert(LoginLockout).values(username_key=key).on_conflict_do_nothing()
        )
        return (
            await self._session.execute(
                select(LoginLockout).where(LoginLockout.username_key == key).with_for_update()
            )
        ).scalar_one()
