"""The knowledge reconciler's leader lock follows the transaction, not the pool.

This is deliberately a real PostgreSQL test.  A mocked session cannot reproduce the
failure that motivated it: committing a session-level advisory lock returned its
connection to the pool, after which the explicit unlock could run on another connection
and silently leak the lock.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.knowledge.worker import KnowledgeWorker

pytestmark = pytest.mark.asyncio


async def test_reconcile_lock_is_exclusive_and_released_with_its_transaction(
    api: tuple, db_url: str
) -> None:
    """A concurrent pass skips, then the same worker can acquire after commit."""
    del api, db_url  # fixtures bind and clean the process-wide application database

    first = KnowledgeWorker()
    second = KnowledgeWorker()
    first_holds_lock = asyncio.Event()
    release_first = asyncio.Event()
    second_syncs = 0

    async def block_first(_session) -> int:
        first_holds_lock.set()
        await release_first.wait()
        return 0

    async def count_second(_session) -> int:
        nonlocal second_syncs
        second_syncs += 1
        return 0

    first._sync_providers = block_first  # type: ignore[method-assign]
    second._sync_providers = count_second  # type: ignore[method-assign]

    first_pass = asyncio.create_task(first.reconcile())
    await asyncio.wait_for(first_holds_lock.wait(), timeout=5)

    # This needs a different pooled connection while the first transaction owns the
    # lock.  It must skip without entering provider reconciliation.
    assert await asyncio.wait_for(second.reconcile(), timeout=5) == 0
    assert second_syncs == 0

    release_first.set()
    assert await asyncio.wait_for(first_pass, timeout=5) == 0

    # Commit ended the first transaction and therefore released the xact lock.  The
    # next pass must acquire it; this is the assertion the old session lock failed.
    assert await asyncio.wait_for(second.reconcile(), timeout=5) == 0
    assert second_syncs == 1
