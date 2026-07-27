import uuid

import pytest

from app.db.models import Role, User
from app.security.hashing import generate_secret, keyed_hash, verify_hash
from app.security.passwords import hash_password, verify_password
from app.security.tokens import (
    TokenError,
    TokenExpiredError,
    decode_access_token,
    decode_refresh_token,
    issue_access_token,
    issue_refresh_token,
)
from app.services import ws_ticket
from app.services.rbac import NODE_MANAGE, NODE_VIEW, has_action
from app.services.ws_ticket import WsTicketService
from app.settings import Settings


def test_password_hash_roundtrip() -> None:
    digest = hash_password("correct horse")
    assert digest != "correct horse"
    assert verify_password(digest, "correct horse")
    assert not verify_password(digest, "wrong")


def test_keyed_hash_is_deterministic_and_verifies() -> None:
    secret = generate_secret("enroll_")
    assert secret.startswith("enroll_")
    digest = keyed_hash(secret)
    assert digest == keyed_hash(secret)
    assert verify_hash(secret, digest)
    assert not verify_hash(secret + "x", digest)


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = issue_access_token(user_id, "Admin")
    claims = decode_access_token(token)
    assert claims.user_id == user_id
    assert claims.role == "Admin"


def test_refresh_token_roundtrip_and_type_isolation() -> None:
    user_id = uuid.uuid4()
    refresh = issue_refresh_token(user_id, 7)
    claims = decode_refresh_token(refresh)
    assert claims.user_id == user_id
    assert claims.token_version == 7
    # An access token must not validate as a refresh token and vice versa.
    with pytest.raises(TokenError):
        decode_refresh_token(issue_access_token(user_id, "Admin"))
    with pytest.raises(TokenError):
        decode_access_token(refresh)


def test_expired_token_raises_expired_subclass() -> None:
    # An expired token must be distinguishable from an invalid one so the
    # boundary can return TOKEN_EXPIRED (prompt refresh) vs TOKEN_INVALID.
    expired = Settings(access_token_ttl_seconds=-1)
    token = issue_access_token(uuid.uuid4(), "Admin", settings=expired)
    with pytest.raises(TokenExpiredError):
        decode_access_token(token)


def test_tampered_token_is_invalid_not_expired() -> None:
    token = issue_access_token(uuid.uuid4(), "Admin")
    with pytest.raises(TokenError) as exc:
        decode_access_token(token + "tamper")
    assert not isinstance(exc.value, TokenExpiredError)


def test_tampered_token_is_rejected() -> None:
    token = issue_access_token(uuid.uuid4(), "Admin")
    with pytest.raises(TokenError):
        decode_access_token(token + "tamper")


def _user_with_actions(*actions: str) -> User:
    role = Role(name="Test", permissions={"actions": list(actions)})
    return User(username="u", password_hash="x", display_name="U", role=role)


def test_rbac_has_action() -> None:
    admin = _user_with_actions(NODE_VIEW, NODE_MANAGE)
    viewer = _user_with_actions(NODE_VIEW)
    assert has_action(admin, NODE_MANAGE)
    assert not has_action(viewer, NODE_MANAGE)
    assert has_action(viewer, NODE_VIEW)


def test_ws_ticket_single_use_and_resource_bound() -> None:
    service = WsTicketService(ttl_seconds=60)
    user_id = uuid.uuid4()
    ticket = service.issue(user_id, "nodes/abc")
    # Wrong resource is rejected without consuming a fresh ticket's validity.
    assert service.consume("nonexistent", "nodes/abc") is None
    assert service.consume(ticket, "nodes/other") is None
    # Correct resource resolves the user, then the ticket is burned.
    ticket2 = service.issue(user_id, "nodes/abc")
    assert service.consume(ticket2, "nodes/abc") == user_id
    assert service.consume(ticket2, "nodes/abc") is None


def test_ws_ticket_expiry() -> None:
    service = WsTicketService(ttl_seconds=-1)
    ticket = service.issue(uuid.uuid4(), "r")
    assert service.consume(ticket, "r") is None


def test_ws_ticket_equal_boundary_is_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    # A ticket consumed at exactly its expiry instant is treated as expired.
    clock = {"now": 100.0}
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: clock["now"])
    service = WsTicketService(ttl_seconds=0)  # expires at issue time (100.0)
    ticket = service.issue(uuid.uuid4(), "r")
    assert service.consume(ticket, "r") is None
