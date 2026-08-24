#!/usr/bin/env python
"""Which `blocked` cards the migration could not explain (PX-22, plan/26/02 §5.3).

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/px/ambiguous-report.py

`0043` turns `stage='blocked'` into `is_blocked = true` plus a derived reason. When no
rule fires the reason is `unknown`, and **that is the honest answer rather than a
failure**: two of the seven derivation steps the upstream plan listed need the node
registry, and `alembic upgrade` runs in a process that does not have one.

This lists those cards with enough context for a person to classify them by hand —
including the last five activity kinds, because "what happened to this card recently" is
what actually answers the question.

**A card is not held up by being on this list.** The read model renders `unknown` as
"blocked, reason unknown" rather than pretending to know, so `beta.1` ships with them.
What the list gates is `beta.2`'s `HD-06`, the migration that removes the legacy
`blocked` stage — that one cannot be written until somebody has read this.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

_QUERY = """
SELECT t.card_ref,
       t.title,
       p.name  AS project_name,
       t.stage,
       t.blocking_reason,
       t.updated_at,
       COALESCE(
         (SELECT string_agg(a.kind, ',' ORDER BY a.at DESC)
          FROM (SELECT e.kind AS kind, e.occurred_at AS at FROM activity_events e
                WHERE e.task_id = t.id ORDER BY e.occurred_at DESC LIMIT 5) a),
         ''
       ) AS recent_activity
FROM tasks t
JOIN projects p ON p.id = t.project_id
WHERE t.is_blocked AND (t.blocking_reason IS NULL OR t.blocking_reason = 'unknown')
ORDER BY p.name, t.card_ref
"""


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/px/local/blocked-ambiguous")
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        rows = (await session.execute(sa.text(_QUERY))).mappings().all()
        derived = dict(
            (
                await session.execute(
                    sa.text(
                        "SELECT COALESCE(blocking_reason, 'null'), count(*) FROM tasks "
                        "WHERE is_blocked GROUP BY 1 ORDER BY 1"
                    )
                )
            ).all()
        )
    await engine.dispose()

    records = [
        {
            "card_ref": row["card_ref"],
            "title": row["title"],
            "project_name": row["project_name"],
            "stage": row["stage"],
            "derived_reason": row["blocking_reason"] or "null",
            "updated_at": row["updated_at"].isoformat(),
            "recent_activity": row["recent_activity"],
        }
        for row in rows
    ]

    base = REPO / args.out
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(
        json.dumps(
            {
                "commit": commit(),
                "database": url.rsplit("/", 1)[-1],
                # The whole distribution, not only the ambiguous slice: "20 unknown" is
                # alarming on its own and unremarkable beside "20 blocked cards in total".
                "blocked_by_reason": {
                    key: int(value) for key, value in derived.items()
                },
                "ambiguous": len(records),
                "cards": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    with base.with_suffix(".csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "card_ref",
                "title",
                "project_name",
                "stage",
                "derived_reason",
                "updated_at",
                "recent_activity",
            ],
        )
        writer.writeheader()
        writer.writerows(records)

    print(
        json.dumps(
            {"blocked_by_reason": derived, "ambiguous": len(records)}, default=int
        )
    )
    print(f"report written to {args.out}.{{json,csv}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
