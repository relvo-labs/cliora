"""The hottest polling endpoint shares only concurrent, identical work."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from app.services.work import items
from app.services.work.filters import compile_filter
from app.services.work.scope import ProjectScope


@pytest.mark.asyncio
async def test_identical_project_count_polls_share_one_in_flight_read(monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    expected = items.Counts({}, {}, 0, True)

    async def read_once(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202 - test seam
        started.set()
        await release.wait()
        return expected

    read = AsyncMock(side_effect=read_once)
    monkeypatch.setattr(items, "_work_counts_once", read)
    project_id = uuid.uuid4()
    scope = ProjectScope(all_projects=False, project_ids=frozenset({project_id}))
    compiled = compile_filter(None)

    first = asyncio.create_task(
        items.work_counts(
            None,  # type: ignore[arg-type]  # mocked read never touches a session
            scope=scope,
            compiled=compiled,
            project_id=project_id,
        )
    )
    await started.wait()
    second = asyncio.create_task(
        items.work_counts(
            None,  # type: ignore[arg-type]
            scope=scope,
            compiled=compiled,
            project_id=project_id,
        )
    )
    await asyncio.sleep(0)
    assert read.await_count == 1

    release.set()
    assert await asyncio.gather(first, second) == [expected, expected]

    # A completed result is never cached: the next poll observes current database state.
    assert (
        await items.work_counts(
            None,  # type: ignore[arg-type]
            scope=scope,
            compiled=compiled,
            project_id=project_id,
        )
        == expected
    )
    assert read.await_count == 2
