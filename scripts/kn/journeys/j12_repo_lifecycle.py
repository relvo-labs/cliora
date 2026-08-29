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

    CLIORA_GIT_ALLOWED_HOSTS='["github.com"]' E2E_RUNNER=1 scripts/e2e/run-stack.sh \
      uv run --project backend python scripts/kn/journeys/j12_repo_lifecycle.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import sqlalchemy as sa

from kn_harness import Journey, KnowledgeStack, use_agent_script

from app.db.models import KnowledgeChunk, KnowledgeSource, Project, ProjectRepository
from app.services.knowledge import provider_sync
from app.services.secrets import SecretService
from app.settings import Settings

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

PROVIDER_AGENT = r"""#!/usr/bin/env bash
set -uo pipefail
pack="$(cliora knowledge context 2>&1)" || {
  cliora task say "release context failed: $pack"
  exit 3
}
label="$(printf '%s' "$pack" | awk '
  /^## \[S[0-9]+\]/ { label=$2 }
  /來源類型：release/ { print label; exit }
')"
[ -n "$label" ] || { cliora task say "release label missing"; exit 3; }
cliora task say "release-ready $label"

# The journey removes the release from its controlled provider while this run sleeps.
sleep 6
# Labels are deliberately pack-local and the ready message above becomes new knowledge,
# so use the source id retained from that original manifest for the later citation.
cited="$(cliora knowledge cite "__SOURCE_ID__" 2>&1)"
status=$?
cliora task say "release-cite-status=$status $cited"
[ "$status" -ne 0 ] && printf '%s' "$cited" | grep -q 'no longer exists'
"""


class _ProviderFixture(ThreadingHTTPServer):
    """A controlled upstream reached through the production GitHub HTTP reader."""

    releases: list[dict[str, object]]
    calls: list[str]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _ProviderHandler)
        self.releases = []
        self.calls = []


class _ProviderHandler(BaseHTTPRequestHandler):
    server: _ProviderFixture

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlsplit(self.path).path
        self.server.calls.append(path)
        payload = self.server.releases if path.endswith("/releases") else []
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


async def _provider_release_lifecycle(
    stack: KnowledgeStack,
    journey: Journey,
    *,
    project_id: str,
    repository_id: str,
) -> None:
    fixture = _ProviderFixture()
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    try:
        port = fixture.server_address[1]
        settings = Settings(
            provider_api_base=f"http://127.0.0.1:{port}",
            provider_api_hosts=["127.0.0.1"],
        )
        published_at = datetime.now(UTC).replace(microsecond=0)
        fixture.releases = [
            {
                "tag_name": "v2.0.0-beta.2-fixture",
                "name": "Provider lifecycle fixture",
                "body": "這份 release 曾經發布，之後被撤下；引用文字必須保留。",
                "draft": False,
                "prerelease": True,
                "published_at": published_at.isoformat().replace("+00:00", "Z"),
                "html_url": "https://example.invalid/releases/v2.0.0-beta.2-fixture",
            }
        ]

        async with stack.maker() as session:
            project = await session.get(Project, uuid.UUID(project_id))
            repository = await session.get(ProjectRepository, uuid.UUID(repository_id))
            assert project is not None and repository is not None
            project.provider_sync_enabled = True
            secret = await SecretService(session, settings=settings).create(
                project=project,
                name="J12_PROVIDER_TOKEN",
                kind="provider_token",
                value="fixture-token-never-leaves-localhost",
                actor_id=project.owner_user_id,
            )
            repository.provider_token_secret_id = secret.id
            first = await provider_sync.sync_project(
                session, project_id=project.id, settings=settings
            )
            source = (
                await session.execute(
                    sa.select(KnowledgeSource).where(
                        KnowledgeSource.project_id == project.id,
                        KnowledgeSource.source_type == "release",
                        KnowledgeSource.source_external_id.endswith(
                            ":ver:v2.0.0-beta.2-fixture"
                        ),
                    )
                )
            ).scalar_one()
            original = (
                await session.execute(
                    sa.select(KnowledgeChunk.content).where(
                        KnowledgeChunk.source_id == source.id
                    )
                )
            ).scalar_one()
            await session.commit()
            source_id = source.id

        journey.check(
            first.sources == 1 and fixture.calls,
            "release 經本番 GitHubReader 的 HTTP GET 進入 knowledge",
            {"sources": first.sources, "calls": fixture.calls.copy()},
        )

        use_agent_script(PROVIDER_AGENT.replace("__SOURCE_ID__", str(source_id)))
        task = await stack.card(project_id, title="引用即將撤下的 release")
        pinned = await stack.client.post(
            f"/api/projects/{project_id}/knowledge/pins",
            json={
                "task_id": task["id"],
                "source_id": str(source_id),
                "mode": "pin",
            },
            headers=stack.headers,
        )
        pinned.raise_for_status()
        run_id = (await stack.dispatch(task["id"]))["run_id"]

        async def release_is_cited() -> bool:
            return any(
                "release-ready [S" in message["body"]
                for message in await stack.messages(task["id"])
                if message["author_kind"] == "agent"
            )

        ready = await stack.wait_for(
            release_is_cited, 30.0, "the agent to capture the release citation"
        )
        journey.check(bool(ready), "Agent 在刪除前取得 release citation label")

        fixture.releases = []
        async with stack.maker() as session:
            repository = await session.get(ProjectRepository, uuid.UUID(repository_id))
            assert repository is not None
            repository.provider_synced_at = None
            second = await provider_sync.sync_project(
                session, project_id=uuid.UUID(project_id), settings=settings
            )
            await session.commit()
        finished = await stack.wait_for_terminal_run(run_id)
        said = [
            message["body"]
            for message in await stack.messages(task["id"])
            if message["author_kind"] == "agent"
        ]
        journey.check(
            finished is not None
            and any(
                "release-cite-status=" in body and "no longer exists" in body
                for body in said
            ),
            "同一個 citation 在 upstream 刪除後明說 no longer exists",
            said,
        )

        async with stack.maker() as session:
            source = await session.get(KnowledgeSource, source_id)
            chunks = (
                (
                    await session.execute(
                        sa.select(KnowledgeChunk).where(
                            KnowledgeChunk.source_id == source_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert source is not None
            journey.check(
                second.repositories == 1
                and source.deleted_at is not None
                and not source.active
                and chunks
                and all(chunk.valid_to is not None for chunk in chunks)
                and any(chunk.content == original for chunk in chunks),
                "release tombstone 保留原文，但退出預設檢索",
                {
                    "deleted_at": source.deleted_at.isoformat()
                    if source.deleted_at
                    else None,
                    "active": source.active,
                    "chunks": len(chunks),
                    "provider_gets": len(fixture.calls),
                },
            )
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)


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

        said = [
            m["body"]
            for m in await stack.messages(task["id"])
            if m["author_kind"] == "agent"
        ]
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
            "docs/lease.md" not in lease,
            "the deleted document is gone from search",
            lease,
        )
        journey.check(
            "docs/lifecycle.md" in life, "the kept document is still findable", life
        )

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
        journey.step("provider release lifecycle")
        await _provider_release_lifecycle(
            stack,
            journey,
            project_id=project_id,
            repository_id=repository_id,
        )
    return journey.finish()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
