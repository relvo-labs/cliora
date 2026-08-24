#!/usr/bin/env python
"""J4 — find it in My Work, answer it, and the next turn reads the answer.

The journey that proves the phase's *entrance* works, end to end, against a real daemon:

1. a card is waiting on a person, and **My Work finds it without naming a project**;
2. the same card carries the same `primary_attention` from three different endpoints
   (exit condition 35, here with a real registry rather than a fixture);
3. "reply and continue" creates a **new turn**, not a comment;
4. the continuation run **actually reads the answer** — the agent's own output quotes it,
   which is the only way to tell "the answer was stored" from "the answer was delivered";
5. and afterwards the card is **gone from My Work**, because the thing it was waiting for
   happened. Not because somebody marked it read — `GATE-PX-MYWORK-READS-STATE` is the
   static half of this claim and this is the live half.

Run: E2E_RUNNER=1 scripts/e2e/run-stack.sh \
       uv run --project backend python scripts/px/journeys/j4_my_work_answer.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from px_harness import (  # noqa: E402
    Journey,
    ReadModelStack,
    encode_filter,
    use_agent_script,
)

#: The answer a person types. Distinctive so that finding it in the agent's output is
#: evidence of delivery rather than a coincidence.
ANSWER = "用 v3 的驗收標準，並且只看 P0 那三條"

#: The agent for the continuation turn: print the context pack it was handed. That is
#: the whole assertion — a turn that ran but received nothing looks identical to one that
#: received the answer, unless the agent says what it read.
#:
#: **From `.cliora/context/task.md`, not from stdin.** The first version of this script
#: read stdin, and it printed nothing: the runtime shim consumes the pack itself (it is
#: what reports `context_bytes`), so by the time a child starts there is no stdin left.
#: The file is not a workaround — it *is* the delivered pack, written by
#: `runner.WriteContext` from the same `spec.Context` the shim was fed, and it is the
#: copy the CLI's own `cliora context show` reads. Both locations are tried because the
#: working directory is the run root for a card with no repository and the checkout
#: otherwise (`run_handlers.go`, `source.Kind == "none"`).
ECHO_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail
for candidate in .cliora/context/task.md ../.cliora/context/task.md; do
  if [ -r "$candidate" ]; then
    printf 'I read (%s): ' "$candidate"
    cat "$candidate"
    exit 0
  fi
done
echo 'NO CONTEXT PACK ON DISK' >&2
exit 1
"""


async def main() -> int:
    journey = Journey("j4", "My Work → answer and continue → the turn reads it")
    async with ReadModelStack() as stack:
        await stack.require_runner()
        await stack.require_quiet_database()

        journey.step("a card parked on a person's reply")
        project_id = await stack.project("px-j4")
        card = await stack.card(project_id, title="支援 SAML SSO 登入")
        parent_run = await stack.waiting_parent(card["id"], project_id, live=False)
        question_id = await stack.wait_for_open_question(card["id"], deadline=30.0)
        journey.check(
            question_id is not None, "the card has an open question", question_id
        )
        if question_id is None:
            return journey.finish()

        journey.step("My Work finds it without naming a project")
        mine = await stack.my_work_items(
            filter=encode_filter(
                {"field": "attention", "op": "eq", "value": "waiting_for_your_input"}
            ),
            limit=50,
        )
        # **By id, never by `card_ref`.** A reference is unique *per project* and My Work
        # is cross-project by definition — `TASK-1` exists in every project that has ever
        # had a card. The first version of this journey compared references and passed,
        # then failed on a re-run because an earlier J15 had left its own `TASK-1` waiting
        # in another project: a green that depended on the database being empty.
        ids = [item["id"] for group in mine["groups"] for item in group["items"]]
        journey.check(
            card["id"] in ids,
            "`/api/me/work-items` returns it with no project in the request",
            [item["card_ref"] for group in mine["groups"] for item in group["items"]],
        )

        journey.step("three endpoints, one answer (exit condition 35, live)")
        from_project = await stack.attention_of(project_id, card["id"])
        from_me = next(
            (
                item["primary_attention"]
                for group in mine["groups"]
                for item in group["items"]
                if item["id"] == card["id"]
            ),
            None,
        )
        counts = await stack.work_counts(project_id)
        journey.note("counts_by_attention", counts["by_attention"])
        journey.check(
            from_project == from_me == "waiting_for_your_input",
            "the project board and My Work agree about this card",
            {"project": from_project, "me": from_me},
        )
        journey.check(
            counts["by_attention"].get("waiting_for_your_input", 0) >= 1,
            "and the counts endpoint counts it",
            counts["by_attention"],
        )

        journey.step("reply and continue")
        use_agent_script(ECHO_SCRIPT)
        result = await stack.answer_and_continue(card["id"], question_id, ANSWER)
        journey.note("answer_result", result)
        journey.check(
            result.get("mode") in {"new_turn", "live_run"},
            "answering created a turn rather than only a comment",
            result.get("mode"),
        )
        journey.check(
            not result.get("refusal_code"),
            "the continuation was not refused",
            result.get("refusal_code"),
        )

        journey.step("the continuation reads the answer")
        continuations = await stack.continuations_of(question_id)
        journey.check(
            len(continuations) == 1,
            "exactly one continuation run, not two",
            len(continuations),
        )
        if continuations:
            child = continuations[0]
            journey.check(
                str(child.parent_run_id) == parent_run,
                "the continuation is a child of the run that asked",
                {"parent": str(child.parent_run_id), "expected": parent_run},
            )
            finished = await stack.wait_for_terminal_run(str(child.id), deadline=180.0)
            journey.check(finished is not None, "the continuation finished", finished)
            log = await stack.run_log(str(child.id))
            journey.note("continuation_log_bytes", len(log))
            journey.check(
                ANSWER in log,
                "**the agent's own output contains the answer** — it was delivered, not "
                "merely stored",
                log[-400:] if log else "",
            )
            # The turn number, from the same bytes. A continuation that was handed the
            # *first* turn's pack would still contain the card's title and objective and
            # would pass every assertion above except this one.
            journey.check(
                "第 2 輪" in log or "turn 2" in log.lower(),
                "and the pack is the continuation's, not a re-send of the first turn's",
                [line for line in log.splitlines() if "輪" in line][:3],
            )

        journey.step("and My Work no longer waits on it")

        async def stopped_waiting() -> object:
            current = await stack.attention_of(project_id, card["id"])
            return None if current == "waiting_for_your_input" else {"level": current}

        cleared = await stack.wait_for(
            stopped_waiting, 60.0, "the card to stop waiting"
        )
        journey.check(
            cleared is not None,
            "the card leaves the waiting state because the question closed — not "
            "because anybody marked anything read",
            await stack.attention_of(project_id, card["id"]),
        )
        after = await stack.my_work_items(
            filter=encode_filter(
                {"field": "attention", "op": "eq", "value": "waiting_for_your_input"}
            ),
            limit=50,
        )
        after_ids = [item["id"] for group in after["groups"] for item in group["items"]]
        journey.check(
            card["id"] not in after_ids,
            "and it is gone from My Work's waiting section",
            # The references are the readable half of the detail; the *assertion* is on
            # ids. Other projects' cards legitimately appear here — that is what "with no
            # project in the request" means — so listing them is information, not a fault.
            {
                "this_card": card["card_ref"],
                "others_still_waiting": [
                    item["card_ref"]
                    for group in after["groups"]
                    for item in group["items"]
                ],
            },
        )

    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
