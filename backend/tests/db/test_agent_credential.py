"""The session credential and the path it authenticates on (TK-06, FR-TASK-008).

The security review (`docs/security-review-v21.md`) asks three questions, and these
are the answers in executable form:

* what can a copied token do — four routes, two actions, one project, until the
  session ends;
* can it reach anything a person can — no, and not because of a scope check: the two
  authentication paths are disjoint, and `test_the_two_authentication_paths_are_disjoint`
  is what keeps them that way;
* can the token value leak — every place it could appear is asserted empty.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AuditLog, Node, NodeRuntime, NodeWorkspaceRoot, Role, SessionToken, User
from app.security.passwords import hash_password
from app.services.agent_auth import SESSION_TOKEN_SCOPES, TOKEN_PREFIX, SessionTokenService
from app.services.rbac import (
    FILE_UPLOAD,
    PROJECT_MANAGE,
    TASK_APPROVE,
    TASK_CREATE,
    TERMINAL_OPERATE,
)

pytestmark = pytest.mark.asyncio

ROOT = "/home/neil/projects"
WORKSPACE = f"{ROOT}/app"


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


async def _node(maker: async_sessionmaker) -> uuid.UUID:
    async with maker() as session:
        node = Node(
            name=f"vm-{uuid.uuid4().hex[:6]}",
            hostname="vm.invalid",
            status="online",
            is_enabled=True,
        )
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path=ROOT, is_enabled=True)]
        session.add(node)
        await session.commit()
        return node.id


async def _project_and_card(client: AsyncClient, headers: dict[str, str]) -> tuple[dict, dict]:
    project = (
        await client.post(
            "/api/projects", json={"name": f"p-{uuid.uuid4().hex[:8]}"}, headers=headers
        )
    ).json()
    card = (
        await client.post(
            f"/api/projects/{project['id']}/tasks", json={"title": "card"}, headers=headers
        )
    ).json()["task"]
    return project, card


async def _issue(
    maker: async_sessionmaker, *, project_id: uuid.UUID, node_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[str, uuid.UUID]:
    """Issue a credential the way the projection step will (TK-07)."""
    from app.db.models import TerminalSession

    async with maker() as session:
        terminal = TerminalSession(
            id=uuid.uuid4(),
            node_id=node_id,
            user_id=user_id,
            name="s",
            runtime="claude",
            workspace=WORKSPACE,
            status="running",
            rows=24,
            columns=80,
            project_id=project_id,
        )
        session.add(terminal)
        await session.flush()
        issued = await SessionTokenService(session).issue(
            terminal=terminal, project_id=project_id, actor_id=user_id
        )
        value = issued.value
        session_id = terminal.id
        await session.commit()
    return value, session_id


# --- the scope ------------------------------------------------------------- #


async def test_the_scope_excludes_every_action_that_would_matter() -> None:
    """Two actions in, four kinds of action deliberately out.

    Written as a difference from the *forbidden* set rather than as a copy of the
    allowed one: adding a dangerous action to the vocabulary and forgetting to exclude
    it is the failure this shape catches.
    """
    forbidden = {TASK_APPROVE, TASK_CREATE, PROJECT_MANAGE, FILE_UPLOAD, TERMINAL_OPERATE}
    assert SESSION_TOKEN_SCOPES & forbidden == set()
    assert len(SESSION_TOKEN_SCOPES) == 2


async def test_an_agent_principal_has_no_user_id() -> None:
    """A principal that carried one would eventually be passed to something that
    records an actor, and the agent would start signing a person's name (ADR 0028)."""
    from app.services.agent_auth import AgentPrincipal

    assert "user_id" not in AgentPrincipal.__dataclass_fields__


# --- the two paths are disjoint -------------------------------------------- #


