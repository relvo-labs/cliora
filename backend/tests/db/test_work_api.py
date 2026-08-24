"""The read model over HTTP: items, counts, views, bulk and My Work (PX-25/26/47/28).

Grouped by the property being defended, because most of these exist to stop one specific
thing rather than to describe a feature:

* **counts and items cannot disagree** — the same `ProjectScope` and the same
  `CompiledFilter`, asserted by comparing two endpoints on one fixture;
* **a column header is a server count**, not the number of rows the browser happens to
  hold — the upstream plan calls this the commonest lie on a board like this;
* **a view grants nothing** — `visible_fields` shapes a response and takes no part in
  authorization, and somebody else's personal view is a 403 rather than a 404;
* **bulk goes through the single write path** — so the Done Gate, the dependency refusal,
  the audit trail and the knowledge outbox all still happen;
* **`/api/me/*` answers only about the caller**, and refuses a subject rather than
  ignoring one.
"""

from __future__ import annotations

import base64
import json
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AuditLog, Role, User, WorkView
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio


def encode(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str = "Admin"
) -> tuple[uuid.UUID, dict[str, str]]:
    username = f"{role_name.lower()}-{uuid.uuid4().hex[:8]}"
    async with maker() as setup:
        role = (await setup.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password("pw"),
            display_name=username,
            role_id=role.id,
        )
        setup.add(user)
        await setup.commit()
        user_id = user.id
    login = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}


async def _project_with_cards(
    client: AsyncClient, headers: dict[str, str], stages: list[str]
) -> tuple[str, list[dict]]:
    project_id = (
        await client.post(
            "/api/projects", json={"name": f"work-{uuid.uuid4().hex[:6]}"}, headers=headers
        )
    ).json()["id"]
    cards = []
    for index, stage in enumerate(stages):
        created = await client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": f"card {index}", "risk": "high" if index % 2 else "low"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        card = created.json()["task"]
        if stage != "backlog":
            moved = await client.patch(
                f"/api/tasks/{card['id']}",
                json={"version": card["version"], "stage": stage},
                headers=headers,
            )
            assert moved.status_code == 200, moved.text
            card = moved.json()["task"]
        cards.append(card)
    return project_id, cards


# --- items and counts ------------------------------------------------------------- #


async def test_counts_and_items_describe_the_same_set(api, projects_enabled) -> None:
    """SR-3's first item, asserted across two endpoints rather than inside one.

    They receive the same `ProjectScope` and the same `CompiledFilter`; this is what makes
    that observable from outside.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(
        client, headers, ["backlog"] * 3 + ["ready"] * 2 + ["implementing"]
    )

    items = await client.get(
        f"/api/projects/{project_id}/work-items?group=lifecycle", headers=headers
    )
    counts = await client.get(f"/api/projects/{project_id}/work-counts", headers=headers)
    assert items.status_code == 200, items.text
    assert counts.status_code == 200, counts.text

    per_group = {group["key"]: group["count"] for group in items.json()["groups"]}
    assert per_group == counts.json()["by_lifecycle"]
    assert sum(per_group.values()) == counts.json()["total"] == 6


async def test_a_group_count_is_the_server_total_not_the_page(api, projects_enabled) -> None:
    """The commonest lie on a board like this, asserted on the server.

    Twelve cards, a page of four: the header still says twelve.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, ["backlog"] * 12)

    response = await client.get(
        f"/api/projects/{project_id}/work-items?group=lifecycle&limit=4", headers=headers
    )
    assert response.status_code == 200, response.text
    group = response.json()["groups"][0]
    assert group["count"] == 12
    assert len(group["items"]) == 4
    assert group["next_cursor"]


async def test_a_cursor_walks_the_group_without_repeating_or_skipping(
    api, projects_enabled
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, ["backlog"] * 9)

    seen: list[str] = []
    cursors: dict[str, str] = {}
    for _ in range(4):
        query = f"/api/projects/{project_id}/work-items?group=lifecycle&limit=4"
        if cursors:
            query += f"&cursors={encode(cursors)}"
        page = (await client.get(query, headers=headers)).json()
        group = page["groups"][0]
        seen.extend(item["card_ref"] for item in group["items"])
        if not group["next_cursor"]:
            break
        cursors = {group["key"]: group["next_cursor"]}
    assert len(seen) == 9
    assert len(set(seen)) == 9


async def test_an_unknown_grouping_is_refused_by_name(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, ["backlog"])
    response = await client.get(
        f"/api/projects/{project_id}/work-items?group=assignee", headers=headers
    )
    assert response.status_code == 400
    body = response.json()["error"]
    assert body["code"] == "FILTER_FIELD_NOT_ALLOWED"
    assert body["details"]["field"] == "assignee"
    assert "lifecycle" in body["details"]["allowed_fields"]


