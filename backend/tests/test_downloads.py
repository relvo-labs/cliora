from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers
from app.api.http.downloads import router as downloads_router
from app.settings import Settings, get_settings


def _client(artifacts_dir: str) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(downloads_router)
    app.dependency_overrides[get_settings] = lambda: Settings(artifacts_dir=artifacts_dir)
    return TestClient(app, raise_server_exceptions=False)


def test_download_tarball(tmp_path: Path) -> None:
    (tmp_path / "agentd_1.2.3_linux_amd64.tar.gz").write_bytes(b"BINARY")
    with _client(str(tmp_path)) as client:
        response = client.get("/api/downloads/agentd_1.2.3_linux_amd64.tar.gz")
        assert response.status_code == 200
        assert response.content == b"BINARY"


def test_download_checksums(tmp_path: Path) -> None:
    (tmp_path / "checksums.txt").write_text("abc  agentd_1.2.3_linux_amd64.tar.gz\n")
    with _client(str(tmp_path)) as client:
        response = client.get("/api/downloads/checksums.txt")
        assert response.status_code == 200
        assert "agentd_1.2.3_linux_amd64.tar.gz" in response.text


def test_install_script_served_as_shellscript(tmp_path: Path) -> None:
    (tmp_path / "install.sh").write_text("#!/usr/bin/env bash\necho hi\n")
    with _client(str(tmp_path)) as client:
        response = client.get("/api/install-script")
        assert response.status_code == 200
        assert response.text.startswith("#!/usr/bin/env bash")
        assert "shellscript" in response.headers["content-type"]


def test_rejects_unknown_name(tmp_path: Path) -> None:
    (tmp_path / "passwd").write_text("secret")
    with _client(str(tmp_path)) as client:
        assert client.get("/api/downloads/agentd").status_code == 404
        assert client.get("/api/downloads/passwd").status_code == 404


def test_rejects_traversal(tmp_path: Path) -> None:
    with _client(str(tmp_path)) as client:
        assert client.get("/api/downloads/..%2f..%2fetc%2fpasswd").status_code == 404


def test_missing_artifact_is_404(tmp_path: Path) -> None:
    with _client(str(tmp_path)) as client:
        assert client.get("/api/downloads/checksums.txt").status_code == 404
        assert client.get("/api/install-script").status_code == 404


def test_unconfigured_artifacts_dir_is_404(tmp_path: Path) -> None:
    with _client("") as client:
        assert client.get("/api/downloads/checksums.txt").status_code == 404
        assert client.get("/api/install-script").status_code == 404
