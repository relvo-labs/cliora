import importlib

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.api.errors import ApiError, install_error_handlers
from app.api.middleware import RequestIdMiddleware
from app.main import app
from app.services.registry import get_node_registry


def test_healthz_ok_and_sets_request_id() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert "x-request-id" in response.headers


def test_request_id_is_echoed_when_supplied() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz", headers={"x-request-id": "trace-123"})
        assert response.headers["x-request-id"] == "trace-123"


def test_readyz_reports_database_and_daemon_keys() -> None:
    with TestClient(app) as client:
        body = client.get("/readyz").json()
        assert {"status", "database", "daemon_connected"} <= set(body)
        assert isinstance(body["database"], bool)


# --------------------------------------------------------------------------- #
# Readiness is a status code, not only a body (ADR 0020)
#
# Both halves are patched explicitly rather than relying on whether a database
# happens to be reachable from the test host: the point of these three tests is the
# mapping from (database, migration) to the status code, and a test that passes
# because the developer has no PostgreSQL running proves nothing about it.
# --------------------------------------------------------------------------- #


def _patch_readiness(monkeypatch: pytest.MonkeyPatch, *, database: bool, migration: bool) -> None:
    async def _database() -> bool:
        return database

    async def _migration() -> bool:
        return migration

    monkeypatch.setattr("app.main._database_ready", _database)
    monkeypatch.setattr("app.main._migration_head_applied", _migration)


def test_readyz_returns_200_when_the_database_and_migration_are_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_readiness(monkeypatch, database=True, migration=True)
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ready"


def test_readyz_returns_503_when_the_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A managed platform's health check reads the status code and nothing else, so a
    degraded 200 let an unready Central take traffic."""
    _patch_readiness(monkeypatch, database=False, migration=False)
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.json()
    assert body["status"] == "degraded"
    # Which half failed still has to be readable: it decides which runbook applies.
    assert body["database"] is False


def test_readyz_returns_503_when_the_applied_migration_is_not_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The database being reachable is not readiness. A container started against a
    schema the migration step never reached must stay out of rotation."""
    _patch_readiness(monkeypatch, database=True, migration=False)
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()["database"] is True


# --------------------------------------------------------------------------- #
# P0 dev relay retirement (P4-07, ADR 0016)
# --------------------------------------------------------------------------- #


def test_no_p0_relay_route_is_mounted() -> None:
    """The relay's endpoints were the app's only WebSockets authorized by a single
    static token shared by every client. They were kept behind a fail-closed
    environment check, which made them one misconfigured variable from reachable —
    so this asserts they are *gone*, not that they are refused."""
    mounted = {getattr(route, "path", "") for route in app.routes}
    assert not [path for path in mounted if "p0" in path or "/poc" in path], sorted(mounted)


def test_the_relay_package_is_gone() -> None:
    """`app/relay/registry.py` served only the P0 endpoints. Its sibling
    `queue.py` (the bounded terminal channel) is production code and moved to
    `app/services/terminal_queue.py`, where its only consumers live — the package name
    `relay` now belonged to the retired thing."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.relay")
    # The production queue survived the move.
    assert importlib.import_module("app.services.terminal_queue").BrowserChannel


def test_readyz_counts_authenticated_daemons_not_the_dev_relay() -> None:
    """`daemon_connected` used to report the P0 relay's registry, so a real fleet of
    enrolled nodes read `false` while the dev relay read `true`."""
    with TestClient(app) as client:
        body = client.get("/readyz").json()
    assert body["daemon_connected"] == (get_node_registry().connection_count > 0)


def _error_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(RequestIdMiddleware)
    install_error_handlers(test_app)

    @test_app.get("/api-error")
    async def _raise_api_error() -> None:
        raise ApiError("FORBIDDEN", "Not allowed", status.HTTP_403_FORBIDDEN)

    @test_app.get("/boom")
    async def _raise_unexpected() -> None:
        raise RuntimeError("secret internal detail: password=hunter2")

    return test_app


def test_api_error_returns_stable_code_and_request_id() -> None:
    with TestClient(_error_app()) as client:
        response = client.get("/api-error")
        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "FORBIDDEN"
        assert body["error"]["message"] == "Not allowed"
        assert body["request_id"]


def test_unexpected_error_is_opaque() -> None:
    with TestClient(_error_app(), raise_server_exceptions=False) as client:
        response = client.get("/boom")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        # No internal detail or secret leaks into the client response.
        assert "secret" not in response.text
        assert "hunter2" not in response.text
