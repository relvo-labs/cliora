"""No session-existence oracle for callers without `session.view` (issue #93).

ADR 0016: "Where a resource may legitimately be absent, `session.view` is
evaluated first and only then may a 404 be returned; otherwise 403." Before the
fix, a custom role that held a route's own action (`file.browse`,
`session.terminate`, `terminal.shell`, `file.upload`) but not `session.view` got
`404 SESSION_NOT_FOUND` for a random id and `403 FORBIDDEN` for a real one.

Every session-id route is exercised for three targets — a session owned by
someone else, a session owned by the caller, and a random UUID — and the status
and error body (minus the per-request `request_id`) must be identical. The route
list is checked against the mounted app so a new session-scoped route cannot be
added without deciding its answer here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import WebSocket
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.http.sessions import attach_resource
from app.api.ws.terminal import terminal_gateway
from app.db.models import Node, NodeWorkspaceRoot, Role, TerminalSession, User
from app.main import app
from app.repositories.sessions import SessionRepository
from app.security.passwords import hash_password
from app.services import ws_ticket
from app.services.rbac import ROLE_ACTIONS, SESSION_VIEW
from app.services.ws_ticket import WsTicketService

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

# (method, path under /api/sessions/{sid}, request kwargs). Bodies and queries are
# valid, so nothing but authorization or existence can decide the answer.
_ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "", {}),
    ("DELETE", "", {}),
    ("POST", "/terminate", {}),
    ("POST", "/shell", {"json": {"rows": 40, "columns": 120}}),
    ("POST", "/attach", {}),
    ("GET", "/files/tree", {"params": {"path": "."}}),
    ("GET", "/files/search", {"params": {"keyword": "main"}}),
    ("GET", "/files/content", {"params": {"path": "main.py"}}),
    ("GET", "/files/download", {"params": {"path": "main.py"}}),
    (
        "POST",
        "/files/images",
        {"content": _PNG, "headers": {"Content-Type": "image/png"}},
    ),
    ("POST", "/files/upload", {"params": {"filename": "a.txt"}, "content": b"x"}),
    ("POST", "/files/binary-preview", {"json": {"path": "a.png"}}),
]
_ROUTE_IDS = [f"{m} {p or '/'}" for m, p, _ in _ROUTES]

# Custom roles without `session.view`:
# * every other action, so each route's own `require_action()` passes and only the
#   session-scope order decides — the case that leaked;
# * Developer's actions, which lack `node.manage`, so on base the ownership scope
#   check refused a colleague's session while the caller's own went through;
# * nothing at all, so the action guard refuses before any lookup.
_ALL_BUT_VIEW = sorted(ROLE_ACTIONS["Admin"] - {SESSION_VIEW})
_NO_VIEW_ROLES = {
    "all-but-session.view": _ALL_BUT_VIEW,
    "developer-without-session.view": sorted(ROLE_ACTIONS["Developer"] - {SESSION_VIEW}),
    "no-actions": [],
}


def test_route_table_covers_every_mounted_session_id_route() -> None:
    mounted = {
        (method, route.path.removeprefix("/api/sessions/{session_id}"))
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/sessions/{session_id}")
        for method in route.methods
    }
    assert mounted == {(m, p) for m, p, _ in _ROUTES}


async def _user(
    client: AsyncClient, maker: async_sessionmaker, actions: list[str] | None, role_name: str = ""
) -> tuple[dict[str, str], uuid.UUID]:
    """Log in a user holding a built-in role (`role_name`) or a custom one (`actions`)."""
    username = f"u-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        if actions is None:
            role = (
                await session.execute(sa.select(Role).where(Role.name == role_name))
            ).scalar_one()
        else:
            role = Role(name=f"oracle-{uuid.uuid4().hex[:8]}", permissions={"actions": actions})
            session.add(role)
            await session.flush()
        user = User(
            username=username,
            password_hash=hash_password("pw"),
            display_name=username,
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        uid = user.id
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}, uid


@pytest_asyncio.fixture
async def drop_custom_roles(db_url: str) -> AsyncIterator[None]:
    """Remove the roles these tests create. Requested *before* `api` so it tears
    down after it: `api` clears users (which reference roles) but keeps roles,
    because those are migration seed."""
    yield
    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.delete(Role).where(Role.name.like("oracle-%")))
    finally:
        await engine.dispose()


async def _session_row(maker: async_sessionmaker, owner_id: uuid.UUID) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.flush()
        ts = TerminalSession(
            node_id=node.id,
            user_id=owner_id,
            name="s1",
            runtime="claude",
            workspace="/home/neil/projects/app",
            status="running",
            rows=40,
            columns=120,
        )
        session.add(ts)
        await session.commit()
        return ts.id


async def _call(
    client: AsyncClient, method: str, sid: uuid.UUID, path: str, kwargs: dict[str, Any], headers
) -> tuple[int, dict[str, Any]]:
    extra = dict(kwargs)
    merged = {**headers, **extra.pop("headers", {})}
    resp = await client.request(method, f"/api/sessions/{sid}{path}", headers=merged, **extra)
    body = resp.json() if resp.content else {}
    body.pop("request_id", None)  # differs per request by design
    return resp.status_code, body


@pytest.mark.parametrize("role", list(_NO_VIEW_ROLES))
@pytest.mark.parametrize(("method", "path", "kwargs"), _ROUTES, ids=_ROUTE_IDS)
async def test_without_session_view_existence_cannot_be_probed(
    drop_custom_roles: None, api: tuple, role: str, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    client, maker = api
    _, other_id = await _user(client, maker, None, role_name="Admin")
    headers, uid = await _user(client, maker, _NO_VIEW_ROLES[role])
    theirs = await _session_row(maker, other_id)
    mine = await _session_row(maker, uid)

    answers = {
        "someone else's": await _call(client, method, theirs, path, kwargs, headers),
        "the caller's own": await _call(client, method, mine, path, kwargs, headers),
        "a random id": await _call(client, method, uuid.uuid4(), path, kwargs, headers),
    }
    expected = (
        403,
        {"error": {"code": "FORBIDDEN", "message": "You do not have permission for this action"}},
    )
    assert answers == dict.fromkeys(answers, expected)


@pytest.mark.parametrize(("method", "path", "kwargs"), _ROUTES, ids=_ROUTE_IDS)
async def test_a_permitted_caller_still_gets_404_for_a_missing_session(
    api: tuple, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    client, maker = api
    headers, _ = await _user(client, maker, None, role_name="Admin")
    status, body = await _call(client, method, uuid.uuid4(), path, kwargs, headers)
    assert (status, body["error"]["code"]) == (404, "SESSION_NOT_FOUND")


async def test_a_permitted_caller_still_reaches_an_existing_session(api: tuple) -> None:
    """Behaviour for `session.view` holders is unchanged: Viewer reads and attaches,
    and a Developer is still refused (403) on a colleague's session it may see but
    not act on — existence is not secret from someone who can list the fleet."""
    client, maker = api
    viewer, _ = await _user(client, maker, None, role_name="Viewer")
    developer, _ = await _user(client, maker, None, role_name="Developer")
    _, admin_id = await _user(client, maker, None, role_name="Admin")
    sid = await _session_row(maker, admin_id)

    assert (await client.get(f"/api/sessions/{sid}", headers=viewer)).status_code == 200
    assert (await client.post(f"/api/sessions/{sid}/attach", headers=viewer)).status_code == 200
    refused = await client.post(f"/api/sessions/{sid}/terminate", headers=developer)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"


class _FakeWebSocket:
    def __init__(self, ticket: str) -> None:
        self.query_params = {"ticket": ticket}
        self.closed_with: int | None = None
        self.sent: list[object] = []

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)


async def _shell_row(maker: async_sessionmaker, parent_id: uuid.UUID) -> uuid.UUID:
    """A system terminal inside `parent_id`, owned by the parent's owner (ADR 0021)."""
    async with maker() as session:
        parent = await session.get(TerminalSession, parent_id)
        assert parent is not None
        ts = TerminalSession(
            node_id=parent.node_id,
            user_id=parent.user_id,
            parent_session_id=parent.id,
            name="shell",
            runtime="shell",
            workspace=parent.workspace,
            status="running",
            rows=40,
            columns=120,
        )
        session.add(ts)
        await session.commit()
        return ts.id


