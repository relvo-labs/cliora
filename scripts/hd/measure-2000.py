#!/usr/bin/env python
"""The thirteen performance budgets, re-weighed on 2000 cards (`HD-09`, plan/27/07 §5).

    . scripts/hd/env.sh && hd_stack_env
    uv run --project backend python scripts/hd/measure-2000.py

Every number is printed **beside its 200-card value**, because the question this run
answers is "how much did ten times the data cost", and a lone number cannot answer it.
The 200-card column is read from the artifacts the earlier milestones left behind rather
than re-derived, so a disagreement here is a disagreement with a recorded measurement.

**Nine of the thirteen are measured; four are not, and the four are named in the output**
with the reason. Three of them (board first interactive, cached drawer open, optimistic
move) are perceived browser latency: they are the time from a click to a repaint, and the
card count reaches them only through an API call that *is* measured here. The fourth
(message commit → continuation turn) is a daemon round trip whose clock starts after the
write this script times, and it does not touch the tasks table at all.

Shape follows the service-level measurement of `plan/26` (D127): the query and the
derivation are what the card count changes, and an ASGI round trip adds the same constant
to every row while making the result depend on the client. **The concurrency scenarios are
the deliberate exception** and go over HTTP — see `--concurrency`, where the pool and the
worker contending is the entire point.
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

from app.api.http.work import _card  # noqa: E402
from app.db.models import Project, Task, TaskMessage, User  # noqa: E402
from app.services.conversation import ConversationService  # noqa: E402
from app.services.knowledge.context import ContextBuilder  # noqa: E402
from app.services.knowledge.search import KnowledgeSearch  # noqa: E402
from app.services.work.attention import derive_attention  # noqa: E402
from app.services.work.filters import FilterNode, compile_filter  # noqa: E402
from app.services.work.items import work_counts, work_items  # noqa: E402
from app.services.work.rows import WorkRowReader  # noqa: E402
from app.services.work.scope import ProjectScope  # noqa: E402

PROJECT_SLUG = "hd-large-20260828"
DEEP_CARD_MESSAGES = 500
ITERATIONS = 20

#: The 200-card column, read from what the earlier milestones recorded. Each entry names
#: the file it came from so a reader can check it rather than trust it.
BASELINE = {
    "work_items_unfiltered": (14.4, "px/local/w2/work-api-measurement.json"),
    "work_items_derived_filter": (11.441, "px/local/w2/work-api-measurement.json"),
    "work_counts": (9.8, "px/local/w2/work-api-measurement.json"),
    "message_commit": (7.9, "cv/local/conversation-perf.json"),
    "conversation_reopen": (5.5, "cv/local/conversation-perf.json"),
    "knowledge_search": (110.7, "kn/local/measurements.json"),
    "context_pack_build": (78.8, "kn/local/measurements.json"),
    "derive_attention_phase_b": (0.253, "px/local/w0/attention-measurement.json"),
}

#: The `WorkItemCardDTO` payload budget, which is the one row of the thirteen that is
#: measured in bytes rather than milliseconds — and the one whose budget is **not** the
#: upstream number. `research/03/10` §5 says 160 KB; `plan/26`'s D94 refused to copy it
#: (it was derived from a 74 KB figure `plan/19` had already made stale) and pinned the
#: measured value plus 15% instead. The upstream number is recorded here too, because a
#: budget that moved is exactly the kind of thing a later reader assumes never did.
PAYLOAD_BUDGET_BYTES = 198_671
PAYLOAD_UPSTREAM_BYTES = 160 * 1024

#: budget in milliseconds, and the milestone the budget belongs to.
BUDGETS = {
    "work_items_unfiltered": (1000.0, "beta.1", "200 張卡 work-items 初次回應 P95"),
    "work_items_derived_filter": (300.0, "beta.1", "filter apply"),
    "work_counts": (500.0, "beta.1", "My Work counts P95"),
    "message_commit": (500.0, "alpha.2", "Ticket message commit P95"),
    "conversation_reopen": (500.0, "alpha.2", "conversation reopen（最近 50 則）P95"),
    "knowledge_search": (1000.0, "alpha.3", "knowledge search P95"),
    "context_pack_build": (2000.0, "alpha.3", "context pack build P95（index warm）"),
    # **Not one of the thirteen.** An extra, carried because phase B claims not to grow
    # with the project and a claim like that is worth a number. Counted separately below.
    "derive_attention_phase_b": (None, "beta.1", "phase B（in-process registry，額外）"),
}
EXTRA = {"derive_attention_phase_b"}

#: The four that are not re-weighed, and why. Written out rather than omitted: a table of
#: nine rows headed "the thirteen budgets" is a table that has lost four of them quietly.
NOT_REMEASURED = [
    {
        "item": "Board 首次可互動",
        "budget": "< 2s",
        "why": (
            "Perceived browser latency — first paint to interactive, measured in a "
            "browser rather than against a session. The card count reaches it only "
            "through work-items and work-counts, both re-weighed above."
        ),
    },
    {
        "item": "打開已快取 Task Drawer",
        "budget": "< 150ms 感知",
        "why": (
            "'Cached' means no request is made. There is no server work to weigh, and "
            "the card count cannot change a repaint of data already held."
        ),
    },
    {
        "item": "optimistic move",
        "budget": "< 100ms 畫面回應",
        "why": (
            "Optimistic by definition: the screen responds before the write is sent. "
            "The number measures the frontend's own update path."
        ),
    },
    {
        "item": "message commit → continuation turn 開始",
        "budget": "< 10s",
        "why": (
            "A daemon round trip. Its clock starts after the write `message_commit` "
            "times, runs through lease acquisition and process start, and touches the "
            "tasks table not at all. J1 exercised it against a real agentd 0.14.1."
        ),
    },
    {
        "item": "Ticket／decision ingest freshness P95",
        "budget": "< 10s",
        "why": (
            "Worker cadence, not query cost: the number is dominated by how often the "
            "reconciler wakes. HD-10's queue-depth metric is what watches it now."
        ),
    },
]

QUERIES = [
    ("CV-05", "exact reference"),
    ("lease_expires_at", "symbol"),
    ("lese_expires", "typo"),
    ("租約過期", "chinese phrase"),
]


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summarise(samples: list[float]) -> dict[str, float]:
    return {
        "n": len(samples),
        "min_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
    }


async def deep_card(session, project_id: uuid.UUID) -> Task:
    """A card carrying `DEEP_CARD_MESSAGES` messages, so the two conversation budgets are
    weighed against the same conversation depth `alpha.2` used.

    Seeded here rather than in `seed-large.py` because it is a *measurement* fixture: the
    conversation budgets scale with messages per card, and holding that dimension equal to
    the 200-card run is what leaves the table size as the only difference.
    """
    task = (
        await session.execute(
            sa.select(Task).where(Task.project_id == project_id).order_by(Task.card_ref).limit(1)
        )
    ).scalar_one()
    existing = await session.scalar(
        sa.select(sa.func.count()).select_from(TaskMessage).where(TaskMessage.task_id == task.id)
    )
    if existing >= DEEP_CARD_MESSAGES:
        return task

    user = (await session.execute(sa.select(User).limit(1))).scalar_one()
    conversation = ConversationService(session)
    for index in range(existing, DEEP_CARD_MESSAGES):
        await conversation.post(
            task=task,
            body=f"量測資料第 {index} 則留言，用來把對話深度固定在 {DEEP_CARD_MESSAGES}。",
            author_kind="user",
            author_user_id=user.id,
        )
    await session.commit()
    return task


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("CLIORA_DATABASE_URL", ""))
    parser.add_argument("--project", default=PROJECT_SLUG)
    parser.add_argument("--iterations", type=int, default=ITERATIONS)
    parser.add_argument("--out", default="artifacts/hd/local/w6/perf-2000.json")
    args = parser.parse_args()
    if not args.url:
        print("set CLIORA_DATABASE_URL (see scripts/hd/env.sh)", file=sys.stderr)
        return 2

    engine = create_async_engine(args.url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    results: dict[str, object] = {}

    async with maker() as session:
        project = (
            await session.execute(sa.select(Project).where(Project.slug == args.project))
        ).scalar_one_or_none()
        if project is None:
            print(f"no project with slug {args.project}", file=sys.stderr)
            print(
                "re-run: uv run --project backend python scripts/hd/seed-large.py", file=sys.stderr
            )
            await engine.dispose()
            return 2
        cards = await session.scalar(
            sa.select(sa.func.count()).select_from(Task).where(Task.project_id == project.id)
        )
        if cards < 2000:
            print(f"{cards} cards — this measurement is meaningless below 2000", file=sys.stderr)
            await engine.dispose()
            return 2

        task = await deep_card(session, project.id)

    async with maker() as session:
        scope = ProjectScope(all_projects=False, project_ids=frozenset({project.id}))
        unfiltered = compile_filter(None)
        derived = compile_filter(
            FilterNode.model_validate(
                {"field": "execution_status", "op": "eq", "value": "not_queued"}
            )
        )

        def offline(_: uuid.UUID) -> bool:
            return False

        # Untimed first pass: the budget is "index warm", and a cold number measures disk.
        await work_items(
            session,
            scope=scope,
            compiled=unfiltered,
            project_id=project.id,
            group="lifecycle",
            is_online=offline,
        )

        for label, compiled in (("unfiltered", unfiltered), ("derived_filter", derived)):
            samples = []
            for _ in range(args.iterations):
                began = time.perf_counter()
                await work_items(
                    session,
                    scope=scope,
                    compiled=compiled,
                    project_id=project.id,
                    group="lifecycle",
                    is_online=offline,
                )
                samples.append((time.perf_counter() - began) * 1000)
            results[f"work_items_{label}"] = summarise(samples)

        samples = []
        for _ in range(args.iterations):
            began = time.perf_counter()
            await work_counts(
                session,
                scope=scope,
                compiled=unfiltered,
                project_id=project.id,
                is_online=offline,
            )
            samples.append((time.perf_counter() - began) * 1000)
        results["work_counts"] = summarise(samples)

        # Phase B on its own: the in-process half of `derive_attention`. It reads a
        # registry rather than the database, so the card count should not reach it at
        # all — and a claim like that is worth a number rather than a sentence.
        reader = WorkRowReader(session)
        rows, runtime = await reader.for_project(project, is_online=offline)
        samples = []
        for _ in range(args.iterations):
            began = time.perf_counter()
            for row in rows:
                derive_attention(row, runtime)
            samples.append((time.perf_counter() - began) * 1000)
        results["derive_attention_phase_b"] = {**summarise(samples), "calls": len(rows)}

        # Payload bytes for one page of cards. **The budget this answers is per page, not
        # per project** — a page is 100 cards and the upstream row says 200, so 200 cards
        # are shaped here to keep the comparison against `work-item-bytes.json` honest.
        page = await work_items(
            session,
            scope=scope,
            compiled=unfiltered,
            project_id=project.id,
            group="lifecycle",
            is_online=offline,
        )
        derived = [item for group in page.groups for item in group.items][:200]
        body = json.dumps(
            [_card(item, None).model_dump(mode="json") for item in derived],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        results["work_item_payload"] = {
            "cards": len(derived),
            "bytes": len(body.encode("utf-8")),
            "baseline_bytes": 172758,
            "baseline_cards": 200,
            "baseline_from": "px/local/baseline/work-item-bytes.json",
        }

    async with maker() as session:
        conversation = ConversationService(session)
        fresh = await session.get(Task, task.id)
        user = (await session.execute(sa.select(User).limit(1))).scalar_one()

        await conversation.page(fresh, limit=50)
        samples = []
        for _ in range(args.iterations):
            began = time.perf_counter()
            await conversation.page(fresh, limit=50)
            samples.append((time.perf_counter() - began) * 1000)
        results["conversation_reopen"] = summarise(samples)

        samples = []
        for index in range(args.iterations):
            began = time.perf_counter()
            await conversation.post(
                task=fresh,
                body=f"量測 commit 第 {index} 則。",
                author_kind="user",
                author_user_id=user.id,
            )
            await session.commit()
            samples.append((time.perf_counter() - began) * 1000)
        results["message_commit"] = summarise(samples)

    async with maker() as session:
        search = KnowledgeSearch(session, project.id)
        relevance = []
        for query, _kind in QUERIES:
            await search.search(query, limit=20)
        samples = []
        for query, kind in QUERIES:
            hits = 0
            for _ in range(args.iterations):
                began = time.perf_counter()
                found = await search.search(query, limit=20)
                samples.append((time.perf_counter() - began) * 1000)
                hits = found.total
            relevance.append({"query": query, "kind": kind, "hits": hits})
        results["knowledge_search"] = summarise(samples)
        results["knowledge_relevance"] = relevance

        builder = ContextBuilder(session)
        fresh = await session.get(Task, task.id)
        await builder.build(fresh)
        samples = []
        for _ in range(args.iterations):
            began = time.perf_counter()
            await builder.build(fresh)
            samples.append((time.perf_counter() - began) * 1000)
        results["context_pack_build"] = summarise(samples)

        chunks = await session.scalar(sa.text("select count(*) from knowledge_chunks"))
        total_tasks = await session.scalar(sa.select(sa.func.count()).select_from(Task))

    await engine.dispose()

    table = []
    for key, (budget, milestone, label) in BUDGETS.items():
        measured = results[key]["p95_ms"]
        was, source = BASELINE[key]
        table.append(
            {
                "item": label,
                "milestone": milestone,
                "of_the_thirteen": key not in EXTRA,
                "budget_ms": budget,
                "p95_200_cards_ms": was,
                "p95_2000_cards_ms": measured,
                "ratio": round(measured / was, 2) if was else None,
                "verdict": "N/A" if budget is None else ("PASS" if measured < budget else "FAIL"),
                "baseline_from": f"artifacts/{source}",
            }
        )

    # The thirteenth row, in bytes. Kept in the same table so that "thirteen budgets" can
    # be counted from the artifact rather than taken on trust.
    bytes_row = results["work_item_payload"]
    table.append(
        {
            "item": "`WorkItemCardDTO` 200 張 payload",
            "milestone": "beta.1",
            "of_the_thirteen": True,
            "unit": "bytes",
            "budget_bytes": PAYLOAD_BUDGET_BYTES,
            "upstream_budget_bytes": PAYLOAD_UPSTREAM_BYTES,
            "upstream_budget_note": "D94 refused to copy it; see the constant's comment",
            "bytes_200_cards": bytes_row["baseline_bytes"],
            "bytes_2000_cards": bytes_row["bytes"],
            "ratio": round(bytes_row["bytes"] / bytes_row["baseline_bytes"], 2),
            "verdict": "PASS" if bytes_row["bytes"] < PAYLOAD_BUDGET_BYTES else "FAIL",
            "baseline_from": f"artifacts/{bytes_row['baseline_from']}",
        }
    )

    counted = sum(1 for row in table if row["of_the_thirteen"])
    document = {
        "commit": commit(),
        "database": args.url.rsplit("/", 1)[-1],
        "project_slug": args.project,
        "dataset": {
            "cards_in_project": cards,
            "cards_total": total_tasks,
            "knowledge_chunks": chunks,
            "deep_card_messages": DEEP_CARD_MESSAGES,
        },
        "iterations": args.iterations,
        # Counted rather than claimed: the two lists must account for all thirteen
        # budgets, and a table quietly holding twelve is the failure this guards.
        "thirteen_accounted_for": counted + len(NOT_REMEASURED),
        "measured": table,
        "not_remeasured": NOT_REMEASURED,
        "raw": results,
    }
    if counted + len(NOT_REMEASURED) != 13:
        print(
            f"accounting error: {counted} measured + {len(NOT_REMEASURED)} not re-weighed "
            f"= {counted + len(NOT_REMEASURED)}, not 13",
            file=sys.stderr,
        )
        return 2
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    width = max(len(row["item"]) for row in table)
    print(f"{'item'.ljust(width)}  {'200':>9}  {'2000':>9}  {'×':>6}  budget   verdict")
    for row in table:
        if row.get("unit") == "bytes":
            print(
                f"{row['item'].ljust(width)}  {row['bytes_200_cards'] / 1024:>7.1f}KB"
                f"  {row['bytes_2000_cards'] / 1024:>7.1f}KB  {row['ratio']:>6}"
                f"  {row['budget_bytes'] / 1024:>5.0f}KB   {row['verdict']}"
            )
            continue
        budget = "—" if row["budget_ms"] is None else f"{row['budget_ms']:.0f}ms"
        print(
            f"{row['item'].ljust(width)}  {row['p95_200_cards_ms']:>8.2f}ms"
            f"  {row['p95_2000_cards_ms']:>8.2f}ms  {str(row['ratio']):>6}"
            f"  {budget:>7}   {row['verdict']}"
        )
    failed = [row for row in table if row["verdict"] == "FAIL"]
    print(
        f"\n{counted} of the thirteen measured, {len(NOT_REMEASURED)} not re-weighed "
        f"(= 13), {len(table) - counted} extra, {len(failed)} over budget"
    )
    print(f"wrote {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
