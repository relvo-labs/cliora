"""Issue #59 schema/seed rollback preserves credentials and unrelated grants."""

import asyncio
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from app.bootstrap import create_admin
from app.db.models import LoginLockout, Role, User
from app.repositories.users import username_key
from tests.db.test_migration_0022_roundtrip import _alembic_config


async def test_migration_0023_up_down_up_preserves_users_and_contracts_grants(api, db_url):
    _, maker = api
    cfg = _alembic_config()
    engine = create_async_engine(db_url)
    async with maker() as session:
        user, _ = await create_admin(session, "preserved", "password")
        uid, digest = user.id, user.password_hash
        viewer = (await session.execute(sa.select(Role).where(Role.name == "Viewer"))).scalar_one()
        # Downgrade contracts a manually widened grant, without losing other actions.
        viewer.permissions = {
            "actions": [*viewer.permissions["actions"], "user.unlock", "custom.action"]
        }
        session.add(
            LoginLockout(
                username_key=username_key("unknown"),
                failures=20,
                locked_until=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await session.commit()
    try:
        await asyncio.to_thread(command.downgrade, cfg, "0022_node_binary_preview")
        async with engine.connect() as conn:
            assert await conn.scalar(sa.text("SELECT to_regclass('login_lockouts')")) is None
            roles = dict((await conn.execute(sa.text("SELECT name, permissions FROM roles"))).all())
            assert all("user.unlock" not in p["actions"] for p in roles.values())
            assert "custom.action" in roles["Viewer"]["actions"]
        await asyncio.to_thread(command.upgrade, cfg, "head")
        await asyncio.to_thread(command.upgrade, cfg, "head")  # repeated Alembic upgrade is a no-op
        async with maker() as session:
            user = await session.get(User, uid)
            assert user.password_hash == digest
            assert (await session.execute(sa.select(LoginLockout))).scalars().all() == []
            roles = dict((await session.execute(sa.select(Role.name, Role.permissions))).all())
            assert {n for n, p in roles.items() if "user.unlock" in p["actions"]} == {"Admin"}
            assert "custom.action" in roles["Viewer"]["actions"]
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")
        async with maker() as session:
            viewer = (
                await session.execute(sa.select(Role).where(Role.name == "Viewer"))
            ).scalar_one()
            viewer.permissions = {
                "actions": [
                    a
                    for a in viewer.permissions["actions"]
                    if a not in {"custom.action", "user.unlock"}
                ]
            }
            await session.commit()
        await engine.dispose()
