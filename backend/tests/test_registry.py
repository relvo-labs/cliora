import uuid

from app.services.registry import (
    DEGRADED,
    DISABLED,
    OFFLINE,
    ONLINE,
    NodeConnectionRegistry,
    compute_status,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_compute_status_transitions() -> None:
    kw = {"online_within": 30, "degraded_within": 90}
    assert compute_status(is_enabled=True, seconds_since_heartbeat=5, **kw) == ONLINE
    assert compute_status(is_enabled=True, seconds_since_heartbeat=30, **kw) == ONLINE
    assert compute_status(is_enabled=True, seconds_since_heartbeat=60, **kw) == DEGRADED
    assert compute_status(is_enabled=True, seconds_since_heartbeat=120, **kw) == OFFLINE
    assert compute_status(is_enabled=True, seconds_since_heartbeat=None, **kw) == OFFLINE
    # Disabled wins regardless of liveness (FR-NODE-005).
    assert compute_status(is_enabled=False, seconds_since_heartbeat=1, **kw) == DISABLED


async def test_registry_tracks_heartbeat_with_monotonic_clock() -> None:
    clock = FakeClock()
    registry = NodeConnectionRegistry(clock=clock)
    node_id = uuid.uuid4()

    connection, previous = await registry.register(node_id, object())  # type: ignore[arg-type]
    assert previous is None
    assert registry.is_connected(node_id)
    assert registry.seconds_since_heartbeat(node_id) == 0

    clock.now += 50
    assert registry.seconds_since_heartbeat(node_id) == 50

    await registry.touch(node_id)
    assert registry.seconds_since_heartbeat(node_id) == 0
    clock.now += 10
    assert registry.seconds_since_heartbeat(node_id) == 10

    await registry.remove(node_id, connection)
    assert not registry.is_connected(node_id)
    assert registry.seconds_since_heartbeat(node_id) is None


async def test_registry_replace_returns_previous() -> None:
    registry = NodeConnectionRegistry(clock=FakeClock())
    node_id = uuid.uuid4()
    first, previous = await registry.register(node_id, object())  # type: ignore[arg-type]
    assert previous is None
    _, previous2 = await registry.register(node_id, object())  # type: ignore[arg-type]
    assert previous2 is first
    # Removing the stale first connection must not drop the live one.
    await registry.remove(node_id, first)
    assert registry.is_connected(node_id)


async def test_binary_preview_bit_belongs_to_the_live_connection() -> None:
    """ADR 0029 §9: the authoritative gate is the registration of the connection that
    is open *now*. A daemon that reconnects downgraded must be refused at once, not
    after the next database write, and a closed connection carries no capability."""
    registry = NodeConnectionRegistry(clock=FakeClock())
    node_id = uuid.uuid4()
    assert registry.binary_preview(node_id) is False  # no connection at all

    first, _ = await registry.register(node_id, object())  # type: ignore[arg-type]
    assert registry.binary_preview(node_id) is False  # connected, nothing reported yet
    registry.set_binary_preview(first, True)
    assert registry.binary_preview(node_id) is True

    # A replacement connection starts with nothing, whatever the old one said.
    second, previous = await registry.register(node_id, object())  # type: ignore[arg-type]
    assert previous is first
    assert registry.binary_preview(node_id) is False
    # A late write on the superseded connection cannot switch the new one on.
    registry.set_binary_preview(first, True)
    assert registry.binary_preview(node_id) is False

    registry.set_binary_preview(second, True)
    await registry.remove(node_id, second)
    assert registry.binary_preview(node_id) is False
