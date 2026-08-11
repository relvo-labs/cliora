"""Central's in-memory aggregation of run log chunks (ADR 0030 Part A, D3).

A run's output arrives as `run.log_chunk` frames on the **same socket that carries
interactive terminal bytes** — `node_gateway`'s `raw_bytes` branch is in the same
`while` loop. One database round trip per chunk would therefore spend V1's terminal
responsiveness on an agent's debug output, so chunks accumulate here and a row is
written when the buffer reaches 64 KiB or two seconds have passed.

**The cost is accepted and stated rather than hidden:** if the Central process
crashes, each in-flight run loses its last unflushed segment. The log is a diagnostic
— re-running produces another one — and the two things that are *not* diagnostics
deliberately avoid this path entirely: card artifacts go over HTTP and land one at a
time, and card messages commit per message (ADR 0030 Part A, three sentences).

**Truncation happens in the middle, not at the tail.** A run's beginning (environment,
command) and end (result, error) are both more useful than its middle, so once the cap
is reached the buffer keeps the *last* 512 KiB in a ring and writes one marker row
saying how many bytes were dropped.

**The ring holds lines, not bytes.** The content is a JSONL event stream, and half an
event cannot be rendered — so it drops a whole line rather than part of one.

This is process-local state, like `NodeConnectionRegistry`. Central is a single-process
deployment and both rely on that; whoever changes one changes the other.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_utc
from app.db.models import RunLog, TaskRun

# One row is written at this size or at this age, whichever comes first. Both are
# candidates for adjustment once M-AR-2 has measured a real run's JSONL rate.
FLUSH_BYTES = 64 * 1024
FLUSH_SECONDS = 2.0
# What is kept once the cap is reached.
RING_BYTES = 512 * 1024


@dataclass
class _Buffer:
    lines: deque[str] = field(default_factory=deque)
    pending_bytes: int = 0
    first_seq: int | None = None
    last_flush: float = 0.0
    total_bytes: int = 0
    dropped_bytes: int = 0
    truncating: bool = False


class RunLogBuffer:
    """One buffer per in-flight run, keyed by run id."""

    def __init__(self) -> None:
        self._buffers: dict[uuid.UUID, _Buffer] = {}

    def append(self, run_id: uuid.UUID, seq: int, data: str, *, now: float) -> bool:
        """Take one chunk. Returns True when the caller should flush.

        Never writes to the database itself: the WebSocket loop decides when to spend
        a round trip, and this object only ever answers "now would be a good moment".
        """
        buffer = self._buffers.setdefault(run_id, _Buffer(last_flush=now))
        if buffer.first_seq is None:
            buffer.first_seq = seq
        size = len(data.encode())
        buffer.total_bytes += size
        buffer.lines.append(data)
        buffer.pending_bytes += size
        if buffer.truncating:
            # Already past the cap: keep the tail and count what falls off the front.
            while buffer.pending_bytes > RING_BYTES and len(buffer.lines) > 1:
                dropped = buffer.lines.popleft()
                dropped_size = len(dropped.encode())
                buffer.pending_bytes -= dropped_size
                buffer.dropped_bytes += dropped_size
            return False
        return buffer.pending_bytes >= FLUSH_BYTES or (now - buffer.last_flush) >= FLUSH_SECONDS

    def begin_truncating(self, run_id: uuid.UUID) -> None:
        buffer = self._buffers.get(run_id)
        if buffer is not None:
            buffer.truncating = True

    def total_bytes(self, run_id: uuid.UUID) -> int:
        buffer = self._buffers.get(run_id)
        return buffer.total_bytes if buffer is not None else 0

    def is_truncating(self, run_id: uuid.UUID) -> bool:
        buffer = self._buffers.get(run_id)
        return bool(buffer is not None and buffer.truncating)

    def due(self, now: float) -> list[uuid.UUID]:
        """Runs whose buffer has been sitting too long.

        The reaper calls this: a run that stops producing output between the last
        chunk and its completion would otherwise leave that segment unwritten until
        the run finished.
        """
        return [
            run_id
            for run_id, buffer in self._buffers.items()
            if buffer.lines and (now - buffer.last_flush) >= FLUSH_SECONDS
        ]

    async def flush(self, session: AsyncSession, run_id: uuid.UUID, *, now: float) -> bool:
        """Write one aggregated row. Returns True when something was written."""
        buffer = self._buffers.get(run_id)
        if buffer is None or not buffer.lines:
            return False
        data = "\n".join(buffer.lines)
        seq = buffer.first_seq or 0
        dropped = buffer.dropped_bytes
        session.add(
            RunLog(
                id=uuid.uuid4(),
                run_id=run_id,
                seq=seq,
                data=data,
                truncated=dropped > 0,
                received_at=now_utc(),
            )
        )
        await session.execute(
            update(TaskRun)
            .where(TaskRun.id == run_id)
            .values(log_bytes=buffer.total_bytes, log_truncated_bytes=dropped)
        )
        buffer.lines.clear()
        buffer.pending_bytes = 0
        buffer.first_seq = None
        buffer.last_flush = now
        return True

    def discard(self, run_id: uuid.UUID) -> None:
        self._buffers.pop(run_id, None)


_buffer = RunLogBuffer()


def get_run_log_buffer() -> RunLogBuffer:
    return _buffer
