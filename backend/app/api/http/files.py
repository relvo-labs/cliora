"""Workspace filesystem HTTP API (P3-06, P13). RBAC-guarded (file.browse) browser
boundary that relays directory listing, filename search, and single-file
preview to the daemon via the request-correlation path. Central authorizes and
relays only — it never reads the node filesystem and never returns a server
absolute path (ADR 0014). Denials (sensitive/binary/oversize) come back in-band
in the content body with success:false; path/existence errors surface as safe
ApiError responses via the global handler.

Two write paths exist, both gated on `file.upload`, which Viewer does not hold:

* POST /images drops a single image into a platform-named directory (ADR 0024).
  It carries no filename — the daemon names the file.
* POST /upload places one file at a directory and filename the *caller* chooses
  (ADR 0026). It never overwrites: a collision is refused with FILE_EXISTS, and
  that single property is why this path needs no version precondition and no undo.

The contrast is deliberate and is not a redundancy: a pasted screenshot does not
need a name, and `requirements.txt`'s name is its entire meaning.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.http.deps import require_action
from app.db.engine import get_session
from app.db.models import User
from app.services.files import FileRelayService
from app.services.rbac import FILE_BROWSE, FILE_UPLOAD
from app.services.registry import NodeConnectionRegistry, get_node_registry

router = APIRouter(prefix="/api/sessions/{session_id}/files", tags=["files"])


def get_registry() -> NodeConnectionRegistry:
    return get_node_registry()


@router.get("/tree")
async def list_tree(
    session_id: uuid.UUID,
    path: str = Query(default="."),
    cursor: str | None = Query(default=None),
    entry_limit: int | None = Query(default=None, ge=1, le=2000),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    service = FileRelayService(session, registry=registry)
    return await service.list_dir(
        actor=user, session_id=session_id, path=path, cursor=cursor, entry_limit=entry_limit
    )


@router.get("/search")
async def search_files(
    session_id: uuid.UUID,
    keyword: str = Query(min_length=1, max_length=256),
    root: str | None = Query(default=None),
    max_results: int | None = Query(default=None, ge=1, le=200),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    service = FileRelayService(session, registry=registry)
    return await service.search(
        actor=user, session_id=session_id, keyword=keyword, root=root, max_results=max_results
    )


# The four image types a CLI can read (ADR 0024 §2.1). Central checks the
# declared type and the leading bytes only to avoid occupying a node connection
# with something obviously wrong; the daemon's sniff is what actually decides.
_IMAGE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_MAX_UPLOAD_BYTES = 4 * 1024 * 1024


async def _read_bounded_body(request: Request, limit: int) -> bytes:
    """Read a raw request body, refusing anything over `limit`.

    Two-stage on purpose: the declared Content-Length is checked first so an
    oversize upload is refused before its body is transferred, and the running
    total is checked again while reading, because Content-Length is a claim by the
    sender. Shared by both upload paths so they cannot disagree about the ceiling.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ApiError(
            "FILE_UPLOAD_TOO_LARGE",
            f"The file is larger than {limit // (1024 * 1024)} MiB",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            # Stop reading rather than buffer the rest to find out how big a lie
            # the Content-Length was.
            raise ApiError(
                "FILE_UPLOAD_TOO_LARGE",
                f"The file is larger than {limit // (1024 * 1024)} MiB",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _looks_like_image(head: bytes) -> bool:
    """Cheap magic-number pre-screen. Never the authority — the daemon re-sniffs
    and its answer is the one that names the file."""
    return (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"\xff\xd8\xff")
        or head.startswith(b"GIF87a")
        or head.startswith(b"GIF89a")
        or (len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP")
    )


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    session_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_action(FILE_UPLOAD)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    """Drop one image into the session workspace so the CLI can read it.

    The body is the raw image; there is no multipart form and no filename field.
    That is not only ADR 0024 §3 (the sender does not name the file) — it also
    keeps `python-multipart` out of the dependency list and one parser out of the
    request path, for a request that carries exactly one unnamed thing.
    """
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in _IMAGE_CONTENT_TYPES:
        raise ApiError(
            "FILE_UPLOAD_UNSUPPORTED_TYPE",
            "Only PNG, JPEG, GIF and WebP images can be dropped",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    body = await _read_bounded_body(request, _MAX_UPLOAD_BYTES)
    if not body or not _looks_like_image(body[:12]):
        raise ApiError(
            "FILE_UPLOAD_UNSUPPORTED_TYPE",
            "The body is not a PNG, JPEG, GIF or WebP image",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    service = FileRelayService(session, registry=registry)
    payload = await service.upload_image(actor=user, session_id=session_id, data=body)
    # upload_image writes the audit entry; commit it with the response.
    await session.commit()
    return payload


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    session_id: uuid.UUID,
    request: Request,
    directory: str = Query(default=".", max_length=4096),
    filename: str = Query(min_length=1, max_length=1024),
    user: User = Depends(require_action(FILE_UPLOAD)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    """Place one file at a caller-chosen path inside the session workspace.

    The body is the raw file and the destination travels in the query string.
    No multipart, for the same reason as /images: this request carries exactly one
    thing, so it needs neither a parser nor `python-multipart` in the dependency
    list. Non-ASCII names ride through URL encoding — which is also why the
    filename is validated *after* decoding (`%2F` decodes to a separator).

    There is no content-type check and no magic-number sniff. Image drop must
    guarantee the CLI can read what it stores; this path makes no such promise, and
    a user putting a .tar.gz into their own workspace is not the platform's
    business. What stands in for a type check is the name policy and the fixed
    0644 mode, both applied on the node.

    `filename`'s Query max_length is deliberately loose (1024): the real limit is
    255 *bytes* and belongs where the unit is known, not in a character count.
    """
    body = await _read_bounded_body(request, _MAX_UPLOAD_BYTES)
    service = FileRelayService(session, registry=registry)
    payload = await service.store_file(
        actor=user,
        session_id=session_id,
        directory=directory,
        filename=filename,
        data=body,
    )
    # store_file writes the audit entry; commit it with the response.
    await session.commit()
    return payload


@router.get("/content")
async def read_content(
    session_id: uuid.UUID,
    path: str = Query(min_length=1, max_length=4096),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> dict[str, Any]:
    service = FileRelayService(session, registry=registry)
    payload = await service.read_file(actor=user, session_id=session_id, path=path)
    # A sensitive-read denial is audited inside read_file; commit that entry.
    await session.commit()
    return payload
