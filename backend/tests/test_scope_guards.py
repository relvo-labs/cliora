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
    """The terminal is a byte pipe, and a run's event stream is stored **unparsed**.

    V2.2 puts the word this guard used to scan for (`agent`) on a route and an action,
    so — exactly as SCOPE-002 had to in V2.1 — the guard now has to say what it means
    rather than what it matches. Two things are being kept apart:

    * **The forbidden one** is the platform *interpreting* a runtime's internal events:
      a message type or an API field that models a tool call, a thought or a turn.
      That would make a third-party CLI's schema part of our contract, and it would
      change every time that CLI shipped.
    * **The permitted one** is carrying a run's JSONL output as an **opaque string**.
      `run_logs.data` is text, `GET /api/runs/{id}/logs` returns it verbatim, and no
      route, action or message names anything inside it (plan/18/06-…md §2.1).

    So the assertion drops the bare word and keeps the structural claim: nothing in the
    surface names an event *shape*.
    """
    assert _no_surface_for("tool_call", "toolcall", "thought", "turn") == []
    # Every declared message is control-plane or filesystem; none models runtime output.
    assert not [name for name in _message_names() if name.startswith("terminal-output")]
    # And the run log stays a string on the way out: the DTO exposes `data`, never a
    # parsed field. A `tool_name`, `event_type` or `content` column here would be the
    # first step towards owning somebody else's schema.
    from app.api.http import schemas

    assert set(schemas.RunLogLineDTO.model_fields) == {
        "seq",
        "data",
        "truncated",
        "received_at",
    }


def test_scope_002_no_central_approval_mechanism() -> None:
    """SCOPE-002 forbids the platform standing between an agent and its own actions.

    V2.1 adds `task.approve` and `POST /api/tasks/{id}/gates/{gate}`, and both contain
    the word this guard used to scan for — so the guard has to say what it means
    rather than what it matches. The two are different mechanisms:

    * **The forbidden one** gates *execution*: a request the agent's runtime makes,
      held until Central says yes. That would need an approval surface on the session,
      terminal or filesystem path, and a way for the daemon to ask and wait.
    * **The task-layer one** gates *governance*: a person ticks a review gate on a
      card. Nothing is held, nothing is waiting on it, and it cannot stop or permit a
      single byte the agent runs — in V2.1 nothing executes at all (ADR 0028 sec 1).

    So the assertion narrows to the execution path and keeps its teeth there, and the
    task layer is named explicitly rather than allowed by an unexamined word list.
    """
    execution_surface = " ".join(
        sorted(
            path
            for path in _route_paths()
            if "/sessions" in path or "/nodes" in path or "/tunnels" in path
        )
        + sorted(_message_names())
        + sorted(
            action for action in rbac.ALL_ACTIONS if not action.startswith(("task.", "project."))
        )
    ).lower()
    hits = [
        word for word in ("approve", "approval", "consent", "authoriz") if word in execution_surface
    ]
    assert hits == []
    # And the governance one stays where it is: on a card, never on a session.
    assert "task.approve" in rbac.ALL_ACTIONS
    assert not [path for path in _route_paths() if "gates" in path and "/sessions" in path]


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
    """The non-goal is **automatic** dispatch, not dispatch.

    V2.2 adds `POST /api/tasks/{id}/dispatch`, and it is a person pressing a button:
    it creates a queued row and returns. Nothing selects a machine, nothing is sent to
    one, and a runner only ever acquires work by polling for it (ADR 0029 sec 2). The
    words that would betray the forbidden shape are the ones about *choosing* — a
    schedule, an assignment, a priority ordering — so those stay in the list and the
    bare verb leaves it.

    `SCOPE-014`'s own file carries the harder half of this claim: that no code path
    pushes work at a node.
    """
    assert _no_surface_for("schedule", "assignment", "backlog", "autoassign") == []
    # Dispatch exists, is guarded by its own action, and that action is held by a
    # person's role — never by a run credential (which holds `task.update` only).
    assert "run.dispatch" in rbac.ALL_ACTIONS
    assert not [path for path in _route_paths() if "dispatch" in path and "/cli/" in path]


def test_scope_006_the_console_is_not_an_ide() -> None:
    """An IDE needs somewhere to save *what you are looking at*.

    Two write messages now exist. Neither can save a file you opened: image drop
    (ADR 0024) writes a new image to a name the daemon invents, and file upload
    (ADR 0026) writes a new file under a name the user typed but refuses to replace
    anything that is already there. There is still no message that edits, renames
    or deletes — and after 2026-08-03 that is a product decision rather than a
    backlog item: those verbs belong to the CLI and the terminal.
    """
    filesystem = {name for name in _message_names() if name.startswith("filesystem-")}
    assert filesystem == {
        "filesystem-list",
        "filesystem-read",
        "filesystem-search",
        "filesystem-upload",
        "filesystem-uploaded",
        "filesystem-store",
        "filesystem-stored",
    }