async def test_a_filter_narrows_both_endpoints_the_same_way(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, ["backlog"] * 4)
    encoded = encode({"field": "risk", "op": "eq", "value": "high"})

    items = (
        await client.get(f"/api/projects/{project_id}/work-items?filter={encoded}", headers=headers)
    ).json()
    counts = (
        await client.get(
            f"/api/projects/{project_id}/work-counts?filter={encoded}", headers=headers
        )
    ).json()
    loaded = sum(len(group["items"]) for group in items["groups"])
    assert loaded == counts["total"] == 2


async def test_a_viewer_without_project_view_sees_no_work_items_and_zero_counts(
    api, projects_enabled
) -> None:
    """The honest name for this test (D93).

    It measures a **global** role, because that is the only lever this deployment has:
    there is no per-project membership, so a "no access to this project" case cannot be
    constructed. The name says so rather than implying a boundary that is not there — the
    half that cannot be proved here is `plan/26/11` §1.
    """
    client, maker = api
    _, admin = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, admin, ["backlog", "ready"])
    async with maker() as setup:
        role = (await setup.execute(sa.select(Role).where(Role.name == "Viewer"))).scalar_one()
        role.permissions = {"actions": []}
        await setup.commit()
    try:
        _, stripped = await _actor(client, maker, role_name="Viewer")
        items = await client.get(f"/api/projects/{project_id}/work-items", headers=stripped)
        counts = await client.get(f"/api/projects/{project_id}/work-counts", headers=stripped)
        assert items.status_code == counts.status_code == 403
    finally:
        async with maker() as restore:
            role = (
                await restore.execute(sa.select(Role).where(Role.name == "Viewer"))
            ).scalar_one()
            role.permissions = {
                "actions": [
                    "node.view",
                    "session.view",
                    "file.browse",
                    "project.view",
                    "agent.view",
                ]
            }
            await restore.commit()


# --- views ------------------------------------------------------------------------ #


