"""Graceful shutdown drain (P4-12, NFR-002).

The property worth testing is a negative one: **shutting Central down must not end a
CLI session.** NFR-002 says a browser disconnect may not terminate a session; a Central
restart is the same promise from the other side, and it is the promise a well-meaning
cleanup hook breaks most easily. So these tests assert what the drain does *not* do as
carefully as what it does.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app import main
from app.services.registry import NodeConnectionRegistry
from app.services.terminal_queue import BrowserChannel
from app.services.terminal_relay import TerminalRelay
from app.settings import Settings

pytestmark = pytest.mark.asyncio


class FakeSocket:
    def __init__(self, *, hang: bool = False) -> None:
        self.closed_with: int | None = None
        self.sent: list[str] = []
        self._hang = hang

    async def close(self, code: int = 1000) -> None:
        if self._hang:
            await asyncio.Event().wait()  # never returns
        self.closed_with = code

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


async def _drain_with(monkeypatch: pytest.MonkeyPatch, **settings: object) -> None:
    base = Settings(**settings)  # type: ignore[arg-type]
    monkeypatch.setattr(main, "get_settings", lambda: base)
    await main._drain()


async def test_every_subscribed_browser_is_told_why(monkeypatch: pytest.MonkeyPatch) -> None:
    relay = TerminalRelay()
    registry = NodeConnectionRegistry()
    monkeypatch.setattr(main, "get_terminal_relay", lambda: relay)
    monkeypatch.setattr(main, "get_node_registry", lambda: registry)

    session_id = uuid.uuid4()
    channel = BrowserChannel(1 << 20, 128)
    await relay.subscribe(session_id, "c1", uuid.uuid4(), channel, can_write=True)

    await _drain_with(monkeypatch)

    item = await asyncio.wait_for(channel.get(), timeout=1)
    assert item is not None, "the browser was disconnected with no explanation"
    kind, payload = item
    assert kind == "control"
    assert isinstance(payload, str)
    body = json.loads(payload)
    assert body["type"] == "terminal.server_shutdown"
    # The browser has to be able to promise the user their session is still there.
    # Without this flag the message is just a different-looking disconnect.
    assert body["payload"]["session_preserved"] is True
    assert body["payload"]["reason"] == "server_restarting"


async def test_the_drain_sends_no_stop_to_any_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core NFR-002 guarantee. If the drain ever grew a 'tidy up the sessions'
    step, this is the test that fails."""
    relay = TerminalRelay()
    registry = NodeConnectionRegistry()
    monkeypatch.setattr(main, "get_terminal_relay", lambda: relay)
    monkeypatch.setattr(main, "get_node_registry", lambda: registry)

    socket = FakeSocket()
    node_id = uuid.uuid4()
    await registry.register(node_id, socket)  # type: ignore[arg-type]
    session_id = uuid.uuid4()
    await relay.subscribe(
        session_id, "c1", uuid.uuid4(), BrowserChannel(1 << 20, 128), can_write=True
    )

    await _drain_with(monkeypatch)

    # Nothing was *sent* to the node at all — no session.stop, no terminal.detach.
    assert socket.sent == []
    # It was closed with 1012 (service restart), which is what makes the daemon's
    # existing backoff reconnect rather than treat it as a protocol error.
    assert socket.closed_with == 1012
    assert registry.connection_count == 0


async def test_a_socket_that_will_not_close_cannot_hold_the_deploy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck socket must cost the drain its budget and no more. Waiting longer would
    protect nothing — the sessions survive either way — while turning a deploy into an
    outage."""
    relay = TerminalRelay()
    registry = NodeConnectionRegistry()
    monkeypatch.setattr(main, "get_terminal_relay", lambda: relay)
    monkeypatch.setattr(main, "get_node_registry", lambda: registry)
    await registry.register(uuid.uuid4(), FakeSocket(hang=True))  # type: ignore[arg-type]

    loop = asyncio.get_running_loop()
    started = loop.time()
    await _drain_with(monkeypatch, shutdown_drain_seconds=0.2)
    elapsed = loop.time() - started

    # Returned, rather than hanging forever on the stuck close.
    assert elapsed < 5, f"drain took {elapsed:.2f}s despite a 0.2s bound"


async def test_the_drain_is_harmless_with_nothing_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common case: a restart with no browsers and no nodes attached. It must not
    raise, because an exception in the lifespan's finally block would mask whatever the
    real shutdown reason was."""
    monkeypatch.setattr(main, "get_terminal_relay", lambda: TerminalRelay())
    monkeypatch.setattr(main, "get_node_registry", lambda: NodeConnectionRegistry())
    await _drain_with(monkeypatch)


async def test_pending_requests_are_failed_rather_than_abandoned() -> None:
    """A request in flight when SIGTERM arrives gets an answer now, not a timeout after
    the process is gone."""
    registry = NodeConnectionRegistry()
    node_id = uuid.uuid4()
    socket = FakeSocket()
    connection, _ = await registry.register(node_id, socket)  # type: ignore[arg-type]
    future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
    connection.pending["01K0ABCDEFGHJKMNPQRSTVWXYZ"] = future

    closed = await registry.close_all(code=1012)

    assert closed == 1
    assert future.done()
    with pytest.raises(Exception) as raised:  # ApiError
        future.result()
    assert getattr(raised.value, "code", None) == "NODE_OFFLINE"
