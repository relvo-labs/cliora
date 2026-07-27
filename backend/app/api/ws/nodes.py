"""Authenticated daemon WebSocket endpoint (P1-13).

Handshake: Central sends a single-use nonce; the daemon signs it with its local
Ed25519 private key. Central verifies with the stored public key (ADR 0008), then registers the
connection, persists `node.register` metadata, and tracks heartbeats. Status is
computed from the monotonic heartbeat gap by the registry — never self-reported.
"""

from __future__ import annotations

import asyncio
import base64
import json
import secrets
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.engine import get_session
from app.logging import get_logger
from app.protocol import ProtocolError, decode_binary, decode_control
from app.security.node_keys import new_challenge_id
from app.services.node_update import NodeUpdateService, outcome_from_payload
from app.services.nodes import (
    NodeRegistrationService,
    RegisterNodeInput,
    RuntimeInput,
    WorkspaceRootInput,
)
from app.services.registry import get_node_registry
from app.services.sessions import SessionService
from app.services.terminal_relay import get_terminal_relay
from app.settings import get_settings

# Daemon terminal events (fresh ULID, not correlated responses) fanned out to
# the session's browser subscribers rather than matched to a pending request.
_TERMINAL_EVENTS = frozenset({"terminal.gap", "terminal.exited", "terminal.error"})

router = APIRouter()
_logger = get_logger("cliora.node_ws")


def _frame(type_: str, node_id: uuid.UUID, request_id: str, payload: dict[str, Any]) -> str:
    timestamp = now_utc().isoformat().replace("+00:00", "Z")
    return json.dumps(
        {
            "version": 1,
            "type": type_,
            "request_id": request_id,
            "node_id": str(node_id),
            "timestamp": timestamp,
            "success": True,
            "payload": payload,
        }
    )


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _runtime_inputs(items: list[dict[str, Any]]) -> list[RuntimeInput]:
    return [
        RuntimeInput(
            runtime=r["runtime"],
            available=r["available"],
            version=r.get("version"),
            binary_path=r.get("binary_path"),
            checked_at=_parse_ts(r.get("checked_at")),
        )
        for r in items
    ]


def _register_input(payload: dict[str, Any]) -> RegisterNodeInput:
    return RegisterNodeInput(
        name=payload["name"],
        hostname=payload["hostname"],
        os=payload["os"],
        os_version=payload["os_version"],
        architecture=payload["architecture"],
        daemon_version=payload["daemon_version"],
        run_user=payload["run_user"],
        runtimes=_runtime_inputs(payload.get("runtimes", [])),
        workspace_roots=[
            WorkspaceRootInput(
                path=w["path"], display_name=w.get("display_name"), is_enabled=w["is_enabled"]
            )
            for w in payload.get("workspace_roots", [])
        ],
    )


