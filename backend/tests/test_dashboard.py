"""Freshness, per-block isolation, caching and role projection (P4-06).

These are the guarantees the Dashboard is *for* — that it never presents a stale
or partial view as a live one — so they are tested without a database, against
fake fetchers and a fake clock. The aggregate SQL is exercised against PostgreSQL
in `tests/db/test_dashboard_api.py`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import metrics
from app.services import dashboard
from app.services.dashboard import (
    DEGRADED_BLOCK,
    OK,
    RECENT_ACTIVITY,
    STALE,
    Block,
    Summary,
    cached_summary,
    project_for,
)
from app.services.registry import DEGRADED, OFFLINE, ONLINE, NodeConnectionRegistry
from app.settings import Settings

AT = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class FakeNode:
    """Only the attributes the freshness rule reads."""

    def __init__(
        self, *, is_enabled: bool = True, status: str = OFFLINE, node_id: uuid.UUID | None = None
    ) -> None:
        self.id = node_id or uuid.uuid4()
        self.is_enabled = is_enabled
        self.status = status
        self.name = "vm"
        self.last_seen_at = None


def service(*, gaps: dict[uuid.UUID, float | None] | None = None) -> dashboard.DashboardService:
    registry = NodeConnectionRegistry(clock=lambda: 0.0)
    lookup = gaps or {}

    def seconds_since_heartbeat(node_id: uuid.UUID) -> float | None:
        return lookup.get(node_id)

    registry.seconds_since_heartbeat = seconds_since_heartbeat  # type: ignore[method-assign]
    return dashboard.DashboardService(session=None, registry=registry, settings=Settings())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Freshness
# --------------------------------------------------------------------------- #


def test_a_fleet_with_fresh_heartbeats_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 3600.0)
    node = FakeNode()
    assert service(gaps={node.id: 2.0})._nodes_freshness([node]) == OK


def test_a_just_restarted_central_reports_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Before one heartbeat interval has passed, "everything offline" and "we have
    not heard from anyone yet" are the same observation. Publishing the first as
    fact is the failure this contract exists to prevent."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 2.0)
    assert service()._nodes_freshness([FakeNode()]) == STALE


def test_a_connected_but_quiet_node_makes_the_block_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Its socket is open so it is still counted, but what it contributed is older
    than the freshness threshold allows to pass as current."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 3600.0)
    node = FakeNode()
    assert service(gaps={node.id: 45.0})._nodes_freshness([node]) == STALE


def test_a_stored_status_claiming_more_liveness_than_the_registry_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`nodes.status` is a snapshot; the registry is the live view. A row that says
    online with no connection behind it is precisely the "cached value posing as
    real time" case."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 3600.0)
    node = FakeNode(status=ONLINE)
    assert service(gaps={})._nodes_freshness([node]) == STALE


def test_a_stored_offline_status_with_a_live_connection_is_not_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction is normal and must not fire: nothing updates
    `nodes.status` after creation, so every live node's row says "offline". Treating
    that as staleness would make the block permanently stale."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 3600.0)
    node = FakeNode(status=OFFLINE)
    assert service(gaps={node.id: 1.0})._nodes_freshness([node]) == OK


def test_an_empty_fleet_is_ok_not_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """No nodes is a real, knowable state — the empty-deployment case — and must not
    be dressed up as uncertainty."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 3600.0)
    assert service()._nodes_freshness([]) == OK


def test_an_empty_fleet_is_ok_even_on_a_just_restarted_central(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by loading the real page against a freshly started Central: the count is 0
    because the table is empty, and no amount of waiting for heartbeats changes that.
    Marking it stale puts "possibly out of date" next to a certain number — on exactly
    the screen where a new operator is deciding whether the product works."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 1.0)
    assert service()._nodes_freshness([]) == OK


def test_a_populated_fleet_on_a_just_restarted_central_is_still_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemption above must not weaken the rule it is carved out of: with nodes
    present, "everything offline" really is indistinguishable from "we have not heard
    from anyone yet"."""
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 1.0)
    assert service()._nodes_freshness([FakeNode()]) == STALE


@pytest.mark.parametrize(
    ("gap", "enabled", "expected"),
    [
        (1.0, True, ONLINE),
        (45.0, True, DEGRADED),
        (200.0, True, OFFLINE),
        (None, True, OFFLINE),
        (1.0, False, "disabled"),
    ],
)
def test_status_comes_from_the_shared_compute_status(
    gap: float | None, enabled: bool, expected: str
) -> None:
    """The same function the node list uses. A second implementation here would
    eventually disagree with the page it is meant to summarize."""
    node = FakeNode(is_enabled=enabled)
    assert service(gaps={node.id: gap})._live_status(node) == expected


# --------------------------------------------------------------------------- #
# Per-block isolation
# --------------------------------------------------------------------------- #


