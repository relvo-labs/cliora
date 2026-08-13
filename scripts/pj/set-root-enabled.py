#!/usr/bin/env python3
"""Test helper for the V2.0 browser acceptance path.

The product deliberately has no Central API for editing daemon-owned workspace
roots. The E2E stack still needs to exercise the moment a root that was legal at
bind time is withdrawn. This helper changes the throwaway E2E database directly;
it is never imported or shipped by Central.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def run(node_id: uuid.UUID, path: str, *, enabled: bool) -> None:
    url = os.environ["CLIORA_DATABASE_URL"]
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(
                sa.text(
                    "UPDATE node_workspace_roots SET is_enabled = :enabled "
                    "WHERE node_id = :node_id AND path = :path"
                ),
                {"enabled": enabled, "node_id": node_id, "path": path},
            )
            if result.rowcount != 1:
                raise SystemExit(
                    f"expected one workspace root, changed {result.rowcount}"
                )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("node_id", type=uuid.UUID)
    parser.add_argument("path")
    parser.add_argument("state", choices=("on", "off"))
    args = parser.parse_args()
    asyncio.run(run(args.node_id, args.path, enabled=args.state == "on"))


if __name__ == "__main__":
    main()
