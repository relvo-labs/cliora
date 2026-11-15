"""The admission probe must act like registered daemons, then release every resource."""

import asyncio
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


@pytest.fixture
def rig(monkeypatch):
    from app.protocol.codec import decode_control

    monkeypatch.setenv("EDGE_BASE", "https://edge.invalid")
    monkeypatch.setenv("EDGE_SETUP_BASE", "http://central.invalid")
    monkeypatch.setenv("CLIORA_VERIFY_ADMIN", "probe-admin")
    monkeypatch.setenv("CLIORA_VERIFY_PASSWORD", "probe-password")
    spec = importlib.util.spec_from_file_location(
        "edge_limit_probe", ROOT / "scripts/railway/edge_limit_probe.py"
    )
    assert spec and spec.loader
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    monkeypatch.setattr(probe, "HEARTBEAT_INTERVAL_SECONDS", 0.001, raising=False)
    nodes, sockets, deleted, beats = [], [], [], []
    state = SimpleNamespace(bad_ack=None, revoked=False, cap_attempts=0)

    def request(base, path, body=None, token=None, method=None):
        if path == "/api/auth/login":
            return 200, {"tokens": {"access_token": "test-access"}}
        if path == "/api/enrollment-tokens" and method != "DELETE":
            state.max_uses = body["max_uses"]
            return 201, {"id": "test-enrollment", "token": "test-enrollment-token"}
        if path == "/api/nodes/register":
            # Model the transaction retained by an idle authenticated socket: even a
            # one-connection pool must suffice once each node has registered.
            assert all(s.acked for s in sockets if s.authenticated), (
                "must await node.registered before more setup"
            )
            node = str(uuid.uuid4())
            nodes.append(node)
            return 201, {"node_id": node}
        if path.startswith("/api/nodes/") and method == "DELETE":
            deleted.append(path.rsplit("/", 1)[1])
            return 204, {}
        if path == "/api/enrollment-tokens/test-enrollment" and method == "DELETE":
            state.revoked = True
            return 204, {}
        raise AssertionError(path)

    class Socket:
        def __init__(self, node):
            self.node, self.authenticated, self.acked = node, False, False
            self.state = SimpleNamespace(name="OPEN")
            self.sent = []

        async def __aenter__(self):
            assert all(s.acked for s in sockets), "must await node.registered before next socket"
            if len(sockets) == 50:
                state.cap_attempts += 1
                raise InvalidStatus(Response(429, "Too Many Requests", Headers()))
            sockets.append(self)
            return self

        async def __aexit__(self, *args):
            self.state.name = "CLOSED"

        async def recv(self):
            if not self.sent:
                return json.dumps(
                    {
                        "type": "node.challenge",
                        "request_id": "01K0ABCDEFGHJKMNPQRSTVWXYZ",
                        "payload": {"nonce": "test-nonce"},
                    }
                )
            last = self.sent[-1]
            if last["type"] == "node.auth":
                self.authenticated = True
                return json.dumps({"type": "node.authenticated"})
            assert last["type"] == "node.register"
            assert not self.acked
            self.acked = True
            reply = {
                "type": "node.registered",
                "node_id": self.node,
                "request_id": last["request_id"],
                "payload": {"node_id": self.node},
            }
            if state.bad_ack:
                reply[state.bad_ack] = "wrong"
            return json.dumps(reply)

        async def send(self, raw):
            message = decode_control(raw)  # validates payload AND envelope against v1
            if message.type == "node.heartbeat":
                assert self.acked, "heartbeat before registration acknowledgement"
                beats.append(self.node)
            self.sent.append(json.loads(raw))

        async def ping(self):
            pong = asyncio.get_running_loop().create_future()
            pong.set_result(None)
            return pong

    class Terminal:
        close_code = 1008

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def wait_closed(self):
            pass

    def connect(url, **kwargs):
        if "/ws/sessions/" in url:
            return Terminal()
        return Socket(url.rsplit("/", 1)[1])

    monkeypatch.setattr(probe, "request", request)
    monkeypatch.setattr(probe, "connect", connect)
    return SimpleNamespace(
        probe=probe, nodes=nodes, sockets=sockets, deleted=deleted, beats=beats, state=state
    )


@pytest.mark.asyncio
async def test_register_ack_before_next_socket_and_cleanup(rig) -> None:
    await rig.probe.connection_cap()
    assert len(rig.nodes) == rig.state.max_uses == 51
    assert len(rig.sockets) == 50 and all(s.acked for s in rig.sockets)
    assert set(rig.beats) == set(rig.nodes[:50])
    assert rig.state.cap_attempts == 1
    assert set(rig.deleted) == set(rig.nodes) and rig.state.revoked
    assert all(s.state.name == "CLOSED" for s in rig.sockets)
    assert not any(t.get_name() == "edge-limit-heartbeats" for t in asyncio.all_tasks())


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ack", ["type", "request_id", "node_id"])
async def test_bad_register_ack_fails_and_cleans_everything(rig, bad_ack: str) -> None:
    rig.state.bad_ack = bad_ack
    with pytest.raises(AssertionError, match="node.registered"):
        await rig.probe.connection_cap()
    assert set(rig.deleted) == set(rig.nodes) and rig.state.revoked
    assert all(s.state.name == "CLOSED" for s in rig.sockets)
    assert not any(t.get_name() == "edge-limit-heartbeats" for t in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_register_burst_uses_unambiguous_wrong_method(rig, monkeypatch) -> None:
    counts = {}
    methods = []

    def request(base, path, body=None, token=None, method=None):
        counts[path] = counts.get(path, 0) + 1
        if path == "/api/nodes/register":
            methods.append(method)
            # GET is handled by /api/nodes/{node_id}'s auth dependency, hence 401.
            return (405 if method == "OPTIONS" else 401, {}) if counts[path] == 1 else (429, {})
        if path.startswith("/api/auth/"):
            return (405 if counts[path] <= 11 else 429), {}
        return 200, {}

    monkeypatch.setattr(rig.probe, "request", request)
    await rig.probe.http_limits()
    assert methods == ["OPTIONS", "OPTIONS"]
