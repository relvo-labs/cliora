"""Process-wide admission for unauthenticated node sockets (issue #59 part C)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app import metrics


class PendingNodeConnections:
    """Keep only active IP buckets, bounded by the global pending limit.

    Reservation and release are synchronous so cancellation cannot interrupt cleanup.
    The lock also covers handlers on different event loops in the same process; it is
    never held over an await. Missing clients all use the same None bucket.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0
        self._by_ip: dict[str | None, int] = {}

    @contextmanager
    def slot(self, host: str | None, *, total_max: int, per_ip_max: int) -> Iterator[bool]:
        reason = None
        with self._lock:
            if self._total >= total_max:
                reason = "global"
            elif self._by_ip.get(host, 0) >= per_ip_max:
                reason = "per_ip"
            else:
                self._total += 1
                self._by_ip[host] = self._by_ip.get(host, 0) + 1
        if reason is not None:
            metrics.increment(metrics.NODE_WS_PENDING_REJECTED_TOTAL, reason=reason)
            yield False
            return
        try:
            yield True
        finally:
            with self._lock:
                self._total -= 1
                remaining = self._by_ip[host] - 1
                if remaining:
                    self._by_ip[host] = remaining
                else:
                    del self._by_ip[host]


_limiter = PendingNodeConnections()


def get_node_pending_limiter() -> PendingNodeConnections:
    return _limiter
