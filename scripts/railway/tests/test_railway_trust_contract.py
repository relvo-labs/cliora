"""Issue 184: the Railway trust contract is a named opt-in, never a hand-typed global range."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "deploy/railway/19-trusted-proxies.sh"
KEYWORD_INCLUDE = (
    "# railway-edge (#184): X-Real-IP from Railway's HTTP edge, any socket peer\n"
    "set_real_ip_from 0.0.0.0/0;\n"
    "set_real_ip_from ::/0;\n"
)
spec = importlib.util.spec_from_file_location(
    "env_cases", Path(__file__).with_name("test_check_env.py")
)
assert spec and spec.loader
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


def render(tmp_path: Path, value: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(RENDERER), *args],
        env={
            **os.environ,
            "CLIORA_TRUSTED_PROXY_DIR": str(tmp_path),
            "CLIORA_TRUSTED_PROXY_CIDRS": value,
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("value", ["railway-edge", " railway-edge\n", ",railway-edge,"])
def test_railway_edge_keyword_trusts_x_real_ip_from_any_peer(tmp_path: Path, value: str) -> None:
    result = render(tmp_path, value)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "realip.conf").read_text() == KEYWORD_INCLUDE


@pytest.mark.parametrize(
    "value",
    [
        "0.0.0.0/0",
        "::/0",
        "0::/0",
        "10.0.0.1/32,::/0",
        "railway-edge,10.23.0.4/32",
        "railway-edge railway-edge",
        "Railway-Edge",
        "railway_edge",
        "railway-private-environment",
        "*",
    ],
)
def test_only_the_exact_keyword_means_global_trust(tmp_path: Path, value: str) -> None:
    result = render(tmp_path, value)
    assert result.returncode != 0
    assert "CLIORA_TRUSTED_PROXY_CIDRS" in result.stderr
    assert not (tmp_path / "realip.conf").exists()


def test_numeric_lists_still_render_bounded_entries(tmp_path: Path) -> None:
    result = render(tmp_path, "10.23.0.4/32 fd00:59::2/128")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "realip.conf").read_text() == (
        "set_real_ip_from 10.23.0.4/32;\nset_real_ip_from fd00:59::2/128;\n"
    )


@pytest.mark.parametrize("value", ["railway-edge", "railway-edge,172.30.59.1/32"])
def test_compose_has_no_railway_edge(tmp_path: Path, value: str) -> None:
    result = render(tmp_path, value, "--allow-direct")
    assert result.returncode != 0
    assert not (tmp_path / "realip.conf").exists()


def test_compose_direct_and_host_proxy_paths_are_unchanged(tmp_path: Path) -> None:
    assert render(tmp_path, "", "--allow-direct").returncode == 0
    assert (tmp_path / "realip.conf").read_text() == ""
    assert render(tmp_path, "10.23.0.4/32", "--allow-direct").returncode == 0
    assert (tmp_path / "realip.conf").read_text() == "set_real_ip_from 10.23.0.4/32;\n"
    assert render(tmp_path, "0.0.0.0/0", "--allow-direct").returncode != 0


# --- Central: FORWARDED_ALLOW_IPS=railway-private-environment -----------------------------


def start(tmp_path: Path, value: str | None) -> subprocess.CompletedProcess[str]:
    """Run central.railway.json's startCommand with a fake uvicorn that prints its argv."""
    fake = tmp_path / "bin"
    fake.mkdir(exist_ok=True)
    (fake / "uvicorn").write_text('#!/bin/sh\nfor a; do printf "%s\\n" "$a"; done\n')
    (fake / "uvicorn").chmod(0o755)
    (tmp_path / "glob-bait").write_text("")  # an unquoted * would expand to this name
    command = json.loads((ROOT / "deploy/railway/central.railway.json").read_text())["deploy"][
        "startCommand"
    ]
    env = {k: v for k, v in os.environ.items() if k not in {"FORWARDED_ALLOW_IPS", "PORT"}}
    env["PATH"] = f"{fake}:{env['PATH']}"
    if value is not None:
        env["FORWARDED_ALLOW_IPS"] = value
    return subprocess.run(
        ["sh", "-c", command],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_central_keyword_maps_to_trusting_every_private_peer(tmp_path: Path) -> None:
    result = start(tmp_path, "railway-private-environment")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "app.main:app",
        "--host",
        "",
        "--port",
        "8080",
        "--proxy-headers",
        "--forwarded-allow-ips=*",
    ]


