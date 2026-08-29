#!/usr/bin/env python
"""Read-only provider transport evidence against a disposable Cliora database.

This makes no provider mutation: ``provider_reads`` can issue only GET and the hardening
gate enforces that absence.  It creates a local project/repository/secret, runs the real
provider reconcile pass, and proves a merged PR arrived as ``reviewed`` and is selected
by a context pack.

The token is accepted only through ``CLIORA_PROVIDER_EVIDENCE_TOKEN``.  It is encrypted
through ``SecretService``, never printed, never passed as an argv value, and the report is
refused if the plaintext appears in its serialization.

    CLIORA_PROVIDER_EVIDENCE_TOKEN=... \
      CLIORA_SECRET_MASTER_KEY=... \
      uv run --project backend python scripts/hd/real-provider-evidence.py \
        --url postgresql+asyncpg://.../disposable_db \
        --repository owner/name \
        --out artifacts/hd/local/provider-real.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app.clock import now_utc  # noqa: E402
from app.db.models import (  # noqa: E402
    KnowledgeSource,
    Project,
    ProjectRepository,
    Role,
    Task,
    User,
)
from app.security.passwords import hash_password  # noqa: E402
from app.services import provider_reads  # noqa: E402
from app.services.knowledge import provider_sync  # noqa: E402
from app.services.knowledge.context import ContextBuilder  # noqa: E402
from app.services.knowledge.search import KnowledgeSearch  # noqa: E402
from app.services.secrets import SecretService  # noqa: E402
from app.settings import Settings  # noqa: E402

_REPOSITORY = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def _seed(maker, *, repository_path: str, token: str, settings: Settings):
    async with maker() as session:
        role = (
            await session.execute(sa.select(Role).where(Role.name == "Admin"))
        ).scalar_one()
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=uuid.uuid4(),
            username=f"provider-evidence-{suffix}",
            display_name="Provider evidence",
            password_hash=hash_password(uuid.uuid4().hex),
            role_id=role.id,
        )
        session.add(user)
        await session.flush()
        project = Project(
            id=uuid.uuid4(),
            name=f"Provider evidence {suffix}",
            slug=f"provider-evidence-{suffix}",
            owner_user_id=user.id,
            knowledge_enabled=True,
            provider_sync_enabled=True,
        )
        session.add(project)
        await session.flush()
        secret = await SecretService(session, settings=settings).create(
            project=project,
            name="GITHUB_PROVIDER_TOKEN",
            kind="provider_token",
            value=token,
            actor_id=user.id,
        )
        repository = ProjectRepository(
            id=uuid.uuid4(),
            project_id=project.id,
            scheme="https",
            host="github.com",
            path=repository_path,
            default_branch="main",
            auth_kind="ambient",
            provider_token_secret_id=secret.id,
            created_by=user.id,
        )
        session.add(repository)
        await session.commit()
        return project.id, user.id


async def _disabled_transport_trap(
    maker, *, project_id: uuid.UUID, settings: Settings
) -> tuple[int, provider_sync.SyncOutcome]:
    """Prove the disabled flag exits before a provider reader can issue any GET."""
    calls = 0
    original = provider_reads.reader_for

    def trapped_reader(host: str, current_settings: Settings):
        nonlocal calls
        calls += 1
        raise RuntimeError(
            f"disabled provider sync reached the transport reader for {host}"
        )

    async with maker() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        project.provider_sync_enabled = False
        await session.commit()

    provider_reads.reader_for = trapped_reader
    try:
        async with maker() as session:
            outcome = await provider_sync.sync_project(
                session, project_id=project_id, settings=settings
            )
    finally:
        provider_reads.reader_for = original
    return calls, outcome


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--out", default="artifacts/hd/local/provider-real.json")
    args = parser.parse_args()

    if not _REPOSITORY.fullmatch(args.repository):
        parser.error("--repository must be owner/name")
    token = os.environ.get("CLIORA_PROVIDER_EVIDENCE_TOKEN", "")
    if not token:
        print("CLIORA_PROVIDER_EVIDENCE_TOKEN is required", file=sys.stderr)
        return 2

    settings = Settings()
    engine = create_async_engine(args.url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    project_id, user_id = await _seed(
        maker, repository_path=args.repository, token=token, settings=settings
    )

    began = time.perf_counter()
    async with maker() as session:
        outcome = await provider_sync.sync_project(
            session, project_id=project_id, settings=settings
        )
        await session.commit()
    elapsed = time.perf_counter() - began
    disabled_reader_calls, disabled_outcome = await _disabled_transport_trap(
        maker, project_id=project_id, settings=settings
    )

    async with maker() as session:
        merged = (
            await session.execute(
                sa.select(KnowledgeSource)
                .where(
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.source_type == "pull_request",
                    KnowledgeSource.authority == "reviewed",
                    KnowledgeSource.active.is_(True),
                    KnowledgeSource.deleted_at.is_(None),
                )
                .order_by(KnowledgeSource.occurred_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if merged is None:
            print(
                "provider returned no merged pull request in the bounded first pass",
                file=sys.stderr,
            )
            await engine.dispose()
            return 1

        task = Task(
            id=uuid.uuid4(),
            project_id=project_id,
            card_ref="HD-PROVIDER-EVIDENCE",
            title=merged.title or "Merged pull request",
            description="Verify that a real provider source enters retrieved evidence.",
            created_by=user_id,
        )
        session.add(task)
        await session.flush()
        search = await KnowledgeSearch(session, project_id).search(task.title, limit=8)
        pack = await ContextBuilder(session).build(task)
        selected = any(
            item.get("source_id") == str(merged.id) for item in pack.manifest
        )
        found = any(hit.source_id == merged.id for hit in search.items)

        report = {
            "commit": _commit(),
            "observed_at": now_utc().isoformat(),
            "provider": "github.com",
            "repository": args.repository,
            "operation": "GET-only provider reconcile into disposable local database",
            "sync_elapsed_seconds": round(elapsed, 3),
            "outcome": {
                "repositories": outcome.repositories,
                "sources": outcome.sources,
                "failures": outcome.failures,
                "skipped": outcome.skipped,
            },
            "provider_disabled_transport_trap": {
                "reader_calls": disabled_reader_calls,
                "http_gets": 0 if disabled_reader_calls == 0 else "not evaluated",
                "outcome": {
                    "repositories": disabled_outcome.repositories,
                    "sources": disabled_outcome.sources,
                    "failures": disabled_outcome.failures,
                    "skipped": disabled_outcome.skipped,
                },
            },
            "merged_pull_request": {
                "source_id": str(merged.id),
                "title": merged.title,
                "authority": merged.authority,
                "occurred_at": merged.occurred_at.isoformat(),
                "uri": merged.source_uri,
                "found_by_search": found,
                "selected_by_context_pack": selected,
            },
            "limits": [
                "This observes real GET transport and post-read ingestion.",
                "It does not observe event-to-next-300-second-reconcile lag.",
                "It does not create, merge, close, approve, tag, or delete provider data.",
            ],
        }

    await engine.dispose()
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if token in encoded:
        raise RuntimeError("refusing to write a report containing the provider token")
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(encoded)
    print(encoded, end="")
    if (
        not found
        or not selected
        or merged.authority != "reviewed"
        or disabled_reader_calls != 0
        or disabled_outcome != provider_sync.SyncOutcome()
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
