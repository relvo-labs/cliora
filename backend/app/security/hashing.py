"""Keyed hashing for enrollment tokens and node secrets (ADR 0008).

High-entropy secrets are stored as `HMAC-SHA256(pepper, value)` so they can be
looked up / compared without keeping plaintext. Comparison is constant-time.
Plaintext secrets are generated here and shown to the caller exactly once.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.settings import Settings, get_settings

ALGORITHM = "hmac-sha256"


def generate_secret(prefix: str = "", n_bytes: int = 32) -> str:
    """Return a URL-safe high-entropy secret, optionally prefixed (e.g. 'enroll_')."""
    return f"{prefix}{secrets.token_urlsafe(n_bytes)}"


def keyed_hash(value: str, settings: Settings | None = None) -> str:
    pepper = (settings or get_settings()).token_pepper.encode("utf-8")
    return hmac.new(pepper, value.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_hash(value: str, stored_hash: str, settings: Settings | None = None) -> bool:
    return hmac.compare_digest(keyed_hash(value, settings), stored_hash)
