"""Seed a Developer and a Viewer alongside the stack's Admin (plan/16 PJ-00 / PJ-07).

`app.bootstrap` only creates the initial Admin, but three of plan/16's checks need the
other two roles:

* PJ-00 B3 — the nav baseline is per-role (Admin sees six entries, Developer and Viewer
  see three), so one screenshot cannot be the baseline.
* Exit condition 9 — a Viewer must see /projects and the timeline, must see no actor
  name, and must get 403 from POST /api/projects.
* PJ-07's flag-off regression — the RBAC matrix is three roles wide.

Idempotent: re-running updates the password rather than failing, so it is safe inside
run-stack.sh, which may be started many times against the same database.

    CLIORA_DATABASE_URL=... python scripts/pj/seed_users.py [--password pw]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.db.models import Role, User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402

SEEDED = [("e2e-developer", "Developer", "E2E Developer"), ("e2e-viewer", "Viewer", "E2E Viewer")]


async def _seed(url: str, password: str) -> None:
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            for username, role_name, display in SEEDED:
                role = (
                    await session.execute(select(Role).where(Role.name == role_name))
                ).scalar_one_or_none()
                if role is None:
                    raise SystemExit(
                        f"role {role_name!r} is missing — run `alembic upgrade head` first"
                    )
                user = (
                    await session.execute(select(User).where(User.username == username))
                ).scalar_one_or_none()
                if user is None:
                    session.add(
                        User(
                            id=uuid.uuid4(),
                            username=username,
                            display_name=display,
                            password_hash=hash_password(password),
                            role_id=role.id,
                            is_active=True,
                        )
                    )
                    print(f"created {username} ({role_name})")
                else:
                    # Update rather than skip: the password is the thing a caller most
                    # often needs to be sure about, and a stale one fails confusingly
                    # much later, in a browser.
                    user.password_hash = hash_password(password)
                    user.role_id = role.id
                    user.is_active = True
                    print(f"updated {username} ({role_name})")
            await session.commit()
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("CLIORA_DATABASE_URL", ""))
    parser.add_argument("--password", default=os.environ.get("E2E_SEED_PASSWORD", "e2e-seed-pw"))
    args = parser.parse_args()
    if not args.url:
        raise SystemExit("set CLIORA_DATABASE_URL or pass --url")
    asyncio.run(_seed(args.url, args.password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
