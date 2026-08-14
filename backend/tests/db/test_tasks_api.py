"""Task API behaviour over real HTTP (TK-04, FR-TASK-001…004, ADR 0028).

Grouped by the property being defended, the same way `test_projects_api.py` is,
because most of these exist to stop one specific regression:

* the board response stays a **summary** — the shape M1 chose instead of paging, and
  the one someone will later widen "just for convenience" (`plan/17/10-…md` §1);
* exactly one rule refuses, and its message **names the blocking cards**;
* two writers cannot both land, and the loser is told the current version;
* a review gate records a person, and a disabled gate says why it is disabled;
* Viewer holds none of the three write actions.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Role, TunnelIntegration, User, VerificationReport
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


async def test_epic_and_user_story_can_be_edited(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    epic = (
        await client.post(
            f"/api/projects/{project['id']}/epics",
            json={"title": "Original epic"},
            headers=headers,
        )
    ).json()
    story = (
        await client.post(
            f"/api/projects/{project['id']}/user-stories",
            json={"title": "Original story", "epic_id": epic["id"]},
            headers=headers,
        )
    ).json()

    edited_epic = await client.patch(
        f"/api/epics/{epic['id']}",
        json={"title": "Edited epic", "order_index": 2},
        headers=headers,
    )
    edited_story = await client.patch(
        f"/api/user-stories/{story['id']}",
        json={"title": "Edited story", "epic_id": None},
        headers=headers,
    )

    assert edited_epic.status_code == 200, edited_epic.text
    assert edited_epic.json()["title"] == "Edited epic"
    assert edited_story.status_code == 200, edited_story.text
    assert edited_story.json()["title"] == "Edited story"
    assert edited_story.json()["epic_id"] is None


async def _project(client: AsyncClient, headers: dict[str, str]) -> dict:
    resp = await client.post(
        "/api/projects", json={"name": f"proj-{uuid.uuid4().hex[:8]}"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _card(
    client: AsyncClient, headers: dict[str, str], project_id: str, title: str = "card", **fields
) -> dict:
    resp = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={"title": title, **fields},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["task"]


# --- the feature flag ------------------------------------------------------ #


async def test_every_task_route_is_404_while_the_flag_is_off(
    api: tuple, projects_disabled: None
) -> None:
    client, sessionmaker = api
    """404 before the action guard, exactly as the project routes behave.

    An Admin holds `task.create` whichever way the flag is set — the seed migration
    runs unconditionally — so a 403 here would be the wrong answer *and* would tell a
    caller the capability exists.
    """
    _, headers = await _actor(client, sessionmaker, "Admin")
    project_id = uuid.uuid4()
    for method, path in [
        ("get", f"/api/projects/{project_id}/board"),
        ("get", f"/api/projects/{project_id}/roadmap"),
        ("get", f"/api/projects/{project_id}/process"),
        ("get", f"/api/tasks/{uuid.uuid4()}"),
    ]:
        resp = await getattr(client, method)(path, headers=headers)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
    resp = await client.post(
        f"/api/projects/{project_id}/tasks", json={"title": "x"}, headers=headers
    )
    assert resp.status_code == 404


# --- the board's shape ----------------------------------------------------- #


async def test_the_board_card_stays_a_summary(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    """M1's decision, pinned.

    The measurement (`plan/17/10-…md` §1) is what replaced paging: 74 KB for 200
    summary cards against 439 KB for the full ones. Adding acceptance criteria or gate
    detail back to a board card would silently undo it, and nothing else in the suite
    would notice — the response would simply get bigger.
    """
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    await _card(
        client,
        headers,
        project["id"],
        acceptance_criteria=[{"id": "AC-01", "text": "something", "result": None}],
    )
    resp = await client.get(f"/api/projects/{project['id']}/board", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [lane["stage"] for lane in body["lanes"]] == [
        "backlog",
        "blocked",
        "ready",
        "implementing",
        "verify",
        "done",
    ]
    assert body["has_more"] is False
    card = body["lanes"][0]["cards"][0]
    assert "acceptance_criteria" not in card
    assert "gates" not in card
    assert card["gates_approved_count"] == 0
    assert card["blocking_count"] == 0
    assert card["active_run_status"] is None
    assert card["active_run_runner_name"] is None
    assert card["waiting_reason"] is None


async def test_the_roadmap_keeps_both_unclassified_buckets(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    """A card must never disappear because of how it was filed (D4)."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    epic = (
        await client.post(
            f"/api/projects/{project['id']}/epics", json={"title": "epic"}, headers=headers
        )
    ).json()
    story = (
        await client.post(
            f"/api/projects/{project['id']}/user-stories",
            json={"title": "story", "epic_id": epic["id"]},
            headers=headers,
        )
    ).json()
    await _card(
        client, headers, project["id"], "filed", user_story_id=story["id"], epic_id=epic["id"]
    )
    await _card(client, headers, project["id"], "epic only", epic_id=epic["id"])
    await _card(client, headers, project["id"], "loose")

    body = (await client.get(f"/api/projects/{project['id']}/roadmap", headers=headers)).json()
    assert body["total_count"] == 3
    assert [item["title"] for item in body["epics"][0]["unclassified"]] == ["epic only"]
    assert [item["title"] for item in body["unclassified"]] == ["loose"]
    assert body["epics"][0]["total_count"] == 2