def test_scope_007_the_write_paths_are_both_additive() -> None:
    """Narrowed twice, never withdrawn (ADR 0024 then ADR 0026 — the same treatment
    SCOPE-011 got).

    The workspace is no longer read-only, so this guard does not assert that nothing
    writes. It asserts the shape of what does, and the shape is the point: **both
    write paths only ever add a file.** Neither can replace or remove one, so the
    console cannot be used to lose work.

    An addition to this set is not forbidden, but it must be deliberate: a third
    entry here means a third ADR against W1-W4, and a *mutating* path that is not
    additive means the whole argument in ADR 0026 sec 3 needs redoing.
    """
    file_routes = {path for path in _route_paths() if "/files" in path}
    mutating = {
        (method, path)
        for method, path in mounted_routes()
        if "/files" in path and method not in {"GET"}
    }
    assert file_routes, "the file surface disappeared; this guard is stale"
    assert mutating == {
        ("POST", "/api/sessions/{session_id}/files/images"),
        ("POST", "/api/sessions/{session_id}/files/upload"),
    }, (
        "the set of write paths changed. Two exist by decision (ADR 0024, ADR 0026); "
        "a third needs its own ADR against W1-W4, and a DELETE or PUT here would "
        "contradict ADR 0026 sec 3 rather than extend it."
    )
    assert rbac.FILE_BROWSE in rbac.ALL_ACTIONS
    assert rbac.FILE_UPLOAD in rbac.ALL_ACTIONS
    # Viewer stays read-only even though the system as a whole no longer is. Three
    # rounds of widening and this has not had to change once.
    assert rbac.FILE_UPLOAD not in rbac.ROLE_ACTIONS[rbac.VIEWER]
    assert _no_surface_for("file.edit", "file.delete", "file.rename") == []


def test_scope_007b_the_upload_request_cannot_name_the_file() -> None:
    """The single property that makes one write path safe (ADR 0024 §3).

    A `filename` field would reintroduce path traversal, double extensions and
    overwrite in one move, and it would buy nothing: nobody needs the screenshot
    to keep its original name. Defended here as well as in the schema because a
    comment is not a defence — this is the same reasoning that put the argv
    guard in place for `session.start`.
    """
    upload = json.loads((MESSAGE_SCHEMAS / "filesystem-upload.schema.json").read_text())
    assert set(upload["properties"]) == {"session_id", "data"}
    assert upload["additionalProperties"] is False
    forbidden = {
        "filename",
        "name",
        "path",
        "dir",
        "directory",
        "extension",
        "ext",
        "mime",
        "overwrite",
    }
    assert forbidden.isdisjoint(upload["properties"])


def test_scope_007c_the_store_request_cannot_replace_anything() -> None:
    """The mirror of 007b, and the property that keeps this round small (ADR 0026).

    File upload *must* let the caller name its destination — a name is what makes a
    file useful — so the guard cannot be "there is no name field". It is two
    narrower things instead:

    * a filename cannot hold a path, because `directory` and `filename` are separate
      fields and the filename pattern excludes a separator. This matters concretely:
      URL encoding decodes `%2F` to a separator, so the wire has to state the rule
      rather than trust the order of decode-then-validate.
    * nothing can ask to replace, chmod or retype the target. Without that, the
      version tokens, trash can and undo semantics this round does not have would
      all become necessary.
    """
    store = json.loads((MESSAGE_SCHEMAS / "filesystem-store.schema.json").read_text())
    assert set(store["properties"]) == {"session_id", "directory", "filename", "data"}
    assert store["additionalProperties"] is False
    forbidden = {
        "overwrite",
        "replace",
        "force",
        "mode",
        "chmod",
        "mime",
        "precondition",
        "revision",
        "etag",
        "if_match",
    }
    assert forbidden.isdisjoint(store["properties"])
    # A filename is one segment. The pattern is the enforcement; this asserts the
    # pattern is actually there, because a schema that lost it would still validate
    # every well-formed request.
    assert "/" in store["properties"]["filename"]["pattern"]


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

    # **Central talks to a node over the authenticated WebSocket and over nothing else.**
    #
    # Until V2.4 that was enforced as "no HTTP client anywhere", which was a good proxy
    # for the rule and is no longer the same statement as it. V2.4 gives Central one
    # outbound call — opening a pull request on a provider's public API — and that is
    # not proxying and is not aimed at a node (ADR 0033 §3).
    #
    # So the guard narrows to what it was always defending, and gets **stricter** in the
    # process: an HTTP client may be imported by exactly one module, whose only
    # reachable hosts come from a deployment-level allowlist that no repository row can
    # influence. Widening the allowlist to a node's address would still be a proxy —
    # which is why the allowlist's default is a single public host and lives in
    # settings rather than in data.
    HTTP_CLIENTS = {"httpx", "requests", "aiohttp", "urllib3"}
    PROVIDER_MODULE = "services/providers.py"
    offenders: dict[str, set[str]] = {}
    for path, text in sources.items():
        imported: set[str] = set()
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        hit = imported & HTTP_CLIENTS
        if hit and not str(path).endswith(PROVIDER_MODULE):
            offenders[str(path.relative_to(app_root))] = hit
    assert offenders == {}, (
        "an HTTP client appeared outside the provider adapter: "
        f"{offenders}. Central reaches a node over the WebSocket and nothing else; the "
        f"one permitted client lives in {PROVIDER_MODULE} and may only call hosts on "
        "the deployment's provider allowlist."
    )

    # And that module cannot be pointed at a node: the base URL is a setting, never a
    # column, so no repository row decides where Central connects.
    provider_source = next(
        text for path, text in sources.items() if str(path).endswith(PROVIDER_MODULE)
    )
    assert "provider_api_host_list" in provider_source, (
        "the provider adapter must check the deployment's host allowlist before it makes a request"
    )
    for column in ("repository.host", "row.host", "repository.scheme"):
        assert f"{column}}}" not in provider_source, (
            f"the provider adapter interpolated {column} into a URL; the address is a "
            "deployment setting, not repository data"
        )

    # And the tunnel surface carries no field that could name where to connect: the provider
    # host is a daemon-side constant and the target is always the node's own loopback (SEC-002).
    schema = json.loads((MESSAGE_SCHEMAS / "tunnel-open.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert not {"host", "hostname", "url", "scheme", "ssh_options", "provider_options"} & set(
        schema["properties"]
    )
