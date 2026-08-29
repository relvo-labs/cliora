#!/usr/bin/env python
"""Observe provider event-to-reconcile P95 for one real 300-second worker hour.

Two controlled repositories receive one merged PR at different offsets in each of twelve
unmodified worker intervals.  The production ``KnowledgeWorker`` owns the schedule and
the production ``GitHubReader`` performs loopback HTTP GETs.  This gives 24 independent
event samples spanning an hour without creating or changing an external provider object.

Run against a migrated disposable database.  ``CLIORA_DATABASE_URL`` and
``CLIORA_SECRET_MASTER_KEY`` are required; the report is written to
``artifacts/hd/local/provider-lag-hour.json``.
"""

from __future__ import annotations

import asyncio
import json
import math
import pathlib
import sys
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import sqlalchemy as sa

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))

from app import metrics  # noqa: E402
from app.clock import now_utc  # noqa: E402
from app.db.engine import get_database  # noqa: E402
from app.db.models import (  # noqa: E402
    KnowledgeSource,
    Project,
    ProjectRepository,
    Role,
    User,
)
from app.security.passwords import hash_password  # noqa: E402
from app.services.knowledge.worker import (  # noqa: E402
    RECONCILE_INTERVAL_SECONDS,
    KnowledgeWorker,
)
from app.services.secrets import SecretService  # noqa: E402
from app.settings import Settings  # noqa: E402

ROUNDS = 12
EVENT_OFFSETS_SECONDS = (10.0, 230.0)
POLL_SECONDS = 1.0
ROUND_TIMEOUT_SECONDS = RECONCILE_INTERVAL_SECONDS + 45.0


class _Fixture(ThreadingHTTPServer):
    pulls: dict[str, dict[str, object]]
    calls: int

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.pulls = {}
        self.calls = 0


class _Handler(BaseHTTPRequestHandler):
    server: _Fixture

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        path = urlsplit(self.path).path
        self.server.calls += 1
        parts = path.strip("/").split("/")
        repo_path = "/".join(parts[1:3]) if len(parts) >= 4 else ""
        payload: object
        if path.endswith("/pulls") and repo_path in self.server.pulls:
            payload = [self.server.pulls[repo_path]]
        else:
            payload = []
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _pull(number: int, event_at: datetime, *, merged: bool) -> dict[str, object]:
    encoded_time = event_at.isoformat().replace("+00:00", "Z")
    return {
        "number": number,
        "title": f"Scheduled provider lag sample {number}",
        "body": "One controlled event for the one-hour reconcile observation.",
        "state": "closed" if merged else "open",
        "merged_at": encoded_time if merged else None,
        "head": {"ref": f"sample/{number}"},
        "base": {"ref": "main"},
        "html_url": f"https://example.invalid/pulls/{number}",
        "updated_at": encoded_time,
    }


async def _seed(
    settings: Settings, fixture: _Fixture
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    database = get_database()
    async with database.session() as session:
        role = (
            await session.execute(sa.select(Role).where(Role.name == "Admin"))
        ).scalar_one()
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=uuid.uuid4(),
            username=f"provider-lag-{suffix}",
            display_name="Provider lag observation",
            password_hash=hash_password(uuid.uuid4().hex),
            role_id=role.id,
        )
        session.add(user)
        await session.flush()
        project = Project(
            id=uuid.uuid4(),
            name=f"Provider lag {suffix}",
            slug=f"provider-lag-{suffix}",
            owner_user_id=user.id,
            knowledge_enabled=True,
            provider_sync_enabled=True,
        )
        session.add(project)
        await session.flush()
        secret = await SecretService(session, settings=settings).create(
            project=project,
            name="PROVIDER_LAG_TOKEN",
            kind="provider_token",
            value="controlled-loopback-token",
            actor_id=user.id,
        )
        repository_ids: list[uuid.UUID] = []
        initial = now_utc()
        for index, name in enumerate(("lag-a", "lag-b"), start=1):
            path = f"controlled/{name}"
            repository = ProjectRepository(
                id=uuid.uuid4(),
                project_id=project.id,
                scheme="https",
                host="github.com",
                path=path,
                default_branch="main",
                auth_kind="ambient",
                provider_token_secret_id=secret.id,
                created_by=user.id,
            )
            session.add(repository)
            repository_ids.append(repository.id)
            fixture.pulls[path] = _pull(index, initial, merged=False)
        await session.commit()
        return project.id, repository_ids


async def _sync_times(
    repository_ids: list[uuid.UUID],
) -> dict[uuid.UUID, datetime | None]:
    async with get_database().session() as session:
        rows = (
            await session.execute(
                sa.select(
                    ProjectRepository.id,
                    ProjectRepository.provider_synced_at,
                ).where(ProjectRepository.id.in_(repository_ids))
            )
        ).all()
        return {row.id: row.provider_synced_at for row in rows}


