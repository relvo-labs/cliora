"""Bounded process-local IP failure windows for the single Central process (#59).

Only the ASGI client host is a key; missing clients share the same bucket.
Probation entries are reclaimed oldest-first; active bans are never evicted.
If all slots hold active bans, new IPs proceed untracked. Each bucket holds at
most failure_limit timestamps; inactive windows expire lazily.
Restart clears IP state. Account state remains in PostgreSQL.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
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
        # These indexes share bucket objects and together have at most max_entries
        # keys. Fixed window/ban durations make expiry order monotonic. Probation
        # is ordered by the most recent failure, including repeated failures.
        self._probation: OrderedDict[str, _Bucket] = OrderedDict()
        self._bans: OrderedDict[str, _Bucket] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._bans:
            key, bucket = next(iter(self._bans.items()))
            if bucket.locked_until > now:
                break
            self._bans.popitem(last=False)
            del self._buckets[key]
        while self._probation:
            key, bucket = next(iter(self._probation.items()))
            if bucket.failures[-1] > now - self._settings.login_ip_window_seconds:
                break
            self._probation.popitem(last=False)
            del self._buckets[key]

    def check(self, client_ip: str | None) -> None:
        now = self._clock()
        self._prune(now)
        bucket = self._buckets.get(client_ip or "unknown")
        if bucket is not None and bucket.locked_until > now:
            raise throttled(bucket.locked_until - now)

    def failed(self, client_ip: str | None) -> float:
        now = self._clock()
        self._prune(now)
        key = client_ip or "unknown"
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._settings.login_ip_max_entries:
                if not self._probation:
                    # Capacity alone must never refuse an unrelated client. The
                    # account lockout still applies, even when IP tracking cannot.
                    return 0
                oldest, _ = self._probation.popitem(last=False)
                del self._buckets[oldest]
            bucket = self._buckets[key] = _Bucket()
        if bucket.locked_until > now:
            return bucket.locked_until - now
        while (
            bucket.failures and bucket.failures[0] <= now - self._settings.login_ip_window_seconds
        ):
            bucket.failures.popleft()
        bucket.failures.append(now)
        if len(bucket.failures) >= self._settings.login_ip_failure_limit:
            bucket.failures.clear()
            bucket.locked_until = now + self._settings.login_ip_lock_seconds
            self._probation.pop(key, None)
            self._bans[key] = bucket
            return float(self._settings.login_ip_lock_seconds)
        self._probation[key] = bucket
        self._probation.move_to_end(key)
        return 0


@lru_cache
def get_login_ip_limiter() -> LoginIPLimiter:
    return LoginIPLimiter(get_settings())


class LoginLockoutCleanup:
    """Single-process, no-await admission gate for opportunistic batched cleanup.

    Claim before awaiting SQL so concurrent requests cannot start multiple batches
    in an interval. Rollback/cancellation retries at the next interval.
    """

    def __init__(
        self, interval_seconds: float, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._interval = interval_seconds
        self._clock = clock
        self._next_run: float | None = None

    def claim(self) -> bool:
        now = self._clock()
        if self._next_run is not None and now < self._next_run:
            return False
        self._next_run = now + self._interval
        return True


@lru_cache
def get_login_lockout_cleanup() -> LoginLockoutCleanup:
    return LoginLockoutCleanup(get_settings().login_lockout_cleanup_interval_seconds)
