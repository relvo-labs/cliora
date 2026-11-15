"""Bounded ticket retention, driven by the same monotonic clock as consumption."""

import uuid

import pytest

from app.api.errors import ApiError
from app.services import ws_ticket
from app.services.ws_ticket import WsTicketService
from app.settings import Settings


def test_unconsumed_expired_tickets_are_reclaimed_on_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    # Isolate expiry reclamation from the separately tested per-user bound.
    service = WsTicketService(60, max_pending_per_user=128)
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
    for _ in range(limit):
        service.issue(uuid.uuid4(), "r")
    snapshot = service._tickets.copy()
    for _ in range(20):
        with pytest.raises(ApiError) as error:
            service.issue(uuid.uuid4(), "r")
        assert error.value.status_code == 503
        assert service._tickets == snapshot


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


def test_consumption_frees_capacity_without_evicting_other_users() -> None:
    service = WsTicketService(60, max_pending=2, sweep_batch_size=1)
    first_user, other_user = uuid.uuid4(), uuid.uuid4()
    oldest = service.issue(first_user, "r")
    other = service.issue(other_user, "r")
    assert service.consume(other, "r") == other_user
    newest = service.issue(first_user, "r")
    assert len(service._tickets) == 2
    assert service.consume(oldest, "r") == first_user
    assert service.consume(newest, "r") == first_user
    assert service._tickets == {}
    assert service._tickets_by_user == {}


def test_wrong_resource_burns_ticket() -> None:
    service = WsTicketService(60)
    ticket = service.issue(uuid.uuid4(), "r")
    assert service.consume(ticket, "other") is None
    assert service.consume(ticket, "r") is None
    assert service._tickets == {}
    assert service._tickets_by_user == {}


@pytest.mark.parametrize(
    "field",
    ["ws_ticket_max_pending", "ws_ticket_max_pending_per_user", "ws_ticket_sweep_batch_size"],
)
@pytest.mark.parametrize("value", [0, -1])
def test_retention_settings_reject_nonpositive_bounds(field: str, value: int) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_factory_uses_retention_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        ws_ticket_max_pending=3, ws_ticket_max_pending_per_user=2, ws_ticket_sweep_batch_size=1
    )
    monkeypatch.setattr(ws_ticket, "get_settings", lambda: settings)
    monkeypatch.setattr(ws_ticket, "_service", None)
    service = ws_ticket.get_ws_ticket_service()
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    uid = uuid.uuid4()
    service.issue(uid, "r")
    service.issue(uid, "r")
    service.issue(uuid.uuid4(), "r")
    with pytest.raises(ApiError) as user_full:
        service.issue(uid, "r")
    assert user_full.value.status_code == 429
    with pytest.raises(ApiError) as global_full:
        service.issue(uuid.uuid4(), "r")
    assert global_full.value.status_code == 503
    now[0] = 100.0 + settings.ws_ticket_ttl_seconds
    service.issue(uid, "r")
    assert len(service._tickets) == 3  # One expired entry removed, then one added.


def test_two_user_flood_never_invalidates_victim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: 100.0)
    service = WsTicketService(60)
    victim, attacker = uuid.uuid4(), uuid.uuid4()
    protected = service.issue(victim, "r")
    rejected = 0
    for _ in range(4096):
        try:
            service.issue(attacker, "r")
        except ApiError as exc:
            assert exc.status_code == 429
            rejected += 1
    assert service.consume(protected, "r") == victim
    assert rejected == 4096 - 32
    assert len(service._tickets) == 32


def test_per_user_33rd_rejected_then_recovers_on_consume_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    service = WsTicketService(60)
    uid = uuid.uuid4()
    tickets = [service.issue(uid, "r") for _ in range(32)]
    snapshot = service._tickets.copy()
    with pytest.raises(ApiError) as error:
        service.issue(uid, "r")
    assert (error.value.status_code, error.value.code) == (429, "WS_TICKET_BUSY")
    assert service._tickets == snapshot
    assert service.consume(tickets[0], "r") == uid
    service.issue(uid, "r")
    assert len(service._tickets) == 32
    now[0] = 160.0
    fresh = service.issue(uid, "r")
    assert len(service._tickets) == 1
    assert service.consume(fresh, "r") == uid


def test_global_capacity_rejects_without_eviction() -> None:
    service = WsTicketService(60, max_pending=2)
    victim, attacker = uuid.uuid4(), uuid.uuid4()
    protected = service.issue(victim, "r")
    other = service.issue(attacker, "r")
    snapshot = service._tickets.copy()
    with pytest.raises(ApiError) as error:
        service.issue(attacker, "r")
    assert (error.value.status_code, error.value.code) == (503, "INTERNAL_ERROR")
    assert service._tickets == snapshot
    assert service.consume(protected, "r") == victim
    assert service.consume(other, "r") == attacker


def test_user_expiry_recovers_behind_global_backlog_with_one_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    service = WsTicketService(60, max_pending=10, max_pending_per_user=2, sweep_batch_size=1)
    for _ in range(4):
        other = uuid.uuid4()
        service.issue(other, "r")
        service.issue(other, "r")
    now[0] = 101.0
    uid = uuid.uuid4()
    service.issue(uid, "r")
    service.issue(uid, "r")
    now[0] = 161.0
    fresh = service.issue(uid, "r")
    assert len(service._tickets) == 10  # One shared removal budget, not one per index.
    assert service.consume(fresh, "r") == uid


@pytest.mark.parametrize("expired", [False, True])
def test_consumed_users_leave_no_index_entries(
    monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    now = [100.0]
    monkeypatch.setattr(ws_ticket, "monotonic_seconds", lambda: now[0])
    service = WsTicketService(60)
    for _ in range(1000):
        uid = uuid.uuid4()
        ticket = service.issue(uid, "r")
        if expired:
            now[0] += 60
        assert service.consume(ticket, "r") == (None if expired else uid)
        assert service._tickets == {}
        assert service._tickets_by_user == {}