async def _wait_for_next_round(
    repository_ids: list[uuid.UUID],
    previous: dict[uuid.UUID, datetime | None],
    worker: KnowledgeWorker,
    *,
    deadline: float,
) -> dict[uuid.UUID, datetime | None]:
    while time.monotonic() < deadline:
        if worker._task is not None and worker._task.done():  # noqa: SLF001
            exception = worker._task.exception()  # noqa: SLF001
            raise RuntimeError("the production worker task stopped") from exception
        current = await _sync_times(repository_ids)
        if all(
            current[repository_id] is not None
            and (
                previous[repository_id] is None
                or current[repository_id] > previous[repository_id]
            )
            for repository_id in repository_ids
        ):
            return current
        await asyncio.sleep(POLL_SECONDS)
    raise TimeoutError(
        "the production worker did not complete the next 300-second round"
    )


async def _source_lag(project_id: uuid.UUID, number: int) -> float:
    suffix = f":pr:{number}"
    async with get_database().session() as session:
        row = (
            await session.execute(
                sa.select(
                    KnowledgeSource.ingested_at,
                    KnowledgeSource.source_updated_at,
                ).where(
                    KnowledgeSource.project_id == project_id,
                    KnowledgeSource.source_type == "pull_request",
                    KnowledgeSource.source_external_id.endswith(suffix),
                    KnowledgeSource.authority == "reviewed",
                )
            )
        ).one()
        return max(0.0, (row.ingested_at - row.source_updated_at).total_seconds())


def _percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def main() -> int:
    fixture = _Fixture()
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    worker: KnowledgeWorker | None = None
    started_at = now_utc()
    began = time.monotonic()
    samples: list[dict[str, object]] = []
    try:
        port = fixture.server_address[1]
        settings = Settings(
            provider_api_base=f"http://127.0.0.1:{port}",
            provider_api_hosts=["127.0.0.1"],
        )
        metrics.reset()
        project_id, repository_ids = await _seed(settings, fixture)
        worker = KnowledgeWorker(settings)
        await worker.start()
        previous = await _wait_for_next_round(
            repository_ids,
            {repository_id: None for repository_id in repository_ids},
            worker,
            deadline=time.monotonic() + ROUND_TIMEOUT_SECONDS,
        )

        for round_index in range(1, ROUNDS + 1):
            round_started = time.monotonic()
            numbers = (round_index * 2 + 1, round_index * 2 + 2)
            for repo_index, (path, offset, number) in enumerate(
                zip(
                    ("controlled/lag-a", "controlled/lag-b"),
                    EVENT_OFFSETS_SECONDS,
                    numbers,
                    strict=True,
                )
            ):
                await asyncio.sleep(max(0.0, round_started + offset - time.monotonic()))
                event_at = now_utc()
                fixture.pulls[path] = _pull(number, event_at, merged=True)
                samples.append(
                    {
                        "round": round_index,
                        "repository": repo_index + 1,
                        "number": number,
                        "event_at": event_at.isoformat(),
                    }
                )
                print(
                    f"round {round_index}/{ROUNDS}: event {repo_index + 1}/2 at +{offset:.0f}s",
                    flush=True,
                )

            previous = await _wait_for_next_round(
                repository_ids,
                previous,
                worker,
                deadline=round_started + ROUND_TIMEOUT_SECONDS,
            )
            for sample in samples[-2:]:
                sample["lag_seconds"] = round(
                    await _source_lag(project_id, int(sample["number"])), 3
                )
            print(
                f"round {round_index}/{ROUNDS}: reconciled; lags "
                f"{samples[-2]['lag_seconds']}s, {samples[-1]['lag_seconds']}s",
                flush=True,
            )

        values = [float(sample["lag_seconds"]) for sample in samples]
        p95 = _percentile95(values)
        histogram = metrics.histogram_value(metrics.PROVIDER_RECONCILE_LAG_SECONDS)
        assert histogram is not None
        report = {
            "started_at": started_at.isoformat(),
            "finished_at": now_utc().isoformat(),
            "duration_seconds": round(time.monotonic() - began, 3),
            "worker_reconcile_interval_seconds": RECONCILE_INTERVAL_SECONDS,
            "rounds": ROUNDS,
            "samples": samples,
            "sample_count": len(values),
            "p95_seconds": round(p95, 3),
            "budget_seconds": 300.0,
            "verdict": "PASS" if p95 <= 300.0 else "FAIL",
            "histogram": histogram,
            "provider_http_gets": fixture.calls,
            "boundary": (
                "Production KnowledgeWorker cadence and GitHubReader HTTP path against "
                "a controlled loopback upstream; no external provider object mutated."
            ),
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        out = REPO / "artifacts/hd/local/provider-lag-hour.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(encoded)
        print(encoded, end="")
        return 0 if report["verdict"] == "PASS" else 1
    finally:
        if worker is not None:
            await worker.stop()
        fixture.shutdown()
        fixture.server_close()
        thread.join(timeout=2)
        await get_database().dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
