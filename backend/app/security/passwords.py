"""Argon2id password hashing (ADR 0007).

`verify` runs a constant-ish path and callers should still run a dummy verify
for unknown users to avoid a timing oracle (see AuthService.login).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.settings import Settings, get_settings


def _hasher(settings: Settings | None = None) -> PasswordHasher:
    s = settings or get_settings()
    return PasswordHasher(
        time_cost=s.argon2_time_cost,
        memory_cost=s.argon2_memory_cost_kib,
        parallelism=s.argon2_parallelism,
    )


def hash_password(password: str, settings: Settings | None = None) -> str:
    return _hasher(settings).hash(password)


def verify_password(password_hash: str, password: str, settings: Settings | None = None) -> bool:
    try:
        return _hasher(settings).verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# A precomputed hash of a random value, used to spend comparable time when the
# username does not exist so login timing does not reveal account existence.
_DUMMY_HASH = PasswordHasher().hash("cliora-timing-equalizer")


def dummy_verify() -> None:
    try:
        PasswordHasher().verify(_DUMMY_HASH, "wrong")
    except Exception:
        pass
