#!/usr/bin/env python
"""What phase A, phase B and `derive_attention` actually cost (PX-24, plan/26/03 §5).

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/px/measure-attention.py

Six numbers, on the fixed dataset (`scripts/cv/seed-dataset.py`, seed 20260819):

| measured                                   | target   | why this one |
|--------------------------------------------|----------|--------------|
| one page of 200 cards, P95                  | < 1 s    | the upstream budget |
| `derive_attention` × 200, pure              | < 10 ms  | if it is slower, it is looking something up |
| phase B at the queue length the seed has    | baseline | |
| phase B at 60 queued                        | record   | **D92's claim is that this tracks the queue** |
| `EXPLAIN` of the board's `ORDER BY updated_at DESC` | record | D104: the index does not exist until `0043` |

The fourth row is the one worth reading. D92 accepted a per-process, unsortable answer
for two attention levels **on the grounds that the cost is bound to the dispatch queue
rather than to the board**. If phase B at 60 queued is ten times phase B at 6, the claim
holds and the reasoning stands; if it is ten times *the whole page*, it does not, and the
right response is to bound the queue rather than to keep the sentence.

Written to `artifacts/px/local/w0/attention-measurement.json` with the commit, the database and
the row counts beside it, because a threshold without the shape it was measured on is a
number somebody will later quote at a different shape (plan/24 D76).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import Project, Task, TaskRun  # noqa: E402
from app.services.work.attention import derive_attention  # noqa: E402
from app.services.work.rows import WorkRowReader  # noqa: E402

SEED_PROJECT_SLUG = "cv-dataset-20260819"


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def percentile(samples: list[float], fraction: float) -> float:
    """Nearest-rank, not interpolated: with 20 samples an interpolated P95 invents a
    value between two observations, and every threshold here is compared against
    something that actually happened."""
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered)) - 1))
    return ordered[index]


def summarise(samples: list[float]) -> dict[str, float]:
    return {
        "n": len(samples),
        "min_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=SEED_PROJECT_SLUG)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument(
        "--out", default="artifacts/px/local/w0/attention-measurement.json"
    )
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    results: dict[str, object] = {}

    async with maker() as session:
        project = (
            await session.execute(
                sa.select(Project).where(Project.slug == args.project)
            )
        ).scalar_one_or_none()
        if project is None:
            print(f"no project with slug {args.project}", file=sys.stderr)
            return 2
        cards = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(Task)
                .where(Task.project_id == project.id)
            )
        ).scalar_one()
        queued = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRun)
                .where(TaskRun.project_id == project.id, TaskRun.status == "queued")
            )
        ).scalar_one()

        # Nothing is connected. That is the expensive branch and it is also the honest
        # one for a measurement: an online runner makes phase B stop at the first
        # eligible machine, so a "fast" number would be a number about the fixture.
        def offline(_: uuid.UUID) -> bool:
            return False

        reader = WorkRowReader(session)
        # One untimed pass so that the plan cache and the connection are warm; the first
        # call otherwise measures PostgreSQL parsing rather than this code.
        rows, runtime = await reader.for_project(project, is_online=offline)

        page: list[float] = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            rows, runtime = await reader.for_project(project, is_online=offline)
            for row in rows:
                derive_attention(row, runtime)
            page.append((time.perf_counter() - started) * 1000)
        results["page_of_cards"] = {**summarise(page), "cards": int(cards)}

        pure: list[float] = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            for row in rows:
                derive_attention(row, runtime)
            pure.append((time.perf_counter() - started) * 1000)
        results["derive_attention_pure"] = {**summarise(pure), "calls": len(rows)}

        active = await reader._repository.active_runs(project.id)  # noqa: SLF001
        queued_runs = [run for run in active.values() if run.status == "queued"]
        tasks = {
            task.id: task
            for task in (
                await session.execute(
                    sa.select(Task).where(Task.project_id == project.id)
                )
            ).scalars()
        }
        phase_b: list[float] = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            await reader.runtime_signals(queued_runs, tasks, is_online=offline)
            phase_b.append((time.perf_counter() - started) * 1000)
        results["phase_b"] = {**summarise(phase_b), "queued": len(queued_runs)}

        plan = (
            await session.execute(
                sa.text(
                    "EXPLAIN (FORMAT JSON) SELECT id FROM tasks WHERE project_id = :pid "
                    "ORDER BY updated_at DESC, id DESC"
                ),
                {"pid": str(project.id)},
            )
        ).scalar_one()
        indexes = [
            row[0]
            for row in (
                await session.execute(
                    sa.text(
                        "SELECT indexname FROM pg_indexes WHERE tablename = 'tasks'"
                    )
                )
            ).all()
        ]
        results["board_order_plan"] = {
            "node": plan[0]["Plan"]["Node Type"],
            "total_cost": plan[0]["Plan"]["Total Cost"],
            "indexes_on_tasks": sorted(indexes),
        }

    await engine.dispose()

    payload = {
        "commit": commit(),
        "database": url.rsplit("/", 1)[-1],
        "project_slug": args.project,
        "cards": int(cards),
        "queued_runs": int(queued),
        "iterations": args.iterations,
        "results": results,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
