"""Idle reaper for system-terminal sessions (WT-07, FR-SHELL-001.AC-08).

The third and last layer of the shell lifetime (ADR 0021 §4). The first two are
cooperative — the browser terminates the session when the tab closes, and a
session dies with the CLI session it belongs to. Neither survives the case this
module exists for: the browser crashes, the laptop closes, the tunnel drops. No
message is sent, so nothing above notices, and a shell stays open on the node
with nobody watching it.

This is not a scheduler. There is no periodic sweep and no persistent queue: one
bounded timer per detached shell, started by the WebSocket teardown that observed
the last subscriber leaving, and re-checking the live subscriber list before it
acts. A reattach inside the window therefore costs nothing and cancels nothing —
the task simply finds a subscriber and returns.

Deliberately inverted relative to a CLI session, which must survive a browser
disconnect (FR-SESSION-006). That contrast is the decision, not an oversight.
"""

from __future__ import annotations

import asyncio
import uuid

from app.api.errors import ApiError
from app.db.engine import get_database
from app.logging import get_logger
from app.services.sessions import SHELL_RUNTIME, TERMINAL_STATES, SessionService
from app.settings import get_settings

_logger = get_logger("cliora.shell_reaper")


class ShellReaper:
    def __init__(self) -> None:
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def schedule(self, session_id: uuid.UUID, *, delay_seconds: float | None = None) -> None:
        """Arm the reaper for a shell session that just lost its last subscriber.

        Idempotent per session: an existing timer is left alone rather than
        restarted, so a flapping connection cannot push the deadline out forever.
        """
        if session_id in self._tasks:
            return
        delay = (
            delay_seconds
            if delay_seconds is not None
            else get_settings().shell_idle_terminate_seconds
        )
        task = asyncio.create_task(self._reap(session_id, delay))
        self._tasks[session_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(session_id, None))

    async def _reap(self, session_id: uuid.UUID, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        # Imported here rather than at module scope: the relay imports nothing from
        # this module, and keeping the edge one-directional avoids an import cycle
        # through the WebSocket layer.
        from app.services.terminal_relay import get_terminal_relay

        if get_terminal_relay().subscriber_count(session_id) > 0:
            return  # somebody came back
        try:
            async with get_database().session() as db:
                service = SessionService(db)
                session = await service.get(session_id)
                if session.runtime != SHELL_RUNTIME or session.status in TERMINAL_STATES:
                    return
                await service.terminate(actor_id=session.user_id, session_id=session_id)
                await db.commit()
        except ApiError as exc:
            # A node that is offline or unresponsive cannot be cleaned up from here;
            # its own reconciliation on reconnect is what collects the tmux session.
            _logger.warning(
                "shell_reap_failed",
                extra={"event": "shell_reap_failed", "code": exc.code},
            )
            return
        _logger.info("shell_reaped", extra={"event": "shell_reaped"})

    async def cancel_all(self) -> None:
        """Drop every pending timer on shutdown. Terminating shells during a drain
        would turn a deploy into a fleet-wide teardown; the node keeps them and the
        next detach re-arms the timer."""
        for task in list(self._tasks.values()):
            task.cancel()
        self._tasks.clear()

    def pending(self) -> int:
        return len(self._tasks)


_reaper: ShellReaper | None = None


def get_shell_reaper() -> ShellReaper:
    global _reaper
    if _reaper is None:
        _reaper = ShellReaper()
    return _reaper
