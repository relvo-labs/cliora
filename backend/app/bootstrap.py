"""First-admin bootstrap (P1-04).

Roles are seeded by migration 0002, but a fresh deployment has no user, so no one
can sign in to create the first enrollment token. This creates the initial Admin
account. Run once after ``alembic upgrade head`` (from the backend directory):

    CLIORA_ADMIN_PASSWORD='…' python -m app.bootstrap create-admin --username admin

The password comes from ``--password`` or ``CLIORA_ADMIN_PASSWORD`` so it need not
appear in shell history. It is idempotent: an existing username is left unchanged
unless ``--update-password`` is given (which also bumps ``token_version`` to
revoke that user's outstanding refresh tokens).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_database, reset_database
from app.db.models import Role, User
from app.security.passwords import hash_password


class BootstrapError(Exception):
    """Raised when the environment is not ready to create an admin."""


async def create_admin(
    session: AsyncSession,
    username: str,
    password: str,
    display_name: str = "Administrator",
    *,
    update_password: bool = False,
) -> tuple[User, str]:
    """Create (or optionally update) the Admin user. Returns (user, status) where
    status is 'created', 'updated', or 'unchanged'."""
    role = (await session.execute(select(Role).where(Role.name == "Admin"))).scalar_one_or_none()
    if role is None:
        raise BootstrapError("Admin role not found; run 'alembic upgrade head' first")

    existing = (
        await session.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if existing is not None:
        if not update_password:
            return existing, "unchanged"
        existing.password_hash = hash_password(password)
        existing.token_version += 1
        await session.flush()
        return existing, "updated"

    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )
    session.add(user)
    await session.flush()
    return user, "created"


async def _run(args: argparse.Namespace) -> int:
    username: str = args.username
    display_name: str = args.display_name
    update_password: bool = args.update_password
    password: str = args.password or os.environ.get("CLIORA_ADMIN_PASSWORD", "")
    if not password:
        print("error: provide --password or set CLIORA_ADMIN_PASSWORD", file=sys.stderr)
        return 2

    database = get_database()
    try:
        async with database.session() as session:
            _, status = await create_admin(
                session, username, password, display_name, update_password=update_password
            )
            await session.commit()
    finally:
        await reset_database()
    print(f"admin '{username}': {status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="create the initial Admin user")
    create.add_argument("--username", required=True)
    create.add_argument("--password", default=None)
    create.add_argument("--display-name", default="Administrator")
    create.add_argument("--update-password", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
