"""`GET /api/dashboard/summary` against the real app and schema (P4-06, PRD §10.2).

The freshness rules and the cache are covered hermetically in
`tests/test_dashboard.py`. What needs PostgreSQL is the aggregate SQL itself, the
two scenarios the plan requires of every Dashboard test — **one backend query
failing** and **no nodes at all** — and the heartbeat write path that fills
`node_metric_samples`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import metrics
from app.db.models import (
    AuditLog,
    Node,
    NodeMetricSample,
    NodeRuntime,
    Role,
    TerminalSession,
    User,
)
from app.security.passwords import hash_password
from app.services import audit, dashboard
from app.services.nodes import NodeRegistrationService
from app.services.registry import NodeConnectionRegistry
from app.settings import Settings

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The aggregate cache is process-wide: a summary left behind by one test would
    be served to the next, and the assertions would pass or fail on stale data."""
    dashboard.reset_cache()
    yield
    dashboard.reset_cache()


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str = "Admin"
) -> tuple[uuid.UUID, dict[str, str]]:
    username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password("pw"),
            display_name=f"{role_name} {username}",
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _node(
    maker: async_sessionmaker,
    *,
    name: str = "vm-1",
    enabled: bool = True,
    runtimes: dict[str, bool] | None = None,
    checked_at: datetime | None = None,
) -> uuid.UUID:
    async with maker() as session:
        node = Node(name=name, hostname=f"{name}.local", status="offline", is_enabled=enabled)
        node.runtimes = [
            NodeRuntime(runtime=runtime, available=available, checked_at=checked_at)
            for runtime, available in (runtimes or {}).items()
        ]
        session.add(node)
        await session.commit()
        return node.id


async def _session_row(
    maker: async_sessionmaker,
    node_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status: str = "running",
    runtime: str = "claude",
) -> uuid.UUID:
    async with maker() as session:
        row = TerminalSession(
            node_id=node_id,
            user_id=user_id,
            name="s",
            runtime=runtime,
            workspace="/home/neil/projects/app",
            status=status,
        )
        session.add(row)
        await session.commit()
        return row.id


async def _sample(
    maker: async_sessionmaker,
    node_id: uuid.UUID,
    *,
    at: datetime,
    cpu: float | None = None,
    memory: float | None = None,
) -> None:
    async with maker() as session:
        session.add(
            NodeMetricSample(
                node_id=node_id,
                sampled_at=at,
                cpu_usage=cpu,
                memory_usage=memory,
                active_sessions=1,
            )
        )
        await session.commit()


