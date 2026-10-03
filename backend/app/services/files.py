"""Central filesystem relay (P3-06). Read-only browser boundary for directory
listing, filename search, and single-file preview. Central only relays and
authorizes: it resolves a session to its node + workspace, prefix-authorizes the
requested workspace-relative path, and forwards the operation to the daemon via
the request-correlation path. Central never reads the node filesystem itself and
never emits a server absolute path to the browser (ADR 0014). The daemon is the
sole authority on the final canonical decision and the sensitive/binary/oversize
policy.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import math
import os
import posixpath
import time
import uuid
from collections import Counter
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import anyio
from fastapi import status

from app import metrics
from app.api.error_catalog import safe_message
from app.api.errors import ApiError
from app.db.models import TerminalSession, User
from app.logging import get_logger
from app.protocol.codec import ControlMessage
from app.repositories.sessions import SessionRepository
from app.services import audit, authz
from app.services.audit import AuditService
from app.services.registry import NodeConnectionRegistry, get_node_registry
from app.settings import Settings, get_settings

log = get_logger("cliora.files")

# Classifications the daemon returns for a *sensitive* preview denial (as
# opposed to symlink/outside/not-regular). Only these are audited (SEC-006).
_SENSITIVE_REASONS = frozenset({"dotenv", "private_key", "keystore", "sensitive_dir", "sensitive"})

# Daemon error codes that must collapse to a single safe outward "cannot access"
# so the browser cannot probe for the existence of paths outside its workspace.
_NOT_ACCESSIBLE = frozenset({"WORKSPACE_OUTSIDE_ALLOWED_ROOT", "WORKSPACE_NOT_FOUND"})

# Image-drop refusals the daemon can return, with the outward status each maps
# to. They keep their own code rather than collapsing into INTERNAL_ERROR
# because every one of them has a different next step for the user, and none of
# them reveals anything about the node's filesystem (ADR 0024).
_UPLOAD_ERROR_STATUS: dict[str, tuple[str, int]] = {
    "FILE_UPLOAD_TOO_LARGE": (
        "The image is larger than 4 MiB",
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    ),
    "FILE_UPLOAD_UNSUPPORTED_TYPE": (
        "Only PNG, JPEG, GIF and WebP images can be dropped",
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ),
    "FILE_UPLOAD_QUOTA_EXCEEDED": (
        "This session has reached its image quota",
        status.HTTP_429_TOO_MANY_REQUESTS,
    ),
    "FILE_UPLOAD_FAILED": (
        "The node could not store the image",
        status.HTTP_502_BAD_GATEWAY,
    ),
    "FILE_UPLOAD_DISABLED": (
        "This node does not accept image drop",
        status.HTTP_403_FORBIDDEN,
    ),
    # General file upload (ADR 0026) adds three refusals of its own. FILE_EXISTS is
    # the most common one and it is not a failure: never overwriting is the property
    # that lets this path exist without a version precondition or an undo.
    "FILE_EXISTS": (
        "A file or directory with that name already exists",
        status.HTTP_409_CONFLICT,
    ),
    "FILE_UPLOAD_NO_SPACE": (
        "The node does not have enough free disk space",
        status.HTTP_507_INSUFFICIENT_STORAGE,
    ),
    "FILE_UPLOAD_FILES_DISABLED": (
        "This node does not accept file upload",
        status.HTTP_403_FORBIDDEN,
    ),
    # Download (ADR 0028) adds one refusal of its own. The other three it can
    # produce - FILE_DENIED, FILE_TOO_LARGE, FILE_NOT_FOUND - are already mapped
    # by `_map_error`, and reusing them says something true: a file the preview
    # refuses to show is refused here on the same grounds, by the same function
    # on the node.
    "FILE_DOWNLOAD_DISABLED": (
        "This node does not hand workspace files back",
        status.HTTP_403_FORBIDDEN,
    ),
}


# --- Read-only binary preview (ADR 0029, plan/31/04) ---

# The wire allowlist (contract 1.11.0 mime enum) and the kind each mime implies. The
# X-Cliora-Preview-Mime header is taken from here, never copied from the node.
PREVIEW_MIMES: dict[str, str] = {
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/gif": "image",
    "application/pdf": "pdf",
}
PREVIEW_CHUNK_SIZE = 524288
PREVIEW_MAX_CHUNKS = 32
PREVIEW_MAX_SIZE = PREVIEW_CHUNK_SIZE * PREVIEW_MAX_CHUNKS
PREVIEW_MAX_SIDE = 8192
# How long the close at the end of a stream may take. It is best effort: the
# daemon's idle TTL is the backstop for a close that does not arrive.
_PREVIEW_CLOSE_SECONDS = 1.0
_PREVIEW_AUDIT_SECONDS = 2.0

# In-band refusals: each keeps its own code and status, because each has a different
# next step (the `_map_error` principle). None of them is answered with a download.
_PREVIEW_DENIAL_STATUS: dict[str, int] = {
    "FILE_DENIED": status.HTTP_403_FORBIDDEN,
    "FILE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "FILE_PERMISSION_DENIED": status.HTTP_403_FORBIDDEN,
    "FILE_TOO_LARGE": status.HTTP_413_CONTENT_TOO_LARGE,
    "FILE_PREVIEW_UNSUPPORTED": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "FILE_PREVIEW_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "FILE_PREVIEW_LIMIT": status.HTTP_413_CONTENT_TOO_LARGE,
}
# Node-level refusals, which arrive as error frames.
_PREVIEW_ERROR_STATUS: dict[str, int] = {
    "FILE_PREVIEW_DISABLED": status.HTTP_403_FORBIDDEN,
    "FILE_PREVIEW_EXPIRED": status.HTTP_502_BAD_GATEWAY,
    "NODE_BUSY": status.HTTP_503_SERVICE_UNAVAILABLE,
}


@dataclass(slots=True)
class BinaryPreviewDenial:
    """An in-band refusal, returned rather than raised so the route can commit the
    sensitive-denial audit row before it raises (ADR 0029 §6 step 5)."""

    code: str
    status_code: int
    details: dict[str, Any]

    def to_error(self) -> ApiError:
        return ApiError(
            self.code,
            safe_message(self.code, "This file cannot be previewed"),
            self.status_code,
            details=self.details,
        )


class _PreviewStreams:
    """Streams in flight per user and per node, in this process (BP-OM-09: Central is
    assumed to serve a node's WebSocket from one process). No lock is needed: the check
    and the increment happen with no await between them."""

    def __init__(self) -> None:
        self.by_user: Counter[uuid.UUID] = Counter()
        self.by_node: Counter[uuid.UUID] = Counter()

    def acquire(
        self, user_id: uuid.UUID, node_id: uuid.UUID, *, per_user: int, per_node: int
    ) -> bool:
        if self.by_user[user_id] >= per_user or self.by_node[node_id] >= per_node:
            return False
        self.by_user[user_id] += 1
        self.by_node[node_id] += 1
        return True

    def release(self, user_id: uuid.UUID, node_id: uuid.UUID) -> None:
        self.by_user[user_id] -= 1
        self.by_node[node_id] -= 1
        if self.by_user[user_id] <= 0:
            del self.by_user[user_id]
        if self.by_node[node_id] <= 0:
            del self.by_node[node_id]


_preview_streams = _PreviewStreams()


@dataclass(slots=True)
class BinaryPreviewStream:
    """A validated handle on the node, owned by one HTTP response. Whoever holds it
    must end with `FileRelayService.stream_binary_preview` running to its `finally`,
    which closes the handle and frees the stream slot on every path."""

    node_id: uuid.UUID
    session_id: uuid.UUID
    actor_id: uuid.UUID
    preview_id: str
    kind: str
    mime: str
    size: int
    chunk_count: int
    width: int | None
    height: int | None
    started: float
    _released: bool = field(default=False)
    # Set when stream_binary_preview's `finally` has run (handle closed).
    finished: bool = field(default=False)

    def headers(self) -> dict[str, str]:
        """ADR 0029 §6's header set. There is no Content-Disposition: this is not a
        download and must not look like one."""
        h = {
            "Content-Length": str(self.size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store, private",
            "Vary": "Authorization",
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Cliora-Preview-Mime": self.mime,
            "X-Cliora-Preview-Kind": self.kind,
        }
        if self.kind == "image" and self.width is not None and self.height is not None:
            h["X-Cliora-Preview-Width"] = str(self.width)
            h["X-Cliora-Preview-Height"] = str(self.height)
        return h

    def release_slot(self) -> None:
        if not self._released:
            self._released = True
            _preview_streams.release(self.actor_id, self.node_id)


def _reject_rel_path(rel: str, *, allow_empty: bool = False) -> str:
    """Validate a workspace-relative path at the HTTP boundary before any daemon
    call: no absolute path, no `..` segment, no NUL/control char, no `~`. Returns
    the cleaned path. Mirrors the daemon guard (defence in depth, SEC-001)."""
    if rel is None:
        rel = ""
    if rel in ("", ".") and allow_empty:
        return "."
    if not rel:
        raise ApiError("FILE_INVALID_PATH", "A path is required", status.HTTP_400_BAD_REQUEST)
    if len(rel) > 4096:
        raise ApiError("FILE_INVALID_PATH", "Path too long", status.HTTP_400_BAD_REQUEST)
    if any(ord(ch) < 0x20 for ch in rel):
        raise ApiError(
            "FILE_INVALID_PATH",
            "Path contains control characters",
            status.HTTP_400_BAD_REQUEST,
        )
    if rel.startswith("/") or rel.startswith("~"):
        raise ApiError(
            "FILE_INVALID_PATH",
            "Path must be workspace-relative",
            status.HTTP_400_BAD_REQUEST,
        )
    clean = posixpath.normpath(rel)
    if clean == ".." or clean.startswith("../"):
        raise ApiError(
            "FILE_INVALID_PATH",
            "Path escapes the workspace",
            status.HTTP_400_BAD_REQUEST,
        )
    return clean


# The longest filename the daemon will store, in BYTES. The wire schema's
# maxLength counts code points, so 84 CJK characters plus an extension passes it
# at 88 characters and 256 bytes (measured: plan/15/07-open-measurements.md sec 2).
_MAX_FILENAME_BYTES = 255


def _reject_filename(name: str) -> str:
    """Validate a client-supplied filename at the HTTP boundary: exactly one path
    segment, no separator, no control characters, bounded in bytes.

    This runs on the value Starlette has already URL-decoded, and that ordering is
    the point: `%2F` decodes to `/` and `..%2F` to `../`, so a check applied to the
    raw query string would not see the separator at all. Mirrors the daemon's own
    check rather than replacing it (defence in depth, SEC-001) — Central validates
    so an obviously bad request never occupies a node connection, and the daemon
    validates because Central is not the only conceivable caller.
    """
    if not name:
        raise ApiError("FILE_INVALID_NAME", "A filename is required", status.HTTP_400_BAD_REQUEST)
    if len(name.encode("utf-8")) > _MAX_FILENAME_BYTES:
        raise ApiError("FILE_INVALID_NAME", "Filename too long", status.HTTP_400_BAD_REQUEST)
    if name in (".", ".."):
        raise ApiError("FILE_INVALID_NAME", "Invalid filename", status.HTTP_400_BAD_REQUEST)
    if "/" in name:
        raise ApiError(
            "FILE_INVALID_NAME",
            "A filename may not contain a path separator",
            status.HTTP_400_BAD_REQUEST,
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in name):
        raise ApiError(
            "FILE_INVALID_NAME",
            "Filename contains control characters",
            status.HTTP_400_BAD_REQUEST,
        )
    return name


def _keyword_digest(keyword: str) -> str:
    """Short, stable digest of a search keyword for correlation logs. The keyword
    itself may name a confidential project or file and must never be logged."""
    return hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:12]


class FileRelayService:
    def __init__(
        self,
        session: Any,
        *,
        registry: NodeConnectionRegistry | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._repo = SessionRepository(session)
        self._registry = registry or get_node_registry()
        self._audit = AuditService(session)
        self._settings = settings or get_settings()

    async def _resolve(self, session_id: uuid.UUID, viewer: User) -> TerminalSession:
        """Resolve the session, then authorize *this* user against it.

        Every filesystem operation goes through here, so the resource-scope check
        cannot be forgotten by a new caller: `viewer` is required (ADR 0016).
        Order matters — `session.view` is settled before the lookup, so a user
        without it cannot tell a missing session from someone else's (issue #93);
        existence and file access are settled before the online check, so a user
        without access learns nothing about the node's state.
        The session's workspace already sits inside an enabled root; the daemon
        re-canonicalizes on every operation regardless.
        """
        authz.authorize_session_lookup(viewer)
        s = await self._repo.get(session_id)
        if s is None:
            raise ApiError("SESSION_NOT_FOUND", "Session not found", status.HTTP_404_NOT_FOUND)
        authz.authorize_file_browse(viewer, s)
        if not self._registry.is_connected(s.node_id):
            raise ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)
        return s

    @asynccontextmanager
    async def _observe(
        self,
        op: str,
        *,
        session_id: uuid.UUID,
        node_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Measure, count and log one filesystem relay operation.

        Duration is monotonic. The correlation line carries ids, the operation,
        the outcome code and bounded volume counters — never a path, a search
        keyword, or file content (SEC-004, ADR 0015). The caller fills the
        yielded dict with the outcome (`code`) and volume detail.
        """
        started = time.monotonic()
        detail: dict[str, Any] = {"code": "OK"}
        try:
            yield detail
        except asyncio.CancelledError:
            # The browser aborted (tab closed, keyword changed): not an error.
            detail["code"] = "CANCELLED"
            metrics.increment(metrics.FILESYSTEM_RELAY_CANCEL_TOTAL, op=op)
            raise
        except ApiError as exc:
            detail["code"] = exc.code
            if exc.code == "REQUEST_TIMEOUT":
                metrics.increment(metrics.FILESYSTEM_RELAY_TIMEOUT_TOTAL, op=op)
            elif exc.code == "NODE_OFFLINE":
                metrics.increment(metrics.FILESYSTEM_NODE_DISCONNECT_TOTAL, op=op)
            raise
        finally:
            duration = time.monotonic() - started
            code = str(detail.get("code", "OK"))
            metrics.increment(metrics.FILESYSTEM_REQUEST_TOTAL, op=op, code=code)
            metrics.observe(metrics.FILESYSTEM_REQUEST_DURATION, duration, op=op)
            extra: dict[str, Any] = {
                "event": f"filesystem.{op}",
                "op": op,
                "code": code,
                "duration_ms": round(duration * 1000, 2),
                "session_id": str(session_id),
            }
            if node_id is not None:
                extra["node_id"] = str(node_id)
            if actor_id is not None:
                extra["user_id"] = str(actor_id)
            for key, value in detail.items():
                if key != "code" and value is not None:
                    extra[key] = value
            log.info("filesystem relay", extra=extra)

    async def list_dir(
        self,
        *,
        actor: User,
        session_id: uuid.UUID,
        path: str,
        cursor: str | None,
        entry_limit: int | None,
    ) -> dict[str, Any]:
        async with self._observe("list", session_id=session_id, actor_id=actor.id) as detail:
            node_id = (await self._resolve(session_id, actor)).node_id
            detail["node_id"] = str(node_id)
            rel = _reject_rel_path(path, allow_empty=True)
            payload: dict[str, Any] = {"session_id": str(session_id), "path": rel}
            if cursor:
                payload["cursor"] = cursor
            if entry_limit:
                payload["entry_limit"] = entry_limit
            message = await self._registry.request(
                node_id,
                "filesystem.list",
                payload,
                timeout_seconds=self._settings.file_list_timeout_seconds,
            )
            result = self._expect(message, "filesystem.entries")
            detail["entries"] = len(result.get("entries", []))
            detail["truncated"] = bool(result.get("truncated"))
            return result

    async def search(
        self,
        *,
        actor: User,
        session_id: uuid.UUID,
        keyword: str,
        root: str | None,
        max_results: int | None,
    ) -> dict[str, Any]:
        async with self._observe("search", session_id=session_id, actor_id=actor.id) as detail:
            node_id = (await self._resolve(session_id, actor)).node_id
            detail["node_id"] = str(node_id)
            if not keyword or len(keyword) > 256 or any(ord(ch) < 0x20 for ch in keyword):
                raise ApiError(
                    "FILE_INVALID_PATH",
                    "Invalid search keyword",
                    status.HTTP_400_BAD_REQUEST,
                )
            # A keyword can name a confidential project or file, so it is never
            # logged in the clear: a short digest correlates repeats instead
            # (ADR 0015 redaction).
            detail["keyword_digest"] = _keyword_digest(keyword)
            detail["keyword_length"] = len(keyword)
            payload: dict[str, Any] = {"session_id": str(session_id), "keyword": keyword}
            if root:
                payload["root"] = _reject_rel_path(root, allow_empty=True)
            if max_results:
                payload["max_results"] = max_results
            message = await self._registry.request(
                node_id,
                "filesystem.search",
                payload,
                timeout_seconds=self._settings.file_search_timeout_seconds,
            )
            result = self._expect(message, "filesystem.search_result")
            detail["results"] = len(result.get("results", []))
            detail["scanned"] = result.get("scanned_count")
            detail["partial"] = bool(result.get("partial"))
            detail["stopped_reason"] = result.get("stopped_reason")
            return result

    async def read_file(self, *, actor: User, session_id: uuid.UUID, path: str) -> dict[str, Any]:
        actor_id = actor.id
        async with self._observe("read", session_id=session_id, actor_id=actor_id) as detail:
            s = await self._resolve(session_id, actor)
            detail["node_id"] = str(s.node_id)
            rel = _reject_rel_path(path)
            message = await self._registry.request(
                s.node_id,
                "filesystem.read",
                {"session_id": str(session_id), "path": rel},
                timeout_seconds=self._settings.file_read_timeout_seconds,
            )
            payload = self._expect(message, "filesystem.content")
            if payload.get("success"):
                # Byte count only — never the content itself.
                detail["bytes"] = len(payload.get("content") or "")
            else:
                error = payload.get("error") or {}
                detail["code"] = str(error.get("code", "FILE_DENIED"))
                detail["denied_reason"] = error.get("reason")
                metrics.increment(
                    metrics.FILESYSTEM_DENIED_TOTAL,
                    code=str(error.get("code", "FILE_DENIED")),
                    reason=str(error.get("reason") or "unspecified"),
                )
            await self._maybe_audit_denied(actor_id, s.node_id, session_id, rel, payload)
            return payload

    async def upload_image(
        self, *, actor: User, session_id: uuid.UUID, data: bytes
    ) -> dict[str, Any]:
        """Relay one image to the node and return the path it was stored at.

        Central holds the bytes only for the duration of this call: they are
        base64'd, forwarded, and dropped. Nothing is written to disk, to the
        database, to a log line or to a metrics label (ADR 0024 sec 5). A byte
        stored here would raise three questions — how long, who can read it, is
        it in backups — and not storing it answers all three.
        """
        actor_id = actor.id
        async with self._observe("upload", session_id=session_id, actor_id=actor_id) as detail:
            s = await self._resolve_for_upload(session_id, actor)
            detail["node_id"] = str(s.node_id)
            detail["bytes"] = len(data)
            message = await self._registry.request(
                s.node_id,
                "filesystem.upload",
                {
                    "session_id": str(session_id),
                    "data": base64.b64encode(data).decode("ascii"),
                },
                timeout_seconds=self._settings.file_upload_timeout_seconds,
            )
            payload = self._expect(message, "filesystem.uploaded")
            detail["mime"] = payload.get("mime")
            await self._audit_upload(actor_id, s.node_id, session_id, payload, source="image")
            return payload

    async def store_file(
        self,
        *,
        actor: User,
        session_id: uuid.UUID,
        directory: str,
        filename: str,
        data: bytes,
    ) -> dict[str, Any]:
        """Relay one uploaded file to the node and return the path it was stored at.

        Central holds the bytes only for the duration of this call, the same as
        `upload_image`: they are base64'd, forwarded and dropped. Nothing is written
        to disk, to the database, to a log line or to a metrics label (ADR 0024 sec 5,
        which applies to this path unchanged).

        The filename does reach the audit record, and only there. An audit table has
        access control; a correlation log does not, and a filename can name a
        confidential project as readily as a search keyword can.
        """
        actor_id = actor.id
        async with self._observe("store", session_id=session_id, actor_id=actor_id) as detail:
            s = await self._resolve_for_upload(session_id, actor)
            detail["node_id"] = str(s.node_id)
            detail["bytes"] = len(data)
            rel_dir = _reject_rel_path(directory, allow_empty=True)
            name = _reject_filename(filename)
            message = await self._registry.request(
                s.node_id,
                "filesystem.store",
                {
                    "session_id": str(session_id),
                    "directory": rel_dir,
                    "filename": name,
                    "data": base64.b64encode(data).decode("ascii"),
                },
                timeout_seconds=self._settings.file_upload_timeout_seconds,
            )
            payload = self._expect(message, "filesystem.stored")
            await self._audit_upload(actor_id, s.node_id, session_id, payload, source="file")
            return payload

    async def download_file(
        self, *, actor: User, session_id: uuid.UUID, path: str
    ) -> tuple[str, bytes]:
        """Relay one file back from the node and return (rel_path, raw bytes).

        Gated on `file.browse`, not on a new action: a download is a read, and the
        three fixed roles cannot express "may preview but may not download" anyway
        (ADR 0028 sec 5). What that reuse costs is that `file.browse` now means more
        than it did - its holder gets the exact bytes of a file the preview would
        have shown only as text, and of one it would have refused to render at all.
        That cost is real and belongs in the release note rather than a footnote.

        Central holds the bytes only for the duration of this call, the same as the
        two upload paths in the other direction: they are decoded, handed to the
        response, and dropped. Nothing is written to disk, to the database, to a log
        line or to a metrics label. A byte stored here would raise three questions -
        how long, who can read it, is it in backups - and not storing it answers all
        three (ADR 0024 sec 5, which applies unchanged).

        Unlike `read_file` there is no in-band denial to unpack: every refusal
        arrives as an error frame and `_expect` turns it into an ApiError. That is
        forced by where the answer is going - the HTTP body on this path is the
        file, so a denial has nowhere to live except the status line.
        """
        actor_id = actor.id
        async with self._observe("download", session_id=session_id, actor_id=actor_id) as detail:
            s = await self._resolve(session_id, actor)
            detail["node_id"] = str(s.node_id)
            rel = _reject_rel_path(path)
            message = await self._registry.request(
                s.node_id,
                "filesystem.download",
                {"session_id": str(session_id), "path": rel},
                timeout_seconds=self._settings.file_download_timeout_seconds,
            )
            payload = self._expect(message, "filesystem.downloaded")
            try:
                data = base64.b64decode(payload.get("data") or "", validate=True)
            except (ValueError, TypeError) as exc:
                # A frame that passed the schema but does not decode means the node
                # and this process disagree about the wire, which is not something a
                # user can act on.
                raise ApiError(
                    "INTERNAL_ERROR",
                    "Node could not complete the request",
                    status.HTTP_502_BAD_GATEWAY,
                ) from exc
            # Byte count only - never the content, and never the path, which goes to
            # the audit table instead (it has access control; a log line does not).
            detail["bytes"] = len(data)
            stored_rel = str(payload.get("path") or rel)
            await self._audit_download(actor_id, s.node_id, session_id, stored_rel, len(data))
            return stored_rel, data

    async def _audit_download(
        self,
        actor_id: uuid.UUID,
        node_id: uuid.UUID,
        session_id: uuid.UUID,
        rel_path: str,
        size: int,
    ) -> None:
        """Record a successful download (ADR 0028 sec 7).

        The successful case is audited here because a download leaves a copy
        outside the platform. Binary preview has its own success audit with no
        path; the download record includes the selected relative path.

        `size_bytes`, not `bytes`: the latter is an exact-match forbidden metadata
        key and is stripped from every audit API response, so a number written under
        it would be recorded and then never readable.
        """
        try:
            await self._audit.record(
                audit.FILE_DOWNLOAD,
                user_id=actor_id,
                node_id=node_id,
                session_id=session_id,
                metadata={"path": rel_path, "size_bytes": size},
            )
        except Exception:
            # Same trade as the upload audit: the bytes have already left the node,
            # so failing the user's request would not un-send them. The gap is
            # counted and logged rather than hidden.
            metrics.increment(metrics.FILESYSTEM_AUDIT_ERROR_TOTAL, action="download")
            log.warning(
                "audit write failed",
                extra={"action": audit.FILE_DOWNLOAD, "session_id": str(session_id)},
            )

    # --- Read-only binary preview (ADR 0029 §6) ---

    @property
    def settings(self) -> Settings:
        return self._settings

    async def binary_preview_target(self, *, actor: User, session_id: uuid.UUID) -> TerminalSession:
        """Steps 2-4: session, file-browse scope (Viewer included, shell refused),
        node online, then the two capability gates. Both gates refuse BEFORE any frame
        is sent: an old daemon drops unknown types silently, so asking it would only
        turn into a timeout (ADR 0029 §9)."""
        s = await self._resolve(session_id, actor)
        if not self._settings.binary_preview_enabled or not self._registry.binary_preview(
            s.node_id
        ):
            raise ApiError(
                "FILE_PREVIEW_UNSUPPORTED_NODE",
                safe_message("FILE_PREVIEW_UNSUPPORTED_NODE"),
                status.HTTP_409_CONFLICT,
            )
        return s

    async def open_binary_preview(
        self, *, actor: User, target: TerminalSession, path: str
    ) -> BinaryPreviewStream | BinaryPreviewDenial:
        """Steps 6-8: validate the path, take a stream slot, and open a snapshot on the
        node. An in-band refusal is RETURNED; a sensitive one has already been added to
        the session's audit through the shared `_maybe_audit_denied`, and the caller
        commits before raising."""
        actor_id = actor.id
        session_id = target.id
        async with self._observe(
            "binary_preview_open", session_id=session_id, actor_id=actor_id
        ) as detail:
            detail["node_id"] = str(target.node_id)
            rel = _reject_rel_path(path)
            settings = self._settings
            if not _preview_streams.acquire(
                actor_id,
                target.node_id,
                per_user=settings.file_preview_streams_per_user,
                per_node=settings.file_preview_streams_per_node,
            ):
                raise ApiError(
                    "FILE_PREVIEW_BUSY",
                    safe_message("FILE_PREVIEW_BUSY"),
                    status.HTTP_429_TOO_MANY_REQUESTS,
                )
            owned = False
            try:
                started = time.monotonic()
                message = await self._registry.request(
                    target.node_id,
                    "filesystem.preview_open",
                    {"session_id": str(session_id), "path": rel},
                    timeout_seconds=settings.file_preview_open_timeout_seconds,
                )
                if message.type == "error" and message.error:
                    code = str(message.error.get("code", "INTERNAL_ERROR"))
                    if code in _PREVIEW_ERROR_STATUS:
                        raise ApiError(code, safe_message(code), _PREVIEW_ERROR_STATUS[code])
                    raise self._map_error(code)
                payload = self._expect(message, "filesystem.preview_opened")
                if not payload.get("success"):
                    error = payload.get("error") or {}
                    code = str(error.get("code", "FILE_DENIED"))
                    reason = str(error.get("reason") or "unspecified")
                    detail["code"] = code
                    detail["denied_reason"] = reason
                    metrics.increment(metrics.FILESYSTEM_DENIED_TOTAL, code=code, reason=reason)
                    await self._maybe_audit_denied(
                        actor_id, target.node_id, session_id, rel, payload
                    )
                    details: dict[str, Any] = {"reason": reason}
                    for key in ("size", "limit"):
                        if isinstance(error.get(key), int):
                            details[key] = error[key]
                    return BinaryPreviewDenial(
                        code, _PREVIEW_DENIAL_STATUS.get(code, status.HTTP_403_FORBIDDEN), details
                    )
                stream = await self._accept_opened(target, actor_id, payload, started)
                detail["kind"] = stream.kind
                detail["bytes"] = stream.size
                owned = True
                return stream
            finally:
                if not owned:
                    _preview_streams.release(actor_id, target.node_id)

    async def _accept_opened(
        self, target: TerminalSession, actor_id: uuid.UUID, payload: dict[str, Any], started: float
    ) -> BinaryPreviewStream:
        """Re-check the daemon's verdict before anything is forwarded. The schema has
        already been applied on the socket; this is the part it cannot express, and a
        second look at the part a browser decoder depends on. A bad answer is a 502,
        and the handle it named is closed."""
        preview_id = payload.get("preview_id")
        mime = payload.get("mime")
        kind = PREVIEW_MIMES.get(mime) if isinstance(mime, str) else None
        size = payload.get("size")
        count = payload.get("chunk_count")
        width, height = payload.get("width"), payload.get("height")
        ok = (
            isinstance(preview_id, str)
            and len(preview_id) == 26
            and kind is not None
            and payload.get("kind") == kind
            and isinstance(size, int)
            and 1 <= size <= PREVIEW_MAX_SIZE
            and payload.get("chunk_size") == PREVIEW_CHUNK_SIZE
            and count == max(1, math.ceil(size / PREVIEW_CHUNK_SIZE))
        )
        if ok and kind == "image":
            ok = all(isinstance(v, int) and 1 <= v <= PREVIEW_MAX_SIDE for v in (width, height))
        if ok and kind == "pdf":
            ok = width is None and height is None
        if not ok:
            if isinstance(preview_id, str):
                await self._close_preview(target.node_id, target.id, preview_id)
            raise ApiError(
                "INTERNAL_ERROR", "Unexpected node response", status.HTTP_502_BAD_GATEWAY
            )
        assert isinstance(preview_id, str) and isinstance(mime, str) and kind is not None
        assert isinstance(size, int) and isinstance(count, int)
        return BinaryPreviewStream(
            node_id=target.node_id,
            session_id=target.id,
            actor_id=actor_id,
            preview_id=preview_id,
            kind=kind,
            mime=mime,
            size=size,
            chunk_count=count,
            width=width if kind == "image" else None,
            height=height if kind == "image" else None,
            started=started,
        )

    async def stream_binary_preview(
        self, stream: BinaryPreviewStream
    ) -> AsyncGenerator[bytes, None]:
        """Steps 10-12: pull one chunk at a time and hand it on. The next chunk is only
        requested after the previous one was accepted by the ASGI send, so a slow
        client slows the node rather than filling Central's memory.

        A failure mid-stream ends the body early. The response already promised
        `Content-Length`, so the browser gets a network error — never a partial image
        and never a download. On EVERY exit — success, node error, budget, client
        gone — the handle is closed at once; the daemon's idle TTL is only a backstop.
        """
        settings = self._settings
        outcome = "OK"
        sent = 0
        chunks = 0
        try:
            for index in range(stream.chunk_count):
                remaining = settings.file_preview_total_seconds - (
                    time.monotonic() - stream.started
                )
                if remaining <= 0:
                    outcome = "REQUEST_TIMEOUT"
                    metrics.increment(metrics.FILESYSTEM_RELAY_TIMEOUT_TOTAL, op="binary_preview")
                    return
                try:
                    message = await self._registry.request(
                        stream.node_id,
                        "filesystem.preview_chunk",
                        {
                            "session_id": str(stream.session_id),
                            "preview_id": stream.preview_id,
                            "index": index,
                        },
                        timeout_seconds=min(settings.file_preview_chunk_timeout_seconds, remaining),
                    )
                except ApiError as exc:
                    outcome = exc.code
                    return
                data = self._preview_chunk(message, stream, index)
                if data is None:
                    outcome = _chunk_outcome(message)
                    return
                sent += len(data)
                chunks += 1
                yield data
        except (asyncio.CancelledError, GeneratorExit):
            outcome = "CANCELLED"
            metrics.increment(metrics.FILESYSTEM_RELAY_CANCEL_TOTAL, op="binary_preview")
            raise
        finally:
            stream.finished = True
            await self._close_preview(stream.node_id, stream.session_id, stream.preview_id)
            stream.release_slot()
            metrics.increment(metrics.FILESYSTEM_REQUEST_TOTAL, op="binary_preview", code=outcome)
            log.info(
                "filesystem relay",
                extra={
                    "event": "filesystem.binary_preview",
                    "op": "binary_preview",
                    "code": outcome,
                    "kind": stream.kind,
                    "chunks": chunks,
                    "bytes": sent,
                    "duration_ms": round((time.monotonic() - stream.started) * 1000, 2),
                    "session_id": str(stream.session_id),
                    "node_id": str(stream.node_id),
                    "user_id": str(stream.actor_id),
                },
            )

    async def abandon_binary_preview(self, stream: BinaryPreviewStream) -> None:
        """For a response whose body never started (the client left before the first
        chunk): an async generator that never ran does not run its `finally`, so the
        handle is closed and the slot freed here instead. A no-op otherwise."""
        if stream.finished:
            return
        stream.finished = True
        await self._close_preview(stream.node_id, stream.session_id, stream.preview_id)
        stream.release_slot()
        metrics.increment(metrics.FILESYSTEM_REQUEST_TOTAL, op="binary_preview", code="CANCELLED")

    def _preview_chunk(
        self, message: ControlMessage, stream: BinaryPreviewStream, index: int
    ) -> bytes | None:
        """The chunk's bytes, or None if the frame is not exactly the chunk asked for."""
        if message.type != "filesystem.preview_data":
            return None
        payload = message.payload
        if payload.get("preview_id") != stream.preview_id or payload.get("index") != index:
            return None
        try:
            data = base64.b64decode(str(payload.get("data", "")), validate=True)
        except (binascii.Error, ValueError):
            return None
        last = index == stream.chunk_count - 1
        expected = stream.size - PREVIEW_CHUNK_SIZE * index if last else PREVIEW_CHUNK_SIZE
        return data if len(data) == expected else None

    async def _close_preview(
        self, node_id: uuid.UUID, session_id: uuid.UUID, preview_id: str
    ) -> None:
        """Send preview_close, shielded from the cancellation that may be ending the
        stream and bounded to one second. Best effort by design."""
        with anyio.CancelScope(shield=True), anyio.move_on_after(_PREVIEW_CLOSE_SECONDS):
            try:
                await self._registry.request(
                    node_id,
                    "filesystem.preview_close",
                    {"session_id": str(session_id), "preview_id": preview_id},
                    timeout_seconds=_PREVIEW_CLOSE_SECONDS,
                )
            except ApiError:
                pass

    async def _audit_preview_success(
        self, stream: BinaryPreviewStream, *, request_id: str | None = None
    ) -> None:
        """OD-6: `file.binary_preview` with kind, mime and size_bytes — never the path.
        Written on its own short session, like the RBAC-denial middleware, because the
        request's session and a streamed body do not share a lifetime this relies on.
        A failed write is counted and logged, not turned into a failed preview."""
        from app.db.engine import get_database

        try:
            with anyio.CancelScope(shield=True):
                with anyio.move_on_after(_PREVIEW_AUDIT_SECONDS) as deadline:
                    async with get_database().session() as own:
                        await AuditService(own).record(
                            audit.FILE_BINARY_PREVIEW,
                            user_id=stream.actor_id,
                            node_id=stream.node_id,
                            session_id=stream.session_id,
                            request_id=request_id,
                            metadata={
                                "kind": stream.kind,
                                "mime": stream.mime,
                                "size_bytes": stream.size,
                            },
                        )
                        await own.commit()
                if deadline.cancel_called:
                    raise TimeoutError("binary preview audit deadline")
        except (Exception, asyncio.CancelledError) as exc:
            metrics.increment(metrics.FILESYSTEM_AUDIT_ERROR_TOTAL, action="binary_preview")
            log.warning(
                "audit write failed",
                extra={"action": audit.FILE_BINARY_PREVIEW, "session_id": str(stream.session_id)},
            )
            if isinstance(exc, asyncio.CancelledError):
                raise

    async def _resolve_for_upload(self, session_id: uuid.UUID, viewer: User) -> TerminalSession:
        """Same resolution as `_resolve`, gated on `file.upload` instead of
        `file.browse`. Kept separate rather than parameterised so that neither
        check can be reached by passing the wrong argument."""
        authz.authorize_session_lookup(viewer)
        s = await self._repo.get(session_id)
        if s is None:
            raise ApiError("SESSION_NOT_FOUND", "Session not found", status.HTTP_404_NOT_FOUND)
        authz.authorize_file_upload(viewer, s)
        if not self._registry.is_connected(s.node_id):
            raise ApiError("NODE_OFFLINE", "Node is not connected", status.HTTP_409_CONFLICT)
        return s

    async def _audit_upload(
        self,
        actor_id: uuid.UUID,
        node_id: uuid.UUID,
        session_id: uuid.UUID,
        payload: dict[str, Any],
        source: str = "image",
    ) -> None:
        """Record a successful write (ADR 0024 W3, ADR 0026 sec 6).

        One action for both upload paths, with `source` telling them apart, because
        the verb is the same and splitting it would make every audit query a union
        of two keys.

        The relative path is recorded either way, but for different reasons. On the
        image path the platform chose it (ADR 0024 D11). On the file path the *user*
        chose it — and it is still recordable, because the user already sees that
        path: they picked it in the tree. Without it, W3's question ("who put what
        here") has only a counter for an answer. Content is never recorded on either.
        """
        metadata: dict[str, Any] = {
            "path": payload.get("path"),
            "bytes": payload.get("size"),
            "source": source,
        }
        if source == "image":
            # Only the image path sniffs a type, so only it has one to record. An
            # empty mime would be worse than an absent one.
            metadata["mime"] = payload.get("mime")
        try:
            await self._audit.record(
                audit.FILE_UPLOAD,
                user_id=actor_id,
                node_id=node_id,
                session_id=session_id,
                metadata=metadata,
            )
        except Exception:
            # Same trade as the sensitive-read audit: the write already happened
            # on the node, so failing the user's request would not un-write it.
            # The gap is counted and logged rather than hidden.
            metrics.increment(metrics.FILESYSTEM_AUDIT_ERROR_TOTAL, action="upload")
            log.warning(
                "audit write failed",
                extra={"action": audit.FILE_UPLOAD, "session_id": str(session_id)},
            )

    async def _maybe_audit_denied(
        self,
        actor_id: uuid.UUID,
        node_id: uuid.UUID,
        session_id: uuid.UUID,
        rel: str,
        payload: dict[str, Any],
    ) -> None:
        """Record a sensitive-read denial with only a classification + extension
        (never rel_path/stem/content, ADR 0014). Non-sensitive denials
        (symlink/outside/not-regular) are not audited."""
        if payload.get("success"):
            return
        error = payload.get("error") or {}
        if error.get("code") != "FILE_DENIED":
            return
        reason = error.get("reason")
        if reason not in _SENSITIVE_REASONS:
            return
        ext = os.path.splitext(rel)[1].lstrip(".").lower()
        try:
            await self._audit.record(
                audit.FILE_SENSITIVE_READ_DENIED,
                user_id=actor_id,
                node_id=node_id,
                session_id=session_id,
                metadata={"classification": reason, "extension": ext},
            )
        except Exception:
            # An audit write failure must not fail the user's request (the denial
            # itself already happened on the node); it is counted and logged so
            # the gap is visible.
            metrics.increment(metrics.FILESYSTEM_AUDIT_ERROR_TOTAL, action="sensitive_read")
            log.exception(
                "sensitive-read audit write failed",
                extra={
                    "event": "filesystem.audit_failed",
                    "session_id": str(session_id),
                    "node_id": str(node_id),
                    "classification": reason,
                },
            )

    def _expect(self, message: ControlMessage, want_type: str) -> dict[str, Any]:
        """Return the payload of a correlated daemon response, mapping a daemon
        error frame to a safe outward ApiError. Content/existence-probing codes
        collapse to a single 'cannot access' (ADR 0014)."""
        if message.type == want_type:
            return message.payload
        if message.type == "error" and message.error:
            code = str(message.error.get("code", "INTERNAL_ERROR"))
            raise self._map_error(code)
        raise ApiError("INTERNAL_ERROR", "Unexpected node response", status.HTTP_502_BAD_GATEWAY)

    def _map_error(self, code: str) -> ApiError:
        if code in _NOT_ACCESSIBLE:
            return ApiError("FILE_NOT_FOUND", "Cannot access path", status.HTTP_404_NOT_FOUND)
        if code == "WORKSPACE_NOT_DIRECTORY":
            return ApiError(
                "WORKSPACE_NOT_DIRECTORY",
                "Not a directory",
                status.HTTP_400_BAD_REQUEST,
            )
        if code == "WORKSPACE_PERMISSION_DENIED":
            return ApiError(
                "FILE_PERMISSION_DENIED",
                "Permission denied",
                status.HTTP_403_FORBIDDEN,
            )
        # Three codes that, before ADR 0028, only ever arrived *in band* on
        # `filesystem.content` with success:false. The download path has no in-band
        # body to put a denial in - the body is the file - so they arrive as error
        # frames here, and each keeps its own status because each has a different
        # next step: change nothing (denied), use the terminal (too large), refresh
        # the tree (gone).
        if code == "FILE_DENIED":
            return ApiError(
                "FILE_DENIED",
                "This file cannot be downloaded",
                status.HTTP_403_FORBIDDEN,
            )
        if code == "FILE_TOO_LARGE":
            return ApiError(
                "FILE_TOO_LARGE",
                "The file is larger than the 4 MiB download limit",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        if code == "FILE_NOT_FOUND":
            return ApiError("FILE_NOT_FOUND", "Cannot access path", status.HTTP_404_NOT_FOUND)
        if code == "WORKSPACE_INVALID":
            return ApiError("FILE_INVALID_PATH", "Invalid path", status.HTTP_400_BAD_REQUEST)
        if code == "SESSION_NOT_FOUND":
            return ApiError("SESSION_NOT_FOUND", "Session not found", status.HTTP_404_NOT_FOUND)
        # Image-drop refusals pass through with their own code. Collapsing them
        # into INTERNAL_ERROR would tell a user whose quota is full that the
        # server broke — and each of these has a different, actionable next step
        # (ADR 0024; the codes are in the wire enum, so they really can arrive).
        upload = _UPLOAD_ERROR_STATUS.get(code)
        if upload is not None:
            message, http_status = upload
            return ApiError(code, message, http_status)
        return ApiError(
            "INTERNAL_ERROR",
            "Node could not complete the request",
            status.HTTP_502_BAD_GATEWAY,
        )


def _chunk_outcome(message: ControlMessage) -> str:
    if message.type == "error" and message.error:
        return str(message.error.get("code", "INTERNAL_ERROR"))
    return "INTERNAL_ERROR"
