"""Refuse the Railway client-IP trust keywords unless the topology they rely on holds (#184).

`CLIORA_TRUSTED_PROXY_CIDRS=railway-edge` makes the console trust `X-Real-IP` from any socket
peer, and `FORWARDED_ALLOW_IPS=railway-private-environment` makes Central trust forwarded
headers from any peer. Both are sound only while:

  * the environment contains exactly the expected services (Postgres, Central, console):
    any other service shares the private network and could forge headers to either hop;
  * neither console nor Central has a TCP proxy: TCP proxies bypass Railway's HTTP edge,
    so `X-Real-IP` would arrive unsanitized;
  * Central has no public domain (service or custom): only the console may reach it;
  * the keyword values are what is set (or staged) on both services.

This reads the live project through Railway's public GraphQL API with the operator's own
account token (the CLI login or `RAILWAY_API_TOKEN`), and **fails closed**: missing
credentials, an API error, or a response shape it does not recognise is exit 2, never a
pass. Topology or variable problems are exit 1. Variable values are never printed.

`check-trust-topology.sh` is the operator entry point. Tests replay recorded responses
(`--replay`); nothing here is called against the live API by the test suite.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

API_URL = "https://backboard.railway.com/graphql/v2"
REPLAY_FORMAT = "cliora-railway-topology-replay/1"

_spec = importlib.util.spec_from_file_location(
    "check_env", Path(__file__).with_name("check_env.py")
)
assert _spec is not None and _spec.loader is not None
check_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_env)

CONSOLE_TRUST_KEYWORD: str = check_env.CONSOLE_TRUST_KEYWORD
CENTRAL_TRUST_KEYWORD: str = check_env.CENTRAL_TRUST_KEYWORD
Report = check_env.Report

PROJECT_QUERY = """
query ClioraTrustProject($projectId: String!) {
  project(id: $projectId) {
    id
    name
    environments { pageInfo { hasNextPage } edges { node { id name } } }
    services {
      pageInfo { hasNextPage }
      edges {
        node {
          id
          name
          serviceInstances { pageInfo { hasNextPage } edges { node { environmentId } } }
        }
      }
    }
  }
}
"""

EXPOSURE_QUERY = """
query ClioraTrustExposure($projectId: String!, $environmentId: String!, $serviceId: String!) {
  domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
    serviceDomains { domain }
    customDomains { domain }
  }
  tcpProxies(environmentId: $environmentId, serviceId: $serviceId) { domain proxyPort }
}
"""

VARIABLES_QUERY = """
query ClioraTrustVariables($projectId: String!, $environmentId: String!, $serviceId: String!) {
  variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
}
"""

# (operation name, query, variables) -> decoded JSON response body
Transport = Callable[[str, str, dict[str, str]], Any]


class TopologyError(Exception):
    """The topology could not be established; the check fails closed."""


@dataclass(frozen=True)
class Names:
    central: str = "central"
    console: str = "console"
    postgres: str = "Postgres"


def _need(value: Any, kind: type, where: str) -> Any:
    if not isinstance(value, kind):
        raise TopologyError(f"unrecognised Railway API response: {where} is not {kind.__name__}")
    return value


def _nodes(container: Any, key: str, where: str) -> list[dict[str, Any]]:
    """Strictly unwrap a complete GraphQL connection `{key: {edges: [{node: {...}}]}}`.

    A truncated page could hide a service, so a missing or true `hasNextPage` fails closed.
    """
    connection = _need(_need(container, dict, where).get(key), dict, f"{where}.{key}")
    page = _need(connection.get("pageInfo"), dict, f"{where}.{key}.pageInfo")
    if page.get("hasNextPage") is not False:
        raise TopologyError(f"{where}.{key} is incomplete (paginated or no pageInfo)")
    edges = _need(connection.get("edges"), list, f"{where}.{key}.edges")
    return [
        _need(_need(edge, dict, f"{where}.{key}.edges[]").get("node"), dict, f"{where}.{key}.node")
        for edge in edges
    ]


def _str(container: dict[str, Any], key: str, where: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise TopologyError(f"unrecognised Railway API response: {where}.{key} is missing")
    return value


def query(transport: Transport, operation: str, text: str, variables: dict[str, str]) -> dict:
    body = transport(operation, text, variables)
    if not isinstance(body, dict):
        raise TopologyError(f"unrecognised Railway API response to {operation}")
    errors = body.get("errors")
    if errors:
        messages = sorted(
            {str(e.get("message", "?")) if isinstance(e, dict) else "?" for e in errors}
            if isinstance(errors, list)
            else {"?"}
        )
        raise TopologyError(
            f"Railway API refused {operation} ({'; '.join(messages)}); "
            "is the CLI logged in with access to this project?"
        )
    return _need(body.get("data"), dict, f"{operation}.data")


def _variables_of(
    transport: Transport, project_id: str, environment_id: str, service_id: str
) -> dict[str, str]:
    data = query(
        transport,
        "ClioraTrustVariables",
        VARIABLES_QUERY,
        {"projectId": project_id, "environmentId": environment_id, "serviceId": service_id},
    )
    raw = _need(data.get("variables"), dict, "variables")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise TopologyError("unrecognised Railway API response: variables are not strings")
    return dict(raw)


def check_keywords(report: Report, central: dict[str, str], console: dict[str, str]) -> None:
    """Exact keyword values; anything else, including a numeric list, fails this check."""
    if central.get("FORWARDED_ALLOW_IPS") == CENTRAL_TRUST_KEYWORD:
        report.ok(f"central FORWARDED_ALLOW_IPS is {CENTRAL_TRUST_KEYWORD}")
    else:
        report.fail(f"central FORWARDED_ALLOW_IPS is not exactly {CENTRAL_TRUST_KEYWORD}")
    entries = [e for e in re.split(r"[,\s]+", console.get("CLIORA_TRUSTED_PROXY_CIDRS", "")) if e]
    if entries == [CONSOLE_TRUST_KEYWORD]:
        report.ok(f"console CLIORA_TRUSTED_PROXY_CIDRS is {CONSOLE_TRUST_KEYWORD}")
    else:
        report.fail(f"console CLIORA_TRUSTED_PROXY_CIDRS is not exactly {CONSOLE_TRUST_KEYWORD}")


def evaluate(
    transport: Transport,
    *,
    project_id: str,
    environment: str,
    names: Names | None = None,
    staged: tuple[dict[str, str], dict[str, str]] | None = None,
) -> Report:
    """Return the findings, or raise TopologyError when the facts cannot be established."""
    names = names or Names()
    if len({names.central, names.console, names.postgres}) != 3:
        raise TopologyError("the central, console and Postgres service names must differ")
    report = Report()
    data = query(transport, "ClioraTrustProject", PROJECT_QUERY, {"projectId": project_id})
    project = _need(data.get("project"), dict, "project")
    if _str(project, "id", "project") != project_id:
        raise TopologyError("unrecognised Railway API response: a different project answered")

    matches = [
        _str(env, "id", "environment")
        for env in _nodes(project, "environments", "project")
        if _str(env, "name", "environment") == environment
    ]
    if len(matches) != 1:
        raise TopologyError(f"environment {environment!r} matched {len(matches)} environments")
    environment_id = matches[0]

    in_environment: dict[str, str] = {}
    for service in _nodes(project, "services", "project"):
        name, service_id = _str(service, "name", "service"), _str(service, "id", "service")
        instances = _nodes(service, "serviceInstances", f"service {name!r}")
        if any(_str(i, "environmentId", "serviceInstance") == environment_id for i in instances):
            if name in in_environment:
                raise TopologyError(f"two services in {environment!r} are named {name!r}")
            in_environment[name] = service_id

    expected = {names.postgres, names.central, names.console}
    for name in sorted(set(in_environment) - expected):
        report.fail(
            f"unexpected service {name!r} in {environment!r}: it shares the private network "
            "and could forge forwarded headers to console or Central"
        )
    for name in sorted(expected - set(in_environment)):
        report.fail(f"expected service {name!r} is not in {environment!r}")
    if set(in_environment) == expected:
        report.ok(f"{environment!r} contains only {', '.join(sorted(expected))}")

    for role, name in (("central", names.central), ("console", names.console)):
        if name not in in_environment:
            continue
        exposure = query(
            transport,
            "ClioraTrustExposure",
            EXPOSURE_QUERY,
            {
                "projectId": project_id,
                "environmentId": environment_id,
                "serviceId": in_environment[name],
            },
        )
        domains = _need(exposure.get("domains"), dict, f"{name}.domains")
        public = [
            _str(_need(item, dict, f"{name}.{kind}[]"), "domain", f"{name}.{kind}[]")
            for kind in ("serviceDomains", "customDomains")
            for item in _need(domains.get(kind), list, f"{name}.domains.{kind}")
        ]
        proxies = _need(exposure.get("tcpProxies"), list, f"{name}.tcpProxies")
        if proxies:
            report.fail(
                f"{role} service {name!r} has {len(proxies)} TCP proxy(ies); TCP proxies bypass "
                "Railway's HTTP edge, so forwarded headers arrive unsanitized"
            )
        else:
            report.ok(f"{role} service {name!r} has no TCP proxy")
        if role == "central":
            if public:
                report.fail(
                    f"central service {name!r} has {len(public)} public domain(s); it must be "
                    "reachable only from the console over the private network"
                )
            else:
                report.ok(f"central service {name!r} has no public domain")
        elif _need(domains.get("customDomains"), list, f"{name}.domains.customDomains"):
            report.ok(
                "console has a custom domain; if Cloudflare proxies it, Railway derives "
                "X-Real-IP from CF-Connecting-IP only for Cloudflare's IPv4 ranges, so check "
                "the Cloudflare caveat in docs/deployment-railway.md"
            )

    if staged is not None:
        central_vars, console_vars = staged
        report.ok("variables: checked the staged files supplied, not the live values")
    else:
        if {names.central, names.console} - set(in_environment):
            report.fail("trust variables not checked: central or console is not in the environment")
            return report
        central_vars = _variables_of(
            transport, project_id, environment_id, in_environment[names.central]
        )
        console_vars = _variables_of(
            transport, project_id, environment_id, in_environment[names.console]
        )
    check_keywords(report, central_vars, console_vars)
    return report


def project_id_from_status(raw: Any) -> str:
    """`railway status --json` prints the linked project; only its id is used."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise TopologyError("unrecognised `railway status --json` output (no project id)")
    return raw["id"]


