"""`GET /api/audit` against the real app and schema (P4-05, FR-AUTH-002, SEC-006).

The hermetic half of this ticket (`tests/test_audit_query.py`) covers the bounds
and the cursor codec. What needs PostgreSQL is everything the endpoint can only
get wrong once rows exist: keyset paging over a real ordering, the outer joins
that resolve actor and node names, and the promise that reading the trail does
not itself write to it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AuditLog, Node, Role, User
from app.security.passwords import hash_password
from app.services import audit

pytestmark = pytest.mark.asyncio

# Fixture rows are timestamped in the past and queried through a narrow window
# around that instant, so the `user.login` rows that `_actor` unavoidably writes
# at the current time never land inside the window under test.
BASE = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


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


async def _node(maker: async_sessionmaker, name: str = "vm-1") -> uuid.UUID:
    async with maker() as session:
        node = Node(name=name, hostname=f"{name}.local", status="online", is_enabled=True)
        session.add(node)
        await session.commit()
        return node.id


async def _row(
    maker: async_sessionmaker,
    action: str,
    *,
    at: datetime,
    user_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> uuid.UUID:
    """Insert an audit row with an explicit instant.

    Written directly rather than by performing the operation: these tests are
    about the *read* path, and an explicit `created_at` is the only way to assert
    an ordering without sleeping.
    """
    async with maker() as session:
        entry = AuditLog(
            action=action,
            user_id=user_id,
            node_id=node_id,
            session_id=session_id,
            audit_metadata=metadata or {},
            created_at=at,
        )
        session.add(entry)
        await session.commit()
        return entry.id


async def _audit_count(maker: async_sessionmaker) -> int:
    async with maker() as session:
        return int((await session.execute(sa.select(sa.func.count(AuditLog.id)))).scalar_one())


def _window() -> dict[str, str]:
    """A range that contains the fixture rows and nothing else. The default window
    is anchored to *now*, which would also sweep in the sign-in rows the fixtures
    create."""
    return {
        "from": (BASE - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "to": (BASE + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("role", "expected"), [("Admin", 200), ("Developer", 403), ("Viewer", 403)]
)
async def test_only_admin_may_read_the_trail(api: tuple, role: str, expected: int) -> None:
    """`audit.view` is seeded to Admin alone (PRD §8.1). Until P4-05 no endpoint
    checked it at all, so this is the first test that can fail."""
    client, maker = api
    _, headers = await _actor(client, maker, role)
    resp = await client.get("/api/audit", headers=headers)
    assert resp.status_code == expected, resp.text
    if expected == 403:
        assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_unauthenticated_read_is_401_not_403(api: tuple) -> None:
    client, _ = api
    resp = await client.get("/api/audit")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #


async def test_action_filter_selects_only_that_action(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=actor_id)
    await _row(maker, audit.NODE_DISABLE, at=BASE - timedelta(minutes=1), user_id=actor_id)

    resp = await client.get(
        "/api/audit", params={**_window(), "action": audit.USER_LOGOUT}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert {item["action"] for item in resp.json()["items"]} == {audit.USER_LOGOUT}


async def test_repeated_action_parameter_is_a_union(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=actor_id)
    await _row(maker, audit.NODE_DISABLE, at=BASE - timedelta(minutes=1), user_id=actor_id)
    await _row(maker, audit.NODE_REMOVE, at=BASE - timedelta(minutes=2), user_id=actor_id)

    resp = await client.get(
        "/api/audit",
        params=[*_window().items(), ("action", audit.USER_LOGOUT), ("action", audit.NODE_REMOVE)],
        headers=headers,
    )
    assert {item["action"] for item in resp.json()["items"]} == {
        audit.USER_LOGOUT,
        audit.NODE_REMOVE,
    }


async def test_resource_filters_narrow_by_id(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    wanted_node = await _node(maker, "wanted")
    other_node = await _node(maker, "other")
    session_id = uuid.uuid4()
    await _row(maker, audit.NODE_DISABLE, at=BASE, user_id=actor_id, node_id=wanted_node)
    await _row(
        maker,
        audit.NODE_DISABLE,
        at=BASE - timedelta(minutes=1),
        user_id=actor_id,
        node_id=other_node,
    )
    await _row(
        maker,
        audit.SESSION_TERMINATE,
        at=BASE - timedelta(minutes=2),
        user_id=actor_id,
        node_id=wanted_node,
        session_id=session_id,
    )

    by_node = await client.get(
        "/api/audit", params={**_window(), "node_id": str(wanted_node)}, headers=headers
    )
    assert {item["node"]["id"] for item in by_node.json()["items"]} == {str(wanted_node)}

    by_session = await client.get(
        "/api/audit", params={**_window(), "session_id": str(session_id)}, headers=headers
    )
    assert [item["session_id"] for item in by_session.json()["items"]] == [str(session_id)]


async def test_actor_filter_uses_the_indexed_user_id(api: tuple) -> None:
    client, maker = api
    admin_id, headers = await _actor(client, maker)
    other_id, _ = await _actor(client, maker, "Developer")
    await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=admin_id)
    await _row(maker, audit.USER_LOGOUT, at=BASE - timedelta(minutes=1), user_id=other_id)

    resp = await client.get(
        "/api/audit", params={**_window(), "user_id": str(other_id)}, headers=headers
    )
    assert {item["actor"]["id"] for item in resp.json()["items"]} == {str(other_id)}


async def test_time_window_excludes_rows_outside_it(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    inside = await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=actor_id)
    await _row(maker, audit.USER_LOGOUT, at=BASE - timedelta(days=10), user_id=actor_id)

    resp = await client.get(
        "/api/audit",
        params={
            "from": (BASE - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "to": (BASE + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        },
        headers=headers,
    )
    assert [item["id"] for item in resp.json()["items"]] == [str(inside)]


@pytest.mark.parametrize(
    ("params", "why"),
    [
        ({"action": "not.an.action"}, "unknown action"),
        ({"from": "2026-07-01T00:00:00"}, "naive from"),
        ({"to": "2026-07-01T00:00:00"}, "naive to"),
        ({"from": "2026-01-01T00:00:00Z", "to": "2026-07-01T00:00:00Z"}, "range over 90 days"),
        ({"from": "2026-07-02T00:00:00Z", "to": "2026-07-01T00:00:00Z"}, "reversed range"),
        ({"limit": "0"}, "limit below one"),
        ({"limit": "201"}, "limit over the cap"),
        ({"cursor": "tampered"}, "malformed cursor"),
    ],
)
async def test_out_of_bounds_query_is_422(api: tuple, params: dict, why: str) -> None:
    client, maker = api
    _, headers = await _actor(client, maker)
    resp = await client.get("/api/audit", params=params, headers=headers)
    assert resp.status_code == 422, f"{why} was accepted: {resp.text}"
    assert resp.json()["error"]["code"] == "INVALID_QUERY"


# --------------------------------------------------------------------------- #
# Paging
# --------------------------------------------------------------------------- #


async def test_pages_are_newest_first_and_cover_every_row_exactly_once(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    ids = [
        await _row(maker, audit.USER_LOGOUT, at=BASE - timedelta(minutes=n), user_id=actor_id)
        for n in range(5)
    ]

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params = {**_window(), "limit": "2"}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get("/api/audit", params=params, headers=headers)).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None, "paging did not terminate"
    assert seen == [str(entry_id) for entry_id in ids], "order or coverage differs"
    assert len(set(seen)) == len(seen), "a row was returned twice"


async def test_rows_written_mid_walk_do_not_shift_the_remaining_pages(api: tuple) -> None:
    """The reason for keyset paging. With OFFSET, a row inserted after page one is
    fetched pushes the window down and page two repeats a row already shown."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    original = [
        await _row(maker, audit.USER_LOGOUT, at=BASE - timedelta(minutes=n), user_id=actor_id)
        for n in range(4)
    ]

    first = (
        await client.get("/api/audit", params={**_window(), "limit": "2"}, headers=headers)
    ).json()
    assert [item["id"] for item in first["items"]] == [str(i) for i in original[:2]]

    # A newer row arrives between the two requests.
    await _row(maker, audit.USER_LOGOUT, at=BASE + timedelta(minutes=1), user_id=actor_id)

    second = (
        await client.get(
            "/api/audit",
            params={**_window(), "limit": "2", "cursor": first["next_cursor"]},
            headers=headers,
        )
    ).json()
    assert [item["id"] for item in second["items"]] == [str(i) for i in original[2:]]


