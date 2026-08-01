"""The three-layer port-forwarding policy and derived tunnel state (PG-07, ADR 0022 D17).

`effective_policy` has four inputs and three outputs and no database, so it gets its coverage
here rather than through the API: a mistake in it does not show up as a wrong screen, it shows
up as a port being forwarded that a node's owner refused.

The cases that matter most are the two the plan names explicitly — a platform that tries to
widen cannot defeat the node's veto, and three port lists intersect rather than override — and
they are the first two tests below.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.clock import now_utc
from app.db.models import NodeTunnel
from app.services.tunnels import (
    LAYER_INTEGRATION,
    LAYER_NODE_LOCAL,
    LAYER_NODE_SETTINGS,
    PORT_CEILING,
    PORT_FLOOR,
    STATE_CLOSED,
    STATE_EXPIRED,
    STATE_FAILED,
    STATE_OPENING,
    STATE_RUNNING,
    STATE_UNAVAILABLE,
    IntegrationLayer,
    NodeReportLayer,
    NodeSettingsLayer,
    derive_state,
    effective_policy,
    generate_basic_password,
    parse_port_specs,
)
from app.settings import Settings


def _settings(**kwargs: object) -> Settings:
    return Settings(jwt_secret="a-real-secret", token_pepper="a-real-pepper", **kwargs)  # type: ignore[arg-type]


def _integration(*, enabled: bool = True, ports: list[str] | None = None) -> IntegrationLayer:
    return IntegrationLayer(enabled=enabled, allowed_ports=ports)


def _node_settings(
    *, enabled: bool = True, ports: list[str] | None = None, max_tunnels: int | None = None
) -> NodeSettingsLayer:
    return NodeSettingsLayer(enabled=enabled, allowed_ports=ports, max_tunnels=max_tunnels)


def _report(
    *,
    veto: bool = False,
    ports: list[str] | None = None,
    max_tunnels: int | None = None,
    supports: bool = True,
) -> NodeReportLayer:
    return NodeReportLayer(
        veto=veto,
        prereq_ok=True,
        allowed_ports=ports,
        max_tunnels=max_tunnels,
        reported_at=now_utc(),
        daemon_supports=supports,
    )


# --- The two cases the plan requires ------------------------------------------------ #


def test_the_nodes_veto_survives_everything_the_platform_says() -> None:
    """D17: the local veto is absolute and the platform has no path that overrides it.

    This is the test that would fail if someone made the platform layers authoritative
    "because the admin should be able to force it" — which is exactly the change that would
    make a node's owner's `tunnel.enabled: false` a suggestion.
    """
    policy = effective_policy(
        _integration(enabled=True, ports=None),
        _node_settings(enabled=True, ports=None, max_tunnels=100),
        _report(veto=True),
        _settings(),
    )
    assert policy.enabled is False
    assert policy.blocked_by == LAYER_NODE_LOCAL


def test_three_port_lists_intersect_instead_of_the_last_one_winning() -> None:
    policy = effective_policy(
        _integration(ports=["3000-3999", "5173"]),
        _node_settings(ports=["3500-8000"]),
        _report(ports=["3600-3700", "5173"]),
        _settings(),
    )
    # What survives is the overlap of all three, not the last layer's list: 3000-3999 meets
    # 3500-8000 at 3500-3999, which the node's own 3600-3700 narrows again; 5173 is the only
    # single port present in all three.
    assert policy.allowed_ports == ((3600, 3700), (5173, 5173))
    assert policy.permits(3650)
    assert policy.permits(5173)
    assert not policy.permits(3400)
    assert not policy.permits(8000)


# --- Enablement, layer by layer ----------------------------------------------------- #


@pytest.mark.parametrize(
    ("integration", "node_settings", "report", "expected"),
    [
        (_integration(enabled=False), _node_settings(), _report(), LAYER_INTEGRATION),
        (_integration(), _node_settings(enabled=False), _report(), LAYER_NODE_SETTINGS),
        (_integration(), _node_settings(), _report(veto=True), LAYER_NODE_LOCAL),
        (_integration(), _node_settings(), _report(supports=False), LAYER_NODE_LOCAL),
    ],
)
def test_a_refusal_names_the_layer_that_refused(
    integration: IntegrationLayer,
    node_settings: NodeSettingsLayer,
    report: NodeReportLayer,
    expected: str,
) -> None:
    """Three layers means "not allowed" has three remedies. A refusal that does not say
    which layer refused leaves the user changing settings at random."""
    policy = effective_policy(integration, node_settings, report, _settings())
    assert policy.enabled is False
    assert policy.blocked_by == expected


def test_the_integration_layer_is_reported_before_the_others() -> None:
    """With everything off, the platform-level switch is the one named: it is the layer a
    platform user can actually act on, and it explains the other two."""
    policy = effective_policy(
        _integration(enabled=False),
        _node_settings(enabled=False),
        _report(veto=True),
        _settings(),
    )
    assert policy.blocked_by == LAYER_INTEGRATION


def test_all_three_layers_enabled_permits() -> None:
    policy = effective_policy(_integration(), _node_settings(), _report(), _settings())
    assert policy.enabled is True
    assert policy.blocked_by is None


# --- Ports -------------------------------------------------------------------------- #


def test_no_configured_ports_means_the_whole_unprivileged_range() -> None:
    policy = effective_policy(_integration(), _node_settings(), _report(), _settings())
    assert policy.allowed_ports == ((PORT_FLOOR, PORT_CEILING),)
    assert policy.permits(PORT_FLOOR)
    assert policy.permits(PORT_CEILING)
    assert not policy.permits(PORT_FLOOR - 1)


def test_an_empty_list_forbids_everything_and_is_not_the_same_as_unset() -> None:
    """Both settings are legitimate and they are opposites: "" narrows to nothing, NULL does
    not narrow at all. Collapsing them would silently widen one of them."""
    forbidden = effective_policy(_integration(ports=[]), _node_settings(), _report(), _settings())
    assert forbidden.allowed_ports == ()
    assert not forbidden.permits(5173)
    unset = effective_policy(_integration(ports=None), _node_settings(), _report(), _settings())
    assert unset.allowed_ports == ((PORT_FLOOR, PORT_CEILING),)


def test_a_stored_range_below_the_floor_narrows_to_nothing_rather_than_permitting_it() -> None:
    """The floor is not negotiable at any layer. A spec of `80-90` is not an error to raise
    at read time, but it must not become permission to forward port 80."""
    assert parse_port_specs(["80-90"]) == ()
    assert parse_port_specs(["900-2000"]) == ((PORT_FLOOR, 2000),)


def test_unparseable_specs_are_ignored_not_treated_as_permission() -> None:
    assert parse_port_specs(["nonsense", "5173"]) == ((5173, 5173),)
    assert parse_port_specs(None) is None


# --- Caps --------------------------------------------------------------------------- #


def test_the_per_node_cap_is_the_narrowest_of_the_three_that_apply() -> None:
    policy = effective_policy(
        _integration(),
        _node_settings(max_tunnels=2),
        _report(max_tunnels=1),
        _settings(tunnels_per_node_max=3),
    )
    assert policy.max_tunnels == 1


def test_the_fleet_budget_is_not_folded_into_the_per_node_cap() -> None:
    """ADR 0022 D17b. The budget is a provider-plan fact checked as a global count; folding
    it into this minimum is what made a budget of 8 unreachable while every node allowed 3 —
    the fleet could hold 3xN tunnels against a plan permitting 8."""
    policy = effective_policy(
        _integration(), _node_settings(), _report(), _settings(tunnels_per_node_max=3)
    )
    assert policy.max_tunnels == 3


# --- Derived state ------------------------------------------------------------------ #


def _tunnel(**kwargs: object) -> NodeTunnel:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "node_id": uuid.uuid4(),
        "port": 5173,
        "protection": "basic",
        "created_by": uuid.uuid4(),
        "expires_at": now_utc() + timedelta(hours=1),
        "url": "https://example.pinggy.link",
        "url_change_count": 0,
    }
    return NodeTunnel(**{**defaults, **kwargs})


def test_state_is_derived_in_precedence_order() -> None:
    now = now_utc()
    assert derive_state(_tunnel(closed_at=now), connected=True, now=now) == STATE_CLOSED
    assert (
        derive_state(_tunnel(expires_at=now - timedelta(seconds=1)), connected=True, now=now)
        == STATE_EXPIRED
    )
    assert (
        derive_state(
            _tunnel(state_error_code="TUNNEL_PROVIDER_UNAVAILABLE"), connected=True, now=now
        )
        == STATE_FAILED
    )
    assert derive_state(_tunnel(), connected=False, now=now) == STATE_UNAVAILABLE
    assert derive_state(_tunnel(url=None), connected=True, now=now) == STATE_OPENING
    assert derive_state(_tunnel(), connected=True, now=now) == STATE_RUNNING


def test_a_recorded_failure_outranks_the_node_being_offline() -> None:
    """`failed` carries a code and a remedy; `unavailable` is an observation that changes on
    its own. Showing the weaker one would hide the only actionable half."""
    now = now_utc()
    tunnel = _tunnel(state_error_code="TUNNEL_PROVIDER_UNTRUSTED")
    assert derive_state(tunnel, connected=False, now=now) == STATE_FAILED


# --- The one-time password ---------------------------------------------------------- #


def test_the_generated_password_never_contains_the_providers_separator() -> None:
    """`b:user:pass` is colon-separated, and the provider's documentation says the pair may
    not contain one. A colon here would not be a formatting problem: it would create a second
    credential pair or an unintended remote option."""
    for _ in range(50):
        password = generate_basic_password(24)
        assert ":" not in password
        assert len(password) == 24
        assert password.isascii() and all(0x21 <= ord(c) <= 0x7E for c in password)


def test_the_password_length_is_bounded_to_what_the_wire_accepts() -> None:
    assert len(generate_basic_password(2)) == 8
    assert len(generate_basic_password(400)) == 64
