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
import hashlib
import os
import posixpath
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import status

from app import metrics
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
}


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


def keyword_digest(keyword: str) -> str:
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
        Order matters — existence and view access are settled before the online
        check, so a user without access learns nothing about the node's state.
        The session's workspace already sits inside an enabled root; the daemon
        re-canonicalizes on every operation regardless.
        """
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
            detail["keyword_digest"] = keyword_digest(keyword)
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

    async def _resolve_for_upload(self, session_id: uuid.UUID, viewer: User) -> TerminalSession:
        """Same resolution as `_resolve`, gated on `file.upload` instead of
        `file.browse`. Kept separate rather than parameterised so that neither
        check can be reached by passing the wrong argument."""
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
