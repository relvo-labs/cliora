"""Static BP-05 guards for both deployed nginx configurations."""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
CONFIGS = (
    ROOT / "deploy/nginx/nginx.conf",
    ROOT / "deploy/railway/nginx.conf.template",
)
LOCATION = r"^/api/sessions/[0-9a-fA-F-]{36}/files/binary-preview$"


def _size(value: str) -> int:
    match = re.fullmatch(r"(\d+)([kKmM]?)", value)
    assert match, f"invalid nginx size: {value}"
    return (
        int(match.group(1))
        * {"": 1, "k": 1024, "m": 1024 * 1024}[match.group(2).lower()]
    )


def _directive(block: str, name: str) -> str:
    match = re.search(rf"^\s*{re.escape(name)}\s+([^;]+);", block, re.MULTILINE)
    assert match, f"missing {name}"
    return match.group(1).strip()


@pytest.mark.parametrize("config", CONFIGS, ids=("compose", "railway"))
def test_binary_preview_location(config: Path) -> None:
    source = config.read_text()
    # The four-space indentation pins this format to http rather than a server or location.
    fmt = re.search(
        r"^    log_format cliora_noquery\s+((?:[^;]|\n)*);", source, re.MULTILINE
    )
    assert fmt, "missing http-level cliora_noquery format"
    assert not re.search(
        r"\$(?:request(?![\w])|args(?![\w])|query_string(?![\w])|request_uri(?![\w]))",
        fmt.group(1),
    ), "cliora_noquery records a query-bearing variable"

    match = re.search(
        r'^        location ~ "' + re.escape(LOCATION) + r'" \{\n(.*?)^        \}',
        source,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "missing dedicated binary-preview regex location"
    body = "\n".join(line.split("#", 1)[0] for line in match.group(1).splitlines())
    assert _directive(body, "access_log").split()[-1] == "cliora_noquery"
    max_body = _size(_directive(body, "client_max_body_size"))
    buffer = _size(_directive(body, "client_body_buffer_size"))
    assert max_body == 24 * 1024, (
        "edge limit must match Central's 24576-byte body limit"
    )
    assert buffer >= max_body, "request body could spill into client_body_temp"
    assert _directive(body, "proxy_buffering") == "off"
    assert _directive(body, "proxy_max_temp_file_size") == "0"
    # The /api/ location has no add_header. Keeping this location the same lets it
    # inherit every security header from the server block.
    assert not re.search(r"^\s*add_header\s", body, re.MULTILINE)