async def test_a_failing_block_degrades_only_itself() -> None:
    async def boom() -> Block:
        raise RuntimeError("relation does not exist")

    metrics.reset()
    block = await service()._guarded("resources", boom)

    assert block.status == DEGRADED_BLOCK
    assert block.data is None
    assert block.error_code == "BLOCK_UNAVAILABLE"
    assert metrics.counter_value(metrics.DASHBOARD_BLOCK_ERROR_TOTAL, block="resources") == 1


async def test_a_failing_block_does_not_leak_the_underlying_error() -> None:
    """A database message can name a table, a column, or a path. The client gets a
    stable code; the counter and the log carry the detail."""

    async def boom() -> Block:
        raise RuntimeError('column "secret_column" of relation "users" does not exist')

    block = await service()._guarded("nodes", boom)
    assert block.error_code is not None
    assert "secret_column" not in repr(block)


async def test_a_successful_block_is_passed_through_unchanged() -> None:
    async def fine() -> Block:
        return Block(status=STALE, generated_at=AT, data={"total": 3})

    block = await service()._guarded("nodes", fine)
    assert (block.status, block.data, block.generated_at) == (STALE, {"total": 3}, AT)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


class CountingService:
    def __init__(self, at: datetime = AT) -> None:
        self.calls = 0
        self._at = at

    async def summary(self) -> Summary:
        self.calls += 1
        return Summary(
            generated_at=self._at,
            blocks={"nodes": Block(status=OK, generated_at=self._at, data={"total": self.calls})},
        )


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_two_requests_inside_the_ttl_fetch_once() -> None:
    dashboard.reset_cache()
    counting, clock = CountingService(), FakeClock()

    first = await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]
    clock.now += 1
    second = await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]

    assert counting.calls == 1
    assert first is second


async def test_generated_at_is_the_fetch_time_not_the_request_time() -> None:
    """Back-filling it to now() would let a five-second-old number claim to be
    current, which is the whole deception the freshness contract forbids."""
    dashboard.reset_cache()
    counting, clock = CountingService(), FakeClock()

    await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]
    clock.now += 4
    cached = await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]

    assert cached.generated_at == AT
    assert cached.blocks["nodes"].generated_at == AT


async def test_the_cache_expires_and_refetches() -> None:
    dashboard.reset_cache()
    counting, clock = CountingService(), FakeClock()

    await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]
    clock.now += 6
    await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]

    assert counting.calls == 2


async def test_reset_cache_forces_a_refetch() -> None:
    dashboard.reset_cache()
    counting, clock = CountingService(), FakeClock()
    await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]
    dashboard.reset_cache()
    await cached_summary(counting, ttl_seconds=5, clock=clock)  # type: ignore[arg-type]
    assert counting.calls == 2


# --------------------------------------------------------------------------- #
# Role projection
# --------------------------------------------------------------------------- #


def _activity_summary() -> Summary:
    return Summary(
        generated_at=AT,
        blocks={
            RECENT_ACTIVITY: Block(
                status=OK,
                generated_at=AT,
                data={
                    "items": [
                        {
                            "id": uuid.uuid4(),
                            "action": "node.remove",
                            "created_at": AT,
                            "actor_id": uuid.uuid4(),
                            "actor_name": "Alice",
                            "node_id": None,
                            "node_name": None,
                        }
                    ],
                    "limit": 20,
                },
            )
        },
    )


def test_audit_view_sees_the_actor() -> None:
    projected = project_for(_activity_summary(), can_view_audit=True)
    assert projected.blocks[RECENT_ACTIVITY].data is not None
    assert projected.blocks[RECENT_ACTIVITY].data["items"][0]["actor_name"] == "Alice"


def test_without_audit_view_the_action_survives_but_the_actor_does_not() -> None:
    """Knowing *that* a node was removed is operational context; knowing *who*
    removed it is the audit trail, and that is Admin-only (FR-AUTH-002)."""
    projected = project_for(_activity_summary(), can_view_audit=False)
    item = projected.blocks[RECENT_ACTIVITY].data["items"][0]  # type: ignore[index]
    assert item["action"] == "node.remove"
    assert item["actor_name"] is None
    assert item["actor_id"] is None
    # Flagged, so the UI can say the column is hidden rather than imply the events
    # had no actor.
    assert projected.blocks[RECENT_ACTIVITY].data["actors_hidden"] is True  # type: ignore[index]


def test_projection_does_not_mutate_the_cached_summary() -> None:
    """The cache is shared. Redacting in place would leak one viewer's permissions
    into the next viewer's response."""
    summary = _activity_summary()
    project_for(summary, can_view_audit=False)
    assert summary.blocks[RECENT_ACTIVITY].data["items"][0]["actor_name"] == "Alice"  # type: ignore[index]


def test_projection_tolerates_a_degraded_activity_block() -> None:
    """Redaction must not resurrect a block that failed to load."""
    summary = Summary(
        generated_at=AT,
        blocks={
            RECENT_ACTIVITY: Block(
                status=DEGRADED_BLOCK, generated_at=AT, data=None, error_code="BLOCK_UNAVAILABLE"
            )
        },
    )
    projected = project_for(summary, can_view_audit=False)
    assert projected.blocks[RECENT_ACTIVITY].data is None
    assert projected.blocks[RECENT_ACTIVITY].status == DEGRADED_BLOCK


