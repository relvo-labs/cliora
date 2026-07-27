"""Browser terminal WebSocket relay (P2-09/P2-10).

Handshake: a single-use ws-ticket bound to (user, session) (minted by
POST /api/sessions/{id}/attach) authorises the connection; the session must
exist and its node be online. The connection subscribes to the session's relay
hub, triggers a daemon attach, and pumps daemon output to the browser. Only the
current writer's input is relayed to the daemon (viewer/forged input is dropped,
SEC-002/FR-SESSION-007). Terminal bytes never touch the DB or logs (ADR 0004).
"""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.sessions import attach_resource
from app.clock import now_utc
from app.db.engine import get_session
from app.db.models import TerminalSession, User
from app.logging import get_logger
from app.protocol import encode_binary
from app.security.node_keys import new_request_id
from app.services import audit, authz
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.services.sessions import SessionService
from app.services.terminal_queue import BrowserChannel
from app.services.terminal_relay import TerminalRelay, get_terminal_relay
from app.services.ws_ticket import get_ws_ticket_service
from app.settings import get_settings

router = APIRouter()
_logger = get_logger("cliora.terminal_ws")

# RFC 6455 1013 "Try Again Later": the overflowed browser should reconnect, and the
# session it was watching is untouched (ADR 0013).
OVERFLOW_CLOSE_CODE = 1013


def _event(type_: str, session_id: uuid.UUID, payload: dict[str, object]) -> str:
    body = {
        "version": 1,
        "type": type_,
        "request_id": "00000000000000000000000000",
        "node_id": str(session_id),
        "timestamp": now_utc().isoformat().replace("+00:00", "Z"),
        "payload": {"session_id": str(session_id), **payload},
    }
    return json.dumps(body)


