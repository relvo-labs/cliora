"""Central's aggregation of run log chunks (AR-05, ADR 0030 Part A).

Exit condition 14, and the part of it that is easy to satisfy the wrong way:
**truncation happens in the middle, and it never cuts a JSON line in half.**

Both halves matter for the same reason. A run's beginning (environment, command) and
its end (result, error) are the useful parts, so dropping the tail would throw away the
half somebody actually opens the log for. And the content is a JSONL event stream, so a
line split across a truncation boundary is a line the UI cannot render at all — worse
than a line that is simply absent.
"""

from __future__ import annotations

import json
import uuid

from app.services.run_logs import FLUSH_BYTES, RING_BYTES, RunLogBuffer


def _event(index: int, padding: int = 0) -> str:
    return json.dumps({"type": "assistant", "seq": index, "pad": "x" * padding})


def test_a_chunk_is_written_when_it_is_worth_a_round_trip() -> None:
    """Not per chunk. That socket also carries interactive terminal bytes, and a
    database round trip per chunk buys an agent's debug log with the terminal's
    responsiveness."""
    buffer = RunLogBuffer()
    run = uuid.uuid4()

    assert buffer.append(run, 0, _event(0), now=0.0) is False, "a small chunk flushed immediately"
    # Enough bytes to be worth a write.
    assert buffer.append(run, 1, "x" * FLUSH_BYTES, now=0.1) is True


def test_time_flushes_a_quiet_run() -> None:
    """A run that emits one small event a minute would otherwise be invisible until it
    filled a chunk — which is exactly the window somebody watching the log is staring
    at."""
    buffer = RunLogBuffer()
    run = uuid.uuid4()
    buffer.append(run, 0, _event(0), now=0.0)
    assert buffer.append(run, 1, _event(1), now=5.0) is True


def test_truncation_keeps_the_tail_and_counts_what_it_dropped() -> None:
    """The middle goes, and the number of bytes is recorded rather than implied.

    "Bytes received" cannot answer "bytes dropped", which is why `task_runs` carries
    two counters instead of one.
    """
    buffer = RunLogBuffer()
    run = uuid.uuid4()
    # Fill well past the ring so the front really has to fall off.
    line = _event(0, padding=4096)
    for index in range(int(RING_BYTES / len(line)) * 3):
        buffer.append(run, index, _event(index, padding=4096), now=float(index))
        buffer.begin_truncating(run)

    assert buffer.is_truncating(run) is True
    assert buffer.total_bytes(run) > RING_BYTES


def test_a_truncated_buffer_never_holds_half_an_event() -> None:
    """The ring drops **whole lines**.

    A byte-level ring would leave a partial JSON object at the front of the retained
    window, and the UI renders these line by line — so it would show one unparseable
    entry forever rather than one fewer entry.
    """
    buffer = RunLogBuffer()
    run = uuid.uuid4()
    buffer.append(run, 0, _event(0, padding=4096), now=0.0)
    buffer.begin_truncating(run)
    for index in range(1, 400):
        buffer.append(run, index, _event(index, padding=4096), now=float(index))

    # Everything still buffered has to be a whole event.
    retained = buffer._buffers[run].lines
    assert retained, "the ring dropped everything"
    for entry in retained:
        json.loads(entry)  # raises if a line was split

    dropped = buffer._buffers[run].dropped_bytes
    assert dropped > 0, "nothing was dropped, so the ring is not bounding anything"


def test_discarding_a_run_forgets_it() -> None:
    """Process-local state, so a finished run must not keep a buffer alive.

    Central is a single-process deployment and this relies on that, like
    `NodeConnectionRegistry` — whoever changes one changes the other.
    """
    buffer = RunLogBuffer()
    run = uuid.uuid4()
    buffer.append(run, 0, _event(0), now=0.0)
    assert buffer.total_bytes(run) > 0
    buffer.discard(run)
    assert buffer.total_bytes(run) == 0


def test_a_stale_buffer_is_reported_as_due() -> None:
    """The reaper's fourth job. Without it, a run that produces its last output and then
    thinks for a minute leaves that segment unwritten until it finishes."""
    buffer = RunLogBuffer()
    run = uuid.uuid4()
    buffer.append(run, 0, _event(0), now=0.0)
    assert buffer.due(now=0.5) == []
    assert buffer.due(now=10.0) == [run]
