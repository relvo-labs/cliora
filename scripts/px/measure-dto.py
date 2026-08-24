#!/usr/bin/env python
"""How many bytes a page of cards costs on the wire (PX-00 baseline, PX-25's D94 step).

    CLIORA_DATABASE_URL=… uv run --project backend python scripts/px/measure-dto.py

**Measure before pinning** ([D94](../../plan/26/01-decisions-and-governance.md)). The
upstream plan quoted 160 KB for `WorkItemCardDTO` and derived it from "a bit more than
twice 74 KB" — but 74 KB has not been the board's size since `plan/19`, which measured
89,251 bytes against a 90,000-byte budget. A budget derived from a stale number either
guards nothing or fires after the fields are already in use.

Two outputs:

* the **total** for 200 cards, which is what a budget test pins;
* the **per-field cost**, top five, which is what tells you which field to drop. At 200
  cards a field's key name alone is 200 copies of a string, so the answer is rarely the
  field you would have guessed.

This does not construct the response the way the route does — it builds the same DTO
from the same repository call. That is a deliberate seam: what is being measured is the
*schema plus the data*, and the route's job is only to fill it. `PX-28`'s OpenAPI
snapshot is what guards the route.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.api.http.schemas import BoardCardDTO  # noqa: E402
from app.db.models import Project  # noqa: E402
from app.services.tasks import TaskService  # noqa: E402

SEED_PROJECT_SLUG = "cv-dataset-20260819"


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def field_costs(payloads: list[dict[str, object]]) -> list[dict[str, object]]:
    """What each field costs across the whole page, key name included.

    `len(json.dumps({key: value}))` per row, summed. It double-counts the two braces per
    field, which is 2 bytes × 200 × 16 = 6.4 KB of overstatement spread evenly — and the
    point of this list is the *ranking*, which an even offset does not disturb.
    """
    totals: dict[str, int] = {}
    for payload in payloads:
        for key, value in payload.items():
            totals[key] = totals.get(key, 0) + len(
                json.dumps({key: value}, ensure_ascii=False, separators=(",", ":"))
            )
    return [
        {"field": key, "bytes": value}
        for key, value in sorted(totals.items(), key=lambda item: -item[1])
    ]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=SEED_PROJECT_SLUG)
    parser.add_argument(
        "--dto",
        choices=("board", "work"),
        default="board",
        help="board = the V1 BoardCardDTO; work = V2-P1's WorkItemCardDTO",
    )
    parser.add_argument(
        "--out", default="artifacts/px/local/baseline/board-card-bytes.json"
    )
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
        # Nothing connected, which is also what a fresh Central looks like. The waiting
        # reason is a short fixed enum either way, so this does not move the number.
        if args.dto == "work":
            return await _measure_work_items(session, project, args, engine)
        cards = await TaskService(session).board(project.id, is_online=lambda _: False)
        dtos = [
            BoardCardDTO(
                id=card.task.id,
                card_ref=card.task.card_ref,
                title=card.task.title,
                stage=card.task.stage,
                risk=card.task.risk,
                priority=card.task.priority,
                owner_user_id=card.task.owner_user_id,
                owner_name=card.owner_name,
                delivery=card.task.delivery,
                blocking_count=card.blocking_count,
                gates_approved_count=card.gates_approved_count,
                active_run_status=card.active_run_status,
                active_run_runner_name=card.active_run_runner_name,
                waiting_reason=card.waiting_reason,
                version=card.task.version,
                updated_at=card.task.updated_at,
            )
            for card in cards
        ]

    await engine.dispose()

    payloads = [json.loads(dto.model_dump_json()) for dto in dtos]
    body = json.dumps(payloads, ensure_ascii=False, separators=(",", ":"))
    payload = {
        "commit": commit(),
        "dto": "BoardCardDTO",
        "project_slug": args.project,
        "cards": len(dtos),
        "fields": len(BoardCardDTO.model_fields),
        "bytes": len(body.encode("utf-8")),
        "per_field_top5": field_costs(payloads)[:5],
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


async def _measure_work_items(session, project, args, engine) -> int:
    """`WorkItemCardDTO` × the project, with the per-field ranking (D94's first step).

    **Measured before the threshold is written, not after.** The upstream 160 KB came
    from doubling a 74 KB figure that `plan/19` had already made stale, and a budget
    derived from a stale number either guards nothing or fires once the fields are
    already in use.
    """
    from app.api.http.work import WorkItemCardDTO, _card
    from app.services.work.attention import derive_attention
    from app.services.work.items import DerivedItem
    from app.services.work.rows import WorkRowReader

    # The **unpaged** set: a page is capped at 100 per group, and what a size budget has
    # to bound is the whole project's worth of cards. Derived through the same reader the
    # endpoint uses, so the measurement is of the real shape.
    rows, runtime = await WorkRowReader(session).for_project(project)
    items = [
        DerivedItem(row=row, attention=derive_attention(row, runtime)) for row in rows
    ]
    payloads = [json.loads(_card(item, None).model_dump_json()) for item in items]
    body = json.dumps(payloads, ensure_ascii=False, separators=(",", ":"))
    measured = len(body.encode("utf-8"))
    await engine.dispose()

    payload = {
        "commit": commit(),
        "dto": "WorkItemCardDTO",
        "project_slug": args.project,
        "cards": len(payloads),
        "fields": len(WorkItemCardDTO.model_fields),
        "bytes": measured,
        # The threshold a pinned test should use: measurement + 15 %.
        "budget_bytes": int(measured * 1.15),
        "per_field_top5": field_costs(payloads)[:5],
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
