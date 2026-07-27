"""Public artifact + install-script endpoints for the one-line installer.

These are intentionally unauthenticated: the daemon fetches the install script
and binary before it holds any credential (the enrollment token gates the later
`POST /api/nodes/register`). Only a closed allowlist of names resolves to a file
and the resolved path is confirmed to stay inside the artifacts directory, so no
path-traversal or arbitrary-file read is possible (SEC / tech §23 #12, ADR 0011).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse, PlainTextResponse

from app.api.errors import ApiError
from app.services.releases import ARTIFACT_PATTERN
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api", tags=["downloads"])

# The closed allowlist of downloadable artifact names lives in
# `app/services/releases.py`, because the release manifest must publish exactly the
# names this endpoint will serve. Two copies of the pattern would eventually
# disagree, and the direction that disagreement takes decides whether a node can
# be updated at all — or whether something unserviceable gets advertised.
_INSTALL_SCRIPT_NAME = "install.sh"


def _artifacts_root(settings: Settings) -> Path:
    if not settings.artifacts_dir:
        raise ApiError("NOT_FOUND", "Artifact not found", status.HTTP_404_NOT_FOUND)
    return Path(settings.artifacts_dir)


def _resolve(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    root_resolved = root.resolve()
    # Defence in depth: the name is already allowlisted, but confirm the resolved
    # path stays inside the artifacts root before touching the filesystem.
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ApiError("NOT_FOUND", "Artifact not found", status.HTTP_404_NOT_FOUND)
    if not candidate.is_file():
        raise ApiError("NOT_FOUND", "Artifact not found", status.HTTP_404_NOT_FOUND)
    return candidate


@router.get("/downloads/{filename}")
async def download_artifact(
    filename: str, settings: Settings = Depends(get_settings)
) -> FileResponse:
    if not ARTIFACT_PATTERN.match(filename):
        raise ApiError("NOT_FOUND", "Artifact not found", status.HTTP_404_NOT_FOUND)
    path = _resolve(_artifacts_root(settings), filename)
    media_type = "text/plain" if filename == "checksums.txt" else "application/gzip"
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get("/install-script")
async def install_script(settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    path = _resolve(_artifacts_root(settings), _INSTALL_SCRIPT_NAME)
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/x-shellscript")
