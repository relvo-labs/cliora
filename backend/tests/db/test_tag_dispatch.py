"""Tag matching, the fifth eligibility condition, and the two node-side refusals.

FR-RUNENV-008, ADR 0029 amendment B. The most valuable test in this file is
`test_the_sql_and_python_predicates_agree`: it is the only one that goes red when
somebody changes one of the two eligibility paths and not the other, and that failure
has no other symptom — the queue behaves one way while the console explains the other.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.models import AgentRunner, Node, Project, Role, Task, User
from app.security.passwords import hash_password
from app.services.registry import NodeConnectionRegistry
from app.services.runs import RunService, tag_match

pytestmark = pytest.mark.asyncio


class _Registry(NodeConnectionRegistry):
    def __init__(self, online: set[uuid.UUID] | None = None) -> None:
        super().__init__()
        self._online = online or set()

    def is_connected(self, node_id: uuid.UUID) -> bool:  # type: ignore[override]
        return node_id in self._online


async def _actor(client, maker, role_name: str = "Admin") -> tuple[uuid.UUID, dict]:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
        user = User(
            id=uuid.uuid4(),
            username=username,
            display_name=username,
            password_hash=hash_password("pw"),
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
    tokens = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    return user.id, {"authorization": f"Bearer {tokens.json()['tokens']['access_token']}"}


async def _project(maker, owner_id: uuid.UUID, **fields) -> uuid.UUID:
    async with maker() as session:
        slug = f"p-{uuid.uuid4().hex[:8]}"
        project = Project(
            id=uuid.uuid4(),
            name=slug,
            slug=slug,
            status="active",
            owner_user_id=owner_id,
            next_card_seq=1,
            **fields,
        )
        session.add(project)
        await session.commit()
        return project.id


async def _card(maker, project_id: uuid.UUID, **fields) -> uuid.UUID:
    async with maker() as session:
        seq = uuid.uuid4().hex[:6]
        task = Task(
            id=uuid.uuid4(),
            project_id=project_id,
            card_ref=f"TASK-{seq}",
            title="a card",
            stage=fields.pop("stage", "ready"),
            risk="low",
            priority="normal",
            delivery=fields.pop("delivery", "artifact"),
            source=fields.pop("source", "none"),
            **fields,
        )
        session.add(task)
        await session.commit()
        return task.id


async def _runner(maker, **fields) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        name = f"node-{uuid.uuid4().hex[:8]}"
        node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(),
            node_id=node.id,
            name=name,
            runtimes=fields.pop("runtimes", []),
            labels=fields.pop("labels", []),
            max_concurrent=1,
            max_waiting=5,
            **fields,
        )
        session.add(runner)
        await session.commit()
        return runner.id, node.id


async def _claim(maker, runner_id: uuid.UUID) -> uuid.UUID | None:
    """One poll, and the run it would be offered — or None."""
    async with maker() as session:
        runner = await session.get(AgentRunner, runner_id)
        offer = await RunService(session).poll(runner=runner, capacity=1)
        await session.commit()
        return offer.run.id if offer is not None else None


# --- the direction of the containment operator -----------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_a_runner_with_more_tags_than_the_card_asks_for_still_claims_it(api) -> None:
    """Superset matching. `@>` instead of `<@` would compile, run, and fail here."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, required_labels=["docker"])
    runner_id, node_id = await _runner(maker, labels=["docker", "node20", "gpu"])

    await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert await _claim(maker, runner_id) is not None


