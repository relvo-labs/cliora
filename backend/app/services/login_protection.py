"""Bounded process-local IP failure windows for the single Central process (#59).

Only the ASGI client host is a key; missing clients share the same bucket. Full
capacity refuses new keys until expiry, rather than evicting an active ban. Each
bucket holds at most failure_limit timestamps; inactive windows expire lazily.
Restart clears IP state. Account state remains in PostgreSQL.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from app.api.errors import ApiError
from app.settings import Settings, get_settings


def throttled(seconds: float) -> ApiError:
    return ApiError(
        "LOGIN_THROTTLED",
        "Too many login attempts. Try again later",
        429,
        headers={"Retry-After": str(max(1, math.ceil(seconds)))},
    )


@dataclass
class _Bucket:
    failures: deque[float] = field(default_factory=deque)
    locked_until: float = 0


class LoginIPLimiter:
    def __init__(self, settings: Settings, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._settings = settings
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def _prune(self, now: float) -> None:
        for key, bucket in list(self._buckets.items()):
            while (
                bucket.failures
                and bucket.failures[0] <= now - self._settings.login_ip_window_seconds
            ):
                bucket.failures.popleft()
            if not bucket.failures and bucket.locked_until <= now:
                del self._buckets[key]

    def check(self, client_ip: str | None) -> None:
        now = self._clock()
        self._prune(now)
        bucket = self._buckets.get(client_ip or "unknown")
        if bucket is not None and bucket.locked_until > now:
            raise throttled(bucket.locked_until - now)
        if bucket is None and len(self._buckets) >= self._settings.login_ip_max_entries:
            raise throttled(self._settings.login_ip_window_seconds)

    def failed(self, client_ip: str | None) -> float:
        now = self._clock()
        self._prune(now)
        key = client_ip or "unknown"
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._settings.login_ip_max_entries:
                return float(self._settings.login_ip_window_seconds)
            bucket = self._buckets[key] = _Bucket()
        if bucket.locked_until > now:
            return bucket.locked_until - now
        bucket.failures.append(now)
        if len(bucket.failures) >= self._settings.login_ip_failure_limit:
            bucket.failures.clear()
            bucket.locked_until = now + self._settings.login_ip_lock_seconds
            return float(self._settings.login_ip_lock_seconds)
        return 0


@lru_cache
def get_login_ip_limiter() -> LoginIPLimiter:
    return LoginIPLimiter(get_settings())