async def test_the_two_authentication_paths_are_disjoint(
    api: tuple, projects_enabled: None
) -> None:
    """The first line of defence, and the reason the scope check is only the second.

    A session token presented to a user route is refused *before* anything looks at
    what it may do — and with the same 401 as any other bad credential, so the shape of
    the answer tells a prober nothing.
    """
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, card = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, _ = await _issue(
        sessionmaker,
        project_id=uuid.UUID(project["id"]),
        node_id=node_id,
        user_id=user_id,
    )
    agent = {"Authorization": f"Bearer {token}"}

    # A session token on the human surface: 401 everywhere, including the read routes.
    for method, path, body in [
        ("get", f"/api/projects/{project['id']}/board", None),
        ("get", f"/api/tasks/{card['id']}", None),
        ("patch", f"/api/tasks/{card['id']}", {"version": 1, "stage": "ready"}),
        ("post", f"/api/tasks/{card['id']}/gates/architecture", {"approved": True}),
        ("post", f"/api/projects/{project['id']}/tasks", {"title": "x"}),
        ("get", "/api/sessions", None),
        ("get", "/api/auth/me", None),
    ]:
        resp = (
            await getattr(client, method)(path, json=body, headers=agent)
            if body
            else await getattr(client, method)(path, headers=agent)
        )
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"

    # And a perfectly valid user JWT on the agent surface: also 401.
    resp = await client.get("/api/cli/tasks", headers=headers)
    assert resp.status_code == 401


