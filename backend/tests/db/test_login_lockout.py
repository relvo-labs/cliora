"""Issue #59: durable account lockout and process-local login protection."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from fastapi import Depends
from httpx import ASGITransport, AsyncClient

from app.api.http.deps import get_auth_service
from app.db.engine import get_session
from app.db.models import AuditLog, LoginLockout
from app.main import app
from app.repositories.users import username_key
from app.security.tokens import issue_access_token
from app.services import auth as auth_module
from app.services.auth import AuthService
from app.services.login_protection import LoginIPLimiter
from app.settings import Settings
from tests.db.test_auth_api import _make_user


async def test_fifth_failure_locks_and_refuses_correct_password(api: tuple) -> None:
    client, maker = api
    await _make_user(maker, username="target", password="correct")
    for attempt in range(1, 6):
        response = await client.post(
            "/api/auth/login", json={"username": "target", "password": "wrong"}
        )
        assert response.status_code == (429 if attempt == 5 else 401)
    assert response.headers["Retry-After"] == "60"
    correct = await client.post(
        "/api/auth/login", json={"username": "target", "password": "correct"}
    )
    assert correct.status_code == 429


@pytest.fixture
async def protection(api, monkeypatch):
    """Real transactions/HTTP, deterministic time and cheap password outcomes."""
    now = [datetime(2026, 11, 15, tzinfo=UTC)]
    settings = Settings()
    limiter = LoginIPLimiter(settings, clock=lambda: now[0].timestamp())
    verify = AsyncMock(side_effect=lambda digest, password: password == "correct")
    dummy = AsyncMock()
    monkeypatch.setattr(auth_module, "verify_password", verify)
    monkeypatch.setattr(auth_module, "dummy_verify", dummy)

    async def service(session=Depends(get_session)):
        return AuthService(session, settings=settings, clock=lambda: now[0], ip_limiter=limiter)

    app.dependency_overrides[get_auth_service] = service
    try:
        yield now, verify, dummy
    finally:
        app.dependency_overrides.pop(get_auth_service, None)


async def _attempt(username="target", password="wrong", host="192.0.2.1", headers=None):
    # Explicit ASGI clients exercise the seam; spoofed headers must be ignored.
    transport = ASGITransport(app=app, client=(host, 1234) if host else None)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/auth/login", json={"username": username, "password": password}, headers=headers
        )


async def test_threshold_durations_expiry_and_every_failure_after_twenty(api, protection):
    _, maker = api
    now, verify, _ = protection
    await _make_user(maker, username="target", password="correct")
    for count in range(1, 23):
        response = await _attempt(host=f"192.0.2.{count}")
        duration = {5: 60, 10: 900}.get(count, 3600 if count >= 20 else 0)
        assert response.status_code == (429 if duration else 401)
        if duration:
            assert response.headers["Retry-After"] == str(duration)
            calls = verify.await_count
            now[0] += timedelta(seconds=duration - 1)
            blocked = await _attempt(password="correct", host="198.51.100.1")
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "1"
            assert verify.await_count == calls
            now[0] += timedelta(seconds=1)  # equality expires
    assert verify.await_count == 22
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("target"))
        assert state.failures == 20
        assert state.locked_until.tzinfo is not None


async def test_success_resets_durable_consecutive_failures(api, protection):
    _, maker = api
    await _make_user(maker, username="target", password="correct")
    for _ in range(4):
        assert (await _attempt()).status_code == 401
    assert (await _attempt(password="correct")).status_code == 200
    for _ in range(4):
        assert (await _attempt()).status_code == 401
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("target"))
        assert state.failures == 4 and state.locked_until is None


async def test_unknown_username_response_and_timing_path_parity(api, protection):
    _, maker = api
    _, verify, dummy = protection
    await _make_user(maker, username="target", password="correct")
    for count in range(1, 7):
        known = await _attempt()
        unknown = await _attempt(username="ghost")
        assert known.status_code == unknown.status_code == (401 if count < 5 else 429)
        assert known.json()["error"] == unknown.json()["error"]
        assert known.headers.get("Retry-After") == unknown.headers.get("Retry-After")
    assert verify.await_count == dummy.await_count == 5
    # Unicode/case variants of an unknown key share the lockout.
    assert (await _attempt(username="ＧＨＯＳＴ")).status_code == 429


async def test_distributed_ips_cannot_bypass_account_lock(api, protection):
    _, maker = api
    await _make_user(maker, username="target", password="correct")
    for index in range(5):
        response = await _attempt(host=f"192.0.2.{index}")
    assert response.status_code == 429
    assert (await _attempt(password="correct", host="198.51.100.8")).status_code == 429


async def test_concurrent_failures_are_not_lost(api, protection):
    _, maker = api
    await _make_user(maker, username="target", password="correct")
    responses = await asyncio.gather(*[_attempt(host=f"192.0.2.{i}") for i in range(8)])
    assert sorted(r.status_code for r in responses) == [401] * 4 + [429] * 4
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("target"))
        assert state.failures == 5


@pytest.mark.parametrize("host", ["192.0.2.1", None])
async def test_ip_limit_across_usernames_ignores_forwarded_headers(api, protection, host):
    now, _, dummy = protection
    for count in range(20):
        response = await _attempt(
            username=f"ghost-{count}",
            host=host,
            headers={"X-Forwarded-For": f"198.51.100.{count}", "X-Real-IP": f"203.0.113.{count}"},
        )
        assert response.status_code == (429 if count == 19 else 401)
    assert response.headers["Retry-After"] == "600"
    assert (await _attempt(username="new-name", host=host)).status_code == 429
    assert dummy.await_count == 20
    assert (await _attempt(username="new-name", host="203.0.113.254")).status_code == 401
    now[0] += timedelta(seconds=600)
    assert (await _attempt(username="new-name", host=host)).status_code == 401


@pytest.mark.parametrize("role_name", ["Admin", "Developer", "Viewer"])
async def test_unlock_api_rbac_and_audit(api, protection, role_name):
    client, maker = api
    actor_id = await _make_user(maker, username="operator", password="correct", role_name=role_name)
    await _make_user(maker, username="target", password="correct")
    for _ in range(5):
        await _attempt()
    response = await client.post(
        "/api/auth/unlock",
        json={"username": "target"},
        headers={"Authorization": f"Bearer {issue_access_token(actor_id, role_name)}"},
    )
    assert response.status_code == (204 if role_name == "Admin" else 403)
    async with maker() as session:
        rows = list(
            (
                await session.execute(sa.select(AuditLog).where(AuditLog.action == "user.unlocked"))
            ).scalars()
        )
        assert len(rows) == (1 if role_name == "Admin" else 0)
        if role_name != "Admin":
            denial = (
                await session.execute(sa.select(AuditLog).where(AuditLog.action == "authz.denied"))
            ).scalar_one()
            assert denial.user_id == actor_id
            assert denial.audit_metadata["denied_action"] == "user.unlock"
        if rows:
            assert rows[0].user_id == actor_id
            assert rows[0].audit_metadata["username"] == "target"
            assert "request_id" in rows[0].audit_metadata
    assert (await _attempt(password="correct")).status_code == (
        200 if role_name == "Admin" else 429
    )


async def test_lockout_start_and_refusal_audited_without_password(api, protection):
    _, maker = api
    for _ in range(6):
        await _attempt(username="ghost", password="secret-material")
    async with maker() as session:
        rows = list((await session.execute(sa.select(AuditLog))).scalars())
        assert len(rows) == 6
        reasons = [row.audit_metadata["reason"] for row in rows]
        assert reasons.count("lockout_started") == reasons.count("account_locked") == 1
        for row in rows:
            assert row.action == "user.login_failed" and row.user_id is None
            assert len(row.audit_metadata["username"]) <= 64
            assert "request_id" in row.audit_metadata
            assert "secret-material" not in str(row.audit_metadata)


async def test_bootstrap_unlock_command_unknown_key_is_audited(api, protection):
    _, maker = api
    for _ in range(5):
        await _attempt(username="ghost")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.bootstrap",
        "unlock-user",
        "--username",
        "GHOST",
        cwd=Path(__file__).parents[2],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    assert "unlocked" in stdout.decode()
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("ghost"))
        assert state.failures == 0 and state.locked_until is None
        row = (
            await session.execute(sa.select(AuditLog).where(AuditLog.action == "user.unlocked"))
        ).scalar_one()
        assert row.user_id is None and row.audit_metadata["source"] == "system"
    assert (await _attempt(username="ghost")).status_code == 401


async def test_password_capacity_http_503_is_uniform_for_known_and_unknown(api):
    from app.security import passwords

    client, maker = api
    await _make_user(maker, username="target", password="correct")
    for _ in range(4):
        assert passwords._slots.acquire(blocking=False)
    try:
        known, unknown = await asyncio.gather(
            client.post("/api/auth/login", json={"username": "target", "password": "correct"}),
            client.post("/api/auth/login", json={"username": "ghost", "password": "wrong"}),
        )
        assert known.status_code == unknown.status_code == 503
        assert (
            known.json()["error"]
            == unknown.json()["error"]
            == {"code": "INTERNAL_ERROR", "message": "An internal error occurred"}
        )
    finally:
        for _ in range(4):
            passwords._slots.release()
    async with maker() as session:
        states = list((await session.execute(sa.select(LoginLockout))).scalars())
        assert all(state.failures == 0 for state in states)


async def test_success_after_lock_expiry_resets_and_ip_failures_survive_success(api, protection):
    _, maker = api
    now, _, _ = protection
    await _make_user(maker, username="target", password="correct")
    for _ in range(5):
        await _attempt()
    now[0] += timedelta(seconds=60)
    assert (await _attempt(password="correct")).status_code == 200
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("target"))
        assert state.failures == 0 and state.locked_until is None
    for i in range(15):
        result = await _attempt(username=f"ghost-{i}")
        assert result.status_code == (429 if i == 14 else 401)
    assert (await _attempt(password="correct")).status_code == 429
