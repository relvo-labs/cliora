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
# 32 zero bytes, base64. Obviously not a secret, which is the point: a plausible-looking
# key in a fixture is one somebody copies into a deployment.
TEST_MASTER_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

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
    # The project layer (PJ-02). Order matters for the same reason the tunnel tables
    # above it do: `activity_events` and `project_workspaces` hold FKs to `projects`,
    # and `projects` holds an `ON DELETE RESTRICT` FK to `users` — so a leftover
    # project makes the `users` delete below fail, and that surfaces several tests
    # later as an unrelated duplicate-username error. `terminal_sessions` is already
    # cleared above, which releases its `SET NULL` reference first.
    "activity_events",
    "project_workspaces",
    # The task layer (TK-02). Same ordering rule, one level deeper: `tasks` holds FKs
    # to `epics`, `user_stories`, `requirements` and `task_proposals`, and
    # `session_tokens` holds one to `projects` with an `ON DELETE RESTRICT` FK to
    # `users` of its own. `terminal_sessions` is cleared above, which releases both
    # its `SET NULL` reference to `tasks` and the cascade parent of `session_tokens`.
    "session_tokens",
    "task_dependencies",
    "tasks",
    "task_proposals",
    "feature_specs",
    "requirements",
    "user_stories",
    "epics",
    # V2.3. Cleared before `projects` for the usual reason, and — the part this list
    # got wrong until V2.4 — **after** the repository rows, which hold `ON DELETE
    # RESTRICT` FKs into it. The comment here already said so; the table was missing.
    # It went unnoticed because no test had ever linked a repository to a secret, so
    # the constraint was never exercised; the first one that did (the pull-request
    # worker, which needs `provider_token_secret_id` set) failed on cleanup rather than
    # on its own assertion.
    "task_runs",
    "project_repositories",
    "project_secrets",
    "projects",
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


@pytest.fixture
def projects_enabled():
    """Turn the project layer on for a test, and off again afterwards.

    `CLIORA_PROJECTS_ENABLED` defaults to false, and `require_projects_enabled`
    answers **404 before** the action guard runs — deliberately, because a 403 would
    tell a caller that a feature the deployment never enabled exists (ADR 0027).

    That ordering means authorization for these routes is only observable with the
    flag on: without this fixture the RBAC matrix would record "Viewer is refused"
    while actually measuring "the route does not exist", which is the shape of a test
    that passes for the wrong reason. Flag-*off* behaviour has its own tests.
    """
    from app.main import app
    from app.settings import Settings, get_settings

    # **Both** flags, because V2.2's routes carry both guards and the inner one 404s
    # for the same reason the outer one does. Measuring authorization on those routes
    # with the inner flag off would again record "refused" while meaning "absent"
    # (ADR 0029; `agent_runs_disabled` covers the other direction).
    # `secret_master_key` is required as soon as `agent_runs_enabled` is true — the
    # settings validator refuses to construct without one (ADR 0032 §3). A fixed test
    # key rather than a random one, so a ciphertext written by one test is readable by
    # the next and a failure is reproducible.
    #
    # **And it has to go into the environment as well as into the override**, which is
    # not belt and braces. A dependency override reaches code that *asks FastAPI* for
    # settings; `secret_envelope` calls `get_settings()` directly, the way `secret_box`
    # has since ADR 0022, so the override never reaches it. Without the environment
    # variable the routes answer 503 SECRET_KEY_MISSING while the override sits there
    # looking correct. `test_tunnels_api` solved the same problem the same way.
    previous = os.environ.get("CLIORA_SECRET_MASTER_KEY")
    os.environ["CLIORA_SECRET_MASTER_KEY"] = TEST_MASTER_KEY
    get_settings.cache_clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        projects_enabled=True, agent_runs_enabled=True, secret_master_key=TEST_MASTER_KEY
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)
        if previous is None:
            os.environ.pop("CLIORA_SECRET_MASTER_KEY", None)
        else:
            os.environ["CLIORA_SECRET_MASTER_KEY"] = previous
        get_settings.cache_clear()


@pytest.fixture
def agent_runs_disabled():
    """The project layer on, the agent runner off — the combination that has to 404.

    The two flags are not one flag: a deployment can run the task board without ever
    letting anything execute unattended, and that deployment must not be able to tell
    from a response that the runner layer exists at all.
    """
    from app.main import app
    from app.settings import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        projects_enabled=True, agent_runs_enabled=False
    )
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def projects_disabled():
    """Pin the flag off so the same suite is hermetic in both CI matrix legs."""
    from app.main import app
    from app.settings import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(projects_enabled=False)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)


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