async def test_an_agent_can_move_a_card_and_nothing_else(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, card = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, _ = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    agent = {"Authorization": f"Bearer {token}"}

    listing = await client.get("/api/cli/tasks", headers=agent)
    assert listing.status_code == 200, listing.text
    assert [item["card_ref"] for item in listing.json()] == [card["card_ref"]]

    by_ref = await client.get(f"/api/cli/tasks?ref={card['card_ref']}", headers=agent)
    assert by_ref.status_code == 200
    assert by_ref.json()[0]["id"] == card["id"]

    moved = await client.patch(
        f"/api/cli/tasks/{card['id']}",
        json={"version": card["version"], "stage": "implementing"},
        headers=agent,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["task"]["stage"] == "implementing"

    # No gate route exists on the agent prefix. A direct attempt against the human
    # route is rejected as the wrong credential type and leaves an accountable audit
    # row without ever turning the token into a User.
    denied = await client.post(
        f"/api/tasks/{card['id']}/gates/architecture", json={"approved": True}, headers=agent
    )
    assert denied.status_code == 401
    async with sessionmaker() as session:
        row = (
            (
                await session.execute(
                    sa.select(AuditLog)
                    .where(AuditLog.action == "authz.denied")
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.user_id is None
        assert row.audit_metadata["denied_action"] == TASK_APPROVE
        assert row.audit_metadata["actor_kind"] == "session_agent"
        assert row.audit_metadata["token_id"]


async def test_an_agent_may_not_set_a_person_s_fields(api: tuple, projects_enabled: None) -> None:
    """The second line behind the unreachable gate route: the `PATCH` body is open."""
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, card = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, _ = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    agent = {"Authorization": f"Bearer {token}"}
    resp = await client.patch(
        f"/api/cli/tasks/{card['id']}",
        json={"version": card["version"], "owner_user_id": str(user_id)},
        headers=agent,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN_FIELD"


async def test_a_credential_cannot_reach_another_project(
    api: tuple, projects_enabled: None
) -> None:
    """404, not 403: a token must not be usable to discover what exists elsewhere."""
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    mine, _ = await _project_and_card(client, headers)
    theirs, their_card = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, _ = await _issue(
        sessionmaker, project_id=uuid.UUID(mine["id"]), node_id=node_id, user_id=user_id
    )
    agent = {"Authorization": f"Bearer {token}"}
    resp = await client.get(f"/api/cli/tasks/{their_card['id']}", headers=agent)
    assert resp.status_code == 404


async def test_an_agent_write_is_recorded_as_an_agent(api: tuple, projects_enabled: None) -> None:
    """It never signs the name of the person who opened the session (ADR 0028 sec 3)."""
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, card = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, _ = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    await client.patch(
        f"/api/cli/tasks/{card['id']}",
        json={"version": card["version"], "stage": "ready"},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = (await client.get(f"/api/projects/{project['id']}/activity", headers=headers)).json()
    moved = next(item for item in body["items"] if item["kind"] == "task.stage_changed")
    assert moved["actor_kind"] == "agent"
    assert moved["actor_id"] is None
    assert moved["actor_name"] is None


# --- lifecycle -------------------------------------------------------------- #


async def test_a_revoked_or_expired_credential_is_refused(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, _card = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, session_id = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    agent = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/cli/tasks", headers=agent)).status_code == 200

    async with sessionmaker() as session:
        revoked = await SessionTokenService(session).revoke_for_session(session_id)
        await session.commit()
    assert revoked == 1
    assert (await client.get("/api/cli/tasks", headers=agent)).status_code == 401

    # An expired-but-not-revoked credential is refused by the same answer.
    token2, session2 = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    async with sessionmaker() as session:
        await session.execute(
            sa.update(SessionToken)
            .where(SessionToken.session_id == session2)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()
    assert (
        await client.get("/api/cli/tasks", headers={"Authorization": f"Bearer {token2}"})
    ).status_code == 401


async def test_reissuing_for_projection_retry_leaves_only_one_active_token(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, _ = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    first, session_id = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )

    async with sessionmaker() as session:
        from app.db.models import TerminalSession

        terminal = await session.get(TerminalSession, session_id)
        assert terminal is not None
        second = await SessionTokenService(session).issue(
            terminal=terminal, project_id=uuid.UUID(project["id"]), actor_id=user_id
        )
        await session.commit()
        second_value = second.value

    assert (
        await client.get("/api/cli/tasks", headers={"Authorization": f"Bearer {first}"})
    ).status_code == 401
    assert (
        await client.get("/api/cli/tasks", headers={"Authorization": f"Bearer {second_value}"})
    ).status_code == 200
    async with sessionmaker() as session:
        active = (
            (
                await session.execute(
                    sa.select(SessionToken).where(
                        SessionToken.session_id == session_id,
                        SessionToken.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(active) == 1


async def test_ending_a_session_revokes_its_credential(api: tuple, projects_enabled: None) -> None:
    """Revocation lives in the state machine, so every door that ends a session closes
    the credential with it."""
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, _ = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    _token, session_id = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    async with sessionmaker() as session:
        from app.db.models import TerminalSession
        from app.services.sessions import SessionService

        service = SessionService(session)
        terminal = await session.get(TerminalSession, session_id)
        assert terminal is not None
        await service._revoke_tokens_then_record_ended(terminal, actor_user_id=user_id)
        await session.commit()
    async with sessionmaker() as session:
        row = (
            await session.execute(
                sa.select(SessionToken).where(SessionToken.session_id == session_id)
            )
        ).scalar_one()
        assert row.revoked_at is not None


# --- the value never appears anywhere --------------------------------------- #


async def test_the_token_value_never_reaches_the_audit_trail(
    api: tuple, projects_enabled: None
) -> None:
    client, sessionmaker = api
    user_id, headers = await _actor(client, sessionmaker)
    project, _ = await _project_and_card(client, headers)
    node_id = await _node(sessionmaker)
    token, _ = await _issue(
        sessionmaker, project_id=uuid.UUID(project["id"]), node_id=node_id, user_id=user_id
    )
    async with sessionmaker() as session:
        rows = (await session.execute(sa.select(AuditLog))).scalars().all()
        blob = "".join(str(row.audit_metadata) for row in rows)
        assert token not in blob
        assert TOKEN_PREFIX not in blob
        issue_rows = [row for row in rows if row.action == "session_token.issue"]
        assert issue_rows and "token_id" in issue_rows[0].audit_metadata


async def test_no_response_model_can_carry_a_token_value() -> None:
    """An assertion on the OpenAPI document, not on our memory of the endpoints.

    The same instrument V2.3 will need for secrets: "we did not write that endpoint" is
    not evidence, and a schema is.
    """
    from app.main import app

    document = app.openapi()
    schemas = document.get("components", {}).get("schemas", {})
    # Enrollment tokens and the WS ticket legitimately carry a `token` field: both are
    # shown once, by design, to the caller that just created them. What must never
    # exist is a *session* credential on any response — so the scan names the session
    # shapes rather than the word "token", which would only teach the next person to
    # rename their field.
    offenders = [
        f"{name}.{field}"
        for name, schema in schemas.items()
        for field in (schema.get("properties") or {})
        if field in {"session_token", "session_token_value", "agent_token"}
        or (field == "token" and "Session" in name)
    ]
    assert offenders == []
