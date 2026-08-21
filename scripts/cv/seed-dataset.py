#!/usr/bin/env python
"""The fixed dataset every `alpha.2` performance threshold is measured on (`CE-10`, D76).

    uv run --project backend python scripts/cv/seed-dataset.py [--out FILE]

`research/03/CHECKLIST` §0 asked for this before any threshold was quoted, and gave the
reason: **measuring after the fact is meaningless.** `beta.1` will do heavier queries on
the same tables, and without a number from `alpha.2` on a known shape there is nothing to
compare a regression against.

What is fixed is the **rule that produces it**, not the bytes (D76): one seed, written
into `dataset.json` beside the row counts, so a second person can produce the same shape
and a schema change cannot leave a stale dump that fails to restore.

    1 project
    200 tasks         80 backlog / 40 ready / 20 implementing / 20 blocked / 40 done
    1 "deep card"     500 messages, seq 1..500, six kinds mixed
    20 waiting cards  one open question each
    6 runs            two of them continuations (parent_run_id set)
    5 failed runs     so a query over failures has something to find
    1 dependency edge chain of three cards, so `notin_(blocked)` is exercised

Messages go in through `ConversationService.post`, not raw inserts: the sequence is taken
with `UPDATE … RETURNING` on the card's row, and a dataset whose seqs were assigned by a
loop variable would not be the thing being measured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import (  # noqa: E402
    AgentRunner,
    Project,
    Task,
    TaskDependency,
    TaskRun,
    User,
)
from app.services.conversation import ConversationService  # noqa: E402

SEED = 20260819
DEEP_MESSAGES = 500
TASKS = 200
WAITING_CARDS = 20
FAILED_RUNS = 5
# The six lanes by their real names (`process.LANE_ORDER`). **There is no `running`
# stage** — a card being worked on is `implementing`, and a check constraint says so.
STAGES = (
    ["backlog"] * 80
    + ["ready"] * 40
    + ["implementing"] * 20
    + ["blocked"] * 20
    + ["done"] * 40
)
KINDS = ["comment", "comment", "comment", "question", "answer", "system", "proposal"]


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
    parser.add_argument("--out", default="artifacts/cv/local/dataset.json")
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2
    rng = random.Random(SEED)
    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        owner = (await session.execute(sa.select(User).limit(1))).scalars().first()
        if owner is None:
            print("no users in this database — run create-admin first", file=sys.stderr)
            return 2
        runner = (
            (await session.execute(sa.select(AgentRunner).limit(1))).scalars().first()
        )

        name = f"cv-dataset-{SEED}"
        project = Project(id=uuid.uuid4(), name=name, slug=name, owner_user_id=owner.id)
        session.add(project)
        await session.flush()

        cards: list[Task] = []
        for index in range(TASKS):
            task = Task(
                id=uuid.uuid4(),
                project_id=project.id,
                card_ref=f"DS-{index + 1}",
                title=f"資料集卡片 {index + 1}",
                stage=STAGES[index],
                source="none",
                delivery="none",
                risk=rng.choice(["low", "medium", "high"]),
            )
            session.add(task)
            cards.append(task)
        await session.flush()

        # A chain of three, so the queue's `notin_(blocked)` clause has something real to
        # exclude rather than an always-empty subquery.
        session.add(TaskDependency(task_id=cards[1].id, depends_on_task_id=cards[0].id))
        session.add(TaskDependency(task_id=cards[2].id, depends_on_task_id=cards[1].id))

        runs: list[TaskRun] = []
        if runner is not None:
            for index in range(6):
                run = TaskRun(
                    id=uuid.uuid4(),
                    task_id=cards[index].id,
                    project_id=project.id,
                    seq=1,
                    status="succeeded",
                    result="succeeded",
                    runner_id=runner.id,
                    source_kind="none",
                    finished_at=datetime.now(timezone.utc) - timedelta(hours=index),
                )
                session.add(run)
                await session.flush()
                run.root_run_id = run.id
                runs.append(run)
            # Two continuations, so a query that joins a turn to its parent is not
            # measured against an empty set.
            for parent in runs[:2]:
                child = TaskRun(
                    id=uuid.uuid4(),
                    task_id=parent.task_id,
                    project_id=project.id,
                    seq=2,
                    status="succeeded",
                    result="succeeded",
                    runner_id=runner.id,
                    source_kind="none",
                    parent_run_id=parent.id,
                    root_run_id=parent.id,
                    turn_seq=2,
                    input_from_seq=0,
                    input_to_seq=0,
                    finished_at=datetime.now(timezone.utc),
                )
                session.add(child)
            for index in range(FAILED_RUNS):
                session.add(
                    TaskRun(
                        id=uuid.uuid4(),
                        task_id=cards[10 + index].id,
                        project_id=project.id,
                        seq=1,
                        status="failed",
                        result="failed",
                        runner_id=runner.id,
                        source_kind="none",
                        finished_at=datetime.now(timezone.utc),
                    )
                )
        await session.commit()

        # --- the deep card ------------------------------------------------------
        conversation = ConversationService(session)
        deep = cards[0]
        for index in range(DEEP_MESSAGES):
            kind = KINDS[index % len(KINDS)]
            if kind == "proposal":
                await conversation.post(
                    task=deep,
                    body=f"規格提案 #{index}",
                    kind="proposal",
                    author_kind="agent",
                    author_runner_id=runner.id if runner else None,
                )
            elif kind == "system":
                await conversation.post(
                    task=deep,
                    body=f"系統事件 #{index}",
                    kind="system",
                    author_kind="system",
                )
            elif kind in ("question", "answer"):
                # Written as plain comments: a `question` here would open a real question
                # and change what the queue and the projection say, and the dataset is
                # meant to be inert.
                await conversation.post(
                    task=deep,
                    body=f"（{kind} 形狀的內容）#{index}",
                    kind="comment",
                    author_kind="agent" if kind == "question" else "user",
                    author_user_id=None if kind == "question" else owner.id,
                    author_runner_id=runner.id
                    if runner and kind == "question"
                    else None,
                )
            else:
                await conversation.post(
                    task=deep,
                    body=f"第 {index} 則留言，長度中等，用來量分頁。" * 2,
                    kind="comment",
                    author_kind="user",
                    author_user_id=owner.id,
                )
            if index % 100 == 99:
                await session.commit()
        await session.commit()

        # --- the waiting cards --------------------------------------------------
        waiting_ids: list[str] = []
        for card in cards[100 : 100 + WAITING_CARDS]:
            run = TaskRun(
                id=uuid.uuid4(),
                task_id=card.id,
                project_id=project.id,
                seq=1,
                status="succeeded",
                result="awaiting_input",
                runner_id=runner.id if runner else None,
                source_kind="none",
                input_from_seq=0,
                input_to_seq=0,
                finished_at=datetime.now(timezone.utc),
            )
            session.add(run)
            await session.flush()
            run.root_run_id = run.id
            await conversation.post(
                task=card,
                body="要用哪一版的驗收標準？",
                kind="question",
                author_kind="agent",
                author_runner_id=runner.id if runner else None,
                run_id=run.id,
            )
            waiting_ids.append(str(card.id))
        await session.commit()

        counts = {}
        for table in ("tasks", "task_messages", "task_questions", "task_runs"):
            counts[table] = (
                await session.execute(sa.text(f"select count(*) from {table}"))
            ).scalar_one()

    await engine.dispose()

    payload = {
        "seed": SEED,
        "commit": commit(),
        "database": url.rsplit("/", 1)[-1],
        "project_id": str(project.id),
        "deep_card_id": str(deep.id),
        "deep_card_messages": DEEP_MESSAGES,
        "waiting_card_ids": waiting_ids,
        "tasks": TASKS,
        "counts": counts,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False))
    print(f"dataset written to {args.out} (seed {SEED})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