def test_central_numeric_list_passes_through(tmp_path: Path) -> None:
    result = start(tmp_path, "fd00:59::2/128,10.59.0.2/32")
    assert result.returncode == 0, result.stderr
    assert "--forwarded-allow-ips=fd00:59::2/128,10.59.0.2/32" in result.stdout.splitlines()


@pytest.mark.parametrize("value", [None, ""])
def test_central_refuses_to_start_without_a_trust_choice(tmp_path: Path, value: str | None) -> None:
    result = start(tmp_path, value)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "railway-private-environment" in result.stderr
    assert "docs/deployment-railway.md" in result.stderr


@pytest.mark.parametrize(
    "value", ["*", "0.0.0.0/0", "::/0", "fd00::/0,10.0.0.1", "10.0.0.1,*", "0.0.0.0/0 "]
)
def test_central_rejects_hand_typed_global_trust(tmp_path: Path, value: str) -> None:
    result = start(tmp_path, value)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "railway-private-environment" in result.stderr


# Zero-length prefixes in spellings a `*/0 | */0[!0-9]*` pattern missed (review of #186):
# uvicorn 0.35.0 parses the first three as global networks.
PADDED_GLOBAL = ["0.0.0.0/00", "::/00", "::0/000", "0/00"]
PADDED_VALUES = (
    PADDED_GLOBAL
    + [f"10.59.0.2/32,{v}" for v in PADDED_GLOBAL]
    + [f"{v},fd00:59::2/128" for v in PADDED_GLOBAL]
    + ["0.0.0.0/00,::/00", "0.0.0.0/0.0.0.0", "::/0000", " ::/00", "10.59.0.2/32,::0/000 "]
)


@pytest.mark.parametrize("value", PADDED_VALUES)
def test_central_refuses_zero_prefix_in_any_spelling(tmp_path: Path, value: str) -> None:
    result = start(tmp_path, value)
    assert result.returncode == 64, result.stdout + result.stderr
    assert result.stdout == ""  # uvicorn was never executed
    assert "railway-private-environment" in result.stderr


GLOBAL_CORPUS = [
    *PADDED_VALUES,
    "*",
    "0.0.0.0/0",
    "::/0",
    "0::0/0",
    "10.0.0.1,*",
    "fd00:59::2/128,10.59.0.2/32",
    "10.0.0.0/8",
    "fd00::/8",
    "127.0.0.1",
]


@pytest.mark.parametrize("value", GLOBAL_CORPUS)
def test_central_never_starts_uvicorn_with_global_trust_unless_keyword(
    tmp_path: Path, value: str
) -> None:
    """Cross-check against the pinned uvicorn's own parser: whatever the startCommand lets
    through must not make uvicorn trust an arbitrary IPv4 or IPv6 peer."""
    from uvicorn.middleware.proxy_headers import _TrustedHosts

    result = start(tmp_path, value)
    if result.returncode != 0:
        return
    trust = next(
        a.split("=", 1)[1] for a in result.stdout.splitlines() if a.startswith("--forwarded")
    )
    hosts = _TrustedHosts(trust)
    assert not hosts.always_trust
    assert "203.0.113.9" not in hosts and "2001:db8::9" not in hosts


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["http", "websocket"])
async def test_uvicorn_035_semantics_of_the_mapped_and_unmapped_values(scope_type: str) -> None:
    """`*` (the mapping) honours the console's header from any private peer; the bare
    keyword, which the pre-#184 startCommand passed through verbatim, silently trusts
    nobody, so Central would have seen the console's address for every client."""
    import uvicorn
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    assert uvicorn.__version__ == "0.35.0"
    for trusted, expected in (("*", "198.51.100.42"), ("railway-private-environment", None)):
        observed: list[str] = []

        async def app(scope, receive, send, observed=observed):
            observed.append(scope["client"][0])

        peer = "fd12:3456::9"
        scope = {
            "type": scope_type,
            "scheme": "http",
            "client": (peer, 1234),
            "headers": [(b"x-forwarded-for", b"198.51.100.42")],
        }
        await ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None)
        assert observed == [expected or peer]


