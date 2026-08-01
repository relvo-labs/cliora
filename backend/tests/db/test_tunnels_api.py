"""Port-forwarding API against the real schema (PG-07/PG-08/PG-09, ADR 0022).

The daemon round trip is faked through the `get_registry` dependency, the same way the session
API tests do it. What is real here is everything that matters for this feature: the three-layer
policy, the three limits, the credential's one-way trip, and the fact that a password appears
in exactly one response.

Several tests assert on the *absence* of something in a response body. Those are written
against the serialized JSON rather than against the DTO type, because "the type has no field
for it" stops being true the moment somebody adds a convenient one.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.http.tunnels import get_registry
from app.db.models import AuditLog, Node, NodeTunnel, Role, TunnelIntegration, User
from app.main import app
from app.protocol import ControlMessage
from app.security.passwords import hash_password, verify_password
from app.services import audit

pytestmark = pytest.mark.asyncio

# A key for the tests that store a credential. Set on the process, because `secret_box` reads
# it through `get_settings()`; the fixture below restores whatever was there.
_TEST_KEY = base64.b64encode(b"k" * 32).decode()
_TOKEN = "AAAAAAAABBBBBBBB"


@pytest.fixture(autouse=True)
def _encryption_key() -> object:
    from app.settings import get_settings

    previous = os.environ.get("CLIORA_SECRET_ENCRYPTION_KEY")
    os.environ["CLIORA_SECRET_ENCRYPTION_KEY"] = _TEST_KEY
    get_settings.cache_clear()
    yield
    if previous is None:
        os.environ.pop("CLIORA_SECRET_ENCRYPTION_KEY", None)
    else:
        os.environ["CLIORA_SECRET_ENCRYPTION_KEY"] = previous
    get_settings.cache_clear()


def _msg(type_: str, node_id: uuid.UUID, payload: dict, *, success: bool = True) -> ControlMessage:
    return ControlMessage(
        version=1,
        type=type_,
        request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
        node_id=node_id,
        timestamp="2026-08-01T00:00:00Z",
        payload=payload,
        success=success,
    )


class FakeRegistry:
    """A node that answers `tunnel.open` the way the daemon does.

    `opens` keeps every payload it was sent, which is how the credential tests can assert what
    crossed the wire without the service having to expose it.
    """

    def __init__(
        self,
        *,
        connected: bool = True,
        url: str = "https://abc-1-2-3-4.run.pinggy-free.link",
        authenticated: bool | None = None,
        error_code: str | None = None,
    ) -> None:
        self.connected = connected
        self.url = url
        self.authenticated = authenticated
        self.error_code = error_code
        self.opens: list[dict] = []
        self.closes: list[str] = []

    def is_connected(self, node_id: uuid.UUID) -> bool:
        return self.connected

    async def request(self, node_id, type_, payload, *, timeout_seconds, request_id=None):
        if type_ == "tunnel.open":
            self.opens.append(json.loads(json.dumps(payload)))
            if self.error_code:
                return ControlMessage(
                    version=1,
                    type="error",
                    request_id="01K0ABCDEFGHJKMNPQRSTVWXYZ",
                    node_id=node_id,
                    timestamp="2026-08-01T00:00:00Z",
                    payload={},
                    success=False,
                    error={"code": self.error_code, "message": "the provider refused"},
                )
            body: dict[str, object] = {
                "tunnel_id": payload["tunnel_id"],
                "url": self.url,
                "provider": "pinggy",
            }
            if self.authenticated is not None:
                body["authenticated"] = self.authenticated
            return _msg("tunnel.opened", node_id, body)
        if type_ == "tunnel.close":
            self.closes.append(payload["tunnel_id"])
            return _msg("tunnel.closed", node_id, {"tunnel_id": payload["tunnel_id"]})
        raise AssertionError(f"unexpected request type {type_}")


@contextmanager
def use_registry(fake: FakeRegistry):
    app.dependency_overrides[get_registry] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_registry, None)


async def _login(client: AsyncClient, maker: async_sessionmaker, *, role_name: str) -> dict:
    username = f"u-{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        role = (await session.execute(sa.select(Role).where(Role.name == role_name))).scalar_one()
        session.add(
            User(
                username=username,
                password_hash=hash_password("pw"),
                display_name=username,
                role_id=role.id,
            )
        )
        await session.commit()
    resp = await client.post("/api/auth/login", json={"username": username, "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _node(
    maker: async_sessionmaker,
    *,
    veto: bool = False,
    prereq_ok: bool = True,
    local_ports: list[str] | None = None,
    local_max: int | None = None,
    reported: bool = True,
) -> uuid.UUID:
    async with maker() as session:
        node = Node(
            name="vm",
            hostname="vm",
            status="online",
            is_enabled=True,
            tunnel_veto=veto,
            tunnel_prereq_ok=prereq_ok,
            tunnel_prereq_detail={
                "ssh_available": True,
                "egress_ok": prereq_ok,
                "known_hosts_ok": True,
                "daemon_supports_tunnel": True,
            },
            tunnel_local_allowed_ports=local_ports,
            tunnel_local_max=local_max,
            tunnel_reported_at=datetime.now(UTC) if reported else None,
        )
        session.add(node)
        await session.commit()
        return node.id


async def _enable_integration(
    client: AsyncClient, admin: dict, *, plan_tier: str = "free", **fields: object
) -> dict:
    """Enable the integration the way an administrator does: through the API.

    Deliberately not by inserting a row. The acknowledgement, the credential and the enable
    are three separate refusable steps, and a test that writes the row directly would pass
    even if the API let one of them be skipped.
    """
    if plan_tier == "pro":
        resp = await client.put(
            "/api/integrations/tunnel/credential",
            json={"token": _TOKEN, "plan_tier": "pro"},
            headers=admin,
        )
        assert resp.status_code == 200, resp.text
    resp = await client.put(
        "/api/integrations/tunnel",
        json={"enabled": True, "acknowledge": True, **fields},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_body(node_id: uuid.UUID, **over: object) -> dict:
    body: dict[str, object] = {
        "node_id": str(node_id),
        "port": 5173,
        "protection": "basic",
        "acknowledge_third_party": True,
    }
    body.update(over)
    return body


async def _rows(maker: async_sessionmaker, action: str) -> list[AuditLog]:
    async with maker() as session:
        result = await session.execute(sa.select(AuditLog).where(AuditLog.action == action))
        return list(result.scalars().all())


# --- The integration switch --------------------------------------------------------- #


async def test_every_tunnel_route_is_absent_until_the_integration_is_enabled(api: tuple) -> None:
    """The switch lives in the database, so turning it off in the UI has to make the API
    agree at once — 404, not 403: with it off, this is not a capability the deployment has."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        assert (await client.get("/api/tunnels", headers=admin)).status_code == 404
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        assert created.status_code == 404
        policy = await client.get(f"/api/nodes/{node_id}/tunnel-policy", headers=admin)
        assert policy.status_code == 404


