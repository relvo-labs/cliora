"""Refuse to deploy on a variable set that will fail, or worse, half-work (RW-06).

Every rule here corresponds to a failure someone would otherwise diagnose from a symptom
that points somewhere else:

  * a `postgresql://` URL fails at startup with a driver error that says nothing about the
    variable being wrong;
  * a password containing `@` produces a URL that parses, resolves to the wrong host, and
    reports "connection refused";
  * `VITE_API_BASE_URL` set to the API's own domain leaves login, node list and file tree
    working and breaks only terminals, because the terminal socket is built from
    `location.host` and ignores that variable;
  * `drainingSeconds` below `CLIORA_SHUTDOWN_DRAIN_SECONDS` means SIGKILL lands mid-drain
    and every deploy disconnects browsers without explanation;
  * `*.up.railway.app` in `CLIORA_PUBLIC_BASE_URL` is written into every node's config file,
    so it is only cheap to fix before the first node enrolls.

**No secret value is ever printed.** Findings name the variable and the property that
failed. This runs in CI, and CI logs outlive the deploy.

Values arrive as JSON so the check is independent of how they were obtained — see
`check-env.sh` for the `railway variables --json` path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

DEV_SECRET = "dev-only-change-me"
MIN_SECRET_LENGTH = 32
MIN_SCRAPE_TOKEN_LENGTH = 16
PRIVATE_SUFFIX = ".railway.internal"
DEFAULT_DRAIN_SECONDS = 15.0

CENTRAL_REQUIRED = (
    "CLIORA_ENVIRONMENT",
    "CLIORA_DATABASE_URL",
    "CLIORA_JWT_SECRET",
    "CLIORA_TOKEN_PEPPER",
    "CLIORA_PUBLIC_BASE_URL",
    "PORT",
)
CONSOLE_REQUIRED = ("PORT", "CLIORA_BACKEND_HOST", "CLIORA_BACKEND_PORT")


def normalise(raw: Any) -> dict[str, str]:
    """Accept either a flat mapping or a list of {name, value} records.

    Railway's CLI output shape is not something to bet a pre-deploy gate on; both shapes
    are handled so an upgrade cannot turn this check into a false pass.
    """
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("variable list entries must be objects")
            name = item.get("name") or item.get("key")
            if name is None:
                raise ValueError("variable list entry has no name")
            value = item.get("value")
            out[str(name)] = "" if value is None else str(value)
        return out
    raise ValueError(f"unsupported variables payload: {type(raw).__name__}")


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.notes: list[str] = []

    def ok(self, message: str) -> None:
        self.notes.append(f"ok: {message}")

    def fail(self, message: str) -> None:
        self.failures.append(message)
        self.notes.append(f"FAIL: {message}")


def _check_secret(report: Report, name: str, value: str, *, one_way: bool) -> None:
    if value == DEV_SECRET:
        report.fail(f"{name} is still the development default; Central refuses to start on it")
        return
    if len(value) < MIN_SECRET_LENGTH:
        report.fail(f"{name} is shorter than {MIN_SECRET_LENGTH} characters")
        return
    suffix = " (rotating it forces every node to re-enroll)" if one_way else ""
    report.ok(f"{name} is set and long enough{suffix}")


def _check_userinfo_encoding(report: Report, url: str) -> bool:
    """Reject a userinfo section that two parsers would read differently.

    This cannot be left to `urlsplit`. Python splits the userinfo at the **last** `@`, so
    `user:pw-with-@-inside@host` yields the right hostname and a plausible password and looks
    entirely healthy. SQLAlchemy's own URL regex takes the password as `[^@]*` — it stops at
    the **first** `@` — and therefore reads the rest of the password as part of the host. The
    two disagree, the check that used only `urlsplit` passed, and the deploy failed with
    "connection refused" naming a host nobody configured.

    Railway's reference variables do not percent-encode, so a generated password containing
    `@` or `:` produces exactly this. Returns False when the URL must not be used.
    """
    _, _, after_scheme = url.partition("://")
    authority = after_scheme.split("/", 1)[0]
    if "@" not in authority:
        return True
    userinfo, _, _hostport = authority.rpartition("@")
    if "@" in userinfo:
        report.fail(
            "CLIORA_DATABASE_URL userinfo contains an unencoded '@'; percent-encode it as "
            "%40 (SQLAlchemy stops the password at the first '@' and reads the remainder as "
            "the host, while urllib splits at the last one)"
        )
        return False
    if userinfo.count(":") > 1:
        report.fail(
            "CLIORA_DATABASE_URL userinfo contains an unencoded ':'; percent-encode it as %3A"
        )
        return False
    return True


def check_database_url(report: Report, url: str, postgres_password: str | None) -> None:
    if not _check_userinfo_encoding(report, url):
        return
    if not url.startswith("postgresql+asyncpg://"):
        report.fail(
            "CLIORA_DATABASE_URL does not use the postgresql+asyncpg driver "
            "(Railway's own DATABASE_URL is postgresql:// and must be rewritten)"
        )
        return
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not host.endswith(PRIVATE_SUFFIX):
        report.fail(
            f"CLIORA_DATABASE_URL host does not end in {PRIVATE_SUFFIX}; "
            "the database would be reached over the public proxy instead of the private network"
        )
    if not parts.port:
        report.fail("CLIORA_DATABASE_URL names no port")
    if not (parts.path or "").strip("/"):
        report.fail("CLIORA_DATABASE_URL names no database")
    if not parts.username:
        report.fail("CLIORA_DATABASE_URL names no user")
    if not parts.password:
        # Either genuinely absent, or an unencoded reserved character split the userinfo —
        # which is also why the host check above matters.
        report.fail(
            "CLIORA_DATABASE_URL has no parseable password; if it contains @ : / or ? "
            "it must be percent-encoded (reference variables do not encode)"
        )
        return
    if postgres_password is not None:
        if unquote(parts.password) != postgres_password:
            report.fail(
                "CLIORA_DATABASE_URL password does not match the Postgres service password "
                "after percent-decoding"
            )
        else:
            report.ok("CLIORA_DATABASE_URL password matches the Postgres service")
    if not report.failures:
        report.ok("CLIORA_DATABASE_URL uses asyncpg over the private network")


def check_public_base_url(report: Report, value: str, expected_domain: str | None) -> None:
    if not value.startswith("https://"):
        report.fail("CLIORA_PUBLIC_BASE_URL is not https:// (FR-CONN-002, SEC-005)")
        return
    host = urlsplit(value).hostname or ""
    if host.endswith(".up.railway.app"):
        report.fail(
            "CLIORA_PUBLIC_BASE_URL is a platform-generated domain. It is written into every "
            "node's config, so changing it later means re-registering every node — use the "
            "custom domain from the start"
        )
        return
    if expected_domain and host != expected_domain:
        report.fail(
            f"CLIORA_PUBLIC_BASE_URL host is {host}, not the console's custom domain "
            f"{expected_domain}"
        )
        return
    report.ok("CLIORA_PUBLIC_BASE_URL is an https custom domain")


def check(
    central: dict[str, str],
    console: dict[str, str],
    *,
    postgres: dict[str, str] | None = None,
    domain: str | None = None,
    draining_seconds: float | None = None,
) -> Report:
    report = Report()

    for name in CENTRAL_REQUIRED:
        if not central.get(name, "").strip():
            report.fail(f"central is missing {name}")
    for name in CONSOLE_REQUIRED:
        if not console.get(name, "").strip():
            report.fail(f"console is missing {name}")

    environment = central.get("CLIORA_ENVIRONMENT", "")
    if environment != "production":
        report.fail(
            f"CLIORA_ENVIRONMENT is {environment!r}, not 'production'; the dev-secret check "
            "that turns a forgotten value into a failed start is only active in production"
        )
    else:
        report.ok("CLIORA_ENVIRONMENT is production")

    _check_secret(report, "CLIORA_JWT_SECRET", central.get("CLIORA_JWT_SECRET", ""), one_way=False)
    _check_secret(report, "CLIORA_TOKEN_PEPPER", central.get("CLIORA_TOKEN_PEPPER", ""), one_way=True)

    if central.get("CLIORA_DATABASE_URL"):
        password = None
        if postgres is not None:
            password = (
                postgres.get("POSTGRES_PASSWORD")
                or postgres.get("PGPASSWORD")
                or postgres.get("PASSWORD")
            )
        check_database_url(report, central["CLIORA_DATABASE_URL"], password)

    if central.get("CLIORA_PUBLIC_BASE_URL"):
        check_public_base_url(report, central["CLIORA_PUBLIC_BASE_URL"], domain)

    # The console must serve the API from its own origin. A non-empty base URL sends API
    # calls elsewhere while the terminal socket stays here.
    if console.get("VITE_API_BASE_URL", "").strip():
        report.fail(
            "console sets VITE_API_BASE_URL; it must be empty so the console, /api and /ws "
            "share one origin (the terminal socket is built from location.host and ignores it)"
        )
    else:
        report.ok("VITE_API_BASE_URL is unset, so the console and the API share one origin")

    central_port = central.get("PORT", "")
    backend_port = console.get("CLIORA_BACKEND_PORT", "")
    if central_port and backend_port and central_port != backend_port:
        report.fail(
            f"console proxies to port {backend_port} but central listens on {central_port}; "
            "every /api and /ws request would answer 502"
        )
    elif central_port:
        report.ok(f"console proxies to the port central listens on ({central_port})")

    backend_host = console.get("CLIORA_BACKEND_HOST", "")
    if backend_host and not backend_host.endswith(PRIVATE_SUFFIX):
        report.fail(
            f"CLIORA_BACKEND_HOST is {backend_host}, which is not a {PRIVATE_SUFFIX} name; "
            "Central should be reachable only over the private network"
        )
    elif backend_host:
        report.ok("console reaches Central over the private network")

    metrics = central.get("CLIORA_METRICS_ENABLED", "false").strip().lower()
    if metrics in {"1", "true", "yes"}:
        token = central.get("CLIORA_METRICS_SCRAPE_TOKEN", "")
        if len(token) < MIN_SCRAPE_TOKEN_LENGTH:
            report.fail(
                "CLIORA_METRICS_ENABLED is true but CLIORA_METRICS_SCRAPE_TOKEN is shorter "
                f"than {MIN_SCRAPE_TOKEN_LENGTH} characters; Central refuses to start"
            )
        else:
            report.ok("metrics are enabled with a scrape token of sufficient length")
    else:
        report.ok("metrics are disabled (no permanent read surface on the control plane)")

    if draining_seconds is not None:
        drain = float(central.get("CLIORA_SHUTDOWN_DRAIN_SECONDS") or DEFAULT_DRAIN_SECONDS)
        if draining_seconds <= drain:
            report.fail(
                f"drainingSeconds ({draining_seconds:g}) is not above "
                f"CLIORA_SHUTDOWN_DRAIN_SECONDS ({drain:g}); SIGKILL would land mid-drain and "
                "every deploy would disconnect browsers without explanation"
            )
        else:
            report.ok(
                f"drainingSeconds ({draining_seconds:g}) leaves room for the "
                f"{drain:g}s drain"
            )

    return report


def draining_seconds_from_config(path: Path) -> float | None:
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    value = config.get("deploy", {}).get("drainingSeconds")
    return float(value) if isinstance(value, (int, float)) else None


def _load(path: Path) -> dict[str, str]:
    return normalise(json.loads(path.read_text()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_env")
    parser.add_argument("--central-vars", required=True, type=Path)
    parser.add_argument("--console-vars", required=True, type=Path)
    parser.add_argument("--postgres-vars", default=None, type=Path)
    parser.add_argument("--domain", default=None, help="console custom domain, host only")
    parser.add_argument("--central-config", default=None, type=Path)
    args = parser.parse_args(argv)

    draining = (
        draining_seconds_from_config(args.central_config) if args.central_config else None
    )
    report = check(
        _load(args.central_vars),
        _load(args.console_vars),
        postgres=_load(args.postgres_vars) if args.postgres_vars else None,
        domain=args.domain,
        draining_seconds=draining,
    )
    for line in report.notes:
        print(line)
    print(f"\nproblems: {len(report.failures)}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
