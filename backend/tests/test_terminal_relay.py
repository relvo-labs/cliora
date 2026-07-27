"""Hermetic tests for the terminal relay hub (P2-09/P2-10)."""

from __future__ import annotations

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
