#!/usr/bin/env python
"""J14 — another project's memory is not merely hidden; it is not there.

The assertion people expect is "the results are empty". The one that matters is that the
**count** is zero too, and that the refusal is a 404: a non-zero total with an empty list
discloses that something exists, and a 403 confirms an id is real. Isolation answered by
filtering is isolation somebody can measure the shape of.

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j14_isolation.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from kn_harness import Journey, KnowledgeStack


async def main() -> int:
    journey = Journey("J14", "跨專案查詢全部拒絕，且 count 不洩漏")
    async with KnowledgeStack() as stack:
        await stack.require_quiet_database()

        secret_project = await stack.project("kn-secret")
        await stack.enable_knowledge(secret_project)
        card = await stack.card(secret_project, title="機密：租約過期的內部處理")
        await stack.client.post(
            f"/api/tasks/{card['id']}/messages",
            json={"body": "只有這個專案能看到的內容：租約過期時聯絡 X。", "kind": "comment"},
            headers=stack.headers,
        )
        await stack.drain_ingestion(secret_project)

        own = await stack.client.get(
            f"/api/projects/{secret_project}/knowledge/search",
            params={"q": "租約過期"},
            headers=stack.headers,
        )
        own.raise_for_status()
        journey.check(own.json()["total"] > 0, "the owning project can find its own content")

        other = await stack.project("kn-other")
        await stack.enable_knowledge(other)
        await stack.drain_ingestion(other)
        reply = await stack.client.get(
            f"/api/projects/{other}/knowledge/search",
            params={"q": "租約過期"},
            headers=stack.headers,
        )
        reply.raise_for_status()
        body = reply.json()
        journey.note("other_project_total", body["total"])
        journey.check(body["items"] == [], "another project sees no items")
        # The one that matters: a non-zero total with an empty list would disclose that
        # something is there.
        journey.check(body["total"] == 0, "and no count either", body["total"])

        # A project with memory switched off answers 404, not 403 — the status must not
        # say "this exists and is turned off".
        off = await stack.project("kn-off")
        refused = await stack.client.get(
            f"/api/projects/{off}/knowledge/search",
            params={"q": "租約過期"},
            headers=stack.headers,
        )
        journey.note("disabled_status", refused.status_code)
        journey.check(refused.status_code == 404, "a disabled project answers 404")
        journey.check(
            refused.json()["error"]["code"] == "KNOWLEDGE_DISABLED",
            "with a machine code that says which",
            refused.text,
        )

        # A source id from another project is a 404, not a 403.
        sources = await stack.client.get(
            f"/api/projects/{secret_project}/knowledge/sources",
            headers=stack.headers,
        )
        sources.raise_for_status()
        source_id = sources.json()[0]["source_id"]
        crossed = await stack.client.get(
            f"/api/projects/{other}/knowledge/sources/{source_id}/versions",
            headers=stack.headers,
        )
        journey.note("cross_project_status", crossed.status_code)
        journey.check(crossed.status_code == 404, "a cross-project source id answers 404")

        # And a source id that never existed answers the same way, so the two are
        # indistinguishable from outside.
        absent = await stack.client.get(
            f"/api/projects/{other}/knowledge/sources/{uuid.uuid4()}/versions",
            headers=stack.headers,
        )
        journey.check(
            absent.status_code == crossed.status_code,
            "an id that exists elsewhere and one that never existed are indistinguishable",
            (crossed.status_code, absent.status_code),
        )
    return journey.finish()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
