"""V2.5: the agent's side of the requirement flow (RQ-03…RQ-08, ADR 0034).

The phase adds no outward surface, no execution capability and no credential, so what
these tests defend is **semantic**: that something an agent wrote never reads as
something a person decided.

Three groups, in the order the risk runs:

1. **dispatch refuses the wrong card** — before a run exists, so the refusal costs
   nothing;
2. **a run may write proposals and never facts** — the two new routes, their resource
   boundary, and the three "who decided" columns that stay NULL;
3. **the human gates keep their teeth** — a rejection carries a reason, an override
   cannot reach `readiness`, and a dependency on an unselected item does not silently
   disappear.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import (
    AgentRunner,
    DocumentPatchProposal,
    Node,
    Requirement,
    Role,
    Task,
    TaskDependency,
    TaskMessage,
    TaskProposal,
    TaskRun,
    User,
)
from app.security.passwords import hash_password
from app.services.agent_auth import RunTokenService, RunTokenSubject

pytestmark = pytest.mark.asyncio

READINESS_FULL = {
    "problem_stated": True,
    "acceptance_criteria": True,
    "scope_bounded": True,
    "dependencies_known": True,
    "verification_defined": True,
    "risk_assessed": True,
    "context_pointers": True,
}


def _task_item(item_id: str, **overrides: object) -> dict:
    item: dict = {
        "id": item_id,
        "title": f"card {item_id}",
        "readiness": dict(READINESS_FULL),
        "source": "repo",
        "delivery": "artifact",
    }
    item.update(overrides)
    return item


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str = "Admin"
) -> tuple[uuid.UUID, dict[str, str]]:
    username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password("pw"),
            display_name=username,
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        user_id = user.id
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.post(
        "/api/projects", json={"name": f"proj-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _requirement(client: AsyncClient, headers: dict[str, str], project_id: str) -> dict:
    resp = await client.post(
        f"/api/projects/{project_id}/requirements",
        json={"raw_text": "使用者反映報表匯出很慢，想辦法改善"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _card(
    maker: async_sessionmaker,
    project_id: uuid.UUID,
    *,
    kind: str,
    requirement_id: uuid.UUID | None,
    delivery: str = "artifact",
    source: str = "repo",
    secrets: list[str] | None = None,
) -> uuid.UUID:
    async with maker() as session:
        task = Task(
            id=uuid.uuid4(),
            project_id=project_id,
            card_ref=f"TASK-{uuid.uuid4().hex[:6]}",
            title="clarify the requirement",
            stage="ready",
            card_kind=kind,
            source=source,
            delivery=delivery,
            required_secrets=secrets or [],
            requirement_id=requirement_id,
        )
        session.add(task)
        await session.commit()
        return task.id


async def _run_token(
    maker: async_sessionmaker, project_id: uuid.UUID, task_id: uuid.UUID
) -> tuple[dict[str, str], uuid.UUID]:
    async with maker() as session:
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task_id,
            project_id=project_id,
            seq=1,
            status="running",
            source_kind="repo",
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
        return {"Authorization": f"Bearer {issued.value}"}, run.id


async def _approve(client: AsyncClient, headers: dict[str, str], requirement_id: str) -> None:
    resp = await client.post(
        f"/api/requirements/{requirement_id}/specs",
        json={"objective": "faster export"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    resp = await client.post(f"/api/requirements/{requirement_id}/approve", headers=headers)
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------- #
# 1. Dispatch refuses the wrong card, before a run exists
# --------------------------------------------------------------------------- #


async def test_a_clarification_card_declaring_a_secret_is_refused_at_dispatch(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 7.

    And the message matters as much as the refusal: it has to send the reader to the
    card's own field, not to the project's allowlist — which is where a plain "that name
    is not allowed" would send them, to add a name that must not be used at all.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
        secrets=["DB_PASSWORD"],
    )
    resp = await client.post(f"/api/tasks/{task_id}/dispatch", json={}, headers=headers)
    assert resp.status_code == 409, resp.text
    body = resp.json()["error"]
    assert body["code"] == "TASK_KIND_FORBIDS_SECRETS"
    assert "DB_PASSWORD" in body["details"]["required_secrets"]
    assert "允許清單" in body["message"]


async def test_a_clarification_card_cannot_deliver_a_pull_request(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
        delivery="pull_request",
    )
    resp = await client.post(f"/api/tasks/{task_id}/dispatch", json={}, headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "TASK_KIND_DELIVERY_NOT_ALLOWED"


async def test_a_clarification_card_with_no_requirement_is_refused(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    task_id = await _card(
        maker, uuid.UUID(project["id"]), kind="clarification", requirement_id=None
    )
    resp = await client.post(f"/api/tasks/{task_id}/dispatch", json={}, headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "TASK_KIND_NEEDS_REQUIREMENT"


async def test_a_mockup_card_is_refused_while_the_tunnel_integration_is_off(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 11, third item — and the message carries the fourth.

    A refusal that only says "no" reads as "UI work is blocked on this deployment",
    which is the opposite of what D31 decided.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    task_id = await _card(maker, uuid.UUID(project["id"]), kind="mockup", requirement_id=None)
    resp = await client.post(f"/api/tasks/{task_id}/dispatch", json={}, headers=headers)
    assert resp.status_code == 409, resp.text
    body = resp.json()["error"]
    assert body["code"] == "TASK_MOCKUP_INTEGRATION_DISABLED"
    assert "一般的 UI 實作卡不受影響" in body["message"]


async def test_an_ordinary_implementation_card_is_unaffected_by_the_mockup_rule(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 11, fourth item.

    This passes today. Writing it down is the point: it turns red the day somebody makes
    the `ui` gate unconditional, and nothing else would.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="implementation",
        requirement_id=None,
        delivery="none",
        source="none",
    )
    resp = await client.post(f"/api/tasks/{task_id}/dispatch", json={}, headers=headers)
    # 202 rather than 201: nothing is online to claim it, which is the queue working
    # rather than the card being refused. The claim here is only that the mockup rule
    # did not reach it.
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "queued"


async def test_a_card_kind_is_fixed_once_the_card_has_been_run(
    api: tuple, projects_enabled: None
) -> None:
    """ "Ever run", not "currently running".

    A finished clarification card that became an implementation card would still carry
    its specification versions and question thread, and an auditor would see an
    implementation card that inexplicably produced a specification.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    resp = await client.get(f"/api/tasks/{task_id}", headers=headers)
    version = resp.json()["version"]
    # Before any run: the correction is allowed.
    resp = await client.patch(
        f"/api/tasks/{task_id}",
        json={"card_kind": "implementation", "version": version},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    await _run_token(maker, uuid.UUID(project["id"]), task_id)
    resp = await client.get(f"/api/tasks/{task_id}", headers=headers)
    version = resp.json()["version"]
    resp = await client.patch(
        f"/api/tasks/{task_id}",
        json={"card_kind": "clarification", "version": version},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "TASK_KIND_LOCKED"


# --------------------------------------------------------------------------- #
# 2. A run writes proposals, never facts
# --------------------------------------------------------------------------- #


async def test_a_run_submits_a_spec_version_authored_by_a_runner_not_a_person(
    api: tuple, projects_enabled: None
) -> None:
    """`authored_by` stays NULL and `authored_by_kind` says `runner`.

    The column exists so a NULL author does not have to mean two things, and this is the
    writer it was added for — `AgentPrincipal` carries no `user_id` on purpose.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, run_id = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    resp = await client.post(
        "/api/cli/runs/spec",
        json={
            "objective": "把匯出時間壓到 5 秒內",
            "sections": {"user_stories": [{"title": "選擇匯出格式"}]},
            "open_questions": [{"id": "q1", "question": "CSV 還是 PDF？"}],
        },
        headers=agent,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["authored_by_kind"] == "runner"
    assert body["authored_by"] is None
    assert body["run_id"] == str(run_id)
    assert body["sections"]["user_stories"][0]["title"] == "選擇匯出格式"


async def test_a_run_cannot_approve_the_specification_it_wrote(
    api: tuple, projects_enabled: None
) -> None:
    """**401, not 403.**

    403 would mean "we recognise you and refuse"; the truth is that the human routes do
    not accept this kind of credential at all. The two authentication dependencies are
    structurally disjoint, and asserting 401 is what keeps that structural.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    for method, path in (
        ("post", f"/api/requirements/{requirement['id']}/approve"),
        ("post", f"/api/requirements/{requirement['id']}/proposals"),
    ):
        resp = await getattr(client, method)(path, json={"tree": {}}, headers=agent)
        assert resp.status_code == 401, f"{path}: {resp.text}"

    async with maker() as session:
        row = (
            await session.execute(
                sa.select(Requirement).where(Requirement.id == uuid.UUID(requirement["id"]))
            )
        ).scalar_one()
        assert row.approved_by is None
        assert row.status != "approved"


async def test_a_second_question_is_refused_while_the_first_is_unanswered(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 15. Enforced by the server, because the agent has `curl`."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    first = await client.post(
        "/api/cli/runs/messages",
        json={"body": "報表匯出是指 CSV 還是 PDF？", "kind": "question"},
        headers=agent,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/cli/runs/messages",
        json={"body": "可接受的秒數是多少？", "kind": "question"},
        headers=agent,
    )
    assert second.status_code == 409, second.text
    body = second.json()["error"]
    assert body["code"] == "QUESTION_ALREADY_PENDING"
    assert "CSV" in body["details"]["pending_question"]

    # A plain message from a person counts as an answer: people reply by typing, not by
    # pressing a labelled button.
    reply = await client.post(
        f"/api/tasks/{task_id}/messages", json={"body": "CSV"}, headers=headers
    )
    assert reply.status_code == 201, reply.text
    third = await client.post(
        "/api/cli/runs/messages",
        json={"body": "可接受的秒數是多少？", "kind": "question"},
        headers=agent,
    )
    assert third.status_code == 201, third.text


async def test_a_system_message_does_not_unblock_questioning(
    api: tuple, projects_enabled: None
) -> None:
    """Otherwise the 24-hour timeout notice would itself grant another question —
    precisely backwards."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, run_id = await _run_token(maker, uuid.UUID(project["id"]), task_id)
    assert (
        await client.post(
            "/api/cli/runs/messages",
            json={"body": "一個問題", "kind": "question"},
            headers=agent,
        )
    ).status_code == 201

    async with maker() as session:
        session.add(
            TaskMessage(
                id=uuid.uuid4(),
                task_id=task_id,
                run_id=run_id,
                author_kind="system",
                body="租約已續",
                kind="event",
                event_kind="run.waiting_timeout",
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/cli/runs/messages", json={"body": "第二個問題", "kind": "question"}, headers=agent
    )
    assert resp.status_code == 409, resp.text


async def test_a_decomposition_run_may_only_propose_for_its_own_requirement(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 17.

    This is the reason the existing human route was not relaxed: its `requirement_id`
    comes from the URL, and nothing there binds it to the caller. Here the requirement
    is derived from `principal.task_id`, so "another requirement" is not expressible.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    mine = await _requirement(client, headers, project["id"])
    other = await _requirement(client, headers, project["id"])
    await _approve(client, headers, mine["id"])
    await _approve(client, headers, other["id"])

    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="decomposition",
        requirement_id=uuid.UUID(mine["id"]),
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    resp = await client.post(
        "/api/cli/runs/proposal", json={"tree": {"tasks": [_task_item("t1")]}}, headers=agent
    )
    assert resp.status_code == 201, resp.text

    # There is no way to name the other requirement at all — the only route that takes
    # one is the human one, and that refuses this credential outright.
    resp = await client.post(
        f"/api/requirements/{other['id']}/proposals",
        json={"tree": {"tasks": []}},
        headers=agent,
    )
    assert resp.status_code == 401, resp.text
    async with maker() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(TaskProposal)
            .where(TaskProposal.requirement_id == uuid.UUID(other["id"]))
        )
        assert count == 0


async def test_a_clarification_run_cannot_use_the_proposal_route(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)
    resp = await client.post("/api/cli/runs/proposal", json={"tree": {}}, headers=agent)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "TASK_KIND_MISMATCH"


async def test_the_proposal_tree_is_validated_at_submission(
    api: tuple, projects_enabled: None
) -> None:
    """Four of the six checks, and each names what it found.

    At submission rather than at acceptance: a cycle among items nobody selected would
    otherwise surface at some later partial acceptance, long after the run is gone.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await _approve(client, headers, requirement["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="decomposition",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    async def submit(tree: dict) -> tuple[int, dict]:
        resp = await client.post("/api/cli/runs/proposal", json={"tree": tree}, headers=agent)
        return resp.status_code, resp.json()

    code, body = await submit({"tasks": []})
    assert (code, body["error"]["code"]) == (422, "PROPOSAL_EMPTY")

    code, body = await submit(
        {"tasks": [_task_item("a", depends_on=["b"]), _task_item("b", depends_on=["a"])]}
    )
    assert (code, body["error"]["code"]) == (422, "PROPOSAL_TREE_CYCLE")
    assert len(body["error"]["details"]["cycle"]) >= 3

    code, body = await submit({"tasks": [_task_item("a", required_secrets=["X"])]})
    assert (code, body["error"]["code"]) == (422, "PROPOSAL_FIELD_FORBIDDEN")

    code, body = await submit(
        {"tasks": [_task_item("a", title="rotate the deploy token", risk="low")]}
    )
    assert (code, body["error"]["code"]) == (422, "PROPOSAL_RISK_UNDERSTATED")
    assert body["error"]["details"]["terms"]

    # And the same card, honestly labelled, is accepted.
    code, _ = await submit(
        {"tasks": [_task_item("a", title="rotate the deploy token", risk="high")]}
    )
    assert code == 201


async def test_a_specification_question_cannot_be_answered_and_deferred_at_once(
    api: tuple, projects_enabled: None
) -> None:
    """Either resolves it for the approval gate, so both lights the button while hiding
    which state it is in — and those two states are what a reviewer needs to tell
    apart."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/specs",
        json={
            "objective": "x",
            "open_questions": [
                {"id": "q1", "question": "CSV?", "answer": "yes", "resolved_as": "known unknown"}
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "SPEC_QUESTION_AMBIGUOUS"


async def test_an_unknown_specification_section_is_named_not_dropped(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/specs",
        json={"objective": "x", "sections": {"userStories": []}},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()["error"]
    assert body["code"] == "SPEC_SECTION_UNKNOWN"
    assert "userStories" in body["details"]["unknown"]
    assert "user_stories" in body["details"]["allowed"]


# --------------------------------------------------------------------------- #
# 3. The human gates keep their teeth
# --------------------------------------------------------------------------- #


async def test_rejecting_a_proposal_requires_a_reason_and_keeps_it(
    api: tuple, projects_enabled: None
) -> None:
    """The reason is the only signal that accumulates on this path."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await _approve(client, headers, requirement["id"])
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/proposals",
        json={"tree": {"tasks": [_task_item("t1")]}},
        headers=headers,
    )
    proposal_id = resp.json()["id"]

    blank = await client.post(
        f"/api/proposals/{proposal_id}/reject", json={"note": "   "}, headers=headers
    )
    assert blank.status_code == 422, blank.text
    assert blank.json()["error"]["code"] == "PROPOSAL_REJECT_NEEDS_NOTE"

    ok = await client.post(
        f"/api/proposals/{proposal_id}/reject",
        json={"note": "這批卡太細，一個 endpoint 拆成三張"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "rejected"
    assert "太細" in ok.json()["decision_note"]


async def test_an_override_cannot_reach_readiness_and_cannot_touch_an_unselected_item(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 19.

    `readiness` is excluded so that "a card missing readiness lands in `backlog`" cannot
    be ticked away; an unselected item is excluded so that an edit is never applied
    silently at some later acceptance.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await _approve(client, headers, requirement["id"])
    tree = {"tasks": [_task_item("t1"), _task_item("t2", readiness={"problem_stated": True})]}
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/proposals", json={"tree": tree}, headers=headers
    )
    proposal_id = resp.json()["id"]

    bad = await client.post(
        f"/api/proposals/{proposal_id}/accept",
        json={"accept_ids": ["t2"], "overrides": {"t2": {"readiness": READINESS_FULL}}},
        headers=headers,
    )
    assert bad.status_code == 422, bad.text
    assert bad.json()["error"]["code"] == "PROPOSAL_OVERRIDE_NOT_ACCEPTED"

    unselected = await client.post(
        f"/api/proposals/{proposal_id}/accept",
        json={"accept_ids": ["t1"], "overrides": {"t2": {"risk": "high"}}},
        headers=headers,
    )
    assert unselected.status_code == 422, unselected.text
    assert unselected.json()["error"]["code"] == "PROPOSAL_OVERRIDE_NOT_ACCEPTED"

    good = await client.post(
        f"/api/proposals/{proposal_id}/accept",
        json={"accept_ids": ["t1"], "overrides": {"t1": {"delivery": "artifact"}}},
        headers=headers,
    )
    assert good.status_code == 200, good.text
    assert good.json()["created"][0]["delivery"] == "artifact"


async def test_a_dependency_on_an_unaccepted_item_is_reported_and_lands_the_card_in_backlog(
    api: tuple, projects_enabled: None
) -> None:
    """Exit condition 18 — the格 easiest to get wrong.

    The two instincts are both wrong: creating the row is impossible (that card does not
    exist), and skipping it silently leaves a card asserting `dependencies_known` while
    the database holds none.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await _approve(client, headers, requirement["id"])
    tree = {"tasks": [_task_item("base"), _task_item("dependent", depends_on=["base"])]}
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/proposals", json={"tree": tree}, headers=headers
    )
    proposal_id = resp.json()["id"]

    resp = await client.post(
        f"/api/proposals/{proposal_id}/accept",
        json={"accept_ids": ["dependent"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    card = body["created"][0]
    assert card["stage"] == "backlog"
    assert body["unresolved_dependencies"][card["card_ref"]] == ["base"]
    assert "dependencies_known" in body["incomplete"][card["card_ref"]]

    async with maker() as session:
        rows = (
            await session.execute(
                sa.select(TaskDependency).where(TaskDependency.task_id == uuid.UUID(card["id"]))
            )
        ).scalars()
        assert list(rows) == []


async def test_accepting_both_ends_writes_the_dependency(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await _approve(client, headers, requirement["id"])
    tree = {"tasks": [_task_item("base"), _task_item("dependent", depends_on=["base"])]}
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/proposals", json={"tree": tree}, headers=headers
    )
    proposal_id = resp.json()["id"]
    resp = await client.post(f"/api/proposals/{proposal_id}/accept", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["unresolved_dependencies"] == {}
    async with maker() as session:
        count = await session.scalar(sa.select(sa.func.count()).select_from(TaskDependency))
        assert count == 1


async def test_a_partly_accepted_proposal_says_what_remains(
    api: tuple, projects_enabled: None
) -> None:
    """ "Remaining" and "rejected" must not look alike: the rest is still *available*,
    and a screen that cannot tell them apart makes people think it was decided."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await _approve(client, headers, requirement["id"])
    tree = {"tasks": [_task_item("t1"), _task_item("t2"), _task_item("t3")]}
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/proposals", json={"tree": tree}, headers=headers
    )
    proposal_id = resp.json()["id"]
    resp = await client.post(
        f"/api/proposals/{proposal_id}/accept", json={"accept_ids": ["t1"]}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    detail = await client.get(f"/api/requirements/{requirement['id']}", headers=headers)
    proposal = detail.json()["proposals"][0]
    assert proposal["status"] == "partially_accepted"
    assert proposal["accepted_item_ids"] == ["t1"]
    assert proposal["remaining_item_ids"] == ["t2", "t3"]


# --------------------------------------------------------------------------- #
# 4. Document patch proposals: rendered, recorded, never applied
# --------------------------------------------------------------------------- #


async def test_a_run_proposes_a_patch_and_only_a_person_decides_it(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    # No requirement and an ordinary implementation card: a document is most often
    # found to be wrong by the card that ran into it.
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="implementation",
        requirement_id=None,
        delivery="none",
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    resp = await client.post(
        "/api/cli/runs/patch-proposal",
        json={
            "target_path": "docs/prd.md",
            "diff": "--- a/docs/prd.md\n+++ b/docs/prd.md\n@@\n-old\n+new\n",
            "sections": {"modified_sections": ["§8.4"]},
            "reason": "程式碼與描述不符",
        },
        headers=agent,
    )
    assert resp.status_code == 201, resp.text
    proposal_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    # The agent cannot decide it: that route belongs to the human dependency.
    denied = await client.post(f"/api/patch-proposals/{proposal_id}/accept", json={}, headers=agent)
    assert denied.status_code == 401, denied.text

    accepted = await client.post(
        f"/api/patch-proposals/{proposal_id}/accept", json={}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"

    async with maker() as session:
        row = (
            await session.execute(
                sa.select(DocumentPatchProposal).where(
                    DocumentPatchProposal.id == uuid.UUID(proposal_id)
                )
            )
        ).scalar_one()
        assert row.decided_by is not None
        # Accepting creates nothing — not even a card.
        cards = await session.scalar(
            sa.select(sa.func.count())
            .select_from(Task)
            .where(Task.project_id == uuid.UUID(project["id"]))
        )
        assert cards == 1  # only the one this test made


async def test_a_patch_proposal_refuses_an_escaping_target_path(
    api: tuple, projects_enabled: None
) -> None:
    """The platform never opens this file. The check is so a review screen never renders
    something shaped like an attack."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="implementation",
        requirement_id=None,
        delivery="none",
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)
    for path in ("../../etc/passwd", "/etc/passwd"):
        resp = await client.post(
            "/api/cli/runs/patch-proposal",
            json={"target_path": path, "diff": "x"},
            headers=agent,
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "PATCH_PROPOSAL_TARGET_INVALID"


async def test_rejecting_a_patch_proposal_requires_a_reason(
    api: tuple, projects_enabled: None
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="implementation",
        requirement_id=None,
        delivery="none",
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)
    created = await client.post(
        "/api/cli/runs/patch-proposal",
        json={"target_path": "docs/prd.md", "diff": "x"},
        headers=agent,
    )
    proposal_id = created.json()["id"]
    blank = await client.post(
        f"/api/patch-proposals/{proposal_id}/reject", json={}, headers=headers
    )
    assert blank.status_code == 422, blank.text
    assert blank.json()["error"]["code"] == "PATCH_PROPOSAL_REJECT_NEEDS_NOTE"


# --------------------------------------------------------------------------- #
# 5. The three "who decided" columns are unreachable from a run
# --------------------------------------------------------------------------- #


async def test_no_agent_reachable_route_ever_writes_a_decider(
    api: tuple, projects_enabled: None
) -> None:
    """`GATE-RQ-HUMAN-ACTOR`'s dynamic half, in test form.

    Every route the application mounts, walked with a run credential. The route list is
    read from `app.routes` rather than written down, so a route added next phase is
    covered without anybody remembering to add it here — which is the failure mode this
    is really guarding against.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
    )
    agent, _ = await _run_token(maker, uuid.UUID(project["id"]), task_id)

    from app.main import app

    ids = {
        "project_id": project["id"],
        "requirement_id": requirement["id"],
        "task_id": str(task_id),
        "proposal_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "id": str(uuid.uuid4()),
    }
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/"):
            continue
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            concrete = path
            for name, value in ids.items():
                concrete = concrete.replace("{" + name + "}", value)
            if "{" in concrete:
                continue
            try:
                await client.request(method, concrete, json={}, headers=agent)
            except Exception:  # noqa: BLE001 - a handler raising is not this test's claim
                continue

    async with maker() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Requirement)
                .where(Requirement.approved_by.is_not(None))
            )
            == 0
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(TaskProposal)
                .where(TaskProposal.decided_by.is_not(None))
            )
            == 0
        )
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(DocumentPatchProposal)
                .where(DocumentPatchProposal.decided_by.is_not(None))
            )
            == 0
        )


