"""Database-level guarantees for port forwarding (P11, ADR 0022).

These are the constraints that have to hold even when the application layer is wrong. Each
one exists because the application already checks the same thing, and "already checked
somewhere" is how a wrong row eventually gets written: a future endpoint, a fixture, a
migration, or a hand-run UPDATE only meets whatever the schema enforces.

The port floor is the sharpest of them. Everything above it in the stack refuses ports below
1024, and if all of that were bypassed the result would be `sshd` or a database published to
the internet — so it is also written down here, where nothing can talk it out of it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Node, User


async def _node_and_user(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A node and a user to hang tunnels off, created through the models.

    Through the ORM rather than raw SQL on purpose: the point of this module is the
    constraints on the *new* tables, and hand-written setup INSERTs would break every time an
    unrelated NOT NULL column is added elsewhere. The violating inserts below stay raw,
    because the whole question there is what the database refuses.
    """
    role_id = (
        await session.execute(text("SELECT id FROM roles WHERE name = 'Admin'"))
    ).scalar_one()
    node = Node(name="dev-1", hostname="dev-1", status="online", node_metadata={})
    user = User(
        username=f"tunnel-{uuid.uuid4().hex[:8]}",
        display_name="Tunnel Test",
        password_hash="x",
        role_id=role_id,
    )
    session.add_all([node, user])
    await session.flush()
    return node.id, user.id


async def _insert_tunnel(
    session: AsyncSession,
    node_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    port: int = 5173,
    protection: str = "public",
    closed: bool = False,
) -> uuid.UUID:
    tunnel_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO node_tunnels "
            "(id, node_id, port, provider, protection, created_by, created_at, expires_at, "
            " closed_at, url_change_count, rewrite_host) "
            "VALUES (:id, :node_id, :port, 'pinggy', :protection, :created_by, now(), "
            "        :expires_at, :closed_at, 0, false)"
        ),
        {
            "id": tunnel_id,
            "node_id": node_id,
            "port": port,
            "protection": protection,
            "created_by": user_id,
            "expires_at": datetime.now(UTC) + timedelta(hours=4),
            "closed_at": datetime.now(UTC) if closed else None,
        },
    )
    return tunnel_id


@pytest.mark.parametrize("port", [22, 80, 443, 1023, 0, 70000])
async def test_a_port_below_the_floor_cannot_be_stored_at_all(
    session: AsyncSession, port: int
) -> None:
    node_id, user_id = await _node_and_user(session)
    with pytest.raises((IntegrityError, DBAPIError)):
        await _insert_tunnel(session, node_id, user_id, port=port)


async def test_an_ordinary_high_port_is_accepted(session: AsyncSession) -> None:
    node_id, user_id = await _node_and_user(session)
    await _insert_tunnel(session, node_id, user_id, port=5173)


async def test_an_unknown_protection_mode_is_refused(session: AsyncSession) -> None:
    """`public` has to be a named choice, so "no protection" cannot arrive as a typo or an
    empty string that later reads as "some protection"."""
    node_id, user_id = await _node_and_user(session)
    with pytest.raises((IntegrityError, DBAPIError)):
        await _insert_tunnel(session, node_id, user_id, protection="none")


async def test_two_live_tunnels_cannot_share_a_port(session: AsyncSession) -> None:
    """Two URLs for one service is a state a user cannot reason about: closing one leaves the
    other working, with nothing to say which."""
    node_id, user_id = await _node_and_user(session)
    await _insert_tunnel(session, node_id, user_id, port=5173)
    with pytest.raises((IntegrityError, DBAPIError)):
        await _insert_tunnel(session, node_id, user_id, port=5173)


async def test_a_closed_tunnel_frees_its_port(session: AsyncSession) -> None:
    """The uniqueness is filtered on live rows precisely so that closing a tunnel and opening
    it again — the ordinary thing to do — is not blocked by history."""
    node_id, user_id = await _node_and_user(session)
    await _insert_tunnel(session, node_id, user_id, port=5173, closed=True)
    await _insert_tunnel(session, node_id, user_id, port=5173)


async def test_the_same_port_on_two_nodes_is_fine(session: AsyncSession) -> None:
    first_node, user_id = await _node_and_user(session)
    second_node, _ = await _node_and_user(session)
    await _insert_tunnel(session, first_node, user_id, port=5173)
    await _insert_tunnel(session, second_node, user_id, port=5173)


