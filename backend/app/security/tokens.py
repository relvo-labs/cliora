"""JWT access/refresh tokens (ADR 0007).

Access tokens are short-lived bearers carrying the role for coarse checks;
refresh tokens carry `token_version` so a logout (which bumps the user's
`token_version`) invalidates every outstanding refresh without a blacklist.
All instants are aware UTC; an instant exactly at `exp` is treated as expired.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

import jwt

from app.clock import now_utc
from app.settings import Settings, get_settings

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


class TokenExpiredError(TokenError):
    """Raised specifically when a token's `exp` has passed.

    Distinguished from a generic invalid token so the access-token boundary can
    return the stable `TOKEN_EXPIRED` code (prompting a refresh) rather than the
    opaque `TOKEN_INVALID` (FR-AUTH-001)."""


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    role: str
    jti: str


@dataclass(frozen=True, slots=True)
class RefreshClaims:
    user_id: uuid.UUID
    token_version: int
    jti: str


def _encode(payload: dict[str, Any], ttl_seconds: int, settings: Settings) -> str:
    issued = now_utc()
    body = {
        **payload,
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(body, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str, expected_type: TokenType, settings: Settings) -> dict[str, Any]:
    try:
        claims: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
    if claims.get("type") != expected_type:
        raise TokenError("wrong token type")
    return claims


def issue_access_token(user_id: uuid.UUID, role: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return _encode(
        {"type": "access", "sub": str(user_id), "role": role}, s.access_token_ttl_seconds, s
    )


def issue_refresh_token(
    user_id: uuid.UUID, token_version: int, settings: Settings | None = None
) -> str:
    s = settings or get_settings()
    return _encode(
        {"type": "refresh", "sub": str(user_id), "token_version": token_version},
        s.refresh_token_ttl_seconds,
        s,
    )


def decode_access_token(token: str, settings: Settings | None = None) -> AccessClaims:
    claims = _decode(token, "access", settings or get_settings())
    return AccessClaims(
        user_id=uuid.UUID(claims["sub"]),
        role=str(claims["role"]),
        jti=str(claims["jti"]),
    )


def decode_refresh_token(token: str, settings: Settings | None = None) -> RefreshClaims:
    claims = _decode(token, "refresh", settings or get_settings())
    return RefreshClaims(
        user_id=uuid.UUID(claims["sub"]),
        token_version=int(claims["token_version"]),
        jti=str(claims["jti"]),
    )
