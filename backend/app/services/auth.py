"""Authentication use cases (FR-AUTH-001, ADR 0007).

The route owns the transaction (commit/rollback); this service only mutates the
session (audit rows, token_version bumps) and returns typed results.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.db.models import User
from app.repositories.users import LoginLockoutRepository, UserRepository
from app.security.passwords import async_dummy_verify as dummy_verify
from app.security.passwords import async_verify_password as verify_password
from app.security.tokens import (
    TokenError,
    TokenExpiredError,
    decode_access_token,
    decode_refresh_token,
    issue_access_token,
    issue_refresh_token,
)
from app.services import audit
from app.services.login_protection import (
    LoginIPLimiter,
    LoginLockoutCleanup,
    get_login_ip_limiter,
    get_login_lockout_cleanup,
    throttled,
)
from app.settings import Settings, get_settings


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
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
        ip_limiter: LoginIPLimiter | None = None,
        cleanup: LoginLockoutCleanup | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ip_limiter = ip_limiter or get_login_ip_limiter()
        self._cleanup = cleanup or get_login_lockout_cleanup()
        self._lockouts = LoginLockoutRepository(session)
        self._session = session
        self._users = UserRepository(session)
        self._audit = audit.AuditService(session)

    def _pair(self, user: User) -> TokenPair:
        return TokenPair(
            access_token=issue_access_token(user.id, user.role.name),
            refresh_token=issue_refresh_token(user.id, user.token_version),
        )

    async def login(
        self, username: str, password: str, client_ip: str | None = None
    ) -> LoginResult:
        try:
            self._ip_limiter.check(client_ip)
        except ApiError:
            await self._record_failure(username, None, "ip_locked")
            raise
        if self._cleanup.claim():
            await self._lockouts.cleanup_idle(
                now=self._clock(),
                idle_seconds=self._settings.login_lockout_idle_retention_seconds,
                batch_size=self._settings.login_lockout_cleanup_batch_size,
            )
        state = await self._lockouts.for_update(username, now=self._clock())
        # Read time AFTER acquiring the row lock; another login may have queued us.
        now = self._clock()
        user = await self._users.get_by_username(username)
        user_id = user.id if user else None
        if state.locked_until is not None and state.locked_until > now:
            await self._record_failure(username, user_id, "account_locked")
            self._ip_limiter.failed(client_ip)
            # Both known and unknown locked keys skip all password work.
            raise throttled((state.locked_until - now).total_seconds())
        # An IP may have been banned while this attempt waited for the account.
        try:
            self._ip_limiter.check(client_ip)
        except ApiError:
            await self._record_failure(username, user_id, "ip_locked")
            raise
        if user is None:
            await dummy_verify()
            reason = "unknown_user"
        elif not await verify_password(user.password_hash, password):
            reason = "bad_password"
        elif not user.is_active:
            reason = "account_disabled"
        else:
            state.failures = 0
            state.locked_until = None
            await self._audit.record(audit.USER_LOGIN, user_id=user.id)
            return LoginResult(tokens=self._pair(user), user=user)

        thresholds = self._settings.login_lockout_thresholds
        durations = self._settings.login_lockout_seconds
        state.failures = min(state.failures + 1, thresholds[-1])
        duration = 0
        for threshold, seconds in zip(thresholds, durations, strict=True):
            if state.failures == threshold:
                duration = seconds
        if duration:
            state.locked_until = self._clock() + timedelta(seconds=duration)
            await self._record_failure(username, user_id, "lockout_started")
        else:
            await self._record_failure(username, user_id, reason)
        ip_delay = self._ip_limiter.failed(client_ip)
        if duration or ip_delay:
            raise throttled(max(duration, ip_delay))
        if reason == "account_disabled":
            raise _unauthorized("ACCOUNT_DISABLED", "Account is disabled")
        raise _unauthorized("INVALID_CREDENTIALS", "Invalid username or password")

    async def unlock_user(self, username: str, *, actor_id: uuid.UUID | None = None) -> None:
        state = await self._lockouts.for_update(username, now=self._clock())
        state.failures = 0
        state.locked_until = None
        await self._audit.record(
            audit.USER_UNLOCKED,
            user_id=actor_id,
            metadata={"username": username[:64]},
        )

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
        user = await self._users.get_by_id_for_update(claims.user_id)
        if user is None or not user.is_active or user.token_version != claims.token_version:
            raise _unauthorized("TOKEN_INVALID", "Refresh token is invalid or expired")
        # Rotate the per-user version before issuing the replacement pair. This
        # makes the presented refresh token single-use instead of leaving a
        # captured bearer reusable for its full 14-day lifetime.
        await self._users.bump_token_version(user)
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
