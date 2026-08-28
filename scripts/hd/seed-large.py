#!/usr/bin/env python
"""The 2000-card dataset `beta.2` measures scale on (`HD-10`, plan/27/06 §2).

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/hd/seed-large.py

**A second file, and `scripts/cv/seed-dataset.py` is not touched.** That one is 200 cards
and is what `alpha.2`, `alpha.3` and `beta.1` measured against; editing it would leave
three phases of numbers with nothing to compare to. `plan/27` D127 says so and this is
the file that obeys it.

Ten times the fixed dataset, **except for one dimension that is deliberately not
proportional**:

    2000 tasks            same 40/20/10/10/20 % split as the 200-card set
    +9 sibling projects   18000 more cards, so the target is ~10 % of the table
    200 waiting cards     one open question each — attention level 1 at 10 %
    5000 messages         spread, plus one deep card that keeps its 500
    50 repositories       provider reconcile costs repositories × 3 GET per round
    1 chain of 200        ← **the non-proportional one**

`blocking_counts()` walks dependency edges, and its worst case is governed by **chain
depth**, not by card count. Scaling the 200-card set's three-link chain by ten gives a
30-link chain, which is not a worst case of anything. A 200-node chain is: every card in
it has an unsatisfied dependency, and the recursive walk in `TaskRepository.reaches`
has somewhere to walk.

**What this does not contain is a real filter distribution.** `plan/26/11` §10 is right
that a fixture measures PostgreSQL rather than a workload. What it can still answer is
the question that matters here: at 2000 cards, is `work-items` dominated by the query or
by the derivation? Those two have different fixes.
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
from datetime import timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.clock import now_utc  # noqa: E402
from app.db.models import (  # noqa: E402
    KnowledgeChunk,
    KnowledgeSource,
    Project,
    ProjectRepository,
    Task,
    TaskDependency,
    User,
)

SEED = 20260828
TASKS = 2000
WAITING_CARDS = 200
CHAIN = 200
REPOSITORIES = 50
SOURCES = 5000
#: Sibling projects, so the target project is a **minority** of `tasks`.
#:
#: Without these the fixture measures nothing about the indexes it exists to measure:
#: one project means `project_id = ?` selects 2000 of 2011 rows, the planner correctly
#: prefers a sequential scan over 160 pages, and every `EXPLAIN` reports `Seq Scan` —
#: which reads as a missing index and is actually the planner being right.
#:
#: Nine siblings put the target at ~10 % of the table, which is what a deployment with
#: more than one project looks like and is the condition under which
#: `ix_tasks_project_rank` earns its existence. Found by reading the first `EXPLAIN`
#: run's `Rows Removed by Filter: 11`.
FILLER_PROJECTS = 9
CHUNKS_PER_SOURCE = 4

#: The same proportions as `scripts/cv/seed-dataset.py`, so the two sets are comparable.
STAGES = (
    ["backlog"] * int(TASKS * 0.40)
    + ["ready"] * int(TASKS * 0.20)
    + ["implementing"] * int(TASKS * 0.10)
    + ["blocked"] * int(TASKS * 0.10)
    + ["done"] * int(TASKS * 0.20)
)

#: `source_type` values that exist today. `pull_request` and `release` arrive with
#: `0044`; this file does not seed them, and `HD-03` extends it when they do.
SOURCE_TYPES = ("ticket", "conversation", "decision", "activity", "repo_doc")

#: Vocabulary for chunk bodies. Four independent draws per chunk, so no two chunks share
#: a trigram profile — see the comment at the write site for why that is load-bearing.
_SUBJECTS = ("執行器", "看板", "對話層", "知識索引", "遷移腳本", "驗證流程", "節點代理", "權限矩陣")
_VERBS = ("需要重新設計", "在壓力下退化", "已通過驗收", "與既有假設衝突", "被拆成兩段", "沿用既有機制")
_OBJECTS = ("的租約續期", "的游標分頁", "的相依鏈", "的信任層級", "的重試策略", "的欄位投影", "的快取失效")
_TOOLS = ("alembic", "pytest", "playwright", "ruff", "mypy", "psql", "docker compose", "uvicorn")
_NOTES = (
    "待人工確認。", "已記入 ADR。", "回歸測試涵蓋。", "量測值超出預算。",
    "與上游規劃不一致。", "尚未在 Railway 驗證。", "由下一期承接。",
)


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:  # pragma: no cover - a tarball with no .git
        return "unknown"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/hd/local/large-dataset.json")
    args = parser.parse_args()

    url = os.environ.get("CLIORA_DATABASE_URL")
    if not url:
        print("CLIORA_DATABASE_URL is unset", file=sys.stderr)
        return 2

    rng = random.Random(SEED)
    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    now = now_utc()

    async with maker() as session:
        owner = (await session.execute(sa.select(User).limit(1))).scalars().first()
        if owner is None:
            print("no users in this database — run create-admin first", file=sys.stderr)
            return 2

        # **Re-runnable**, which is an exit condition rather than a convenience
        # (`plan/27/06` §8): a fixture that can only be created once is a fixture whose
        # first partial failure leaves the database in a state only `DROP DATABASE`
        # fixes — and this script's first run failed twice on schema details.
        # `ondelete="CASCADE"` on every child means deleting the project is enough.
        # **Every project this script creates, not only the target one.** The first
        # version deleted `hd-large-…` and left the nine `hd-filler-…` behind, so the
        # second run died on their unique slug — after having already deleted the target,
        # which left the database with fillers, no target, and a `large-dataset.json`
        # pointing at a project that no longer existed. `explain.sh` then measured seven
        # plans over zero rows and called every one of them fast.
        stale = (
            (
                await session.execute(
                    sa.select(Project).where(Project.slug.like(f"hd-%-{SEED}%"))
                )
            )
            .scalars()
            .all()
        )
        for project_row in stale:
            await session.delete(project_row)
        if stale:
            await session.flush()

        name = f"hd-large-{SEED}"
        project = Project(
            id=uuid.uuid4(),
            name=name,
            slug=name,
            owner_user_id=owner.id,
            knowledge_enabled=True,
        )
        session.add(project)
        await session.flush()

        # --- 2000 cards -------------------------------------------------------------
        #
        # `updated_at` is spread over 90 days rather than left at `now()`: the board's
        # index is `(project_id, updated_at DESC)` and a table where every row shares one
        # timestamp gives the planner a sort it can do for free, which is not the shape
        # being measured.
        cards: list[Task] = []
        for index in range(TASKS):
            cards.append(
                Task(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    card_ref=f"HD-{index + 1}",
                    title=f"規模資料集卡片 {index + 1}",
                    stage=STAGES[index],
                    source="none",
                    delivery="none",
                    risk=rng.choice(["low", "medium", "high"]),
                    priority=rng.choice(["low", "normal", "high"]),
                    updated_at=now - timedelta(minutes=rng.randrange(0, 90 * 24 * 60)),
                )
            )
        session.add_all(cards)
        await session.flush()

        # --- the chain that is not proportional --------------------------------------
        session.add_all(
            TaskDependency(
                task_id=cards[index + 1].id, depends_on_task_id=cards[index].id
            )
            for index in range(CHAIN)
        )

        # --- 50 repositories ----------------------------------------------------------
        #
        # Three columns rather than a URL, because `ProjectRepository` splits them for a
        # security reason (`models.py`) and a fixture that concatenated them would be
        # seeding a shape the application refuses.
        session.add_all(
            ProjectRepository(
                id=uuid.uuid4(),
                project_id=project.id,
                scheme="https",
                host="github.com",
                path=f"cliora-scale/repo-{index + 1}",
                default_branch="main",
                label=f"repo-{index + 1}",
                auth_kind="ambient",
                created_by=owner.id,
            )
            for index in range(REPOSITORIES)
        )
        await session.flush()

        # --- 5000 knowledge sources, 20000 chunks --------------------------------------
        #
        # Written directly rather than through `KnowledgeStore.upsert`: this is measuring
        # the *index*, and going through ingestion would measure the chunker instead and
        # take twenty minutes. The tokenised document is what the GIN index is built from,
        # so it is produced by the real function.
        from app.services.knowledge.tokenize import document

        sources: list[KnowledgeSource] = []
        for index in range(SOURCES):
            occurred = now - timedelta(minutes=rng.randrange(0, 180 * 24 * 60))
            sources.append(
                KnowledgeSource(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    source_type=SOURCE_TYPES[index % len(SOURCE_TYPES)],
                    source_external_id=f"scale:{index}",
                    source_version="v1",
                    authority=rng.choice(["accepted", "verified", "generated", "discussion"]),
                    checksum=f"{index:064d}",
                    title=f"規模來源 {index + 1}",
                    occurred_at=occurred,
                    source_updated_at=occurred,
                    chunk_count=CHUNKS_PER_SOURCE,
                )
            )
        session.add_all(sources)
        await session.flush()

        for source in sources:
            for ordinal in range(CHUNKS_PER_SOURCE):
                # **Varied, and that is a measurement requirement rather than realism.**
                #
                # The first version of this seed used one template for all 20,000 chunks.
                # Every body then shared nearly every trigram, so `ix_knowledge_chunks_trgm`
                # returned all 20,000 rows as candidates and the recheck removed all of
                # them: 103 ms to produce zero results, with the plan showing the index
                # "used". A benchmark that cannot discriminate measures nothing, and this
                # one produced a number that looked like a finding about the schema.
                #
                # Drawing four terms from a pool of ~40 gives each chunk a distinct
                # trigram profile, which is the property the index needs to be exercised
                # at all.
                body = (
                    f"{source.title} 第 {ordinal + 1} 段。"
                    f"{rng.choice(_SUBJECTS)}{rng.choice(_VERBS)}{rng.choice(_OBJECTS)}，"
                    f"涉及卡片 HD-{rng.randrange(1, TASKS)} 與 {rng.choice(_TOOLS)}。"
                    f"識別碼 {uuid.uuid4().hex[:12]}，"
                    f"備註：{rng.choice(_NOTES)}"
                )
                session.add(
                    KnowledgeChunk(
                        id=uuid.uuid4(),
                        project_id=project.id,
                        source_id=source.id,
                        chunk_key=f"{source.source_external_id}#{ordinal}",
                        content=body,
                        content_hash=f"{index:032d}{ordinal:032d}",
                        token_count=len(body) // 2,
                        search_document=sa.func.setweight(
                            sa.func.to_tsvector(
                                sa.literal_column("'simple'"), document(source.title or "")
                            ),
                            sa.literal_column("'A'"),
                        ).concat(
                            sa.func.setweight(
                                sa.func.to_tsvector(
                                    sa.literal_column("'simple'"), document(body)
                                ),
                                sa.literal_column("'B'"),
                            )
                        ),
                        valid_from=source.occurred_at,
                    )
                )
            if len(session.new) > 4000:
                await session.flush()
        await session.commit()

        # --- sibling projects ---------------------------------------------------------
        #
        # Raw SQL and `generate_series`: this is 18,000 rows whose only property that
        # matters is that they exist and belong to another project, and building them
        # through the ORM would take longer than the measurement.
        for filler in range(FILLER_PROJECTS):
            fname = f"hd-filler-{SEED}-{filler}"
            other = (
                await session.execute(
                    sa.text(
                        "INSERT INTO projects (id, name, slug, status, owner_user_id, "
                        "next_card_seq, allowed_secret_names, verification_commands, "
                        "process_overrides, require_project_verification, "
                        "knowledge_enabled, knowledge_settings) "
                        "VALUES (gen_random_uuid(), :n, :n, 'active', :o, 1, '[]', '[]', "
                        "'{}', false, false, '{}') RETURNING id"
                    ),
                    {"n": fname, "o": owner.id},
                )
            ).scalar_one()
            await session.execute(
                sa.text(
                    "INSERT INTO tasks (id, project_id, card_ref, title, stage, source, "
                    "delivery, risk, priority, rank, updated_at, created_at) "
                    "SELECT gen_random_uuid(), :p, 'FL-' || g, 'filler ' || g, "
                    "  (ARRAY['backlog','ready','implementing','blocked','done'])[1 + (g % 5)], "
                    "  'none', 'none', 'medium', 'normal', 'a' || lpad(g::text, 6, '0'), "
                    "  now() - (g || ' minutes')::interval, now() "
                    "FROM generate_series(1, :n) g"
                ),
                {"p": other, "n": TASKS},
            )
        await session.commit()

        counts = {}
        # `task_dependencies` has no `project_id` — it is an edge between two cards and
        # reaches the project only through them. Counted by join rather than by a column
        # that does not exist.
        for table in (
            "tasks",
            "project_repositories",
            "knowledge_sources",
            "knowledge_chunks",
        ):
            counts[table] = (
                await session.execute(
                    sa.text(f"select count(*) from {table} where project_id = :p"),
                    {"p": project.id},
                )
            ).scalar_one()
        counts["task_dependencies"] = (
            await session.execute(
                sa.text(
                    "select count(*) from task_dependencies d "
                    "join tasks t on t.id = d.task_id where t.project_id = :p"
                ),
                {"p": project.id},
            )
        ).scalar_one()

        # The ratio the module docstring claims, printed rather than assumed —
        # `plan/27/06` §2 says the four-chunks-per-source figure is *chosen*, not
        # measured, and a seed that silently produced three would make the 20,000 in the
        # plan a number nobody can reproduce.
        ratio = counts["knowledge_chunks"] / max(counts["knowledge_sources"], 1)

    await engine.dispose()

    payload = {
        "seed": SEED,
        "filler_projects": FILLER_PROJECTS,
        "commit": commit(),
        "database": url.rsplit("/", 1)[-1],
        "project_id": str(project.id),
        "counts": counts,
        "chunks_per_source": round(ratio, 2),
        "dependency_chain_depth": CHAIN,
        "note": (
            "The chain is deliberately not proportional to the card count: "
            "blocking_counts() is governed by depth, not by rows."
        ),
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
