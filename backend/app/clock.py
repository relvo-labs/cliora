"""Timezone-safe instants (timezone-precision skill / ADR 0009).

The application only ever holds aware UTC datetimes. Naive datetimes are
rejected at the boundary so they can never reach the database or a DTO. Durations
(heartbeat timeout, retry) use `monotonic()`, never wall-clock subtraction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import monotonic


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_aware_utc(value: datetime) -> datetime:
    """Return `value` normalized to UTC, raising if it is naive."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime is not allowed; provide an aware instant")
    return value.astimezone(UTC)


def monotonic_seconds() -> float:
    return monotonic()


# Stamped at import, which is process start for every entry point. Monotonic, so
# an NTP step or a timezone change cannot make the process look younger or older
# than it is.
_STARTED_AT = monotonic()


def process_uptime_seconds() -> float:
    """How long this Central process has been running.

    Used by the Dashboard to decide that its own view is not yet trustworthy: for
    the first heartbeat interval after a restart, no daemon has necessarily
    reconnected, so an "offline fleet" is indistinguishable from "we have not
    heard from anyone yet". Reporting that as fact would be the exact failure the
    freshness contract exists to prevent.
    """
    return monotonic() - _STARTED_AT