# --- the one rule that refuses --------------------------------------------- #


async def test_a_blocked_card_cannot_enter_implementing_and_the_error_names_the_cards(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    """FR-TASK-002.AC-02. The refusal has to be actionable, so it names `card_ref`s."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    blocker_a = await _card(client, headers, project["id"], "a")
    blocker_b = await _card(client, headers, project["id"], "b")
    card = await _card(client, headers, project["id"], "c")
    for blocker in (blocker_a, blocker_b):
        resp = await client.post(
            f"/api/tasks/{card['id']}/dependencies",
            json={"depends_on_task_id": blocker["id"]},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    resp = await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "stage": "implementing"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "TASK_DEPENDENCY_UNSATISFIED"
    assert error["details"]["blocking_refs"] == sorted(
        [blocker_a["card_ref"], blocker_b["card_ref"]]
    )

    # `blocked` is deliberately reachable: moving a card there is how a person says it
    # is blocked, and refusing that would be refusing the truth.
    resp = await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "stage": "blocked"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_finishing_the_blockers_unblocks_the_card(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    blocker = await _card(client, headers, project["id"], "blocker")
    card = await _card(client, headers, project["id"], "card")
    await client.post(
        f"/api/tasks/{card['id']}/dependencies",
        json={"depends_on_task_id": blocker["id"]},
        headers=headers,
    )
    # V2.4: with the runner layer on, `done` is a claim the platform checks, so the
    # blocker needs its completion evidence before it can be finished. That is the Done
    # Gate's business (`test_done_gate.py`); what this test still asserts is the V2.1
    # rule — once the blocker *is* done, the dependent card is free to move.
    async with sessionmaker() as session:
        session.add(
            VerificationReport(
                id=uuid.uuid4(),
                task_id=uuid.UUID(blocker["id"]),
                project_id=uuid.UUID(project["id"]),
                result="passed",
                completion_summary="blocker finished",
                source="platform_observed",
                reported_by_kind="user",
            )
        )
        await session.commit()
    resp = await client.patch(
        f"/api/tasks/{blocker['id']}",
        json={"version": blocker["version"], "stage": "done"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "stage": "implementing"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["task"]["stage"] == "implementing"


async def test_a_cycle_is_refused_and_the_error_shows_the_path(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    first = await _card(client, headers, project["id"], "first")
    second = await _card(client, headers, project["id"], "second")
    await client.post(
        f"/api/tasks/{first['id']}/dependencies",
        json={"depends_on_task_id": second["id"]},
        headers=headers,
    )
    resp = await client.post(
        f"/api/tasks/{second['id']}/dependencies",
        json={"depends_on_task_id": first["id"]},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    error = resp.json()["error"]
    assert error["code"] == "TASK_DEPENDENCY_CYCLE"
    assert first["card_ref"] in error["details"]["path"]


# --- concurrency ------------------------------------------------------------ #


async def test_the_second_writer_gets_409_and_the_current_version(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    """Two tabs, one card. The loser is told what the card is now, so the board can
    re-render without a second request (`plan/17/07-…md` §2.2)."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    card = await _card(client, headers, project["id"])

    first = await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "stage": "ready"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    second = await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "title": "renamed"},
        headers=headers,
    )
    assert second.status_code == 409
    details = second.json()["error"]["details"]
    assert details["version"] == first.json()["task"]["version"]
    assert details["current"]["id"] == card["id"]
    assert details["current"]["acceptance_criteria"] == card["acceptance_criteria"]
    assert details["current"]["stage"] == first.json()["task"]["stage"]
    # And nothing half-landed: the title is untouched.
    current = (await client.get(f"/api/tasks/{card['id']}", headers=headers)).json()
    assert current["title"] == card["title"]


# --- gates ------------------------------------------------------------------ #


