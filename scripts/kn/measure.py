#!/usr/bin/env python
"""The three budgets and the two baselines (`KN-13`, `plan/25/09-…md` §5).

Three of these have thresholds and two deliberately do not.

**With a threshold**: ingest freshness (P95 < 10 s), search (P95 < 1 s) and context pack
build (P95 < 2 s). Those numbers came from the planning document and are the ones the
exit conditions read.

**Without**: the `search_document` size ratio and the relevance baseline. Nobody knows
what a good value is yet, and *a threshold that gets raised the first time it goes red is
worse than no threshold* — it looks like a standard and behaves like a formality. These
are recorded so `KN-13` has a number and so a later change has something to compare with.

The relevance set includes **one query that is expected to miss**. That is D40's accepted
cost measured rather than assumed: the day a vector channel is proposed, this is its
control group.

    uv run --project backend python scripts/kn/measure.py --out artifacts/kn/local/measurements.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import subprocess
import sys
import time
import uuid
from datetime import timedelta

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.clock import now_utc  # noqa: E402
from app.db.models import Project, Role, Task, User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.services.knowledge.context import ContextBuilder  # noqa: E402
from app.services.knowledge.outbox import invalidate_enabled_cache  # noqa: E402
from app.services.knowledge.search import KnowledgeSearch  # noqa: E402
from app.services.knowledge.store import ExtractedSource, KnowledgeStore  # noqa: E402

#: The dataset from `plan/25/09` §5, scaled to what one machine can build in a minute.
#: Recorded in the output so a number is never read without the shape that produced it.
TASKS = 200
MESSAGES = 500
REPO_DOCS = 300

#: The fixed query set. `expect` is what a person judged, once, by reading the corpus —
#: relevance has no automatic oracle and pretending otherwise produces a number that
#: measures the oracle.
QUERIES = [
    ("CV-05", "exact reference", True),
    ("lease_expires_at", "symbol", True),
    # A SHA is findable because a document *mentions* it. "Which documents are at
    # commit X" is a filter rather than a query, and this release has no such filter.
    ("139f143", "commit sha in text", True),
    ("lese_expires", "typo", True),
    ("租約過期", "chinese phrase", True),
    ("驗證報告", "chinese phrase", True),
    ("交付", "chinese word", True),
    # **Expected to miss.** Different wording for the same idea, which lexical retrieval
    # cannot bridge. D40's accepted cost, and the control group for any future vector
    # experiment.
    ("how do we handle timeouts", "semantic gap", False),
]


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


async def _seed(session) -> tuple[uuid.UUID, uuid.UUID]:
    role = (await session.execute(sa.select(Role).where(Role.name == "Admin"))).scalar_one()
    name = f"kn-measure-{uuid.uuid4().hex[:8]}"
    user = User(
        id=uuid.uuid4(),
        username=name,
        display_name=name,
        password_hash=hash_password("pw-12345678"),
        role_id=role.id,
    )
    session.add(user)
    await session.flush()
    project = Project(
        id=uuid.uuid4(), name=name, slug=name, owner_user_id=user.id, knowledge_enabled=True
    )
    session.add(project)
    await session.flush()
    invalidate_enabled_cache()

    store = KnowledgeStore(session)
    now = now_utc()
    focus_task: uuid.UUID | None = None
    for index in range(TASKS):
        task = Task(
            id=uuid.uuid4(),
            project_id=project.id,
            card_ref=f"KN-{index}",
            title=f"卡片 {index}：租約過期時要怎麼處理",
            description="lease_expires_at 到期之後 sweep 會把 run 收成 lost。",
            created_by=user.id,
        )
        session.add(task)
        if focus_task is None:
            focus_task = task.id
        await store.upsert(
            project_id=project.id,
            source_type="ticket",
            source=ExtractedSource(
                external_id=f"task:{task.id}",
                version="v1",
                authority="discussion",
                title=task.title,
                text=task.description or "",
                occurred_at=now - timedelta(days=index % 30),
                source_updated_at=now - timedelta(days=index % 30),
            ),
        )
    for index in range(MESSAGES):
        await store.upsert(
            project_id=project.id,
            source_type="conversation",
            source=ExtractedSource(
                external_id=f"message:{uuid.uuid4()}",
                version=f"seq:{index}",
                authority="discussion",
                title=f"對話 #{index}",
                text=f"這裡在討論 CV-05 的續跑與驗證報告，第 {index} 則。",
                occurred_at=now - timedelta(hours=index),
                source_updated_at=now - timedelta(hours=index),
            ),
        )
    for index in range(REPO_DOCS):
        await store.upsert(
            project_id=project.id,
            source_type="repo_doc",
            source=ExtractedSource(
                external_id=f"repo:docs/{index}.md",
                version="139f143",
                authority="canonical",
                title=f"docs/{index}.md",
                text=(
                    "When the lease expires the sweep marks the run lost and re-queues "
                    "it. See lease_expires_at, landed in 139f143. 交付一律走 PR。"
                    f"段落 {index}。"
                ),
                occurred_at=now - timedelta(days=index % 90),
                source_updated_at=now - timedelta(days=index % 90),
            ),
        )
    await session.commit()
    assert focus_task is not None
    return project.id, focus_task


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/kn/local/measurements.json")
    parser.add_argument(
        "--url",
        default="postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test",
    )
    args = parser.parse_args()

    engine = create_async_engine(args.url)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async with maker() as session:
        started = time.monotonic()
        project_id, task_id = await _seed(session)
        seed_seconds = time.monotonic() - started

    async with maker() as session:
        # Warm the indexes first. A cold-cache number measures the disk, and the budget
        # is explicitly "index warm".
        search = KnowledgeSearch(session, project_id)
        for query, _kind, _expect in QUERIES:
            await search.search(query, limit=20)

        search_samples: list[float] = []
        relevance: list[dict[str, object]] = []
        for query, kind, expect in QUERIES:
            hits = 0
            for _ in range(20):
                begin = time.perf_counter()
                result = await search.search(query, limit=20)
                search_samples.append(time.perf_counter() - begin)
                hits = result.total
            relevance.append(
                {
                    "query": query,
                    "kind": kind,
                    "expected_to_find": expect,
                    "hits": hits,
                    # `met` is the honest field: a miss that was *expected* is a
                    # recorded trade-off, not a failure.
                    "met": (hits > 0) == expect,
                }
            )

        pack_samples: list[float] = []
        task = await session.get(Task, task_id)
        builder = ContextBuilder(session)
        for _ in range(30):
            begin = time.perf_counter()
            await builder.build(task)
            pack_samples.append(time.perf_counter() - begin)

        ratio = await session.scalar(
            sa.text(
                "SELECT avg(pg_column_size(search_document)::float "
                "/ greatest(pg_column_size(content), 1)) "
                "FROM knowledge_chunks WHERE project_id = :pid"
            ),
            {"pid": project_id},
        )
        chunks = await session.scalar(
            sa.text("SELECT count(*) FROM knowledge_chunks WHERE project_id = :pid"),
            {"pid": project_id},
        )

    await engine.dispose()

    report = {
        "commit": _commit(),
        "dataset": {
            "tasks": TASKS,
            "messages": MESSAGES,
            "repo_docs": REPO_DOCS,
            "chunks": int(chunks or 0),
            "seed_seconds": round(seed_seconds, 2),
        },
        "budgets": {
            "search_p95_seconds": {
                "value": round(_p95(search_samples), 4),
                "budget": 1.0,
                "met": _p95(search_samples) < 1.0,
            },
            "context_pack_p95_seconds": {
                "value": round(_p95(pack_samples), 4),
                "budget": 2.0,
                "met": _p95(pack_samples) < 2.0,
            },
        },
        "baselines": {
            # No threshold, deliberately: nobody knows the right value, and a threshold
            # raised the first time it goes red is a formality rather than a standard.
            "search_document_size_ratio": round(float(ratio or 0.0), 3),
            "note": (
                "How much larger the CJK-bigram tsvector is than the text it indexes. "
                "Recorded so a later tokenizer change has something to compare against."
            ),
        },
        "relevance": relevance,
        "relevance_note": (
            "One query is expected to miss ('how do we handle timeouts'). That is D40's "
            "accepted cost measured rather than assumed, and the control group for any "
            "future vector channel."
        ),
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    unmet = [row["query"] for row in relevance if not row["met"]]
    breached = [name for name, entry in report["budgets"].items() if not entry["met"]]
    if unmet or breached:
        print(f"\nunmet relevance: {unmet}; breached budgets: {breached}", file=sys.stderr)
        return 1
    print("\nall measured budgets met")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
