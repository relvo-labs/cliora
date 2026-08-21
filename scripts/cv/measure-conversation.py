#!/usr/bin/env python
"""The four `plan/23/08` §6 measurements that were never taken (`CE-10`).

    uv run --project backend python scripts/cv/measure-conversation.py

`plan/23/10` §5 measured the one that is an exit condition — answer → turn, P95 5.00s.
The other four have thresholds nobody had ever compared anything against:

    message commit P95            < 500ms
    conversation reopen P95       < 500ms   (the newest page of 50)
    cursor pagination P95         < 300ms   (pages of 200, depth 500)
    20 concurrent writes          no error, no gap in the sequence

**None of them is an exit condition**, and superintending that is the point of writing
them down: the reason to take them is that `beta.1` runs heavier queries against the same
tables, and a regression needs something to be a regression *from*
(`research/03/CHECKLIST` §0: measuring afterwards is meaningless).

Two guards before anything is timed, both learned the hard way (`plan/23/10` §5):

  * the dataset has to exist and name the commit it was built at — a number measured on
    an unknown shape gets quoted as if the shape were known;
  * no run may be in flight, or what gets measured is the queue.

Percentiles are nearest-rank. Interpolating would invent a number no request achieved.
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
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

import httpx  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import TaskMessage, TaskRun  # noqa: E402

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
ADMIN = os.environ.get("E2E_ADMIN_USER", "e2e-admin")
PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "e2e-admin-pw")

TARGETS = {
    "message_commit": 500,
    "conversation_reopen": 500,
    "cursor_page": 300,
}
SAMPLES = 100
CONCURRENT = 20


def commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def percentile(values: list[float], pct: float) -> float:
    """Nearest rank: a value some request actually took."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-pct * len(ordered) // 100))))
    return ordered[rank - 1]