# --------------------------------------------------------------------------- #
# 6. The context packs
# --------------------------------------------------------------------------- #


async def test_the_clarification_pack_never_mentions_secrets_and_fits_the_budget(
    api: tuple, projects_enabled: None
) -> None:
    """The pack an agent is started with, rendered directly.

    Two claims: it stays inside the layered budget even with a long requirement and a
    full draft, and it contains no "environment variables available to this run"
    section — which would be a false sentence, because this kind of card is refused
    secrets at dispatch.
    """
    from app.db.models import FeatureSpec
    from app.services.runs import CONTEXT_BUDGET_BYTES, render_clarification_context

    task = Task(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        card_ref="TASK-1",
        title="clarify",
        card_kind="clarification",
    )
    requirement = Requirement(
        id=uuid.uuid4(),
        project_id=task.project_id,
        card_ref="REQ-1",
        raw_text="很慢" * 4000,
    )
    spec = FeatureSpec(
        id=uuid.uuid4(),
        requirement_id=requirement.id,
        seq=2,
        objective="x" * 3000,
        sections={"user_stories": ["y" * 3000]},
        open_questions=[{"id": "q1", "question": "CSV 還是 PDF？"}],
    )
    rendered = render_clarification_context(task, requirement, spec)
    assert len(rendered.encode()) <= CONTEXT_BUDGET_BYTES
    assert "環境變數" not in rendered
    # The rules are never truncated: half a rule is worse than no rule.
    assert "一次一個問題" in rendered
    assert "任務涉及密鑰、身分驗證、金流、遷移或基礎設施。" in rendered
    # And the unresolved question survives the reduction.
    assert "CSV 還是 PDF？" in rendered


