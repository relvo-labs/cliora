"""PR 181 review: deployment must not silently fall back to a proxy-wide identity."""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "env_cases", Path(__file__).with_name("test_check_env.py")
)
assert spec and spec.loader
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


@pytest.mark.parametrize("value", ["", "__unset__", " , \t"])
def test_railway_preflight_requires_ingress_trust(value: str) -> None:
    problems = cases.failures(cases.central(), cases.console(CLIORA_TRUSTED_PROXY_CIDRS=value))
    assert any(
        "CLIORA_TRUSTED_PROXY_CIDRS" in item and "docs/deployment-railway.md" in item
        for item in problems
    )


@pytest.mark.parametrize("value", [None, "", " , \t"])
def test_railway_startup_requires_ingress_trust(tmp_path: Path, value: str | None) -> None:
    env = {**os.environ, "CLIORA_TRUSTED_PROXY_DIR": str(tmp_path)}
    env.pop("CLIORA_TRUSTED_PROXY_CIDRS", None)
    if value is not None:
        env["CLIORA_TRUSTED_PROXY_CIDRS"] = value
    result = subprocess.run(
        ["sh", str(ROOT / "deploy/railway/19-trusted-proxies.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "CLIORA_TRUSTED_PROXY_CIDRS" in result.stderr
    assert "docs/deployment-railway.md" in result.stderr
    assert not (tmp_path / "realip.conf").exists()


@pytest.mark.parametrize("name", ["FORWARDED_ALLOW_IPS", "CLIORA_TRUSTED_PROXY_CIDRS"])
@pytest.mark.parametrize("value", ["172.30.59.2/29", "fd00:59::1/64"])
def test_host_bit_cidrs_are_rejected(name: str, value: str) -> None:
    central, console = cases.central(), cases.console(CLIORA_TRUSTED_PROXY_CIDRS="10.23.0.4/32")
    (central if name == "FORWARDED_ALLOW_IPS" else console)[name] = value
    assert any(name in item for item in cases.failures(central, console))


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["http", "websocket"])
@pytest.mark.parametrize(
    "network,peer", [("172.30.59.0/29", "172.30.59.2"), ("fd00:59::/64", "fd00:59::1")]
)
async def test_canonical_network_is_actually_trusted_by_uvicorn_035(
    scope_type: str, network: str, peer: str
) -> None:
    import uvicorn
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    assert uvicorn.__version__ == "0.35.0"
    assert (
        cases.failures(
            cases.central(FORWARDED_ALLOW_IPS=network),
            cases.console(CLIORA_TRUSTED_PROXY_CIDRS="10.23.0.4/32"),
        )
        == []
    )
    observed = []

    async def app(scope, receive, send):
        observed.append(scope["client"][0])

    scope = {
        "type": scope_type,
        "scheme": "http",
        "client": (peer, 1234),
        "headers": [(b"x-forwarded-for", b"198.51.100.42")],
    }
    await ProxyHeadersMiddleware(app, trusted_hosts=network)(scope, None, None)
    assert observed == ["198.51.100.42"]


@pytest.mark.parametrize("trust", ["172.30.59.2/32", "fd00:59::/64"])
def test_parity_accepts_opt_in_compose_proxy(tmp_path: Path, trust: str) -> None:
    host = (ROOT / "deploy/nginx/nginx.conf").read_text()
    if "real_ip_header X-Real-IP;" not in host:
        host = host.replace(
            "http {", "http {\n    real_ip_header X-Real-IP;\n    real_ip_recursive off;"
        )
    host = host.replace("http {", f"http {{\n    set_real_ip_from {trust};")
    path = tmp_path / "compose.conf"
    path.write_text(host)
    result = subprocess.run(
        [str(ROOT / "scripts/railway/check-edge-parity.sh"), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "config", ["deploy/nginx/nginx.conf", "deploy/railway/nginx.conf.template"]
)
@pytest.mark.parametrize("trust", ["0.0.0.0/0", "::/0", "*"])
def test_parity_rejects_global_trust_in_either_topology(
    tmp_path: Path, config: str, trust: str
) -> None:
    text = (ROOT / config).read_text().replace("http {", f"http {{\n    set_real_ip_from {trust};")
    path = tmp_path / "bad.conf"
    path.write_text(text)
    args = [str(ROOT / "scripts/railway/check-edge-parity.sh")]
    args += (
        [str(path)]
        if "template" not in config
        else [str(ROOT / "deploy/nginx/nginx.conf"), str(path)]
    )
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    assert result.returncode != 0
