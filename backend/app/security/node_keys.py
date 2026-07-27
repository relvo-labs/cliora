"""Ed25519 node challenge-response primitives."""

from __future__ import annotations

import base64
import binascii
import secrets
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN = b"cliora-node-auth-v1\n"
ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _new_ulid_like() -> str:
    """A 26-char Crockford-base32 identifier (ULID-shaped, random)."""
    return "".join(secrets.choice(ULID_ALPHABET) for _ in range(26))


def new_challenge_id() -> str:
    return _new_ulid_like()


def new_request_id() -> str:
    """A fresh correlation id for a Central-initiated control request."""
    return _new_ulid_like()


def signing_message(node_id: uuid.UUID, challenge_id: str, nonce: str) -> bytes:
    return DOMAIN + f"{node_id}\n{challenge_id}\n{nonce}".encode()


def valid_public_key(public_key_b64: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
    except (ValueError, binascii.Error):
        return False
    return True


def verify_signature(
    public_key_b64: str, signature_b64: str, node_id: uuid.UUID, challenge_id: str, nonce: str
) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(
            base64.b64decode(signature_b64, validate=True),
            signing_message(node_id, challenge_id, nonce),
        )
    except (ValueError, binascii.Error, InvalidSignature):
        return False
    return True
