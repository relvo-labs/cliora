"""`GET /api/metrics` against the real app (P4-09, ADR 0018).

What needs the real app rather than the renderer: the authorization gate, the "disabled
looks like absent" behaviour, and the live gauges — including that a slow one degrades
the scrape instead of failing it.
"""

from __future__ import annotations

import asyncio
import re
import uuid

import pytest
import sqlalchemy as sa

from app import metrics
from app.api.http import metrics as metrics_module
from app.db.models import Node, TerminalSession, User
from app.main import app
from app.settings import Settings, get_settings

pytestmark = pytest.mark.asyncio

TOKEN = "a-scrape-token-long-enough"


def enable(**overrides: object):
    """Override settings so the endpoint is enabled with a known token."""
    values = {"metrics_enabled": True, "metrics_scrape_token": TOKEN, **overrides}
    app.dependency_overrides[get_settings] = lambda: Settings(**values)  # type: ignore[arg-type]


def disable() -> None:
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture(autouse=True)
def _clean():
    metrics.reset()
    yield
    disable()
    metrics.reset()


def headers(token: str = TOKEN) -> dict[str, str]:
    return {"X-Metrics-Token": token}


# --------------------------------------------------------------------------- #
# Availability and authorization
# --------------------------------------------------------------------------- #


async def test_disabled_looks_like_a_route_that_does_not_exist(api: tuple) -> None:
    """404, not 403: a probe must not learn from the response whether this deployment
    has metrics configured at all."""
    client, _ = api
    response = await client.get("/api/metrics", headers=headers())
    assert response.status_code == 404


async def test_a_scrape_without_a_token_is_refused(api: tuple) -> None:
    client, _ = api
    enable()
    response = await client.get("/api/metrics")
    assert response.status_code == 401


async def test_a_wrong_token_is_refused(api: tuple) -> None:
    client, _ = api
    enable()
    assert (await client.get("/api/metrics", headers=headers("wrong"))).status_code == 401


async def test_a_token_prefix_is_not_accepted(api: tuple) -> None:
    """Compared whole, in constant time: a prefix match would let a token be discovered
    one byte at a time."""
    client, _ = api
    enable()
    assert (await client.get("/api/metrics", headers=headers(TOKEN[:-1]))).status_code == 401


@pytest.mark.parametrize("style", ["header", "bearer"])
async def test_the_token_is_accepted_in_either_form(api: tuple, style: str) -> None:
    """Prometheus configures a bearer file naturally; an ad-hoc curl check is easier
    with a plain header."""
    client, _ = api
    enable()
    sent = {"X-Metrics-Token": TOKEN} if style == "header" else {"Authorization": f"Bearer {TOKEN}"}
    response = await client.get("/api/metrics", headers=sent)
    assert response.status_code == 200, response.text


async def test_the_response_is_prometheus_text(api: tuple) -> None:
    client, _ = api
    enable()
    response = await client.get("/api/metrics", headers=headers())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in response.headers["content-type"]


async def test_the_scrape_is_not_audited(api: tuple) -> None:
    """A scrape happens every few seconds. Auditing it would swamp the trail it shares a
    table with (ADR 0016)."""
    from app.db.models import AuditLog

    client, maker = api
    enable()

    async def audit_count() -> int:
        async with maker() as session:
            return int((await session.execute(sa.select(sa.func.count(AuditLog.id)))).scalar_one())

    before = await audit_count()
    for _ in range(3):
        await client.get("/api/metrics", headers=headers())
    assert await audit_count() == before


# --------------------------------------------------------------------------- #
# Gauges
# --------------------------------------------------------------------------- #


async def test_every_declared_gauge_is_present(api: tuple) -> None:
    client, _ = api
    enable()
    text = (await client.get("/api/metrics", headers=headers())).text
    for name in (
        "cliora_active_daemon_connections",
        "cliora_active_terminal_connections",
        "cliora_online_nodes",
        "cliora_database_pool_usage",
    ):
        assert f"# TYPE {name} gauge" in text, f"{name} missing from the scrape"


async def test_running_sessions_is_labelled_by_runtime(api: tuple) -> None:
    client, maker = api
    enable()
    async with maker() as session:
        role = (
            await session.execute(sa.select(sa.text("id")).select_from(sa.table("roles")).limit(1))
        ).scalar_one()
        user = User(
            username=f"m-{uuid.uuid4().hex[:8]}",
            password_hash="x",
            display_name="m",
            role_id=role,
        )
        node = Node(name="vm", hostname="vm", status="offline", is_enabled=True)
        session.add_all([user, node])
        await session.flush()
        session.add_all(
            TerminalSession(
                node_id=node.id,
                user_id=user.id,
                name="s",
                runtime=runtime,
                workspace="/w",
                status="running",
            )
            for runtime in ("claude", "claude", "codex")
        )
        await session.commit()

    text = (await client.get("/api/metrics", headers=headers())).text
    assert 'cliora_running_sessions{runtime="claude"} 2' in text
    assert 'cliora_running_sessions{runtime="codex"} 1' in text


