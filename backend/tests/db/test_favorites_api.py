"""Workspace favourites and recents over the real schema (P4-13, FR-WORKSPACE-004/005).

The premise these tests exist to defend: **a favourite is a UX shortcut, never an
authorization source.** So the interesting cases are not "can I save a path" but:

* a path that could not start a session cannot be *stored*, and storing it leaves no row;
* a favourite that was valid when saved stops claiming to be usable once its root, node,
  or connection goes away — the verdict is recomputed on every read, never cached;
* one user's list is invisible and unreachable from another's, including by id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.http.favorites import get_registry
from app.db.models import (
    Node,
    NodeRuntime,
    NodeWorkspaceRoot,
    Role,
    TerminalSession,
    User,
    WorkspaceFavorite,
)
from app.main import app
from app.security.passwords import hash_password

pytestmark = pytest.mark.asyncio

FAVORITES = "/api/workspaces/favorites"
RECENT = "/api/workspaces/recent"


class FakeRegistry:
    """Heartbeat ages by node. A node absent from the map has never been seen."""

    def __init__(self, ages: dict[uuid.UUID, float] | None = None, *, default: float | None = 1.0):
        self._ages = ages or {}
        self._default = default

    def seconds_since_heartbeat(self, node_id: uuid.UUID) -> float | None:
        return self._ages.get(node_id, self._default)


def _use_registry(fake: FakeRegistry) -> None:
    app.dependency_overrides[get_registry] = lambda: fake


@pytest.fixture(autouse=True)
def _online_by_default() -> object:
    """Default every node to freshly-seen, so a test that is not about liveness does not
    have to say so. Liveness tests override it explicitly."""
    _use_registry(FakeRegistry())
    yield
    app.dependency_overrides.pop(get_registry, None)


async def _login(
    client: AsyncClient, maker: async_sessionmaker, *, role_name: str = "Developer"
) -> tuple[dict[str, str], uuid.UUID]:
    username = f"u-{uuid.uuid4().hex[:8]}"
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
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}, user_id


async def _make_node(
    maker: async_sessionmaker, *, roots: tuple[str, ...] = ("/home/neil/projects",)
) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path=p, is_enabled=True) for p in roots]
        session.add(node)
        await session.commit()
        return node.id


async def _count(maker: async_sessionmaker) -> int:
    async with maker() as session:
        return int(
            (await session.execute(sa.select(sa.func.count(WorkspaceFavorite.id)))).scalar_one()
        )


# --------------------------------------------------------------------------- #
# A favourite grants nothing: the same gate as creating a session
# --------------------------------------------------------------------------- #


async def test_a_path_outside_the_allowed_roots_cannot_be_stored(api: tuple) -> None:
    """The core anti-goal. If this passed, a favourite would be a way to persist an
    unauthorized path and hand it back to the session-create path later."""
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    resp = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": "/etc"}, headers=headers
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "WORKSPACE_OUTSIDE_ALLOWED_ROOT"
    # Rejection must leave nothing behind: a stored-but-refused row would still be a
    # stored path outside the root, waiting for a future check to be laxer.
    assert await _count(maker) == 0


async def test_a_prefix_collision_is_not_treated_as_a_root(api: tuple) -> None:
    """`/home/neil/projects-other` is not inside `/home/neil/projects`, even though it
    starts with the same characters. Asserted here as well as on the session path because
    this is the exact bug a second copy of the prefix rule would reintroduce."""
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    resp = await client.post(
        FAVORITES,
        json={"node_id": str(node_id), "path": "/home/neil/projects-other/x"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert await _count(maker) == 0


@pytest.mark.parametrize(
    ("path", "why"),
    [
        ("/home/neil/projects/../../etc", "traversal segment"),
        ("relative/path", "not absolute"),
        ("/home/neil/projects/a\x00b", "NUL byte"),
        ("/home/neil/projects/a\nb", "newline"),
        ("/home/neil/projects/a\tb", "tab"),
    ],
)
async def test_malformed_paths_are_refused(api: tuple, path: str, why: str) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    resp = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": path}, headers=headers
    )
    assert resp.status_code == 422, f"{why}: {resp.text}"
    assert await _count(maker) == 0


async def test_a_directory_named_with_leading_dots_is_allowed(api: tuple) -> None:
    """The `..` check is on segments, not substrings: `..config` is a legal directory
    name and refusing it would be a bug dressed up as security."""
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    resp = await client.post(
        FAVORITES,
        json={"node_id": str(node_id), "path": "/home/neil/projects/..config"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_a_disabled_node_refuses_new_favourites(api: tuple) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    async with maker() as session:
        await session.execute(sa.update(Node).where(Node.id == node_id).values(is_enabled=False))
        await session.commit()
    resp = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": "/home/neil/projects/a"}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "NODE_DISABLED"


async def test_an_unknown_node_is_404(api: tuple) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    resp = await client.post(
        FAVORITES,
        json={"node_id": str(uuid.uuid4()), "path": "/home/neil/projects/a"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


# --------------------------------------------------------------------------- #
# Idempotency and bounds
# --------------------------------------------------------------------------- #


async def test_favouriting_twice_is_the_same_favourite(api: tuple) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    body = {"node_id": str(node_id), "path": "/home/neil/projects/app", "display_name": "App"}
    first = await client.post(FAVORITES, json=body, headers=headers)
    second = await client.post(FAVORITES, json=body, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert await _count(maker) == 1


async def test_re_favouriting_updates_the_display_name(api: tuple) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    path = "/home/neil/projects/app"
    await client.post(
        FAVORITES,
        json={"node_id": str(node_id), "path": path, "display_name": "Old"},
        headers=headers,
    )
    resp = await client.post(
        FAVORITES,
        json={"node_id": str(node_id), "path": path, "display_name": "New"},
        headers=headers,
    )
    assert resp.json()["display_name"] == "New"
    assert await _count(maker) == 1


async def test_the_same_path_on_two_nodes_is_two_favourites(api: tuple) -> None:
    """Uniqueness is `(user, node, path)`. `/home/neil/projects/app` on two machines is
    two different places."""
    client, maker = api
    headers, _ = await _login(client, maker)
    first_node = await _make_node(maker)
    second_node = await _make_node(maker)
    path = "/home/neil/projects/app"
    for node_id in (first_node, second_node):
        resp = await client.post(
            FAVORITES, json={"node_id": str(node_id), "path": path}, headers=headers
        )
        assert resp.status_code == 200, resp.text
    assert await _count(maker) == 2


async def test_the_per_user_cap_is_enforced(api: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import favorites as favorites_service

    monkeypatch.setattr(favorites_service, "MAX_FAVORITES", 2)
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    for index in range(2):
        resp = await client.post(
            FAVORITES,
            json={"node_id": str(node_id), "path": f"/home/neil/projects/p{index}"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
    over = await client.post(
        FAVORITES,
        json={"node_id": str(node_id), "path": "/home/neil/projects/p2"},
        headers=headers,
    )
    assert over.status_code == 422, over.text
    assert await _count(maker) == 2


# --------------------------------------------------------------------------- #
# Owner isolation
# --------------------------------------------------------------------------- #


async def test_one_users_favourites_are_invisible_to_another(api: tuple) -> None:
    client, maker = api
    mine, _ = await _login(client, maker)
    theirs, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    created = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": "/home/neil/projects/app"}, headers=mine
    )
    assert created.status_code == 200
    assert [f["id"] for f in (await client.get(FAVORITES, headers=mine)).json()] == [
        created.json()["id"]
    ]
    assert (await client.get(FAVORITES, headers=theirs)).json() == []


async def test_deleting_another_users_favourite_is_404_not_403(api: tuple) -> None:
    """404, so the response cannot be used to confirm that an id exists. A 403 here would
    turn the delete endpoint into an oracle for other users' favourite ids."""
    client, maker = api
    mine, _ = await _login(client, maker)
    theirs, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    created = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": "/home/neil/projects/app"}, headers=mine
    )
    favorite_id = created.json()["id"]

    foreign = await client.delete(f"{FAVORITES}/{favorite_id}", headers=theirs)
    fictional = await client.delete(f"{FAVORITES}/{uuid.uuid4()}", headers=theirs)
    assert foreign.status_code == fictional.status_code == 404
    # Indistinguishable down to the error body — an identical status with a different
    # message would leak exactly what the status hides. (`request_id` is per-request
    # correlation and is expected to differ.)
    assert foreign.json()["error"] == fictional.json()["error"]
    assert await _count(maker) == 1  # and it is still there

    assert (await client.delete(f"{FAVORITES}/{favorite_id}", headers=mine)).status_code == 204
    assert await _count(maker) == 0


