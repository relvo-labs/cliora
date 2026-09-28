"""Migration 0022 goes down and comes back up, and leaves no drift (plan/31/04 §8).

`downgrade()` must remove everything `upgrade()` added — both columns and the index —
or a Central rolled back past 0022 keeps a half-applied schema that the next upgrade
then trips over. This is the first migration round-trip test in `backend/tests`; it
runs Alembic for real against the test database and restores head when it is done.

Alembic's env.py calls `asyncio.run`, so each command runs in a worker thread.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import models  # noqa: F401  (registers every table)
from app.db.base import Base
from app.settings import get_settings

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).parents[2]
PREVIOUS = "0021_node_file_download"
THIS = "0022_node_binary_preview"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
    return cfg


def _state(conn: Connection) -> dict[str, object]:
    inspector = sa.inspect(conn)
    columns = {c["name"] for c in inspector.get_columns("nodes")}
    indexes = {i["name"] for i in inspector.get_indexes("nodes")}
    version = conn.execute(sa.text("select version_num from alembic_version")).scalar_one()
    return {
        "binary_preview": "binary_preview" in columns,
        "last_registration_at": "last_registration_at" in columns,
        "ix_nodes_binary_preview": "ix_nodes_binary_preview" in indexes,
        "version": version,
    }


def _table_of(diff: object) -> str | None:
    """The table a compare_metadata entry is about, whatever its shape."""
    if isinstance(diff, list):  # modify_* entries come wrapped in a list
        return _table_of(diff[0]) if diff else None
    if not isinstance(diff, tuple) or len(diff) < 2:
        return None
    op = diff[0]
    if op in {"add_column", "remove_column"}:
        return str(diff[2])
    if op.startswith("modify_"):
        return str(diff[2])
    target = diff[1]
    table = getattr(target, "table", None)
    return getattr(table, "name", None) if table is not None else getattr(target, "name", None)


def _drift(conn: Connection) -> list[object]:
    """Drift on the `nodes` table only.

    The base schema already differs from the models elsewhere: 12 indexes and one
    unique constraint that earlier migrations create are not declared on the models
    (14 entries at 157efe3; recorded in plan/31/09 §4 as a pre-existing defect).
    This migration only touches `nodes`, so that is the table whose drift it owns.
    """
    context = MigrationContext.configure(conn, opts={"compare_type": True})
    return [d for d in compare_metadata(context, Base.metadata) if _table_of(d) == "nodes"]


async def test_migration_0022_roundtrip(db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIORA_DATABASE_URL", db_url)
    get_settings.cache_clear()
    cfg = _alembic_config()
    engine = create_async_engine(db_url)

    async def state() -> dict[str, object]:
        async with engine.connect() as conn:
            return await conn.run_sync(_state)

    try:
        await asyncio.to_thread(command.upgrade, cfg, "head")
        at_head = await state()
        assert at_head == {
            "binary_preview": True,
            "last_registration_at": True,
            "ix_nodes_binary_preview": True,
            "version": THIS,
        }

        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        assert await state() == {
            "binary_preview": False,
            "last_registration_at": False,
            "ix_nodes_binary_preview": False,
            "version": PREVIOUS,
        }

        await asyncio.to_thread(command.upgrade, cfg, "head")
        assert await state() == at_head

        async with engine.connect() as conn:
            drift = await conn.run_sync(_drift)
        assert drift == [], f"the migrated nodes table differs from the model: {drift}"
    finally:
        # Whatever happened, leave the shared test database at head.
        await asyncio.to_thread(command.upgrade, cfg, "head")
        await engine.dispose()
        get_settings.cache_clear()