async def _mint(client: AsyncClient, headers: dict[str, str], sid: uuid.UUID) -> str:
    resp = await client.post(
        "/api/ws-ticket", json={"resource": attach_resource(sid)}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["ticket"])


class _LookupSpy:
    """Records every session-id lookup, whichever service makes it.

    Both `SessionService.get` and the file relay's resolution go through
    `SessionRepository.get`, so one spy sees every route's lookup.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[uuid.UUID] = []
        original = SessionRepository.get

        async def spy(repo: SessionRepository, session_id: uuid.UUID) -> Any:
            self.calls.append(session_id)
            return await original(repo, session_id)

        monkeypatch.setattr(SessionRepository, "get", spy)


async def test_terminal_websocket_closes_identically_without_session_view(
    drop_custom_roles: None, api: tuple
) -> None:
    """The handshake refuses every target the same way: 1008, nothing sent.

    Inject tickets below the HTTP boundary to exercise the independent handshake
    guard, including legacy tickets and permissions revoked after issuance.
    HTTP issuance denial is covered separately below. The owned shell leaked
    on base: a shell was owner-only *instead of* needing `session.view`, so the
    owner got past the view check and on to the node check (1011) or a live
    subscription.
    """
    client, maker = api
    _, other_id = await _user(client, maker, None, role_name="Admin")
    _, uid = await _user(client, maker, _ALL_BUT_VIEW)
    own_cli = await _session_row(maker, uid)
    targets = {
        "someone else's": await _session_row(maker, other_id),
        "the caller's own CLI": own_cli,
        "the caller's own shell": await _shell_row(maker, own_cli),
        "a random id": uuid.uuid4(),
    }
    outcomes = {}
    for label, sid in targets.items():
        ws = _FakeWebSocket(ws_ticket.get_ws_ticket_service().issue(uid, attach_resource(sid)))
        async with maker() as session:
            await terminal_gateway(cast(WebSocket, ws), sid, session)
        outcomes[label] = (ws.closed_with, ws.sent)
    assert outcomes == dict.fromkeys(outcomes, (1008, []))


async def test_terminal_websocket_checks_session_view_before_any_lookup(
    drop_custom_roles: None, api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, maker = api
    _, uid = await _user(client, maker, _ALL_BUT_VIEW)
    own_cli = await _session_row(maker, uid)
    spy = _LookupSpy(monkeypatch)
    for sid in (own_cli, await _shell_row(maker, own_cli), uuid.uuid4()):
        ws = _FakeWebSocket(ws_ticket.get_ws_ticket_service().issue(uid, attach_resource(sid)))
        async with maker() as session:
            await terminal_gateway(cast(WebSocket, ws), sid, session)
        assert (ws.closed_with, ws.sent) == (1008, [])
    assert spy.calls == []


async def test_terminal_websocket_still_looks_up_for_a_session_view_holder(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spy is not vacuous: with `session.view` the handshake does resolve the
    id, and a missing one still closes 1008."""
    client, maker = api
    _, uid = await _user(client, maker, None, role_name="Viewer")
    spy = _LookupSpy(monkeypatch)
    sid = uuid.uuid4()
    ws = _FakeWebSocket(ws_ticket.get_ws_ticket_service().issue(uid, attach_resource(sid)))
    async with maker() as session:
        await terminal_gateway(cast(WebSocket, ws), sid, session)
    assert (ws.closed_with, ws.sent, spy.calls) == (1008, [], [sid])