async def test_enabling_without_the_acknowledgement_is_refused(api: tuple) -> None:
    """D14, first of two places. The acknowledgement is a person accepting that traffic
    leaves for a third party; defaulting it would make the record meaningless."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    resp = await client.put("/api/integrations/tunnel", json={"enabled": True}, headers=admin)
    assert resp.status_code == 422
    assert (await client.get("/api/integrations/tunnel", headers=admin)).json()["enabled"] is False


async def test_the_paid_tier_is_refused_without_a_credential(api: tuple) -> None:
    """Pro with no credential is a combination that can only fail, and it would fail later,
    on somebody else's tunnel."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    resp = await client.put(
        "/api/integrations/tunnel",
        json={"enabled": True, "acknowledge": True, "plan_tier": "pro"},
        headers=admin,
    )
    assert resp.status_code == 422


# --- The credential is write-only --------------------------------------------------- #


async def test_the_integration_response_never_carries_the_token(api: tuple) -> None:
    """D19, asserted against the serialized body: the token must not be present as a value,
    a prefix, or a masked form, on the response that just stored it or on any read after."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    stored = await client.put(
        "/api/integrations/tunnel/credential", json={"token": _TOKEN}, headers=admin
    )
    assert stored.status_code == 200, stored.text
    read = await client.get("/api/integrations/tunnel", headers=admin)
    for body in (stored.text, read.text):
        assert _TOKEN not in body
        assert _TOKEN[:6] not in body
    credential = read.json()["credential"]
    assert credential["configured"] is True
    assert len(credential["fingerprint"]) == 8
    assert read.json()["secret_key_available"] is True


async def test_the_stored_token_is_ciphertext_in_the_database(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await client.put("/api/integrations/tunnel/credential", json={"token": _TOKEN}, headers=admin)
    async with maker() as session:
        row = (await session.execute(sa.select(TunnelIntegration))).scalar_one()
    assert row.token_ciphertext is not None and row.token_nonce is not None
    assert _TOKEN.encode() not in row.token_ciphertext
    assert row.token_fingerprint is not None and _TOKEN[:4] not in row.token_fingerprint


async def test_a_token_outside_the_permitted_character_set_is_refused(api: tuple) -> None:
    """The character set is a security control: this value is concatenated into ssh's
    `<token>@<host>` argument, where `+` selects a tunnel type and `@` selects the host."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    for bad in ("abc+tcp", "tok@evil.host", "short", "tok en12345"):
        resp = await client.put(
            "/api/integrations/tunnel/credential", json={"token": bad}, headers=admin
        )
        assert resp.status_code == 422, bad


