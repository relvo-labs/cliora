"""Release manifest endpoint (P4-10, ADR 0017).

Unauthenticated, for the same reason `/api/downloads` is: a daemon needs to know
which releases exist before and independently of holding a credential, and the
content is public information about published artifacts — version numbers,
filenames and digests, all of which the download endpoint already serves.

An empty deployment answers `{"latest": null, "artifacts": []}` with 200, not 404.
The daemon must be able to distinguish "nothing to install" from "this Central is
too old to have the endpoint", and a 404 conflates them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.http.schemas import ReleaseManifestDTO
from app.services.releases import ReleaseService
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/releases", tags=["releases"])


@router.get("/manifest", response_model=ReleaseManifestDTO)
async def release_manifest(settings: Settings = Depends(get_settings)) -> ReleaseManifestDTO:
    return ReleaseManifestDTO.from_manifest(ReleaseService(settings=settings).manifest())
