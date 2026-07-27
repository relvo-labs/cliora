"""Authentication use cases (FR-AUTH-001, ADR 0007).

The route owns the transaction (commit/rollback); this service only mutates the
session (audit rows, token_version bumps) and returns typed results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import User
from app.repositories.users import UserRepository
from app.security.passwords import dummy_verify, verify_password
from app.security.tokens import (
    TokenError,
    TokenExpiredError,
    decode_access_token,
    decode_refresh_token,
    issue_access_token,
    issue_refresh_token,
)
from app.services import audit


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    tokens: TokenPair
    user: User


def _unauthorized(code: str, message: str) -> ApiError:
    return ApiError(code, message, status.HTTP_401_UNAUTHORIZED)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = audit.AuditService(session)

    def _pair(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=issue_access_token(user.id, user.role.name),
            refresh_token=issue_refresh_token(user.id, user.token_version),
        )

    async def login(self, username: str, password: str) -> LoginResult:
        """Audit both outcomes. A failed sign-in is the security event that makes
        credential stuffing visible, so it is recorded with the attempted username
        (never the password) and, when the account exists, its id. The outward
        error stays identical in every failure case."""
        user = await self._users.get_by_username(username)
        if user is None:
            dummy_verify()  # equalize timing so unknown users are indistinguishable
            await self._record_failure(username, None, "unknown_user")
            raise _unauthorized("INVALID_CREDENTIALS", "Invalid username or password")
        if not verify_password(user.password_hash, password):
            await self._record_failure(username, user.id, "bad_password")
            raise _unauthorized("INVALID_CREDENTIALS", "Invalid username or password")
        if not user.is_active:
            await self._record_failure(username, user.id, "account_disabled")
            raise _unauthorized("ACCOUNT_DISABLED", "Account is disabled")
        await self._audit.record(audit.USER_LOGIN, user_id=user.id)
        return LoginResult(tokens=self._pair(user), user=user)

    async def _record_failure(self, username: str, user_id: uuid.UUID | None, reason: str) -> None:
        # `username` is the attempted value, bounded so a garbage flood cannot
        # inflate the row. The password is never touched.
        await self._audit.record(
            audit.USER_LOGIN_FAILED,
            user_id=user_id,
            metadata={"username": username[:64], "reason": reason},
        )

    async def refresh(self, refresh_token: str) -> TokenPair:
        try:
            claims = decode_refresh_token(refresh_token)
        except TokenExpiredError as exc:
            raise _unauthorized("TOKEN_EXPIRED", "Refresh token has expired") from exc
        except TokenError as exc:
            raise _unauthorized("TOKEN_INVALID", "Refresh token is invalid or expired") from exc
        user = await self._users.get_by_id(claims.user_id)
        if user is None or not user.is_active or user.token_version != claims.token_version:
            raise _unauthorized("TOKEN_INVALID", "Refresh token is invalid or expired")
        return self._pair(user)

    async def logout(self, user: User) -> None:
        await self._users.bump_token_version(user)
        await self._audit.record(audit.USER_LOGOUT, user_id=user.id)

    async def authenticate_access(self, token: str) -> User:
        """Resolve the current user from a bearer access token (WS/HTTP boundary)."""
        try:
            claims = decode_access_token(token)
        except TokenExpiredError as exc:
            raise _unauthorized("TOKEN_EXPIRED", "Access token has expired") from exc
        except TokenError as exc:
            raise _unauthorized("TOKEN_INVALID", "Access token is invalid or expired") from exc
        user = await self._users.get_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise _unauthorized("TOKEN_INVALID", "Access token is invalid or expired")
        return user
