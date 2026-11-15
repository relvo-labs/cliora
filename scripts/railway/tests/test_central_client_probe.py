"""Central scope evidence must include both protocols and reject stale proxy identity."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "central_client_probe", Path(__file__).resolve().parents[1] / "central_client_probe.py"
)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def receipt(ip: str = "198.51.100.42") -> dict:
    return {
        "expected_ip": ip,
        "probes": [
            {"protocol": protocol, "path": f"/{protocol}/{index}"}
            for index in range(3)
            for protocol in ("http", "websocket")
        ],
    }


def logs(data: dict, *, wrong: str | None = None, omit: str | None = None) -> str:
    lines = []
    for item in data["probes"]:
        kind = item["protocol"]
        if kind == omit:
            continue
        ip = "fd00:59::2" if kind == wrong else data["expected_ip"]
        suffix = (
            f'GET {item["path"]} HTTP/1.1" 404 Not Found'
            if kind == "http"
            else f'WebSocket {item["path"]}" [accepted]'
        )
        lines.append(f'INFO: {ip}:0 - "{suffix}')
    return "\n".join(lines)


@pytest.mark.parametrize("ip", ["198.51.100.42", "2001:db8:59::42"])
def test_http_and_ws_scopes_match_independent_ipv4_or_ipv6_egress(ip: str) -> None:
    data = receipt(ip)
    probe.verify(data, logs(data))


@pytest.mark.parametrize("protocol", ["http", "websocket"])
def test_console_identity_on_either_protocol_fails(protocol: str) -> None:
    data = receipt()
    with pytest.raises(ValueError, match="expected"):
        probe.verify(data, logs(data, wrong=protocol))


@pytest.mark.parametrize("protocol", ["http", "websocket"])
def test_missing_protocol_is_not_a_pass(protocol: str) -> None:
    data = receipt()
    with pytest.raises(ValueError, match="missing Central"):
        probe.verify(data, logs(data, omit=protocol))


def test_unrelated_older_log_lines_do_not_prove_the_probe() -> None:
    with pytest.raises(ValueError, match="missing Central"):
        probe.verify(receipt(), 'INFO: 198.51.100.42:0 - "GET /healthz HTTP/1.1" 200 OK')
