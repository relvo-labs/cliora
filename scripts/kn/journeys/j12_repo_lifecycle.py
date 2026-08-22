#!/usr/bin/env python
"""J12 — a repository document is updated, then deleted, and retrieval keeps up.

The sync runs **inside the run**, from a real `cliora knowledge sync` against a real git
checkout, because that is the only place it can run: Central has no git client and no
outbound connection it may use for this (ADR 0038 §3.4). So the agent script here makes a
repository, commits, syncs, deletes a file, commits again and syncs again — which is the
whole lifecycle in one run.

The half that matters is **when** the deletion lands: at manifest time, in call ①. The
content call may be cut short by a byte ceiling, and a repository whose deletions only
land when the upload happens to fit is one where "I deleted that document" is sometimes
true.

    E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j12_repo_lifecycle.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from kn_harness import Journey, KnowledgeStack, use_agent_script

AGENT = r"""#!/usr/bin/env bash
# The J12 agent: a repository's life, compressed into one run.
#
# `git init` in the run's own working directory rather than a checkout, because a
# `source: none` card has no checkout — and what is under test is the sync protocol, not
# the fetch. The commit ids are real, which is the part that matters: `source_version` is
# a commit and the manifest is compared against what Central already holds.
set -uo pipefail
git init -q .
git config user.email agent@example.invalid
git config user.name agent

mkdir -p docs
printf '這份文件說明卡片的生命週期。\n' > docs/lifecycle.md
printf '這份文件說明租約過期時的處理方式。\n' > docs/lease.md
git add -A && git commit -qm first

sync() { cliora knowledge sync --json 2>&1; }
first="$(sync)" || { cliora task say "first sync failed: $first"; exit 3; }

# The same content again, at a new commit. Content-addressed negotiation means this must
# cost zero uploads — the economy the whole protocol rests on.
git commit -q --allow-empty -m second
again="$(sync)" || { cliora task say "second sync failed: $again"; exit 3; }

git rm -q docs/lease.md && git commit -qm third
third="$(sync)" || { cliora task say "third sync failed: $third"; exit 3; }

cliora task say "sync1=$first"
cliora task say "sync2=$again"
cliora task say "sync3=$third"
exit 0
"""


async def main() -> int:
    journey = Journey("J12", "repo 文件更新與刪除之後，舊內容不再被檢索命中")
    async with KnowledgeStack() as stack:
        await stack.require_quiet_database()
        project_id = await stack.project("kn-journey")
        await stack.enable_knowledge(project_id)
        await stack.drain_ingestion(project_id)

        reply = await stack.client.post(
            f"/api/projects/{project_id}/repositories",
            json={
                "scheme": "https",
                "host": "github.com",
                "path": f"acme/{uuid.uuid4().hex[:8]}",
                "default_branch": "main",
            },
            headers=stack.headers,
        )
        reply.raise_for_status()
        repository_id = reply.json()["id"]

        use_agent_script(AGENT)
        task = await stack.card(project_id, title="同步這個 repo 的文件")
        # The card names no repository and does not need to: the project has exactly
        # one, so Central resolves it. An agent should not have to know a platform uuid
        # to describe the directory it is standing in.
        assert repository_id
        run_id = (await stack.dispatch(task["id"]))["run_id"]
        await stack.wait_for_terminal_run(run_id)
        journey.step("run finished")

        said = [m["body"] for m in await stack.messages(task["id"]) if m["author_kind"] == "agent"]
        journey.note("agent_said", said)
        joined = " ".join(said)
        journey.check(
            '"unchanged": 2' in joined or '"unchanged":2' in joined,
            "an unchanged repository uploaded nothing",
            said,
        )
        journey.check(
            '"removed": 1' in joined or '"removed":1' in joined,
            "the deleted path was tombstoned at manifest time",
            said,
        )

        async def search(query: str) -> list[str]:
            found = await stack.client.get(
                f"/api/projects/{project_id}/knowledge/search",
                params={"q": query},
                headers=stack.headers,
            )
            found.raise_for_status()
            return [item["title"] for item in found.json()["items"]]

        lease = await search("租約過期")
        life = await search("生命週期")
        journey.note("after_delete_lease", lease)
        journey.note("after_delete_lifecycle", life)
        journey.check(
            "docs/lease.md" not in lease, "the deleted document is gone from search", lease
        )
        journey.check("docs/lifecycle.md" in life, "the kept document is still findable", life)

        rows = await stack.client.get(
            f"/api/projects/{project_id}/knowledge/sources",
            params={"source_type": "repo_doc"},
            headers=stack.headers,
        )
        rows.raise_for_status()
        by_title = {row["title"]: row for row in rows.json()}
        journey.note("sources", {k: v["active"] for k, v in by_title.items()})
        journey.check(
            "docs/lease.md" not in by_title or not by_title["docs/lease.md"]["active"],
            "the tombstoned source is kept but inactive",
        )
    return journey.finish()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
