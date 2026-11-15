"""Hermetic tests for the terminal relay hub (P2-09/P2-10)."""

from __future__ import annotations

import json
import uuid

import pytest

from app.services.terminal_queue import BrowserChannel
from app.services.terminal_relay import TerminalRelay

pytestmark = pytest.mark.asyncio


def _channel() -> BrowserChannel:
    return BrowserChannel(max_bytes=1024 * 1024, max_frames=128)


async def test_first_write_capable_subscriber_is_writer_rest_viewers() -> None:
    relay = TerminalRelay()
    sid = uuid.uuid4()
    r1 = await relay.subscribe(sid, "c1", uuid.uuid4(), _channel(), can_write=True)
    r2 = await relay.subscribe(sid, "c2", uuid.uuid4(), _channel(), can_write=True)
    assert r1 == "writer"
    assert r2 == "viewer"
    assert relay.is_writer(sid, "c1")
    assert not relay.is_writer(sid, "c2")


async def test_viewer_only_user_never_becomes_writer() -> None:
    relay = TerminalRelay()
    sid = uuid.uuid4()
    role = await relay.subscribe(sid, "c1", uuid.uuid4(), _channel(), can_write=False)
    assert role == "viewer"
    assert not relay.is_writer(sid, "c1")


async def test_route_output_fans_out_to_all_subscribers() -> None:
    relay = TerminalRelay()
    sid = uuid.uuid4()
    ch1, ch2 = _channel(), _channel()
    await relay.subscribe(sid, "c1", uuid.uuid4(), ch1, can_write=True)
    await relay.subscribe(sid, "c2", uuid.uuid4(), ch2, can_write=False)
    await relay.route_output(sid, b"hello")
    assert (await ch1.get()) == ("output", b"hello")
    assert (await ch2.get()) == ("output", b"hello")


async def test_takeover_transfers_writer() -> None:
    relay = TerminalRelay()
    sid = uuid.uuid4()
    await relay.subscribe(sid, "c1", uuid.uuid4(), _channel(), can_write=True)
    await relay.subscribe(sid, "c2", uuid.uuid4(), _channel(), can_write=True)
    assert relay.is_writer(sid, "c1")
    assert await relay.takeover(sid, "c2")
    assert relay.is_writer(sid, "c2")
    assert not relay.is_writer(sid, "c1")


async def test_takeover_unknown_connection_fails() -> None:
    relay = TerminalRelay()
    sid = uuid.uuid4()
    await relay.subscribe(sid, "c1", uuid.uuid4(), _channel(), can_write=True)
    assert not await relay.takeover(sid, "ghost")


async def test_unsubscribe_releases_writer_and_cleans_up() -> None:
    relay = TerminalRelay()
    sid = uuid.uuid4()
    await relay.subscribe(sid, "c1", uuid.uuid4(), _channel(), can_write=True)
    await relay.unsubscribe(sid, "c1")
    assert not relay.is_writer(sid, "c1")
    assert relay.subscriber_count(sid) == 0


async def test_ownership_cache_uses_authoritative_owner_once_for_output_burst() -> None:
    from unittest.mock import AsyncMock

    relay = TerminalRelay()
    node_a, node_b, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lookup = AsyncMock(return_value=(node_b, True))
    # A forged first claim cannot teach the cache that A owns B's session.
    assert not await relay.authorize_node_session(node_a, sid, lookup)
    for _ in range(10_000):
        assert await relay.authorize_node_session(node_b, sid, lookup)
    assert not await relay.authorize_node_session(node_a, sid, lookup)
    lookup.assert_awaited_once_with(sid)


async def test_unknown_session_is_not_cached_and_can_be_learned_later() -> None:
    from unittest.mock import AsyncMock

    relay = TerminalRelay()
    node_id, sid = uuid.uuid4(), uuid.uuid4()
    lookup = AsyncMock(return_value=None)
    assert not await relay.authorize_node_session(node_id, sid, lookup)
    assert not await relay.authorize_node_session(node_id, sid, lookup)
    assert not relay._owners
    lookup.return_value = (node_id, True)
    assert await relay.authorize_node_session(node_id, sid, lookup)
    assert lookup.await_count == 3


