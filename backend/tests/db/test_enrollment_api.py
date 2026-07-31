"""Enrollment token + node registration over HTTP (FR-INSTALL-001, FR-NODE-001)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import get_args

import sqlalchemy as sa
from httpx import AsyncClient

from app.api.http.schemas import NodeReportedRuntime
from app.clock import now_utc
from app.db.models import EnrollmentToken, NodeCredential, NodeRuntime, Role, User
from app.security.hashing import keyed_hash
from app.security.passwords import hash_password
from app.services.sessions import RUNTIMES


async def _make_user(maker, *, username, password, role_name="Admin") -> uuid.UUID:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            role_id=role.id,
        )
        session.add(user)
        await session.commit()
        return user.id


async def _login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    tokens = (
        await client.post("/api/auth/login", json={"username": username, "password": password})
    ).json()["tokens"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _register_body(token: str, name: str = "dev-vm-01") -> dict:
    return {
        "token": token,
        "name": name,
        "hostname": name,
        "os": "linux",
        "os_version": "Ubuntu 24.04",
        "architecture": "amd64",
        "daemon_version": "1.0.0",
        "run_user": "neil",
        "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "runtimes": [{"runtime": "claude", "available": True, "version": "1.2.3"}],
        "workspace_roots": [{"path": "/home/neil/work", "is_enabled": True}],
    }


async def test_admin_creates_token_once_and_lists_without_plaintext(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw", role_name="Admin")
    headers = await _login(client, "admin", "pw")

    created = await client.post("/api/enrollment-tokens", json={}, headers=headers)
    assert created.status_code == 201
    plaintext = created.json()["token"]
    assert plaintext.startswith("enroll_")

    listed = await client.get("/api/enrollment-tokens", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "active"
    assert rows[0]["used_count"] == 0
    assert "token" not in rows[0]  # plaintext never re-exposed


async def test_non_admin_cannot_create_token(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="dev", password="pw", role_name="Developer")
    headers = await _login(client, "dev", "pw")
    response = await client.post("/api/enrollment-tokens", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_register_consumes_single_use_token(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    headers = await _login(client, "admin", "pw")
    token = (await client.post("/api/enrollment-tokens", json={}, headers=headers)).json()["token"]

    first = await client.post("/api/nodes/register", json=_register_body(token))
    assert first.status_code == 201
    body = first.json()
    assert "node_secret" not in body
    assert set(body) == {"node_id", "server_url"}
    assert uuid.UUID(body["node_id"])
    async with maker() as session:
        credential = (
            await session.execute(
                sa.select(NodeCredential).where(
                    NodeCredential.node_id == uuid.UUID(body["node_id"])
                )
            )
        ).scalar_one()
        assert credential.algorithm == "ed25519"
        assert credential.public_key == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        assert credential.secret_hash is None

    # Single-use token is now exhausted.
    second = await client.post("/api/nodes/register", json=_register_body(token, name="vm2"))
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "ENROLLMENT_TOKEN_INVALID"


async def test_register_rejects_expired_token(api: tuple) -> None:
    client, maker = api
    admin_id = await _make_user(maker, username="admin", password="pw")
    plaintext = "enroll_expired_example"
    async with maker() as session:
        session.add(
            EnrollmentToken(
                token_hash=keyed_hash(plaintext),
                created_by=admin_id,
                expires_at=now_utc() - timedelta(minutes=1),
                max_uses=1,
            )
        )
        await session.commit()
    response = await client.post("/api/nodes/register", json=_register_body(plaintext))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ENROLLMENT_TOKEN_INVALID"


async def test_revoked_token_cannot_register(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    headers = await _login(client, "admin", "pw")
    created = (await client.post("/api/enrollment-tokens", json={}, headers=headers)).json()

    assert (
        await client.delete(f"/api/enrollment-tokens/{created['id']}", headers=headers)
    ).status_code == 204
    response = await client.post("/api/nodes/register", json=_register_body(created["token"]))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ENROLLMENT_TOKEN_INVALID"


async def test_register_accepts_the_runtime_set_the_daemon_detects(api: tuple) -> None:
    """The daemon enumerates claude, codex *and* shell at enrolment.

    `install.DetectRuntimes` has probed all three since the system terminal
    shipped, but RuntimeItemDTO still only allowed two, so every real
    `agentd install` died on HTTP 422 before a node row was ever written. The
    fixture above registers one runtime and never caught it; this one sends
    exactly what the daemon sends.
    """
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    headers = await _login(client, "admin", "pw")
    token = (await client.post("/api/enrollment-tokens", json={}, headers=headers)).json()["token"]

    body = _register_body(token)
    body["runtimes"] = [
        {"runtime": "claude", "available": True, "version": "1.2.3"},
        {"runtime": "codex", "available": False},
        {"runtime": "shell", "available": True, "version": "5.2.21", "binary_path": "/bin/bash"},
    ]
    response = await client.post("/api/nodes/register", json=body)
    assert response.status_code == 201, response.text

    # Persisted, and persisted as available: the node's report is the only place
    # the system terminal's availability lives, and `_require_runtime` reads it
    # back to decide whether a shell may be opened at all (ADR 0021).
    async with maker() as session:
        rows = (
            await session.execute(
                sa.select(NodeRuntime).where(
                    NodeRuntime.node_id == uuid.UUID(response.json()["node_id"])
                )
            )
        ).scalars()
        runtimes = {r.runtime: r.available for r in rows}
    assert runtimes == {"claude": True, "codex": False, "shell": True}


def test_node_reported_runtimes_match_the_session_service() -> None:
    """The drift guard the last change needed.

    Two independent lists of runtime ids exist: the session service's RUNTIMES,
    and the enrolment DTO's Literal. Adding `shell` to the first and not the
    second is what broke enrolment, and nothing failed. `fake` is excluded
    deliberately — `_require_runtime` short-circuits it and no node reports it.
    """
    assert set(get_args(NodeReportedRuntime)) == RUNTIMES - {"fake"}