# --- Pre-deploy variable check ------------------------------------------------------------


def test_check_env_accepts_both_keywords() -> None:
    assert (
        cases.failures(
            cases.central(FORWARDED_ALLOW_IPS="railway-private-environment"),
            cases.console(CLIORA_TRUSTED_PROXY_CIDRS="railway-edge"),
            domain="cliora.example.com",
            draining_seconds=25,
        )
        == []
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("FORWARDED_ALLOW_IPS", "railway-edge"),
        ("FORWARDED_ALLOW_IPS", " railway-private-environment"),
        ("FORWARDED_ALLOW_IPS", "railway-private-environment,fd00::1"),
        ("CLIORA_TRUSTED_PROXY_CIDRS", "railway-private-environment"),
        ("CLIORA_TRUSTED_PROXY_CIDRS", "railway-edge,10.23.0.4/32"),
        ("CLIORA_TRUSTED_PROXY_CIDRS", "RAILWAY-EDGE"),
    ],
)
def test_check_env_rejects_misplaced_or_mixed_keywords(name: str, value: str) -> None:
    central, console = cases.central(), cases.console()
    (central if name == "FORWARDED_ALLOW_IPS" else console)[name] = value
    assert any(name in item for item in cases.failures(central, console))


@pytest.mark.parametrize("value", PADDED_VALUES)
@pytest.mark.parametrize("name", ["FORWARDED_ALLOW_IPS", "CLIORA_TRUSTED_PROXY_CIDRS"])
def test_check_env_refuses_zero_prefix_in_any_spelling(name: str, value: str) -> None:
    central, console = cases.central(), cases.console()
    (central if name == "FORWARDED_ALLOW_IPS" else console)[name] = value
    assert any(name in item for item in cases.failures(central, console))


@pytest.mark.parametrize("value", PADDED_VALUES)
def test_console_renderer_refuses_zero_prefix_in_any_spelling(tmp_path: Path, value: str) -> None:
    result = render(tmp_path, value)
    assert result.returncode != 0
    assert not (tmp_path / "realip.conf").exists()


@pytest.mark.parametrize("value", PADDED_VALUES)
def test_topology_check_refuses_zero_prefix_in_any_spelling(value: str) -> None:
    spec = importlib.util.spec_from_file_location(
        "topology_for_contract", ROOT / "scripts/railway/check_trust_topology.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["topology_for_contract"] = module
    spec.loader.exec_module(module)
    report = module.Report()
    module.check_keywords(
        report, {"FORWARDED_ALLOW_IPS": value}, {"CLIORA_TRUSTED_PROXY_CIDRS": value}
    )
    assert len(report.failures) == 2


@pytest.mark.parametrize("value", ["10.0.0.0/08", "fd00::/08"])
def test_preflight_and_startup_agree_on_leading_zero_prefixes(tmp_path: Path, value: str) -> None:
    """Python parses `/08` as /8; the startCommand refuses every `/0...` prefix, so the
    preflight must refuse it too rather than pass a value Central will not start with."""
    assert start(tmp_path, value).returncode == 64
    assert any(
        "FORWARDED_ALLOW_IPS" in item
        for item in cases.failures(cases.central(FORWARDED_ALLOW_IPS=value), cases.console())
    )
