#!/usr/bin/env python
"""What `work-items`, `work-counts` and a bulk update cost (PX-25, plan/26/03 §5).

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/px/measure-work-api.py

Three budgets, and the middle one is the tight one:

===========================================  ==========  =======================
`work-items`, 200 cards, P95                  < 1 s       the upstream budget
`work-counts`, P95                            < 200 ms    **D95 polls it every 20 s**
bulk update of 100 cards, one transaction     < 3 s       and if it is over, the
                                                          limit comes down to the
                                                          measured value (D96)
===========================================  ==========  =======================

`work-counts` is the hottest endpoint in the phase: every open board tab asks for it three
times a minute. The bulk figure is the one with a **decision** attached — the limit of 100
is provisional until this has been run, because a bulk update is a hundred single-card
writes in one transaction rather than one statement.

Measured against the service functions rather than over HTTP: what is being sized is the
query and the derivation, and an ASGI round trip would add the same constant to every
number while making the result depend on the client.
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

from app.db.models import Project, Task, User  # noqa: E402
from app.services.tasks import TaskService  # noqa: E402
from app.services.work.filters import FilterNode, compile_filter  # noqa: E402
from app.services.work.items import work_counts, work_items  # noqa: E402
from app.services.work.scope import ProjectScope  # noqa: E402
from app.settings import Settings  # noqa: E402

SEED_PROJECT_SLUG = "cv-dataset-20260819"
BULK_SIZE = 100


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def percentile(samples: list[float], fraction: float) -> float:
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
        "--out", default="artifacts/px/local/w2/work-api-measurement.json"
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
        scope = ProjectScope(all_projects=False, project_ids=frozenset({project.id}))
        unfiltered = compile_filter(None)
        # A filter with a derived term, which is the expensive path: three of the fifteen
        # fields are not columns, so the whole SQL-admitted set is derived before paging.
        derived = compile_filter(
            FilterNode.model_validate(
                {"field": "execution_status", "op": "eq", "value": "not_queued"}
            )
        )

        def offline(_: uuid.UUID) -> bool:
            return False

        # One untimed pass, so the first call does not measure PostgreSQL parsing.
        await work_items(
            session,
            scope=scope,
            compiled=unfiltered,
            project_id=project.id,
            group="lifecycle",
            is_online=offline,
        )

        for label, compiled in (
            ("unfiltered", unfiltered),
            ("derived_filter", derived),
        ):
            samples: list[float] = []
            for _ in range(args.iterations):
                started = time.perf_counter()
                await work_items(
                    session,
                    scope=scope,
                    compiled=compiled,
                    project_id=project.id,
                    group="lifecycle",
                    is_online=offline,
                )
                samples.append((time.perf_counter() - started) * 1000)
            results[f"work_items_{label}"] = summarise(samples)

        samples = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            await work_counts(
                session,
                scope=scope,
                compiled=unfiltered,
                project_id=project.id,
                is_online=offline,
            )
            samples.append((time.perf_counter() - started) * 1000)
        results["work_counts"] = summarise(samples)

        cards = (
            await session.execute(
                sa.select(Task.id).where(Task.project_id == project.id).limit(1)
            )
        ).scalars()
        results["cards"] = int(
            (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(Task)
                    .where(Task.project_id == project.id)
                )
            ).scalar_one()
        )
        del cards

    # The bulk transaction, on its own session and rolled back: it writes four rows per
    # card and the measurement must not leave four hundred behind.
    bulk_samples: list[float] = []
    for _ in range(3):
        async with maker() as session:
            actor = (await session.execute(sa.select(User).limit(1))).scalar_one()
            project = (
                await session.execute(
                    sa.select(Project).where(Project.slug == args.project)
                )
            ).scalar_one()
            ids = list(
                (
                    await session.execute(
                        sa.select(Task.id)
                        .where(Task.project_id == project.id)
                        .order_by(Task.card_ref)
                        .limit(BULK_SIZE)
                    )
                ).scalars()
            )
            service = TaskService(
                session,
                settings=Settings(projects_enabled=True, agent_runs_enabled=False),
            )
            started = time.perf_counter()
            for task_id in ids:
                task = await service.require_task(task_id)
                await service.update_task(
                    task=task,
                    actor_id=actor.id,
                    actor_kind="user",
                    expected_version=task.version,
                    changes={"priority": "high"},
                )
            bulk_samples.append((time.perf_counter() - started) * 1000)
            await session.rollback()
    results["bulk_update_100"] = summarise(bulk_samples)

    await engine.dispose()
    payload = {
        "commit": commit(),
        "database": url.rsplit("/", 1)[-1],
        "project_slug": args.project,
        "iterations": args.iterations,
        "bulk_size": BULK_SIZE,
        "budgets_ms": {
            "work_items": 1000,
            "work_counts": 200,
            "bulk_update_100": 3000,
        },
        "results": results,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
