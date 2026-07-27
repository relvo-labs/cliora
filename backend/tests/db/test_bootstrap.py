from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import create_admin
from app.security.passwords import verify_password

pytestmark = pytest.mark.asyncio


async def test_create_admin_then_idempotent(session: AsyncSession) -> None:
    user, status = await create_admin(session, "root", "s3cret-pw")
    assert status == "created"
    assert user.role.name == "Admin"
    assert verify_password(user.password_hash, "s3cret-pw")

    # A second call with the same username is a no-op by default.
    again, status2 = await create_admin(session, "root", "different-pw")
    assert status2 == "unchanged"
    assert again.id == user.id
    assert verify_password(again.password_hash, "s3cret-pw")


async def test_update_password_rotates_and_revokes(session: AsyncSession) -> None:
    created, _ = await create_admin(session, "root", "old-pw")
    version_before = created.token_version

    updated, status = await create_admin(session, "root", "new-pw", update_password=True)
    assert status == "updated"
    assert verify_password(updated.password_hash, "new-pw")
    # Rotating the password bumps token_version to revoke old refresh tokens.
    assert updated.token_version == version_before + 1
