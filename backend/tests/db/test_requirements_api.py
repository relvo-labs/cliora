"""The manual requirement flow (TK-05, FR-TASK-005, D28).

Every test here defends one of the three rules that make this flow worth having, and
each of them is asserted **at the API** rather than in the console — because V2.5
points an agent at exactly these routes, and a rule that lives in a disabled button
would not be there when it did.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Role, User
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str
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
        json={"raw_text": "把檔案樹做得快一點"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


READY_TREE = {
    "tasks": [
        {
            "id": "t1",
            "title": "complete card",
            "readiness": {
                "problem_stated": True,
                "acceptance_criteria": True,
                "scope_bounded": True,
                "dependencies_known": True,
                "verification_defined": True,
                "risk_assessed": True,
                "context_pointers": True,
            },
        },
        {"id": "t2", "title": "incomplete card", "readiness": {"problem_stated": True}},
    ]
}


async def test_intake_takes_one_sentence(api: tuple, projects_enabled: None) -> None:
    """The whole intake surface. Ten required fields at this moment is how the flow
    stops being used at all (D28)."""
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    body = await _requirement(client, headers, project["id"])
    assert body["status"] == "intake"
    assert body["card_ref"].startswith("REQ-")


async def test_an_unresolved_question_blocks_approval_and_the_error_names_it(
    api: tuple, projects_enabled: None
) -> None:
    """FR-TASK-005.AC-03, at the API. And the detail view carries the same list, so a
    console can disable the button *and say why* from one response."""
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/specs",
        json={
            "objective": "faster tree",
            "open_questions": [{"id": "q1", "question": "含 symlink 嗎？"}],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    detail = (await client.get(f"/api/requirements/{requirement['id']}", headers=headers)).json()
    assert detail["blocking_questions"] == ["含 symlink 嗎？"]
    assert detail["status"] == "clarifying"

    resp = await client.post(f"/api/requirements/{requirement['id']}/approve", headers=headers)
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "SPEC_HAS_OPEN_QUESTIONS"
    assert error["details"]["questions"] == ["含 symlink 嗎？"]


async def test_a_known_unknown_counts_as_resolved(api: tuple, projects_enabled: None) -> None:
    """Recording a question as a known unknown is not the same as pretending it was
    answered — but it does let the specification be approved (D28 §3)."""
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await client.post(
        f"/api/requirements/{requirement['id']}/specs",
        json={
            "objective": "faster tree",
            "open_questions": [
                {"id": "q1", "question": "含 symlink 嗎？", "resolved_as": "known_unknown"}
            ],
        },
        headers=headers,
    )
    resp = await client.post(f"/api/requirements/{requirement['id']}/approve", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"


async def test_an_unapproved_requirement_cannot_be_decomposed(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await client.post(
        f"/api/requirements/{requirement['id']}/specs", json={"objective": "x"}, headers=headers
    )
    resp = await client.post(
        f"/api/requirements/{requirement['id']}/proposals",
        json={"tree": READY_TREE},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "REQUIREMENT_NOT_APPROVED"


async def test_accepting_a_proposal_lands_incomplete_cards_in_backlog(
    api: tuple, projects_enabled: None
) -> None:
    """The Definition of Ready's one hard consequence in V2.1 (FR-TASK-005.AC-06).

    And the response says *which* items were missing, so the reason is on the same
    screen as the result rather than in a second place the user has to go and find.
    """
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await client.post(
        f"/api/requirements/{requirement['id']}/specs", json={"objective": "x"}, headers=headers
    )
    await client.post(f"/api/requirements/{requirement['id']}/approve", headers=headers)
    proposal = (
        await client.post(
            f"/api/requirements/{requirement['id']}/proposals",
            json={"tree": READY_TREE},
            headers=headers,
        )
    ).json()

    resp = await client.post(
        f"/api/proposals/{proposal['id']}/accept", json={"accept_ids": None}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_title = {task["title"]: task for task in body["created"]}
    assert by_title["complete card"]["stage"] == "ready"
    assert by_title["incomplete card"]["stage"] == "backlog"
    missing = body["incomplete"][by_title["incomplete card"]["card_ref"]]
    assert "acceptance_criteria" in missing and len(missing) == 6
    # Provenance: "from requirement #N, proposal #M" on the card's detail page.
    assert by_title["complete card"]["requirement_id"] == requirement["id"]
    assert by_title["complete card"]["proposal_id"] == proposal["id"]


async def test_partial_acceptance_creates_only_what_was_chosen(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    await client.post(
        f"/api/requirements/{requirement['id']}/specs", json={"objective": "x"}, headers=headers
    )
    await client.post(f"/api/requirements/{requirement['id']}/approve", headers=headers)
    proposal = (
        await client.post(
            f"/api/requirements/{requirement['id']}/proposals",
            json={"tree": READY_TREE},
            headers=headers,
        )
    ).json()
    resp = await client.post(
        f"/api/proposals/{proposal['id']}/accept", json={"accept_ids": ["t1"]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert [task["title"] for task in resp.json()["created"]] == ["complete card"]

    detail = (await client.get(f"/api/requirements/{requirement['id']}", headers=headers)).json()
    assert detail["proposals"][0]["status"] == "partially_accepted"

    # The rest stay *available*, not declined: accepting them later is the normal
    # follow-up (research/02/10 §2.7 condition 5).
    again = await client.post(
        f"/api/proposals/{proposal['id']}/accept", json={"accept_ids": ["t2"]}, headers=headers
    )
    assert again.status_code == 200, again.text
    assert [task["title"] for task in again.json()["created"]] == ["incomplete card"]

    # …and accepting one twice creates nothing, because a duplicated card is the one
    # failure this flow could produce silently.
    third = await client.post(
        f"/api/proposals/{proposal['id']}/accept", json={"accept_ids": ["t1"]}, headers=headers
    )
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "PROPOSAL_ALREADY_DECIDED"


async def test_specs_are_append_only(api: tuple, projects_enabled: None) -> None:
    """Version N against N-1 is what the review screen is for."""
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    requirement = await _requirement(client, headers, project["id"])
    for objective in ("first", "second", "third"):
        resp = await client.post(
            f"/api/requirements/{requirement['id']}/specs",
            json={"objective": objective},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
    detail = (await client.get(f"/api/requirements/{requirement['id']}", headers=headers)).json()
    assert [spec["seq"] for spec in detail["specs"]] == [1, 2, 3]
    assert [spec["objective"] for spec in detail["specs"]] == ["first", "second", "third"]
    assert all(spec["authored_by_kind"] == "user" for spec in detail["specs"])


async def test_a_viewer_may_read_and_a_developer_may_decide(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    _, admin = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, admin)
    requirement = await _requirement(client, admin, project["id"])
    _, viewer = await _actor(client, sessionmaker, "Viewer")
    _, developer = await _actor(client, sessionmaker, "Developer")

    assert (
        await client.get(f"/api/requirements/{requirement['id']}", headers=viewer)
    ).status_code == 200
    assert (
        await client.post(f"/api/requirements/{requirement['id']}/approve", headers=viewer)
    ).status_code == 403
    # A Developer holds `task.approve`: a gate that needs an administrator per card is
    # a gate nobody can afford to use.
    await client.post(
        f"/api/requirements/{requirement['id']}/specs", json={"objective": "x"}, headers=developer
    )
    assert (
        await client.post(f"/api/requirements/{requirement['id']}/approve", headers=developer)
    ).status_code == 200
