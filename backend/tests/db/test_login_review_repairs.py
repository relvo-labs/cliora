"""Adversarial regressions for independent review of PR #182 (Delta 1)."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa

from app.db.models import LoginLockout
from app.repositories.users import LoginLockoutRepository, username_key
from app.services.login_protection import LoginIPLimiter
from app.settings import Settings
from tests.db import test_login_lockout
from tests.db.test_auth_api import _make_user
from tests.db.test_login_lockout import _attempt

protection = test_login_lockout.protection


@pytest.mark.parametrize("saturation", ["probation", "bans"])
async def test_saturation_after_ten_thousand_ips_preserves_ban_and_valid_login(
    api, protection, saturation
):
    _, maker = api
    now, verify, _ = protection
    await _make_user(maker, username="target", password="correct")
    limiter = LoginIPLimiter(Settings(), clock=lambda: now[0].timestamp())
    for _ in range(20):
        limiter.failed("198.51.100.1")
    for i in range(10_001):
        for _ in range(20 if saturation == "bans" else 1):
            limiter.failed(f"2001:db8::{i:x}")
    # Exercise the same limiter through the real login route and transaction.
    from fastapi import Depends

    from app.api.http.deps import get_auth_service
    from app.db.engine import get_session
    from app.main import app
    from app.services.auth import AuthService

    async def service(session=Depends(get_session)):
        return AuthService(session, clock=lambda: now[0], ip_limiter=limiter)

    previous = app.dependency_overrides[get_auth_service]
    app.dependency_overrides[get_auth_service] = service
    try:
        response = await _attempt(password="correct", host="203.0.113.100")
        assert response.status_code == 200
        assert verify.await_count == 1
        assert (await _attempt(password="correct", host="198.51.100.1")).status_code == 429
        assert verify.await_count == 1
        # Account protection remains effective when IP tracking is saturated.
        for attempt in range(1, 6):
            failed = await _attempt(host="203.0.113.100")
            assert failed.status_code == (429 if attempt == 5 else 401)
        assert len(limiter._buckets) <= 10_000
    finally:
        app.dependency_overrides[get_auth_service] = previous


async def test_exact_username_success_cannot_reset_another_account(api, protection):
    _, maker = api
    await _make_user(maker, username="alice", password="correct")
    await _make_user(maker, username="Alice", password="correct")
    for index in range(4):
        assert (await _attempt(username="Alice", host=f"192.0.2.{index}")).status_code == 401
    assert (await _attempt(username="alice", password="correct")).status_code == 200
    assert (await _attempt(username="Alice")).status_code == 429
    assert (await _attempt(username="alice", password="correct")).status_code == 200
    async with maker() as session:
        alice = await session.get(LoginLockout, username_key("alice"))
        other = await session.get(LoginLockout, username_key("Alice"))
        assert alice.failures == 0
        assert other.failures == 5


async def test_idle_unknown_username_is_retired_on_later_login(api, protection):
    _, maker = api
    now, _, _ = protection
    assert (await _attempt(username="stale-ghost")).status_code == 401
    now[0] += timedelta(hours=24, seconds=1)
    assert (await _attempt(username="fresh-ghost")).status_code == 401
    async with maker() as session:
        assert await session.get(LoginLockout, username_key("stale-ghost")) is None


async def test_retention_batch_bound_expiry_boundary_and_active_lock_preservation(api):
    _, maker = api
    now = datetime(2026, 11, 15, tzinfo=UTC)
    cutoff = now - timedelta(hours=24)
    rows = [
        LoginLockout(
            username_key=f"stale-{i}",
            failures=4,
            last_activity_at=cutoff - timedelta(seconds=10 - i),
        )
        for i in range(5)
    ]
    rows.extend(
        [
            LoginLockout(
                username_key="active-lock",
                failures=20,
                last_activity_at=cutoff - timedelta(days=1),
                locked_until=now + timedelta(seconds=1),
            ),
            LoginLockout(
                username_key="expired-lock",
                failures=20,
                last_activity_at=cutoff - timedelta(days=1),
                locked_until=now,
            ),
            LoginLockout(username_key="exact-cutoff", failures=4, last_activity_at=cutoff),
            LoginLockout(username_key="recent", failures=4, last_activity_at=now),
        ]
    )
    async with maker() as session:
        session.add_all(rows)
        await session.commit()
    async with maker() as session:
        repo = LoginLockoutRepository(session)
        assert await repo.cleanup_idle(now=now, idle_seconds=86400, batch_size=2) == 2
        await session.commit()
        remaining = set((await session.execute(sa.select(LoginLockout.username_key))).scalars())
        assert len(remaining) == 7
        assert "expired-lock" not in remaining and "stale-0" not in remaining
        assert {"active-lock", "exact-cutoff", "recent"} <= remaining
        assert await repo.cleanup_idle(now=now, idle_seconds=86400, batch_size=2) == 2
        assert await repo.cleanup_idle(now=now, idle_seconds=86400, batch_size=2) == 2
        assert await repo.cleanup_idle(now=now, idle_seconds=86400, batch_size=2) == 0
        await session.commit()
        remaining = set((await session.execute(sa.select(LoginLockout.username_key))).scalars())
        assert remaining == {"active-lock", "exact-cutoff", "recent"}


async def test_retention_skips_rows_locked_by_an_inflight_login(api):
    _, maker = api
    now = datetime(2026, 11, 15, tzinfo=UTC)
    async with maker() as session:
        session.add_all(
            [
                LoginLockout(username_key=key, failures=4, last_activity_at=now - timedelta(days=2))
                for key in ["busy", "idle"]
            ]
        )
        await session.commit()
    async with maker() as live, maker() as cleanup:
        await live.execute(
            sa.select(LoginLockout).where(LoginLockout.username_key == "busy").with_for_update()
        )
        count = await asyncio.wait_for(
            LoginLockoutRepository(cleanup).cleanup_idle(
                now=now, idle_seconds=86400, batch_size=10
            ),
            timeout=2,
        )
        assert count == 1
        await cleanup.commit()
        await live.rollback()
    async with maker() as session:
        assert set((await session.execute(sa.select(LoginLockout.username_key))).scalars()) == {
            "busy"
        }


async def test_cleanup_interval_shared_by_concurrent_login_requests(api, protection, monkeypatch):
    original = LoginLockoutRepository.cleanup_idle
    calls = AsyncMock()

    async def cleanup(self, **kwargs):
        await calls(**kwargs)
        return await original(self, **kwargs)

    monkeypatch.setattr(LoginLockoutRepository, "cleanup_idle", cleanup)
    now, _, _ = protection
    results = await asyncio.gather(
        *[_attempt(username=f"ghost-{i}", host=f"192.0.2.{i}") for i in range(4)]
    )
    assert all(r.status_code == 401 for r in results)
    assert calls.await_count == 1
    assert calls.call_args.kwargs["batch_size"] == 1000
    now[0] += timedelta(seconds=59)
    await _attempt(username="later")
    assert calls.await_count == 1
    now[0] += timedelta(seconds=1)
    await _attempt(username="interval-boundary")
    assert calls.await_count == 2


async def test_retention_is_identical_for_known_and_unknown_names(api, protection):
    _, maker = api
    now, verify, dummy = protection
    await _make_user(maker, username="known", password="correct")
    assert (await _attempt(username="known")).status_code == 401
    assert (await _attempt(username="unknown")).status_code == 401
    now[0] += timedelta(days=2)
    # The same idle policy applies before looking up whether either user exists.
    for username in ["known", "unknown"]:
        result = await _attempt(username=username)
        assert result.status_code == 401
        assert result.json()["error"] == {
            "code": "INVALID_CREDENTIALS",
            "message": "Invalid username or password",
        }
    assert verify.await_count == dummy.await_count == 2
    async with maker() as session:
        for username in ["known", "unknown"]:
            row = await session.get(LoginLockout, username_key(username))
            assert row.failures == 1
            assert row.last_activity_at == now[0]


@pytest.mark.parametrize("variant", ["Alice", "ＡＬＩＣＥ"])
async def test_unknown_username_variants_do_not_lock_a_known_account(api, protection, variant):
    _, maker = api
    await _make_user(maker, username="alice", password="correct")
    for _ in range(5):
        result = await _attempt(username=variant)
    assert result.status_code == 429
    assert (await _attempt(username="alice", password="correct")).status_code == 200
    assert (await _attempt(username=variant)).status_code == 429


async def test_locked_refusal_refreshes_activity_without_extending_lock(api, protection):
    _, maker = api
    now, _, _ = protection
    for _ in range(5):
        await _attempt(username="ghost")
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("ghost"))
        locked_until = state.locked_until
        assert state.last_activity_at == now[0]
    now[0] += timedelta(seconds=30)
    assert (await _attempt(username="ghost", password="correct")).status_code == 429
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("ghost"))
        assert state.last_activity_at == now[0]
        assert state.locked_until == locked_until


async def test_login_upsert_survives_concurrent_retention_delete(api):
    _, maker = api
    now = datetime(2026, 11, 15, tzinfo=UTC)
    async with maker() as seed:
        seed.add(
            LoginLockout(
                username_key=username_key("ghost"),
                failures=4,
                last_activity_at=now - timedelta(days=2),
            )
        )
        await seed.commit()
    async with maker() as cleanup, maker() as login:
        assert (
            await LoginLockoutRepository(cleanup).cleanup_idle(
                now=now, idle_seconds=86400, batch_size=10
            )
            == 1
        )
        attempt = asyncio.create_task(LoginLockoutRepository(login).for_update("ghost", now=now))
        try:
            await asyncio.sleep(0.02)
            assert not attempt.done()  # waits for the deletion's transaction
            await cleanup.commit()
            state = await asyncio.wait_for(attempt, timeout=2)
            assert state.failures == 0 and state.locked_until is None
            assert state.last_activity_at == now
            state.failures = 1
            await login.commit()
        finally:
            if not attempt.done():
                attempt.cancel()
                await asyncio.gather(attempt, return_exceptions=True)
    async with maker() as session:
        state = await session.get(LoginLockout, username_key("ghost"))
        assert state.failures == 1
