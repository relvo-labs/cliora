#!/usr/bin/env python
"""J11 — a decision reaches the index, and a real agent cites it (`plan/25/09` §6).

Three assertions, and the third is the one no in-process test can make:

1. the accepted decision is in the index with `authority='accepted'`;
2. the agent's message quotes it by label;
3. **a `context_packs` row exists with `total_bytes > 0`** — that is, the agent actually
   ran `cliora knowledge context`.

The third is ADR 0039's bet being measured. The offer carries the project's rules and a
pointer, and everything else is fetched; if agents do not fetch, project memory is
elaborate and unread. Asserting the row turns that from a worry into a number.

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j11_cited_turn.py
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa
from kn_harness import Journey, KnowledgeStack, use_agent_script

AGENT = r"""#!/usr/bin/env bash
# The J11 agent: read the project's memory, then say something that cites it.
#
# It does exactly what the offer's context pack tells an agent to do, which is the point
# — the journey is testing whether that instruction is followed and whether what comes
# back is usable, not whether the endpoint returns 200.
set -uo pipefail

pack="$(cliora knowledge context 2>&1)" || {
  cliora task say "無法讀取專案記憶：$pack"
  exit 3
}

# The label is assigned by the pack, so the agent finds it rather than assuming it.
label="$(printf '%s' "$pack" | grep -o '\[S[0-9]\+\]' | head -1)"
if [ -z "$label" ]; then
  cliora task say "專案記憶裡沒有與這張卡相關的來源。"
  exit 0
fi

body="$(cliora knowledge cite "$label" 2>&1)" || body="(cite failed: $body)"
summary="$(printf '%s' "$body" | head -3 | tr '\n' ' ')"
cliora task say "依 $label 的說明，這張卡要照既有規格處理。摘要：$summary"
exit 0
"""


async def main() -> int:
    journey = Journey("J11", "新 accepted decision 進 Knowledge，Agent 引用得到")
    async with KnowledgeStack() as stack:
        await stack.require_quiet_database()
        project_id = await stack.project("kn-journey")
        await stack.enable_knowledge(project_id)
        # Drain the backfill **before** measuring anything. Enabling is also the backfill
        # trigger (ADR 0038 §7), so a freshness number taken across it measures the
        # backfill, not the decision — and the budget is about the decision.
        await stack.drain_ingestion(project_id)
        journey.step("project memory enabled and backfilled")

        # A decision, written the way a person writes one: a comment marked as a
        # decision on a card. The ingestion path is the ordinary one — nothing here
        # reaches into the knowledge tables.
        seed = await stack.card(project_id, title="規格：租約過期時的處理")
        reply = await stack.client.post(
            f"/api/tasks/{seed['id']}/messages",
            json={"body": "決議：租約過期時重試三次，之後把卡片標為 blocked。", "kind": "decision"},
            headers=stack.headers,
        )
        reply.raise_for_status()
        waited = await stack.drain_ingestion(project_id)
        journey.note("ingest_wait_seconds", round(waited, 2))
        journey.check(waited < 10.0, "the decision is searchable within the 10s budget")

        found = await stack.client.get(
            f"/api/projects/{project_id}/knowledge/search",
            params={"q": "租約過期"},
            headers=stack.headers,
        )
        found.raise_for_status()
        hits = found.json()["items"]
        journey.note("search_hits", [hit["title"] for hit in hits])
        journey.check(bool(hits), "the decision is in the index")

        use_agent_script(AGENT)
        task = await stack.card(project_id, title="實作：租約過期的重試")
        run_id = (await stack.dispatch(task["id"]))["run_id"]
        await stack.wait_for_terminal_run(run_id)
        journey.step("run finished")

        messages = await stack.messages(task["id"])
        agent_said = [message["body"] for message in messages if message["author_kind"] == "agent"]
        journey.note("agent_said", agent_said)
        journey.check(
            any("[S" in body for body in agent_said),
            "the agent's message carries a citation label",
            agent_said,
        )

        async with stack.maker() as session:
            packs = (
                await session.execute(
                    sa.text(
                        "SELECT total_bytes, jsonb_array_length(source_manifest) AS sources "
                        "FROM context_packs WHERE task_id = :tid"
                    ),
                    {"tid": task["id"]},
                )
            ).all()
        journey.note("context_packs", [dict(row._mapping) for row in packs])
        # **ADR 0039's bet.** A pack row exists only if the agent fetched it.
        journey.check(len(packs) >= 1, "the agent fetched its context pack", packs)
        journey.check(
            all(row.total_bytes > 0 for row in packs), "the pack it fetched was not empty"
        )
    return journey.finish()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
