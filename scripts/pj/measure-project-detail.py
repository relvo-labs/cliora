#!/usr/bin/env python3
"""M-PJ-01: p95 and response size for a project with 50 bindings."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.http.projects import get_registry
from app.db.engine import get_session
from app.db.models import Node, NodeWorkspaceRoot, Project, ProjectWorkspace, Role, User
from app.main import app
from app.security.passwords import hash_password
from app.settings import Settings, get_settings

BINDINGS = 50
SAMPLES = 30
BUDGET_MS = 200.0


class OnlineRegistry:
    @staticmethod
    def seconds_since_heartbeat(_node_id: uuid.UUID) -> float:
        return 0.0


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percent)))
    return ordered[index]


async def main() -> None:
    url = os.environ.get(
        "CLIORA_TEST_DATABASE_URL",
        "postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_test",
    )
    engine = create_async_engine(url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex[:10]
    username = f"measure-pj-{suffix}"
    node_ids: list[uuid.UUID] = []

    async with maker() as session:
        role = (
            await session.execute(sa.select(Role).where(Role.name == "Admin"))
        ).scalar_one()
        user = User(
            id=uuid.uuid4(),
            username=username,
            display_name="Project measurement",
            password_hash=hash_password("measure-pw"),
            role_id=role.id,
        )
        project = Project(
            id=uuid.uuid4(),
            name="Fifty bindings",
            slug=f"measure-{suffix}",
            owner_user_id=user.id,
        )
        session.add(user)
        await session.flush()
        session.add(project)
        await session.flush()
        for index in range(BINDINGS):
            node = Node(
                id=uuid.uuid4(),
                name=f"measure-{suffix}-{index}",
                hostname=f"measure-{index}.invalid",
                status="online",
                is_enabled=True,
            )
            root = NodeWorkspaceRoot(
                node_id=node.id, path=f"/srv/measure/{index}", is_enabled=True
            )
            binding = ProjectWorkspace(
                id=uuid.uuid4(),
                project_id=project.id,
                node_id=node.id,
                path=f"/srv/measure/{index}/repo",
            )
            node_ids.append(node.id)
            session.add_all([node, root, binding])
        await session.commit()
        project_id = project.id
        user_id = user.id

    async def sessions() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: Settings(projects_enabled=True)
    app.dependency_overrides[get_registry] = OnlineRegistry
    timings: list[float] = []
    response_bytes = 0
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://measure"
        ) as client:
            login = await client.post(
                "/api/auth/login", json={"username": username, "password": "measure-pw"}
            )
            login.raise_for_status()
            headers = {
                "Authorization": f"Bearer {login.json()['tokens']['access_token']}"
            }
            for _ in range(SAMPLES):
                started = time.perf_counter()
                response = await client.get(
                    f"/api/projects/{project_id}", headers=headers
                )
                timings.append((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                response_bytes = len(response.content)
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_registry, None)
        async with maker() as session:
            await session.execute(sa.delete(Project).where(Project.id == project_id))
            await session.execute(sa.delete(Node).where(Node.id.in_(node_ids)))
            await session.execute(sa.delete(User).where(User.id == user_id))
            await session.commit()
        await engine.dispose()

    result = {
        "bindings": BINDINGS,
        "samples": SAMPLES,
        "response_bytes": response_bytes,
        "mean_ms": round(statistics.mean(timings), 3),
        "p95_ms": round(percentile(timings, 0.95), 3),
        "budget_ms": BUDGET_MS,
    }
    output = Path("artifacts/pj/local/project-detail-performance.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["p95_ms"] >= BUDGET_MS:
        raise SystemExit("M-PJ-01 exceeded its p95 budget")


if __name__ == "__main__":
    asyncio.run(main())