async def test_the_integration_row_is_a_singleton(session: AsyncSession) -> None:
    """Code that reads "the first row" would silently pick one of two, and the wrong settings
    row is a bug nobody finds by reading."""
    await session.execute(
        text(
            "INSERT INTO tunnel_integration (id, singleton, enabled, provider, plan_tier, "
            " concurrent_budget, default_protection, default_ttl_seconds, updated_at) "
            "VALUES (:id, true, false, 'pinggy', 'free', 8, 'basic', 14400, now())"
        ),
        {"id": uuid.uuid4()},
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(
            text(
                "INSERT INTO tunnel_integration (id, singleton, enabled, provider, plan_tier, "
                " concurrent_budget, default_protection, default_ttl_seconds, updated_at) "
                "VALUES (:id, true, true, 'pinggy', 'pro', 8, 'basic', 14400, now())"
            ),
            {"id": uuid.uuid4()},
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("provider", "'ngrok'"),
        ("plan_tier", "'enterprise'"),
        ("default_protection", "'none'"),
        ("concurrent_budget", "0"),
        ("concurrent_budget", "101"),
        ("default_ttl_seconds", "30"),
    ],
)
async def test_the_integration_row_refuses_values_outside_its_vocabulary(
    session: AsyncSession, column: str, value: str
) -> None:
    """Including the budget bounds: a budget of zero would disable the feature through a
    number rather than through the switch that says so, and there is no plan with 101."""
    columns = {
        "id": ":id",
        "singleton": "true",
        "enabled": "false",
        "provider": "'pinggy'",
        "plan_tier": "'free'",
        "concurrent_budget": "8",
        "default_protection": "'basic'",
        "default_ttl_seconds": "14400",
        "updated_at": "now()",
    }
    columns[column] = value
    statement = (
        f"INSERT INTO tunnel_integration ({', '.join(columns)}) "
        f"VALUES ({', '.join(columns.values())})"
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.execute(text(statement), {"id": uuid.uuid4()})


async def test_the_integration_row_stores_no_plaintext_credential(session: AsyncSession) -> None:
    """The absence is the control: with no column able to hold a plaintext credential, no
    future code path can decide to write one 'for now'."""
    columns = (
        await session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'tunnel_integration'"
            )
        )
    ).scalars()
    names = set(columns)
    assert "token_ciphertext" in names
    assert "token_nonce" in names
    assert "token_fingerprint" in names
    for forbidden in ("token", "token_plaintext", "credential", "secret", "password"):
        assert forbidden not in names, f"tunnel_integration must not have a {forbidden} column"


async def test_per_node_settings_default_to_taking_part(session: AsyncSession) -> None:
    """The platform-level switch is the gate; a per-node row exists to turn one machine off,
    not to turn each one on (ADR 0022 D3)."""
    node_id, _ = await _node_and_user(session)
    await session.execute(
        text("INSERT INTO node_tunnel_settings (node_id, updated_at) VALUES (:id, now())"),
        {"id": node_id},
    )
    enabled = (
        await session.execute(
            text("SELECT enabled FROM node_tunnel_settings WHERE node_id = :id"),
            {"id": node_id},
        )
    ).scalar_one()
    assert enabled is True


async def test_removing_a_node_removes_its_tunnels_and_settings(session: AsyncSession) -> None:
    """Hard-deleting a node is a maintenance path (the product soft-deletes), and it must not
    leave rows pointing at a node that no longer exists."""
    node_id, user_id = await _node_and_user(session)
    await _insert_tunnel(session, node_id, user_id)
    await session.execute(
        text("INSERT INTO node_tunnel_settings (node_id, updated_at) VALUES (:id, now())"),
        {"id": node_id},
    )
    await session.execute(text("DELETE FROM nodes WHERE id = :id"), {"id": node_id})
    remaining = (
        await session.execute(
            text("SELECT count(*) FROM node_tunnels WHERE node_id = :id"), {"id": node_id}
        )
    ).scalar_one()
    settings_remaining = (
        await session.execute(
            text("SELECT count(*) FROM node_tunnel_settings WHERE node_id = :id"),
            {"id": node_id},
        )
    ).scalar_one()
    assert remaining == 0
    assert settings_remaining == 0


async def test_nodes_report_tunnel_prerequisites_pessimistically(session: AsyncSession) -> None:
    """A node that has reported nothing is not ready, and `tunnel_reported_at IS NULL` is how
    the UI tells "not ready" from "we have not heard from it"."""
    node_id, _ = await _node_and_user(session)
    row = (
        await session.execute(
            text(
                "SELECT tunnel_veto, tunnel_prereq_ok, tunnel_reported_at FROM nodes WHERE id = :id"
            ),
            {"id": node_id},
        )
    ).one()
    assert row.tunnel_veto is False
    assert row.tunnel_prereq_ok is False
    assert row.tunnel_reported_at is None
