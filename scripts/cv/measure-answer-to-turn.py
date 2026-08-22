#!/usr/bin/env python
"""Exit condition 1 of `v2.0.0-alpha.2`: **answer → the next turn starts, P95 < 10s.**

    scripts/cv/measure-answer-to-turn.py [--samples N] [--out FILE]

Run it *inside* the e2e stack with runner mode on, which is where a real daemon is
polling for work:

    CLIORA_DATABASE_URL=... E2E_RUNNER=1 scripts/e2e/run-stack.sh \\
      uv run --project backend python scripts/cv/measure-answer-to-turn.py

**The number is recorded in three segments, not as one figure** (`plan/23/08` §6), and
that is the whole reason this script exists rather than a stopwatch:

    answer commit  →  the runner's next poll   0–5s, and it is the poll interval
    poll           →  claim                    Central's dispatch path
    claim          →  the child process starts  the runtime, not the platform

A single P95 over ten seconds cannot tell you which of those to fix, and the three have
three different owners. If the first segment dominates, that is **evidence for D44** —
the phase's decision to leave the contract alone and let continuations ride the
existing 5-second `runner.poll` — and not a Central performance problem.

## What is real here and what is staged

The measured interval is real: a person's answer goes in over HTTP, and the clock stops
on columns the **real** daemon wrote (`claimed_at`, `started_at`) after it polled
Central over its own websocket and launched a child process.

What is staged is everything *before* the answer: the parent run and its open question
are written directly, rather than by dispatching a card and racing to ask a question
from inside it before the process exits. That race would only add flakiness to the
setup — it is not on the interval being measured, and a continuation neither knows nor
cares how its parent came to be waiting.

The runtime is `fakecli`, so segment three measures **this stack's** process launch and
nothing about Claude or Codex. It is reported separately for exactly that reason.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import httpx  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import AgentRunner, Task, TaskRun  # noqa: E402
from app.services.conversation import ConversationService  # noqa: E402

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")
ADMIN = os.environ.get("E2E_ADMIN_USER", "e2e-admin")
PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "e2e-admin-pw")
DB_URL = os.environ["CLIORA_DATABASE_URL"]

# The deadline for a continuation to be claimed. Generous against the 5s poll: what a
# timeout here means is "the runner never took it", which is a failure of a different
# kind from a slow one and is reported as such.
CLAIM_DEADLINE = 60.0


def _p(values: list[float], pct: float) -> float:
    """Percentile by nearest rank — the value some sample actually had.

    Interpolating would invent a number no run produced, and with twenty samples the
    honest answer to "what is the 95th" is "the second worst one".
    """
    if not values:
        return float("nan")
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-pct * len(ordered) // 100))))
    return ordered[rank - 1]


async def _login(client: httpx.AsyncClient) -> dict[str, str]:
    reply = await client.post(
        "/api/auth/login", json={"username": ADMIN, "password": PASSWORD}
    )
    reply.raise_for_status()
    return {"authorization": f"Bearer {reply.json()['tokens']['access_token']}"}


async def _project(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    name = f"cv-perf-{uuid.uuid4().hex[:8]}"
    reply = await client.post(
        "/api/projects", json={"name": name, "slug": name}, headers=headers
    )
    reply.raise_for_status()
    return reply.json()["id"]


async def _card(
    client: httpx.AsyncClient, headers: dict[str, str], project_id: str
) -> dict:
    """A card an agent needs no repository for: `source: none`, `delivery: none`."""
    reply = await client.post(
        f"/api/projects/{project_id}/tasks",
        json={
            "title": "釐清：這一輪的驗收標準",
            "source": "none",
            "delivery": "none",
            "card_kind": "clarification",
        },
        headers=headers,
    )
    reply.raise_for_status()
    task = reply.json()["task"]
    if task["stage"] != "ready":
        moved = await client.patch(
            f"/api/tasks/{task['id']}",
            json={"stage": "ready", "version": task["version"]},
            headers=headers,
        )
        moved.raise_for_status()
        task = moved.json()["task"]
    return task


async def _waiting_parent(
    maker, task_id: str, project_id: str, runner_id: uuid.UUID
) -> str:
    """A finished run that left an open question — the state D59 made possible.

    `status='succeeded'` with `result='awaiting_input'` is precisely what `finish()`
    derives when a completing run has an unanswered question, so this is the shape the
    resume path meets in production and not a convenience.
    """
    async with maker() as session:
        task = await session.get(Task, uuid.UUID(task_id))
        run = TaskRun(
            id=uuid.uuid4(),
            task_id=uuid.UUID(task_id),
            project_id=uuid.UUID(project_id),
            seq=1,
            status="succeeded",
            result="awaiting_input",
            runner_id=runner_id,
            source_kind="none",
            input_from_seq=0,
            input_to_seq=0,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.flush()
        run.root_run_id = run.id
        await ConversationService(session).post(
            task=task,
            body="要我用哪一版的驗收標準？",
            kind="question",
            author_kind="agent",
            author_runner_id=runner_id,
            run_id=run.id,
        )
        await session.commit()
        return str(run.id)


async def _open_question(
    client: httpx.AsyncClient, headers: dict[str, str], task_id: str
) -> str:
    reply = await client.get(f"/api/tasks/{task_id}/questions", headers=headers)
    reply.raise_for_status()
    return next(q["id"] for q in reply.json() if q["state"] == "open")


async def _sample(
    client, headers, maker, project_id: str, runner_id: uuid.UUID
) -> dict:
    task = await _card(client, headers, project_id)
    await _waiting_parent(maker, task["id"], project_id, runner_id)
    question_id = await _open_question(client, headers, task["id"])

    answered_at = time.monotonic()
    reply = await client.post(
        f"/api/tasks/{task['id']}/questions/{question_id}/answer",
        json={"body": "用 2026-08-14 那一版，其餘不變。"},
        headers=headers,
    )
    reply.raise_for_status()
    result = reply.json()
    committed = time.monotonic() - answered_at
    if result["mode"] != "new_turn":
        return {"error": f"mode={result['mode']} refusal={result.get('refusal_code')}"}

    child_id = uuid.UUID(result["continuation_run_id"])
    claimed = started = None
    deadline = time.monotonic() + CLAIM_DEADLINE
    while time.monotonic() < deadline:
        async with maker() as session:
            child = await session.get(TaskRun, child_id)
            claimed = child.claimed_at
            started = child.started_at
            queued = child.queued_at
        if claimed is not None and started is not None:
            break
        await asyncio.sleep(0.05)
    if claimed is None:
        return {"error": "the runner never claimed the continuation"}

    # The wall clock of the *database* is what these columns are in, so the segments
    # come from differences between them, and only the first one is anchored to the
    # request. Mixing the two clocks for a single figure would be wrong by whatever
    # the offset is; keeping them separate costs nothing.
    return {
        "commit_seconds": committed,
        "queue_to_claim": (claimed - queued).total_seconds(),
        "claim_to_start": (started - claimed).total_seconds() if started else None,
        "answer_to_start": committed + (started - queued).total_seconds()
        if started
        else None,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--out", default="artifacts/cv/local/answer-to-turn.json")
    args = parser.parse_args()

    engine = create_async_engine(DB_URL, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
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
        print("no enabled runner: start the stack with E2E_RUNNER=1", file=sys.stderr)
        return 2

    # **A queue that is not empty measures contention, not latency.** The runner has a
    # small `max_concurrent`, and a run left over from an earlier round takes a slot —
    # which shows up as a sample four to ten poll intervals long and looks exactly like
    # a platform that is sometimes slow. Measured on 2026-08-19: a second round against
    # a database still holding the first round's runs put the first sample at 48s.
    # Refused rather than reported, because the resulting number would be quoted.
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
            f"{in_flight} run(s) are still in flight in this database. They will compete "
            "for the runner's slots and the measurement would be of the queue, not of the "
            "answer path. Use an empty database:\n"
            "  dropdb cliora_e2e && createdb cliora_e2e",
            file=sys.stderr,
        )
        return 2

    samples: list[dict] = []
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        headers = await _login(client)
        project_id = await _project(client, headers)
        for index in range(args.samples):
            sample = await _sample(client, headers, maker, project_id, runner.id)
            samples.append(sample)
            note = sample.get("error") or f"{sample['answer_to_start']:.2f}s"
            print(f"  [{index + 1}/{args.samples}] {note}", flush=True)
    await engine.dispose()

    good = [s for s in samples if "error" not in s and s["answer_to_start"] is not None]
    failed = [s for s in samples if "error" in s]
    if not good:
        print("every sample failed", file=sys.stderr)
        for sample in failed:
            print(f"  {sample['error']}", file=sys.stderr)
        return 1

    def stat(key: str) -> dict[str, float]:
        values = [s[key] for s in good if s.get(key) is not None]
        return {
            "median": statistics.median(values),
            "p95": _p(values, 95),
            "max": max(values),
        }

    report = {
        "samples": len(samples),
        "usable": len(good),
        "failed": [s["error"] for s in failed],
        "runtime": "fakecli (segment three is this stack's, not an agent's)",
        "segments": {
            "answer_commit": stat("commit_seconds"),
            "queued_to_claimed": stat("queue_to_claim"),
            "claimed_to_started": stat("claim_to_start"),
        },
        "answer_to_turn_start": stat("answer_to_start"),
    }
    verdict = report["answer_to_turn_start"]["p95"] < 10.0
    report["exit_condition_1"] = "PASS" if verdict else "FAIL"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    print()
    print(
        f"answer → turn start   P95 {report['answer_to_turn_start']['p95']:.2f}s "
        f"(median {report['answer_to_turn_start']['median']:.2f}s, "
        f"n={len(good)}/{len(samples)})"
    )
    for name, value in report["segments"].items():
        print(f"  {name:<20} median {value['median']:.3f}s  p95 {value['p95']:.3f}s")
    print(f"\nexit condition 1 (P95 < 10s): {report['exit_condition_1']}  → {out}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
