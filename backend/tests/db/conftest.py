"""Fixtures for database-backed tests.

These tests are skipped unless CLIORA_TEST_DATABASE_URL points at a PostgreSQL
with `alembic upgrade head` already applied (the CI service container, or the
local docker container documented in the P1 plan). This keeps the default
hermetic `make unit` run database-free while still exercising the real schema.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

TEST_DB_URL = os.environ.get("CLIORA_TEST_DATABASE_URL")

# Tables cleared between HTTP tests (roles are seeded by migration and kept).
# Order respects FK dependencies: children before parents.
_CLEANUP_TABLES = (
    "audit_logs",
    "workspace_favorites",
    # Port forwarding (P11). All three hold FKs to `users`, so a leftover row here makes the
    # `users` delete below fail with a foreign-key violation — which then surfaces as an
    # unrelated test failing on a duplicate username, several tests later.
    "node_tunnels",
    "node_tunnel_settings",
    "tunnel_integration",
    "session_connections",
    "terminal_sessions",
    "node_metric_samples",
    "node_credentials",
    "node_workspace_roots",
    "node_runtimes",
    "enrollment_tokens",
    "nodes",
    "users",
)


@pytest.fixture
def db_url() -> str:
    if not TEST_DB_URL:
        pytest.skip("CLIORA_TEST_DATABASE_URL not set")
    return TEST_DB_URL


@pytest_asyncio.fixture
async def session(db_url: str) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is rolled back after each test."""
    engine = create_async_engine(db_url)
    conn = await engine.connect()
    trans = await conn.begin()
    db_session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield db_session
    finally:
        await db_session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def api(db_url: str):
    """An async HTTP client whose routes use a session bound to the test DB.

    Routes commit normally (persisting to the container); the fixture clears the
    control-plane tables afterwards so tests remain independent.
    """
    from app.db.engine import get_session, reset_database
    from app.main import app

    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    # Some code legitimately opens its own session outside the request's unit of
    # work — `AuthzDenialAuditMiddleware` writes its audit row on a fresh one so it
    # survives a rolled-back request. That path goes through the process-wide
    # engine, which is created lazily and bound to whichever event loop was
    # current. Each test gets a new loop, so the cached engine would belong to a
    # closed one and every such write would fail. Disposing it around each test
    # forces a rebind instead of leaving a cross-loop engine behind.
    await reset_database()
    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, maker
    finally:
        app.dependency_overrides.pop(get_session, None)
        async with maker() as session:
            for table in _CLEANUP_TABLES:
                await session.execute(text(f"DELETE FROM {table}"))
            await session.commit()
        await engine.dispose()
        # Dispose the process-wide engine too, so the next test's loop starts clean.
        await reset_database()