# The CLI refreshes its OAuth access token when any `railway` command runs; this check only
# reads it, so an access token this close to expiry is treated as already expired.
EXPIRY_MARGIN_SECONDS = 60
REFRESH_HINT = "run any railway command (e.g. `railway whoami`) to refresh it, then retry"


def _expires_at(value: Any) -> float:
    """`tokenExpiresAt` as epoch seconds. CLI 5.x writes integer seconds; milliseconds and
    ISO-8601 strings are accepted defensively. Anything else is malformed (fail closed)."""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int | float) and not isinstance(value, bool):
        seconds = float(value)
        if not math.isfinite(seconds):
            raise TopologyError("Railway CLI config has an unreadable tokenExpiresAt")
        return seconds / 1000 if seconds > 1e12 else seconds  # > 1e12 cannot be seconds
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            return parsed.timestamp()
    raise TopologyError("Railway CLI config has an unreadable tokenExpiresAt")


def cli_token(environ: dict[str, str], home: Path, now: float | None = None) -> str:
    """The API token: RAILWAY_API_TOKEN, else the CLI login's legacy `user.token`, else its
    OAuth `user.accessToken` (CLI 5.x) while unexpired. No token value is ever printed."""
    token = environ.get("RAILWAY_API_TOKEN", "").strip()
    if token:
        return token
    path = Path(environ.get("RAILWAY_CONFIG_FILE") or home / ".railway" / "config.json")
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise TopologyError(f"no Railway CLI session ({path}: {type(exc).__name__})") from exc
    if not isinstance(config, dict):
        raise TopologyError(f"unrecognised Railway CLI config ({path})")
    user = config.get("user")
    if user is None:
        raise TopologyError("the Railway CLI is not logged in (run `railway login`)")
    if not isinstance(user, dict):
        raise TopologyError(f"unrecognised Railway CLI config ({path}: user)")
    for key in ("token", "accessToken"):
        if user.get(key) is not None and not isinstance(user.get(key), str):
            raise TopologyError(f"unrecognised Railway CLI config ({path}: user.{key})")
    legacy, access = user.get("token") or "", user.get("accessToken") or ""
    if legacy:
        return legacy
    if not access:
        raise TopologyError("the Railway CLI is not logged in (run `railway login`)")
    if user.get("tokenExpiresAt") is not None:
        current = time.time() if now is None else now
        if _expires_at(user["tokenExpiresAt"]) <= current + EXPIRY_MARGIN_SECONDS:
            raise TopologyError(f"the Railway CLI access token has expired; {REFRESH_HINT}")
    return access


