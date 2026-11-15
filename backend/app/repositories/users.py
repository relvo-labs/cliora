from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
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
    # Match UserRepository's exact username equality, including for unknown keys.
    # Case/Unicode variants can be distinct users and must not share resets/locks.
    return hashlib.sha256(username.encode("utf-8")).hexdigest()


class LoginLockoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_update(self, username: str, *, now: datetime | None = None) -> LoginLockout:
        now = now or datetime.now(UTC)
        # Atomic upsert both takes the row lock and refreshes activity. A separate
        # INSERT DO NOTHING + SELECT could race retention deleting the idle row
        # between those statements. Keep the lock through verify + commit.
        statement = (
            insert(LoginLockout)
            .values(username_key=username_key(username), last_activity_at=now)
            .on_conflict_do_update(
                index_elements=[LoginLockout.username_key], set_={"last_activity_at": now}
            )
            .returning(LoginLockout)
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(statement)).scalar_one()

    async def cleanup_idle(self, *, now: datetime, idle_seconds: int, batch_size: int) -> int:
        # Indexed oldest-first scan, bounded row count, no waiting on live logins.
        # The candidate row locks survive through DELETE, closing the race with
        # an attempt refreshing activity or starting a new lock concurrently.
        candidates = (
            select(LoginLockout.username_key)
            .where(
                LoginLockout.last_activity_at < now - timedelta(seconds=idle_seconds),
                or_(LoginLockout.locked_until.is_(None), LoginLockout.locked_until <= now),
            )
            .order_by(LoginLockout.last_activity_at, LoginLockout.username_key)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
            .cte("idle_login_lockouts")
        )
        result = await self._session.execute(
            delete(LoginLockout)
            .where(LoginLockout.username_key.in_(select(candidates.c.username_key)))
            .returning(LoginLockout.username_key)
        )
        return len(result.scalars().all())
