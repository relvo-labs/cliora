"""Symmetric encryption for third-party integration credentials (P11, ADR 0022).

This module exists for exactly one kind of value: a credential the platform holds on a
user's behalf and must be able to *use* later — the tunnel provider's token. That rules out
hashing, which is what every other secret in this system gets (passwords, enrollment
tokens, node credentials, tunnel basic-auth passwords). It is the only reversible secret in
the schema, so its handling is narrow on purpose.

Four rules, each with a reason:

1. **No key, no storage.** With `CLIORA_SECRET_ENCRYPTION_KEY` unset, `encrypt` raises
   instead of returning something. "Store it in plain text for now and encrypt later" has
   no way back: the plaintext that was already written stays written, and the later
   migration cannot un-disclose it. The API turns this into an explicit refusal
   (`SECRET_KEY_MISSING`) that names the missing configuration.
2. **A fresh nonce per write**, stored next to the ciphertext. AES-GCM loses
   confidentiality outright when a nonce is reused under the same key, so the nonce is
   generated here and never supplied by a caller.
3. **The fingerprint is of the plaintext, and it is short.** It answers "is this the token
   I rotated last week" for a person reading the settings page, and it is the only thing
   about the credential any interface ever returns. Eight hex characters is enough to
   compare and far too little to reconstruct.
4. **The plaintext is not held.** `decrypt` returns it to the one caller that needs it
   (assembling a `tunnel.open` frame) and nothing stores it in a dataclass, a cache, or a
   log line.

AES-GCM comes from `cryptography`, already a dependency: no new package for this.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.settings import get_settings

# 96-bit nonces are the size AES-GCM is specified and optimised for.
NONCE_BYTES = 12
KEY_BYTES = 32
# Bound to the value the credential is allowed to be; a caller passing something much
# larger is a bug somewhere upstream, not a value to quietly encrypt.
MAX_PLAINTEXT_BYTES = 4096
# Domain separator: the same token encrypted for a different purpose must not decrypt in
# this one. AES-GCM authenticates this alongside the ciphertext.
_AAD = b"cliora-integration-credential-v1"


class SecretKeyMissing(RuntimeError):
    """The deployment has no encryption key, so a credential cannot be stored."""


class SecretDecryptionFailed(RuntimeError):
    """The ciphertext did not authenticate under the configured key.

    Raised for a wrong key, a truncated value, or tampering — deliberately one exception
    for all three, because the caller's response is the same (ask for the credential
    again) and distinguishing them would only tell an attacker which of the three it was.
    """


def _key() -> bytes:
    raw = get_settings().secret_encryption_key.strip()
    if not raw:
        raise SecretKeyMissing("CLIORA_SECRET_ENCRYPTION_KEY is not configured")
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error) as exc:  # pragma: no cover - settings validate first
        raise SecretKeyMissing("CLIORA_SECRET_ENCRYPTION_KEY is not valid base64") from exc
    if len(key) != KEY_BYTES:
        raise SecretKeyMissing("CLIORA_SECRET_ENCRYPTION_KEY must decode to 32 bytes")
    return key


def is_available() -> bool:
    """Whether this deployment can store a credential at all.

    Reported to the settings UI so an administrator sees "this environment cannot store
    credentials" before typing one in, rather than after pressing save.
    """
    try:
        _key()
    except SecretKeyMissing:
        return False
    return True


def encrypt(plaintext: str) -> tuple[bytes, bytes]:
    """Encrypt a credential. Returns (ciphertext, nonce)."""
    if not plaintext:
        raise ValueError("refusing to encrypt an empty credential")
    data = plaintext.encode("utf-8")
    if len(data) > MAX_PLAINTEXT_BYTES:
        raise ValueError("credential is too large to be one")
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, data, _AAD)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes) -> str:
    """Recover a credential for immediate use by the caller."""
    if not ciphertext or len(nonce) != NONCE_BYTES:
        raise SecretDecryptionFailed("stored credential is malformed")
    try:
        return AESGCM(_key()).decrypt(nonce, ciphertext, _AAD).decode("utf-8")
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise SecretDecryptionFailed("stored credential could not be decrypted") from exc


def fingerprint(plaintext: str) -> str:
    """Eight hex characters of SHA-256 over the credential.

    Not a security control — it is a human aid, and the only part of a credential any
    interface returns. It is over the plaintext rather than the ciphertext so that
    re-encrypting the same token (a nonce change) keeps the same fingerprint: otherwise
    "did the credential change" could not be answered from it.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:8]