@router.websocket("/ws/nodes/{node_id}")
async def node_gateway(
    websocket: WebSocket,
    node_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    await websocket.accept()
    settings = get_settings()

    # --- 1. Authentication: issue a single-use random challenge. ---
    challenge_id = new_challenge_id()
    nonce = base64.b64encode(secrets.token_bytes(32)).decode()
    await websocket.send_text(_frame("node.challenge", node_id, challenge_id, {"nonce": nonce}))
    try:
        first = decode_control(
            await asyncio.wait_for(
                websocket.receive_text(), timeout=settings.hmac_challenge_ttl_seconds
            )
        )
    except (WebSocketDisconnect, ProtocolError, TimeoutError):
        await websocket.close(code=1002)
        return
    if first.type != "node.auth" or first.node_id != node_id:
        await websocket.close(code=1008)
        return
    signature = first.payload.get("signature", "")
    response_challenge = first.payload.get("challenge_id", "")
    service = NodeRegistrationService(session)
    try:
        if response_challenge != challenge_id:
            raise ApiError("NODE_AUTH_FAILED", "auth failed")
        await service.authenticate_signature(
            node_id, challenge_id, nonce, signature if isinstance(signature, str) else ""
        )
    except ApiError:
        _logger.info(
            "node_auth_failed", extra={"event": "node_auth_failed", "node_id": str(node_id)}
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "success": False,
                    "error": {"code": "NODE_AUTH_FAILED", "message": "auth failed"},
                }
            )
        )
        await websocket.close(code=1008)
        return
    await websocket.send_text(
        _frame("node.authenticated", node_id, first.request_id, {"node_id": str(node_id)})
    )

    # --- 2. Register the live connection (evict any stale one) ---
    registry = get_node_registry()
    connection, previous = await registry.register(node_id, websocket)
    if previous is not None:
        try:
            await previous.websocket.close(code=1012)
        except RuntimeError:
            pass

    # --- 3. Control loop (text control + binary terminal output) ---
    relay = get_terminal_relay()
    try:
        while True:
            event = await websocket.receive()
            if event.get("type") == "websocket.disconnect":
                break
            raw_bytes = event.get("bytes")
            if raw_bytes is not None:
                # Daemon → browser terminal output (kind=2); fan out by session.
                try:
                    kind, session_id, payload = decode_binary(raw_bytes)
                except ProtocolError:
                    continue
                if kind == 2:
                    await relay.route_output(session_id, payload)
                continue
            text = event.get("text")
            if text is None:
                continue
            try:
                message = decode_control(text)
            except ProtocolError:
                continue
            if message.type == "node.register":
                await service.persist_registration(node_id, _register_input(message.payload))
                await session.commit()
                await websocket.send_text(
                    _frame(
                        "node.registered", node_id, message.request_id, {"node_id": str(node_id)}
                    )
                )
            elif message.type == "node.heartbeat":
                await registry.touch(node_id)
                resources = message.payload.get("resources")
                registry.set_resources(node_id, resources if isinstance(resources, dict) else None)
                await service.record_heartbeat(node_id)
                # Persisted at a reduced rate (P4-06): the live sample above is what
                # the node views read, this is the history the Dashboard and the
                # runbooks need after a Central restart. A failed write is counted
                # and swallowed inside the service so it cannot break liveness.
                if registry.claim_metric_sample(
                    node_id, settings.node_metric_sample_interval_seconds
                ):
                    await service.persist_metric_sample(node_id, message.payload)
                await session.commit()
            elif message.type == "node.system_info":
                await service.update_system_info(node_id, message.payload)
                await session.commit()
            elif message.type == "node.runtime_status":
                await service.update_runtime_status(
                    node_id, _runtime_inputs(message.payload.get("runtimes", []))
                )
                await session.commit()
            elif message.type == "node.shutdown":
                break
            elif message.type == "session.status_changed":
                sid = message.payload.get("session_id")
                new_status = message.payload.get("status")
                exit_code = message.payload.get("exit_code")
                if isinstance(sid, str) and isinstance(new_status, str):
                    await SessionService(session).apply_status_changed(
                        uuid.UUID(sid),
                        new_status,
                        exit_code=exit_code if isinstance(exit_code, int) else None,
                    )
                    await session.commit()
            elif message.type == "daemon.update_result":
                # An update restarts the daemon, which drops the socket the
                # correlated reply was going to travel on. The fresh connection
                # reports the outcome unsolicited, and this is how a row stops being
                # stuck at `in_progress`. Resolving it as a correlated response first
                # covers the (rarer) case where the reply did make it back in time.
                if not registry.resolve_response(node_id, message):
                    await NodeUpdateService(session).apply_result(
                        node_id, outcome_from_payload(message.payload)
                    )
                    await session.commit()
            elif message.type in _TERMINAL_EVENTS:
                sid = message.payload.get("session_id")
                if isinstance(sid, str):
                    try:
                        await relay.route_control(uuid.UUID(sid), text)
                    except ValueError:
                        pass
            elif not registry.resolve_response(node_id, message):
                # A response to no known request (late/duplicate/unknown id) — drop it.
                _logger.warning(
                    "node_ws_unmatched_message",
                    extra={
                        "event": "node_ws_unmatched_message",
                        "node_id": str(node_id),
                        "message_type": message.type,
                    },
                )
    except (WebSocketDisconnect, ProtocolError):
        pass
    finally:
        await registry.remove(node_id, connection)
