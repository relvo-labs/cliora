"""Settings that must fail closed in production.

`test_p0_fails_closed_in_production` used to live here, guarding the P0 development
relay against being enabled in production. P4-07 deleted the relay itself, so there
is nothing left to guard — the test is replaced by
`test_no_p0_relay_surface_remains` in `test_api_foundation.py`, which asserts the
endpoints and settings are gone rather than merely refused.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret": "dev-only-change-me"},
        {"token_pepper": "dev-only-change-me"},
        {"jwt_secret": "dev-only-change-me", "token_pepper": "dev-only-change-me"},
    ],
)
def test_development_secrets_fail_closed_in_production(overrides: dict[str, str]) -> None:
    """A deployment that forgot to set a secret must not start with the shipped
    placeholder: every token it then issues would be forgeable by anyone who has read
    the repository."""
    with pytest.raises(ValidationError):
        Settings(environment="production", **{**_production_secrets(), **overrides})


def test_production_starts_with_real_secrets() -> None:
    settings = Settings(environment="production", **_production_secrets())
    assert settings.environment == "production"


def test_the_retired_p0_settings_are_gone() -> None:
    """Their absence is the point: while `p0_enabled` existed, the relay it gated was
    one environment variable away from being reachable in production."""
    fields = set(Settings.model_fields)
    assert {"p0_enabled", "p0_token", "node_id"} & fields == set()


def _production_secrets() -> dict[str, str]:
    return {"jwt_secret": "a-real-secret", "token_pepper": "a-real-pepper"}
