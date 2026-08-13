"""Why a runner went quiet, and the two other things this page must not confuse it with.

Exit condition 21. A runner with no capacity reports it by **not polling** — there is no
"capacity: 0" frame, which is what removes the scheduler from the platform (ADR 0029
sec 2). The price is that from Central three different situations look identical:

* the runner is full,
* the runner has nowhere to put a checkout,
* the machine is gone.

All three are silence on the socket. Only the node can tell them apart, so it says which
on its heartbeat, and this is where that lands. Without it the Agents page shows 「離線」
for a healthy machine and somebody goes looking for a network fault.

The trap this file is mostly guarding is the *stale* one: a reason that is written when
it appears and never cleared. A runner that filled its disk in March would then still
read 「磁碟用盡」 in June, on a page whose whole job is to say what is true now.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.models import AgentRunner, Node, Project, Role, Task, User
from app.security.passwords import hash_password
from app.services.runners import RunnerService

pytestmark = pytest.mark.asyncio


async def _runner(maker) -> tuple[uuid.UUID, uuid.UUID]:
    """A node with a runner. Returns (node_id, runner_id)."""
    async with maker() as session:
        name = f"pressure-{uuid.uuid4().hex[:8]}"
        node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(),
            node_id=node.id,
            name=name,
            runtimes=["claude"],
            labels=[],
            max_concurrent=2,
            max_waiting=5,
        )
        session.add(runner)
        await session.commit()
        return node.id, runner.id


async def test_a_reason_is_recorded_and_then_cleared(api: tuple, projects_enabled: None) -> None:
    """Both directions, because only the first one is obvious.

    Writing the reason is the feature; clearing it is what keeps the page true. A
    service that only ever wrote non-empty values would leave a runner that recovered
    still reading 「磁碟用盡」, and the reader has no way to tell that from a runner
    that is still full.
    """
    _client, maker = api
    node_id, runner_id = await _runner(maker)

    async with maker() as session:
        await RunnerService(session).record_pressure(
            node_id,
            {
                "blocked_reason": "disk_quota",
                "disk_used_bytes": 5153960755,
                "disk_quota_bytes": 5368709120,
            },
        )
        await session.commit()

    async with maker() as session:
        row = await session.get(AgentRunner, runner_id)
        assert row is not None
        assert row.blocked_reason == "disk_quota"
        assert row.disk_used_bytes == 5153960755
        assert row.disk_quota_bytes == 5368709120
        assert row.reported_at is not None

    # The next heartbeat from a runner that has recovered carries no reason.
    async with maker() as session:
        await RunnerService(session).record_pressure(
            node_id, {"disk_used_bytes": 104857600, "disk_quota_bytes": 5368709120}
        )
        await session.commit()

    async with maker() as session:
        row = await session.get(AgentRunner, runner_id)
        assert row is not None
        assert row.blocked_reason is None
        assert row.disk_used_bytes == 104857600


async def test_a_reason_the_platform_does_not_know_is_dropped(
    api: tuple, projects_enabled: None
) -> None:
    """The value is rendered as console copy, so it is compared against a closed set.

    A node is not a trusted source of the words on an operator's screen: an unrecognised
    reason stored verbatim would either be printed raw or, worse, fall through the
    console's `switch` and show the runner as 「線上」 while it takes no work at all.
    """
    _client, maker = api
    node_id, runner_id = await _runner(maker)

    async with maker() as session:
        await RunnerService(session).record_pressure(node_id, {"blocked_reason": "offline"})
        await session.commit()

    async with maker() as session:
        row = await session.get(AgentRunner, runner_id)
        assert row is not None
        assert row.blocked_reason is None


async def test_a_disk_figure_that_was_not_measured_is_left_alone(
    api: tuple, projects_enabled: None
) -> None:
    """A missing measurement must not become a number.

    The daemon omits the field when it could not walk its run root. Writing 0 there
    would render as an empty disk with plenty of room — the opposite of "we do not
    know" — and would rule disk out as a cause for whoever is reading the page.
    """
    _client, maker = api
    node_id, runner_id = await _runner(maker)

    async with maker() as session:
        service = RunnerService(session)
        await service.record_pressure(node_id, {"disk_used_bytes": 4096, "disk_quota_bytes": 8192})
        await service.record_pressure(node_id, {"blocked_reason": "at_capacity"})
        await session.commit()

    async with maker() as session:
        row = await session.get(AgentRunner, runner_id)
        assert row is not None
        assert row.blocked_reason == "at_capacity"
        # Kept, not zeroed.
        assert row.disk_used_bytes == 4096
        assert row.disk_quota_bytes == 8192


async def test_a_heartbeat_from_a_node_that_is_not_a_runner_writes_nothing(
    api: tuple, projects_enabled: None
) -> None:
    """The `runner` object is absent on a plain node, and absence is not a report.

    Treating it as "nothing is wrong" would overwrite a real reason every five seconds
    on a node whose runner mode was switched off mid-incident.
    """
    _client, maker = api
    node_id, runner_id = await _runner(maker)

    async with maker() as session:
        service = RunnerService(session)
        await service.record_pressure(node_id, {"blocked_reason": "disk_low"})
        await service.record_pressure(node_id, None)
        await session.commit()

    async with maker() as session:
        row = await session.get(AgentRunner, runner_id)
        assert row is not None
        assert row.blocked_reason == "disk_low"


async def test_the_page_gets_the_pinned_card_count(api: tuple, projects_enabled: None) -> None:
    """Assigned is not occupied, and the difference is the point.

    A card can name a runner for days without ever producing a run, so a console that
    shows only 「執行中」 makes an over-subscribed machine look idle. The plan names this
    as one of the three most easily omitted numbers on the page.
    """
    _client, maker = api
    node_id, runner_id = await _runner(maker)
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        name = f"pin-{uuid.uuid4().hex[:8]}"
        user = User(
            id=uuid.uuid4(),
            username=name,
            display_name=name,
            password_hash=hash_password("pw"),
            role_id=role.id,
        )
        session.add(user)
        await session.flush()
        project = Project(
            id=uuid.uuid4(),
            name=name,
            slug=name,
            status="active",
            owner_user_id=user.id,
            next_card_seq=1,
        )
        session.add(project)
        await session.flush()
        session.add_all(
            [
                Task(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    card_ref=f"TASK-{index}-{uuid.uuid4().hex[:4]}",
                    title=f"card {index}",
                    stage="ready",
                    source="none",
                    delivery="none",
                    assigned_runner_id=runner_id,
                )
                for index in range(3)
            ]
        )
        await session.commit()

    async with maker() as session:
        runner = await session.get(AgentRunner, runner_id)
        assert runner is not None
        view = await RunnerService(session).view(runner, is_online=lambda _id: True)
        assert view.assigned_cards == 3
        # None of them has run, and the page must not present that as spare capacity.
        assert view.active_runs == 0
        assert view.node.id == node_id
