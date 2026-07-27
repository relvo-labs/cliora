"""Credential revoke/rotate lifecycle and live-socket severing (P1-09/14)."""

from __future__ import annotations

import base64
import uuid

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.api.errors import ApiError
from app.db.models import AuditLog, NodeCredential, Role, User
from app.security.node_keys import signing_message
from app.security.passwords import hash_password
from app.services.enrollment import EnrollmentService
from app.services.nodes import (
    NodeManagementService,
    NodeRegistrationService,
    RegisterNodeInput,
    RuntimeInput,
)
from app.services.registry import NodeConnectionRegistry

CHALLENGE = "01K0ABCDEFGHJKMNPQRSTVWXYZ"
NONCE = base64.b64encode(b"n" * 32).decode()


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    return private, public


def _sign(private: Ed25519PrivateKey, node_id: uuid.UUID) -> str:
    return base64.b64encode(private.sign(signing_message(node_id, CHALLENGE, NONCE))).decode()


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed = code


async def _seed(session) -> tuple[uuid.UUID, Ed25519PrivateKey, str]:
    private, public = _keypair()
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    admin = User(
        username=f"admin-{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("pw"),
        display_name="a",
        role_id=role.id,
    )
    session.add(admin)
    await session.flush()
    created = await EnrollmentService(session).create(created_by=admin.id)
    registered = await NodeRegistrationService(session).register(
        created.plaintext,
        RegisterNodeInput(
            name="vm",
            hostname="vm",
            os="linux",
            os_version="Ubuntu 24.04",
            architecture="amd64",
            daemon_version="1.0.0",
            run_user="neil",
            public_key=public,
            runtimes=[RuntimeInput(runtime="claude", available=True)],
        ),
    )
    await session.flush()
    return registered.node.id, private, admin.id


async def _audit_actions(session, node_id: uuid.UUID) -> list[str]:
    rows = await session.execute(sa.select(AuditLog.action).where(AuditLog.node_id == node_id))
    return list(rows.scalars())


async def test_revoke_credential_severs_live_connection(session) -> None:
    node_id, _, admin_id = await _seed(session)
    registry = NodeConnectionRegistry(pending_max=8)
    ws = FakeWebSocket()
    await registry.register(node_id, ws)

    service = NodeManagementService(session, registry=registry)
    await service.revoke_credential(node_id, actor_id=admin_id)

    # Live socket dropped immediately, credential revoked, audit written.
    assert ws.closed == 1008
    assert not registry.is_connected(node_id)
    cred = (
        await session.execute(sa.select(NodeCredential).where(NodeCredential.node_id == node_id))
    ).scalar_one()
    assert cred.revoked_at is not None
    assert "credential.revoke" in await _audit_actions(session, node_id)


async def test_rotate_credential_new_version_and_key(session) -> None:
    node_id, old_private, admin_id = await _seed(session)
    registry = NodeConnectionRegistry(pending_max=8)
    ws = FakeWebSocket()
    await registry.register(node_id, ws)

    new_private, new_public = _keypair()
    service = NodeManagementService(session, registry=registry)
    credential = await service.rotate_credential(node_id, public_key=new_public, actor_id=admin_id)
    await session.flush()

    # New version issued, old one revoked, live socket dropped.
    assert credential.version == 2
    assert ws.closed == 1008
    active = (
        (
            await session.execute(
                sa.select(NodeCredential).where(
                    NodeCredential.node_id == node_id, NodeCredential.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(active) == 1 and active[0].version == 2

    # The rotated key authenticates; the old key no longer does.
    reg = NodeRegistrationService(session)
    assert await reg.authenticate_signature(node_id, CHALLENGE, NONCE, _sign(new_private, node_id))
    with pytest.raises(ApiError) as exc:
        await reg.authenticate_signature(node_id, CHALLENGE, NONCE, _sign(old_private, node_id))
    assert exc.value.code == "NODE_AUTH_FAILED"


async def test_remove_severs_connection_and_revokes(session) -> None:
    node_id, _, admin_id = await _seed(session)
    registry = NodeConnectionRegistry(pending_max=8)
    ws = FakeWebSocket()
    await registry.register(node_id, ws)

    service = NodeManagementService(session, registry=registry)
    await service.remove(node_id, actor_id=admin_id)

    assert ws.closed == 1008
    assert not registry.is_connected(node_id)
    # P4-04 changed this deliberately: removal used to emit a second
    # `credential.revoke` row, which made a filter on revocations return events
    # that were never a standalone administrative act. One operation, one row
    # (ADR 0016) — the revocation is now stated in the removal's metadata.
    actions = await _audit_actions(session, node_id)
    assert "node.remove" in actions
    assert "credential.revoke" not in actions
    rows = (
        await session.execute(
            sa.select(AuditLog).where(AuditLog.node_id == node_id, AuditLog.action == "node.remove")
        )
    ).scalars()
    assert [row.audit_metadata["credentials_revoked"] for row in rows] == [True]


async def test_rotate_rejects_bad_public_key(session) -> None:
    node_id, _, admin_id = await _seed(session)
    service = NodeManagementService(session, registry=NodeConnectionRegistry(pending_max=8))
    with pytest.raises(ApiError) as exc:
        await service.rotate_credential(node_id, public_key="not-a-key", actor_id=admin_id)
    assert exc.value.code == "INVALID_ARGUMENT"
