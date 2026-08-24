#!/usr/bin/env python
"""The one fixture `beta.1` adds: N queued runs with nothing able to claim them (PX-24).

    uv run --project backend python scripts/px/seed-queued.py --count 60

D92's cost claim is that phase B's work tracks **the length of the dispatch queue**, not
the size of the board. The fixed dataset (`scripts/cv/seed-dataset.py`, seed 20260819)
has 200 cards and no queued run at all, so the claim has nothing to be measured against.
This puts a chosen number of `ready` cards into `queued` against a runner that cannot
take them, which is the expensive shape: every candidate is examined and rejected, so the
loop runs to completion rather than short-circuiting on the first eligible machine.

**The runner is enabled and its node is never connected.** Disabling it would take it out
of the query entirely and measure the cheap path — which is the mistake this docstring
exists to stop the next person making.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import AgentRunner, Node, Project, Task, TaskRun  # noqa: E402

SEED_PROJECT_SLUG = "cv-dataset-20260819"
# A tag no runner in the fixture carries, so every candidate is rejected on condition 4
# rather than on being offline. Both rejections are `no_eligible_runner`; only this one
# exercises `tag_match` for every runner in the table.
UNSATISFIABLE_LABEL = "px-no-such-capability"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--project", default=SEED_PROJECT_SLUG, help="project slug")
    parser.add_argument("--out", default="artifacts/px/local/w0/queued.json")
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        project = (
            await session.execute(
                sa.select(Project).where(Project.slug == args.project)
            )
        ).scalar_one_or_none()
        if project is None:
            print(f"no project with slug {args.project}", file=sys.stderr)
            return 2

        runner = (
            (
                await session.execute(
                    sa.select(AgentRunner).where(AgentRunner.enabled.is_(True))
                )
            )
            .scalars()
            .first()
        )
        if runner is None:
            node = Node(
                id=uuid.uuid4(),
                name="px-idle",
                hostname="px-idle.invalid",
                status="offline",
            )
            session.add(node)
            await session.flush()
            runner = AgentRunner(
                id=uuid.uuid4(),
                node_id=node.id,
                name="px-idle",
                runtimes=["claude"],
                labels=[],
                run_untagged=True,
            )
            session.add(runner)
            await session.flush()

        # `ready` first, then `backlog`. The seed has 40 ready cards and the
        # measurement asks for 60, and the difference does not matter: what phase B
        # examines is the **queued run**, and the card's stage takes no part in the
        # eligibility predicates. Ordering ready first keeps the smaller counts
        # (the 6-queued baseline) on the stage a dispatch would really come from.
        cards = list(
            (
                await session.execute(
                    sa.select(Task)
                    .where(
                        Task.project_id == project.id,
                        Task.stage.in_(("ready", "backlog")),
                    )
                    .order_by(
                        sa.case((Task.stage == "ready", 0), else_=1),
                        Task.card_ref,
                    )
                    .limit(args.count)
                )
            ).scalars()
        )
        if len(cards) < args.count:
            print(
                f"only {len(cards)} dispatchable cards in {args.project}; "
                f"asked for {args.count}",
                file=sys.stderr,
            )
            return 2

        existing = dict(
            (
                await session.execute(
                    sa.select(TaskRun.task_id, sa.func.max(TaskRun.seq)).group_by(
                        TaskRun.task_id
                    )
                )
            ).all()
        )
        for card in cards:
            card.required_labels = [UNSATISFIABLE_LABEL]
            session.add(
                TaskRun(
                    id=uuid.uuid4(),
                    task_id=card.id,
                    project_id=project.id,
                    seq=int(existing.get(card.id, 0)) + 1,
                    status="queued",
                    attempt=1,
                    runtime="claude",
                    source_kind="none",
                )
            )
        await session.commit()
        queued = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRun)
                .where(TaskRun.project_id == project.id, TaskRun.status == "queued")
            )
        ).scalar_one()

    await engine.dispose()
    payload = {
        "project_id": str(project.id),
        "project_slug": args.project,
        "requested": args.count,
        "queued_total": int(queued),
        "runner": runner.name,
        "label": UNSATISFIABLE_LABEL,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
