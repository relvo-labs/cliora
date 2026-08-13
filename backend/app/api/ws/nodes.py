"""Authenticated daemon WebSocket endpoint (P1-13).

Handshake: Central sends a single-use nonce; the daemon signs it with its local
Ed25519 private key. Central verifies with the stored public key (ADR 0008), then registers the
connection, persists `node.register` metadata, and tracks heartbeats. Status is
computed from the monotonic heartbeat gap by the registry — never self-reported.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
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
from app.protocol.codec import MAX_PAYLOAD
from app.security.node_keys import new_challenge_id, new_request_id
from app.services.node_update import NodeUpdateService, outcome_from_payload
from app.services.nodes import (
    NodeRegistrationService,
    RegisterNodeInput,
    RuntimeInput,
    TunnelReportInput,
    WorkspaceRootInput,
)
from app.services.registry import get_node_registry
from app.services.run_logs import get_run_log_buffer
from app.services.runners import RunnerService
from app.services.runs import MessageService, RunService, release_claim
from app.services.sessions import SessionService
from app.services.terminal_relay import get_terminal_relay
from app.services.tunnels import TunnelService
from app.settings import get_settings

# Daemon terminal events (fresh ULID, not correlated responses) fanned out to
# the session's browser subscribers rather than matched to a pending request.
_TERMINAL_EVENTS = frozenset({"terminal.gap", "terminal.exited", "terminal.error"})

# V2.2 run events, all node→central and all **one-way** (ADR 0029 D2). Every one of
# them needs an explicit branch below, because the last branch of the control loop is
# `resolve_response()` and anything that reaches it is dropped with a warning — so a
# missing type looks like "the message vanished, with no error", which is the hardest
# bug in this phase to find. `GATE-AR-DISPATCH-COVERAGE` checks this set against the
# contract's own type list.
_RUN_EVENTS = frozenset({"run.accept", "run.decline", "run.lease_renew", "run.progress"})
_RUN_TERMINAL_EVENTS = frozenset({"run.complete", "run.failed"})

router = APIRouter()
_logger = get_logger("cliora.node_ws")


async def _absorb_log_chunk(session: AsyncSession, node_id: uuid.UUID, payload: Any) -> None:
    """Buffer one `run.log_chunk`, and write a row only when it is worth a round trip.

    The cap is enforced here rather than in the buffer so that the *decision* to start
    truncating — and the byte count that goes with it — is visible on the path that
    also owns the database write.
    """
    raw = payload.get("run_id") if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    seq = payload.get("seq") if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not isinstance(data, str) or not isinstance(seq, int):
        return
    try:
        run_id = uuid.UUID(raw)
    except ValueError:
        return
    buffer = get_run_log_buffer()
    limit = get_settings().run_log_max_bytes
    if buffer.total_bytes(run_id) >= limit and not buffer.is_truncating(run_id):
        buffer.begin_truncating(run_id)
    now = asyncio.get_running_loop().time()
    if buffer.append(run_id, seq, data, now=now):
        if await buffer.flush(session, run_id, now=now):
            await session.commit()


async def _flush_run_log(session: AsyncSession, run_id: uuid.UUID) -> None:
    buffer = get_run_log_buffer()
    now = asyncio.get_running_loop().time()
    await buffer.flush(session, run_id, now=now)
    buffer.discard(run_id)


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
            # Absent on an agentd older than contract 1.7.0, and absent means the
            # sandbox is enforced (ADR 0023). Unlike the tunnel report there is no
            # "has not said" state worth distinguishing: no claim, no bypass.
            sandbox_bypass=bool(r.get("sandbox_bypass", False)),
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
        # Absent on an agentd older than P11, which is why it is `None` rather than a set of
        # falses: "this node cannot forward ports" and "this node has not said" are different
        # answers and only one of them tells the user to upgrade the daemon.
        tunnel=TunnelReportInput.from_payload(payload.get("tunnel")),
        privileged_terminal=bool(payload.get("privileged_terminal", False)),
        image_upload=bool(payload.get("image_upload", False)),
        file_upload=bool(payload.get("file_upload", False)),
        # Absent on every daemon before 0.8.0, which is exactly the answer we want:
        # missing means incapable, and the session still starts (ADR 0028 sec 5).
        context_projection=bool(payload.get("context_projection", False)),
        # Absent on every daemon before 0.9.0, and the same answer applies: missing
        # means incapable, sessions are unaffected, and the node is simply never
        # offered a run (ADR 0029 sec 7).
        agent_runner=bool(payload.get("agent_runner", False)),
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
                # A runner reports why it stopped polling, because Central cannot tell:
                # a full runner, a runner out of disk and a machine that is gone are all
                # silence on this socket. Behind the flag, since the column only exists
                # in deployments that ran this phase's migration.
                if settings.agent_runs_enabled:
                    await RunnerService(session).record_pressure(
                        node_id, message.payload.get("runner")
                    )
                await session.commit()
            elif message.type == "node.system_info":
                await service.update_system_info(node_id, message.payload)
                await session.commit()
            elif message.type == "node.runtime_status":
                await service.update_runtime_status(
                    node_id,
                    _runtime_inputs(message.payload.get("runtimes", [])),
                    TunnelReportInput.from_payload(message.payload.get("tunnel")),
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
            elif message.type == "tunnel.status":
                # Unsolicited, like the terminal events: it carries a fresh ULID and matches
                # no pending request, so it has to be handled *before* the correlation
                # lookup below or it is discarded as an unmatched message. On the free tier
                # the provider issues a new URL on every reconnect, so this branch is the
                # only thing keeping the platform's copy of the URL true.
                await TunnelService(session).apply_status(node_id, message.payload)
                await session.commit()
            elif message.type == "runner.register":
                runner = await RunnerService(session).register(node_id, message.payload)
                await session.commit()
                await websocket.send_text(
                    _frame(
                        "runner.registered",
                        node_id,
                        message.request_id,
                        {"runner_id": str(runner.id), "enabled": runner.enabled},
                    )
                )
            elif message.type == "runner.poll":
                # **The claim happens here.** `run.offer` therefore means "this card is
                # already yours and the lease has started", not "would you like it".
                #
                # It is answered with a fresh one-way frame rather than a correlated
                # reply, because the daemon keeps no pending map for requests it sends
                # (`connection.go:494` is a single switch) — and because awaiting
                # anything from inside this loop is a guaranteed timeout (ADR 0029 D1).
                polling = await RunnerService(session).for_node(node_id)
                offer = None
                if polling is not None:
                    capacity = message.payload.get("capacity")
                    offer = await RunService(session).poll(
                        runner=polling,
                        capacity=capacity if isinstance(capacity, int) else 1,
                    )
                frame = _frame(
                    "run.offer",
                    node_id,
                    new_request_id(),
                    offer.spec() if offer is not None else {"run_id": None},
                )
                # **Measured before it is sent, and the claim is released if it does not
                # fit** (ADR 0032 Consequences, plan/20/00-…md D2). `run.offer` is a
                # 64 KiB control frame and is deliberately not in the large-frame set —
                # this socket also carries interactive terminal bytes. Without this
                # check the failure is the worst kind available: the receiver drops the
                # frame *silently*, the lease expires, the card is retried to exhaustion
                # and blocked, and nothing anywhere reports an error.
                #
                # The bound existed before this phase and could already be reached by a
                # long context; delivering secrets makes it reachable in practice.
                if offer is not None and len(frame.encode("utf-8")) > MAX_PAYLOAD:
                    await release_claim(session, offer.run)
                    await MessageService(session).post_event(
                        task=offer.task,
                        body=(
                            "這次派工的訊息超過了單一控制訊框的上限，因此認領被釋放、"
                            "卡片退回佇列。最可能的原因是情境包太長或宣告的機密太多。"
                        ),
                        event_kind="run.offer_too_large",
                    )
                    await session.commit()
                    frame = _frame("run.offer", node_id, new_request_id(), {"run_id": None})
                else:
                    await session.commit()
                await websocket.send_text(frame)
            elif message.type in _RUN_EVENTS:
                await RunService(session).apply_event(
                    node_id=node_id, message_type=message.type, payload=message.payload
                )
                await session.commit()
            elif message.type == "run.log_chunk":
                # Deliberately **not** committed per chunk: this socket also carries
                # interactive terminal output, and a database round trip per chunk buys
                # an agent's debug log with the terminal's responsiveness (ADR 0030).
                await _absorb_log_chunk(session, node_id, message.payload)
            elif message.type in _RUN_TERMINAL_EVENTS:
                run_id = message.payload.get("run_id")
                if isinstance(run_id, str):
                    with contextlib.suppress(ValueError):
                        await _flush_run_log(session, uuid.UUID(run_id))
                await RunService(session).finish(
                    node_id=node_id, message_type=message.type, payload=message.payload
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
