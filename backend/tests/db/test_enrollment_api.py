"""Enrollment token + node registration over HTTP (FR-INSTALL-001, FR-NODE-001)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import sqlalchemy as sa
from httpx import AsyncClient

from app.clock import now_utc
from app.db.models import EnrollmentToken, NodeCredential, Role, User
from app.security.hashing import keyed_hash
from app.security.passwords import hash_password


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
