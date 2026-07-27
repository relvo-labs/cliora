"""Request-correlation behaviour of the connection registry (P1-13, hermetic).

Exercises the Future correlation table without a database or real socket:
success, timeout cleanup, duplicate/unknown/late responses, the per-node
pending bound, and in-flight cancellation on disconnect/eviction.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.api.errors import ApiError
from app.protocol import ControlMessage
from app.services.registry import NodeConnectionRegistry


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed: int | None = None

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed = code


def _response(node_id: uuid.UUID, request_id: str) -> ControlMessage:
    return ControlMessage(
        version=1,
        type="runtime.result",
        request_id=request_id,
        node_id=node_id,
        timestamp="2026-07-24T01:00:00Z",
        payload={"ok": True},
        success=True,
    )


async def _registry(pending_max: int = 128) -> tuple[NodeConnectionRegistry, uuid.UUID, object]:
    registry = NodeConnectionRegistry(pending_max=pending_max)
    node_id = uuid.uuid4()
    connection, _ = await registry.register(node_id, FakeWebSocket())
    return registry, node_id, connection


async def test_request_resolves_with_response() -> None:
    registry, node_id, _ = await _registry()
    task = asyncio.create_task(
        registry.request(node_id, "runtime.list", {}, timeout_seconds=1, request_id="r1")
    )
    await asyncio.sleep(0)  # let the request park its future
    assert registry.is_pending(node_id, "r1")
    assert registry.resolve_response(node_id, _response(node_id, "r1")) is True
    result = await task
    assert result.payload["ok"] is True
    assert not registry.is_pending(node_id, "r1")  # cleaned up


async def test_request_times_out_and_cleans_up() -> None:
    registry, node_id, _ = await _registry()
    with pytest.raises(ApiError) as exc:
        await registry.request(node_id, "runtime.list", {}, timeout_seconds=0.01, request_id="r1")
    assert exc.value.code == "REQUEST_TIMEOUT"
    # No stranded entry, and a late response for it is safely dropped.
    assert not registry.is_pending(node_id, "r1")
    assert registry.resolve_response(node_id, _response(node_id, "r1")) is False


async def test_duplicate_and_unknown_responses_are_dropped() -> None:
    registry, node_id, _ = await _registry()
    task = asyncio.create_task(
        registry.request(node_id, "runtime.list", {}, timeout_seconds=1, request_id="r1")
    )
    await asyncio.sleep(0)
    assert registry.resolve_response(node_id, _response(node_id, "r1")) is True
    # Second delivery for the same id, and an unknown id, both return False.
    assert registry.resolve_response(node_id, _response(node_id, "r1")) is False
    assert registry.resolve_response(node_id, _response(node_id, "does-not-exist")) is False
    await task


async def test_pending_bound_rejects_overflow() -> None:
    registry, node_id, _ = await _registry(pending_max=1)
    first = asyncio.create_task(
        registry.request(node_id, "a", {}, timeout_seconds=1, request_id="r1")
    )
    await asyncio.sleep(0)
    with pytest.raises(ApiError) as exc:
        await registry.request(node_id, "b", {}, timeout_seconds=1, request_id="r2")
    assert exc.value.code == "NODE_BUSY"
    registry.resolve_response(node_id, _response(node_id, "r1"))
    await first


async def test_disconnect_cancels_in_flight() -> None:
    registry, node_id, connection = await _registry()
    task = asyncio.create_task(
        registry.request(node_id, "a", {}, timeout_seconds=5, request_id="r1")
    )
    await asyncio.sleep(0)
    await registry.remove(node_id, connection)
    with pytest.raises(ApiError) as exc:
        await task
    assert exc.value.code == "NODE_OFFLINE"


async def test_evict_returns_connection_and_fails_pending() -> None:
    registry, node_id, connection = await _registry()
    task = asyncio.create_task(
        registry.request(node_id, "a", {}, timeout_seconds=5, request_id="r1")
    )
    await asyncio.sleep(0)
    evicted = await registry.evict(node_id)
    assert evicted is connection
    assert not registry.is_connected(node_id)
    with pytest.raises(ApiError) as exc:
        await task
    assert exc.value.code == "NODE_OFFLINE"


async def test_request_to_offline_node_raises() -> None:
    registry = NodeConnectionRegistry(pending_max=128)
    with pytest.raises(ApiError) as exc:
        await registry.request(uuid.uuid4(), "a", {}, timeout_seconds=1, request_id="r1")
    assert exc.value.code == "NODE_OFFLINE"


async def test_heartbeat_resources_are_tracked_live() -> None:
    registry, node_id, _ = await _registry()
    registry.set_resources(node_id, {"cpu_usage": 12.5, "daemon_uptime": 3600})
    assert registry.resources_for(node_id) == {"cpu_usage": 12.5, "daemon_uptime": 3600}
    # Unknown node has no live sample.
    assert registry.resources_for(uuid.uuid4()) is None
