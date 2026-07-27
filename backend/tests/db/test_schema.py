"""The migrated schema matches the ORM models, and instants round-trip as UTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.base import Base
from app.db.models import EnrollmentToken, Role, User


def _reflect(sync_conn: Connection) -> dict[str, set[str]]:
    inspector = sa.inspect(sync_conn)
    return {
        table: {col["name"] for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


async def test_migrated_schema_matches_models(db_url: str) -> None:
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        reflected = await conn.run_sync(_reflect)
    await engine.dispose()

    expected = {
        table.name: {col.name for col in table.columns} for table in Base.metadata.sorted_tables
    }
    assert reflected == expected


async def _seed_user(session: AsyncSession) -> User:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    user = User(
        username="tz-test",
        password_hash="x",
        display_name="TZ Test",
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    return user


async def test_server_default_timestamp_is_aware_utc(session: AsyncSession) -> None:
    user = await _seed_user(session)
    assert user.created_at.tzinfo is not None
    assert user.created_at.utcoffset() == timedelta(0)


async def test_aware_non_utc_instant_round_trips_as_same_instant(
    session: AsyncSession,
) -> None:
    user = await _seed_user(session)
    taipei = datetime(2026, 7, 24, 17, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    token = EnrollmentToken(
        token_hash="tz-roundtrip",
        created_by=user.id,
        expires_at=taipei,
        max_uses=1,
    )
    session.add(token)
    await session.flush()
    await session.refresh(token)
    # Same instant, returned as aware UTC (09:00Z == 17:00+08:00).
    assert token.expires_at == taipei
    assert token.expires_at.utcoffset() == timedelta(0)
    assert token.expires_at == datetime(2026, 7, 24, 9, 0, 0, tzinfo=UTC)


async def test_transaction_rollback_leaves_no_partial_rows(session: AsyncSession) -> None:
    user = await _seed_user(session)
    before = (
        await session.execute(sa.select(sa.func.count()).select_from(EnrollmentToken))
    ).scalar_one()
    savepoint = await session.begin_nested()
    token = EnrollmentToken(token_hash="rollback", created_by=user.id, expires_at=datetime.now(UTC))
    session.add(token)
    await session.flush()
    await savepoint.rollback()
    after = (
        await session.execute(sa.select(sa.func.count()).select_from(EnrollmentToken))
    ).scalar_one()
    assert after == before
