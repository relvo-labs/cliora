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

Two read paths return bytes rather than JSON; each has its own policy:

* GET /download hands back the exact contents of one file (ADR 0028). It is gated
  on `file.browse` like the rest of this module, because a download is a read -
  but it is a *separate endpoint* from /content rather than a flag on it, since
  the two apply different policies to the same file: /content refuses binary and
  caps at the preview size, /download refuses neither and still refuses every
  sensitive file /content does. The response is always application/octet-stream
  with nosniff, so the platform never asks a browser to render node content
  inside the console's own origin.
* POST /binary-preview streams an allowlisted image or PDF with a path in the
  JSON body, under a separate rollout flag and live node capability (ADR 0029).
"""

from __future__ import annotations

import json
import posixpath
import uuid
from typing import Any
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from app.api.errors import ApiError
from app.api.http.deps import require_action
from app.api.middleware import BinaryPreviewCompletion, set_binary_preview_completion
from app.db.engine import get_session
from app.db.models import User
from app.logging import request_id_var
from app.services.files import BinaryPreviewDenial, BinaryPreviewStream, FileRelayService
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


def _content_disposition(rel_path: str) -> str:
    """Build an `attachment` disposition for a workspace-relative path.

    Two forms, and both are needed. `filename=` carries an ASCII fallback for
    clients that do not implement RFC 5987; `filename*=` carries the real,
    percent-encoded UTF-8 name. Sending only the first would rename every non-ASCII
    file on the way out; sending only the second would leave older clients with no
    name at all.

    The ASCII fallback is built by dropping non-ASCII characters rather than by
    transliterating them, because a name is either exactly right or it is a
    fallback, and a fallback that looks like a translation invites someone to trust
    it. Quotes, backslashes and control characters go too - they are the header
    injection surface here, and `quote` only protects the starred form.

    Dropping characters can leave a stub rather than a name: `年度統計.csv` reduces
    to `.csv`, which is not a shortened filename but a different kind of thing - a
    dotfile, and one whose extension a client would then be unable to see. So when
    nothing is left of the stem, `download` stands in for it and the extension is
    kept: `download.csv`. The extension is the half of a fallback name that is
    actually load-bearing, because it is what decides which application opens the
    file; the stem is what the starred form is for.
    """
    name = posixpath.basename(rel_path) or "download"
    kept = "".join(ch for ch in name if 0x20 <= ord(ch) < 0x7F and ch not in '"\\')
    stem, dot, extension = kept.rpartition(".")
    if not dot:
        ascii_name = kept.strip(" .") or "download"
    else:
        ascii_name = (stem.strip(" .") or "download") + "." + (extension.strip(" ") or "bin")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


@router.get("/download")
async def download_file(
    session_id: uuid.UUID,
    path: str = Query(min_length=1, max_length=4096),
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> Response:
    """Return the exact bytes of one file in the session workspace.

    A plain `Response` rather than a `StreamingResponse`, and that is honest about
    what happens: the relay answers in one correlated frame, so the whole file is
    already in memory by the time this function has anything to return. Streaming
    the handover would look like backpressure without providing any, and the thing
    that actually bounds memory here is the 4 MiB ceiling on the node.

    The three headers are a set and none of them is decoration:

    * `application/octet-stream` - never a sniffed or node-supplied type, so the
      platform cannot be talked into serving an HTML file from a workspace as a
      renderable document on its own origin.
    * `nosniff` - which is what stops a browser from ignoring the line above.
    * `attachment` - so the file is saved rather than displayed, for the same reason.

    RBAC is `file.browse`, so a Viewer may download. That is deliberate (ADR 0028
    §5) and it widens what `file.browse` means; the release note says so in its
    first paragraph rather than in a footnote.
    """
    service = FileRelayService(session, registry=registry)
    rel_path, data = await service.download_file(actor=user, session_id=session_id, path=path)
    # download_file writes the audit entry; commit it with the response.
    await session.commit()
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": _content_disposition(rel_path),
            "X-Content-Type-Options": "nosniff",
            # The bytes are the user's file, not a cacheable platform resource, and
            # a shared cache holding a workspace file keyed only by URL would serve
            # it to the next session that asked for the same path.
            "Cache-Control": "no-store",
        },
    )


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


# --- Read-only binary preview (ADR 0029 §6, plan/31/04 §1) ---


class BinaryPreviewResponse(StreamingResponse):
    """The snapshot as `application/octet-stream`, pulled chunk by chunk from the node.

    `__call__` makes cleanup unconditional. Starlette cancels the body on a client
    disconnect, and an async generator cancelled before its first chunk never runs
    its own `finally` — so the handle would stay open on the node until its TTL. The
    shielded block below closes it either way.
    """

    def __init__(self, service: FileRelayService, stream: BinaryPreviewStream) -> None:
        self._service = service
        self._stream = stream
        self._body = service.stream_binary_preview(stream)
        super().__init__(
            self._body, media_type="application/octet-stream", headers=stream.headers()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_id = request_id_var.get()

        async def audit() -> None:
            await self._service._audit_preview_success(self._stream, request_id=request_id)

        set_binary_preview_completion(
            scope, BinaryPreviewCompletion(size=self._stream.size, audit=audit)
        )

        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._body.aclose()
                await self._service.abandon_binary_preview(self._stream)


def _shape_error(message: str, http_status: int) -> ApiError:
    return ApiError("INVALID_ARGUMENT", message, http_status)


async def _preview_path(request: Request, limit: int) -> str:
    """Step 5: the request must be `{"path": "<workspace-relative>"}` as JSON and
    nothing else, and the URL must carry no query at all.

    Refusing ANY query parameter is what makes "someone put the path back in the URL"
    fail in CI rather than surface in an access log: every hop logs URLs, and the
    body is the only place a path is not written down (ADR 0029 §6).
    """
    if request.url.query:
        raise _shape_error("This endpoint takes no query parameters", status.HTTP_400_BAD_REQUEST)
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise _shape_error(
            "The body must be application/json", status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        )
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _shape_error("The request body is too large", status.HTTP_413_CONTENT_TOO_LARGE)
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise _shape_error("The request body is too large", status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _shape_error(
            "The body is not valid JSON", status.HTTP_422_UNPROCESSABLE_CONTENT
        ) from exc
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"path"}
        or not isinstance(parsed["path"], str)
    ):
        raise _shape_error(
            'The body must be exactly {"path": "<workspace-relative path>"}',
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return parsed["path"]


@router.post("/binary-preview")
async def binary_preview(
    session_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_action(FILE_BROWSE)),
    session: AsyncSession = Depends(get_session),
    registry: NodeConnectionRegistry = Depends(get_registry),
) -> BinaryPreviewResponse:
    """Show an allowlisted image or PDF in the console — never hand it over.

    A POST for a read, on purpose: the workspace path travels in the body, so no URL
    carries it and no access log records it (ADR 0029 §6). The order is fixed —
    action, session scope (Viewer included, shell refused), node online, Central's
    flag, the node's live capability, request shape, path, stream limit, open — so
    an old daemon or a disabled flag is refused before a single frame is sent.
    """
    service = FileRelayService(session, registry=registry)
    target = await service.binary_preview_target(actor=user, session_id=session_id)
    path = await _preview_path(request, service.settings.file_preview_max_body_bytes)
    result = await service.open_binary_preview(actor=user, target=target, path=path)
    if isinstance(result, BinaryPreviewDenial):
        # Commit FIRST: a sensitive denial's audit row was added to this session, and
        # raising before the commit would discard it with the session (ADR 0029 §6).
        await session.commit()
        raise result.to_error()
    return BinaryPreviewResponse(service, result)
