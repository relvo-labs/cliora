#!/usr/bin/env python
"""J14 — another project's memory, including provider rows, is not there.

The assertion people expect is "the results are empty". The one that matters is that the
**count** is zero too, and that the refusal is a 404: a non-zero total with an empty list
discloses that something exists, and a 403 confirms an id is real. Isolation answered by
filtering is isolation somebody can measure the shape of.

Both provider source families are seeded through their production handlers/store and
checked separately for item, count and id isolation. The network reader is not part of
this boundary and remains real-provider evidence owned by J17/J18.

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j14_isolation.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from kn_harness import Journey, KnowledgeStack

from app.clock import now_utc
from app.db.models import Project, ProjectRepository
from app.services.knowledge import provider_sources
from app.services.knowledge.store import KnowledgeStore

PR_NEEDLE = "provider-pr-isolation-needle"
RELEASE_NEEDLE = "provider-release-isolation-needle"


async def main() -> int:
    journey = Journey("J14", "跨專案查詢全部拒絕，且 count 不洩漏")
    async with KnowledgeStack() as stack:
        await stack.require_quiet_database()

        secret_project = await stack.project("kn-secret")
        await stack.enable_knowledge(secret_project)
        card = await stack.card(secret_project, title="機密：租約過期的內部處理")
        await stack.client.post(
            f"/api/tasks/{card['id']}/messages",
            json={
                "body": "只有這個專案能看到的內容：租約過期時聯絡 X。",
                "kind": "comment",
            },
            headers=stack.headers,
        )
        # The beta.2 extension: seed both provider source families through their real
        # handlers and the common store. The network transport remains J17's concern;
        # this journey isolates the rows that SR-4 items 7 and 8 inherit.
        async with stack.maker() as session:
            project = await session.get(Project, uuid.UUID(secret_project))
            assert project is not None
            repository = ProjectRepository(
                id=uuid.uuid4(),
                project_id=project.id,
                scheme="https",
                host="github.com",
                path="acme/provider-isolation",
                default_branch="main",
                created_by=project.owner_user_id,
            )
            session.add(repository)
            await session.flush()
            timestamp = now_utc()
            store = KnowledgeStore(session)
            provider_ids = []
            provider_ids.append(
                (
                    await store.upsert(
                        project_id=project.id,
                        source_type="pull_request",
                        source=provider_sources.pull_request_source(
                            repository=repository,
                            number=14,
                            title="Provider isolation PR",
                            body=f"Only the owning project may find {PR_NEEDLE}.",
                            state="closed",
                            merged=True,
                            merged_at=timestamp,
                            head_ref="cliora/HD-14",
                            base_ref="main",
                            url="https://github.com/acme/provider-isolation/pull/14",
                            updated_at=timestamp,
                        ),
                    )
                ).source_id
            )
            provider_ids.append(
                (
                    await store.upsert(
                        project_id=project.id,
                        source_type="release",
                        source=provider_sources.published_version_source(
                            repository=repository,
                            tag="v2.0.0-beta.2",
                            name="Provider isolation release",
                            body=f"Only the owning project may find {RELEASE_NEEDLE}.",
                            published_at=timestamp,
                            prerelease=True,
                            url=(
                                "https://github.com/acme/provider-isolation/"
                                "releases/tag/v2.0.0-beta.2"
                            ),
                        ),
                    )
                ).source_id
            )
            await session.commit()
        await stack.drain_ingestion(secret_project)

        own = await stack.client.get(
            f"/api/projects/{secret_project}/knowledge/search",
            params={"q": "租約過期"},
            headers=stack.headers,
        )
        own.raise_for_status()
        journey.check(
            own.json()["total"] > 0, "the owning project can find its own content"
        )

        for source_type, needle in (
            ("pull_request", PR_NEEDLE),
            ("release", RELEASE_NEEDLE),
        ):
            provider_own = await stack.client.get(
                f"/api/projects/{secret_project}/knowledge/search",
                params={"q": needle, "source_type": source_type},
                headers=stack.headers,
            )
            provider_own.raise_for_status()
            journey.check(
                provider_own.json()["total"] == 1,
                f"the owning project finds its {source_type} source",
                provider_own.json(),
            )

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

        for source_type, needle in (
            ("pull_request", PR_NEEDLE),
            ("release", RELEASE_NEEDLE),
        ):
            provider_other = await stack.client.get(
                f"/api/projects/{other}/knowledge/search",
                params={"q": needle, "source_type": source_type},
                headers=stack.headers,
            )
            provider_other.raise_for_status()
            leaked = provider_other.json()
            journey.check(
                leaked["items"] == [] and leaked["total"] == 0,
                f"another project sees neither {source_type} rows nor their count",
                leaked,
            )

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
        # Use a provider id specifically; the old journey happened to use whichever
        # source sorted first and therefore did not exercise either new family.
        source_id = str(provider_ids[0])
        crossed = await stack.client.get(
            f"/api/projects/{other}/knowledge/sources/{source_id}/versions",
            headers=stack.headers,
        )
        journey.note("cross_project_status", crossed.status_code)
        journey.check(
            crossed.status_code == 404, "a cross-project source id answers 404"
        )

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
