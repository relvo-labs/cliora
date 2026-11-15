"""Issue 184: the Railway trust keywords are only allowed on the topology they rely on.

Every response here is replayed from a fixture; the live Railway API is never called.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "railway-topology-expected.json"
_spec = importlib.util.spec_from_file_location(
    "check_trust_topology", ROOT / "scripts/railway/check_trust_topology.py"
)
assert _spec is not None and _spec.loader is not None
topology = importlib.util.module_from_spec(_spec)
sys.modules["check_trust_topology"] = topology
_spec.loader.exec_module(topology)

PROJECT = "prj-0001"
NAMES = topology.Names(central="central", console="cliora", postgres="Postgres")
CENTRAL_ID, CONSOLE_ID = "svc-central-0001", "svc-console-0001"
GOOD_VARS = {
    CENTRAL_ID: {
        "FORWARDED_ALLOW_IPS": "railway-private-environment",
        "CLIORA_JWT_SECRET": "s3cr3t-canary",
    },
    CONSOLE_ID: {"CLIORA_TRUSTED_PROXY_CIDRS": "railway-edge", "PORT": "8080"},
}


def bundle() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def response(data: dict[str, Any], operation: str, service_id: str | None = None) -> dict:
    for item in data["exchanges"]:
        if item["operation"] == operation and item["variables"].get("serviceId") == service_id:
            return item["response"]
    raise AssertionError(f"fixture lacks {operation} {service_id}")


def transport(data: dict[str, Any], variables: dict[str, dict[str, str]] | None = None):
    """Replay the fixture; serve live-variable responses from `variables`."""
    variables = GOOD_VARS if variables is None else variables

    def send(operation: str, text: str, args: dict[str, str]) -> Any:
        if operation == "ClioraTrustVariables":
            return {"data": {"variables": variables[args["serviceId"]]}}
        for item in data["exchanges"]:
            if item["operation"] == operation and item["variables"] == args:
                return copy.deepcopy(item["response"])
        raise AssertionError(f"unexpected request {operation} {args}")

    return send


def run(data: dict[str, Any], **kwargs: Any):
    kwargs.setdefault("names", NAMES)
    return topology.evaluate(
        transport(data, kwargs.pop("variables", None)),
        project_id=PROJECT,
        environment="production",
        **kwargs,
    )


def test_expected_topology_passes() -> None:
    report = run(bundle())
    assert report.failures == []
    assert any("contains only Postgres, central, cliora" in note for note in report.notes)


def test_no_variable_value_is_printed() -> None:
    report = run(
        bundle(),
        variables={
            CENTRAL_ID: {**GOOD_VARS[CENTRAL_ID], "FORWARDED_ALLOW_IPS": "fd00::1/128"},
            CONSOLE_ID: GOOD_VARS[CONSOLE_ID],
        },
    )
    joined = "\n".join(report.notes)
    assert "s3cr3t-canary" not in joined and "fd00::1" not in joined
    assert "FORWARDED_ALLOW_IPS" in joined


def test_a_service_only_in_another_environment_does_not_count() -> None:
    data = bundle()
    names = [
        edge["node"]["name"]
        for edge in response(data, "ClioraTrustProject")["data"]["project"]["services"]["edges"]
    ]
    assert "scratch" in names  # present in staging only
    assert run(data).failures == []


def test_an_extra_service_fails() -> None:
    data = bundle()
    services = response(data, "ClioraTrustProject")["data"]["project"]["services"]["edges"]
    services.append(
        {
            "node": {
                "id": "svc-x",
                "name": "redis",
                "serviceInstances": {
                    "pageInfo": {"hasNextPage": False},
                    "edges": [{"node": {"environmentId": "env-prod-0001"}}],
                },
            }
        }
    )
    failures = run(data).failures
    assert any("unexpected service 'redis'" in item for item in failures)


def test_a_missing_expected_service_fails() -> None:
    failures = run(bundle(), names=topology.Names("central", "console", "Postgres")).failures
    assert any("'cliora'" in item for item in failures)  # the real console is now "extra"
    assert any("expected service 'console'" in item for item in failures)


@pytest.mark.parametrize("service_id,role", [(CONSOLE_ID, "console"), (CENTRAL_ID, "central")])
def test_a_tcp_proxy_fails(service_id: str, role: str) -> None:
    data = bundle()
    response(data, "ClioraTrustExposure", service_id)["data"]["tcpProxies"].append(
        {"domain": "roundhouse.proxy.rlwy.net", "proxyPort": 41234}
    )
    failures = run(data).failures
    assert len(failures) == 1 and f"{role} service" in failures[0] and "TCP proxy" in failures[0]


@pytest.mark.parametrize("kind", ["serviceDomains", "customDomains"])
def test_a_public_domain_on_central_fails(kind: str) -> None:
    data = bundle()
    response(data, "ClioraTrustExposure", CENTRAL_ID)["data"]["domains"][kind].append(
        {"domain": "central.example.com"}
    )
    failures = run(data).failures
    assert len(failures) == 1 and "public domain" in failures[0]


@pytest.mark.parametrize(
    "service_id,name,value",
    [
        (CENTRAL_ID, "FORWARDED_ALLOW_IPS", None),
        (CENTRAL_ID, "FORWARDED_ALLOW_IPS", "*"),
        (CENTRAL_ID, "FORWARDED_ALLOW_IPS", "fd00:59::2/128"),
        (CENTRAL_ID, "FORWARDED_ALLOW_IPS", " railway-private-environment"),
        (CONSOLE_ID, "CLIORA_TRUSTED_PROXY_CIDRS", None),
        (CONSOLE_ID, "CLIORA_TRUSTED_PROXY_CIDRS", "0.0.0.0/0"),
        (CONSOLE_ID, "CLIORA_TRUSTED_PROXY_CIDRS", "railway-edge,10.0.0.1/32"),
        (CONSOLE_ID, "CLIORA_TRUSTED_PROXY_CIDRS", "railway-private-environment"),
    ],
)
def test_a_missing_or_wrong_keyword_fails(service_id: str, name: str, value: str | None) -> None:
    variables = copy.deepcopy(GOOD_VARS)
    if value is None:
        del variables[service_id][name]
    else:
        variables[service_id][name] = value
    failures = run(bundle(), variables=variables).failures
    assert len(failures) == 1 and name in failures[0]


def test_staged_variables_are_checked_instead_of_live_ones() -> None:
    staged = (
        {"FORWARDED_ALLOW_IPS": "railway-private-environment"},
        {"CLIORA_TRUSTED_PROXY_CIDRS": ""},
    )
    failures = run(bundle(), variables={}, staged=staged).failures
    assert failures == ["console CLIORA_TRUSTED_PROXY_CIDRS is not exactly railway-edge"]


@pytest.mark.parametrize(
    "body",
    [
        {"errors": [{"message": "Not Authorized"}], "data": None},
        {"errors": [{"message": "Not Authorized"}], "data": {"project": None}},
        {"data": None},
        {"message": "Unauthorized"},
        "<html>login</html>",
        None,
    ],
    ids=["graphql-unauth", "unauth-with-partial-data", "no-data", "rest-error", "html", "empty"],
)
def test_unauthenticated_or_unrecognised_responses_fail_closed(body: Any) -> None:
    data = bundle()
    data["exchanges"][0]["response"] = body
    with pytest.raises(topology.TopologyError):
        run(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["data"]["project"].pop("services"),
        lambda p: p["data"]["project"]["services"].update(edges={"node": {}}),
        lambda p: p["data"]["project"]["services"]["edges"][0]["node"].pop("serviceInstances"),
        lambda p: p["data"]["project"]["environments"]["edges"].clear(),
        lambda p: p["data"]["project"].update(id="prj-other"),
        lambda p: p["data"]["project"]["environments"]["edges"].append(
            {"node": {"id": "env-dup", "name": "production"}}
        ),
        lambda p: p["data"]["project"]["services"]["pageInfo"].update(hasNextPage=True),
        lambda p: p["data"]["project"]["services"].pop("pageInfo"),
        lambda p: p["data"]["project"]["environments"]["pageInfo"].update(hasNextPage=None),
        lambda p: p["data"]["project"]["services"]["edges"][0]["node"]["serviceInstances"][
            "pageInfo"
        ].update(hasNextPage=True),
    ],
    ids=[
        "no-services",
        "edges-not-list",
        "no-instances",
        "no-environment",
        "other-project",
        "dup-env",
        "services-next-page",
        "services-no-pageinfo",
        "environments-pageinfo-null",
        "instances-next-page",
    ],
)
def test_an_unrecognised_project_shape_fails_closed(mutate: Any) -> None:
    data = bundle()
    mutate(response(data, "ClioraTrustProject"))
    with pytest.raises(topology.TopologyError):
        run(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["data"].pop("tcpProxies"),
        lambda e: e["data"].update(tcpProxies=None),
        lambda e: e["data"]["domains"].pop("customDomains"),
        lambda e: e["data"]["domains"].update(serviceDomains=[{"name": "x"}]),
        lambda e: e.update(errors=[{"message": "Problem processing request"}]),
    ],
    ids=["no-tcp", "tcp-null", "no-custom", "domain-without-name", "api-error"],
)
def test_an_unrecognised_exposure_shape_fails_closed(mutate: Any) -> None:
    data = bundle()
    mutate(response(data, "ClioraTrustExposure", CENTRAL_ID))
    with pytest.raises(topology.TopologyError):
        run(data)


@pytest.mark.parametrize(
    "payload", [{"data": {"variables": None}}, {"data": {"variables": {"A": 1}}}]
)
def test_unrecognised_variables_fail_closed(payload: Any) -> None:
    def send(operation: str, text: str, args: dict[str, str]) -> Any:
        if operation == "ClioraTrustVariables":
            return payload
        return transport(bundle())(operation, text, args)

    with pytest.raises(topology.TopologyError):
        topology.evaluate(send, project_id=PROJECT, environment="production", names=NAMES)


@pytest.mark.parametrize("raw", [{"id": ""}, {"name": "x"}, [], "not logged in"])
def test_unrecognised_railway_status_fails_closed(raw: Any) -> None:
    with pytest.raises(topology.TopologyError):
        topology.project_id_from_status(raw)
    assert topology.project_id_from_status({"id": PROJECT, "name": "cliora"}) == PROJECT


def test_cli_session_token_is_required(tmp_path: Path) -> None:
    with pytest.raises(topology.TopologyError):
        topology.cli_token({}, tmp_path)  # no ~/.railway/config.json
    (tmp_path / ".railway").mkdir()
    (tmp_path / ".railway/config.json").write_text(json.dumps({"user": {}}))
    with pytest.raises(topology.TopologyError, match="not logged in"):
        topology.cli_token({}, tmp_path)
    (tmp_path / ".railway/config.json").write_text(json.dumps({"user": {"token": "t"}}))
    assert topology.cli_token({}, tmp_path) == "t"
    assert topology.cli_token({"RAILWAY_API_TOKEN": "env"}, tmp_path) == "env"


def _cli(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    central = tmp_path / "central.json"
    console = tmp_path / "console.json"
    central.write_text(json.dumps(GOOD_VARS[CENTRAL_ID]))
    console.write_text(
        json.dumps([{"name": "CLIORA_TRUSTED_PROXY_CIDRS", "value": "railway-edge"}])
    )
    return subprocess.run(
        [
            str(ROOT / "scripts/railway/check-trust-topology.sh"),
            "--replay",
            str(FIXTURE),
            "--project-id",
            PROJECT,
            "--console-service",
            "cliora",
            "--central-vars",
            str(central),
            "--console-vars",
            str(console),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_operator_entry_point_passes_on_the_expected_fixture(tmp_path: Path) -> None:
    result = _cli(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "problems: 0" in result.stdout
    assert "s3cr3t-canary" not in result.stdout


def test_operator_entry_point_fails_on_a_topology_problem(tmp_path: Path) -> None:
    result = _cli(tmp_path, "--console-service", "console")
    assert result.returncode == 1, result.stdout + result.stderr


def test_operator_entry_point_fails_closed_without_variables(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(ROOT / "scripts/railway/check-trust-topology.sh"),
            "--replay",
            str(FIXTURE),
            "--project-id",
            PROJECT,
            "--console-service",
            "cliora",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2 and "FAIL (closed)" in result.stdout


def test_record_never_keeps_variable_responses(tmp_path: Path) -> None:
    sink: list[dict[str, Any]] = []
    topology.evaluate(
        topology.recording(transport(bundle()), sink),
        project_id=PROJECT,
        environment="production",
        names=NAMES,
    )
    assert {item["operation"] for item in sink} == {"ClioraTrustProject", "ClioraTrustExposure"}
    assert "s3cr3t-canary" not in json.dumps(sink)


def test_operator_entry_point_fails_closed_when_cli_is_not_logged_in(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "railway").write_text("#!/bin/sh\necho 'Unauthorized. Please login' >&2\nexit 1\n")
    (fake / "railway").chmod(0o755)
    result = subprocess.run(
        [str(ROOT / "scripts/railway/check-trust-topology.sh"), "--console-service", "cliora"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": f"{fake}:/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert result.returncode == 2 and "not logged in" in result.stderr
