from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

ItemKind = Literal["output", "control", "overflow"]


class QueueOverflow(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QueueStats:
    bytes: int
    frames: int
    control: int
    overflows: int


class BrowserChannel:
    """Single-consumer, FIFO-ordered channel owned by one browser connection.

    Carries opaque terminal *output* bytes (bounded by both byte and frame
    count) plus a small independent budget of *control* text frames. Both are
    drained in strict enqueue order by the sole writer task so that, for
    example, ``session.attached`` precedes its snapshot bytes.

    Terminal output overflow does not block the upstream reader: the offending
    frame is dropped, an ``overflow`` sentinel is queued once, and the writer is
    expected to emit ``terminal.gap`` and close. Control frames never share the
    terminal byte budget, so a flood of output cannot starve control delivery.
    """

    def __init__(self, max_bytes: int, max_frames: int, max_control: int = 64) -> None:
        self._max_bytes = max_bytes
        self._max_frames = max_frames
        self._max_control = max_control
        self._items: asyncio.Queue[tuple[ItemKind, bytes | str] | None] = asyncio.Queue()
        self._bytes = 0
        self._frames = 0
        self._control = 0
        self._overflows = 0
        self._closed = False
        self._overflowed = False
        self._lock = asyncio.Lock()

    async def send_output(self, payload: bytes) -> None:
        """Enqueue terminal output. Never blocks; never raises for a slow peer.

        On overflow the frame is dropped and a single ``overflow`` sentinel is
        queued so the writer can gap/close this one consumer.
        """
        async with self._lock:
            if self._closed or self._overflowed:
                return
            if self._frames >= self._max_frames or self._bytes + len(payload) > self._max_bytes:
                self._overflowed = True
                self._overflows += 1
                self._items.put_nowait(("overflow", b""))
                return
            self._bytes += len(payload)
            self._frames += 1
            self._items.put_nowait(("output", payload))

    async def send_control(self, text: str) -> None:
        """Enqueue a low-volume control frame. Raises QueueOverflow if the small
        independent control budget is exhausted (an abnormal condition)."""
        async with self._lock:
            if self._closed:
                raise QueueOverflow("channel closed")
            if self._control >= self._max_control:
                self._overflows += 1
                raise QueueOverflow("control queue capacity exceeded")
            self._control += 1
            self._items.put_nowait(("control", text))

    async def get(self) -> tuple[ItemKind, bytes | str] | None:
        item = await self._items.get()
        if item is not None:
            kind, payload = item
            async with self._lock:
                if kind == "output":
                    self._bytes -= len(payload)
                    self._frames -= 1
                elif kind == "control":
                    self._control -= 1
        return item

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            while not self._items.empty():
                self._items.get_nowait()
            self._bytes = self._frames = self._control = 0
            self._items.put_nowait(None)

    @property
    def stats(self) -> QueueStats:
        return QueueStats(self._bytes, self._frames, self._control, self._overflows)