@pytest.mark.parametrize(("method", "path", "kwargs"), _ROUTES, ids=_ROUTE_IDS)
async def test_http_routes_check_session_view_before_any_lookup(
    drop_custom_roles: None,
    api: tuple,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    kwargs: dict[str, Any],
) -> None:
    client, maker = api
    headers, uid = await _user(client, maker, _ALL_BUT_VIEW)
    own = await _session_row(maker, uid)
    spy = _LookupSpy(monkeypatch)
    for sid in (own, uuid.uuid4()):
        status, _ = await _call(client, method, sid, path, kwargs, headers)
        assert status == 403
    assert spy.calls == []


async def test_ws_ticket_issuance_does_not_depend_on_existence(
    drop_custom_roles: None, api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller without session.view gets uniform refusal before any lookup."""
    client, maker = api
    headers, uid = await _user(client, maker, _ALL_BUT_VIEW)
    own = await _session_row(maker, uid)
    spy = _LookupSpy(monkeypatch)
    answers = []
    for sid in (own, uuid.uuid4()):
        resp = await client.post(
            "/api/ws-ticket", json={"resource": attach_resource(sid)}, headers=headers
        )
        answers.append((resp.status_code, resp.json()["error"]))
    assert (
        answers
        == [(403, {"code": "FORBIDDEN", "message": "You do not have permission for this action"})]
        * 2
    )
    assert spy.calls == []


@pytest.fixture(autouse=True)
def isolated_tickets(monkeypatch: pytest.MonkeyPatch) -> WsTicketService:
    service = WsTicketService(60)
    monkeypatch.setattr(ws_ticket, "_service", service)
    return service


@pytest.mark.parametrize("role", ["Admin", "Developer", "Viewer"])
async def test_ticket_refuses_another_users_shell_without_issuing(
    api: tuple, isolated_tickets: WsTicketService, role: str
) -> None:
    client, maker = api
    _, owner = await _user(client, maker, None, role_name="Developer")
    headers, _ = await _user(client, maker, None, role_name=role)
    shell = await _shell_row(maker, await _session_row(maker, owner))
    for endpoint, kwargs in (
        ("/api/ws-ticket", {"json": {"resource": attach_resource(shell)}}),
        (f"/api/sessions/{shell}/attach", {}),
    ):
        resp = await client.post(endpoint, headers=headers, **kwargs)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "FORBIDDEN"
        assert isolated_tickets._tickets == {}


@pytest.mark.parametrize(
    "resource",
    [
        "nodes/x",
        "tunnel:abc",
        "shell:abc",
        "session:",
        "session:not-a-uuid",
        "session:00000000000000000000000000000000",
        "Session:00000000-0000-0000-0000-000000000000",
        "session:00000000-0000-0000-0000-000000000000:extra",
    ],
)
async def test_unsupported_ticket_resource_is_rejected(
    api: tuple, isolated_tickets: WsTicketService, resource: str
) -> None:
    client, maker = api
    headers, _ = await _user(client, maker, None, role_name="Admin")
    resp = await client.post("/api/ws-ticket", json={"resource": resource}, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert isolated_tickets._tickets == {}


@pytest.mark.parametrize("role", list(_NO_VIEW_ROLES))
async def test_ticket_no_view_matches_attach_for_missing_and_forbidden(
    drop_custom_roles: None, api: tuple, isolated_tickets: WsTicketService, role: str
) -> None:
    client, maker = api
    headers, uid = await _user(client, maker, _NO_VIEW_ROLES[role])
    existing = await _session_row(maker, uid)
    answers = []
    for sid in (existing, await _shell_row(maker, existing), uuid.uuid4()):
        for endpoint, kwargs in (
            ("/api/ws-ticket", {"json": {"resource": attach_resource(sid)}}),
            (f"/api/sessions/{sid}/attach", {}),
        ):
            resp = await client.post(endpoint, headers=headers, **kwargs)
            answers.append((resp.status_code, resp.json()["error"]))
    assert (
        answers
        == [(403, {"code": "FORBIDDEN", "message": "You do not have permission for this action"})]
        * 6
    )
    assert isolated_tickets._tickets == {}


async def test_ticket_missing_session_matches_attach_for_permitted_user(api: tuple) -> None:
    client, maker = api
    headers, _ = await _user(client, maker, None, role_name="Viewer")
    sid = uuid.uuid4()
    ticket = await client.post(
        "/api/ws-ticket", json={"resource": attach_resource(sid)}, headers=headers
    )
    attach = await client.post(f"/api/sessions/{sid}/attach", headers=headers)
    assert ticket.status_code == attach.status_code == 404
    assert ticket.json()["error"] == attach.json()["error"]


class _AttachedWebSocket(_FakeWebSocket):
    async def receive(self) -> dict[str, str]:
        return {"type": "websocket.disconnect"}


class _AttachRegistry:
    def __init__(self) -> None:
        self.attached: list[str] = []

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id: uuid.UUID, type_: str, payload: dict, **kwargs: Any) -> None:
        assert type_ == "session.attach"
        self.attached.append(payload["session_id"])


@pytest.mark.parametrize("role", ["Admin", "Developer", "Viewer"])
@pytest.mark.parametrize("owner", [True, False])
@pytest.mark.parametrize("endpoint", ["generic", "attach"])
async def test_authorized_ticket_can_attach_terminal(
    api: tuple, monkeypatch: pytest.MonkeyPatch, role: str, owner: bool, endpoint: str
) -> None:
    import app.api.ws.terminal as terminal

    client, maker = api
    headers, uid = await _user(client, maker, None, role_name=role)
    if not owner:
        _, uid = await _user(client, maker, None, role_name="Developer")
    sid = await _session_row(maker, uid)
    if endpoint == "generic":
        ticket = await _mint(client, headers, sid)
    else:
        resp = await client.post(f"/api/sessions/{sid}/attach", headers=headers)
        assert resp.status_code == 200
        ticket = resp.json()["ticket"]
    registry = _AttachRegistry()
    monkeypatch.setattr(terminal, "get_node_registry", lambda: registry)
    ws = _AttachedWebSocket(ticket)
    async with maker() as session:
        await terminal_gateway(cast(WebSocket, ws), sid, session)
    assert registry.attached == [str(sid)]
    assert ws.closed_with is None
    assert any('"terminal.role"' in str(frame) for frame in ws.sent)


@pytest.mark.parametrize("endpoint", ["generic", "attach"])
async def test_shell_owner_ticket_is_usable(api: tuple, endpoint: str) -> None:
    client, maker = api
    headers, uid = await _user(client, maker, None, role_name="Developer")
    shell = await _shell_row(maker, await _session_row(maker, uid))
    if endpoint == "generic":
        ticket = await _mint(client, headers, shell)
    else:
        resp = await client.post(f"/api/sessions/{shell}/attach", headers=headers)
        assert resp.status_code == 200
        ticket = resp.json()["ticket"]
    assert ws_ticket.get_ws_ticket_service().consume(ticket, attach_resource(shell)) == uid


async def test_ws_rechecks_permission_changed_after_ticket_issuance(api: tuple) -> None:
    client, maker = api
    headers, uid = await _user(client, maker, None, role_name="Developer")
    shell = await _shell_row(maker, await _session_row(maker, uid))
    ticket = await _mint(client, headers, shell)
    async with maker() as session:
        viewer = (await session.execute(sa.select(Role).where(Role.name == "Viewer"))).scalar_one()
        await session.execute(sa.update(User).where(User.id == uid).values(role_id=viewer.id))
        await session.commit()
    ws = _FakeWebSocket(ticket)
    async with maker() as session:
        await terminal_gateway(cast(WebSocket, ws), shell, session)
    assert (ws.closed_with, ws.sent) == (1008, [])


@pytest.mark.parametrize("endpoint", ["generic", "attach"])
async def test_two_user_http_flood_preserves_victim_ticket_and_attach(
    api: tuple, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    import app.api.ws.terminal as terminal

    client, maker = api
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: 100.0)
    service = WsTicketService(60, max_pending=64)
    monkeypatch.setattr(ws_ticket, "_service", service)
    victim, victim_id = await _user(client, maker, None, role_name="Developer")
    attacker, _ = await _user(client, maker, None, role_name="Viewer")
    sid = await _session_row(maker, victim_id)
    path = "/api/ws-ticket" if endpoint == "generic" else f"/api/sessions/{sid}/attach"
    kwargs = {"json": {"resource": attach_resource(sid)}} if endpoint == "generic" else {}
    protected = (await client.post(path, headers=victim, **kwargs)).json()["ticket"]
    for_attach = (await client.post(path, headers=victim, **kwargs)).json()["ticket"]
    answers = [await client.post(path, headers=attacker, **kwargs) for _ in range(72)]
    assert service.consume(protected, attach_resource(sid)) == victim_id
    registry = _AttachRegistry()
    monkeypatch.setattr(terminal, "get_node_registry", lambda: registry)
    ws = _AttachedWebSocket(for_attach)
    async with maker() as session:
        await terminal_gateway(cast(WebSocket, ws), sid, session)
    assert registry.attached == [str(sid)]
    assert ws.closed_with is None
    assert [resp.status_code for resp in answers] == [200] * 32 + [429] * 40
    assert all("ticket" not in resp.json() for resp in answers[32:])
    assert len(service._tickets) == 32


@pytest.mark.parametrize("endpoint", ["generic", "attach"])
async def test_http_33rd_ticket_is_429_then_recovers(
    api: tuple, isolated_tickets: WsTicketService, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    client, maker = api
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    headers, uid = await _user(client, maker, None, role_name="Developer")
    sid = await _session_row(maker, uid)
    path = "/api/ws-ticket" if endpoint == "generic" else f"/api/sessions/{sid}/attach"
    kwargs = {"json": {"resource": attach_resource(sid)}} if endpoint == "generic" else {}
    replies = [await client.post(path, headers=headers, **kwargs) for _ in range(32)]
    assert all(resp.status_code == 200 for resp in replies)
    snapshot = isolated_tickets._tickets.copy()
    rejected = await client.post(path, headers=headers, **kwargs)
    assert rejected.status_code == 429
    assert rejected.json()["error"]["code"] == "WS_TICKET_BUSY"
    assert "ticket" not in rejected.json()
    assert isolated_tickets._tickets == snapshot
    assert isolated_tickets.consume(replies[0].json()["ticket"], attach_resource(sid)) == uid
    assert (await client.post(path, headers=headers, **kwargs)).status_code == 200
    assert len(isolated_tickets._tickets) == 32
    now[0] = 160.0
    assert (await client.post(path, headers=headers, **kwargs)).status_code == 200
    assert len(isolated_tickets._tickets) == 1


@pytest.mark.parametrize("endpoint", ["generic", "attach"])
async def test_http_global_full_returns_controlled_error_without_eviction(
    api: tuple, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    client, maker = api
    service = WsTicketService(60, max_pending=2)
    monkeypatch.setattr(ws_ticket, "_service", service)
    victim, victim_id = await _user(client, maker, None, role_name="Developer")
    attacker, attacker_id = await _user(client, maker, None, role_name="Viewer")
    sid = await _session_row(maker, victim_id)
    path = "/api/ws-ticket" if endpoint == "generic" else f"/api/sessions/{sid}/attach"
    kwargs = {"json": {"resource": attach_resource(sid)}} if endpoint == "generic" else {}
    protected = (await client.post(path, headers=victim, **kwargs)).json()["ticket"]
    other = (await client.post(path, headers=attacker, **kwargs)).json()["ticket"]
    snapshot = service._tickets.copy()
    rejected = await client.post(path, headers=attacker, **kwargs)
    assert rejected.status_code == 503
    assert rejected.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "An internal error occurred",
    }
    assert "ticket" not in rejected.json()
    assert service._tickets == snapshot
    assert service.consume(protected, attach_resource(sid)) == victim_id
    assert service.consume(other, attach_resource(sid)) == attacker_id
