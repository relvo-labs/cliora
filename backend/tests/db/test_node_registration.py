"""Service-level Ed25519 node auth and enrollment concurrency."""

from __future__ import annotations

import asyncio
import base64
import uuid

import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.errors import ApiError
from app.db.models import NodeCredential, Role, User
from app.security.node_keys import signing_message
from app.security.passwords import hash_password
from app.services.enrollment import EnrollmentService
from app.services.nodes import NodeRegistrationService, RegisterNodeInput, RuntimeInput


def _keys() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    return private, public


def _register_input(public_key: str, name: str = "vm") -> RegisterNodeInput:
    return RegisterNodeInput(
        name=name,
        hostname=name,
        os="linux",
        os_version="Ubuntu 24.04",
        architecture="amd64",
        daemon_version="1.0.0",
        run_user="neil",
        public_key=public_key,
        runtimes=[RuntimeInput(runtime="claude", available=True)],
    )


async def _seed_admin(session: AsyncSession) -> uuid.UUID:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    user = User(
        username="admin", password_hash=hash_password("pw"), display_name="a", role_id=role.id
    )
    session.add(user)
    await session.flush()
    return user.id


async def _registered(session: AsyncSession):
    private, public = _keys()
    admin_id = await _seed_admin(session)
    created = await EnrollmentService(session).create(created_by=admin_id)
    registered = await NodeRegistrationService(session).register(
        created.plaintext, _register_input(public)
    )
    await session.flush()
    return private, registered


async def test_node_authenticates_with_valid_signature(session: AsyncSession) -> None:
    private, registered = await _registered(session)
    challenge_id, nonce = "01K0ABCDEFGHJKMNPQRSTVWXYZ", "nonce"
    signature = base64.b64encode(
        private.sign(signing_message(registered.node.id, challenge_id, nonce))
    ).decode()
    node = await NodeRegistrationService(session).authenticate_signature(
        registered.node.id, challenge_id, nonce, signature
    )
    assert node.id == registered.node.id


async def test_node_auth_rejects_wrong_signature(session: AsyncSession) -> None:
    _, registered = await _registered(session)
    try:
        await NodeRegistrationService(session).authenticate_signature(
            registered.node.id,
            "01K0ABCDEFGHJKMNPQRSTVWXYZ",
            "nonce",
            base64.b64encode(b"x" * 64).decode(),
        )
        raise AssertionError("expected NODE_AUTH_FAILED")
    except ApiError as exc:
        assert exc.code == "NODE_AUTH_FAILED"


async def test_node_auth_rejects_revoked_credential(session: AsyncSession) -> None:
    private, registered = await _registered(session)
    credential = (
        await session.execute(
            sa.select(NodeCredential).where(NodeCredential.node_id == registered.node.id)
        )
    ).scalar_one()
    from app.clock import now_utc

    credential.revoked_at = now_utc()
    await session.flush()
    challenge_id, nonce = "01K0ABCDEFGHJKMNPQRSTVWXYZ", "nonce"
    signature = base64.b64encode(
        private.sign(signing_message(registered.node.id, challenge_id, nonce))
    ).decode()
    try:
        await NodeRegistrationService(session).authenticate_signature(
            registered.node.id, challenge_id, nonce, signature
        )
        raise AssertionError("expected NODE_AUTH_FAILED")
    except ApiError as exc:
        assert exc.code == "NODE_AUTH_FAILED"


async def test_concurrent_consume_respects_max_uses(db_url: str) -> None:
    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            admin_id = await _seed_admin(session)
            created = await EnrollmentService(session).create(created_by=admin_id, max_uses=1)
            plaintext = created.plaintext
            await session.commit()

        async def attempt() -> bool:
            async with maker() as session:
                try:
                    await EnrollmentService(session).consume(plaintext)
                    await session.commit()
                    return True
                except ApiError:
                    await session.rollback()
                    return False

        # Row-level FOR UPDATE serializes the two attempts; exactly one wins.
        results = await asyncio.gather(attempt(), attempt())
        assert sorted(results) == [False, True]
    finally:
        async with maker() as session:
            await session.execute(sa.text("DELETE FROM node_credentials"))
            await session.execute(sa.text("DELETE FROM nodes"))
            await session.execute(sa.text("DELETE FROM enrollment_tokens"))
            await session.execute(sa.text("DELETE FROM users"))
            await session.commit()
        await engine.dispose()