def http_transport(token: str) -> Transport:
    def send(operation: str, text: str, variables: dict[str, str]) -> Any:
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(
                {"operationName": operation, "query": text, "variables": variables}
            ).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "cliora-check-trust-topology",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            exc.close()
            raise TopologyError(f"Railway API answered HTTP {exc.code} to {operation}") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise TopologyError(
                f"Railway API unreachable or not JSON ({type(exc).__name__})"
            ) from exc

    return send


def replay_transport(path: Path) -> Transport:
    bundle = json.loads(path.read_text())
    if not isinstance(bundle, dict) or bundle.get("format") != REPLAY_FORMAT:
        raise TopologyError(f"{path} is not a {REPLAY_FORMAT} file")
    exchanges = _need(bundle.get("exchanges"), list, "replay.exchanges")

    def send(operation: str, text: str, variables: dict[str, str]) -> Any:
        for item in exchanges:
            item = _need(item, dict, "replay.exchanges[]")
            if item.get("operation") == operation and item.get("variables") == variables:
                return item.get("response")
        raise TopologyError(f"replay has no recorded {operation} response for {variables}")

    return send


def recording(transport: Transport, sink: list[dict[str, Any]]) -> Transport:
    """Record topology exchanges as evidence. Variable responses hold secrets: never kept."""

    def send(operation: str, text: str, variables: dict[str, str]) -> Any:
        body = transport(operation, text, variables)
        if operation != "ClioraTrustVariables":
            sink.append({"operation": operation, "variables": variables, "response": body})
        return body

    return send


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_trust_topology", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--environment", default="production")
    project = parser.add_mutually_exclusive_group(required=True)
    project.add_argument("--project-id")
    project.add_argument("--status-json", type=Path, help="output of `railway status --json`")
    parser.add_argument("--central-service", default="central")
    parser.add_argument("--console-service", default="console")
    parser.add_argument("--postgres-service", default="Postgres")
    parser.add_argument("--central-vars", type=Path, help="staged Central variables (JSON)")
    parser.add_argument("--console-vars", type=Path, help="staged console variables (JSON)")
    parser.add_argument("--replay", type=Path, help="recorded responses; no network access")
    parser.add_argument("--record", type=Path, help="write topology responses (no variables)")
    args = parser.parse_args(argv)
    if (args.central_vars is None) != (args.console_vars is None):
        parser.error("--central-vars and --console-vars go together")

    sink: list[dict[str, Any]] = []
    try:
        project_id = args.project_id or project_id_from_status(
            json.loads(args.status_json.read_text())
        )
        staged = None
        if args.central_vars is not None:
            staged = (
                check_env.normalise(json.loads(args.central_vars.read_text())),
                check_env.normalise(json.loads(args.console_vars.read_text())),
            )
        if args.replay is not None:
            transport = replay_transport(args.replay)
        else:
            transport = http_transport(cli_token(dict(os.environ), Path.home()))
        report = evaluate(
            recording(transport, sink),
            project_id=project_id,
            environment=args.environment,
            names=Names(args.central_service, args.console_service, args.postgres_service),
            staged=staged,
        )
    except (TopologyError, OSError, ValueError) as exc:
        print(f"FAIL (closed): {exc}")
        return 2
    finally:
        if args.record is not None and sink:
            args.record.write_text(
                json.dumps({"format": REPLAY_FORMAT, "exchanges": sink}, indent=2) + "\n"
            )
    for line in report.notes:
        print(line)
    print(f"\nproblems: {len(report.failures)}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
