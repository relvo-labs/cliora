"""Idle reaping of unattended system terminals (FR-SHELL-001.AC-08, ADR 0021 §6).

The behaviour under test is deliberately the *opposite* of FR-SESSION-006: a CLI
session must survive a browser disconnect, a shell must not. Both directions are
asserted here so a future "consistency" fix cannot pass silently.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services import shell_reaper as reaper_module
from app.services.shell_reaper import ShellReaper
from app.services.terminal_queue import BrowserChannel
from app.services.terminal_relay import TerminalRelay

pytestmark = pytest.mark.asyncio

SHELL = uuid.uuid4()


class _Terminated(Exception):
    """Raised by the stub service instead of touching a database."""


def _service_stub(runtime: str, status: str, terminated: list[uuid.UUID]):
    class _Session:
        def __init__(self) -> None:
            self.runtime = runtime
            self.status = status
            self.user_id = uuid.uuid4()

    class _Service:
        def __init__(self, db: object) -> None:
            pass

        async def get(self, session_id: uuid.UUID) -> _Session:
            return _Session()

        async def terminate(self, *, actor_id: uuid.UUID, session_id: uuid.UUID) -> None:
            terminated.append(session_id)

    return _Service


class _FakeDatabase:
    def session(self):  # pragma: no cover - trivial context manager
        class _Ctx:
            async def __aenter__(self_inner):
                return object()

            async def __aexit__(self_inner, *exc):
                return False

            async def commit(self_inner):
                return None

        return _Ctx()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch):
    """Relay + patched database/service so the reaper can run without Postgres."""
    relay = TerminalRelay()
    terminated: list[uuid.UUID] = []
    monkeypatch.setattr(reaper_module, "get_database", lambda: _FakeDatabase())
    monkeypatch.setattr(
        "app.services.terminal_relay.get_terminal_relay", lambda: relay, raising=False
    )
    monkeypatch.setattr(
        reaper_module, "SessionService", _service_stub("shell", "running", terminated)
    )
    return relay, terminated


async def _attach(relay: TerminalRelay, session_id: uuid.UUID, conn: str) -> None:
    await relay.subscribe(session_id, conn, uuid.uuid4(), BrowserChannel(1024, 8), can_write=True)


async def test_an_unattended_shell_is_terminated(wired) -> None:
    _relay, terminated = wired
    reaper = ShellReaper()
    reaper.schedule(SHELL, delay_seconds=0)
    await asyncio.sleep(0.05)
    assert terminated == [SHELL]


async def test_a_reattach_inside_the_window_saves_it(wired) -> None:
    """No cancellation path is needed: the timer re-checks the live subscriber
    list, so coming back is enough."""
    relay, terminated = wired
    reaper = ShellReaper()
    reaper.schedule(SHELL, delay_seconds=0.05)
    await _attach(relay, SHELL, "conn-1")
    await asyncio.sleep(0.1)
    assert terminated == []


async def test_a_flapping_connection_cannot_push_the_deadline_out(wired) -> None:
    """`schedule` is idempotent per session. Restarting the timer on every detach
    would let a reconnect loop keep an unattended shell alive indefinitely."""
    _relay, terminated = wired
    reaper = ShellReaper()
    reaper.schedule(SHELL, delay_seconds=0.05)
    for _ in range(5):
        reaper.schedule(SHELL, delay_seconds=60)
    assert reaper.pending() == 1
    await asyncio.sleep(0.1)
    assert terminated == [SHELL]


async def test_a_cli_session_is_never_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-SESSION-006. Even if something armed the reaper for a CLI session, the
    runtime check refuses — the promise that a session outlives its browser is not
    allowed to depend on nobody making that mistake."""
    terminated: list[uuid.UUID] = []
    monkeypatch.setattr(reaper_module, "get_database", lambda: _FakeDatabase())
    monkeypatch.setattr(
        "app.services.terminal_relay.get_terminal_relay", lambda: TerminalRelay(), raising=False
    )
    monkeypatch.setattr(
        reaper_module, "SessionService", _service_stub("claude", "running", terminated)
    )
    reaper = ShellReaper()
    reaper.schedule(uuid.uuid4(), delay_seconds=0)
    await asyncio.sleep(0.05)
    assert terminated == []


async def test_an_already_ended_shell_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    terminated: list[uuid.UUID] = []
    monkeypatch.setattr(reaper_module, "get_database", lambda: _FakeDatabase())
    monkeypatch.setattr(
        "app.services.terminal_relay.get_terminal_relay", lambda: TerminalRelay(), raising=False
    )
    monkeypatch.setattr(
        reaper_module, "SessionService", _service_stub("shell", "terminated", terminated)
    )
    reaper = ShellReaper()
    reaper.schedule(SHELL, delay_seconds=0)
    await asyncio.sleep(0.05)
    assert terminated == []


async def test_shutdown_drops_pending_timers(wired) -> None:
    """A deploy must not become a fleet-wide teardown of open terminals."""
    _relay, terminated = wired
    reaper = ShellReaper()
    reaper.schedule(SHELL, delay_seconds=0.05)
    await reaper.cancel_all()
    await asyncio.sleep(0.1)
    assert terminated == []
    assert reaper.pending() == 0
