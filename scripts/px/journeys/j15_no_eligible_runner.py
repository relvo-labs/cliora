#!/usr/bin/env python
"""J15 — no eligible runner → the missing tag is named → fix it → the runner claims it.

This is the journey that proves attention's **second phase** is real. Levels 5 and 6 are
answered from an in-process dict rather than from a column (ADR 0029 §1), so every other
test of them is a test of a mock. Here a real daemon is polling, a real card asks for a tag
nothing carries, and the question is whether the screen says something a person can act on.

Three claims, and the middle one is the phase's:

1. a queued card no runner can take shows `no_eligible_runner` **through the read model** —
   not through a debug endpoint;
2. the console and the board agree about *why*, and the reason **names the missing tag**;
   "waiting for an available agent" is the wrong sentence when the truth is "no machine has
   `arm64`", and the difference decides whether somebody waits or fixes something;
3. removing the tag is enough — the same run is claimed, with no re-dispatch.

Run: E2E_RUNNER=1 scripts/e2e/run-stack.sh \
       uv run --project backend python scripts/px/journeys/j15_no_eligible_runner.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from px_harness import Journey, ReadModelStack, encode_filter  # noqa: E402

#: A tag no runner in the e2e stack carries. Chosen so that every candidate is rejected on
#: tag matching rather than on being offline — the expensive branch, and the one whose
#: message has something to say.
MISSING_TAG = "arm64"


async def main() -> int:
    journey = Journey("j15", "No eligible runner → named tag → fix → claimed")
    async with ReadModelStack() as stack:
        runner = await stack.require_runner()
        await stack.require_quiet_database()
        journey.note(
            "runner", {"name": runner.name, "labels": list(runner.labels or [])}
        )

        journey.step("a card that asks for a tag nothing carries")
        project_id = await stack.project("px-j15")
        card = await stack.card(project_id, title="在 arm64 上重建映像檔")
        await stack.set_labels(card["id"], [MISSING_TAG])
        dispatched = await stack.dispatch(card["id"])
        run_id = dispatched["run_id"]

        journey.step("the read model says why, without anybody opening a log")
        level = await stack.wait_for_attention(
            project_id, card["id"], "no_eligible_runner"
        )
        journey.check(
            level == "no_eligible_runner",
            "the board shows `no_eligible_runner` for a card no runner can take",
            level,
        )

        # The same answer, asked the way a filter asks it. This is what the quick filter
        # chip does, and it is the half that would silently return zero rows if phase B
        # were skipped.
        filtered = await stack.work_items(
            project_id,
            filter=encode_filter(
                {"field": "attention", "op": "eq", "value": "no_eligible_runner"}
            ),
            limit=50,
        )
        refs = [
            item["card_ref"] for group in filtered["groups"] for item in group["items"]
        ]
        journey.check(
            card["card_ref"] in refs,
            "filtering on `attention = no_eligible_runner` finds it",
            refs,
        )
        journey.check(
            filtered["runtime_signals_available"] is True,
            "the response says the registry was consulted, so an empty result would mean "
            "something",
            filtered["runtime_signals_available"],
        )

        journey.step("the console names the missing tag")
        # **From the dispatch response.** That is where the console gets it: the reason and
        # the missing tags travel with the dispatch, not on the run resource —
        # `TaskRunDTO.waiting_reason` is the flat kind and carries no tags. Worth knowing,
        # because a screen that only read the run would show "waiting" and nothing else.
        journey.note("dispatch", dispatched)
        journey.check(
            dispatched.get("waiting_reason") == "no_eligible_runner",
            "the console's diagnosis agrees with the board's",
            dispatched.get("waiting_reason"),
        )
        journey.check(
            MISSING_TAG in (dispatched.get("missing_tags") or []),
            f"the reason names `{MISSING_TAG}` rather than saying 'waiting'",
            dispatched.get("missing_tags"),
        )

        journey.step("remove the tag; the same run is claimed")
        await stack.set_labels(card["id"], [])
        claimed = await stack.wait_for_claim(run_id, deadline=90.0)
        journey.check(
            claimed is not None,
            "the runner claims the run once the card stops asking for the tag",
            None if claimed is None else str(claimed.claimed_at),
        )
        journey.check(
            await stack.count_runs(card["id"]) == 1,
            "one run, not two — fixing the card did not need a re-dispatch",
            await stack.count_runs(card["id"]),
        )

        journey.step("and the attention clears")
        cleared = await stack.wait_for_attention(project_id, card["id"], None, 60.0)
        journey.check(
            cleared is None,
            "the board stops saying `no_eligible_runner` once it is claimed",
            cleared,
        )

    return journey.finish()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