async def test_clearing_the_credential_drops_the_paid_tier_with_it(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await client.put(
        "/api/integrations/tunnel/credential",
        json={"token": _TOKEN, "plan_tier": "pro"},
        headers=admin,
    )
    cleared = await client.delete("/api/integrations/tunnel/credential", headers=admin)
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["credential"]["configured"] is False
    assert body["plan_tier"] == "free"


async def test_the_credential_audit_records_the_fingerprint_and_nothing_else(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await client.put("/api/integrations/tunnel/credential", json={"token": _TOKEN}, headers=admin)
    rows = await _rows(maker, audit.INTEGRATION_CREDENTIAL_SET)
    assert len(rows) == 1
    metadata = rows[0].audit_metadata
    assert len(metadata["fingerprint"]) == 8
    assert _TOKEN not in json.dumps(metadata)


async def test_a_developer_may_not_touch_the_integration_settings(api: tuple) -> None:
    """`integration.manage` is Admin-only: a Developer may open tunnels, but not decide whose
    service and whose account the organisation uses."""
    client, maker = api
    dev = await _login(client, maker, role_name="Developer")
    assert (await client.get("/api/integrations/tunnel", headers=dev)).status_code == 403
    assert (
        await client.put("/api/integrations/tunnel", json={"enabled": True}, headers=dev)
    ).status_code == 403
    assert (
        await client.put("/api/integrations/tunnel/credential", json={"token": _TOKEN}, headers=dev)
    ).status_code == 403
    cleared = await client.delete("/api/integrations/tunnel/credential", headers=dev)
    assert cleared.status_code == 403


# --- Creating -------------------------------------------------------------------------- #


async def test_creating_returns_the_url_and_the_only_copy_of_the_password(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    fake = FakeRegistry()
    with use_registry(fake):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        assert created.status_code == 201, created.text
        detail = created.json()
        assert detail["url"] == fake.url
        assert detail["state"] == "running"
        assert detail["basic_auth_user"] == "preview"
        password = detail["basic_auth_password"]
        assert password and ":" not in password

        listed = await client.get("/api/tunnels", headers=admin)
        assert listed.status_code == 200
        assert "basic_auth_password" not in listed.text
        assert password not in listed.text

    async with maker() as session:
        row = (await session.execute(sa.select(NodeTunnel))).scalar_one()
    # Only the hash is stored, following the enrollment-token discipline: the plaintext exists
    # in one response and then nowhere.
    assert row.basic_auth_hash != password
    assert verify_password(row.basic_auth_hash, password)


async def test_the_open_frame_carries_no_credential_on_the_free_tier(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    fake = FakeRegistry()
    with use_registry(fake):
        assert (
            await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        ).status_code == 201
    assert "credential" not in fake.opens[0]


async def test_the_paid_tier_sends_the_decrypted_credential_and_records_its_fingerprint(
    api: tuple,
) -> None:
    """The one decryption site, observed from the outside: the plaintext reaches the frame,
    the audit row names which credential opened the tunnel, and the token itself is in
    neither the audit metadata nor the response."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    integration = await _enable_integration(client, admin, plan_tier="pro")
    node_id = await _node(maker)
    fake = FakeRegistry(authenticated=True)
    with use_registry(fake):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert created.status_code == 201, created.text
    assert fake.opens[0]["credential"] == _TOKEN
    assert _TOKEN not in created.text

    rows = await _rows(maker, audit.TUNNEL_CREATE)
    assert len(rows) == 1
    metadata = rows[0].audit_metadata
    assert metadata["fingerprint"] == integration["credential"]["fingerprint"]
    assert _TOKEN not in json.dumps(metadata)
    # The URL is deliberately absent: it is part of the access credential, and the audit
    # trail is readable by every `audit.view` holder.
    assert "url" not in metadata


async def test_a_silently_anonymous_tunnel_is_rejected_rather_than_handed_over(api: tuple) -> None:
    """PG-01 #10: the provider answers a bad credential by issuing an anonymous tunnel
    instead of refusing. Accepting it would hand over something nobody asked for, with none
    of the paid tier's properties, and call it success."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin, plan_tier="pro")
    node_id = await _node(maker)
    fake = FakeRegistry(authenticated=False)
    with use_registry(fake):
        resp = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "TUNNEL_PROVIDER_UNAUTHORIZED"
    # It was also torn down on the node, and no row was left behind.
    assert fake.closes
    async with maker() as session:
        count = (
            await session.execute(sa.select(sa.func.count()).select_from(NodeTunnel))
        ).scalar_one()
    assert count == 0


async def test_a_failed_open_leaves_no_row_behind(api: tuple) -> None:
    """A row for a tunnel that does not exist would be listed, counted against all three
    limits, and closable by nobody."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry(error_code="TUNNEL_PROVIDER_UNAVAILABLE")):
        resp = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "TUNNEL_PROVIDER_UNAVAILABLE"
    async with maker() as session:
        count = (
            await session.execute(sa.select(sa.func.count()).select_from(NodeTunnel))
        ).scalar_one()
    assert count == 0


async def test_the_first_tunnel_on_a_node_requires_the_third_party_acknowledgement(
    api: tuple,
) -> None:
    """D14, second place. The answer comes from the audit trail, so the second tunnel on the
    same node does not ask again — and a different node does."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    body = _create_body(node_id)
    del body["acknowledge_third_party"]
    with use_registry(FakeRegistry()):
        first = await client.post("/api/tunnels", json=body, headers=admin)
        assert first.status_code == 422
        assert first.json()["error"]["details"]["requires_acknowledgement"] == "third_party"

        acknowledged = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        assert acknowledged.status_code == 201
        await client.delete(f"/api/tunnels/{acknowledged.json()['id']}", headers=admin)

        again = await client.post("/api/tunnels", json=body, headers=admin)
        assert again.status_code == 201, "the acknowledgement is remembered per node"


async def test_an_unprotected_tunnel_requires_its_own_acknowledgement_and_is_audited(
    api: tuple,
) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        refused = await client.post(
            "/api/tunnels",
            json=_create_body(node_id, protection="public"),
            headers=admin,
        )
        assert refused.status_code == 422
        assert refused.json()["error"]["details"]["requires_acknowledgement"] == "public"

        created = await client.post(
            "/api/tunnels",
            json=_create_body(node_id, protection="public", acknowledge_public=True),
            headers=admin,
        )
    assert created.status_code == 201, created.text
    assert created.json()["basic_auth_password"] is None
    assert len(await _rows(maker, audit.TUNNEL_PUBLIC_ACKNOWLEDGED)) == 1


# --- The three layers, through the API ------------------------------------------------ #


async def test_a_node_that_vetoes_locally_cannot_be_overridden_by_the_platform(
    api: tuple,
) -> None:
    """The refusal names the local layer, because that is the only layer whose remedy is not
    on this platform: its owner has to change the node's own configuration file."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker, veto=True)
    with use_registry(FakeRegistry()):
        resp = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "TUNNEL_NODE_DISABLED"
    assert error["details"]["layer"] == "node_local"
    assert "config.yaml" in error["message"]


async def test_turning_a_node_off_in_its_platform_settings_names_that_layer(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        updated = await client.put(
            f"/api/nodes/{node_id}/tunnel-settings", json={"enabled": False}, headers=admin
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["blocked_by"] == "node_settings"

        resp = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["layer"] == "node_settings"
    assert len(await _rows(maker, audit.INTEGRATION_NODE_SETTINGS_UPDATED)) == 1


async def test_the_effective_port_range_is_the_intersection_of_all_three_layers(
    api: tuple,
) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin, allowed_ports=["3000-6000"])
    node_id = await _node(maker, local_ports=["5000-5500"])
    with use_registry(FakeRegistry()):
        await client.put(
            f"/api/nodes/{node_id}/tunnel-settings",
            json={"allowed_ports": ["4000-5200"]},
            headers=admin,
        )
        policy = await client.get(f"/api/nodes/{node_id}/tunnel-policy", headers=admin)
        assert policy.status_code == 200, policy.text
        assert policy.json()["allowed_ports"] == ["5000-5200"]

        outside = await client.post(
            "/api/tunnels", json=_create_body(node_id, port=5300), headers=admin
        )
        assert outside.status_code == 409
        assert outside.json()["error"]["code"] == "TUNNEL_PORT_NOT_ALLOWED"
        inside = await client.post(
            "/api/tunnels", json=_create_body(node_id, port=5100), headers=admin
        )
    assert inside.status_code == 201, inside.text


async def test_a_privileged_port_is_refused_before_it_reaches_the_node(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    fake = FakeRegistry()
    with use_registry(fake):
        resp = await client.post("/api/tunnels", json=_create_body(node_id, port=22), headers=admin)
    assert resp.status_code == 422
    assert fake.opens == []


async def test_a_node_missing_a_prerequisite_is_refused_immediately_with_the_reason(
    api: tuple,
) -> None:
    """The first error most people meet. It has to be answered from what the node already
    reported, not by opening a connection and waiting for the 20-second budget to run out."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker, prereq_ok=False)
    fake = FakeRegistry()
    with use_registry(fake):
        resp = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "TUNNEL_PROVIDER_NOT_CONFIGURED"
    assert "outbound access to the provider" in error["message"]
    assert "agentd doctor" in error["message"]
    assert fake.opens == [], "no frame is sent to a node that cannot serve it"


async def test_a_node_that_has_never_reported_is_treated_as_unsupported_not_ready(
    api: tuple,
) -> None:
    """An agentd older than P11 sends no report at all. "We do not know" must not read as
    "ready", and the remedy it points at is upgrading the daemon."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker, reported=False, prereq_ok=False)
    with use_registry(FakeRegistry()):
        policy = await client.get(f"/api/nodes/{node_id}/tunnel-policy", headers=admin)
        assert policy.json()["blocked_by"] == "node_local"
        assert policy.json()["reported_at"] is None
        resp = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TUNNEL_NODE_DISABLED"


# --- The three limits ----------------------------------------------------------------- #


async def test_the_fleet_budget_is_checked_globally_not_per_node(api: tuple) -> None:
    """ADR 0022 D17b. With a budget of 1 the second tunnel is refused even though it is on a
    different node — the budget is what one provider account may hold open at once."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin, concurrent_budget=1)
    first_node = await _node(maker)
    second_node = await _node(maker)
    with use_registry(FakeRegistry()):
        assert (
            await client.post("/api/tunnels", json=_create_body(first_node), headers=admin)
        ).status_code == 201
        resp = await client.post("/api/tunnels", json=_create_body(second_node), headers=admin)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TUNNEL_LIMIT_REACHED"
    assert "budget" in resp.json()["error"]["message"]


async def test_the_per_node_cap_names_the_node_rather_than_the_budget(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin, concurrent_budget=20)
    node_id = await _node(maker, local_max=1)
    with use_registry(FakeRegistry()):
        assert (
            await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        ).status_code == 201
        resp = await client.post(
            "/api/tunnels", json=_create_body(node_id, port=5174), headers=admin
        )
    assert resp.status_code == 409
    assert "node" in resp.json()["error"]["message"]


async def test_the_same_port_cannot_be_forwarded_twice_and_the_answer_names_the_existing_one(
    api: tuple,
) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        first = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        assert first.status_code == 201
        again = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    assert again.status_code == 409
    assert again.json()["error"]["details"]["tunnel_id"] == first.json()["id"]


# --- Closing, rotating, extending ----------------------------------------------------- #


async def test_closing_writes_the_row_and_tells_the_node(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    fake = FakeRegistry()
    with use_registry(fake):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        tunnel_id = created.json()["id"]
        closed = await client.delete(f"/api/tunnels/{tunnel_id}", headers=admin)
        assert closed.status_code == 204
        listed = await client.get("/api/tunnels", headers=admin)
        ended = await client.get("/api/tunnels?include_ended=true", headers=admin)
    assert listed.json() == []
    assert [t["state"] for t in ended.json()] == ["closed"]
    assert fake.closes == [tunnel_id]
    rows = await _rows(maker, audit.TUNNEL_CLOSE)
    assert len(rows) == 1
    assert rows[0].audit_metadata["reason"] == "user"
    assert "url" not in rows[0].audit_metadata


async def test_a_developer_cannot_close_someone_elses_tunnel_but_an_admin_can(
    api: tuple,
) -> None:
    """Ownership, not role: an unwanted exposure has to be closeable by an administrator
    after whoever opened it has gone home."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    other_dev = await _login(client, maker, role_name="Developer")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        tunnel_id = created.json()["id"]
        refused = await client.delete(f"/api/tunnels/{tunnel_id}", headers=other_dev)
        assert refused.status_code == 403
        # The Developer can see it, and the capability flags say what they may do with it.
        listed = await client.get("/api/tunnels", headers=other_dev)
        assert listed.json()[0]["capabilities"]["can_close"] is False
        assert (await client.delete(f"/api/tunnels/{tunnel_id}", headers=admin)).status_code == 204


async def test_a_viewer_holds_neither_tunnel_action(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    viewer = await _login(client, maker, role_name="Viewer")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    assert (await client.get("/api/tunnels", headers=viewer)).status_code == 403
    assert (
        await client.post("/api/tunnels", json=_create_body(node_id), headers=viewer)
    ).status_code == 403
    assert (
        await client.get(f"/api/nodes/{node_id}/tunnel-policy", headers=viewer)
    ).status_code == 403


async def test_rotating_the_password_reopens_the_tunnel_with_a_new_one(api: tuple) -> None:
    """The provider fixes its remote options at connection time, so "change the password" is
    "close and reopen". The response therefore carries a new URL as well, and the old tunnel
    is closed rather than left running with a password nobody holds."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    fake = FakeRegistry()
    with use_registry(fake):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        first = created.json()
        fake.url = "https://second-1-2-3-4.run.pinggy-free.link"
        rotated = await client.post(f"/api/tunnels/{first['id']}/rotate-password", headers=admin)
    assert rotated.status_code == 200, rotated.text
    body = rotated.json()
    assert body["basic_auth_password"] != first["basic_auth_password"]
    assert body["url"] == fake.url != first["url"]
    assert body["id"] != first["id"], "a rotation is a new tunnel, and the response shows it"
    async with maker() as session:
        old = await session.get(NodeTunnel, uuid.UUID(first["id"]))
    assert old is not None and old.closed_at is not None


async def test_extending_moves_our_deadline_and_not_the_providers(api: tuple) -> None:
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        before = created.json()
        extended = await client.post(f"/api/tunnels/{before['id']}/extend", headers=admin)
    assert extended.status_code == 200, extended.text
    assert datetime.fromisoformat(extended.json()["expires_at"]) > datetime.fromisoformat(
        before["expires_at"]
    )
    assert extended.json()["upstream_expires_at"] == before["upstream_expires_at"]
    # The same row, fully described: an earlier version of this path built the response
    # without the joined names, so extending a tunnel silently blanked its creator.
    assert extended.json()["created_by_username"] == before["created_by_username"]
    assert extended.json()["node_name"] == before["node_name"]


async def test_disabling_a_node_closes_its_tunnels(api: tuple) -> None:
    """A session may reasonably finish; a tunnel is an open door. "Nothing new starts" cannot
    leave the doors open — and a row left live would keep consuming the fleet budget."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    fake = FakeRegistry()
    with use_registry(fake):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        assert created.status_code == 201
        disabled = await client.post(
            f"/api/nodes/{node_id}/enabled", json={"enabled": False}, headers=admin
        )
        assert disabled.status_code == 200, disabled.text
        listed = await client.get("/api/tunnels", headers=admin)
    assert listed.json() == []
    rows = await _rows(maker, audit.TUNNEL_CLOSE)
    assert [row.audit_metadata["reason"] for row in rows] == ["node_disabled"]


# --- Unsolicited status ---------------------------------------------------------------- #


async def test_a_new_url_from_the_node_replaces_the_old_one_and_is_counted(api: tuple) -> None:
    """The free tier reassigns the URL on every reconnect (PG-01 #6), so this is the path that
    keeps the platform's copy true. `reconnecting` deliberately keeps the last known URL: a
    blank field would read as "gone" rather than "changing"."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    tunnel_id = created.json()["id"]

    from app.services.tunnels import TunnelService

    async with maker() as session:
        service = TunnelService(session)
        await service.apply_status(node_id, {"tunnel_id": tunnel_id, "state": "reconnecting"})
        await session.commit()
        row = await session.get(NodeTunnel, uuid.UUID(tunnel_id))
        assert row is not None and row.url == created.json()["url"]

        await service.apply_status(
            node_id,
            {
                "tunnel_id": tunnel_id,
                "state": "running",
                "url": "https://third-1-2-3-4.run.pinggy-free.link",
                "upstream_expires_at": (datetime.now(UTC) + timedelta(minutes=60)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            },
        )
        await session.commit()
        await session.refresh(row)
        assert row.url == "https://third-1-2-3-4.run.pinggy-free.link"
        assert row.url_change_count == 1
        assert row.url_updated_at is not None
        assert row.upstream_expires_at is not None


async def test_a_failure_report_records_the_code_without_closing_the_tunnel(api: tuple) -> None:
    """The row is what carries the reason; whether to retry or give up belongs to whoever
    created it. Closing it here would delete the explanation."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
        tunnel_id = created.json()["id"]

        from app.services.tunnels import TunnelService

        async with maker() as session:
            await TunnelService(session).apply_status(
                node_id,
                {
                    "tunnel_id": tunnel_id,
                    "state": "failed",
                    "error_code": "TUNNEL_PROVIDER_UNTRUSTED",
                },
            )
            await session.commit()
        listed = await client.get("/api/tunnels", headers=admin)
    row = listed.json()[0]
    assert row["state"] == "failed"
    assert row["state_error_code"] == "TUNNEL_PROVIDER_UNTRUSTED"


async def test_a_status_report_for_another_nodes_tunnel_is_ignored(api: tuple) -> None:
    """A node may only speak about its own tunnels: a compromised daemon must not be able to
    rewrite the URL of a tunnel on a machine it does not own."""
    client, maker = api
    admin = await _login(client, maker, role_name="Admin")
    await _enable_integration(client, admin)
    node_id = await _node(maker)
    other_node = await _node(maker)
    with use_registry(FakeRegistry()):
        created = await client.post("/api/tunnels", json=_create_body(node_id), headers=admin)
    tunnel_id = created.json()["id"]

    from app.services.tunnels import TunnelService

    async with maker() as session:
        await TunnelService(session).apply_status(
            other_node,
            {
                "tunnel_id": tunnel_id,
                "state": "running",
                "url": "https://attacker-1-2-3-4.run.pinggy-free.link",
            },
        )
        await session.commit()
        row = await session.get(NodeTunnel, uuid.UUID(tunnel_id))
    assert row is not None and row.url == created.json()["url"]