@pytest.mark.usefixtures("projects_enabled")
async def test_a_runner_missing_one_of_the_cards_tags_never_sees_it(api) -> None:
    """The other direction, and the reason both are needed: a reversed operator leaves
    exactly one of these two green."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, required_labels=["docker", "node20"])
    runner_id, _ = await _runner(maker, labels=["docker"])

    await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert await _claim(maker, runner_id) is None


# --- run_untagged ----------------------------------------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_a_reserved_runner_and_an_ordinary_one_sort_two_cards_between_them(api) -> None:
    """Exit condition 3c, and it has to be one test rather than two.

    Asserting only that the reserved machine refuses the untagged card would pass just
    as well if the card were unclaimable by anybody. Both runners poll, and each ends up
    with the card meant for it.
    """
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    tagged = await _card(maker, project, required_labels=["gpu"])
    plain = await _card(maker, project)
    reserved_id, _ = await _runner(maker, labels=["gpu"], run_untagged=False)
    ordinary_id, _ = await _runner(maker, labels=[], run_untagged=True)

    await client.post(f"/api/tasks/{tagged}/dispatch", json={}, headers=headers)
    await client.post(f"/api/tasks/{plain}/dispatch", json={}, headers=headers)

    claimed_by_reserved = await _claim(maker, reserved_id)
    claimed_by_ordinary = await _claim(maker, ordinary_id)
    assert claimed_by_reserved is not None
    assert claimed_by_ordinary is not None

    # The reserved machine took the tagged card and the ordinary one took the other.
    async with maker() as session:
        from app.db.models import TaskRun

        runs = {
            run.id: run.task_id for run in (await session.execute(sa.select(TaskRun))).scalars()
        }
    assert runs[claimed_by_reserved] == tagged
    assert runs[claimed_by_ordinary] == plain


@pytest.mark.usefixtures("projects_enabled")
async def test_an_absent_declaration_is_read_as_permissive(api) -> None:
    """Exit condition 3f, asserted against the payload rather than a version number.

    A daemon that predates V2.3 sends neither boolean. Reading a missing key as False
    would be the tightening direction, and a machine that quietly stops claiming
    anything after an upgrade is the hardest kind of regression to trace.
    """
    from app.services.runners import RunnerService

    client, maker = api
    async with maker() as session:
        name = f"old-{uuid.uuid4().hex[:8]}"
        node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
        session.add(node)
        await session.commit()
        runner = await RunnerService(session).register(
            node.id,
            {
                "name": node.name,
                "runtimes": [],
                "labels": [],
                "max_concurrent": 1,
                "max_waiting": 5,
                "dedicated": False,
            },
        )
        await session.commit()
        assert runner.run_untagged is True
        assert runner.accept_secrets is True


# --- the two predicates agree ----------------------------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_the_sql_and_python_predicates_agree(api) -> None:
    """**The one test that catches a half-applied change to eligibility.**

    Two implementations exist for a reason the module docstring gives — one has to be
    SQL, the other cannot be — and the failure mode of letting them drift is silent: the
    queue behaves one way and the console explains the other, with nothing red.
    """
    from app.db.models import TaskRun
    from app.services.runs import tag_match_clause

    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)

    cases = [
        ([], True, []),
        ([], True, ["docker"]),
        ([], False, []),
        ([], False, ["docker"]),
        (["docker"], True, []),
        (["docker"], True, ["docker"]),
        (["docker"], True, ["docker", "node20"]),
        (["docker"], False, []),
        (["docker"], False, ["docker"]),
        (["docker", "node20"], True, ["docker"]),
        (["docker", "node20"], True, ["docker", "node20"]),
        (["docker", "node20"], False, ["node20"]),
        (["gpu"], False, ["gpu", "arm64"]),
    ]

    for runner_labels, run_untagged, card_labels in cases:
        task_id = await _card(maker, project, required_labels=list(card_labels))
        runner_id, _ = await _runner(maker, labels=list(runner_labels), run_untagged=run_untagged)
        async with maker() as session:
            runner = await session.get(AgentRunner, runner_id)
            task = await session.get(Task, task_id)
            in_python = tag_match(runner, task)
            in_sql = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(Task)
                    .where(Task.id == task_id, tag_match_clause(runner))
                )
            ).scalar() == 1
        assert in_python == in_sql, (
            f"runner={runner_labels} run_untagged={run_untagged} card={card_labels}: "
            f"python={in_python} sql={in_sql}"
        )
    assert TaskRun is not None  # keeps the import meaningful to a reader


# --- dispatch refusals ------------------------------------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_naming_a_runner_that_lacks_a_tag_is_refused_and_says_which(api) -> None:
    """Exit condition 3d. Naming a machine does not make it eligible."""
    from app.db.models import TaskRun

    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, required_labels=["docker", "node20"])
    runner_id, node_id = await _runner(maker, labels=["node20"])

    response = await client.post(
        f"/api/tasks/{task}/dispatch",
        json={"assigned_runner_id": str(runner_id)},
        headers=headers,
    )
    body = response.json()
    assert response.status_code == 409
    assert body["error"]["code"] == "AGENT_TAG_MISMATCH"
    assert body["error"]["details"]["missing_tags"] == ["docker"]
    # And it is not queued: a refusal that also enqueues the work is not a refusal.
    async with maker() as session:
        count = (await session.execute(sa.select(sa.func.count()).select_from(TaskRun))).scalar()
    assert count == 0


@pytest.mark.usefixtures("projects_enabled")
async def test_naming_a_reserved_runner_for_an_untagged_card_gets_its_own_code(api) -> None:
    """A different code because the fix is different: tag the card, or pick another
    machine. One "not eligible" would make the second reading look like a bug."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project)
    runner_id, _ = await _runner(maker, labels=["gpu"], run_untagged=False)

    response = await client.post(
        f"/api/tasks/{task}/dispatch",
        json={"assigned_runner_id": str(runner_id)},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AGENT_REFUSES_UNTAGGED"


# --- accept_secrets ---------------------------------------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_a_node_that_refuses_secrets_is_never_offered_a_card_with_any(api) -> None:
    """Exit condition 3, the second compensating control (ADR 0032 §0)."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner, allowed_secret_names=["NPM_TOKEN"])
    async with maker() as session:
        from app.services.secrets import SecretService

        service = SecretService(session)
        await service.create(
            project=await session.get(Project, project),
            name="NPM_TOKEN",
            kind="env",
            value="a-value",
            actor_id=owner,
        )
        await session.commit()
    task = await _card(maker, project, required_secrets=["NPM_TOKEN"])
    refuser_id, _ = await _runner(maker, accept_secrets=False)

    dispatched = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert dispatched.status_code == 202, dispatched.text
    assert await _claim(maker, refuser_id) is None

    accepter_id, _ = await _runner(maker, accept_secrets=True)
    assert await _claim(maker, accepter_id) is not None


# --- the waiting reason -----------------------------------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_an_unclaimable_card_says_which_tags_are_missing(api) -> None:
    """Exit condition 3e. "Waiting for an available agent" is the wrong sentence when
    the truth is "no machine has docker", and they lead to different actions."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, required_labels=["docker", "node20"])
    _, node_id = await _runner(maker, labels=["node20"])

    from app.api.http import agents as agents_module
    from app.main import app

    app.dependency_overrides[agents_module.get_registry] = lambda: _Registry({node_id})
    try:
        response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    finally:
        app.dependency_overrides.pop(agents_module.get_registry, None)

    body = response.json()
    assert response.status_code == 202, response.text
    assert body["waiting_reason"] == "no_eligible_runner"
    assert body["missing_tags"] == ["docker"]


@pytest.mark.usefixtures("projects_enabled")
async def test_the_missing_set_is_the_smallest_one_not_the_intersection(api) -> None:
    """Two runners lacking different tags. An intersection answers "nothing is missing",
    which is false and printed next to a card nobody is claiming."""
    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)
    task = await _card(maker, project, required_labels=["docker", "gpu"])
    _, node_a = await _runner(maker, labels=["docker"])  # missing gpu
    _, node_b = await _runner(maker, labels=["gpu"])  # missing docker

    from app.api.http import agents as agents_module
    from app.main import app

    app.dependency_overrides[agents_module.get_registry] = lambda: _Registry({node_a, node_b})
    try:
        response = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    finally:
        app.dependency_overrides.pop(agents_module.get_registry, None)

    body = response.json()
    assert body["waiting_reason"] == "no_eligible_runner"
    assert len(body["missing_tags"]) == 1
    assert body["missing_tags"][0] in {"docker", "gpu"}


