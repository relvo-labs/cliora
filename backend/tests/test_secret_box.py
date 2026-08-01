"""Integration-credential encryption (P11, ADR 0022).

The point of these tests is not that AES-GCM works — `cryptography` has its own tests. It
is that this module's four refusals hold, because each one is a place where a convenient
mistake would be invisible: storing plaintext when no key is set, reusing a nonce,
returning something decryptable under the wrong key, or leaking the credential through the
fingerprint.
"""

from __future__ import annotations

import base64
import secrets

import pytest

from app.security import secret_box
from app.settings import Settings, get_settings


def _with_key(monkeypatch: pytest.MonkeyPatch, key: bytes | None) -> None:
    """Point `get_settings()` at a Settings carrying (or lacking) an encryption key."""
    encoded = base64.b64encode(key).decode() if key is not None else ""
    settings = Settings(secret_encryption_key=encoded)
    monkeypatch.setattr(secret_box, "get_settings", lambda: settings)


def test_a_credential_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    ciphertext, nonce = secret_box.encrypt("xGBTh6cy58q")
    assert secret_box.decrypt(ciphertext, nonce) == "xGBTh6cy58q"


def test_the_ciphertext_does_not_contain_the_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    ciphertext, _ = secret_box.encrypt("xGBTh6cy58q")
    assert b"xGBTh6cy58q" not in ciphertext


def test_every_write_uses_a_fresh_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nonce reuse under one key destroys AES-GCM's confidentiality outright, so the nonce
    is generated inside this module and a caller has no way to supply one."""
    _with_key(monkeypatch, secrets.token_bytes(32))
    first_ct, first_nonce = secret_box.encrypt("xGBTh6cy58q")
    second_ct, second_nonce = secret_box.encrypt("xGBTh6cy58q")
    assert first_nonce != second_nonce
    assert first_ct != second_ct


def test_a_wrong_key_cannot_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    ciphertext, nonce = secret_box.encrypt("xGBTh6cy58q")
    _with_key(monkeypatch, secrets.token_bytes(32))
    with pytest.raises(secret_box.SecretDecryptionFailed):
        secret_box.decrypt(ciphertext, nonce)


def test_tampering_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    ciphertext, nonce = secret_box.encrypt("xGBTh6cy58q")
    flipped = bytes([ciphertext[0] ^ 0x01]) + ciphertext[1:]
    with pytest.raises(secret_box.SecretDecryptionFailed):
        secret_box.decrypt(flipped, nonce)


def test_without_a_key_encryption_refuses_rather_than_storing_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode this prevents has no way back: plaintext already written stays
    written, and encrypting later cannot un-disclose it."""
    _with_key(monkeypatch, None)
    assert secret_box.is_available() is False
    with pytest.raises(secret_box.SecretKeyMissing):
        secret_box.encrypt("xGBTh6cy58q")


def test_is_available_reports_a_usable_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    assert secret_box.is_available() is True


def test_a_short_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings validates length at startup; this is the second layer, for a Settings
    object built by hand in a test or a script."""
    monkeypatch.setattr(
        secret_box,
        "get_settings",
        lambda: Settings.model_construct(
            secret_encryption_key=base64.b64encode(secrets.token_bytes(16)).decode()
        ),
    )
    with pytest.raises(secret_box.SecretKeyMissing):
        secret_box.encrypt("xGBTh6cy58q")


def test_a_malformed_stored_value_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    with pytest.raises(secret_box.SecretDecryptionFailed):
        secret_box.decrypt(b"", b"0" * 12)
    with pytest.raises(secret_box.SecretDecryptionFailed):
        secret_box.decrypt(b"something", b"short")


def test_the_fingerprint_is_stable_across_re_encryption(monkeypatch: pytest.MonkeyPatch) -> None:
    """It is over the plaintext, not the ciphertext: re-encrypting the same token must not
    look like a changed credential in the settings page."""
    _with_key(monkeypatch, secrets.token_bytes(32))
    secret_box.encrypt("xGBTh6cy58q")
    secret_box.encrypt("xGBTh6cy58q")
    assert secret_box.fingerprint("xGBTh6cy58q") == secret_box.fingerprint("xGBTh6cy58q")


def test_the_fingerprint_discloses_no_credential_characters() -> None:
    token = "xGBTh6cy58q"
    printed = secret_box.fingerprint(token)
    assert len(printed) == 8
    assert token not in printed
    # A short digest, not a prefix of the value: the whole reason it is safe to show.
    assert not token.startswith(printed)
    assert secret_box.fingerprint("xGBTh6cy58r") != printed


def test_an_empty_credential_is_not_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    with pytest.raises(ValueError):
        secret_box.encrypt("")


def test_an_absurdly_large_value_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _with_key(monkeypatch, secrets.token_bytes(32))
    with pytest.raises(ValueError):
        secret_box.encrypt("A" * (secret_box.MAX_PLAINTEXT_BYTES + 1))


def test_settings_rejects_a_key_of_the_wrong_length() -> None:
    """Startup is where a wrong-length key must fail: otherwise it fails on the first
    encryption, which happens while somebody is typing a credential into a form."""
    with pytest.raises(ValueError, match="32 bytes"):
        Settings(secret_encryption_key=base64.b64encode(secrets.token_bytes(16)).decode())


def test_settings_rejects_a_key_that_is_not_base64() -> None:
    with pytest.raises(ValueError, match="base64"):
        Settings(secret_encryption_key="not base64 at all !!")


def test_no_key_configured_is_a_valid_deployment() -> None:
    """Most deployments do not use this integration, and they must still start."""
    assert Settings().secret_encryption_key == ""
    assert get_settings() is not None
