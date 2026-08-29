#!/usr/bin/env python
"""The lifecycle a 0.12.0 node has to complete unchanged (`CE-09`, exit condition 16).

Driven by `scripts/cv/compat-0120.sh`, which built the old binary and enrolled it. This
half dispatches the work and reads the result, including the old daemon's log — because a
decode failure looks like "the card went blocked", not like an error.

The control card matters as much as the subject: run the same steps on the current node
and compare the columns. Without it, "the old node behaved like this" has nothing to be
*like*.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sqlalchemy as sa  # noqa: E402

from app.db.models import TaskRun  # noqa: E402
from harness import REPO, Journey, Stack, commit  # noqa: E402

OLD_RUNNER_ID = os.environ["CE_OLD_RUNNER_ID"]
OLD_LOG = Path(os.environ["CE_OLD_LOG"])
OLD_VERSION = os.environ.get("CE_OLD_VERSION", "unknown")
OLD_COMMIT = os.environ.get("CE_OLD_COMMIT", "f91d9c4")

#: What a decode failure leaves in a daemon's log. Broad on purpose: the exact wording
#: belongs to a version we are deliberately not editing.
DECODE_ERROR = re.compile(
    r"unknown message|decode|unmarshal|invalid frame", re.IGNORECASE
)


async def lifecycle(
    stack: Journey,
    s: Stack,
    project_id: str,
    *,
    labels: list[str],
    who: str,
    expect_finish: bool,
):
    """Dispatch, let the agent ask, answer, and see how far the node gets.

    `expect_finish` is not a convenience: it is the difference this whole script measures.
    The current node completes both rounds; a 0.12.0 node completes neither, and asserting
    that as a **negative** is what turns "we think it is compatible" into a record of
    exactly which half is.
    """
    card = await s.card(project_id, f"相容性：{who}")
    if labels:
        # `required_labels` is how the work is aimed at one node rather than raced for.
        async with s.maker() as session:
            await session.execute(
                sa.text("update tasks set required_labels = :labels where id = :id"),
                {"labels": json.dumps(labels), "id": uuid.UUID(card["id"])},
            )
            await session.commit()

    dispatched = await s.dispatch(card["id"])
    run_id = dispatched["run_id"]
    claimed = await s.wait_for_claim(run_id, 120.0)
    stack.check(
        claimed is not None,
        f"{who}: the run was claimed",
        dispatched.get("waiting_reason"),
    )
    if claimed is None:
        return None
    stack.check(
        str(claimed.runner_id) == OLD_RUNNER_ID
        if labels
        else str(claimed.runner_id) != OLD_RUNNER_ID,
        f"{who}: the intended node took it",
        str(claimed.runner_id),
    )

    question_id = await s.wait_for_open_question(card["id"], 120.0)
    stack.check(question_id is not None, f"{who}: the agent asked a question")
    if question_id is None:
        return None

    # The new semantics: the process ended and the card is still waiting. If `finish()`'s
    # derivation needed anything 0.13.0 added, this is where it would show — and it does
    # not. What shows instead is `CE-17`.
    #
    # The wait is short for the old node: the answer is already known, and sitting out a
    # three-minute lease teaches nothing.
    parent = await s.wait_for_terminal_run(run_id, 120.0 if expect_finish else 20.0)
    if expect_finish:
        stack.check(
            parent is not None
            and parent.status == "succeeded"
            and parent.result == "awaiting_input",
            f"{who}: the run ended as succeeded/awaiting_input (D59)",
            {
                "status": parent.status if parent else None,
                "result": parent.result if parent else None,
            },
        )
    else:
        # **The known negative, asserted as a negative.** 0.12.0 carries `CE-17`: its
        # `run.complete` sends `git_remotes: null`, Central drops the frame for failing
        # validation, and the run sits in `running` until its lease expires. Asserted
        # rather than skipped, and asserted *for this reason* — if a 0.12.0 node ever did
        # finish one of these, this check flips and somebody comes to look.
        stack.check(
            parent is None,
            f"{who}: cannot report that it finished — CE-17, still present here",
            {"status": parent.status if parent else None},
        )

    answered = await s.client.post(
        f"/api/tasks/{card['id']}/questions/{question_id}/answer",
        json={"body": "用第一版，其餘不變。", "resume": True},
        headers=s.headers,
    )
    stack.check(
        answered.status_code == 201,
        f"{who}: the answer was accepted",
        answered.status_code,
    )
    continuation_id = answered.json().get("continuation_run_id")
    stack.check(bool(continuation_id), f"{who}: a continuation was queued")
    if not continuation_id:
        return None

    child = await s.wait_for_claim(continuation_id, 120.0)
    stack.check(child is not None, f"{who}: the continuation was claimed")
    if child is not None and labels:
        stack.check(
            str(child.runner_id) == OLD_RUNNER_ID,
            f"{who}: and by the same old node",
            str(child.runner_id),
        )
    finished = await s.wait_for_terminal_run(
        continuation_id, 150.0 if expect_finish else 20.0
    )
    if expect_finish:
        stack.check(
            finished is not None and finished.status == "succeeded",
            f"{who}: the continuation finished successfully",
            finished.status if finished else None,
        )
    else:
        # The same defect, one round later. `lost` once the reaper reclaims the lease, or
        # still `running` when this looks — both mean "it never reported".
        stack.check(
            finished is None or finished.status in ("lost", "running"),
            f"{who}: the continuation also cannot report completion (CE-17)",
            finished.status if finished else "still running",
        )
    return {
        "card": card["card_ref"],
        "parent_result": parent.result if parent else None,
        "parent_status": parent.status if parent else "never finished",
        "continuation_status": finished.status if finished else "never finished",
    }


async def main() -> int:
    journey = Journey(
        "compat-0120", "an un-upgraded 0.12.0 node runs the whole lifecycle"
    )
    journey.note("old_version", OLD_VERSION)
    journey.note("old_commit", OLD_COMMIT)
    journey.note("new_version", (REPO / "daemon/VERSION").read_text().strip())
    journey.note("new_commit", commit())

    async with Stack() as stack:
        await stack.require_runner()
        # This runs last because the old node deliberately leaves work behind. A browser
        # journey immediately before it may still be finishing its successful retry,
        # though, and that process shares the mutable fake-agent script and current-node
        # capacity with the control leg below. Wait for *prior* execution to drain before
        # starting the old node's subject; otherwise a compatibility result is really a
        # measurement of the preceding journey's teardown race.
        async with stack.maker() as session:
            in_flight = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.status.in_(Stack.CONTENDING))
                )
            ).scalar_one()
        journey.note("runs_in_flight_at_start", in_flight)
        if in_flight:
            deadline = asyncio.get_running_loop().time() + 120.0
            remaining = in_flight
            while remaining and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.25)
                async with stack.maker() as session:
                    remaining = (
                        await session.execute(
                            sa.select(sa.func.count())
                            .select_from(TaskRun)
                            .where(TaskRun.status.in_(Stack.CONTENDING))
                        )
                    ).scalar_one()
            journey.note("runs_in_flight_after_drain", remaining)
            journey.check(
                remaining == 0,
                "prior journeys released execution capacity before compatibility",
                remaining,
            )
            if remaining:
                return journey.finish()
        project_id = await stack.project("cv-compat")

        journey.step("the subject: the 0.12.0 node")
        old = await lifecycle(
            journey,
            stack,
            project_id,
            labels=["compat-0120"],
            who="0.12.0",
            expect_finish=False,
        )
        journey.note("old_node", old)

        journey.step("the control: the current node")
        new = await lifecycle(
            journey, stack, project_id, labels=[], who="0.13.x", expect_finish=True
        )
        journey.note("new_node", new)

        # **What "compatible" turned out to mean.** Everything on the wire works: the old
        # node is offered the run, claims it, asks a question, is offered the continuation
        # and claims that too, and never fails to decode a frame. What it cannot do is
        # *report that it finished* — and that is not something V2-C1 broke. It is
        # `CE-17`, which 0.12.0 has carried since V2.2 and which no test ever reached,
        # because nothing had run a run to the end against a real daemon.
        #
        # So exit condition 16's honest answer is neither "identical" nor "broken by this
        # release". It is **"identical, including a defect only the upgrade fixes"**.
        journey.check(
            old is not None
            and new is not None
            and old["parent_status"] == "never finished"
            and new["parent_result"] == "awaiting_input",
            "the wire is compatible; completing a run is not (exit 16, restated)",
            {"old": old, "new": new},
        )

        # The log, not only the outcome. A dropped frame produces no error anywhere — the
        # card is claimed, the offer disappears, the lease expires, the card retries to
        # exhaustion and goes blocked, "and nothing anywhere mentions compatibility"
        # (contract 1.13.0's changelog).
        text = (
            OLD_LOG.read_text(encoding="utf-8", errors="replace")
            if OLD_LOG.exists()
            else ""
        )
        hits = [line for line in text.splitlines() if DECODE_ERROR.search(line)]
        journey.note("decode_errors", len(hits))
        journey.note("decode_error_lines", hits[:5])
        journey.check(not hits, "the old node logged no decode failure", len(hits))

        async with stack.maker() as session:
            claimed_by_old = (
                await session.execute(
                    sa.select(sa.func.count())
                    .select_from(TaskRun)
                    .where(TaskRun.runner_id == uuid.UUID(OLD_RUNNER_ID))
                )
            ).scalar_one()
        # Recorded, not asserted. The two per-round claim checks above already prove the
        # old node ran both, and this aggregate moves underneath them: the reaper reclaims
        # an expired lease and a retry is a **new row** (ADR 0029 §4), so the count
        # changes for reasons that have nothing to do with compatibility.
        journey.note("runs_still_attributed_to_the_old_node", claimed_by_old)

    verdict = journey.finish()

    # A second file, in the shape `plan/24/04` §6 asked for: the release note cites this
    # rather than a journey's check list.
    payload = {
        "old_binary": {"version": OLD_VERSION, "commit": OLD_COMMIT},
        "new_binary": {
            "version": (REPO / "daemon/VERSION").read_text().strip(),
            "commit": commit(),
        },
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit(),
        "decode_errors": len(hits),
        "exit_condition_16": "PASS" if verdict == 0 else "FAIL",
    }
    out = REPO / "artifacts/cv/local/compat-0120.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written to {out.relative_to(REPO)}")
    return verdict


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