# --------------------------------------------------------------------------- #
# Metric sampling rate limit
# --------------------------------------------------------------------------- #


def test_the_first_heartbeat_on_a_connection_claims_a_sample() -> None:
    clock = FakeClock()
    registry = NodeConnectionRegistry(clock=clock)
    node_id = uuid.uuid4()
    registry._connections[node_id] = _connection(node_id, clock.now)  # type: ignore[attr-defined]
    assert registry.claim_metric_sample(node_id, 60) is True


def test_a_second_heartbeat_inside_the_interval_does_not() -> None:
    clock = FakeClock()
    registry = NodeConnectionRegistry(clock=clock)
    node_id = uuid.uuid4()
    registry._connections[node_id] = _connection(node_id, clock.now)  # type: ignore[attr-defined]

    assert registry.claim_metric_sample(node_id, 60) is True
    for _ in range(5):
        clock.now += 10  # heartbeats every 10 s
        assert registry.claim_metric_sample(node_id, 60) is False
    clock.now += 10  # 60 s since the first claim
    assert registry.claim_metric_sample(node_id, 60) is True


def test_an_unknown_node_never_claims_a_sample() -> None:
    """No connection means no heartbeat, so there is nothing to sample — and no
    per-connection state to hold the schedule in."""
    registry = NodeConnectionRegistry(clock=FakeClock())
    assert registry.claim_metric_sample(uuid.uuid4(), 60) is False


def test_a_reconnecting_node_samples_immediately() -> None:
    """The schedule lives on the connection: after a reconnect the first heartbeat
    should be recorded, not held back by the previous socket's timing."""
    clock = FakeClock()
    registry = NodeConnectionRegistry(clock=clock)
    node_id = uuid.uuid4()
    registry._connections[node_id] = _connection(node_id, clock.now)  # type: ignore[attr-defined]
    assert registry.claim_metric_sample(node_id, 60) is True

    clock.now += 5
    registry._connections[node_id] = _connection(node_id, clock.now)  # type: ignore[attr-defined]
    assert registry.claim_metric_sample(node_id, 60) is True


def _connection(node_id: uuid.UUID, at: float):  # type: ignore[no-untyped-def]
    from app.services.registry import NodeConnection

    return NodeConnection(
        node_id=node_id,
        websocket=None,  # type: ignore[arg-type]
        connected_at=at,
        last_heartbeat=at,
    )


def test_the_default_sampling_interval_is_coarser_than_the_heartbeat() -> None:
    """Otherwise every heartbeat writes a row: six per node per minute, for no extra
    fidelity than one (ADR 0018)."""
    settings = Settings()
    assert settings.node_metric_sample_interval_seconds > settings.heartbeat_interval_seconds
    # And the resource window must span more than one interval, so a single missed
    # sample cannot empty the fleet summary.
    assert settings.dashboard_resource_window_seconds > settings.node_metric_sample_interval_seconds


def test_every_declared_block_has_a_fetcher() -> None:
    """`BLOCKS` is what the UI and the tests iterate over. A name listed there with
    no fetcher produces a card that is permanently absent — which reads as "this
    metric does not exist" rather than "it could not be loaded"."""
    assert set(service()._fetchers()) == set(dashboard.BLOCKS)


# --------------------------------------------------------------------------- #
# Wire contract with the browser
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).parents[2]
DTO = ROOT / "frontend/src/api/dto.ts"


def test_block_names_match_the_frontend_summary_type() -> None:
    """The browser types each block individually, so a block renamed on one side
    silently renders as an absent card on the other."""
    source = DTO.read_text(encoding="utf-8")
    block = re.search(r"export interface DashboardSummary \{.*?\n\}", source, re.S)
    assert block is not None, "DashboardSummary is missing from frontend/src/api/dto.ts"
    declared = set(re.findall(r"^\s{4}(\w+): DashboardBlock<", block.group(0), re.M))
    assert declared == set(dashboard.BLOCKS)


def test_unhealthy_reason_codes_match_the_frontend_union() -> None:
    """The UI turns each code into wording. A code it does not know about would show
    as a blank explanation next to a node flagged as unhealthy."""
    source = DTO.read_text(encoding="utf-8")
    union = re.search(r"export type UnhealthyReason =(.*?);", source, re.S)
    assert union is not None
    assert set(re.findall(r'"([^"]+)"', union.group(1))) == {
        dashboard.REASON_OFFLINE,
        dashboard.REASON_DEGRADED,
        dashboard.REASON_NO_RUNTIME,
        dashboard.REASON_RECENT_FAILURE,
    }


def test_block_status_values_match_the_frontend_union() -> None:
    source = DTO.read_text(encoding="utf-8")
    union = re.search(r"export type DashboardBlockStatus =(.*?);", source, re.S)
    assert union is not None
    assert set(re.findall(r'"([^"]+)"', union.group(1))) == {OK, STALE, DEGRADED_BLOCK}
