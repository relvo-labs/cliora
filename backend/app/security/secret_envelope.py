"""Envelope encryption for a project's secrets (FR-RUNENV-002, ADR 0032 §3).

**This is not `secret_box.py`, and the separation is deliberate.** That module holds one
kind of value — the tunnel provider's token — under `CLIORA_SECRET_ENCRYPTION_KEY`, with
no envelope and no key version. Sharing it would tie two rotations together that happen
for different reasons (a provider change for one, personnel movement for the other), and
would turn a module that passed a security review for one purpose into one serving two.

Four properties, each with a reason:

1. **Envelope, not direct encryption.** Every row carries its own data key; the value is
   encrypted under the DEK and the DEK under the master key. Rotating the master key
   therefore rewraps DEKs and leaves every ciphertext byte-for-byte identical. Without
   this, rotation is a full-table re-encryption and nobody performs it twice.
2. **`key_version` exists from the first row**, not "added later". Without it the first
   rotation has no way to say which key opens which row.
3. **A fresh DEK per `seal`.** Two secrets with the same value are two completely
   different byte sequences at rest, so "these two projects use the same token" cannot
   be read out of the database.
4. **One decryption function, one caller.** `unseal` is the only way back to plaintext,
   and `GATE-SC-SINGLE-DECRYPT` asserts that exactly one module in `backend/app/` calls
   it. Every additional caller is another path a security review has to trace.

**What this design costs is written down rather than implied** (ADR 0032 §3): the master
key and the ciphertext share one trust boundary, there is no decryption audit, and losing
the key loses every secret irrecoverably. The envelope and `key_version` are what keep
the KMS upgrade to a single function — the one that unwraps a DEK.
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.settings import get_settings

KEY_BYTES = 32
NONCE_BYTES = 12
# The version a fresh row is stamped with when nothing says otherwise. Rotation moves
# it through `CLIORA_SECRET_MASTER_KEY_VERSION`; this is only the floor.
CURRENT_KEY_VERSION = 1
# The largest legitimate input measured is an RSA-4096 private key at 3 369 bytes
# (M-SC-1, plan/20/09-…md §1.2); an ed25519 key is 399 and a fine-grained PAT is 93.
# 8 KiB leaves 2.4x headroom over the largest, and the ceiling matters because eight of
# these have to fit inside a 64 KiB control frame alongside the task context.
MAX_PLAINTEXT_BYTES = 8192

# Domain separator. **Different from `secret_box`'s**, so a tunnel credential and a
# project secret cannot be decrypted in each other's context even under one key.
_AAD = b"cliora-project-secret-v1"

# Where an older master key lives once it has been rotated away from:
# `CLIORA_SECRET_MASTER_KEY_V1`, `…_V2`, and so on. Read straight from the environment
# rather than through `Settings`, because the set is open-ended and pydantic would need
# a field per version.
_OLD_KEY_ENV = "CLIORA_SECRET_MASTER_KEY_V{version}"

# The value `.env.example` ships with. Rejected at startup so that a deployment cannot
# reach production still holding it — the same treatment `jwt_secret` and `token_pepper`
# already get.
DEV_DEFAULT = "dev-only-change-me"


class MasterKeyMissing(RuntimeError):
    """No usable master key, so a secret can be neither stored nor read."""


class SecretDecryptionFailed(RuntimeError):
    """The ciphertext did not authenticate.

    One exception for a wrong key, a truncated value and tampering, following
    `secret_box`'s reasoning: the caller's response is the same in all three, and
    distinguishing them only tells an attacker which it was. The one thing the message
    *does* name is a **missing key version**, because that is an operator's mistake with
    an operator's fix, not an attacker's signal.
    """


@dataclass(frozen=True, slots=True)
class SealedSecret:
    """The five stored columns, as one value."""

    value_encrypted: bytes
    value_nonce: bytes
    dek_wrapped: bytes
    dek_nonce: bytes
    key_version: int


def master_key_status_for(raw: str) -> tuple[bool, str]:
    """Whether a candidate master key is usable, and if not, which of four ways.

    A pure function over a string: it does not touch `get_settings()`, so the settings
    validator can call it while `Settings` is still being constructed. The reason is
    stated in the four forms an operator can act on, rather than as one "invalid".
    """
    value = (raw or "").strip()
    if not value:
        return False, "is not set"
    if value == DEV_DEFAULT:
        return False, "is still the development default"
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        return False, "is not valid base64"
    if len(decoded) != KEY_BYTES:
        return False, f"must decode to {KEY_BYTES} bytes"
    return True, ""


def _decode(raw: str, *, label: str) -> bytes:
    ok, reason = master_key_status_for(raw)
    if not ok:
        raise MasterKeyMissing(f"{label} {reason}")
    return base64.b64decode(raw.strip(), validate=True)


def _current_key() -> bytes:
    return _decode(get_settings().secret_master_key, label="CLIORA_SECRET_MASTER_KEY")


def current_key_version() -> int:
    """Which version `seal` stamps onto a new row.

    A setting rather than the module constant, because rotation moves it: after moving
    to version 2, new rows must say 2 while the version-1 rows keep opening.
    """
    return max(1, get_settings().secret_master_key_version)


def _key_for_version(version: int) -> bytes:
    """The key that opens a row of this version.

    **The versioned environment variable is consulted first**, and that order is the
    whole correctness of rotation. The obvious implementation — "version N is whatever
    `CLIORA_SECRET_MASTER_KEY` currently holds" — works until the first rotation and
    then silently makes every pre-rotation row unreadable, because the current key is by
    then the *new* one. The rewrap test caught exactly that.

    A row whose key has been removed produces an error that **names the version**:
    "could not decrypt" sends an operator looking for corruption when the fix is to put
    one environment variable back.
    """
    name = _OLD_KEY_ENV.format(version=version)
    raw = os.environ.get(name, "")
    if raw:
        try:
            return _decode(raw, label=name)
        except MasterKeyMissing as exc:
            raise SecretDecryptionFailed(str(exc)) from exc
    if version == current_key_version():
        return _current_key()
    raise SecretDecryptionFailed(
        f"this secret was sealed under key version {version}, and {name} is not set"
    )


def is_available() -> bool:
    """Whether this deployment can store a secret at all.

    Reported to the console so an administrator sees "this environment cannot hold
    secrets" before typing one in, rather than after pressing save — the same courtesy
    `secret_box.is_available` provides for tunnel credentials.
    """
    try:
        _current_key()
    except MasterKeyMissing:
        return False
    return True


def seal(plaintext: str) -> SealedSecret:
    """Encrypt a value under a fresh data key, and the data key under the master key."""
    if not plaintext:
        raise ValueError("refusing to seal an empty secret")
    data = plaintext.encode("utf-8")
    if len(data) > MAX_PLAINTEXT_BYTES:
        raise ValueError("secret is larger than a secret should be")
    master = _current_key()
    dek = secrets.token_bytes(KEY_BYTES)
    value_nonce = secrets.token_bytes(NONCE_BYTES)
    dek_nonce = secrets.token_bytes(NONCE_BYTES)
    return SealedSecret(
        value_encrypted=AESGCM(dek).encrypt(value_nonce, data, _AAD),
        value_nonce=value_nonce,
        dek_wrapped=AESGCM(master).encrypt(dek_nonce, dek, _AAD),
        dek_nonce=dek_nonce,
        key_version=current_key_version(),
    )


def unseal(sealed: SealedSecret) -> str:
    """Recover a value for immediate use by its one caller.

    **The only path back to plaintext in this codebase.** Nothing here stores the result
    in a dataclass, a cache or a log line.
    """
    master = _key_for_version(sealed.key_version)
    try:
        dek = AESGCM(master).decrypt(sealed.dek_nonce, sealed.dek_wrapped, _AAD)
        return AESGCM(dek).decrypt(sealed.value_nonce, sealed.value_encrypted, _AAD).decode("utf-8")
    except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
        raise SecretDecryptionFailed("stored secret could not be decrypted") from exc


def rewrap(sealed: SealedSecret, *, to_version: int | None = None) -> SealedSecret:
    """Re-encrypt the data key under another master key, leaving the value untouched.

    `value_encrypted` and `value_nonce` come back byte-for-byte identical, and a test
    asserts exactly that: it is the property that makes rotation something other than a
    full-table re-encryption, and the property a KMS migration would rely on.
    """
    to_version = to_version or current_key_version()
    master_old = _key_for_version(sealed.key_version)
    try:
        dek = AESGCM(master_old).decrypt(sealed.dek_nonce, sealed.dek_wrapped, _AAD)
    except InvalidTag as exc:
        raise SecretDecryptionFailed("stored secret could not be decrypted") from exc
    master_new = _key_for_version(to_version)
    dek_nonce = secrets.token_bytes(NONCE_BYTES)
    return SealedSecret(
        value_encrypted=sealed.value_encrypted,
        value_nonce=sealed.value_nonce,
        dek_wrapped=AESGCM(master_new).encrypt(dek_nonce, dek, _AAD),
        dek_nonce=dek_nonce,
        key_version=to_version,
    )
