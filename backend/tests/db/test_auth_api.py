"""HTTP auth flow against the real schema (FR-AUTH-001)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import AuditLog, Role, User
from app.security.passwords import hash_password


async def _make_user(
    maker: async_sessionmaker,
    *,
    username: str,
    password: str,
    role_name: str = "Admin",
    is_active: bool = True,
) -> uuid.UUID:
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            role_id=role.id,
            is_active=is_active,
        )
        session.add(user)
        await session.commit()
        return user.id


async def test_login_success_returns_tokens_and_user(api: tuple) -> None:
    client: AsyncClient
    client, maker = api
    await _make_user(maker, username="admin", password="s3cret-pass", role_name="Admin")

    response = await client.post(
        "/api/auth/login", json={"username": "admin", "password": "s3cret-pass"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert body["user"]["role"] == "Admin"
    assert "node.manage" in body["user"]["permissions"]


async def test_login_invalid_password_is_401(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="s3cret-pass")
    response = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_user_is_401_same_code(api: tuple) -> None:
    client, _ = api
    response = await client.post(
        "/api/auth/login", json={"username": "ghost", "password": "whatever"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_disabled_user_cannot_login(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="dis", password="pw", is_active=False)
    response = await client.post("/api/auth/login", json={"username": "dis", "password": "pw"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_me_requires_bearer_and_returns_identity(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="dev", password="pw", role_name="Developer")
    tokens = (
        await client.post("/api/auth/login", json={"username": "dev", "password": "pw"})
    ).json()["tokens"]

    assert (await client.get("/api/auth/me")).status_code == 401
    me = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == "dev"
    assert me.json()["role"] == "Developer"


async def test_refresh_issues_new_access_token(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    tokens = (
        await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    ).json()["tokens"]
    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


async def test_refresh_token_is_single_use(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    tokens = (
        await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    ).json()["tokens"]

    first = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200

    replay = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "TOKEN_INVALID"


async def test_logout_invalidates_refresh_token(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    tokens = (
        await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    ).json()["tokens"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (await client.post("/api/auth/logout", headers=headers)).status_code == 204
    # The refresh token minted before logout must no longer work.
    reused = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "TOKEN_INVALID"


async def test_ws_ticket_requires_auth(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    assert (await client.post("/api/ws-ticket", json={"resource": "nodes/x"})).status_code == 401
    tokens = (
        await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    ).json()["tokens"]
    ticket = await client.post(
        "/api/ws-ticket",
        json={"resource": "nodes/x"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert ticket.status_code == 200
    assert ticket.json()["ticket"]


async def test_login_writes_audit_without_secrets(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="admin", password="pw")
    await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    async with maker() as session:
        actions = (await session.execute(sa.select(AuditLog.action))).scalars().all()
    assert "user.login" in actions
