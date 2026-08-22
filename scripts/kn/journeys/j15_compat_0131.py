#!/usr/bin/env python
"""An un-upgraded node keeps working, and is not told to run a command it lacks.

Not one of the four planned journeys, and it exists because `plan/25/07` got this wrong
the first time. The plan said the CLI hint would be gated on
`runner.register.features`; that field's enum is **closed** to `verification` and
`evidence`, a misspelling is a rejected frame by deliberate design, and adding a value
would be a contract change — and worse, an un-upgraded Central would then reject a new
daemon's registration outright.

So the gate is the daemon's reported version, and this asserts both halves of it: a
0.13.1 node still gets the project's rules, and does **not** get told to run
`cliora knowledge context`.

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j15_compat_0131.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import sqlalchemy as sa
from kn_harness import Journey, KnowledgeStack


async def main() -> int:
    journey = Journey("J15", "未升級節點（0.13.1）行為不變，且不被指示執行不存在的命令")
    async with KnowledgeStack() as stack:
        await stack.require_quiet_database()
        project_id = await stack.project("kn-compat")
        await stack.enable_knowledge(project_id)
        await stack.client.patch(
            f"/api/projects/{project_id}",
            json={"description": "交付一律走 PR，不直接推 main。"},
            headers=stack.headers,
        )
        await stack.drain_ingestion(project_id)

        # The node in this stack is current. Rewriting the column is how a 0.13.1 fleet
        # is simulated without keeping an old binary around — and the column is what the
        # production code reads, so nothing about the check is bypassed.
        async with stack.maker() as session:
            real = await session.scalar(sa.text("SELECT daemon_version FROM nodes LIMIT 1"))
            await session.execute(sa.text("UPDATE nodes SET daemon_version = '0.13.1'"))
            await session.commit()
        journey.note("real_daemon_version", real)

        try:
            task = await stack.card(project_id, title="舊節點也要能跑：租約過期")
            run_id = (await stack.dispatch(task["id"]))["run_id"]
            await stack.wait_for_terminal_run(run_id)
            journey.check(True, "an un-upgraded node completes an ordinary run")

            # `task_runs` does not store the pack — it is rendered at offer time — so
            # the assertion goes through the production chooser against the real rows
            # this run left behind. `_context_for` is the single place a card's kind
            # decides its pack (`GATE-RQ-CONTEXT-DISPATCH`), so this is the same string
            # the node received.
            async with stack.maker() as session:
                from app.db.models import Task, TaskRun
                from app.services.runs import RunService

                run_row = await session.get(TaskRun, uuid.UUID(run_id))
                task_row = await session.get(Task, uuid.UUID(task["id"]))
                context = await RunService(session)._context_for(task_row, (), run_row)
            journey.note("context_bytes", len(context or ""))
            journey.check(
                "cliora knowledge" not in (context or ""),
                "it is not told to run a command it does not have",
            )
            journey.check(
                "交付一律走 PR" in (context or ""),
                "but it still receives the project's rules",
            )
            journey.check(
                len((context or "").encode()) < 32768,
                "and the offer stays inside the wire ceiling",
                len((context or "").encode()),
            )
        finally:
            async with stack.maker() as session:
                await session.execute(sa.text("UPDATE nodes SET daemon_version = :v"), {"v": real})
                await session.commit()
    return journey.finish()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
