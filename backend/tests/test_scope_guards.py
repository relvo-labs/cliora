"""Executable guards for the PRD §4 non-goals.

`plan/06/01` §5 asks a scope guard for a runnable boundary, contract or grep
check — an inspection checklist only where nothing else is possible. The twelve
`SCOPE-*` guards had neither: they pointed at a plan document, which records that
we decided not to build something but cannot notice when someone does.

Each test here asserts the *absence* of a surface, against the three places a
non-goal would have to appear to be real: the mounted HTTP route table, the RBAC
action list, and the versioned wire contract. Absence tests age badly when they
grep for words nobody would use, so each one names the surface a real
implementation of that non-goal would need, not a plausible-sounding string.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from test_authz import mounted_routes

from app.services import rbac

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "v1"
MESSAGE_SCHEMAS = CONTRACTS / "schemas" / "messages"


def _message_names() -> set[str]:
    return {path.stem.removesuffix(".schema") for path in MESSAGE_SCHEMAS.glob("*.json")}


def _route_paths() -> set[str]:
    return {path for _, path in mounted_routes()}


def _surface() -> str:
    """Everything a caller can name: route paths, action keys, message types."""
    return " ".join(sorted(_route_paths() | rbac.ALL_ACTIONS | _message_names())).lower()


def _no_surface_for(*words: str) -> list[str]:
    surface = _surface()
    return [word for word in words if word in surface]


def test_scope_001_no_surface_parses_runtime_internal_events() -> None:
    """The terminal is a byte pipe. Parsing Claude's or Codex's internal events
    would need a message type carrying them; there is none, and terminal output
    travels as an opaque binary frame rather than a structured payload."""
    assert _no_surface_for("agent", "tool_call", "toolcall", "thought", "turn") == []
    # Every declared message is control-plane or filesystem; none models runtime output.
    assert not [name for name in _message_names() if name.startswith("terminal-output")]


def test_scope_002_no_central_approval_mechanism() -> None:
    assert _no_surface_for("approve", "approval", "consent", "authoriz") == []


def test_scope_003_nothing_intercepts_the_cli_native_permission_prompt() -> None:
    """An interception point would have to be a message the daemon sends up when
    the CLI asks, and a reply the browser sends back. Neither exists: input and
    output are raw bytes in both directions."""
    assert _no_surface_for("prompt", "confirm", "permission_request") == []
    assert "session-start" in _message_names()
    start = json.loads((MESSAGE_SCHEMAS / "session-start.schema.json").read_text())
    assert set(start["properties"]) == {
        "session_id",
        "runtime",
        "workspace",
        "rows",
        "columns",
    }


def test_scope_004_no_multi_agent_collaboration_flow() -> None:
    assert _no_surface_for("workflow", "orchestr", "pipeline", "handoff") == []


def test_scope_005_no_automatic_task_dispatch() -> None:
    assert _no_surface_for("dispatch", "schedule", "assignment", "backlog") == []


def test_scope_006_the_console_is_not_an_ide() -> None:
    """An IDE needs somewhere to save. No route mutates a file and no filesystem
    message does anything but list, read or search."""
    filesystem = {name for name in _message_names() if name.startswith("filesystem-")}
    assert filesystem == {"filesystem-list", "filesystem-read", "filesystem-search"}


def test_scope_007_no_file_write_or_edit_surface() -> None:
    file_routes = {path for path in _route_paths() if "/files" in path}
    mutating = {
        (method, path)
        for method, path in mounted_routes()
        if "/files" in path and method not in {"GET"}
    }
    assert file_routes, "the read-only file surface disappeared; this guard is stale"
    assert mutating == set()
    assert rbac.FILE_BROWSE in rbac.ALL_ACTIONS
    assert _no_surface_for("file.write", "file.edit", "file.delete") == []


def test_scope_008_no_git_surface() -> None:
    assert _no_surface_for("git", "commit", "push", "merge_request", "pull_request") == []


def test_scope_009_no_semantic_analysis_of_cli_conversation() -> None:
    """Analysis would need the content first. Terminal bytes are never persisted,
    and the audit metadata sanitizer forbids the keys that could carry them."""
    from app.services import audit

    # Not "summary": /api/dashboard/summary counts nodes and sessions and has
    # nothing to do with what was said in a terminal.
    assert _no_surface_for("transcript", "embedding", "sentiment", "classify") == []
    forbidden = {key.lower() for key in audit.FORBIDDEN_METADATA_KEYS}
    assert {"content", "output"} <= forbidden


def test_scope_010_no_cross_runtime_behaviour_model() -> None:
    """The only thing shared across runtimes is an id from a closed allowlist. A
    unified behaviour model would need per-runtime capability or behaviour fields
    on the wire; the enum carries none."""
    start = json.loads((MESSAGE_SCHEMAS / "session-start.schema.json").read_text())
    # `shell` joined the allowlist in v1.5.0 (ADR 0021). It changes nothing here:
    # the field is still a closed enum of ids, with no capability or behaviour
    # field beside it for a unified model to be expressed in.
    assert start["properties"]["runtime"] == {"enum": ["claude", "codex", "shell", "fake"]}


def test_scope_011_the_front_end_cannot_name_a_command() -> None:
    """The load-bearing one (SEC-002, TECH-SEC-07). Session start accepts a
    runtime id and a workspace; there is no field a command could travel in.

    ADR 0023 widened what has to be true here. The daemon now adds a launch flag of
    its own (codex's sandbox bypass), so the property being defended is no longer just
    "no command string": nobody outside the node may name a flag, *or ask for a
    posture*. Both are asserted, because the second is the shape the next request for
    this will take — "let the user pick --model", "let Central turn the sandbox on for
    this one session" — and neither would be caught by the first assertion alone.
    """
    start = json.loads((MESSAGE_SCHEMAS / "session-start.schema.json").read_text())
    assert start["additionalProperties"] is False
    forbidden = {
        "command",
        "args",
        "argv",
        "shell",
        "env",
        "entrypoint",
        "flags",
        "sandbox",
        "sandbox_bypass",
        "sudo",
        "privileged",
    }
    assert not forbidden & set(start["properties"])
    # The five fields are the whole contract; a sixth is the thing this test exists
    # to notice.
    assert set(start["properties"]) == {
        "session_id",
        "runtime",
        "workspace",
        "rows",
        "columns",
    }


def test_scope_011_the_posture_fields_are_report_only() -> None:
    """A node reports its posture; nothing may set it (ADR 0023 D11).

    `sandbox_bypass` and `privileged_terminal` exist on the *node → Central*
    announces only. If either appeared on a message Central sends, or on an inbound
    HTTP body other than enrollment, the platform could grant itself root on a node.
    """
    inbound = json.loads((MESSAGE_SCHEMAS / "session-start.schema.json").read_text())
    assert "sandbox_bypass" not in inbound["properties"]

    register = json.loads((MESSAGE_SCHEMAS / "node-register.schema.json").read_text())
    assert register["properties"]["privileged_terminal"] == {"type": "boolean"}

    item = json.loads((MESSAGE_SCHEMAS / "runtime-item.schema.json").read_text())
    assert item["properties"]["sandbox_bypass"] == {"type": "boolean"}
    assert item["additionalProperties"] is False

    # No Central-authored message carries either field. The daemon-bound schemas are
    # the ones Central produces; a posture field in any of them would be an
    # instruction rather than a report.
    for name in ("session-start", "daemon-update", "tunnel-open", "terminal-size"):
        schema = json.loads((MESSAGE_SCHEMAS / f"{name}.schema.json").read_text())
        assert not {"privileged_terminal", "sandbox_bypass", "sandbox", "flags", "args"} & set(
            schema["properties"]
        ), f"{name} carries a posture or argv field"


def test_scope_012_the_vm_filesystem_is_not_mounted_on_central() -> None:
    """Files reach Central as relayed responses. A mount would show up as a path
    the server opens directly; the only filesystem access is through the daemon
    protocol."""
    app_root = Path(__file__).resolve().parents[1] / "app"
    # Imports, not raw text: a substring search for "fuse" finds every "refused".
    imported: set[str] = set()
    for path in app_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert not imported & {"fuse", "fusepy", "paramiko", "smbprotocol", "pysmb"}

    # And no shelling out to a mount: the only remote filesystem access Central
    # has is the daemon relay.
    sources = "\n".join(path.read_text(encoding="utf-8") for path in app_root.rglob("*.py"))
    for phrase in ("mount -t", "sshfs ", "mount.nfs", "os.system"):
        assert phrase not in sources, f"Central appears to mount a filesystem: {phrase}"


def test_scope_013_central_does_not_proxy_to_a_node_http_service() -> None:
    """Port forwarding is an integration, not a reverse proxy (ADR 0022).

    This is the mechanical half of the scope guard. The self-hosted design (plan/10, withdrawn)
    would have needed three things Central must not grow: a catch-all route that accepts an
    arbitrary path, an HTTP client aimed at a node, and a streaming relay between the two. The
    tunnel service sends a control frame and stores what comes back; nothing more.

    The reason to test rather than to trust the plan: a proxy is the obvious answer to the next
    request that arrives ("can I open the preview inside the console?"), and it would arrive as
    a small, reasonable-looking diff.
    """
    app_root = Path(__file__).resolve().parents[1] / "app"
    sources = {path: path.read_text(encoding="utf-8") for path in app_root.rglob("*.py")}
    blob = "\n".join(sources.values())

    # A catch-all path parameter is how a proxy route is spelled in FastAPI.
    for pattern in ("{path:path}", "{full_path:path}", "{proxy_path:path}"):
        assert pattern not in blob, f"a catch-all route appeared in Central: {pattern}"

    # No outbound HTTP client library: Central talks to nodes over the authenticated
    # WebSocket and to nothing else. (`httpx` is a test dependency; the app does not import it.)
    imported: set[str] = set()
    for path, text in sources.items():
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert not imported & {"httpx", "requests", "aiohttp", "urllib3"}, (
        "Central imports an HTTP client; the port-forwarding path must not route traffic"
    )

    # And the tunnel surface carries no field that could name where to connect: the provider
    # host is a daemon-side constant and the target is always the node's own loopback (SEC-002).
    schema = json.loads((MESSAGE_SCHEMAS / "tunnel-open.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert not {"host", "hostname", "url", "scheme", "ssh_options", "provider_options"} & set(
        schema["properties"]
    )
