from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.clock import ensure_aware_utc, now_utc


def test_now_utc_is_aware_utc() -> None:
    value = now_utc()
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_ensure_aware_utc_rejects_naive() -> None:
    with pytest.raises(ValueError):
        ensure_aware_utc(datetime(2026, 7, 24, 9, 0, 0))


def test_ensure_aware_utc_normalizes_offset() -> None:
    taipei = datetime(2026, 7, 24, 17, 0, 0, tzinfo=ZoneInfo("Asia/Taipei"))
    normalized = ensure_aware_utc(taipei)
    assert normalized == datetime(2026, 7, 24, 9, 0, 0, tzinfo=UTC)
    assert normalized.utcoffset() == timedelta(0)
