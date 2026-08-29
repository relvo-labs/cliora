#!/usr/bin/env python
"""J17/J18 against production HTTP reads and a controlled upstream.

No external provider object is mutated.  The fixture is reachable only on loopback, but
the reader, sync service, database, Central, frontend and browser are the production
paths.  The journey moves one PR from open to merged, times it through Drawer rendering,
then returns a revoked-token response for three rounds and proves the fourth does not
read before checking the reason in the settings UI.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import sqlalchemy as sa

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "kn" / "journeys"))
sys.path.insert(0, str(REPO / "backend"))

from kn_harness import KnowledgeStack  # noqa: E402

from app.clock import now_utc  # noqa: E402
from app.db.models import KnowledgeSource, Project, ProjectRepository  # noqa: E402
from app.services.knowledge import provider_sync  # noqa: E402
from app.services.secrets import SecretService  # noqa: E402
from app.settings import Settings  # noqa: E402


class _Fixture(ThreadingHTTPServer):
    pull: dict[str, object]
    revoked: bool
    calls: list[str]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.pull = {}
        self.revoked = False
        self.calls = []


class _Handler(BaseHTTPRequestHandler):
    server: _Fixture

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlsplit(self.path).path
        self.server.calls.append(path)
        if self.server.revoked:
            payload: object = {"message": "Bad credentials"}
            status = 401
        else:
            payload = [self.server.pull] if path.endswith("/pulls") else []
            status = 200
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _pull(*, merged: bool, updated_at: datetime) -> dict[str, object]:
    return {
        "number": 71,
        "title": "J17 merged provider journey",
        "body": "A controlled provider fact that must reach Related knowledge.",
        "state": "closed" if merged else "open",
        "merged_at": updated_at.isoformat().replace("+00:00", "Z") if merged else None,
        "head": {"ref": "feature/j17"},
        "base": {"ref": "main"},
        "html_url": "https://example.invalid/pulls/71",
        "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
    }


def _browser(project_id: str, task_id: str, title: str) -> None:
    env = os.environ.copy()
    frontend_port = env.get("E2E_FRONTEND_PORT", "5188")
    central_port = env.get("CENTRAL_PORT", "8000")
    env.update(
        {
            "E2E_PROVIDER_PROJECT": project_id,
            "E2E_PROVIDER_TASK": task_id,
            "E2E_PROVIDER_TITLE": title,
            "E2E_FRONTEND_PORT": frontend_port,
            "E2E_BASE_URL": f"http://127.0.0.1:{frontend_port}",
            "CLIORA_DEV_PROXY_TARGET": f"http://127.0.0.1:{central_port}",
        }
    )
    subprocess.run(
        [
            "npx",
            "playwright",
            "test",
            "--config",
            "tests/hd/playwright.config.ts",
            "provider-journeys.spec.ts",
            "--workers=1",
        ],
        cwd=REPO / "frontend",
        env=env,
        check=True,
    )


async def main() -> int:
    fixture = _Fixture()
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    report: dict[str, object] = {}
    try:
        port = fixture.server_address[1]
        settings = Settings(
            provider_api_base=f"http://127.0.0.1:{port}",
            provider_api_hosts=["127.0.0.1"],
        )
        async with KnowledgeStack() as stack:
            await stack.require_quiet_database()
            project_id = await stack.project("hd-provider-events")
            await stack.enable_knowledge(project_id)
            repository_reply = await stack.client.post(
                f"/api/projects/{project_id}/repositories",
                json={
                    "scheme": "https",
                    "host": "github.com",
                    "path": "controlled/provider-events",
                    "default_branch": "main",
                },
                headers=stack.headers,
            )
            repository_reply.raise_for_status()
            repository_id = uuid.UUID(repository_reply.json()["id"])

            async with stack.maker() as session:
                project = await session.get(Project, uuid.UUID(project_id))
                repository = await session.get(ProjectRepository, repository_id)
                assert project is not None and repository is not None
                project.provider_sync_enabled = True
                secret = await SecretService(session, settings=settings).create(
                    project=project,
                    name="PROVIDER_EVENT_TOKEN",
                    kind="provider_token",
                    value="controlled-token",
                    actor_id=project.owner_user_id,
                )
                repository.provider_token_secret_id = secret.id
                fixture.pull = _pull(merged=False, updated_at=now_utc())
                await provider_sync.sync_project(
                    session, project_id=project.id, settings=settings
                )
                await session.commit()

            event_at = now_utc()
            began = time.perf_counter()
            fixture.pull = _pull(merged=True, updated_at=event_at)
            async with stack.maker() as session:
                repository = await session.get(ProjectRepository, repository_id)
                assert repository is not None
                # This is the next live-cursor round, not another first pass. Move the
                # prior success just beyond the per-repository rate floor so the
                # production guard permits the deterministic round without erasing the
                # cursor semantics the freshness metric depends on.
                repository.provider_synced_at = event_at - timedelta(seconds=101)
                merged_outcome = await provider_sync.sync_project(
                    session, project_id=uuid.UUID(project_id), settings=settings
                )
                reviewed = (
                    await session.execute(
                        sa.select(KnowledgeSource)
                        .where(
                            KnowledgeSource.project_id == uuid.UUID(project_id),
                            KnowledgeSource.source_type == "pull_request",
                            KnowledgeSource.authority == "reviewed",
                            KnowledgeSource.active.is_(True),
                            KnowledgeSource.deleted_at.is_(None),
                        )
                        .order_by(KnowledgeSource.occurred_at.desc())
                        .limit(1)
                    )
                ).scalar_one()
                await session.commit()
            ingest_seconds = time.perf_counter() - began

            task = await stack.card(project_id, title=reviewed.title or "J17 merged PR")
            pin = await stack.client.post(
                f"/api/projects/{project_id}/knowledge/pins",
                json={
                    "task_id": task["id"],
                    "source_id": str(reviewed.id),
                    "mode": "pin",
                },
                headers=stack.headers,
            )
            pin.raise_for_status()

            fixture.revoked = True
            calls_before_failures = len(fixture.calls)
            failure_outcomes = []
            async with stack.maker() as session:
                for _ in range(3):
                    repository = await session.get(ProjectRepository, repository_id)
                    assert repository is not None
                    repository.provider_synced_at = now_utc() - timedelta(seconds=101)
                    failure_outcomes.append(
                        await provider_sync.sync_project(
                            session,
                            project_id=uuid.UUID(project_id),
                            settings=settings,
                        )
                    )
                calls_after_three = len(fixture.calls)
                fourth = await provider_sync.sync_project(
                    session, project_id=uuid.UUID(project_id), settings=settings
                )
                calls_after_fourth = len(fixture.calls)
                await session.commit()

            await asyncio.to_thread(
                _browser,
                project_id,
                task["id"],
                reviewed.title or "J17 merged PR",
            )
            visible_seconds = time.perf_counter() - began
            report = {
                "observed_at": now_utc().isoformat(),
                "fixture": "loopback controlled upstream; production GitHubReader HTTP path",
                "j17": {
                    "verdict": "PASS" if visible_seconds <= 300 else "FAIL",
                    "event_at": event_at.isoformat(),
                    "ingest_seconds": round(ingest_seconds, 3),
                    "drawer_visible_seconds": round(visible_seconds, 3),
                    "authority": reviewed.authority,
                    "sync_sources": merged_outcome.sources,
                    "metric_lags_seconds": list(merged_outcome.reconcile_lags_seconds),
                },
                "j18": {
                    "verdict": "PASS"
                    if all(item.failures == 1 for item in failure_outcomes)
                    and fourth.skipped == 1
                    and calls_after_fourth == calls_after_three
                    else "FAIL",
                    "failure_rounds": [item.failures for item in failure_outcomes],
                    "provider_reads_for_three_rounds": calls_after_three
                    - calls_before_failures,
                    "fourth_round_provider_reads": calls_after_fourth
                    - calls_after_three,
                    "fourth_round_skipped": fourth.skipped,
                    "settings_reason_visible": True,
                },
                "limits": [
                    "No external provider object was created, merged, revoked, or deleted.",
                    "The upstream event and refusal are controlled; HTTP reader, sync, database, Central, frontend, and Chromium are production paths.",
                ],
            }
    finally:
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)

    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    out = REPO / "artifacts/hd/local/provider-event-journeys.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(encoded)
    print(encoded, end="")
    return 0 if report["j17"]["verdict"] == report["j18"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
