"""In-process metrics registry (tech §18.1, P3-09)."""

from __future__ import annotations

import pytest

from app import metrics


@pytest.fixture(autouse=True)
def _clean() -> None:
    metrics.reset()


def test_counter_accumulates_per_label_set() -> None:
    metrics.increment(metrics.FILESYSTEM_REQUEST_TOTAL, op="list", code="OK")
    metrics.increment(metrics.FILESYSTEM_REQUEST_TOTAL, op="list", code="OK")
    metrics.increment(metrics.FILESYSTEM_REQUEST_TOTAL, op="read", code="FILE_DENIED")

    assert metrics.counter_value(metrics.FILESYSTEM_REQUEST_TOTAL, op="list", code="OK") == 2
    assert (
        metrics.counter_value(metrics.FILESYSTEM_REQUEST_TOTAL, op="read", code="FILE_DENIED") == 1
    )
    # An unseen label set reads as zero rather than raising.
    assert metrics.counter_value(metrics.FILESYSTEM_REQUEST_TOTAL, op="search", code="OK") == 0


def test_label_order_does_not_create_a_new_series() -> None:
    metrics.increment("x_total", op="list", code="OK")
    metrics.increment("x_total", code="OK", op="list")
    assert metrics.counter_value("x_total", op="list", code="OK") == 2


def test_histogram_records_count_sum_and_buckets() -> None:
    for value in (0.01, 0.2, 1.5, 4.0, 30.0):
        metrics.observe(metrics.FILESYSTEM_REQUEST_DURATION, value, op="list")

    entry = metrics.histogram_value(metrics.FILESYSTEM_REQUEST_DURATION, op="list")
    assert entry is not None
    assert entry["count"] == 5
    assert entry["sum"] == pytest.approx(35.71)
    # Each sample lands in the first bucket it fits; 30 s exceeds every bound.
    assert entry["buckets"][0.05] == 1
    assert entry["buckets"][0.25] == 1
    assert entry["buckets"][2.0] == 1
    assert entry["buckets"][5.0] == 1
    assert entry["inf"] == 1


def test_snapshot_exposes_every_series_and_reset_clears_them() -> None:
    metrics.increment(metrics.FILESYSTEM_RELAY_TIMEOUT_TOTAL, op="search")
    metrics.observe(metrics.FILESYSTEM_REQUEST_DURATION, 0.4, op="read")

    snap = metrics.snapshot()
    assert metrics.FILESYSTEM_RELAY_TIMEOUT_TOTAL in snap["counters"]
    assert metrics.FILESYSTEM_REQUEST_DURATION in snap["histograms"]

    metrics.reset()
    assert metrics.snapshot() == {"counters": {}, "histograms": {}}