async def test_a_viewer_cannot_use_the_shortcuts(api: tuple) -> None:
    """Gated on `session.create` (ADR 0016): a Viewer cannot start a session, so there is
    nothing for them to shortcut."""
    client, maker = api
    headers, _ = await _login(client, maker, role_name="Viewer")
    node_id = await _make_node(maker)
    assert (await client.get(FAVORITES, headers=headers)).status_code == 403
    assert (await client.get(RECENT, headers=headers)).status_code == 403
    post = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": "/home/neil/projects/a"}, headers=headers
    )
    assert post.status_code == 403
    assert await _count(maker) == 0


# --------------------------------------------------------------------------- #
# The verdict is recomputed, never cached
# --------------------------------------------------------------------------- #


async def _favourite(client: AsyncClient, headers: dict, node_id: uuid.UUID, path: str) -> str:
    resp = await client.post(
        FAVORITES, json={"node_id": str(node_id), "path": path}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["usability"] == "usable"
    return resp.json()["id"]


async def test_create_reports_the_same_verdict_as_the_next_listing(api: tuple) -> None:
    """Found by a live smoke, not by a unit test: the create response hard-coded
    `usable`, so favouriting a path on an offline node answered `usable` and the very
    next GET answered `node_offline` for the same row. The optimistic star in the UI
    would flip a moment later for no reason the user could see.

    Favouriting an offline node is *allowed* on purpose — bookmarking is not starting a
    session — which is exactly why the response cannot assume usability.
    """
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    _use_registry(FakeRegistry(default=None))  # node never seen

    created = await client.post(
        FAVORITES,
        json={"node_id": str(node_id), "path": "/home/neil/projects/app"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    listed = (await client.get(FAVORITES, headers=headers)).json()

    assert created.json()["usability"] == "node_offline"
    assert created.json() == listed[0]


async def test_removing_the_root_makes_a_stored_favourite_unusable(api: tuple) -> None:
    """The case that makes storing the verdict wrong. The favourite was legitimate when
    saved; after the root is withdrawn it must not keep saying so."""
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")

    async with maker() as session:
        await session.execute(
            sa.update(NodeWorkspaceRoot)
            .where(NodeWorkspaceRoot.node_id == node_id)
            .values(is_enabled=False)
        )
        await session.commit()

    listed = (await client.get(FAVORITES, headers=headers)).json()
    # Still listed — silently dropping it would read as data loss — but with the reason.
    assert [f["usability"] for f in listed] == ["outside_allowed_root"]


async def test_disabling_the_node_makes_a_stored_favourite_unusable(api: tuple) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")
    async with maker() as session:
        await session.execute(sa.update(Node).where(Node.id == node_id).values(is_enabled=False))
        await session.commit()
    assert [f["usability"] for f in (await client.get(FAVORITES, headers=headers)).json()] == [
        "node_disabled"
    ]


async def test_an_offline_node_is_reported_offline_not_hidden(api: tuple) -> None:
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")
    _use_registry(FakeRegistry(default=None))  # never seen
    assert [f["usability"] for f in (await client.get(FAVORITES, headers=headers)).json()] == [
        "node_offline"
    ]


async def test_a_lost_root_outranks_a_lost_connection(api: tuple) -> None:
    """Reasons are ordered by permanence. Reporting `node_offline` for a favourite whose
    root is gone would have the user wait for a recovery that fixes nothing."""
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")
    async with maker() as session:
        await session.execute(
            sa.update(NodeWorkspaceRoot)
            .where(NodeWorkspaceRoot.node_id == node_id)
            .values(is_enabled=False)
        )
        await session.commit()
    _use_registry(FakeRegistry(default=None))
    assert [f["usability"] for f in (await client.get(FAVORITES, headers=headers)).json()] == [
        "outside_allowed_root"
    ]


async def test_a_soft_deleted_node_drops_out_of_the_list(api: tuple) -> None:
    """A removed node is different from a broken favourite: there is no machine to go
    back to, and no action the user could take, so the entry goes rather than nagging."""
    client, maker = api
    headers, _ = await _login(client, maker)
    node_id = await _make_node(maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")
    async with maker() as session:
        await session.execute(
            sa.update(Node).where(Node.id == node_id).values(deleted_at=datetime.now(UTC))
        )
        await session.commit()
    assert (await client.get(FAVORITES, headers=headers)).json() == []


# --------------------------------------------------------------------------- #
# Recents: derived from session history, not a table
# --------------------------------------------------------------------------- #


async def _session_row(
    maker: async_sessionmaker,
    *,
    user_id: uuid.UUID,
    node_id: uuid.UUID,
    workspace: str,
    created_at: datetime,
    status: str = "running",
) -> None:
    async with maker() as session:
        session.add(
            TerminalSession(
                node_id=node_id,
                user_id=user_id,
                name="s",
                runtime="claude",
                workspace=workspace,
                status=status,
                created_at=created_at,
            )
        )
        await session.commit()


async def test_recent_is_distinct_newest_first_and_counts_ended_sessions(api: tuple) -> None:
    """Three properties in one history because they are properties of the same query:

    * repeated use of one workspace is one entry, at its most recent time;
    * ordering is by that most recent time, newest first;
    * a **terminated** session still counts — "recently used" is history, and returning
      to somewhere you finished working is the entire use case.
    """
    client, maker = api
    headers, user_id = await _login(client, maker)
    node_id = await _make_node(maker)
    base = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await _session_row(
        maker,
        user_id=user_id,
        node_id=node_id,
        workspace="/home/neil/projects/old",
        created_at=base,
        status="exited",
    )
    await _session_row(
        maker,
        user_id=user_id,
        node_id=node_id,
        workspace="/home/neil/projects/app",
        created_at=base + timedelta(hours=1),
        status="exited",
    )
    await _session_row(
        maker,
        user_id=user_id,
        node_id=node_id,
        workspace="/home/neil/projects/app",
        created_at=base + timedelta(hours=2),
    )

    items = (await client.get(RECENT, headers=headers)).json()
    assert [i["path"] for i in items] == ["/home/neil/projects/app", "/home/neil/projects/old"]
    assert items[0]["last_used_at"].startswith("2026-06-01T14:00")


async def test_recent_shows_only_the_callers_own_history(api: tuple) -> None:
    client, maker = api
    mine, my_id = await _login(client, maker)
    theirs, their_id = await _login(client, maker)
    node_id = await _make_node(maker)
    at = datetime(2026, 6, 1, tzinfo=UTC)
    await _session_row(
        maker,
        user_id=their_id,
        node_id=node_id,
        workspace="/home/neil/projects/theirs",
        created_at=at,
    )
    assert (await client.get(RECENT, headers=mine)).json() == []
    assert [i["path"] for i in (await client.get(RECENT, headers=theirs)).json()] == [
        "/home/neil/projects/theirs"
    ]
    assert my_id != their_id


async def test_recent_is_bounded(api: tuple) -> None:
    """The default is small and the cap is hard: without one, a long-lived account turns
    a shortcut row into an unbounded response."""
    client, maker = api
    headers, user_id = await _login(client, maker)
    node_id = await _make_node(maker)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    for index in range(8):
        await _session_row(
            maker,
            user_id=user_id,
            node_id=node_id,
            workspace=f"/home/neil/projects/p{index}",
            created_at=base + timedelta(minutes=index),
        )
    assert len((await client.get(RECENT, headers=headers)).json()) == 5  # default
    assert len((await client.get(f"{RECENT}?limit=2", headers=headers)).json()) == 2
    # Beyond the cap the request is refused rather than silently narrowed, so a caller
    # cannot believe it received everything.
    assert (await client.get(f"{RECENT}?limit=999", headers=headers)).status_code == 422
    assert (await client.get(f"{RECENT}?limit=0", headers=headers)).status_code == 422


async def test_recent_reports_liveness_without_hiding_entries(api: tuple) -> None:
    client, maker = api
    headers, user_id = await _login(client, maker)
    online = await _make_node(maker)
    offline = await _make_node(maker)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    await _session_row(
        maker, user_id=user_id, node_id=online, workspace="/home/neil/projects/a", created_at=base
    )
    await _session_row(
        maker,
        user_id=user_id,
        node_id=offline,
        workspace="/home/neil/projects/b",
        created_at=base - timedelta(hours=1),
    )
    _use_registry(FakeRegistry({online: 1.0}, default=None))
    items = (await client.get(RECENT, headers=headers)).json()
    assert [(i["path"], i["node_online"]) for i in items] == [
        ("/home/neil/projects/a", True),
        ("/home/neil/projects/b", False),
    ]


async def test_recent_excludes_soft_deleted_nodes(api: tuple) -> None:
    client, maker = api
    headers, user_id = await _login(client, maker)
    node_id = await _make_node(maker)
    await _session_row(
        maker,
        user_id=user_id,
        node_id=node_id,
        workspace="/home/neil/projects/a",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    async with maker() as session:
        await session.execute(
            sa.update(Node).where(Node.id == node_id).values(deleted_at=datetime.now(UTC))
        )
        await session.commit()
    assert (await client.get(RECENT, headers=headers)).json() == []


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


async def test_favourites_are_removed_with_their_user_and_node(api: tuple) -> None:
    """Both FKs cascade. A favourite is meaningless without either end, and leaving
    orphans behind would keep one user's stored paths after their account is gone."""
    client, maker = api
    headers, user_id = await _login(client, maker)
    node_id = await _make_node(maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")
    async with maker() as session:
        await session.execute(sa.delete(User).where(User.id == user_id))
        await session.commit()
    assert await _count(maker) == 0

    headers, _ = await _login(client, maker)
    await _favourite(client, headers, node_id, "/home/neil/projects/app")
    async with maker() as session:
        await session.execute(sa.delete(Node).where(Node.id == node_id))
        await session.commit()
    assert await _count(maker) == 0
