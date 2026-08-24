#!/usr/bin/env python
"""Does `ix_tasks_project_updated` actually change the board's plan? (PX-22, D104)

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/px/measure-board-index.py

The V1 board is `ORDER BY updated_at DESC` and has never had an index behind it. `0043`
adds one, and this is the measurement that says whether it was worth adding — **by
dropping it and putting it back**, which is the only comparison that means anything. The
alternative (turning `enable_indexscan` off) measures the planner's willingness to use
*any* index, which is a different question.

Two sizes, because the answer differs and the difference is the point: at a couple of
hundred cards a sequential scan of a small table beats an index, and the index earns its
keep further out. A measurement at one size would license the wrong conclusion either
way.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

# **Two queries, and the second is the reason the index exists.**
#
# The V1 board fetches *every* card in the project, so a full scan plus a sort is
# optimal whatever indexes exist — an index cannot beat reading rows you are going to
# read anyway. The measurement below shows exactly that, at both sizes, which means
# D104's stated justification ("the board is ORDER BY updated_at DESC") is true and
# insufficient.
#
# What the index is actually for is the query `beta.1` adds: a **paged** read that stops
# early. `PX-25`'s cursor and the Done column's "last 7 days / last N" are both of that
# shape, and there the index turns a sort of the whole project into a bounded walk.
_ORDER_QUERY = "SELECT id FROM tasks WHERE project_id = :project_id ORDER BY updated_at DESC, id DESC"
_PAGED_QUERY = _ORDER_QUERY + " LIMIT 50"
_INDEX_SQL = (
    "CREATE INDEX ix_tasks_project_updated ON tasks (project_id, updated_at DESC)"
)


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


async def _plan(connection, project_id: str, query: str) -> dict[str, object]:
    await connection.execute(sa.text("ANALYZE tasks"))
    plan = (
        await connection.execute(
            sa.text(f"EXPLAIN (ANALYZE, FORMAT JSON) {query}"),
            {"project_id": project_id},
        )
    ).scalar_one()
    root = plan[0]["Plan"]
    return {
        "node": root["Node Type"],
        "total_cost": root["Total Cost"],
        "actual_ms": root["Actual Total Time"],
        "rows": root["Actual Rows"],
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--large", type=int, default=2000, help="cards in the synthetic project"
    )
    parser.add_argument(
        "--out", default="artifacts/px/local/baseline/board-order-explain.json"
    )
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    results: dict[str, dict[str, object]] = {}
    async with engine.begin() as connection:
        seeded = (
            await connection.execute(
                sa.text(
                    "SELECT project_id, count(*) FROM tasks GROUP BY 1 "
                    "ORDER BY count(*) DESC LIMIT 1"
                )
            )
        ).first()
        if seeded is None:
            print(
                "no tasks in this database — seed the fixed dataset first",
                file=sys.stderr,
            )
            return 2
        small_project, small_count = str(seeded[0]), int(seeded[1])

        # A throwaway project with `--large` cards, in the same transaction as the
        # rollback below, so this never leaves rows behind.
        owner = (
            await connection.execute(sa.text("SELECT id FROM users LIMIT 1"))
        ).scalar_one()
        large_project = uuid.uuid4()
        await connection.execute(
            sa.text(
                "INSERT INTO projects (id, name, slug, status, owner_user_id, next_card_seq) "
                "VALUES (:id, :name, :slug, 'active', :owner, 1)"
            ),
            {
                "id": str(large_project),
                "name": "px-index-measurement",
                "slug": f"px-index-{large_project.hex[:8]}",
                "owner": owner,
            },
        )
        await connection.execute(
            sa.text(
                "INSERT INTO tasks (id, project_id, card_ref, title, stage, source, delivery, "
                "rank, updated_at, created_at) "
                "SELECT gen_random_uuid(), :project, 'IX-' || n, 'index measurement ' || n, "
                "'backlog', 'none', 'none', 'a', now() - (n || ' minutes')::interval, now() "
                "FROM generate_series(1, :count) AS n"
            ),
            {"project": str(large_project), "count": args.large},
        )

        for label, project_id, count in (
            ("small", small_project, small_count),
            ("large", str(large_project), args.large),
        ):
            entry: dict[str, object] = {"cards": count}
            for shape, query in (
                ("whole_board", _ORDER_QUERY),
                ("paged_50", _PAGED_QUERY),
            ):
                await connection.execute(
                    sa.text("DROP INDEX IF EXISTS ix_tasks_project_updated")
                )
                before = await _plan(connection, project_id, query)
                await connection.execute(sa.text(_INDEX_SQL))
                after = await _plan(connection, project_id, query)
                entry[shape] = {"before": before, "after": after}
            results[label] = entry

        # Everything above happened inside one transaction; rolling it back removes the
        # synthetic project and restores whatever index state the database had.
        raise _Rollback(results)

    return 0  # pragma: no cover - unreachable, the rollback always fires


class _Rollback(Exception):
    """Carries the results out of the transaction that is about to be undone."""

    def __init__(self, results: dict[str, dict[str, object]]) -> None:
        super().__init__("rollback")
        self.results = results


async def run() -> int:
    try:
        return await main()
    except _Rollback as rolled_back:
        payload = {
            "commit": commit(),
            "database": (os.environ.get("CLIORA_DATABASE_URL") or "").rsplit("/", 1)[
                -1
            ],
            "queries": {"whole_board": _ORDER_QUERY, "paged_50": _PAGED_QUERY},
            "results": rolled_back.results,
        }
        # Recreate the index the transaction rolled away, if the schema expects it.
        engine = create_async_engine(os.environ["CLIORA_DATABASE_URL"])
        async with engine.begin() as connection:
            head = (
                await connection.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one_or_none()
            if head == "0043_work_views_and_rank":
                await connection.execute(
                    sa.text(
                        "CREATE INDEX IF NOT EXISTS ix_tasks_project_updated "
                        "ON tasks (project_id, updated_at DESC)"
                    )
                )
        await engine.dispose()
        out = REPO / "artifacts/px/local/baseline/board-order-explain.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload["results"], ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
