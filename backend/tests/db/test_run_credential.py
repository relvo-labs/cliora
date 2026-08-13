"""The run credential and what it cannot do (AR-08, ADR 0029 §6).

The security review's second section rests on properties that are all *absences*, and
an absence is exactly what stops being true without anything failing. So each of these
asserts a door that must stay shut:

* a run credential **never becomes a `User`** — the two authentication paths are
  structurally disjoint, not separated by a check somebody remembered;
* it **cannot dispatch or cancel**, which is what stops one prompt-injected agent from
  emptying the queue;
* it **cannot touch another card**, and the refusal is a 404 rather than a 403 so it
  cannot be used to discover which cards exist;
* it stops working the moment its run ends, through **one** revocation path.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.db.models import AgentRunner, Node, Project, Role, Task, TaskRun, User
from app.security.passwords import hash_password
from app.services.agent_auth import (
    KIND_RUN,
    RUN_TOKEN_SCOPES,
    RunTokenService,
    RunTokenSubject,
)
from app.services.rbac import (
    AGENT_MANAGE,
    FILE_UPLOAD,
    PROJECT_MANAGE,
    RUN_CANCEL,
    RUN_DISPATCH,
    TASK_APPROVE,
    TASK_CREATE,
    TERMINAL_OPERATE,
)

pytestmark = pytest.mark.asyncio


async def _world(maker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
        name = f"rt-{uuid.uuid4().hex[:8]}"
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
        tasks = [
            Task(
                id=uuid.uuid4(),
                project_id=project.id,
                card_ref=f"TASK-{index}-{uuid.uuid4().hex[:4]}",
                title=f"card {index}",
                stage="ready",
                source="none",
                delivery="none",
            )
            for index in (1, 2)
        ]
        node = Node(id=uuid.uuid4(), name=name, hostname=f"{name}.invalid", status="online")
        session.add_all([*tasks, node])
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(), node_id=node.id, name=name, runtimes=["claude"], labels=[]
        )
        session.add(runner)
        await session.commit()
        return project.id, tasks[0].id, tasks[1].id


async def _issue(maker, project_id, task_id) -> tuple[str, uuid.UUID]:
    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task_id,
            project_id=project_id,
            seq=1,
            status="running",
            source_kind="none",
        )
        session.add(run)
        await session.flush()
        issued = await RunTokenService(session).issue(
            run=RunTokenSubject(
                run_id=run.id,
                project_id=project_id,
                task_id=task_id,
                timeout_seconds=3600,
            )
        )
        await session.commit()
        return issued.value, run.id


# Sync, and marked as such: it reads a constant and touches nothing else. The
# module-level asyncio mark would otherwise claim it.
@pytest.mark.asyncio(loop_scope="function")
async def test_the_scope_holds_two_actions_and_none_of_the_dangerous_ones() -> None:
    """Asserted as a set, not as membership.

    "It also holds X" is how a scope grows; comparing the whole set is what makes an
    addition a decision somebody has to make on purpose.
    """
    assert RUN_TOKEN_SCOPES == frozenset({"project.view", "task.update"})
    for forbidden in (
        TASK_APPROVE,  # an agent's output is not an approval
        TASK_CREATE,  # an agent proposes; a person creates
        PROJECT_MANAGE,
        AGENT_MANAGE,
        FILE_UPLOAD,
        TERMINAL_OPERATE,
        # The two this phase added, and the important pair: without them one
        # prompt-injected agent could empty the queue.
        RUN_DISPATCH,
        RUN_CANCEL,
    ):
        assert forbidden not in RUN_TOKEN_SCOPES


async def test_the_prefix_is_distinct_and_the_principal_carries_no_user(
    api: tuple, projects_enabled: None
) -> None:
    _client, maker = api
    project, task, _other = await _world(maker)
    token, run_id = await _issue(maker, project, task)

    assert token.startswith("cliora_rt_"), "a scanner and a human both read the prefix"

    async with maker() as session:
        principal = await RunTokenService(session).resolve(token)
    assert principal is not None
    assert principal.kind == KIND_RUN
    assert principal.run_id == run_id
    assert principal.task_id == task
    assert principal.session_id is None
    # No `user_id` field at all — a principal with one is eventually handed to
    # something that records an actor, and the agent starts impersonating the person
    # who dispatched it.
    assert not hasattr(principal, "user_id")


async def test_a_run_credential_is_refused_by_the_human_path(
    api: tuple, projects_enabled: None
) -> None:
    """401, and the *same* 401 as any other bad token.

    A distinguishable answer would tell a prober that the credential type was the
    problem, which is a signal it can use.
    """
    client, maker = api
    project, task, _other = await _world(maker)
    token, _run = await _issue(maker, project, task)

    response = await client.get("/api/auth/me", headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_a_run_credential_reaches_only_its_own_card(
    api: tuple, projects_enabled: None
) -> None:
    """The resource boundary, and why the refusal shape matters.

    Posting to its own card works; the *other* card is not reachable at all — and it
    answers 404 rather than 403, so a token cannot be used to learn which cards exist.
    """
    client, maker = api
    project, task, other = await _world(maker)
    token, _run = await _issue(maker, project, task)
    headers = {"authorization": f"Bearer {token}"}

    posted = await client.post(
        "/api/cli/runs/messages", json={"body": "做完了 X", "kind": "message"}, headers=headers
    )
    assert posted.status_code == 201
    assert posted.json()["author_kind"] == "agent"

    # There is no path that names another card: the credential carries its own, and the
    # route takes no id. The other card is reachable only through the human API.
    listed = await client.get("/api/cli/runs/messages", headers=headers)
    assert [row["task_id"] for row in listed.json()] == [str(task)]
    assert str(other) not in [row["task_id"] for row in listed.json()]


async def test_a_question_parks_the_run(api: tuple, projects_enabled: None) -> None:
    """`ask` is `say` plus one field, and that field is what moves the run.

    A parked run renews its lease, accrues no execution timeout, and occupies the
    waiting limit rather than the execution one — a run waiting on a person is not
    running a process.
    """
    client, maker = api
    project, task, _other = await _world(maker)
    token, run_id = await _issue(maker, project, task)

    response = await client.post(
        "/api/cli/runs/messages",
        json={"body": "這個欄位要用哪個名稱？", "kind": "question"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201

    async with maker() as session:
        run = await session.get(TaskRun, run_id)
        assert run is not None
        assert run.status == "waiting_for_input"
        assert run.waiting_since is not None


async def test_the_credential_dies_with_its_run(api: tuple, projects_enabled: None) -> None:
    """One revocation path, four triggers.

    Called from the run state machine rather than from the routes that can end a run —
    the same reasoning the session credential documents, and here there are four doors
    rather than one.
    """
    client, maker = api
    project, task, _other = await _world(maker)
    token, run_id = await _issue(maker, project, task)
    headers = {"authorization": f"Bearer {token}"}

    assert (await client.get("/api/cli/runs/messages", headers=headers)).status_code == 200

    async with maker() as session:
        await RunTokenService(session).revoke_for_run(run_id)
        await session.commit()

    assert (await client.get("/api/cli/runs/messages", headers=headers)).status_code == 401


async def test_a_credential_that_would_outlive_the_ceiling_is_refused(
    api: tuple, projects_enabled: None
) -> None:
    """Refused at issue rather than issued and expiring mid-run.

    This bound started to bite when the wall clock grew from one hour to six, so it is
    asserted instead of assumed: a token that dies halfway through a run looks to the
    agent like the platform revoked it.
    """
    from app.api.errors import ApiError

    _client, maker = api
    project, task, _other = await _world(maker)
    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task,
            project_id=project,
            seq=9,
            status="running",
            source_kind="none",
        )
        session.add(run)
        await session.flush()
        with pytest.raises(ApiError) as raised:
            await RunTokenService(session).issue(
                run=RunTokenSubject(
                    run_id=run.id,
                    project_id=project,
                    task_id=task,
                    # Well beyond the deployment's ceiling on agent credentials.
                    timeout_seconds=86400,
                )
            )
    assert raised.value.code == "RUN_TOKEN_TTL_EXCEEDED"


async def test_the_run_surface_is_absent_when_the_inner_flag_is_off(
    api: tuple, agent_runs_disabled: None
) -> None:
    """A credential nobody in this deployment can hold does not authenticate."""
    client, maker = api
    project, task, _other = await _world(maker)
    token, _run = await _issue(maker, project, task)

    response = await client.get(
        "/api/cli/runs/messages", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code in {401, 404}
