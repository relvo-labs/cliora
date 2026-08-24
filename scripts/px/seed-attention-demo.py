#!/usr/bin/env python
"""One small project showing all eight attention levels at once (PX-24/PX-18 evidence).

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/px/seed-attention-demo.py

**This is a demonstration fixture, not a performance one.** The performance numbers come
from the fixed 200-card dataset (`scripts/cv/seed-dataset.py`); what this exists for is
the wave-0 evidence in plan/26/00 §4b — a screenshot of the *existing* board in which a
reader can see the eight badges beside one another and judge whether they are
distinguishable without reading the colours.

Levels 5 and 6 depend on the node registry, which is a dict in the Central process. This
seeds rows that make them true **for a Central with nothing connected**, which is the
state a locally started one is in.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.clock import now_utc  # noqa: E402
from app.db.models import (  # noqa: E402
    AgentRunner,
    Node,
    Project,
    Task,
    TaskDependency,
    TaskRun,
    User,
    VerificationReport,
)

SLUG = "px-attention-demo"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/px/local/w0/attention-demo.json")
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2

    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        owner = (await session.execute(sa.select(User).limit(1))).scalars().first()
        if owner is None:
            print("no users — run create-admin first", file=sys.stderr)
            return 2

        existing = (
            await session.execute(sa.select(Project).where(Project.slug == SLUG))
        ).scalar_one_or_none()
        if existing is not None:
            await session.execute(sa.delete(Project).where(Project.id == existing.id))
            await session.flush()

        project = Project(
            id=uuid.uuid4(), name="Attention demo", slug=SLUG, owner_user_id=owner.id
        )
        session.add(project)
        await session.flush()

        node = Node(
            id=uuid.uuid4(),
            name="px-demo-vm",
            hostname="px-demo.invalid",
            status="offline",
        )
        session.add(node)
        await session.flush()
        runner = AgentRunner(
            id=uuid.uuid4(),
            node_id=node.id,
            name="px-demo-runner",
            runtimes=["claude"],
            labels=[],
            run_untagged=True,
        )
        session.add(runner)
        await session.flush()

        seq = 0

        def card(title: str, stage: str, **fields: object) -> Task:
            nonlocal seq
            seq += 1
            task = Task(
                id=uuid.uuid4(),
                project_id=project.id,
                card_ref=f"AT-{seq}",
                title=title,
                stage=stage,
                source="none",
                delivery="none",
                **fields,  # type: ignore[arg-type]
            )
            session.add(task)
            return task

        def run(task: Task, status: str, **fields: object) -> TaskRun:
            row = TaskRun(
                id=uuid.uuid4(),
                task_id=task.id,
                project_id=project.id,
                seq=1,
                status=status,
                attempt=1,
                source_kind="none",
                **fields,  # type: ignore[arg-type]
            )
            session.add(row)
            return row

        # 1 waiting_for_your_input
        stalled = card(
            "支援 SAML SSO 登入",
            "implementing",
            open_question_count=1,
            waiting_for_actor="human",
            risk="high",
        )
        run(stalled, "waiting_for_input", runtime="claude")

        # 2 pending_human_approval — in review with no gate approved
        card("匯出報表加上時區選項", "verify", risk="medium")

        # 3 verification_failed
        bad = card("修正登入節流的計數", "implementing")
        session.add(
            VerificationReport(
                id=uuid.uuid4(),
                task_id=bad.id,
                project_id=project.id,
                result="failed",
                source="machine_verified",
                reported_by_kind="agent",
            )
        )

        # 4 run_failed
        failed = card("升級 asyncpg 至 0.30", "implementing")
        run(failed, "failed", result="failed")

        # 5 no_eligible_runner — asks for a tag nothing carries
        tagged = card("在 arm64 上重建映像檔", "ready", required_labels=["arm64"])
        run(tagged, "queued", runtime="claude")

        # 6 assigned_runner_offline — named machine, node not connected
        assigned = card("同步 staging 的種子資料", "ready")
        run(assigned, "queued", runtime="claude", assigned_runner_id=runner.id)

        # 7 dependency_blocked
        blocker = card("先決定 token 的存放位置", "ready")
        blocked = card("接上第三方 webhook", "ready")
        await session.flush()
        session.add(TaskDependency(task_id=blocked.id, depends_on_task_id=blocker.id))

        # 8 over_wip_or_stale — in flight and untouched for longer than the threshold
        stale = card("整理舊的遷移檔", "implementing")
        await session.flush()
        await session.execute(
            sa.update(Task)
            .where(Task.id == stale.id)
            .values(updated_at=now_utc() - timedelta(days=21))
        )

        # Two quiet cards, so the board is not wall-to-wall badges — a screenshot in
        # which everything is flagged proves nothing about whether a flag draws the eye.
        card("補上 API 文件的範例", "ready")
        card("刪除未使用的設定旗標", "done")

        await session.commit()
        project_id = str(project.id)

    await engine.dispose()
    payload = {"project_id": project_id, "slug": SLUG, "cards": seq}
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
