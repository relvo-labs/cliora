"""Pending node admission at the ASGI socket boundary (issue #59 part C)."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import WebSocket
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app import metrics
from app.api.errors import ApiError
from app.api.ws import nodes
from app.services.node_pending import PendingNodeConnections
from app.services.registry import NodeConnectionRegistry
from app.services.terminal_relay import TerminalRelay
from app.settings import Settings

REJECTED = "node_ws_pending_rejected_total"
RID = "01K0ABCDEFGHJKMNPQRSTVWXYZ"


class Peer:
    def __init__(self, host, *, fail_at=None):
        self.node_id = uuid.uuid4()
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.sent = []
        self.fail_at = fail_at
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.socket = WebSocket(
            {
                "type": "websocket",
                "path": f"/ws/nodes/{self.node_id}",
                "client": None if host is None else (host, 12345),
                # A forged header must not change the scope client's bucket.
                "headers": [(b"x-forwarded-for", str(self.node_id).encode())],
            },
            self.receive,
            self.send,
        )
        self.task = asyncio.create_task(
            nodes.node_gateway(self.socket, self.node_id, AsyncMock(spec=AsyncSession))
        )

    async def receive(self):
        event = await self.incoming.get()
        if self.fail_at == "receive" and event["type"] != "websocket.connect":
            raise RuntimeError("receive failed")
        return event

    async def send(self, event):
        body = json.loads(event["text"]) if "text" in event else {}
        stage = body.get("type", event["type"])
        if self.fail_at == stage:
            raise RuntimeError("send failed")
        self.sent.append(event)
        self.outgoing.put_nowait(event)

    async def next(self):
        return await asyncio.wait_for(self.outgoing.get(), timeout=2)

    def auth(self, **changes):
        challenge = json.loads(self.sent[-1]["text"])
        frame = {
            "version": 1,
            "type": "node.auth",
            "node_id": str(self.node_id),
            "request_id": RID,
            "timestamp": "2026-11-15T00:00:00Z",
            "payload": {"challenge_id": challenge["request_id"], "signature": "A" * 86 + "=="},
        }
        frame.update(changes)
        self.push(json.dumps(frame))

    def push(self, text):
        self.incoming.put_nowait({"type": "websocket.receive", "text": text})

    def disconnect(self, code=1000):
        self.incoming.put_nowait({"type": "websocket.disconnect", "code": code})


@pytest_asyncio.fixture
async def peers(monkeypatch):
    settings = SimpleNamespace(
        **(Settings().model_dump() | {"node_ws_pending_max": 64, "node_ws_pending_per_ip_max": 10})
    )
    monkeypatch.setattr(nodes, "get_settings", lambda: settings)
    registry = NodeConnectionRegistry()
    monkeypatch.setattr(nodes, "get_node_registry", lambda: registry)
    monkeypatch.setattr(nodes, "get_terminal_relay", lambda: TerminalRelay())
    monkeypatch.setattr(
        nodes.NodeRegistrationService, "authenticate_signature", AsyncMock(return_value=None)
    )
    opened = []

    async def open_peer(host="192.0.2.1", **kwargs):
        peer = Peer(host, **kwargs)
        opened.append(peer)
        return peer

    yield settings, open_peer
    for peer in opened:
        peer.task.cancel()
    await asyncio.gather(*(peer.task for peer in opened), return_exceptions=True)


async def challenged(peer):
    assert await peer.next() == {"type": "websocket.accept", "subprotocol": None, "headers": []}
    assert json.loads((await peer.next())["text"])["type"] == "node.challenge"


async def rejected(peer):
    assert (await peer.next())["type"] == "websocket.accept"
    assert await peer.next() == {"type": "websocket.close", "code": 1013, "reason": ""}
    await peer.task
    assert all(event["type"] != "websocket.send" for event in peer.sent)


def test_pending_defaults():
    settings = Settings()
    assert settings.hmac_challenge_ttl_seconds == 10
    assert settings.node_ws_pending_max == 64
    assert settings.node_ws_pending_per_ip_max == 10


def test_pending_limits_are_configurable_and_must_be_positive(monkeypatch):
    monkeypatch.setenv("CLIORA_NODE_WS_PENDING_MAX", "8")
    monkeypatch.setenv("CLIORA_NODE_WS_PENDING_PER_IP_MAX", "3")
    assert Settings().node_ws_pending_max == 8
    assert Settings().node_ws_pending_per_ip_max == 3
    for name in ("CLIORA_NODE_WS_PENDING_MAX", "CLIORA_NODE_WS_PENDING_PER_IP_MAX"):
        with monkeypatch.context() as patch:
            patch.setenv(name, "0")
            with pytest.raises(ValidationError):
                Settings()


def test_ip_state_is_bounded_during_rejection_and_deleted_after_release():
    limiter = PendingNodeConnections()
    with limiter.slot("active", total_max=1, per_ip_max=1) as admitted:
        assert admitted
        for index in range(1000):
            with limiter.slot(str(index), total_max=1, per_ip_max=1) as rejected:
                assert not rejected
        assert limiter._by_ip == {"active": 1}
    for index in range(1000):
        with limiter.slot(str(index), total_max=1, per_ip_max=1) as admitted:
            assert admitted
    assert limiter._by_ip == {}
    assert limiter._total == 0


async def test_global_cap_rejects_without_challenge_and_counts_bounded_metric(peers):
    _, open_peer = peers
    before = metrics.counter_value(REJECTED, reason="global")
    for index in range(64):
        await challenged(await open_peer(f"192.0.2.{index}"))
    for index in range(20):
        await rejected(await open_peer(f"198.51.100.{index}"))
    assert metrics.counter_value(REJECTED, reason="global") == before + 20
    series, _ = metrics.export_series()
    assert all(
        key in {(("reason", "global"),), (("reason", "per_ip"),)}
        for name, key, _ in series
        if name == REJECTED
    )


@pytest.mark.parametrize("host", ["192.0.2.1", None])
async def test_per_ip_cap_is_independent_and_unknown_clients_share_bucket(peers, host):
    _, open_peer = peers
    before = metrics.counter_value(REJECTED, reason="per_ip")
    for _ in range(10):
        await challenged(await open_peer(host))
    await rejected(await open_peer(host))
    await challenged(await open_peer("198.51.100.1"))
    assert metrics.counter_value(REJECTED, reason="per_ip") == before + 1


async def test_authenticated_nodes_release_slot_and_remain_connected_when_cap_fills(peers):
    settings, open_peer = peers
    settings.node_ws_pending_max = 2
    settings.node_ws_pending_per_ip_max = 2
    blocker = await open_peer()
    await challenged(blocker)
    for _ in range(10):
        authenticated = await open_peer()
        await challenged(authenticated)
        authenticated.auth()
        assert json.loads((await authenticated.next())["text"])["type"] == "node.authenticated"
        assert not authenticated.task.done()
    second = await open_peer()
    await challenged(second)
    await rejected(await open_peer())
    assert not blocker.task.done()
    assert not authenticated.task.done()
    assert nodes.get_node_registry().connection_count == 10


@pytest.mark.parametrize(
    "exit_path",
    [
        "malformed",
        "wrong_type",
        "wrong_node",
        "replayed",
        "signature",
        "timeout",
        "disconnect",
        "shutdown_disconnect",
        "cancel",
        "accept_error",
        "challenge_error",
        "receive_error",
        "verify_error",
        "error_send",
        "close_error",
        "authenticated_send",
    ],
)
async def test_slot_released_on_every_pre_auth_exit_without_leaking(peers, monkeypatch, exit_path):
    settings, open_peer = peers
    settings.node_ws_pending_max = 1
    settings.node_ws_pending_per_ip_max = 1
    settings.hmac_challenge_ttl_seconds = 0.01
    for _ in range(10):
        stage = {
            "accept_error": "websocket.accept",
            "challenge_error": "node.challenge",
            "receive_error": "receive",
            "error_send": "error",
            "close_error": "websocket.close",
            "authenticated_send": "node.authenticated",
        }.get(exit_path)
        peer = await open_peer(fail_at=stage)
        verify = AsyncMock(return_value=None)
        if exit_path in {"signature", "error_send"}:
            verify.side_effect = ApiError("NODE_AUTH_FAILED", "auth failed")
        elif exit_path == "verify_error":
            verify.side_effect = RuntimeError("database failed")
        monkeypatch.setattr(nodes.NodeRegistrationService, "authenticate_signature", verify)
        if exit_path in {"accept_error", "challenge_error"}:
            with pytest.raises(RuntimeError):
                await peer.task
        else:
            await challenged(peer)
            if exit_path in {"malformed", "close_error"}:
                peer.push("not json")
            elif exit_path == "wrong_type":
                peer.auth(type="node.shutdown", payload={"reason": "shutdown"})
            elif exit_path == "wrong_node":
                peer.auth(node_id=str(uuid.uuid4()))
            elif exit_path == "replayed":
                peer.auth(payload={"challenge_id": RID, "signature": "A" * 86 + "=="})
            elif exit_path in {"disconnect", "shutdown_disconnect"}:
                peer.disconnect(1012 if exit_path == "shutdown_disconnect" else 1000)
            elif exit_path == "cancel":
                peer.task.cancel()
            elif exit_path != "timeout":
                peer.auth()
            if exit_path == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await peer.task
            elif exit_path in {
                "receive_error",
                "verify_error",
                "error_send",
                "close_error",
                "authenticated_send",
            }:
                with pytest.raises(RuntimeError):
                    await peer.task
            else:
                await peer.task
                assert peer.sent[-1]["code"] in {1002, 1008}
    # One new occupant must fill the slot: neither a leak nor a double release.
    replacement = await open_peer()
    await challenged(replacement)
    await rejected(await open_peer())


async def test_default_challenge_wait_expires_after_ten_seconds(peers):
    settings, open_peer = peers
    settings.node_ws_pending_max = 1
    peer = await open_peer()
    started = asyncio.get_running_loop().time()
    await challenged(peer)
    await asyncio.wait_for(peer.task, timeout=12)
    elapsed = asyncio.get_running_loop().time() - started
    assert 9.5 <= elapsed < 12
    assert peer.sent[-1]["code"] == 1002
    await challenged(await open_peer())
