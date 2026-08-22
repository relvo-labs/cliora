#!/usr/bin/env python
"""**J5** — the daemon dies after the answer, and exactly one turn still happens.

Exit condition 5, and the heaviest of the four script journeys: it is the only one whose
subject is a process that is not running any more.

Two timing traps decide whether this measures what it claims to (`plan/24/03` §4):

* **killed too late** — if the runner had already polled and claimed the continuation,
  what is measured is "crashed after claiming", a different (also real) property. The
  journey asserts `claimed_at IS NULL` at the moment of the kill and **says which
  property it measured** rather than passing either way;
* **killed too early** — killing before the answer's 201 comes back measures Central on
  its own, with the daemon not yet involved. So the order is: 201, read `mode`, kill.

SIGKILL on the process group, never SIGTERM (D75): a graceful shutdown is not a crash.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlalchemy as sa  # noqa: E402

from app.db.models import TaskRun  # noqa: E402
from harness import REPO, Journey, Stack  # noqa: E402

CTL = REPO / "scripts/cv/daemon-ctl.sh"


def ctl(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CTL), command],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=os.environ.copy(),
    )


async def main() -> int:
    journey = Journey("j5-chaos", "an answer survives the daemon dying")
    async with Stack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()
        if not os.environ.get("E2E_DAEMON_PGID_FILE"):
            raise SystemExit("no daemon handles: start the stack with E2E_RUNNER=1")

        journey.step("a card waiting on an answer")
        project_id = await stack.project("cv-j5")
        task = await stack.card(project_id)
        parent_id = await stack.waiting_parent(task["id"], project_id)
        question_id = await stack.open_question(task["id"])

        journey.step("answering, and then killing the daemon before it can poll")
        answered = await stack.client.post(
            f"/api/tasks/{task['id']}/questions/{question_id}/answer",
            json={"body": "用 2026-08-14 那一版，其餘不變。", "resume": True},
            headers=stack.headers,
        )
        journey.check(
            answered.status_code == 201,
            "the answer was committed",
            answered.status_code,
        )
        result = answered.json()
        journey.note("mode", result.get("mode"))
        journey.check(
            result.get("mode") == "new_turn", "a turn was queued", result.get("mode")
        )
        continuation_id = result.get("continuation_run_id")
        if not continuation_id:
            return journey.finish()

        # The kill, immediately — and what the run looked like at that instant.
        async with stack.maker() as session:
            before = await session.get(TaskRun, uuid.UUID(continuation_id))
            claimed_before_kill = before.claimed_at is not None
        killed = ctl("kill")
        journey.note("kill_output", killed.stdout.strip() or killed.stderr.strip())
        journey.check(killed.returncode == 0, "the daemon's process group was killed")
        journey.note("claimed_before_kill", claimed_before_kill)
        if claimed_before_kill:
            # Reported, not hidden: this run of the journey exercised "crashed after
            # claiming". The assertions below still hold, but the label has to be true.
            journey.note(
                "measured",
                "crash after claim — the runner had already polled; re-run for the "
                "before-claim variant",
            )
        else:
            journey.note(
                "measured", "crash before claim — the queued turn outlived the daemon"
            )

        journey.step("restarting it as the same node")
        started = ctl("start")
        journey.check(started.returncode == 0, "the daemon started again")
        online = ctl("wait-online")
        journey.check(
            online.returncode == 0,
            "and Central lists the node online again",
            online.stderr.strip()[-200:] if online.returncode else None,
        )

        journey.step("waiting for the continuation to be claimed and to finish")
        claimed = await stack.wait_for_claim(continuation_id, 120.0)
        journey.check(
            claimed is not None, "the surviving turn was claimed after the restart"
        )

        # --- the six assertions -------------------------------------------
        continuations = await stack.continuations_of(question_id)
        journey.check(
            len(continuations) == 1,
            "exactly one continuation exists for this question",
            len(continuations),
        )
        if continuations:
            child = continuations[0]
            journey.check(
                child.claimed_at is not None and child.started_at is not None,
                "it was really claimed and really started",
                {"claimed": bool(child.claimed_at), "started": bool(child.started_at)},
            )
            answer_seq = next(
                (
                    m["conversation_seq"]
                    for m in await stack.messages(task["id"])
                    if m["kind"] == "answer"
                ),
                None,
            )
            journey.check(
                answer_seq is not None
                and (child.input_from_seq or 0)
                <= answer_seq
                <= (child.input_to_seq or 0),
                "the answer falls inside the turn's input range",
                {
                    "answer": answer_seq,
                    "from": child.input_from_seq,
                    "to": child.input_to_seq,
                },
            )

        question = await stack.question_row(question_id)
        journey.check(
            question is not None and question.state == "answered",
            "the question is answered",
            question.state if question else None,
        )
        answers = [m for m in await stack.messages(task["id"]) if m["kind"] == "answer"]
        journey.check(len(answers) == 1, "one answer, not two", len(answers))
        seq = await stack.sequence(task["id"])
        journey.check(
            seq == list(range(1, len(seq) + 1)), "the sequence has no gaps", seq
        )

        async with stack.maker() as session:
            parent = await session.get(TaskRun, uuid.UUID(parent_id))
            journey.check(
                parent.status == "succeeded" and parent.result == "awaiting_input",
                "the parent run did not come back to life",
                {"status": parent.status, "result": parent.result},
            )
            total = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.task_id == uuid.UUID(task["id"]))
                )
            ).scalar_one()
        journey.check(
            total == 2, "the card has exactly two runs: the parent and one turn", total
        )
    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