async def test_the_decomposition_pack_reads_readiness_keys_from_the_process(
    api: tuple, projects_enabled: None
) -> None:
    """Not a constant: a project may disable readiness items, and a pack naming seven
    fixed keys would have the agent fill one that `accept()` then ignores — which looks
    like the agent inventing fields."""
    from app.services.runs import render_decomposition_context

    task = Task(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        card_ref="TASK-1",
        title="decompose",
        card_kind="decomposition",
    )
    requirement = Requirement(
        id=uuid.uuid4(), project_id=task.project_id, card_ref="REQ-1", raw_text="需求"
    )
    rendered = render_decomposition_context(
        task, requirement, None, ["problem_stated", "scope_bounded"], [(1, "太細了")]
    )
    assert "`problem_stated`" in rendered
    assert "`scope_bounded`" in rendered
    assert "`risk_assessed`" not in rendered
    # A previous rejection is carried forward as a negative example.
    assert "太細了" in rendered
    # And the splitting rules Monstrare specifies are present.
    assert "全端三分法" in rendered
    assert "相互排斥" in rendered


async def test_a_clarification_card_gets_the_clarification_pack(
    api: tuple, projects_enabled: None
) -> None:
    """The dispatch point, end to end: the offer a runner receives.

    One branch decides this and `GATE-RQ-CONTEXT-DISPATCH` asserts there is only one. A
    second branch's first missed kind hands a clarification card the implementation pack
    — whose secrets section would be a lie.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    task_id = await _card(
        maker,
        uuid.UUID(project["id"]),
        kind="clarification",
        requirement_id=uuid.UUID(requirement["id"]),
        delivery="none",
    )
    async with maker() as session:
        node = Node(id=uuid.uuid4(), name="n", hostname="n.invalid", status="online")
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(),
            node_id=node.id,
            name=f"r-{uuid.uuid4().hex[:6]}",
            runtimes=["claude"],
            labels=[],
            enabled=True,
            run_untagged=True,
        )
        session.add(runner)
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=task_id,
            project_id=uuid.UUID(project["id"]),
            seq=1,
            status="queued",
            source_kind="none",
        )
        session.add(run)
        await session.commit()
        runner_id = runner.id

    from app.services.runs import RunService

    async with maker() as session:
        runner_row = await session.get(AgentRunner, runner_id)
        offer = await RunService(session).poll(runner=runner_row, capacity=1)
        assert offer is not None
        assert "你要把一句模糊的需求問成一份規格" in offer.context
        assert "環境變數" not in offer.context


async def test_a_project_row_is_needed_before_the_dispatch_refusals_run(
    api: tuple, projects_enabled: None
) -> None:
    """A guard against a regression that would be silent: `card_kind` refusals read the
    card, but the mockup one reads the integration, and an exception there would surface
    as a 500 on an ordinary dispatch."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    resp = await client.get(f"/api/projects/{project['id']}", headers=headers)
    assert resp.status_code == 200, resp.text


