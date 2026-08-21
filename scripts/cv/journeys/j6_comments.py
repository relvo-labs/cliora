#!/usr/bin/env python
"""**J6** — a comment does not wake an agent (exit condition 6).

There is already an integration test for this (`test_a_comment_does_not_wake_an_agent`).
It runs in one process against one session; this runs twenty writes over HTTP against a
live Central with a real runner polling beside it, and adds the two things the unit test
cannot express: the difference between `200` and `201` on a replayed idempotency key, and
D67's other half — a comment **does** close the question while the asking run is still up.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import Journey, Stack  # noqa: E402

COMMENTS = 20


async def main() -> int:
    journey = Journey("j6-comments", "twenty comments do not wake an agent")
    async with Stack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()

        # --- the agent asked and ended -------------------------------------
        journey.step("a card whose agent asked a question and then exited")
        project_id = await stack.project("cv-j6")
        task = await stack.card(project_id)
        await stack.waiting_parent(task["id"], project_id)
        question_id = await stack.open_question(task["id"])
        runs_before = await stack.count_runs(task["id"])

        journey.step(f"sending {COMMENTS} ordinary comments")
        key = f"cv-j6-{uuid.uuid4().hex[:8]}"
        replayed_status: list[int] = []
        for index in range(COMMENTS):
            # One of the twenty repeats the previous body **and** its key. The rest are
            # distinct: an idempotent write is the exception being tested, not the rule.
            body = "第 10 則" if index in (9, 10) else f"第 {index + 1} 則留言"
            payload = {"body": body, "kind": "comment"}
            if index in (9, 10):
                payload["idempotency_key"] = key
            reply = await stack.client.post(
                f"/api/tasks/{task['id']}/messages", json=payload, headers=stack.headers
            )
            if index in (9, 10):
                replayed_status.append(reply.status_code)
            else:
                assert reply.status_code == 201, reply.text

        journey.check(
            replayed_status == [201, 200],
            "the same key with the same body replays as 200, not a second 201",
            replayed_status,
        )

        messages = await stack.messages(task["id"])
        comments = [m for m in messages if m["kind"] == "comment"]
        journey.check(
            len(comments) == COMMENTS - 1,
            f"{COMMENTS} posts wrote {COMMENTS - 1} comments (one was a replay)",
            len(comments),
        )
        journey.check(
            await stack.count_runs(task["id"]) == runs_before,
            "not one new run was created",
            await stack.count_runs(task["id"]),
        )
        question = await stack.question_row(question_id)
        journey.check(
            question is not None and question.state == "open",
            "the question the ended run asked is still open",
            question.state if question else None,
        )
        card = await stack.task(task["id"])
        journey.check(
            card.get("waiting_for_actor") == "human",
            "the card still says it is waiting for a person",
            card.get("waiting_for_actor"),
        )
        journey.check(
            card.get("open_question_count") == 1,
            "the projection still counts one open question",
            card.get("open_question_count"),
        )
        seq = await stack.sequence(task["id"])
        journey.check(
            seq == list(range(1, len(seq) + 1)), "the sequence has no gaps", seq[-3:]
        )

        # --- the agent asked and is still polling (D67) ---------------------
        #
        # The run's state is staged rather than produced by an agent looping on
        # `cliora task wait`: what is being tested is Central's rule, and racing a
        # polling process would add flakiness to the setup rather than to the assertion.
        journey.step("the other half of D67: the asking run is still up")
        live_task = await stack.card(project_id, "釐清：還在輪詢的那一種")
        await stack.waiting_parent(live_task["id"], project_id, live=True)
        live_question_id = await stack.open_question(live_task["id"])
        live_runs_before = await stack.count_runs(live_task["id"])

        posted = await stack.client.post(
            f"/api/tasks/{live_task['id']}/messages",
            json={"body": "可以，照你說的做。", "kind": "comment"},
            headers=stack.headers,
        )
        journey.check(
            posted.status_code == 201, "the comment was written", posted.status_code
        )

        live_question = await stack.question_row(live_question_id)
        journey.check(
            live_question is not None and live_question.state == "answered",
            "a comment closes the question the *live* run is waiting on (D67)",
            live_question.state if live_question else None,
        )
        journey.check(
            await stack.count_runs(live_task["id"]) == live_runs_before,
            "and still creates no turn — 留言 is not 回覆並繼續",
        )
    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