async def test_rows_sharing_an_instant_are_paged_without_loss(api: tuple) -> None:
    """`created_at` is not unique: rows written in one transaction share it. The
    tiebreak on `id` is what keeps such a group pageable."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    async with maker() as session:
        entries = [
            AuditLog(action=audit.USER_LOGOUT, user_id=actor_id, audit_metadata={}, created_at=BASE)
            for _ in range(3)
        ]
        session.add_all(entries)
        await session.commit()
        expected = sorted((str(entry.id) for entry in entries), reverse=True)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(4):
        params = {**_window(), "limit": "1"}
        if cursor:
            params["cursor"] = cursor
        body = (await client.get("/api/audit", params=params, headers=headers)).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == expected


async def test_exhausted_window_reports_no_next_cursor(api: tuple) -> None:
    """A `next_cursor` on the last page would make a client fetch an empty page and
    then have to decide whether that meant "done" or "transient failure"."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=actor_id)
    body = (
        await client.get("/api/audit", params={**_window(), "limit": "5"}, headers=headers)
    ).json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is None


async def test_empty_result_is_an_empty_list_not_an_error(api: tuple) -> None:
    """ "No records under this filter" is a legitimate answer with its own UI state;
    404 would make the view render a failure instead."""
    client, maker = api
    _, headers = await _actor(client, maker)
    resp = await client.get(
        "/api/audit", params={**_window(), "action": audit.SESSION_FAILED}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


# --------------------------------------------------------------------------- #
# Item shape, joins and leakage
# --------------------------------------------------------------------------- #


async def test_item_carries_resolved_names_and_a_promoted_request_id(api: tuple) -> None:
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    node_id = await _node(maker, "build-01")
    await _row(
        maker,
        audit.NODE_DISABLE,
        at=BASE,
        user_id=actor_id,
        node_id=node_id,
        metadata={"request_id": "01K0RID", "reason": "maintenance"},
    )
    item = (await client.get("/api/audit", params=_window(), headers=headers)).json()["items"][0]

    assert item["actor"]["id"] == str(actor_id)
    assert item["actor"]["username"]
    assert item["node"] == {"id": str(node_id), "name": "build-01"}
    assert item["request_id"] == "01K0RID"
    # Promoted to its own field, so it is not repeated inside the metadata blob.
    assert item["metadata"] == {"reason": "maintenance"}
    assert item["created_at"].endswith("Z") or "+00:00" in item["created_at"]


async def test_a_row_without_an_actor_reports_null_rather_than_being_hidden(api: tuple) -> None:
    """System- and daemon-initiated events have no actor. Filtering them out would
    quietly shorten the trail; inventing an actor would be worse."""
    client, maker = api
    _, headers = await _actor(client, maker)
    await _row(maker, audit.NODE_REGISTER, at=BASE, metadata={"source": "daemon"})
    item = (await client.get("/api/audit", params=_window(), headers=headers)).json()["items"][0]
    assert item["actor"] is None
    assert item["node"] is None
    assert item["request_id"] is None


async def test_ids_that_no_longer_resolve_keep_the_row_with_null_names(api: tuple) -> None:
    """`audit_logs` holds ids without a foreign key precisely so history survives
    deletion. An inner join here would erase those rows from the trail."""
    client, maker = api
    _, headers = await _actor(client, maker)
    await _row(maker, audit.NODE_REMOVE, at=BASE, user_id=uuid.uuid4(), node_id=uuid.uuid4())
    item = (await client.get("/api/audit", params=_window(), headers=headers)).json()["items"][0]
    assert item["actor"]["username"] is None
    assert item["actor"]["display_name"] is None
    assert item["node"]["name"] is None


async def test_a_soft_deleted_node_still_resolves_its_name(api: tuple) -> None:
    """Node removal is a soft delete (ADR 0011); the audit view must still be able
    to say which node the event was about."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    node_id = await _node(maker, "retired")
    async with maker() as session:
        await session.execute(sa.update(Node).where(Node.id == node_id).values(deleted_at=BASE))
        await session.commit()
    await _row(maker, audit.NODE_REMOVE, at=BASE, user_id=actor_id, node_id=node_id)
    item = (await client.get("/api/audit", params=_window(), headers=headers)).json()["items"][0]
    assert item["node"]["name"] == "retired"


@pytest.mark.parametrize("key", ["password", "token", "content", "rel_path", "private_key"])
async def test_a_forbidden_key_already_in_the_table_is_not_served(api: tuple, key: str) -> None:
    """Rows written before the minimization rule — or by a future bug — must not be
    published just because they are stored."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=actor_id, metadata={key: "leak", "ok": 1})
    resp = await client.get("/api/audit", params=_window(), headers=headers)
    assert "leak" not in resp.text
    assert resp.json()["items"][0]["metadata"] == {"ok": 1}


async def test_reading_the_trail_writes_no_audit_row(api: tuple) -> None:
    """ADR 0016: an Admin reviewing the trail would otherwise inflate the thing
    they are reviewing, and the read is already in the request log."""
    client, maker = api
    actor_id, headers = await _actor(client, maker)
    await _row(maker, audit.USER_LOGOUT, at=BASE, user_id=actor_id)
    before = await _audit_count(maker)

    for _ in range(3):
        assert (
            await client.get("/api/audit", params=_window(), headers=headers)
        ).status_code == 200

    assert await _audit_count(maker) == before


async def test_a_refused_read_is_not_audited_either(api: tuple) -> None:
    """Only mutations and cross-owner attempts are security events (ADR 0016); a
    plain read 403 would bury that signal in noise."""
    client, maker = api
    _, developer = await _actor(client, maker, "Developer")
    before = await _audit_count(maker)
    assert (await client.get("/api/audit", headers=developer)).status_code == 403
    async with maker() as session:
        denials = (
            await session.execute(
                sa.select(sa.func.count(AuditLog.id)).where(AuditLog.action == audit.AUTHZ_DENIED)
            )
        ).scalar_one()
    assert denials == 0
    assert await _audit_count(maker) == before
