"""Enrollment token use cases (FR-INSTALL-001, SEC-003, ADR 0008).

Tokens are stored only as a keyed hash; the plaintext is returned exactly once
at creation. `consume` locks the row so concurrent registrations cannot exceed
`max_uses`, and treats expired/exhausted/revoked/unknown identically to avoid
enumeration.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.clock import now_utc
from app.db.models import EnrollmentToken
from app.repositories.enrollment import EnrollmentTokenRepository
from app.security.hashing import generate_secret, keyed_hash
from app.services import audit
from app.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class CreatedToken:
    token: EnrollmentToken
    plaintext: str


def token_status(token: EnrollmentToken) -> str:
    if not token.is_active:
        return "revoked"
    if token.used_count >= token.max_uses:
        return "exhausted"
    if now_utc() >= token.expires_at:
        return "expired"
    return "active"


class EnrollmentService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self._repo = EnrollmentTokenRepository(session)
        self._audit = audit.AuditService(session)
        self._settings = settings or get_settings()

    async def create(
        self,
        *,
        created_by: uuid.UUID,
        ttl_seconds: int | None = None,
        max_uses: int | None = None,
    ) -> CreatedToken:
        ttl = ttl_seconds or self._settings.enrollment_default_ttl_seconds
        uses = max_uses or self._settings.enrollment_default_max_uses
        if ttl <= 0 or uses <= 0:
            raise ApiError("INVALID_ARGUMENT", "ttl_seconds and max_uses must be positive")
        plaintext = generate_secret("enroll_")
        token = await self._repo.create(
            token_hash=keyed_hash(plaintext, self._settings),
            created_by=created_by,
            expires_at=now_utc() + timedelta(seconds=ttl),
            max_uses=uses,
        )
        await self._audit.record(
            audit.ENROLLMENT_CREATE,
            user_id=created_by,
            metadata={"token_id": str(token.id), "max_uses": uses, "ttl_seconds": ttl},
        )
        return CreatedToken(token=token, plaintext=plaintext)

    async def list(self) -> list[EnrollmentToken]:
        return list(await self._repo.list_all())

    async def revoke(self, token_id: uuid.UUID, *, actor_id: uuid.UUID) -> EnrollmentToken:
        token = await self._repo.get_by_id(token_id)
        if token is None:
            raise ApiError("NOT_FOUND", "Enrollment token not found", status.HTTP_404_NOT_FOUND)
        token.is_active = False
        await self._audit.record(
            audit.ENROLLMENT_REVOKE, user_id=actor_id, metadata={"token_id": str(token.id)}
        )
        return token

    async def consume(self, plaintext: str) -> EnrollmentToken:
        """Validate and atomically spend one use of a token (row-locked)."""
        token = await self._repo.lock_by_hash(keyed_hash(plaintext, self._settings))
        invalid = ApiError(
            "ENROLLMENT_TOKEN_INVALID",
            "Enrollment token is invalid, expired, or already used",
            status.HTTP_401_UNAUTHORIZED,
        )
        if token is None or token_status(token) != "active":
            raise invalid
        token.used_count += 1
        if token.used_count >= token.max_uses:
            token.is_active = False
        return token