async def test_a_new_project_lists_its_seeded_views(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    response = await client.get(f"/api/projects/{project_id}/views", headers=headers)
    assert response.status_code == 200, response.text
    names = [view["name"] for view in response.json()]
    assert names[0] == "Active Work"
    assert set(names) == {"Active Work", "Backlog", "Waiting for Me", "Blocked", "Verification"}


async def test_a_duplicate_name_is_refused_with_the_name(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    body = {"name": "Mine", "layout": "list", "scope": "personal", "filter": {}}
    first = await client.post(f"/api/projects/{project_id}/views", json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = await client.post(f"/api/projects/{project_id}/views", json=body, headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "VIEW_NAME_CONFLICT"
    assert second.json()["error"]["details"]["name"] == "Mine"


async def test_somebody_elses_personal_view_is_403_not_404(api, projects_enabled) -> None:
    """403 because the view is already absent from the other caller's listing.

    Saying "this is not yours" therefore discloses nothing they could not infer, and it
    lets a client tell it apart from a view that was deleted.
    """
    client, maker = api
    _, mine = await _actor(client, maker)
    _, theirs = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, mine, [])
    created = await client.post(
        f"/api/projects/{project_id}/views",
        json={"name": "Private", "layout": "list", "scope": "personal", "filter": {}},
        headers=mine,
    )
    view_id = created.json()["id"]

    listing = await client.get(f"/api/projects/{project_id}/views", headers=theirs)
    assert "Private" not in [view["name"] for view in listing.json()]

    refused = await client.patch(
        f"/api/work-views/{view_id}", json={"name": "Hijacked"}, headers=theirs
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "VIEW_NOT_OWNED"


async def test_a_shared_view_needs_project_manage(api, projects_enabled) -> None:
    client, maker = api
    _, admin = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, admin, [])
    _, viewer = await _actor(client, maker, role_name="Viewer")
    refused = await client.post(
        f"/api/projects/{project_id}/views",
        json={"name": "Team", "layout": "board", "scope": "project", "filter": {}},
        headers=viewer,
    )
    assert refused.status_code == 403
    allowed = await client.post(
        f"/api/projects/{project_id}/views",
        json={"name": "Team", "layout": "board", "scope": "project", "filter": {}},
        headers=admin,
    )
    assert allowed.status_code == 201, allowed.text


async def test_visible_fields_shape_the_response_and_nothing_else(api, projects_enabled) -> None:
    """The set of cards and the counts are identical; only the payload is narrower.

    There is a test for this because a field list is the most natural place for somebody
    to eventually put a permission (ADR 0042 §2).
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, ["backlog"] * 3)
    created = await client.post(
        f"/api/projects/{project_id}/views",
        json={
            "name": "Narrow",
            "layout": "list",
            "scope": "personal",
            "filter": {},
            "visible_fields": ["title", "lifecycle"],
        },
        headers=headers,
    )
    view_id = created.json()["id"]

    wide = (await client.get(f"/api/projects/{project_id}/work-items", headers=headers)).json()
    narrow = (
        await client.get(f"/api/projects/{project_id}/work-items?view={view_id}", headers=headers)
    ).json()
    assert sum(len(g["items"]) for g in wide["groups"]) == sum(
        len(g["items"]) for g in narrow["groups"]
    )
    shaped = narrow["groups"][0]["items"][0]
    assert shaped["title"]
    # **Absent, not null.** `"owner_name": null` would mean both "this card has no
    # owner" and "this view does not show owners", and those are different facts.
    assert "owner_name" not in shaped
    assert wide["groups"][0]["items"][0]["lifecycle"] == shaped["lifecycle"]


async def test_changing_the_default_writes_audit_and_changing_density_does_not(
    api, projects_enabled
) -> None:
    """Two assertions in one test because they are one decision (plan/26/05 §4).

    "Which view does this project open on" is a change to everybody's first screen. A
    person's display density is a preference, and auditing preferences turns the audit log
    into telemetry.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    views = (await client.get(f"/api/projects/{project_id}/views", headers=headers)).json()
    target = next(view for view in views if view["name"] == "Backlog")

    async def audit_rows() -> list[AuditLog]:
        async with maker() as check:
            return list(
                (
                    await check.execute(
                        sa.select(AuditLog).where(
                            AuditLog.audit_metadata["action"].astext == "set_default_view"
                        )
                    )
                ).scalars()
            )

    assert await audit_rows() == []
    promoted = await client.patch(
        f"/api/work-views/{target['id']}", json={"is_default": True}, headers=headers
    )
    assert promoted.status_code == 200, promoted.text
    rows = await audit_rows()
    assert len(rows) == 1
    assert rows[0].audit_metadata["new_view_id"] == target["id"]
    assert rows[0].audit_metadata["old_view_id"] is not None

    before = len([row async for row in _all_audit(maker)])
    density = await client.patch(
        f"/api/work-views/{target['id']}", json={"density": "compact"}, headers=headers
    )
    assert density.status_code == 200, density.text
    after = len([row async for row in _all_audit(maker)])
    assert after == before, "changing density must not write an audit row"


async def _all_audit(maker: async_sessionmaker):
    async with maker() as check:
        for row in (await check.execute(sa.select(AuditLog.id))).scalars():
            yield row


async def test_only_one_view_is_the_default_after_a_change(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    views = (await client.get(f"/api/projects/{project_id}/views", headers=headers)).json()
    target = next(view for view in views if view["name"] == "Verification")
    await client.patch(
        f"/api/work-views/{target['id']}", json={"is_default": True}, headers=headers
    )
    async with maker() as check:
        defaults = list(
            (
                await check.execute(
                    sa.select(WorkView.name).where(
                        WorkView.project_id == uuid.UUID(project_id),
                        WorkView.is_default.is_(True),
                    )
                )
            ).scalars()
        )
    assert defaults == ["Verification"]


async def test_a_duplicate_is_always_personal(api, projects_enabled) -> None:
    """Copying a shared view is how somebody tries something without broadcasting it."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    views = (await client.get(f"/api/projects/{project_id}/views", headers=headers)).json()
    shared = next(view for view in views if view["scope"] == "project")
    copy = await client.post(
        f"/api/work-views/{shared['id']}/duplicate",
        json={"name": "My copy"},
        headers=headers,
    )
    assert copy.status_code == 201, copy.text
    assert copy.json()["scope"] == "personal"
    assert copy.json()["is_default"] is False


async def test_a_deleted_shared_view_frees_its_name(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    body = {"name": "Sprint", "layout": "list", "scope": "project", "filter": {}}
    first = await client.post(f"/api/projects/{project_id}/views", json=body, headers=headers)
    removed = await client.delete(f"/api/work-views/{first.json()['id']}", headers=headers)
    assert removed.status_code == 204, removed.text
    again = await client.post(f"/api/projects/{project_id}/views", json=body, headers=headers)
    assert again.status_code == 201, again.text


async def test_an_uncompilable_filter_cannot_be_saved(api, projects_enabled) -> None:
    """A view whose filter only fails on read is one that looks fine in the list."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, _ = await _project_with_cards(client, headers, [])
    response = await client.post(
        f"/api/projects/{project_id}/views",
        json={
            "name": "Broken",
            "layout": "list",
            "scope": "personal",
            "filter": {"field": "assignee", "op": "eq", "value": "x"},
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FILTER_FIELD_NOT_ALLOWED"


# --- bulk ------------------------------------------------------------------------- #


async def test_bulk_update_writes_one_audit_row_and_n_activity_rows(api, projects_enabled) -> None:
    """D105. The batch is one decision; each card's timeline is its own history."""
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, cards = await _project_with_cards(client, headers, ["backlog"] * 3)

    response = await client.post(
        "/api/tasks/bulk-update",
        json={"task_ids": [card["id"] for card in cards], "patch": {"risk": "critical"}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 3

    async with maker() as check:
        audits = list(
            (
                await check.execute(
                    sa.select(AuditLog).where(
                        AuditLog.audit_metadata["action"].astext == "bulk_update"
                    )
                )
            ).scalars()
        )
        activity = (
            await check.execute(
                sa.text(
                    "SELECT count(*) FROM activity_events "
                    "WHERE project_id = :project AND kind = 'task.updated'"
                ),
                {"project": project_id},
            )
        ).scalar_one()
    assert len(audits) == 1
    assert sorted(audits[0].audit_metadata["item_refs"]) == sorted(
        card["card_ref"] for card in cards
    )
    assert activity == 3


async def test_bulk_update_refuses_past_its_limit_and_says_both_numbers(
    api, projects_enabled
) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    response = await client.post(
        "/api/tasks/bulk-update",
        json={"task_ids": [str(uuid.uuid4()) for _ in range(101)], "patch": {"risk": "low"}},
        headers=headers,
    )
    assert response.status_code == 400
    details = response.json()["error"]["details"]
    assert details == {"limit": 100, "received": 101}


async def test_bulk_update_is_all_or_nothing(api, projects_enabled) -> None:
    """One refusal rolls the whole batch back, and the response names the reason.

    The alternative — partial success — needs an interface that says which cards
    succeeded, and that is a different feature rather than a relaxation of this one.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, cards = await _project_with_cards(client, headers, ["backlog"] * 2)

    response = await client.post(
        "/api/tasks/bulk-update",
        json={
            "task_ids": [cards[0]["id"], str(uuid.uuid4())],
            "patch": {"risk": "critical"},
        },
        headers=headers,
    )
    assert response.status_code == 404
    async with maker() as check:
        risks = list(
            (
                await check.execute(
                    sa.text("SELECT risk FROM tasks WHERE project_id = :p"),
                    {"p": project_id},
                )
            ).scalars()
        )
    assert "critical" not in risks


async def test_bulk_update_cannot_reach_a_field_a_patch_cannot(api, projects_enabled) -> None:
    """The same `EDITABLE_FIELDS` as a single card. Bulk is not a wider door."""
    client, maker = api
    _, headers = await _actor(client, maker)
    _, cards = await _project_with_cards(client, headers, ["backlog"])
    response = await client.post(
        "/api/tasks/bulk-update",
        json={"task_ids": [cards[0]["id"]], "patch": {"card_ref": "TASK-999"}},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FORBIDDEN_FIELD"


# --- /api/me --------------------------------------------------------------------- #


async def test_my_work_items_and_a_projects_agree_about_a_card(api, projects_enabled) -> None:
    """One `derive_attention`, one compiler, two scopes (D93).

    The same card must carry the same `primary_attention` whichever endpoint asked.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    project_id, cards = await _project_with_cards(client, headers, ["ready", "ready"])
    link = await client.post(
        f"/api/tasks/{cards[1]['id']}/dependencies",
        json={"depends_on_task_id": cards[0]["id"]},
        headers=headers,
    )
    assert link.status_code == 201, link.text

    project_page = (
        await client.get(f"/api/projects/{project_id}/work-items", headers=headers)
    ).json()
    mine = (await client.get("/api/me/work-items", headers=headers)).json()

    def attention(page: dict) -> dict[str, str | None]:
        return {
            item["card_ref"]: item["primary_attention"]
            for group in page["groups"]
            for item in group["items"]
        }

    project_attention = attention(project_page)
    my_attention = attention(mine)
    assert project_attention
    for ref, value in project_attention.items():
        assert my_attention[ref] == value


async def test_my_work_refuses_a_subject_rather_than_ignoring_one(api, projects_enabled) -> None:
    """The rule this namespace was created with.

    Undeclared, the parameter would be silently dropped and a caller who passed it would
    believe they had been answered. Looking at somebody else's queue is a different
    capability and belongs on a path where the subject is visible.
    """
    client, maker = api
    _, headers = await _actor(client, maker)
    response = await client.get(f"/api/me/work-items?user_id={uuid.uuid4()}", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["rejected_parameters"] == ["user_id"]


async def test_my_attention_counts_spans_projects(api, projects_enabled) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    await _project_with_cards(client, headers, ["backlog"] * 2)
    await _project_with_cards(client, headers, ["ready"] * 3)
    counts = (await client.get("/api/me/attention-counts", headers=headers)).json()
    assert counts["total"] == 5
    assert counts["by_lifecycle"] == {"backlog": 2, "ready": 3}
