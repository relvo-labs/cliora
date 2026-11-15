"""Process bounds, expiry and password work admission (#59)."""

import asyncio
import threading
import time

import pytest

from app.api.errors import ApiError
from app.security import passwords
from app.services.login_protection import LoginIPLimiter
from app.settings import Settings


def test_ip_storage_cap_and_window_expiry_fail_closed():
    now = [0.0]
    limiter = LoginIPLimiter(Settings(login_ip_max_entries=2), clock=lambda: now[0])
    limiter.failed("a")
    limiter.failed("b")
    with pytest.raises(ApiError) as full:
        limiter.check("c")
    assert full.value.status_code == 429
    assert limiter.failed("c") == 600
    assert len(limiter._buckets) == 2
    now[0] = 600
    limiter.check("c")
    assert len(limiter._buckets) == 0


def test_ip_failures_outside_sliding_window_do_not_accumulate():
    now = [0.0]
    limiter = LoginIPLimiter(Settings(), clock=lambda: now[0])
    for _ in range(19):
        assert limiter.failed("a") == 0
    now[0] = 600
    assert limiter.failed("a") == 0
    limiter.check("a")


async def _wait_until(predicate):
    async with asyncio.timeout(2):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("condition did not become true")


async def test_password_semaphore_caps_mixed_operations_and_times_out_at_five_seconds(monkeypatch):
    release = threading.Event()
    guard = threading.Lock()
    active = [0]
    peak = [0]

    class Hasher:
        def work(self):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            try:
                assert release.wait(8)
            finally:
                with guard:
                    active[0] -= 1

        def hash(self, password):
            self.work()
            return "hash"

        def verify(self, digest, password):
            self.work()
            return False

    monkeypatch.setattr(passwords, "_hasher", lambda settings=None: Hasher())
    tasks = [
        asyncio.create_task(passwords.async_hash_password("p")),
        asyncio.create_task(passwords.async_verify_password("hash", "p")),
        asyncio.create_task(passwords.async_dummy_verify()),
        asyncio.create_task(asyncio.to_thread(passwords.hash_password, "p")),
    ]
    try:
        await _wait_until(lambda: active[0] == 4)
        started = time.monotonic()
        with pytest.raises(ApiError) as busy:
            await passwords.async_verify_password("hash", "p")
        elapsed = time.monotonic() - started
        assert busy.value.status_code == 503
        assert busy.value.code == "INTERNAL_ERROR"
        assert busy.value.message == "An internal error occurred"
        assert 4.9 <= elapsed < 6.5
        assert peak[0] == 4  # event loop kept running while all workers blocked
    finally:
        release.set()
        await asyncio.gather(*tasks)


async def test_cancelling_password_waiter_does_not_free_running_worker(monkeypatch):
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr(passwords, "_slots", semaphore)

    def work():
        started.set()
        try:
            release.wait(2)
        finally:
            finished.set()

    task = asyncio.create_task(passwords._async_work(work))
    try:
        await _wait_until(started.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not semaphore.acquire(blocking=False)
    finally:
        release.set()
        await _wait_until(finished.is_set)
    await _wait_until(lambda: semaphore.acquire(blocking=False))
    semaphore.release()


def test_lockout_settings_validate_order_and_positive_durations():
    with pytest.raises(ValueError):
        Settings(login_lockout_thresholds=(10, 5, 20))
    with pytest.raises(ValueError):
        Settings(login_lockout_seconds=(60, 0, 3600))


def test_full_ip_storage_preserves_existing_ban_until_expiry():
    now = [0.0]
    limiter = LoginIPLimiter(
        Settings(login_ip_max_entries=1, login_ip_failure_limit=1), clock=lambda: now[0]
    )
    assert limiter.failed("banned") == 600
    now[0] = 599
    for key in ["banned", "new"]:
        with pytest.raises(ApiError):
            limiter.check(key)
    assert list(limiter._buckets) == ["banned"]
    now[0] = 600
    limiter.check("new")
    assert not limiter._buckets


def test_dummy_hash_performs_argon2_verification():
    from argon2.exceptions import VerifyMismatchError

    # A malformed placeholder would return immediately and become a timing oracle.
    with pytest.raises(VerifyMismatchError):
        passwords._hasher().verify(passwords._DUMMY_HASH, "wrong")


async def test_password_waiter_runs_when_capacity_returns(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)
    monkeypatch.setattr(passwords, "_slots", slots)
    task = asyncio.create_task(passwords._async_work(lambda: "done"))
    await asyncio.sleep(0.03)
    assert not task.done()
    slots.release()
    assert await asyncio.wait_for(task, timeout=1) == "done"
    assert slots.acquire(blocking=False)
    slots.release()