def summarise(name: str, seconds: list[float]) -> dict:
    p95_ms = percentile(seconds, 95) * 1000
    target = TARGETS[name]
    return {
        "n": len(seconds),
        "median_ms": round(statistics.median(seconds) * 1000, 1),
        "p95_ms": round(p95_ms, 1),
        "max_ms": round(max(seconds) * 1000, 1),
        "target_ms": target,
        "verdict": "PASS" if p95_ms < target else "OVER",
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="artifacts/cv/local/dataset.json")
    parser.add_argument("--out", default="artifacts/cv/local/conversation-perf.json")
    args = parser.parse_args()

    dataset_path = REPO / args.dataset
    if not dataset_path.exists():
        print(
            f"no dataset at {args.dataset}. Build it first:\n"
            "  uv run --project backend python scripts/cv/seed-dataset.py",
            file=sys.stderr,
        )
        return 2
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if dataset.get("commit") != commit():
        # Refused rather than noted: the whole value of these four numbers is that a
        # later run can be compared with them, and that needs the shape to be known.
        print(
            f"the dataset was built at {str(dataset.get('commit'))[:7]}, not HEAD. "
            "Rebuild it so the numbers and the shape agree.",
            file=sys.stderr,
        )
        return 2

    url = os.environ["CLIORA_DATABASE_URL"]
    engine = create_async_engine(url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        in_flight = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(TaskRun)
                .where(
                    TaskRun.status.in_(
                        ["queued", "claimed", "running", "waiting_for_input"]
                    )
                )
            )
        ).scalar_one()
    if in_flight:
        print(
            f"{in_flight} run(s) in flight; they compete for the runner and these numbers "
            "would be of the queue rather than of the query.",
            file=sys.stderr,
        )
        await engine.dispose()
        return 2

    deep = dataset["deep_card_id"]
    results: dict[str, object] = {}

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        login = await client.post(
            "/api/auth/login", json={"username": ADMIN, "password": PASSWORD}
        )
        login.raise_for_status()
        headers = {"authorization": f"Bearer {login.json()['tokens']['access_token']}"}

        print(
            f"==> message commit ({SAMPLES} posts on a {dataset['deep_card_messages']}-message card)"
        )
        commits: list[float] = []
        for index in range(SAMPLES):
            started = time.monotonic()
            reply = await client.post(
                f"/api/tasks/{deep}/messages",
                json={"body": f"量測用的第 {index} 則留言。", "kind": "comment"},
                headers=headers,
            )
            reply.raise_for_status()
            commits.append(time.monotonic() - started)
        results["message_commit"] = summarise("message_commit", commits)

        print(f"==> conversation reopen ({SAMPLES} reads of the newest 50)")
        reopens: list[float] = []
        for _ in range(SAMPLES):
            started = time.monotonic()
            reply = await client.get(
                f"/api/tasks/{deep}/messages", params={"limit": 50}, headers=headers
            )
            reply.raise_for_status()
            reopens.append(time.monotonic() - started)
        results["conversation_reopen"] = summarise("conversation_reopen", reopens)

        print("==> cursor pagination (pages of 200, walked to the end, 100 times)")
        pages: list[float] = []
        for _ in range(SAMPLES):
            after = 0
            started = time.monotonic()
            while True:
                reply = await client.get(
                    f"/api/tasks/{deep}/messages",
                    params={"after_seq": after, "limit": 200},
                    headers=headers,
                )
                reply.raise_for_status()
                items = reply.json()["items"]
                if not items:
                    break
                after = items[-1]["conversation_seq"]
            pages.append(time.monotonic() - started)
        results["cursor_page"] = summarise("cursor_page", pages)

        print(f"==> {CONCURRENT} concurrent writes to one card")

        # A separate client each: one client would put them on one connection and
        # HTTP/1.1 would serialise them, which is not concurrency.
        async def write(index: int) -> int:
            async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as own:
                reply = await own.post(
                    f"/api/tasks/{deep}/messages",
                    json={"body": f"併發寫入 {index}", "kind": "comment"},
                    headers=headers,
                )
                return reply.status_code

        before = await _max_seq(maker, deep)
        started = time.monotonic()
        codes = await asyncio.gather(*(write(index) for index in range(CONCURRENT)))
        wall = time.monotonic() - started
        after = await _max_seq(maker, deep)
        gaps = await _gaps(maker, deep)
        results["concurrent_writes"] = {
            "n": CONCURRENT,
            "errors": sum(1 for code in codes if code != 201),
            "seq_before": before,
            "seq_after": after,
            "seq_advanced_by": after - before,
            "gaps": gaps,
            "wall_clock_ms": round(wall * 1000, 1),
            # A gap or an error here is **not** a performance result: it is the
            # numbering or the unique index failing, and it stops the closeout.
            "verdict": "PASS"
            if not gaps
            and after - before == CONCURRENT
            and all(c == 201 for c in codes)
            else "FAIL",
        }

    await engine.dispose()

    payload = {
        "commit": commit(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "seed": dataset["seed"],
            "tasks": dataset["tasks"],
            "deep_card_messages": dataset["deep_card_messages"],
            "counts": dataset["counts"],
        },
        "inflight_runs_at_start": in_flight,
        **results,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    for name in ("message_commit", "conversation_reopen", "cursor_page"):
        row = results[name]
        print(
            f"  {name:22} p95 {row['p95_ms']:8.1f}ms   target {row['target_ms']}ms   {row['verdict']}"
        )
    concurrent = results["concurrent_writes"]
    print(
        f"  {'concurrent_writes':22} {concurrent['errors']} error(s), "
        f"{len(concurrent['gaps'])} gap(s)   {concurrent['verdict']}"
    )
    print(f"\nwritten to {args.out}")
    # Only the concurrency result can fail the run: the three latency targets were never
    # exit conditions, and an over-target number is a fact to record, not a blocker
    # (`plan/24/05` §4).
    return 0 if concurrent["verdict"] == "PASS" else 1


async def _max_seq(maker, task_id: str) -> int:
    async with maker() as session:
        return (
            await session.execute(
                sa.select(
                    sa.func.coalesce(sa.func.max(TaskMessage.conversation_seq), 0)
                ).where(TaskMessage.task_id == task_id)
            )
        ).scalar_one()


async def _gaps(maker, task_id: str) -> list[int]:
    async with maker() as session:
        seqs = list(
            (
                await session.execute(
                    sa.select(TaskMessage.conversation_seq)
                    .where(TaskMessage.task_id == task_id)
                    .order_by(TaskMessage.conversation_seq)
                )
            )
            .scalars()
            .all()
        )
    return [n for n in range(1, (seqs[-1] if seqs else 0) + 1) if n not in set(seqs)]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