@router.websocket("/ws/sessions/{session_id}/terminal")
async def terminal_gateway(
    websocket: WebSocket,
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    await websocket.accept()

    # --- 1. Authorise via single-use ws-ticket bound to (user, session) ---
    ticket = websocket.query_params.get("ticket")
    user_id = (
        get_ws_ticket_service().consume(ticket, attach_resource(session_id)) if ticket else None
    )
    if user_id is None:
        await websocket.close(code=1008)
        return
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        await websocket.close(code=1008)
        return

    svc = SessionService(session)
    try:
        sess = await svc.get(session_id)
    except ApiError:
        await websocket.close(code=1008)
        return

    # Resource-scope check at the handshake. The ws-ticket proves *who* holds it;
    # it does not prove they may view this session — a role change between
    # minting the ticket and connecting must take effect (ADR 0016).
    if not authz.may_view_session(user, sess):
        await websocket.close(code=1008)
        return

    registry = get_node_registry()
    if not registry.is_connected(sess.node_id):
        await websocket.close(code=1011)
        return

    # --- 2. Subscribe to the session relay ---
    settings = get_settings()
    relay = get_terminal_relay()
    channel = BrowserChannel(settings.terminal_queue_max_bytes, settings.terminal_queue_max_frames)
    conn_id = uuid.uuid4().hex
    can_write = authz.may_write_session(user, sess)
    role = await relay.subscribe(session_id, conn_id, user.id, channel, can_write=can_write)
    node_id = sess.node_id

    async def pump() -> None:
        """Drain this browser's bounded channel to the socket in FIFO order."""
        while True:
            item = await channel.get()
            if item is None:
                return
            kind, payload = item
            try:
                if kind == "output" and isinstance(payload, bytes):
                    await websocket.send_bytes(payload)
                elif kind == "control" and isinstance(payload, str):
                    await websocket.send_text(payload)
                elif kind == "overflow":
                    await websocket.send_text(
                        _event("terminal.gap", session_id, {"reason": "overflow"})
                    )
                    # Then close, rather than merely stopping. Returning here used to
                    # leave the socket open with a dead pump: the browser had its gap
                    # notice but would never receive another byte, stayed counted in
                    # `active_terminal_connections`, stayed subscribed in the relay —
                    # and if it was the **writer**, kept the writer marker while being
                    # unable to see anything, so nobody else could take over normally.
                    # 1013 ("try again later") is what tells the client this is
                    # recoverable by reconnecting, which is exactly what it is: the
                    # session is still running on the node.
                    #
                    # Found by the P4-11 slow-client harness against a live Central; no
                    # unit test noticed, because every one of them asserted the gap was
                    # sent and none asserted what happened next.
                    await websocket.close(code=OVERFLOW_CLOSE_CODE)
                    return
            except (WebSocketDisconnect, RuntimeError):
                return

    pump_task = asyncio.create_task(pump())
    await websocket.send_text(_event("terminal.role", session_id, {"role": role}))

    # Audit the attach (metadata only — never terminal content; SEC-006).
    await audit.AuditService(session).record(
        audit.SESSION_ATTACH,
        user_id=user.id,
        node_id=node_id,
        session_id=session_id,
        metadata={"role": role},
    )
    await session.commit()

    # --- 3. Trigger the daemon attach (correlated) ---
    try:
        await registry.request(
            node_id,
            "session.attach",
            {"session_id": str(session_id), "rows": sess.rows, "columns": sess.columns},
            timeout_seconds=settings.session_attach_timeout_seconds,
        )
    except ApiError:
        await _teardown(relay, session_id, conn_id, channel, pump_task)
        await websocket.close(code=1011)
        return

    # --- 4. Browser → daemon (writer input + control) ---
    try:
        while True:
            event = await websocket.receive()
            if event.get("type") == "websocket.disconnect":
                break
            raw = event.get("bytes")
            if raw is not None:
                # Only the current writer's raw bytes reach the daemon PTY, and
                # write eligibility is re-checked here rather than trusted from
                # the handshake: a demotion mid-session must take effect on the
                # next keystroke (ADR 0016).
                if relay.is_writer(session_id, conn_id) and authz.may_write_session(user, sess):
                    frame = encode_binary(1, session_id, raw)
                    await registry.send_binary(node_id, frame)
                continue
            text = event.get("text")
            if text is not None:
                await _handle_browser_control(
                    text, registry, relay, node_id, sess, conn_id, user, session
                )
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await _teardown(relay, session_id, conn_id, channel, pump_task)


async def _handle_browser_control(
    text: str,
    registry: NodeConnectionRegistry,
    relay: TerminalRelay,
    node_id: uuid.UUID,
    sess: TerminalSession,
    conn_id: str,
    user: User,
    session: AsyncSession,
) -> None:
    """Authorize every inbound control message against the resource, not once at
    attach. A viewer's forged resize or takeover is dropped here (ADR 0016)."""
    session_id = sess.id
    try:
        msg = json.loads(text)
    except json.JSONDecodeError:
        return
    mtype = msg.get("type")
    if (
        mtype == "terminal.resize"
        and relay.is_writer(session_id, conn_id)
        and authz.may_write_session(user, sess)
    ):
        payload = msg.get("payload", {})
        rows, columns = payload.get("rows"), payload.get("columns")
        if isinstance(rows, int) and isinstance(columns, int):
            await registry.send_text_frame(
                node_id, _resize_frame(node_id, session_id, rows, columns)
            )
    elif mtype == "terminal.control_acquire" and authz.may_takeover_session(user, sess):
        if await relay.takeover(session_id, conn_id):
            # Notify all subscribers of the new writer assignment and audit it.
            await relay.route_control(
                session_id, _event("terminal.role", session_id, {"writer_conn": conn_id})
            )
            await audit.AuditService(session).record(
                audit.SESSION_TAKEOVER,
                user_id=user.id,
                node_id=node_id,
                session_id=session_id,
            )
            await session.commit()


def _resize_frame(node_id: uuid.UUID, session_id: uuid.UUID, rows: int, columns: int) -> str:
    return json.dumps(
        {
            "version": 1,
            "type": "terminal.resize",
            "request_id": new_request_id(),
            "node_id": str(node_id),
            "timestamp": now_utc().isoformat().replace("+00:00", "Z"),
            "payload": {"session_id": str(session_id), "rows": rows, "columns": columns},
        }
    )


async def _teardown(
    relay: TerminalRelay,
    session_id: uuid.UUID,
    conn_id: str,
    channel: BrowserChannel,
    pump_task: asyncio.Task[None],
) -> None:
    await relay.unsubscribe(session_id, conn_id)
    await channel.close()
    pump_task.cancel()
    try:
        await pump_task
    except (asyncio.CancelledError, Exception):
        pass
