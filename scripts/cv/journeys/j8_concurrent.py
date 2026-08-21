#!/usr/bin/env python
"""**J8** — two people answer one question (exit condition 2).

The property is *at most one continuation per answer*, and the only way to test it is to
have two requests genuinely in flight at once. `asyncio.gather` rather than two awaits,
and two HTTP clients rather than one: the race window is the single-row CAS on
`task_questions`, which is measured in milliseconds, and a test that serialises its own
requests is green whether or not that CAS exists.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

from harness import BASE, Journey, Stack  # noqa: E402


async def main() -> int:
    journey = Journey("j8-concurrent", "two answers to one question produce one turn")
    async with Stack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()

        journey.step("a card with one open question")
        project_id = await stack.project("cv-j8")
        task = await stack.card(project_id)
        await stack.waiting_parent(task["id"], project_id)
        question_id = await stack.open_question(task["id"])
        url = f"/api/tasks/{task['id']}/questions/{question_id}/answer"

        async def answer(who: str) -> httpx.Response:
            # A separate client per caller: sharing one would put both requests on one
            # connection, and HTTP/1.1 would serialise them for us — which is the exact
            # thing being ruled out.
            async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
                return await client.post(
                    url,
                    json={"body": f"{who} 的答案", "resume": True},
                    headers=stack.headers,
                )

        journey.step("both answers, in flight at the same time")
        first, second = await asyncio.gather(answer("甲"), answer("乙"))
        codes = sorted([first.status_code, second.status_code])
        journey.note("status_codes", codes)
        journey.check(codes == [201, 409], "one 201 and one 409", codes)

        loser = first if first.status_code == 409 else second
        winner = first if first.status_code == 201 else second
        if loser.status_code == 409:
            error = loser.json().get("error", {})
            details = error.get("details") or {}
            journey.check(
                error.get("code") == "QUESTION_ALREADY_ANSWERED",
                "the refusal names the reason",
                error.get("code"),
            )
            # Recoverable means the loser can see what happened without a reload: who
            # answered and when, not just "no".
            journey.check(
                "answered_by" in details and "answered_at" in details,
                "and says who answered it, and when",
                sorted(details),
            )

        answers = [m for m in await stack.messages(task["id"]) if m["kind"] == "answer"]
        journey.check(len(answers) == 1, "exactly one answer was written", len(answers))
        expected = "甲 的答案" if winner is first else "乙 的答案"
        journey.check(
            bool(answers) and answers[0]["body"] == expected,
            "the stored answer is the one whose request got the 201",
            {"stored": answers[0]["body"] if answers else None, "expected": expected},
        )

        continuations = await stack.continuations_of(question_id)
        journey.check(
            len(continuations) == 1,
            "exactly one continuation exists (uq_task_runs_continuation)",
            len(continuations),
        )

        claimed = (
            await stack.wait_for_claim(str(continuations[0].id))
            if continuations
            else None
        )
        journey.check(claimed is not None, "and a runner claimed it")

        # The loser's words were not stored, and that is deliberate: an answer's body
        # belongs to the question it closed. The promise that a person's typing survives
        # a failure is the composer's localStorage draft, which J1a exercises in the
        # browser — two different guarantees that are easy to conflate. Recorded as a
        # note rather than a check: the count above already asserts it.
        journey.note("bodies", [m["body"] for m in await stack.messages(task["id"])])
    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