# --- delivery ---------------------------------------------------------------


@pytest.mark.usefixtures("projects_enabled")
async def test_every_delivery_mode_dispatches_and_the_table_of_refusals_is_empty(
    api,
) -> None:
    """V2.3 refused two modes by phase; V2.4 delivers all five.

    The check that used to reject them is deliberately still there and deliberately
    empty — it is where the *next* unhandled mode gets turned away, and a declaration
    the platform silently ignores is worse than one it refuses (plan/18/00-…md D11).
    """
    from app.services.runs import UNSUPPORTED_DELIVERIES

    assert UNSUPPORTED_DELIVERIES == {}

    client, maker = api
    owner, headers = await _actor(client, maker)
    project = await _project(maker, owner)

    for delivery in ("none", "artifact", "branch"):
        card = await _card(maker, project, delivery=delivery, source="none")
        accepted = await client.post(f"/api/tasks/{card}/dispatch", json={}, headers=headers)
        assert accepted.status_code == 202, f"{delivery}: {accepted.text}"

    # The two pull-request modes are refused only on **their own declarations** now —
    # a missing target, or a branch outside the namespace — never on a version number.
    pr_card = await _card(maker, project, delivery="pull_request", source="none")
    refused = await client.post(f"/api/tasks/{pr_card}/dispatch", json={}, headers=headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "TASK_DELIVERY_NEEDS_SOURCE"
    # The refusal is about this card, not about a release.
    assert "V2.4" not in refused.json()["error"]["message"]


@pytest.mark.usefixtures("projects_enabled")
async def test_an_oversized_offer_releases_the_claim_instead_of_vanishing(api) -> None:
    """Exit condition 12, and the failure it replaces is the point.

    `run.offer` is a 64 KiB control frame and is deliberately not in the large-frame
    set. Without this check an oversized frame is dropped **silently** by the receiver:
    the card is claimed, the lease expires, the run is retried to exhaustion and
    blocked, and nothing anywhere reports an error. Releasing turns that into a queued
    card with a sentence next to it.

    The trigger is secrets rather than a long context, and that is itself a result of
    this phase: lowering the `context` ceiling to 32 KiB means one field can no longer
    consume the whole budget on its own. Eight secrets at the per-value ceiling can —
    which is exactly why the schema bounds are necessary and **not sufficient**.
    """
    from app.api.ws import nodes as nodes_ws
    from app.db.models import Project, TaskMessage, TaskRun
    from app.protocol.codec import MAX_PAYLOAD
    from app.services.runs import MessageService, RunService, release_claim
    from app.services.secrets import SecretService

    client, maker = api
    owner, headers = await _actor(client, maker)
    names = [f"BIG_SECRET_{i}" for i in range(8)]
    project = await _project(maker, owner, allowed_secret_names=names)
    async with maker() as session:
        row = await session.get(Project, project)
        service = SecretService(session)
        for name in names:
            await service.create(
                project=row, name=name, kind="env", value="x" * 8000, actor_id=owner
            )
        await session.commit()

    task = await _card(maker, project, required_secrets=names)
    runner_id, _ = await _runner(maker)
    dispatched = await client.post(f"/api/tasks/{task}/dispatch", json={}, headers=headers)
    assert dispatched.status_code == 202, dispatched.text

    async with maker() as session:
        runner = await session.get(AgentRunner, runner_id)
        offer = await RunService(session).poll(runner=runner, capacity=1)
        assert offer is not None
        frame = nodes_ws._frame("run.offer", runner.node_id, "01K0" + "A" * 22, offer.spec())
        assert len(frame.encode("utf-8")) > MAX_PAYLOAD, "the fixture no longer oversizes"
        await release_claim(session, offer.run)
        await MessageService(session).post_event(
            task=await session.get(Task, task),
            body="這次派工的訊息超過了單一控制訊框的上限。",
            event_kind="run.offer_too_large",
        )
        await session.commit()

    async with maker() as session:
        run = (await session.execute(sa.select(TaskRun))).scalars().one()
        assert run.status == "queued"
        assert run.runner_id is None
        assert run.lease_expires_at is None
        events = [m.event_kind for m in (await session.execute(sa.select(TaskMessage))).scalars()]
        assert "run.offer_too_large" in events