async def test_ownership_cache_is_bounded_and_expires_at_ttl() -> None:
    from unittest.mock import AsyncMock

    now = [0.0]
    relay = TerminalRelay(ownership_cache_max=2, ownership_ttl_seconds=60, clock=lambda: now[0])
    node_id = uuid.uuid4()
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lookup = AsyncMock(return_value=(node_id, True))
    for sid in (first, second, first, third):
        assert await relay.authorize_node_session(node_id, sid, lookup)
    assert lookup.await_count == 3
    assert len(relay._owners) == 2 and second not in relay._owners
    now[0] = 60.0
    lookup.return_value = None
    assert not await relay.authorize_node_session(node_id, first, lookup)
    assert lookup.await_count == 4


async def test_end_invalidation_allows_final_event_without_caching_ended_session() -> None:
    from unittest.mock import AsyncMock

    relay = TerminalRelay()
    node_id, sid = uuid.uuid4(), uuid.uuid4()
    lookup = AsyncMock(return_value=(node_id, True))
    assert await relay.authorize_node_session(node_id, sid, lookup)
    relay.forget_session(sid)
    lookup.return_value = (node_id, False)
    # Status may arrive before terminal.exited. The final event still needs to
    # reach its owner, but must not resurrect an entry after end invalidation.
    assert await relay.authorize_node_session(node_id, sid, lookup)
    assert sid not in relay._owners
    lookup.return_value = None
    assert not await relay.authorize_node_session(node_id, sid, lookup)
    assert lookup.await_count == 3


async def test_end_during_lookup_cannot_repopulate_ownership_cache() -> None:
    import asyncio

    relay = TerminalRelay()
    node_id, sid = uuid.uuid4(), uuid.uuid4()
    started, finish = asyncio.Event(), asyncio.Event()

    async def lookup(session_id):
        started.set()
        await finish.wait()
        return node_id, True

    task = asyncio.create_task(relay.authorize_node_session(node_id, sid, lookup))
    await started.wait()
    relay.forget_session(sid)
    finish.set()
    assert await task
    assert sid not in relay._owners


async def test_denials_are_counted_with_bounded_redacted_structured_logs(
    caplog, monkeypatch
) -> None:
    import logging
    from unittest.mock import AsyncMock

    from app import metrics
    from app.logging import JsonFormatter

    # Alembic's in-process migration tests disable existing named loggers via
    # fileConfig. Isolate that global state while testing real LogRecords here.
    monkeypatch.setattr(logging.getLogger("cliora.terminal_relay"), "disabled", False)
    now = [0.0]
    relay = TerminalRelay(clock=lambda: now[0])
    node_id = uuid.uuid4()
    lookup = AsyncMock(return_value=None)
    labels = {"action": "node.session", "role": "daemon", "reason": "scope"}
    before = metrics.counter_value(metrics.AUTHZ_DENIED_TOTAL, **labels)
    with caplog.at_level(logging.WARNING, logger="cliora.terminal_relay"):
        for _ in range(100):
            assert not await relay.authorize_node_session(node_id, uuid.uuid4(), lookup)
        assert len(caplog.records) == 1
        now[0] = 30
        assert not await relay.authorize_node_session(node_id, uuid.uuid4(), lookup)
    assert len(caplog.records) == 2
    assert metrics.counter_value(metrics.AUTHZ_DENIED_TOTAL, **labels) - before == 101
    record = json.loads(JsonFormatter().format(caplog.records[0]))
    assert record["event"] == "node_session_denied"
    assert record["node_id"] == str(node_id) and uuid.UUID(record["session_id"])
    assert record["denied_action"] == "node.session" and record["reason"] == "scope"
    assert set(record) == {
        "timestamp",
        "level",
        "service",
        "logger",
        "message",
        "event",
        "node_id",
        "session_id",
        "denied_action",
        "reason",
    }
    assert not relay._owners