async def test_the_pool_gauge_reports_every_state(api: tuple) -> None:
    client, _ = api
    enable()
    text = (await client.get("/api/metrics", headers=headers())).text
    for state in ("checked_out", "available", "overflow", "size"):
        assert f'cliora_database_pool_usage{{state="{state}"}}' in text


async def test_a_slow_gauge_degrades_the_scrape_instead_of_failing_it(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Losing one number is better than losing all visibility, and it matters most
    exactly when something is already slow."""
    client, _ = api
    enable(metrics_gauge_timeout_seconds=0.01)

    original = metrics_module._bounded

    async def slow_online(name, compute, budget_seconds):  # type: ignore[no-untyped-def]
        if name == "online_nodes":

            async def hang() -> float:
                await asyncio.sleep(5)
                return 0.0

            return await original(name, hang, budget_seconds)
        return await original(name, compute, budget_seconds)

    monkeypatch.setattr(metrics_module, "_bounded", slow_online)
    response = await client.get("/api/metrics", headers=headers())

    assert response.status_code == 200
    assert "cliora_online_nodes " not in response.text
    # The omission is visible rather than looking like a metric that does not exist.
    assert 'cliora_scrape_error_total{block="online_nodes"}' in response.text
    # And the rest of the scrape is intact.
    assert "cliora_active_daemon_connections" in response.text


async def test_a_raising_gauge_also_degrades_rather_than_500s(
    api: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = api
    enable()
    original = metrics_module._bounded

    async def boom(name, compute, budget_seconds):  # type: ignore[no-untyped-def]
        if name == "running_sessions":

            async def raise_it() -> dict[str, int]:
                raise RuntimeError('relation "terminal_sessions" does not exist')

            return await original(name, raise_it, budget_seconds)
        return await original(name, compute, budget_seconds)

    monkeypatch.setattr(metrics_module, "_bounded", boom)
    response = await client.get("/api/metrics", headers=headers())

    assert response.status_code == 200
    assert "cliora_running_sessions" not in response.text
    # The underlying message could name a table; it must not reach the scrape.
    assert "terminal_sessions" not in response.text


# --------------------------------------------------------------------------- #
# Recorded series reach the scrape
# --------------------------------------------------------------------------- #


async def test_http_request_duration_is_recorded_with_the_route_template(api: tuple) -> None:
    """The template, not the path: the actual URL would create one series per session
    id, forever."""
    client, _ = api
    enable()
    await client.get(f"/api/nodes/{uuid.uuid4()}")  # 401, but still timed
    text = (await client.get("/api/metrics", headers=headers())).text

    assert "# TYPE cliora_http_request_duration_seconds histogram" in text
    assert 'route="/api/nodes/{node_id}"' in text
    # And no series carries a concrete uuid.
    assert not re.search(r'route="[^"]*[0-9a-f]{8}-[0-9a-f]{4}-', text), text


async def test_an_unmatched_path_becomes_one_series_not_one_per_url(api: tuple) -> None:
    """Otherwise a scanner probing a thousand URLs grows the series set by a thousand."""
    client, _ = api
    enable()
    for index in range(3):
        await client.get(f"/definitely-not-a-route-{index}")
    text = (await client.get("/api/metrics", headers=headers())).text
    assert 'route="<unmatched>"' in text
    assert "definitely-not-a-route" not in text


async def test_the_scrape_reflects_a_counter_recorded_during_the_request(api: tuple) -> None:
    client, _ = api
    enable()
    metrics.increment(metrics.AUDIT_ERROR_TOTAL, action="user.login")
    text = (await client.get("/api/metrics", headers=headers())).text
    assert 'cliora_audit_error_total{action="user.login"} 1' in text


async def test_no_series_in_a_real_scrape_carries_an_identifier(api: tuple) -> None:
    """The end-to-end form of the allowlist rule: whatever the app recorded while
    serving real requests, the published output must contain no uuid and no path."""
    client, _ = api
    enable()
    await client.get(f"/api/nodes/{uuid.uuid4()}")
    await client.get(f"/api/sessions/{uuid.uuid4()}/files/tree?path=/etc/passwd")
    text = (await client.get("/api/metrics", headers=headers())).text

    for line in text.splitlines():
        if line.startswith("#") or "{" not in line:
            continue
        labels = line[line.index("{") + 1 : line.rindex("}")]
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", labels), line
        assert "/etc/passwd" not in labels, line
