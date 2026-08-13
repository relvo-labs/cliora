"""Card artifacts: receiving them safely and serving them safely (ADR 0030 Part B).

Two halves, and the second is the one this phase is most likely to get wrong.

**Receiving** is six ordered steps, and the order is part of the safety: authorize,
check the declared size, check the three quotas, verify the digest, *determine* the
content type, then write. The quota check is before the write rather than after, which
makes it imprecise under concurrency — two simultaneous uploads can both pass — and
that cost is accepted: a quota is an operational guard rail, not a security boundary,
and a project-wide advisory lock would make two runs wait on each other.

**Serving** never renders. Cliora is a single-origin deployment (ADR 0020), so "open in
a new tab" and "render inline" are the same act, and there is no version of this that
is safe because the user asked for it. `content_type` is determined here from the
extension and the magic bytes and **never** from the uploader's declaration — that
field is the primary stored-XSS entry point in the phase.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import Task, TaskArtifact, TaskArtifactBlob
from app.services import audit as audit_actions
from app.services.activity import ACTOR_AGENT, ACTOR_USER, ARTIFACT_ATTACHED, ActivityService
from app.services.audit import AuditService
from app.settings import Settings, get_settings

# The closed table. Anything outside it becomes `application/octet-stream`, and that
# default is the point: **an unrecognised thing is binary, and binary can only be
# downloaded.**
_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    # The two most common artifacts a run produces. Kept as text so the preview works:
    # making the commonest output download-only would quietly train people to stop
    # attaching diffs.
    ".patch": "text/plain",
    ".diff": "text/plain",
}
_MAGIC = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": b"GIF8",
}
# What may be shown inline. Markdown is served as **plain text**: rendering it would
# execute embedded HTML, and a file called `report.md` whose content is HTML passes
# every text check there is.
PREVIEWABLE = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "text/plain",
    # Markdown **is** previewable, and the preview handler serves it as `text/plain`.
    # Leaving it out would have made the second most common artifact download-only,
    # which is the same mistake as excluding `.patch`: it quietly teaches people to
    # stop attaching things. `application/json` is deliberately *not* here — it has no
    # reader in the console, and an unread preview is a surface with no purpose.
    "text/markdown",
}
BINARY = "application/octet-stream"


def determine_content_type(filename: str, data: bytes) -> str:
    """Extension plus magic bytes, and the uploader's declaration discarded.

    A `.md` whose content is HTML still becomes `text/markdown`, and that is fine —
    markdown is previewed as plain text, so it cannot render either way.
    """
    dot = filename.rfind(".")
    if dot < 0:
        return BINARY
    declared = _EXTENSIONS.get(filename[dot:].lower())
    if declared is None:
        return BINARY
    magic = _MAGIC.get(declared)
    if magic is not None:
        return declared if data.startswith(magic) else BINARY
    if declared.startswith("text/") or declared == "application/json":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return BINARY
    return declared


class ArtifactService:
    def __init__(self, session: AsyncSession, *, settings: Settings | None = None) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._audit = AuditService(session)
        self._activity = ActivityService(session)

    async def require(self, artifact_id: uuid.UUID) -> TaskArtifact:
        row = await self._session.get(TaskArtifact, artifact_id)
        if row is None:
            raise ApiError("NOT_FOUND", "Artifact not found", status.HTTP_404_NOT_FOUND)
        return row

    async def list_for(self, task_id: uuid.UUID) -> list[TaskArtifact]:
        return list(
            (
                await self._session.execute(
                    select(TaskArtifact)
                    .where(TaskArtifact.task_id == task_id)
                    .order_by(TaskArtifact.created_at.desc())
                )
            ).scalars()
        )

    async def blob(self, artifact_id: uuid.UUID) -> bytes:
        row = await self._session.get(TaskArtifactBlob, artifact_id)
        if row is None:
            # A soft-deleted artifact keeps its metadata and loses its bytes, so this
            # is the normal answer for one — 410 rather than 404, because the record of
            # who deleted it and why is deliberately still there.
            raise ApiError("ARTIFACT_DELETED", "That artifact was deleted", status.HTTP_410_GONE)
        return row.bytes

    async def attach(
        self,
        *,
        task: Task,
        filename: str,
        data: bytes,
        declared_sha256: str,
        run_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
        uploader_kind: str,
        user_id: uuid.UUID | None,
        runner_id: uuid.UUID | None,
    ) -> TaskArtifact:
        settings = self._settings
        if len(data) > settings.artifact_max_bytes:
            raise ApiError(
                "ARTIFACT_TOO_LARGE",
                "That file is larger than the per-file limit",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                details={"size": len(data), "limit": settings.artifact_max_bytes},
            )
        if run_id is not None:
            count = (
                await self._session.execute(
                    select(func.count())
                    .select_from(TaskArtifact)
                    .where(TaskArtifact.run_id == run_id, TaskArtifact.deleted_at.is_(None))
                )
            ).scalar() or 0
            if count >= settings.artifact_run_max_count:
                raise ApiError(
                    "ARTIFACT_RUN_LIMIT",
                    "This run has attached as many artifacts as it may",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    details={"count": int(count), "limit": settings.artifact_run_max_count},
                )
        used = (
            await self._session.execute(
                select(func.coalesce(func.sum(TaskArtifact.size), 0)).where(
                    TaskArtifact.project_id == task.project_id,
                    TaskArtifact.deleted_at.is_(None),
                )
            )
        ).scalar() or 0
        quota = settings.artifact_project_quota_mb * 1024 * 1024
        if int(used) + len(data) > quota:
            raise ApiError(
                "ARTIFACT_PROJECT_QUOTA",
                "This project's artifact quota is full",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                details={"used": int(used), "limit": quota},
            )

        digest = hashlib.sha256(data).hexdigest()
        if declared_sha256 and declared_sha256.lower() != digest:
            # Not tamper protection — the connection is TLS. It catches a **truncated**
            # upload, which should fail rather than become a broken artifact.
            raise ApiError(
                "ARTIFACT_DIGEST_MISMATCH",
                "The upload did not match its stated digest; it may have been truncated",
                status.HTTP_400_BAD_REQUEST,
            )

        artifact = TaskArtifact(
            id=uuid.uuid4(),
            task_id=task.id,
            project_id=task.project_id,
            run_id=run_id,
            message_id=message_id,
            filename=filename[:255],
            content_type=determine_content_type(filename, data),
            size=len(data),
            sha256=digest,
            storage_ref="",
            uploaded_by_kind=uploader_kind,
            uploaded_by_user_id=user_id,
            uploaded_by_runner_id=runner_id,
        )
        artifact.storage_ref = f"db:{artifact.id}"
        self._session.add(artifact)
        self._session.add(TaskArtifactBlob(artifact_id=artifact.id, bytes=data))
        await self._session.flush()
        await self._audit.record(
            audit_actions.ARTIFACT_UPLOAD,
            user_id=user_id,
            metadata={
                "artifact_id": str(artifact.id),
                "task_id": str(task.id),
                "size": artifact.size,
                "content_type": artifact.content_type,
            },
        )
        await self._activity.record(
            ARTIFACT_ATTACHED,
            project_id=task.project_id,
            task_id=task.id,
            actor_user_id=user_id,
            actor_kind=ACTOR_USER if uploader_kind == "user" else ACTOR_AGENT,
            # **No filename.** It is on `FORBIDDEN_METADATA_KEYS` with the path keys,
            # and the guard is right: the project timeline is a project-wide feed that
            # every role can read, while the filename belongs on the card's own
            # artifact list. Putting it here would be a small, silent widening — which
            # is how the actor-identity channel P4 closed got reopened once already.
            payload={
                "card_ref": task.card_ref,
                "artifact_id": str(artifact.id),
                "size": artifact.size,
                "content_type": artifact.content_type,
            },
        )
        return artifact

    async def delete(
        self, *, artifact: TaskArtifact, reason: str, actor_id: uuid.UUID
    ) -> TaskArtifact:
        """Soft here, hard for the bytes, and the asymmetry is deliberate.

        Requiring a reason is pointless if the delete erases who gave it; but a quota
        that cannot be freed by deleting something is not a quota. Metadata stays,
        content goes (ADR 0030 Part B).
        """
        if not reason.strip():
            raise ApiError(
                "INVALID_ARGUMENT",
                "Deleting an artifact requires a reason",
                status.HTTP_400_BAD_REQUEST,
            )
        if artifact.deleted_at is not None:
            return artifact
        artifact.deleted_at = now_utc()
        artifact.deleted_by = actor_id
        artifact.delete_reason = reason.strip()[:2000]
        blob = await self._session.get(TaskArtifactBlob, artifact.id)
        if blob is not None:
            await self._session.delete(blob)
        await self._session.flush()
        await self._audit.record(
            audit_actions.ARTIFACT_DELETE,
            user_id=actor_id,
            metadata={"artifact_id": str(artifact.id), "reason": artifact.delete_reason},
        )
        return artifact