# --- V2-P1: the create path the console has actually been using -----------------------
#
# Every test above builds its clarification card by inserting a `Task` row, which is why
# the gap these three cover survived V2.5 unnoticed: there was no HTTP route that could
# make one. `CreateTaskRequest` declared neither `card_kind` nor `requirement_id` and does
# not forbid extras, so the console's "send to agent" button posted both and Pydantic threw
# them away. The card came back 201 with `card_kind='implementation'` and no requirement,
# and the requirement flow silently never started. J1 is what found it.


async def test_creating_a_clarification_card_links_it_to_its_requirement(
    api: tuple, projects_enabled: None
) -> None:
    """The console's own request, asserted end to end.

    The two fields are read off the **response**, not the database: a field accepted into
    the row but absent from the DTO is the same defect one layer further on, and the
    console decides what to do next from the response.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    resp = await client.post(
        f"/api/projects/{project['id']}/tasks",
        json={
            "title": f"釐清 {requirement['card_ref']}",
            "card_kind": "clarification",
            "requirement_id": requirement["id"],
            "source": "repo",
            "delivery": "artifact",
            "stage": "ready",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    task = resp.json()["task"]
    assert task["card_kind"] == "clarification"
    assert task["requirement_id"] == requirement["id"]


async def test_a_clarification_card_cannot_be_created_without_a_requirement(
    api: tuple, projects_enabled: None
) -> None:
    """Refused at create, not only at dispatch.

    Both checks exist. This one stops a card that can only ever be refused from existing
    at all — and a card nobody can dispatch is worse than an error, because it looks like
    progress.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    resp = await client.post(
        f"/api/projects/{project['id']}/tasks",
        json={"title": "釐清什麼都沒有", "card_kind": "clarification", "delivery": "artifact"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "TASK_KIND_NEEDS_REQUIREMENT"


async def test_a_card_cannot_point_at_another_projects_requirement(
    api: tuple, projects_enabled: None
) -> None:
    """404, not 403 — and the reason is disclosure.

    The link *is* the read authorization: a clarification run reads its requirement through
    the run credential, which resolves the requirement from the card. So a card pointed at
    a foreign requirement would be a cross-project read with no further check. A 403 would
    also confirm that the requirement exists, which is exactly what the caller must not
    learn.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    mine = await _project(client, headers)
    theirs = await _project(client, headers)
    foreign = await _requirement(client, headers, theirs["id"])
    resp = await client.post(
        f"/api/projects/{mine['id']}/tasks",
        json={
            "title": "指到別的專案",
            "card_kind": "clarification",
            "requirement_id": foreign["id"],
            "delivery": "artifact",
        },
        headers=headers,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"]["code"] == "REQUIREMENT_NOT_FOUND"


async def test_an_ordinary_card_still_needs_neither_field(
    api: tuple, projects_enabled: None
) -> None:
    """The default path, unchanged.

    Worth a test of its own because the new branch reads `card_kind` before validating it,
    and a defaulting mistake there would make every ordinary create fail.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project = await _project(client, headers)
    resp = await client.post(
        f"/api/projects/{project['id']}/tasks", json={"title": "普通卡"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    task = resp.json()["task"]
    assert task["card_kind"] == "implementation"
    assert task["requirement_id"] is None
