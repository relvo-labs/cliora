"""Issue 59: edge admission limits and the single-address proxy trust contract."""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CONFIGS = [
    ROOT / "deploy/nginx/nginx.conf",
    ROOT / "deploy/railway/nginx.conf.template",
]


def source(path: Path) -> str:
    return re.sub(r"#[^\n]*", "", path.read_text())


def location(text: str, path: str, exact: bool = False) -> str:
    pattern = r"location " + ("= " if exact else "") + re.escape(path) + r" \{(.*?)\n        \}"
    match = re.search(pattern, text, re.S)
    assert match, f"missing location {path}"
    return match[1]


@pytest.mark.parametrize("config", CONFIGS, ids=["compose", "railway"])
def test_limits_are_scoped_to_approved_endpoints(config: Path) -> None:
    text = source(config)
    assert "limit_req_status 429;" in text
    assert "limit_conn_status 429;" in text
    for endpoint in ["login", "refresh", "register"]:
        path = "/api/nodes/register" if endpoint == "register" else f"/api/auth/{endpoint}"
        assert f"limit_req_zone $binary_remote_addr zone=cliora_{endpoint}:10m rate=10r/m;" in text
        block = location(text, path, exact=True)
        limit = f"limit_req zone=cliora_{endpoint}"
        limit += ";" if endpoint == "register" else " burst=10 nodelay;"
        assert limit in block
        for directive in [
            "proxy_read_timeout 240s;",
            "proxy_buffering on;",
            "proxy_http_version 1.1;",
            "proxy_set_header Host $host;",
        ]:
            assert directive in block
    assert "limit_req " not in location(text, "/api/")
    assert "limit_conn_zone $cliora_node_client zone=cliora_nodes:10m;" in text
    assert re.search(
        r'map \$uri \$cliora_node_client\s*\{\s*default "";\s*'
        r"~\^/ws/nodes/ \$binary_remote_addr;\s*\}",
        text,
    )
    ws = location(text, "/ws/")
    for directive in [
        "limit_conn cliora_nodes 50;",
        "proxy_read_timeout 3600s;",
        "proxy_send_timeout 3600s;",
        "proxy_buffering off;",
        "proxy_cache off;",
    ]:
        assert directive in ws


@pytest.mark.parametrize("config", CONFIGS, ids=["compose", "railway"])
def test_every_proxy_location_overwrites_forged_forwarding_chain(config: Path) -> None:
    text = source(config)
    assert "$proxy_add_x_forwarded_for" not in text
    for block in re.findall(r"location [^\n]+\{(.*?)\n        \}", text, re.S):
        if "proxy_pass " in block:
            assert "proxy_set_header X-Forwarded-For $remote_addr;" in block
            assert "proxy_set_header X-Real-IP $remote_addr;" in block


def test_railway_realip_is_explicit_and_has_no_global_trust() -> None:
    text = source(CONFIGS[1])
    assert "real_ip_header X-Real-IP;" in text
    assert "real_ip_recursive off;" in text
    assert "include /etc/nginx/trusted-proxies/*.conf;" in text
    assert not re.search(r"set_real_ip_from\s+(?:0\.0\.0\.0/0|::/0)", text)


def test_uvicorn_trust_is_bound_to_nginx() -> None:
    dockerfile = (ROOT / "deploy/backend.Dockerfile").read_text()
    entrypoint = json.loads(re.search(r"^ENTRYPOINT (.*)$", dockerfile, re.M)[1])
    assert "--proxy-headers" in entrypoint
    assert "--forwarded-allow-ips" not in entrypoint  # reads deployment-specific env
    compose = (ROOT / "deploy/compose/compose.yaml").read_text()
    assert 'FORWARDED_ALLOW_IPS: "172.30.59.2"' in compose
    assert "ipv4_address: 172.30.59.2" in compose
    railway = json.loads((ROOT / "deploy/railway/central.railway.json").read_text())
    command = railway["deploy"]["startCommand"]
    assert "FORWARDED_ALLOW_IPS:?" in command
    assert 'allow-ips=\\"*\\"' not in command


