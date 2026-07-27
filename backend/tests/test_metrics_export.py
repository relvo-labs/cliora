"""The metrics registry's guarantees and the Prometheus exposition (P4-09, ADR 0018).

Two properties carry the weight here:

* **the label allowlist**, because metrics are the one sink with no redaction — a user
  id or a path in a label is published verbatim to anyone who can scrape, and a
  high-cardinality label is how a metrics backend runs out of memory;
* **cumulative histogram buckets**, because the registry stores them non-cumulatively
  and any quantile computed from the raw values would be silently wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import metrics
from app.api.http.metrics import PREFIX, _escape_label, render
from app.settings import Settings

ROOT = Path(__file__).parents[2]


@pytest.fixture(autouse=True)
def _clean_registry():
    metrics.reset()
    yield
    metrics.reset()


# --------------------------------------------------------------------------- #
# The label allowlist
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label",
    ["node_id", "user_id", "session_id", "path", "filename", "keyword", "username", "request_id"],
)
def test_an_identifying_label_is_refused(label: str) -> None:
    """Not dropped — refused. A metric that silently loses its labels looks like it
    works, and the mistake shows up much later as a dashboard that aggregated
    everything into one line."""
    with pytest.raises(metrics.LabelNotAllowed):
        metrics.increment("some_total", **{label: "value"})
    with pytest.raises(metrics.LabelNotAllowed):
        metrics.observe("some_duration_seconds", 0.1, **{label: "value"})


def test_the_forbidden_list_is_disjoint_from_the_allowlist() -> None:
    """Otherwise the explicit ban would be a lie: the allowlist decides, and a key in
    both would be accepted."""
    assert metrics.ALLOWED_LABELS & metrics.FORBIDDEN_LABELS == set()


def test_an_allowed_label_is_recorded() -> None:
    metrics.increment(metrics.DAEMON_REQUEST_TOTAL, type="session.start")
    assert metrics.counter_value(metrics.DAEMON_REQUEST_TOTAL, type="session.start") == 1


def test_a_refused_label_records_nothing_at_all() -> None:
    """The check runs before the write, so a rejected call cannot leave a partial
    series behind under a different key."""
    with pytest.raises(metrics.LabelNotAllowed):
        metrics.increment("x_total", type="ok", node_id="n-1")
    assert metrics.snapshot()["counters"] == {}


def test_every_label_used_in_the_app_is_on_the_allowlist() -> None:
    """Scans the source for keyword arguments passed to `increment`/`observe`.

    The runtime check already refuses an unknown key, but only if that line executes —
    a rarely-taken error path could ship a metric call that raises the first time it is
    reached. This finds it without needing to run it.
    """
    pattern = re.compile(r"metrics\.(?:increment|observe)\((.*?)\)", re.S)
    keywords = re.compile(r"(\w+)=")
    offenders: dict[str, set[str]] = {}
    for path in (ROOT / "backend/app").rglob("*.py"):
        if path.name == "metrics.py":
            continue
        for call in pattern.findall(path.read_text(encoding="utf-8")):
            for name in keywords.findall(call):
                # `amount` is the positional-or-keyword count on increment, not a label.
                if name in {"amount", "value"} or name in metrics.ALLOWED_LABELS:
                    continue
                offenders.setdefault(str(path.relative_to(ROOT)), set()).add(name)
    assert offenders == {}, f"metric labels outside the allowlist: {offenders}"


def test_the_daemon_shares_the_same_allowlist_intent() -> None:
    """Both registries publish to the same Prometheus. A key the daemon allows and the
    backend forbids would be a hole on one side of the same rule."""
    source = (ROOT / "daemon/internal/metrics/metrics.go").read_text(encoding="utf-8")
    block = re.search(r"var allowedLabels = map\[string\]bool\{(.*?)\n\}", source, re.S)
    assert block is not None, "the daemon's allowlist is missing"
    daemon_labels = set(re.findall(r'"(\w+)":', block.group(1)))
    assert daemon_labels & metrics.FORBIDDEN_LABELS == set(), (
        f"the daemon allows labels the backend forbids: "
        f"{sorted(daemon_labels & metrics.FORBIDDEN_LABELS)}"
    )


# --------------------------------------------------------------------------- #
# Exposition format
# --------------------------------------------------------------------------- #


def scrape_text() -> str:
    counters, histograms = metrics.export_series()
    return render(counters, histograms, [])


def test_a_counter_renders_with_its_type_and_prefix() -> None:
    metrics.increment(metrics.AUDIT_ERROR_TOTAL, action="user.login")
    text = scrape_text()
    assert f"# TYPE {PREFIX}audit_error_total counter" in text
    assert f'{PREFIX}audit_error_total{{action="user.login"}} 1' in text


def test_histogram_buckets_are_cumulative_in_the_exposition() -> None:
    """The registry stores one bucket per sample; the format requires "samples ≤ le".

    Without the conversion each bucket would report only the samples that landed exactly
    in it, and `histogram_quantile` over that is not merely imprecise — it is wrong, and
    wrong in a way that looks plausible.
    """
    for value in (0.01, 0.2, 0.2, 4.0, 30.0):
        metrics.observe(
            metrics.HTTP_REQUEST_DURATION, value, method="GET", route="/x", status_class="2xx"
        )
    text = scrape_text()

    buckets = [
        (float(bound), int(count))
        for bound, count in re.findall(
            rf'{PREFIX}http_request_duration_seconds_bucket\{{[^}}]*le="([0-9.]+)"\}} (\d+)', text
        )
    ]
    assert buckets, text
    counts = [count for _, count in buckets]
    assert counts == sorted(counts), f"buckets are not monotonic: {buckets}"

    inf = int(
        re.search(
            rf'{PREFIX}http_request_duration_seconds_bucket\{{[^}}]*le="\+Inf"\}} (\d+)', text
        ).group(1)
    )
    total = int(
        re.search(rf"{PREFIX}http_request_duration_seconds_count\{{[^}}]*\}} (\d+)", text).group(1)
    )
    # The defining property of the format: +Inf holds every sample.
    assert inf == total == 5


def test_a_sample_above_every_bound_lands_only_in_inf() -> None:
    metrics.observe(
        metrics.HTTP_REQUEST_DURATION, 99.0, method="GET", route="/x", status_class="2xx"
    )
    text = scrape_text()
    lowest = re.search(
        rf'{PREFIX}http_request_duration_seconds_bucket\{{[^}}]*le="0.05"\}} (\d+)', text
    )
    assert lowest is not None and lowest.group(1) == "0"
    inf = re.search(
        rf'{PREFIX}http_request_duration_seconds_bucket\{{[^}}]*le="\+Inf"\}} (\d+)', text
    )
    assert inf is not None and inf.group(1) == "1"


def test_a_size_histogram_uses_its_own_bounds() -> None:
    """Rendering queue bytes on the duration scale would put every sample in `+Inf` and
    make the series useless."""
    metrics.observe(metrics.TERMINAL_QUEUE_BYTES, 2048)
    text = scrape_text()
    assert 'le="4096"' in text
    assert 'le="1048576"' in text


def test_the_exposition_ends_with_a_newline() -> None:
    metrics.increment(metrics.AUDIT_ERROR_TOTAL, action="user.login")
    assert scrape_text().endswith("\n")


def test_an_empty_registry_renders_without_error() -> None:
    assert scrape_text() == "\n"


def test_a_label_value_cannot_forge_a_metric_line() -> None:
    """Every value here comes from a closed vocabulary, so this cannot happen today —
    but an unescaped newline would let one label inject additional series, and that is
    not a property to leave to convention."""
    assert _escape_label('a"b') == 'a\\"b'
    assert _escape_label("a\nb") == "a\\nb"
    assert _escape_label("a\\b") == "a\\\\b"


def test_gauge_lines_are_appended_verbatim() -> None:
    text = render([], [], [f"{PREFIX}online_nodes 3"])
    assert f"{PREFIX}online_nodes 3" in text


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_metrics_are_disabled_by_default() -> None:
    """An always-on metrics endpoint is a permanent read surface, and most deployments
    do not scrape at all."""
    assert Settings().metrics_enabled is False


def test_enabling_metrics_without_a_token_refuses_to_start() -> None:
    """Fail at startup rather than serve the whole series set unauthenticated."""
    with pytest.raises(ValueError, match="metrics_scrape_token"):
        Settings(metrics_enabled=True)


def test_a_short_scrape_token_is_refused() -> None:
    with pytest.raises(ValueError, match="16 characters"):
        Settings(metrics_enabled=True, metrics_scrape_token="short")


def test_metrics_enabled_with_a_real_token_is_accepted() -> None:
    settings = Settings(metrics_enabled=True, metrics_scrape_token="a" * 32)
    assert settings.metrics_enabled


def test_the_pool_bounds_are_explicit() -> None:
    """`database_pool_usage` and the exhaustion alert need a denominator that is written
    down, and `pool_timeout` is what turns saturation into a visible 503 rather than a
    request that hangs."""
    settings = Settings()
    assert settings.db_pool_size > 0
    assert settings.db_max_overflow >= 0
    assert settings.db_pool_timeout_seconds > 0
    assert settings.db_pool_recycle_seconds > 0
