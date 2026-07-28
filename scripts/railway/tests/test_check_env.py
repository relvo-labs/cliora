"""Tests for the pre-deploy variable check (RW-06).

Each test is one deployment mistake. The positive case is one test; the rest are the
misconfigurations that would otherwise be diagnosed from a symptom pointing elsewhere.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "check_env.py"
_spec = importlib.util.spec_from_file_location("check_env", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
check_env = importlib.util.module_from_spec(_spec)
sys.modules["check_env"] = check_env
_spec.loader.exec_module(check_env)

SECRET = "S" * 48
DB_PASSWORD = "pw-with-@-and-:-chars"


def central(**overrides: str) -> dict[str, str]:
    base = {
        "CLIORA_ENVIRONMENT": "production",
        "CLIORA_DATABASE_URL": (
            "postgresql+asyncpg://cliora:pw--with--%40--and--%3A--chars"
            "@postgres.railway.internal:5432/railway"
        ),
        "CLIORA_JWT_SECRET": SECRET,
        "CLIORA_TOKEN_PEPPER": SECRET[::-1],
        "CLIORA_PUBLIC_BASE_URL": "https://cliora.example.com",
        "CLIORA_SHUTDOWN_DRAIN_SECONDS": "15",
        "PORT": "8080",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v != "__unset__"}


def console(**overrides: str) -> dict[str, str]:
    base = {
        "PORT": "8080",
        "CLIORA_BACKEND_HOST": "central.railway.internal",
        "CLIORA_BACKEND_PORT": "8080",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v != "__unset__"}


def failures(*args: object, **kwargs: object) -> list[str]:
    return check_env.check(*args, **kwargs).failures  # type: ignore[arg-type]


def test_a_correct_environment_passes() -> None:
    assert failures(central(), console(), domain="cliora.example.com", draining_seconds=25) == []


def test_no_secret_value_appears_in_the_output() -> None:
    """This runs in CI and CI logs outlive the deploy."""
    canary = "Zq7-leak-canary"
    report = check_env.check(
        central(CLIORA_JWT_SECRET=canary), console(), draining_seconds=25
    )
    joined = "\n".join(report.notes)
    assert canary not in joined
    assert SECRET[::-1] not in joined
    # The finding still has to be actionable, which means naming the variable.
    assert "CLIORA_JWT_SECRET" in joined


def test_a_synchronous_driver_url_is_rejected() -> None:
    """Railway's own DATABASE_URL is postgresql://, and the resulting startup error names a
    driver, not the variable that is wrong."""
    problems = failures(
        central(CLIORA_DATABASE_URL="postgresql://u:p@postgres.railway.internal:5432/railway"),
        console(),
    )
    assert any("asyncpg" in problem for problem in problems)


def test_a_public_database_host_is_rejected() -> None:
    problems = failures(
        central(
            CLIORA_DATABASE_URL=(
                "postgresql+asyncpg://u:p@roundhouse.proxy.rlwy.net:41234/railway"
            )
        ),
        console(),
    )
    assert any("private network" in problem for problem in problems)


def test_an_unencoded_password_is_caught_by_the_host_check() -> None:
    """A reference variable does not percent-encode. A password containing `@` splits the
    userinfo, and the URL then parses cleanly while pointing at the wrong host."""
    problems = failures(
        central(
            CLIORA_DATABASE_URL=(
                f"postgresql+asyncpg://cliora:{DB_PASSWORD}@postgres.railway.internal:5432/railway"
            )
        ),
        console(),
    )
    assert problems, "an unencoded @ in the password must not pass"


def test_a_password_mismatch_against_the_postgres_service_is_reported() -> None:
    problems = failures(
        central(), console(), postgres={"POSTGRES_PASSWORD": "something-else"}
    )
    assert any("does not match the Postgres service password" in problem for problem in problems)


def test_the_matching_password_is_accepted_after_percent_decoding() -> None:
    assert (
        failures(
            central(), console(), postgres={"POSTGRES_PASSWORD": "pw--with--@--and--:--chars"}
        )
        == []
    )


def test_dev_secrets_are_rejected() -> None:
    problems = failures(central(CLIORA_TOKEN_PEPPER="dev-only-change-me"), console())
    assert any("development default" in problem for problem in problems)


def test_a_platform_generated_public_domain_is_rejected() -> None:
    """It ends up in every node's config file, so it is only cheap to fix before the first
    node enrolls."""
    problems = failures(
        central(CLIORA_PUBLIC_BASE_URL="https://cliora-production.up.railway.app"), console()
    )
    assert any("re-registering every node" in problem for problem in problems)


def test_a_plaintext_public_base_url_is_rejected() -> None:
    problems = failures(central(CLIORA_PUBLIC_BASE_URL="http://cliora.example.com"), console())
    assert any("https" in problem for problem in problems)


def test_a_public_base_url_that_is_not_the_console_domain_is_rejected() -> None:
    problems = failures(
        central(CLIORA_PUBLIC_BASE_URL="https://other.example.com"),
        console(),
        domain="cliora.example.com",
    )
    assert any("custom domain" in problem for problem in problems)


def test_a_non_empty_vite_api_base_url_is_rejected() -> None:
    """The one that half-works: API calls go to the other origin, the terminal socket stays
    on this one, and only terminals break."""
    problems = failures(central(), console(VITE_API_BASE_URL="https://api.example.com"))
    assert any("VITE_API_BASE_URL" in problem for problem in problems)


def test_mismatched_ports_are_rejected() -> None:
    problems = failures(central(PORT="8000"), console(CLIORA_BACKEND_PORT="8080"))
    assert any("502" in problem for problem in problems)


def test_a_public_backend_host_is_rejected() -> None:
    problems = failures(central(), console(CLIORA_BACKEND_HOST="cliora.example.com"))
    assert any("private network" in problem for problem in problems)


def test_metrics_without_a_long_enough_token_are_rejected() -> None:
    problems = failures(
        central(CLIORA_METRICS_ENABLED="true", CLIORA_METRICS_SCRAPE_TOKEN="short"), console()
    )
    assert any("refuses to start" in problem for problem in problems)


def test_a_draining_window_that_does_not_cover_the_drain_is_rejected() -> None:
    """The platform default is 0, which is precisely the case this must catch."""
    problems = failures(central(), console(), draining_seconds=0)
    assert any("mid-drain" in problem for problem in problems)


def test_a_draining_window_equal_to_the_drain_is_rejected() -> None:
    problems = failures(
        central(CLIORA_SHUTDOWN_DRAIN_SECONDS="25"), console(), draining_seconds=25
    )
    assert any("mid-drain" in problem for problem in problems)


def test_missing_required_variables_are_named() -> None:
    problems = failures(central(CLIORA_JWT_SECRET="__unset__"), console(PORT="__unset__"))
    assert any("central is missing CLIORA_JWT_SECRET" in problem for problem in problems)
    assert any("console is missing PORT" in problem for problem in problems)


@pytest.mark.parametrize(
    "payload",
    [
        {"A": "1", "B": None},
        [{"name": "A", "value": "1"}, {"name": "B", "value": None}],
    ],
)
def test_both_cli_output_shapes_are_accepted(payload: object) -> None:
    assert check_env.normalise(payload) == {"A": "1", "B": ""}


def test_an_unsupported_payload_is_an_error_not_an_empty_pass() -> None:
    with pytest.raises(ValueError):
        check_env.normalise("PORT=8080")


def test_the_draining_window_is_read_from_the_shipped_config() -> None:
    """Ties the check to the file that is actually deployed, so a hand-edited
    drainingSeconds cannot pass by being absent from the check."""
    config = Path(__file__).resolve().parents[3] / "deploy" / "railway" / "central.railway.json"
    assert check_env.draining_seconds_from_config(config) == 25


def test_the_shipped_config_covers_the_default_drain() -> None:
    config = Path(__file__).resolve().parents[3] / "deploy" / "railway" / "central.railway.json"
    draining = check_env.draining_seconds_from_config(config)
    assert draining is not None and draining > check_env.DEFAULT_DRAIN_SECONDS


def test_main_reports_and_exits_non_zero_on_a_problem(tmp_path: Path) -> None:
    central_file = tmp_path / "central.json"
    console_file = tmp_path / "console.json"
    central_file.write_text(json.dumps(central(CLIORA_ENVIRONMENT="development")))
    console_file.write_text(json.dumps(console()))
    assert (
        check_env.main(
            ["--central-vars", str(central_file), "--console-vars", str(console_file)]
        )
        == 1
    )