@pytest.mark.parametrize(
    "replacement",
    [
        "rate=11r/m",
        "burst=9",
        "limit_conn cliora_nodes 51",
        "X-Forwarded-For $proxy_add_x_forwarded_for",
    ],
)
def test_parity_rejects_security_drift(tmp_path: Path, replacement: str) -> None:
    host, railway = (p.read_text() for p in CONFIGS)
    original = {
        "rate=11r/m": "rate=10r/m",
        "burst=9": "burst=10",
        "limit_conn cliora_nodes 51": "limit_conn cliora_nodes 50",
        "X-Forwarded-For $proxy_add_x_forwarded_for": "X-Forwarded-For $remote_addr",
    }[replacement]
    assert original in railway
    a, b = tmp_path / "host.conf", tmp_path / "railway.conf"
    a.write_text(host)
    b.write_text(railway.replace(original, replacement, 1))
    result = subprocess.run(
        [str(ROOT / "scripts/railway/check-edge-parity.sh"), str(a), str(b)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, result.stdout


def test_parity_accepts_shipped_policy() -> None:
    result = subprocess.run(
        [str(ROOT / "scripts/railway/check-edge-parity.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("cidrs", ["10.23.0.4/32,fd00:59::2/128"])
def test_trusted_proxy_renderer(tmp_path: Path, cidrs: str) -> None:
    import os

    result = subprocess.run(
        ["sh", str(ROOT / "deploy/railway/19-trusted-proxies.sh")],
        env={
            **os.environ,
            "CLIORA_TRUSTED_PROXY_DIR": str(tmp_path),
            "CLIORA_TRUSTED_PROXY_CIDRS": cidrs,
        },
        check=False,
    )
    assert result.returncode == 0
    expected = "".join(f"set_real_ip_from {cidr};\n" for cidr in cidrs.split(",") if cidr)
    assert (tmp_path / "realip.conf").read_text() == expected


@pytest.mark.parametrize("cidrs", ["0.0.0.0/0", "::/0", "0.0.0.0/00", "10.0.0.1;include /tmp/x"])
def test_trusted_proxy_renderer_rejects_global_trust_and_injection(
    tmp_path: Path, cidrs: str
) -> None:
    import os

    result = subprocess.run(
        ["sh", str(ROOT / "deploy/railway/19-trusted-proxies.sh")],
        env={
            **os.environ,
            "CLIORA_TRUSTED_PROXY_DIR": str(tmp_path),
            "CLIORA_TRUSTED_PROXY_CIDRS": cidrs,
        },
        check=False,
    )
    assert result.returncode != 0
    assert not (tmp_path / "realip.conf").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["http", "websocket"])
async def test_uvicorn_honors_only_the_configured_nginx_hop(scope_type: str) -> None:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    observed = []

    async def app(scope, receive, send):
        observed.append(scope["client"][0])

    middleware = ProxyHeadersMiddleware(app, trusted_hosts=["172.30.59.2"])
    # nginx replaces an incoming forged chain with one socket-derived value; the config
    # test above pins that overwrite. Uvicorn then populates Starlette's client value.
    for peer in ["172.30.59.2", "172.30.59.4"]:
        scope = {
            "type": scope_type,
            "client": (peer, 1234),
            "scheme": "http",
            "headers": [(b"x-forwarded-for", b"198.51.100.42")],
        }
        await middleware(scope, None, None)
    assert observed == ["198.51.100.42", "172.30.59.4"]



def test_compose_direct_renderer_allows_empty_trust(tmp_path: Path) -> None:
    import os

    result = subprocess.run(
        ["sh", str(ROOT / "deploy/railway/19-trusted-proxies.sh"), "--allow-direct"],
        env={**os.environ, "CLIORA_TRUSTED_PROXY_DIR": str(tmp_path), "CLIORA_TRUSTED_PROXY_CIDRS": ""},
        check=False,
    )
    assert result.returncode == 0
    assert (tmp_path / "realip.conf").read_text() == ""