async def _summary(client: AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.get("/api/dashboard/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# Shape and authorization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("role", ["Admin", "Developer", "Viewer"])
async def test_every_role_may_read_the_summary(api: tuple, role: str) -> None:
    """The Dashboard is the landing page; all three roles hold `node.view`. What
    differs is the detail, not the access."""
    client, maker = api
    _, headers = await _actor(client, maker, role)
    body = await _summary(client, headers)
    assert set(body["blocks"]) == set(dashboard.BLOCKS)


async def test_unauthenticated_read_is_401(api: tuple) -> None:
    client, _ = api
    assert (await client.get("/api/dashboard/summary")).status_code == 401


async def test_every_block_declares_a_status_and_its_own_fetch_time(api: tuple) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    body = await _summary(client, headers)
    for name, block in body["blocks"].items():
        assert block["status"] in {"ok", "stale", "degraded"}, name
        # Per block, not one page-level timestamp: blocks are fetched separately and
        # a single shared instant would misdate the ones that came from the cache.
        assert block["generated_at"], name


# --------------------------------------------------------------------------- #
# Empty deployment
# --------------------------------------------------------------------------- #


async def test_an_empty_deployment_returns_legal_empty_values_not_errors(api: tuple) -> None:
    """A fresh install must render the "install your first node" state. Returning
    404 or null would make the page show a failure instead."""
    client, maker = api
    _, headers = await _actor(client, maker)
    body = await _summary(client, headers)

    blocks = body["blocks"]
    assert blocks["nodes"]["data"]["total"] == 0
    assert blocks["sessions"]["data"]["total_active"] == 0
    assert blocks["unhealthy_nodes"]["data"]["items"] == []
    assert blocks["runtimes"]["data"]["eligible_nodes"] == 0
    # Every block answers with an empty value, not null: a null would force the UI
    # to branch before it can even show the empty state.
    for name in dashboard.BLOCKS:
        assert blocks[name]["data"] is not None, f"{name} returned null on an empty deployment"


async def test_no_resource_samples_reports_empty_rather_than_zero(api: tuple) -> None:
    """0% CPU and "no data" are different facts. Reporting the first when the second
    is true invents a healthy fleet out of an absence of evidence."""
    client, maker = api
    _, headers = await _actor(client, maker)
    resources = (await _summary(client, headers))["blocks"]["resources"]

    assert resources["status"] == "ok"
    assert resources["data"]["sampled_nodes"] == 0
    assert resources["data"]["latest_sample_at"] is None
    for measurement in resources["data"]["measurements"].values():
        assert measurement["average"] is None
        assert measurement["maximum"] is None
        assert measurement["nodes"] == 0


# --------------------------------------------------------------------------- #
# Partial backend failure
# --------------------------------------------------------------------------- #


async def test_one_failing_block_degrades_only_that_block(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan's `partial` contract: the page still answers, one card says
    "temporarily unavailable", and the other five show real numbers."""
    client, maker = api
    _, headers = await _actor(client, maker)
    await _node(maker, runtimes={"claude": True})

    async def boom(self) -> dashboard.Block:  # type: ignore[no-untyped-def]
        raise RuntimeError('relation "node_metric_samples" does not exist')

    monkeypatch.setattr(dashboard.DashboardService, "_resources_block", boom)
    metrics.reset()
    body = await _summary(client, headers)

    resources = body["blocks"]["resources"]
    assert resources["status"] == "degraded"
    assert resources["data"] is None
    assert resources["error_code"] == "BLOCK_UNAVAILABLE"
    # The underlying message could name a table; it must not reach the client.
    assert (
        "node_metric_samples"
        not in (await client.get("/api/dashboard/summary", headers=headers)).text
    )
    assert body["blocks"]["nodes"]["data"]["total"] == 1
    assert body["blocks"]["sessions"]["status"] == "ok"
    assert metrics.counter_value(metrics.DASHBOARD_BLOCK_ERROR_TOTAL, block="resources") >= 1


async def test_a_failing_block_does_not_make_the_response_an_error(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)

    async def boom(self) -> dashboard.Block:  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(dashboard.DashboardService, "_recent_activity_block", boom)
    assert (await client.get("/api/dashboard/summary", headers=headers)).status_code == 200


# --------------------------------------------------------------------------- #
# Aggregates
# --------------------------------------------------------------------------- #


async def test_node_counts_come_from_the_live_registry_not_the_stored_column(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`nodes.status` has said "offline" since P1 for every node, live or not.
    Counting it would report an entirely offline fleet."""
    client, maker = api
    _, headers = await _actor(client, maker)
    online = await _node(maker, name="online-1")
    await _node(maker, name="offline-1")
    disabled = await _node(maker, name="disabled-1", enabled=False)

    registry = NodeConnectionRegistry(clock=lambda: 0.0)
    monkeypatch.setattr(
        registry,
        "seconds_since_heartbeat",
        lambda node_id: 1.0 if node_id in (online, disabled) else None,
    )
    monkeypatch.setattr(dashboard, "get_node_registry", lambda: registry)
    monkeypatch.setattr(dashboard, "process_uptime_seconds", lambda: 3600.0)

    data = (await _summary(client, headers))["blocks"]["nodes"]["data"]
    assert data == {"online": 1, "degraded": 0, "offline": 1, "disabled": 1, "total": 3}


async def test_a_soft_deleted_node_is_excluded_from_every_count(api: tuple) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    async with maker() as session:
        await session.execute(sa.update(Node).where(Node.id == node_id).values(deleted_at=NOW))
        await session.commit()

    body = await _summary(client, headers)
    assert body["blocks"]["nodes"]["data"]["total"] == 0
    assert body["blocks"]["unhealthy_nodes"]["data"]["items"] == []


async def test_sessions_are_counted_by_state_and_by_runtime(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    node_id = await _node(maker)
    await _session_row(maker, node_id, actor_id, status="running", runtime="claude")
    await _session_row(maker, node_id, actor_id, status="running", runtime="codex")
    await _session_row(maker, node_id, actor_id, status="starting", runtime="claude")
    # Terminal states must not be counted as active.
    await _session_row(maker, node_id, actor_id, status="exited", runtime="claude")
    await _session_row(maker, node_id, actor_id, status="terminated", runtime="codex")

    data = (await _summary(client, headers))["blocks"]["sessions"]["data"]
    assert data["running"] == 2
    assert data["starting"] == 1
    assert data["total_active"] == 3
    assert data["per_runtime"] == {"claude": 2, "codex": 1}


async def test_a_runtime_nobody_has_reported_is_unknown_not_unavailable(api: tuple) -> None:
    """Silence is not a negative. A node that has never reported Codex has not said
    Codex is missing, and showing it as unavailable makes a fresh fleet look broken."""
    client, maker = api
    _, headers = await _actor(client, maker)
    await _node(maker, name="a", runtimes={"claude": True}, checked_at=None)

    runtimes = (await _summary(client, headers))["blocks"]["runtimes"]["data"]["runtimes"]
    assert runtimes["claude"]["available"] == 1
    assert runtimes["claude"]["unknown"] == 0
    assert runtimes["codex"]["available"] == 0
    assert runtimes["codex"]["unavailable"] == 0
    assert runtimes["codex"]["unknown"] == 1


async def test_an_unavailable_runtime_is_reported_as_unavailable(api: tuple) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    await _node(maker, name="a", runtimes={"claude": True, "codex": False})

    runtimes = (await _summary(client, headers))["blocks"]["runtimes"]["data"]["runtimes"]
    assert runtimes["codex"]["unavailable"] == 1
    assert runtimes["codex"]["unknown"] == 0


async def test_stale_runtime_detection_marks_the_block_stale(api: tuple) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    ancient = datetime.now(UTC) - timedelta(days=2)
    await _node(maker, name="a", runtimes={"claude": True}, checked_at=ancient)

    assert (await _summary(client, headers))["blocks"]["runtimes"]["status"] == "stale"


async def test_the_fleet_summary_averages_the_newest_sample_per_node(api: tuple) -> None:
    """Per node first, then across the fleet. Averaging raw rows would let one chatty
    node outweigh a quiet one."""
    client, maker = api
    _, headers = await _actor(client, maker)
    chatty = await _node(maker, name="chatty")
    quiet = await _node(maker, name="quiet")
    recent = datetime.now(UTC) - timedelta(seconds=30)
    # Three samples for one node; only its newest should count.
    await _sample(maker, chatty, at=recent - timedelta(seconds=20), cpu=10.0)
    await _sample(maker, chatty, at=recent - timedelta(seconds=10), cpu=20.0)
    await _sample(maker, chatty, at=recent, cpu=30.0)
    await _sample(maker, quiet, at=recent, cpu=70.0)

    data = (await _summary(client, headers))["blocks"]["resources"]["data"]
    assert data["sampled_nodes"] == 2
    assert data["measurements"]["cpu_usage"]["average"] == pytest.approx(50.0)
    assert data["measurements"]["cpu_usage"]["maximum"] == pytest.approx(70.0)
    assert data["measurements"]["cpu_usage"]["nodes"] == 2


async def test_a_measurement_no_node_reported_stays_unknown(api: tuple) -> None:
    """Every column is nullable because the daemon reads each best-effort. A NULL
    must not be averaged in as 0 — an unreadable disk would then look empty."""
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    await _sample(maker, node_id, at=datetime.now(UTC), cpu=50.0, memory=None)

    measurements = (await _summary(client, headers))["blocks"]["resources"]["data"]["measurements"]
    assert measurements["cpu_usage"]["nodes"] == 1
    assert measurements["memory_usage"]["nodes"] == 0
    assert measurements["memory_usage"]["average"] is None


async def test_samples_older_than_the_window_are_ignored(api: tuple) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    node_id = await _node(maker)
    stale_at = datetime.now(UTC) - timedelta(
        seconds=Settings().dashboard_resource_window_seconds * 3
    )
    await _sample(maker, node_id, at=stale_at, cpu=99.0)

    data = (await _summary(client, headers))["blocks"]["resources"]["data"]
    assert data["sampled_nodes"] == 0
    assert data["measurements"]["cpu_usage"]["average"] is None


async def test_unhealthy_nodes_carry_a_reason_code_each(api: tuple) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    # Enabled, no runtime available, and no connection: two reasons.
    await _node(maker, name="broken", runtimes={"claude": False})

    data = (await _summary(client, headers))["blocks"]["unhealthy_nodes"]["data"]
    assert data["total"] == 1
    reasons = data["items"][0]["reasons"]
    assert dashboard.REASON_OFFLINE in reasons
    assert dashboard.REASON_NO_RUNTIME in reasons


async def test_a_disabled_node_is_not_faulted_for_having_no_runtime(api: tuple) -> None:
    """Disabling is an operator decision, not a fault. Listing it as unhealthy would
    make the intended state look like a problem."""
    client, maker = api
    _, headers = await _actor(client, maker)
    await _node(maker, name="parked", enabled=False, runtimes={"claude": False})

    data = (await _summary(client, headers))["blocks"]["unhealthy_nodes"]["data"]
    assert data["items"] == []


async def test_a_recent_session_failure_marks_its_node_unhealthy(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    node_id = await _node(maker, name="flaky", runtimes={"claude": True})
    async with maker() as session:
        session.add(
            AuditLog(
                action=audit.SESSION_FAILED,
                node_id=node_id,
                user_id=actor_id,
                audit_metadata={},
                created_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    data = (await _summary(client, headers))["blocks"]["unhealthy_nodes"]["data"]
    assert dashboard.REASON_RECENT_FAILURE in data["items"][0]["reasons"]


async def test_the_unhealthy_list_is_bounded_but_reports_the_true_total(api: tuple) -> None:
    """Truncating silently would imply the list is complete; the total is what makes
    "10 of 37" honest."""
    client, maker = api
    _, headers = await _actor(client, maker)
    limit = Settings().dashboard_unhealthy_limit
    for index in range(limit + 3):
        await _node(maker, name=f"bad-{index}", runtimes={"claude": False})

    data = (await _summary(client, headers))["blocks"]["unhealthy_nodes"]["data"]
    assert len(data["items"]) == limit
    assert data["total"] == limit + 3


async def test_recent_activity_is_bounded_and_carries_no_metadata(api: tuple) -> None:
    """This block is rendered for every role, so it carries only the safe columns —
    metadata is released solely through the Admin-only audit endpoint."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    async with maker() as session:
        session.add_all(
            AuditLog(
                action=audit.USER_LOGOUT,
                user_id=actor_id,
                audit_metadata={"password": "leak", "reason": "x"},
                created_at=datetime.now(UTC) - timedelta(seconds=index),
            )
            for index in range(30)
        )
        await session.commit()

    block = (await _summary(client, headers))["blocks"]["recent_activity"]
    assert len(block["data"]["items"]) == Settings().dashboard_recent_activity_limit
    assert "leak" not in str(block)
    assert set(block["data"]["items"][0]) == {
        "id",
        "action",
        "created_at",
        "actor_id",
        "actor_name",
        "node_id",
        "node_name",
    }


# --------------------------------------------------------------------------- #
# Role differences
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("role", "sees_actor"), [("Admin", True), ("Developer", False), ("Viewer", False)]
)
async def test_actor_identity_in_recent_activity_requires_audit_view(
    api: tuple, role: str, sees_actor: bool
) -> None:
    client, maker = api
    actor_id, _ = await _actor(client, maker, "Admin")
    async with maker() as session:
        session.add(
            AuditLog(
                action=audit.NODE_REMOVE,
                user_id=actor_id,
                audit_metadata={},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    _, headers = await _actor(client, maker, role)
    block = (await _summary(client, headers))["blocks"]["recent_activity"]
    entry = next(item for item in block["data"]["items"] if item["action"] == audit.NODE_REMOVE)

    if sees_actor:
        assert entry["actor_id"] is not None
        assert entry["actor_name"]
        assert "actors_hidden" not in block["data"]
    else:
        assert entry["actor_id"] is None
        assert entry["actor_name"] is None
        assert block["data"]["actors_hidden"] is True
    # The action and the instant survive for every role: fleet context, not identity.
    assert entry["action"] == audit.NODE_REMOVE
    assert entry["created_at"]


async def test_a_cached_summary_is_projected_per_viewer_not_shared_verbatim(api: tuple) -> None:
    """The cache is process-wide. If redaction happened before caching, whichever
    role asked first would decide what every later role sees."""
    client, maker = api
    actor_id, admin = await _actor(client, maker, "Admin")
    async with maker() as session:
        session.add(
            AuditLog(
                action=audit.NODE_REMOVE,
                user_id=actor_id,
                audit_metadata={},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    _, developer = await _actor(client, maker, "Developer")

    # Developer first, then Admin, inside one cache TTL.
    dev_block = (await _summary(client, developer))["blocks"]["recent_activity"]
    admin_block = (await _summary(client, admin))["blocks"]["recent_activity"]

    dev_entry = next(i for i in dev_block["data"]["items"] if i["action"] == audit.NODE_REMOVE)
    admin_entry = next(i for i in admin_block["data"]["items"] if i["action"] == audit.NODE_REMOVE)
    assert dev_entry["actor_id"] is None
    assert admin_entry["actor_id"] is not None


# --------------------------------------------------------------------------- #
# Heartbeat sample persistence
# --------------------------------------------------------------------------- #


async def _samples(maker: async_sessionmaker, node_id: uuid.UUID) -> list[NodeMetricSample]:
    async with maker() as session:
        result = await session.execute(
            sa.select(NodeMetricSample)
            .where(NodeMetricSample.node_id == node_id)
            .order_by(NodeMetricSample.sampled_at)
        )
        return list(result.scalars())


async def test_a_heartbeat_sample_is_persisted_with_every_measurement(api: tuple) -> None:
    client, maker = api
    node_id = await _node(maker)
    async with maker() as session:
        service = NodeRegistrationService(session)
        assert await service.persist_metric_sample(
            node_id,
            {
                "daemon_version": "0.2.0",
                "active_sessions": 3,
                "resources": {
                    "cpu_usage": 12.5,
                    "memory_usage": 40.0,
                    "load_average": 0.5,
                    "disk_usage": 60.0,
                    "daemon_uptime": 900.0,
                },
            },
        )
        await session.commit()

    rows = await _samples(maker, node_id)
    assert len(rows) == 1
    assert (rows[0].cpu_usage, rows[0].active_sessions, rows[0].daemon_uptime) == (12.5, 3, 900.0)
    assert rows[0].sampled_at.tzinfo is not None


async def test_a_heartbeat_without_resources_still_records_the_session_count(api: tuple) -> None:
    """The `resources` object is optional in the protocol. A heartbeat that omits it
    still says how many sessions are running, which is worth keeping."""
    client, maker = api
    node_id = await _node(maker)
    async with maker() as session:
        service = NodeRegistrationService(session)
        assert await service.persist_metric_sample(
            node_id, {"daemon_version": "0.2.0", "active_sessions": 2}
        )
        await session.commit()

    rows = await _samples(maker, node_id)
    assert rows[0].cpu_usage is None
    assert rows[0].active_sessions == 2


async def test_a_failed_sample_write_is_counted_and_does_not_break_the_heartbeat(
    api: tuple,
) -> None:
    """The point of the savepoint: a history row that cannot be written must not
    take the `last_seen_at` update — which decides liveness — down with it."""
    client, maker = api
    metrics.reset()
    async with maker() as session:
        service = NodeRegistrationService(session)
        await service.record_heartbeat(uuid.uuid4())  # no-op update, still fine
        # A node id with no row violates the FK, so the insert fails.
        assert (
            await service.persist_metric_sample(
                uuid.uuid4(), {"active_sessions": 1, "resources": {"cpu_usage": 1.0}}
            )
            is False
        )
        # The transaction is still usable, which is the whole claim.
        node_id = await _node(maker)
        assert await service.persist_metric_sample(node_id, {"active_sessions": 1}) is True
        await session.commit()

    assert metrics.counter_value(metrics.METRIC_PERSIST_ERROR_TOTAL, reason="write_failed") == 1
    assert len(await _samples(maker, node_id)) == 1


async def test_a_non_numeric_resource_value_is_stored_as_unknown(api: tuple) -> None:
    """The protocol validator rejects these upstream; this is the write path refusing
    to coerce a bad value into a plausible number."""
    client, maker = api
    node_id = await _node(maker)
    async with maker() as session:
        service = NodeRegistrationService(session)
        assert await service.persist_metric_sample(
            node_id, {"active_sessions": "many", "resources": {"cpu_usage": "high"}}
        )
        await session.commit()

    rows = await _samples(maker, node_id)
    assert rows[0].cpu_usage is None
    assert rows[0].active_sessions is None


async def test_removing_a_node_removes_its_samples(api: tuple) -> None:
    """`ON DELETE CASCADE`: node removal is a soft delete today, but a hard delete
    (a test teardown, a future purge) must not leave orphan rows behind."""
    client, maker = api
    node_id = await _node(maker)
    await _sample(maker, node_id, at=datetime.now(UTC), cpu=1.0)
    async with maker() as session:
        await session.execute(sa.delete(Node).where(Node.id == node_id))
        await session.commit()
    assert await _samples(maker, node_id) == []
