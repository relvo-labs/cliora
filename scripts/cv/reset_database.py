"""Drop and recreate a database with no client binaries installed.

The third fallback in `stack-evidence.sh`: a CI runner has PostgreSQL as a *service*
container and no `psql` on the runner itself, and a script that refused there would only
ever run on somebody's laptop.

    uv run --project backend python scripts/cv/reset_database.py <async-url>
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main(url: str) -> int:
    name = url.rsplit("/", 1)[-1]
    admin = url.rsplit("/", 1)[0] + "/postgres"
    # AUTOCOMMIT because `DROP DATABASE` cannot run inside a transaction block.
    engine = create_async_engine(admin, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"
            ),
            {"n": name},
        )
        # Interpolated because an identifier cannot be a bind parameter. The value comes
        # from this repo's own scripts, never from a request.
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    print(f"recreated {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1])))