async def test_a_gate_records_who_approved_it_and_when(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    """The cell that makes "an agent's output is not an approval" a fact in the data."""
    user_id, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    card = await _card(client, headers, project["id"])
    resp = await client.post(
        f"/api/tasks/{card['id']}/gates/architecture", json={"approved": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    gate = resp.json()["gates"]["architecture"]
    assert gate["approved_by"] == str(user_id)
    assert gate["approved_at"].endswith("+00:00") or gate["approved_at"].endswith("Z")

    # Un-ticking exists: a tick nobody can undo is a tick nobody dares make.
    resp = await client.post(
        f"/api/tasks/{card['id']}/gates/architecture", json={"approved": False}, headers=headers
    )
    assert resp.status_code == 200
    assert "architecture" not in resp.json()["gates"]


async def test_the_ui_gate_is_disabled_until_tunnel_integration_is_enabled(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    """Derived state, not an administrator's memory (D31, ADR 0028 sec 8).

    And disabled *visibly*: the reason travels with the gate, because a gate that
    quietly does not exist is worse than one that explains itself.
    """
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    card = await _card(client, headers, project["id"])

    process = (await client.get(f"/api/projects/{project['id']}/process", headers=headers)).json()
    ui_gate = next(gate for gate in process["gates"] if gate["key"] == "ui")
    assert ui_gate["enabled"] is False
    assert ui_gate["disabled_reason"] == "tunnel_integration_disabled"

    resp = await client.post(
        f"/api/tasks/{card['id']}/gates/ui", json={"approved": True}, headers=headers
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "GATE_DISABLED"

    async with sessionmaker() as session:
        session.add(TunnelIntegration(singleton=True, enabled=True, provider="pinggy"))
        await session.commit()
    process = (await client.get(f"/api/projects/{project['id']}/process", headers=headers)).json()
    assert next(gate for gate in process["gates"] if gate["key"] == "ui")["enabled"] is True
    resp = await client.post(
        f"/api/tasks/{card['id']}/gates/ui", json={"approved": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text


async def test_an_unknown_gate_is_404_not_409(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    """A typo and a switched-off integration need different answers."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    card = await _card(client, headers, project["id"])
    resp = await client.post(
        f"/api/tasks/{card['id']}/gates/nonsense", json={"approved": True}, headers=headers
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "GATE_UNKNOWN"


async def test_gates_cannot_be_set_through_the_generic_patch(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    """Otherwise `task.update` would be enough to approve, and the whole split
    between the two actions would be decorative."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    card = await _card(client, headers, project["id"])
    resp = await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "gates": {"architecture": {"approved_by": "x"}}},
        headers=headers,
    )
    # Refused by the request schema before it reaches the service: `extra: forbid`.
    assert resp.status_code in (409, 422)
    current = (await client.get(f"/api/tasks/{card['id']}", headers=headers)).json()
    assert current["gates"] == {}


# --- readiness warns, never refuses ----------------------------------------- #


async def test_readiness_reports_and_does_not_refuse(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    """Enforcing all seven from day one is how a board stops being used."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    resp = await client.post(
        f"/api/projects/{project['id']}/tasks",
        json={"title": "card", "stage": "ready"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    warnings = resp.json()["warnings"]
    assert warnings and warnings[0]["code"] == "READINESS_INCOMPLETE"
    assert len(warnings[0]["missing"]) == 7


# --- authorization ---------------------------------------------------------- #


async def test_a_viewer_may_read_the_board_and_write_nothing(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    _, admin = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, admin)
    card = await _card(client, admin, project["id"])
    _, viewer = await _actor(client, sessionmaker, "Viewer")

    assert (
        await client.get(f"/api/projects/{project['id']}/board", headers=viewer)
    ).status_code == 200
    for method, path, body in [
        ("post", f"/api/projects/{project['id']}/tasks", {"title": "x"}),
        ("patch", f"/api/tasks/{card['id']}", {"version": 1, "title": "x"}),
        ("post", f"/api/tasks/{card['id']}/gates/architecture", {"approved": True}),
    ]:
        resp = await getattr(client, method)(path, json=body, headers=viewer)
        assert resp.status_code == 403, f"{method} {path} -> {resp.status_code}"


async def test_a_developer_may_create_and_approve(api: tuple, projects_enabled: None) -> None:
    client, sessionmaker = api
    """`task.approve` is not an Admin action: a gate that needs an administrator per
    card makes the internalised Review Gates unaffordable (ADR 0028)."""
    _, admin = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, admin)
    _, developer = await _actor(client, sessionmaker, "Developer")
    card = await _card(client, developer, project["id"])
    resp = await client.post(
        f"/api/tasks/{card['id']}/gates/requirements", json={"approved": True}, headers=developer
    )
    assert resp.status_code == 200, resp.text


# --- the timeline ----------------------------------------------------------- #


async def test_a_card_write_lands_on_the_project_timeline(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    """And it says which *kind* of actor did it, which is what V2.2's agent writes
    will need to be distinguishable (ADR 0028 sec 3)."""
    _, headers = await _actor(client, sessionmaker, "Admin")
    project = await _project(client, headers)
    card = await _card(client, headers, project["id"])
    await client.patch(
        f"/api/tasks/{card['id']}",
        json={"version": card["version"], "stage": "ready"},
        headers=headers,
    )
    body = (await client.get(f"/api/projects/{project['id']}/activity", headers=headers)).json()
    kinds = [item["kind"] for item in body["items"]]
    assert "task.created" in kinds
    assert "task.stage_changed" in kinds
    assert all(item["actor_kind"] == "user" for item in body["items"])
