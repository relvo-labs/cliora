"""Async SQLAlchemy engine and session provisioning (ADR 0009).

The engine is owned by a `Database` object created in the FastAPI lifespan and
disposed on shutdown; nothing connects at import time. `get_session` is the
FastAPI dependency that yields one `AsyncSession` per request/use case.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import Settings, get_settings


class Database:
    def __init__(self, url: str, settings: Settings | None = None) -> None:
        resolved = settings or get_settings()
        self._engine: AsyncEngine = create_async_engine(
            url,
            pool_pre_ping=True,
            # Explicit bounds (P4-09, ADR 0018). SQLAlchemy's defaults would work, but
            # `database_pool_usage` and a pool-exhaustion alert need a denominator that
            # is written down, and `pool_timeout` is what turns a saturated pool into a
            # visible 503 rather than a request that hangs until the client gives up.
            pool_size=resolved.db_pool_size,
            max_overflow=resolved.db_max_overflow,
            pool_timeout=resolved.db_pool_timeout_seconds,
            pool_recycle=resolved.db_pool_recycle_seconds,
        )
        self._sessionmaker = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    def session(self) -> AsyncSession:
        return self._sessionmaker()

    def pool_usage(self) -> dict[str, int]:
        """Live pool occupancy, for the `database_pool_usage` gauge.

        Read from the pool rather than counted by us: a parallel counter would drift
        from reality the first time a connection was invalidated behind our back.
        `NullPool` (used by some test setups) exposes none of these, so each value is
        read defensively and a pool that cannot answer reports zeros rather than
        breaking the scrape.
        """
        pool = self._engine.pool

        def read(attribute: str) -> int:
            getter = getattr(pool, attribute, None)
            if getter is None:
                return 0
            try:
                return int(getter())
            except (TypeError, ValueError, AttributeError):
                return 0

        return {
            "checked_out": read("checkedout"),
            "available": read("checkedin"),
            "overflow": max(read("overflow"), 0),
            "size": read("size"),
        }

    async def dispose(self) -> None:
        await self._engine.dispose()


_database: Database | None = None


def get_database(settings: Settings | None = None) -> Database:
    """Return the process-wide Database, creating it on first use."""
    global _database
    if _database is None:
        _database = Database((settings or get_settings()).database_url)
    return _database


async def reset_database() -> None:
    """Dispose and clear the process-wide Database (used by the lifespan/tests)."""
    global _database
    if _database is not None:
        await _database.dispose()
        _database = None


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_database().session() as session:
        yield session
