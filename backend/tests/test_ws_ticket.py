"""Bounded ticket retention, driven by the same monotonic clock as consumption."""

import uuid

import pytest

from app.services import ws_ticket
from app.services.ws_ticket import WsTicketService
from app.settings import Settings


def test_unconsumed_expired_tickets_are_reclaimed_on_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    service = WsTicketService(60)
    uid = uuid.uuid4()
    abandoned = [service.issue(uid, "r") for _ in range(100)]
    now[0] = 160.0
    fresh = service.issue(uid, "r")
    assert len(service._tickets) == 1
    assert all(service.consume(ticket, "r") is None for ticket in abandoned)
    assert service.consume(fresh, "r") == uid


def test_ticket_store_is_bounded_across_users() -> None:
    service = WsTicketService(60)
    limit = Settings().ws_ticket_max_pending
    for _ in range(limit + 20):
        service.issue(uuid.uuid4(), "r")
        assert len(service._tickets) <= limit


def test_sweep_work_is_bounded_and_live_tickets_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    service = WsTicketService(60, max_pending=100, sweep_batch_size=3)
    uid = uuid.uuid4()
    abandoned = [service.issue(uid, "r") for _ in range(10)]
    now[0] = 150.0
    live = service.issue(uid, "r")
    now[0] = 160.0
    service.issue(uid, "r")
    assert len(service._tickets) == 9  # 11 - 3 expired + 1 new
    for _ in range(3):
        service.issue(uid, "r")
    assert not set(abandoned) & service._tickets.keys()
    assert len(service._tickets) == 5
    assert service.consume(live, "r") == uid


def test_capacity_evicts_oldest_and_keeps_new_ticket_usable() -> None:
    service = WsTicketService(60, max_pending=2, sweep_batch_size=1)
    first_user, other_user = uuid.uuid4(), uuid.uuid4()
    oldest = service.issue(first_user, "r")
    other = service.issue(other_user, "r")
    newest = service.issue(first_user, "r")
    assert len(service._tickets) == 2
    assert service.consume(oldest, "r") is None
    assert service.consume(other, "r") == other_user
    assert service.consume(newest, "r") == first_user
    assert service._tickets == {}


def test_wrong_resource_burns_ticket() -> None:
    service = WsTicketService(60)
    ticket = service.issue(uuid.uuid4(), "r")
    assert service.consume(ticket, "other") is None
    assert service.consume(ticket, "r") is None
    assert service._tickets == {}


@pytest.mark.parametrize("field", ["ws_ticket_max_pending", "ws_ticket_sweep_batch_size"])
@pytest.mark.parametrize("value", [0, -1])
def test_retention_settings_reject_nonpositive_bounds(field: str, value: int) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_factory_uses_retention_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(ws_ticket_max_pending=2, ws_ticket_sweep_batch_size=1)
    monkeypatch.setattr(ws_ticket, "get_settings", lambda: settings)
    monkeypatch.setattr(ws_ticket, "_service", None)
    service = ws_ticket.get_ws_ticket_service()
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    uid = uuid.uuid4()
    for _ in range(3):
        service.issue(uid, "r")
    assert len(service._tickets) == 2
    now[0] = 100.0 + settings.ws_ticket_ttl_seconds
    service.issue(uid, "r")
    assert len(service._tickets) == 2  # One expired entry removed, then one added.
