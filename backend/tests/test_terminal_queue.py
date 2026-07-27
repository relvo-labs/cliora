import pytest

from app.services.terminal_queue import BrowserChannel, QueueOverflow


async def test_channel_accounts_and_releases_output_bytes() -> None:
    channel = BrowserChannel(max_bytes=4, max_frames=2)
    await channel.send_output(b"ab")
    await channel.send_output(b"cd")
    assert channel.stats.bytes == 4
    assert channel.stats.frames == 2
    assert await channel.get() == ("output", b"ab")
    assert channel.stats.bytes == 2
    await channel.close()
    assert channel.stats.bytes == 0
    assert await channel.get() is None


async def test_output_overflow_emits_single_sentinel_and_does_not_raise() -> None:
    channel = BrowserChannel(max_bytes=4, max_frames=8)
    await channel.send_output(b"abcd")
    # Over the byte budget: dropped, one overflow sentinel queued, no raise.
    await channel.send_output(b"e")
    await channel.send_output(b"f")
    assert channel.stats.overflows == 1
    assert await channel.get() == ("output", b"abcd")
    assert await channel.get() == ("overflow", b"")


async def test_frame_count_is_bounded_independently() -> None:
    channel = BrowserChannel(max_bytes=1024, max_frames=1)
    await channel.send_output(b"a")
    await channel.send_output(b"b")
    assert channel.stats.overflows == 1
    assert channel.stats.frames == 1


async def test_control_budget_is_independent_of_output() -> None:
    channel = BrowserChannel(max_bytes=1, max_frames=1, max_control=2)
    await channel.send_control("one")
    await channel.send_control("two")
    with pytest.raises(QueueOverflow):
        await channel.send_control("three")
    assert (await channel.get()) == ("control", "one")
    assert channel.stats.control == 1


async def test_close_is_idempotent_and_rejects_control() -> None:
    channel = BrowserChannel(max_bytes=4, max_frames=2)
    await channel.close()
    await channel.close()
    with pytest.raises(QueueOverflow):
        await channel.send_control("x")
    # Output after close is silently dropped (never blocks the daemon reader).
    await channel.send_output(b"x")
    assert channel.stats.bytes == 0
