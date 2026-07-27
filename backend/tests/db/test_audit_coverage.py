"""Audit coverage against the real app (P4-04, SEC-006, tech §13.3, ADR 0016).

For each accountable operation this asserts three things, and each one is a way
audit trails go wrong in practice:

* the operation produces a row **at all** — coverage;
* it produces **exactly one** row, so a filter on either action is not misleading;
* the row carries actor, resource, `request_id` and an aware timestamp, and its
  metadata contains none of the forbidden content-bearing keys.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.http.sessions import get_registry
from app.db.models import AuditLog, Node, NodeCredential, NodeRuntime, NodeWorkspaceRoot, Role, User
from app.main import app
from app.protocol import ControlMessage
from app.security.node_keys import valid_public_key
from app.security.passwords import hash_password
from app.services import audit

pytestmark = pytest.mark.asyncio

_PUBLIC_KEY = "0" * 43 + "="


def _msg(type_: str, node_id: uuid.UUID, payload: dict, *, success: bool) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-07-25T00:00:00Z",
        payload=payload,
        success=success,
    )


class FakeRegistry:
    def is_connected(self, node_id: uuid.UUID) -> bool:
        return True

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        sid = payload.get("session_id")
        if type_ == "session.start":
            return _msg("session.started", node_id, {"session_id": sid, "pid": 7}, success=True)
        return _msg("session.stopped", node_id, {"session_id": sid, "exit_code": 0}, success=True)


@contextmanager
def use_registry():
    app.dependency_overrides[get_registry] = FakeRegistry
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_registry, None)


async def _rows(maker: async_sessionmaker, action: str) -> list[AuditLog]:
    async with maker() as db:
        result = await db.execute(
            sa.select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at)
        )
        return list(result.scalars())


async def _all_rows(maker: async_sessionmaker) -> list[AuditLog]:
    async with maker() as db:
        return list((await db.execute(sa.select(AuditLog))).scalars())


def _assert_row_shape(row: AuditLog, *, expect_actor: bool = True) -> None:
    """Every row must be joinable to its request and free of content."""
    metadata = row.audit_metadata or {}
    assert "request_id" in metadata or metadata.get("source") == "system", (
        f"{row.action} has neither request_id nor an explicit source: {metadata}"
    )
    if expect_actor:
        assert row.user_id is not None, f"{row.action} has no actor"
    # tz-aware instant, never naive (timezone-precision).
    assert row.created_at.tzinfo is not None
    assert row.created_at.utcoffset() is not None
    forbidden = audit.FORBIDDEN_METADATA_KEYS & set(metadata)
    assert forbidden == set(), f"{row.action} metadata carries forbidden keys: {forbidden}"
    blob = json.dumps(metadata)
    for leak in ("BEGIN PRIVATE KEY", "eyJhbGciOi", "enroll_"):
        assert leak not in blob, f"{row.action} metadata leaks {leak}"


async def _actor(
    client: AsyncClient, maker: async_sessionmaker, role_name: str = "Admin"
) -> tuple[uuid.UUID, dict[str, str], str]:
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
    token = resp.json()["tokens"]["access_token"]
    return user_id, {"Authorization": f"Bearer {token}"}, username


async def _node(maker: async_sessionmaker) -> uuid.UUID:
    async with maker() as session:
        node = Node(name="vm", hostname="vm", status="online", is_enabled=True)
        node.runtimes = [NodeRuntime(runtime="claude", available=True)]
        node.workspace_roots = [NodeWorkspaceRoot(path="/home/neil/projects", is_enabled=True)]
        session.add(node)
        await session.commit()
        node_id = node.id
    async with maker() as session:
        session.add(
            NodeCredential(node_id=node_id, public_key=_PUBLIC_KEY, algorithm="ed25519", version=1)
        )
        await session.commit()
    return node_id


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


async def test_successful_login_writes_exactly_one_row(api: tuple) -> None:
    client, maker = api
    user_id, _, _ = await _actor(client, maker)
    rows = await _rows(maker, audit.USER_LOGIN)
    assert len(rows) == 1
    assert rows[0].user_id == user_id
    _assert_row_shape(rows[0])


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [("unknown_user", "unknown_user"), ("bad_password", "bad_password")],
)
async def test_failed_login_is_audited_as_a_security_event(
    api: tuple, scenario: str, reason: str
) -> None:
    """A failed sign-in is what makes credential stuffing visible. It is a distinct
    action so the audit viewer can filter for it (P4-04)."""
    client, maker = api
    if scenario == "unknown_user":
        username, password = f"ghost-{uuid.uuid4().hex[:8]}", "whatever"
    else:
        _, _, username = await _actor(client, maker)
        password = "wrong-password"

    resp = await client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    rows = await _rows(maker, audit.USER_LOGIN_FAILED)
    assert len(rows) == 1
    metadata = rows[0].audit_metadata
    assert metadata["reason"] == reason
    assert metadata["username"] == username
    # The attempted password must never appear anywhere in the row.
    assert password not in json.dumps(metadata)
    _assert_row_shape(rows[0], expect_actor=scenario != "unknown_user")


async def test_failed_login_for_a_disabled_account_is_audited(api: tuple) -> None:
    client, maker = api
    user_id, _, username = await _actor(client, maker)
    async with maker() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.is_active = False
        await db.commit()
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 401
    rows = await _rows(maker, audit.USER_LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].audit_metadata["reason"] == "account_disabled"
    assert rows[0].user_id == user_id


async def test_logout_writes_exactly_one_row(api: tuple) -> None:
    client, maker = api
    user_id, headers, _ = await _actor(client, maker)
    resp = await client.post("/api/auth/logout", headers=headers)
    assert resp.status_code == 204
    rows = await _rows(maker, audit.USER_LOGOUT)
    assert len(rows) == 1
    assert rows[0].user_id == user_id
    _assert_row_shape(rows[0])


# --------------------------------------------------------------------------- #
# Node control plane
# --------------------------------------------------------------------------- #


async def test_disable_and_enable_are_distinct_actions(api: tuple) -> None:
    """Before P4-04 both directions recorded `node.disable` with the direction
    buried in metadata, so filtering for "who disabled this node" also returned the
    re-enables."""
    client, maker = api
    _, headers, _ = await _actor(client, maker)
    node_id = await _node(maker)

    off = await client.post(
        f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=headers
    )
    assert off.status_code == 200
    on = await client.post(f"/api/nodes/{node_id}/enabled", json={"enabled": True}, headers=headers)
    assert on.status_code == 200

    disabled = await _rows(maker, audit.NODE_DISABLE)
    enabled = await _rows(maker, audit.NODE_ENABLE)
    assert len(disabled) == 1 and len(enabled) == 1
    assert disabled[0].node_id == node_id and enabled[0].node_id == node_id
    _assert_row_shape(disabled[0])
    _assert_row_shape(enabled[0])


async def test_credential_revoke_and_rotate_are_distinct_actions(api: tuple) -> None:
    """A rotation revokes *and* issues; recording it as a plain revocation lost the
    distinction (P4-04)."""
    client, maker = api
    _, headers, _ = await _actor(client, maker)
    node_id = await _node(maker)
    assert valid_public_key(_PUBLIC_KEY)

    revoke = await client.post(f"/api/nodes/{node_id}/credential/revoke", headers=headers)
    assert revoke.status_code == 204
    rotate = await client.post(
        f"/api/nodes/{node_id}/credential/rotate",
        json={"public_key": _PUBLIC_KEY},
        headers=headers,
    )
    assert rotate.status_code == 200, rotate.text

    revoked = await _rows(maker, audit.CREDENTIAL_REVOKE)
    rotated = await _rows(maker, audit.CREDENTIAL_ROTATE)
    assert len(revoked) == 1, "revoke must not also record a rotation"
    assert len(rotated) == 1, "rotate must record its own action"
    assert rotated[0].audit_metadata["rotated_to_version"] == 2
    _assert_row_shape(revoked[0])
    _assert_row_shape(rotated[0])
    # Neither may carry the key material.
    assert _PUBLIC_KEY not in json.dumps(rotated[0].audit_metadata)


async def test_node_remove_writes_one_row_not_two(api: tuple) -> None:
    """Removal implies credential revocation, so it states that in metadata rather
    than writing a second `credential.revoke` row — otherwise filtering for
    revocations returns events that were never a standalone administrative act."""
    client, maker = api
    _, headers, _ = await _actor(client, maker)
    node_id = await _node(maker)

    resp = await client.delete(f"/api/nodes/{node_id}", headers=headers)
    assert resp.status_code == 204, resp.text

    removed = await _rows(maker, audit.NODE_REMOVE)
    revoked = await _rows(maker, audit.CREDENTIAL_REVOKE)
    assert len(removed) == 1
    assert revoked == [], "node.remove must not also emit credential.revoke"
    assert removed[0].audit_metadata["credentials_revoked"] is True
    assert removed[0].audit_metadata["soft_delete"] is True
    _assert_row_shape(removed[0])


async def test_enrollment_create_and_revoke(api: tuple) -> None:
    client, maker = api
    _, headers, _ = await _actor(client, maker)
    created = await client.post("/api/enrollment-tokens", json={"name": "vm-1"}, headers=headers)
    assert created.status_code == 201, created.text
    token_id = created.json()["id"]
    secret = json.dumps(created.json())

    revoked = await client.delete(f"/api/enrollment-tokens/{token_id}", headers=headers)
    assert revoked.status_code in (200, 204)

    create_rows = await _rows(maker, audit.ENROLLMENT_CREATE)
    revoke_rows = await _rows(maker, audit.ENROLLMENT_REVOKE)
    assert len(create_rows) == 1 and len(revoke_rows) == 1
    for row in (*create_rows, *revoke_rows):
        _assert_row_shape(row)
        # The one-time secret is returned to the caller but must never be stored.
        plain = created.json().get("token")
        if plain:
            assert plain not in json.dumps(row.audit_metadata), "enrollment secret reached audit"
    assert "token" in secret  # sanity: the response really did carry a secret


# --------------------------------------------------------------------------- #
# Session lifecycle
# --------------------------------------------------------------------------- #


async def test_session_create_and_terminate(api: tuple) -> None:
    client, maker = api
    _, headers, _ = await _actor(client, maker)
    node_id = await _node(maker)
    with use_registry():
        created = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "s",
                "workspace": "/home/neil/projects/app",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["id"]
        terminated = await client.post(f"/api/sessions/{session_id}/terminate", headers=headers)
        assert terminated.status_code == 200, terminated.text

    create_rows = await _rows(maker, audit.SESSION_CREATE)
    terminate_rows = await _rows(maker, audit.SESSION_TERMINATE)
    assert len(create_rows) == 1 and len(terminate_rows) == 1
    for row in (*create_rows, *terminate_rows):
        _assert_row_shape(row)
        assert row.session_id is not None
        assert row.node_id == node_id
        # The workspace absolute path must not be recorded in full.
        assert "/home/neil/projects/app" not in json.dumps(row.audit_metadata)


# --------------------------------------------------------------------------- #
# Security events
# --------------------------------------------------------------------------- #


async def test_refused_mutation_is_audited_with_the_actor_and_request_id(api: tuple) -> None:
    """A Viewer's forged mutation is a security event, and the row must name who was
    refused, what they tried, and which request it was."""
    client, maker = api
    viewer_id, viewer, _ = await _actor(client, maker, "Viewer")
    node_id = await _node(maker)

    resp = await client.post(
        f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=viewer
    )
    assert resp.status_code == 403
    request_id = resp.headers["x-request-id"]

    rows = await _rows(maker, audit.AUTHZ_DENIED)
    assert len(rows) == 1, "a refused mutation must produce exactly one security event"
    row = rows[0]
    assert row.user_id == viewer_id
    metadata = row.audit_metadata
    assert metadata["denied_action"] == "node.manage"
    assert metadata["reason"] == "action"
    assert metadata["method"] == "POST"
    assert metadata["path"].endswith("/enabled")
    # The correlation id must match the response header, which is the whole point:
    # the audit row and the request's logs must be joinable.
    assert metadata["request_id"] == request_id
    _assert_row_shape(row)


async def test_cross_owner_refusal_is_audited_with_scope_reason(api: tuple) -> None:
    client, maker = api
    owner_id, _, _ = await _actor(client, maker, "Developer")
    intruder_id, intruder, _ = await _actor(client, maker, "Developer")
    node_id = await _node(maker)
    from app.db.models import TerminalSession

    async with maker() as db:
        row = TerminalSession(
            node_id=node_id,
            user_id=owner_id,
            name="s",
            runtime="claude",
            workspace="/home/neil/projects/app",
            status="running",
        )
        db.add(row)
        await db.commit()
        session_id = row.id

    resp = await client.post(f"/api/sessions/{session_id}/terminate", headers=intruder)
    assert resp.status_code == 403

    rows = await _rows(maker, audit.AUTHZ_DENIED)
    assert len(rows) == 1
    assert rows[0].user_id == intruder_id
    assert rows[0].audit_metadata["reason"] == "scope"
    assert rows[0].audit_metadata["denied_action"] == "session.terminate"


async def test_plain_read_refusals_are_not_audited(api: tuple) -> None:
    """Read 403s are frequent and uninteresting; auditing them would bury the
    signal (ADR 0016). Only mutations and cross-owner refusals are recorded."""
    client, maker = api
    _, viewer, _ = await _actor(client, maker, "Viewer")
    resp = await client.get("/api/enrollment-tokens", headers=viewer)
    assert resp.status_code == 403
    assert await _rows(maker, audit.AUTHZ_DENIED) == []


# --------------------------------------------------------------------------- #
# Cross-cutting
# --------------------------------------------------------------------------- #


async def test_every_row_written_during_a_full_flow_is_well_formed(api: tuple) -> None:
    """One pass over a realistic sequence, asserting the shape of *every* row it
    produced rather than only the ones a test names."""
    client, maker = api
    _, headers, _ = await _actor(client, maker)
    node_id = await _node(maker)
    with use_registry():
        created = await client.post(
            "/api/sessions",
            json={
                "node_id": str(node_id),
                "runtime": "claude",
                "name": "s",
                "workspace": "/home/neil/projects/app",
            },
            headers=headers,
        )
        session_id = created.json()["id"]
        await client.post(f"/api/sessions/{session_id}/terminate", headers=headers)
    await client.post(f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=headers)
    await client.post("/api/enrollment-tokens", json={"name": "vm"}, headers=headers)
    await client.post("/api/auth/logout", headers=headers)

    rows = await _all_rows(maker)
    assert rows, "the flow produced no audit at all"
    for row in rows:
        assert row.action in audit.ALL_ACTIONS, f"unknown action written: {row.action}"
        _assert_row_shape(row, expect_actor=row.action != audit.NODE_REGISTER)


async def test_audit_write_failure_does_not_break_the_request(api: tuple, monkeypatch) -> None:
    """Accountability must not become an availability problem: if the audit write
    fails, the user's operation still succeeds and the failure is counted."""
    from app import metrics
    from app.repositories.audit import AuditRepository

    client, maker = api
    _, viewer, _ = await _actor(client, maker, "Viewer")
    node_id = await _node(maker)
    metrics.reset()

    def boom(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("audit backend down")

    monkeypatch.setattr(AuditRepository, "add", boom)
    resp = await client.post(
        f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=viewer
    )
    # Still refused with the normal code, not a 500.
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"
    assert metrics.counter_value(metrics.AUDIT_ERROR_TOTAL, action=audit.AUTHZ_DENIED) == 1
    metrics.reset()
