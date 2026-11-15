"""Argon2id with one process-wide concurrency/queue budget (#59, ADR 0007).

Synchronous helpers are for synchronous consumers. Async production callers use
async helpers: admission waits without blocking the loop, hashing runs in a
small dedicated executor. Cancellation never frees a running worker's permit.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from argon2 import PasswordHasher

from app.api.errors import ApiError
from app.settings import Settings, get_settings

# One semaphore shared by hash, real verify and dummy verify, across threads and
# event loops. Configuration is process-wide and takes effect on process start.
_slots = threading.BoundedSemaphore(get_settings().password_max_concurrency)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="password")


def _busy() -> ApiError:
    return ApiError("INTERNAL_ERROR", "An internal error occurred", 503)


def _hasher(settings: Settings | None = None) -> PasswordHasher:
    s = settings or get_settings()
    return PasswordHasher(
        time_cost=s.argon2_time_cost,
        memory_cost=s.argon2_memory_cost_kib,
        parallelism=s.argon2_parallelism,
    )


def _verify(password_hash: str, password: str, settings: Settings | None = None) -> bool:
    try:
        return _hasher(settings).verify(password_hash, password)
    except Exception:
        return False


def _sync_work[T](work: Callable[[], T]) -> T:
    slots = _slots
    if not slots.acquire(timeout=get_settings().password_queue_timeout_seconds):
        raise _busy()
    try:
        return work()
    finally:
        slots.release()


async def _async_work[T](work: Callable[[], T]) -> T:
    slots = _slots
    deadline = time.monotonic() + get_settings().password_queue_timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _busy()
        if slots.acquire(blocking=False):
            break
        await asyncio.sleep(min(0.01, remaining))

    try:
        future = _executor.submit(work)
    except BaseException:
        slots.release()
        raise
    # Release on completion OR cancellation before the worker starts. A cancelled
    # async caller cannot free a permit while Argon2 is still using its memory.
    future.add_done_callback(lambda _: slots.release())
    return await asyncio.wrap_future(future)


def hash_password(password: str, settings: Settings | None = None) -> str:
    return _sync_work(lambda: _hasher(settings).hash(password))


def verify_password(password_hash: str, password: str, settings: Settings | None = None) -> bool:
    return _sync_work(lambda: _verify(password_hash, password, settings))


async def async_hash_password(password: str, settings: Settings | None = None) -> str:
    return await _async_work(lambda: _hasher(settings).hash(password))


async def async_verify_password(
    password_hash: str, password: str, settings: Settings | None = None
) -> bool:
    return await _async_work(lambda: _verify(password_hash, password, settings))


# Fixed valid Argon2id hash; no import-time hashing outside the semaphore.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Y2xpb3JhLXRpbWluZy1zYWx0"
    "$vLh6VXUKQXubkP0cLgRWvABAKi3C/6R9A4ZKbJRf5ks"
)


def dummy_verify() -> None:
    verify_password(_DUMMY_HASH, "wrong")


async def async_dummy_verify() -> None:
    await async_verify_password(_DUMMY_HASH, "wrong")
