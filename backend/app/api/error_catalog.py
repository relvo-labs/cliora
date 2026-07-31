"""The stable error vocabulary, and what each code means to a person (P4-07).

Three separate jobs used to be spread across route code, the protocol schema and the
browser, with nothing keeping them aligned:

1. **the code** — stable, machine-readable, safe to show;
2. **the safe message** — what a client may be told, which must never contain a node
   path, a SQL fragment, a daemon internal string or a secret;
3. **the guidance** — why it happened and what to do next, which is the difference
   between an error a user can act on and one they can only report.

This module is the single source for all three, and `docs/error-catalog.md` is
rendered from it (`scripts/p4/render_error_catalog.py`). Two assertions keep it
honest: every code Central raises must appear here, and every entry here must be
either raised by Central or present in the protocol's closed error enum — so the
catalog can neither miss a real code nor document a fictional one.

**Daemon internal errors never reach a client.** A daemon error frame is mapped to
one of these codes and answered with the *catalog's* message; the daemon's own string
goes to the log with the request id. That mapping is why a node's absolute paths and
internal state cannot arrive in an HTTP body (ADR 0014, extended to session/node/
update in P4-07).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fastapi import status

# Where a code originates. `central` codes are raised by this service; `daemon` codes
# arrive in a control-frame error and are relayed or mapped. A few are both.
CENTRAL = "central"
DAEMON = "daemon"


@dataclass(frozen=True, slots=True)
class ErrorEntry:
    """One stable code and everything a client needs to present it."""

    code: str
    http_status: int | None
    # Shown to the user verbatim. Reviewed for content: no path, no identifier, no
    # internal detail. `None` for codes that only ever travel on the daemon link.
    message: str
    # UI: the cause, in the user's terms.
    cause: str
    # UI: the single most useful next action.
    next_step: str
    # Whether repeating the same request could plausibly succeed. Drives whether the
    # UI offers "retry" — offering it on a permanent failure trains users to ignore it.
    retryable: bool
    # Whether an audit row accompanies this refusal. Only security-relevant refusals
    # are audited (ADR 0016): ordinary read 403s and validation errors are not, or the
    # trail would be buried in noise.
    audited: bool
    origin: str = CENTRAL


def _entry(
    code: str,
    http_status: int | None,
    message: str,
    cause: str,
    next_step: str,
    *,
    retryable: bool = False,
    audited: bool = False,
    origin: str = CENTRAL,
) -> tuple[str, ErrorEntry]:
    return code, ErrorEntry(
        code=code,
        http_status=http_status,
        message=message,
        cause=cause,
        next_step=next_step,
        retryable=retryable,
        audited=audited,
        origin=origin,
    )


CATALOG: dict[str, ErrorEntry] = dict(
    [
        # --- Authentication and authorization ---
        _entry(
            "UNAUTHENTICATED",
            status.HTTP_401_UNAUTHORIZED,
            "Missing bearer token",
            "The request carried no valid access token, or the session expired.",
            "Sign in again.",
            retryable=True,
        ),
        _entry(
            "INVALID_CREDENTIALS",
            status.HTTP_401_UNAUTHORIZED,
            "Invalid username or password",
            "The username or the password did not match.",
            "Check both and try again; repeated failures are recorded.",
            retryable=True,
            audited=True,
        ),
        _entry(
            # Found undocumented by `test_every_code_central_raises_is_documented` once
            # the scan was widened past `ApiError(` to the auth service's raiser helper.
            "ACCOUNT_DISABLED",
            status.HTTP_401_UNAUTHORIZED,
            "Account is disabled",
            "An Admin disabled this account, so it can no longer sign in.",
            "Ask an Admin to re-enable it.",
            audited=True,
        ),
        _entry(
            "TOKEN_EXPIRED",
            status.HTTP_401_UNAUTHORIZED,
            "Token has expired",
            "The access token's short lifetime elapsed.",
            "The browser refreshes automatically; sign in again if it cannot.",
            retryable=True,
        ),
        _entry(
            "TOKEN_INVALID",
            status.HTTP_401_UNAUTHORIZED,
            "Token is not valid",
            "The token was malformed, or was revoked by a sign-out or a role change.",
            "Sign in again.",
            audited=True,
        ),
        _entry(
            "FORBIDDEN",
            status.HTTP_403_FORBIDDEN,
            "You do not have permission for this action",
            # Deliberately uniform: the same message whether the role lacks the action
            # or the user does not own the resource, so a caller cannot use the
            # response to learn that a resource exists or who owns it (ADR 0016).
            "Your role does not allow this action, or the resource belongs to someone else.",
            "Ask an Admin if you need the permission.",
            audited=True,
        ),
        # --- Request shape ---
        _entry(
            "INVALID_ARGUMENT",
            status.HTTP_400_BAD_REQUEST,
            "Invalid argument",
            "A value in the request was not acceptable.",
            "Correct the value and resend.",
        ),
        _entry(
            "INVALID_QUERY",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The query is outside the permitted bounds",
            "A filter was unknown, a time range too wide, or a page size too large.",
            "Narrow the range or reduce the page size; the message names the limit.",
        ),
        _entry(
            "NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Not found",
            "The resource does not exist, or was removed.",
            "Reload the list.",
        ),
        _entry(
            "INTERNAL_ERROR",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An internal error occurred",
            # Also returned with **503** when a database connection could not be checked
            # out in time (P4-09). The code is deliberately the same: a distinct one
            # would tell an unauthenticated caller that the database is under pressure.
            "Something failed on the server, or it is briefly overloaded. The detail is "
            "in the server log only.",
            "Retry; if it persists, report the request id shown here.",
            retryable=True,
            origin=CENTRAL,
        ),
        _entry(
            "CANCELLED",
            None,
            "The request was cancelled",
            "The browser abandoned the request — a closed tab, or a superseded search.",
            "None: this is not a failure.",
        ),
        # --- Enrollment ---
        _entry(
            "ENROLLMENT_TOKEN_INVALID",
            status.HTTP_401_UNAUTHORIZED,
            "Enrollment token is not valid",
            "The token is unknown, expired, revoked, or already used up.",
            "Create a new enrollment token and re-run the installer.",
            audited=True,
            origin=DAEMON,
        ),
        # --- Node and relay ---
        _entry(
            # Central-origin: it is raised when a node id does not resolve here, not
            # reported by a daemon. Marked DAEMON at first, which the origin/enum
            # cross-check caught — a wrong origin would tell a reader the failure came
            # from the node when it never left Central.
            "NODE_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Node not found",
            "The node does not exist, or was removed.",
            "Reload the node list.",
        ),
        _entry(
            "NODE_OFFLINE",
            status.HTTP_409_CONFLICT,
            "Node is not connected",
            "The daemon has no live connection, so nothing can be relayed to it.",
            "Check the node: `systemctl status agentd` and `agentd doctor`.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "NODE_DISABLED",
            status.HTTP_409_CONFLICT,
            "Node is disabled",
            "An Admin disabled this node; it stays connected but refuses new operations.",
            "Re-enable it from the node detail page.",
            origin=DAEMON,
        ),
        _entry(
            "NODE_BUSY",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Too many in-flight requests for this node",
            "The node already has the maximum number of requests awaiting a reply.",
            "Wait and retry; if it persists the daemon may be wedged.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "NODE_AUTH_FAILED",
            status.HTTP_401_UNAUTHORIZED,
            "auth failed",
            "The daemon could not prove it holds the node's private key.",
            "Rotate the credential, or re-enroll the node.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "REQUEST_TIMEOUT",
            status.HTTP_504_GATEWAY_TIMEOUT,
            "Node did not respond in time",
            "The daemon did not answer within the timeout for this operation.",
            "Retry. For an update this is expected and not a failure — the daemon "
            "restarts and reports afterwards.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "QUEUE_OVERFLOW",
            None,
            "Terminal output outpaced this browser",
            "Output arrived faster than this browser could consume it, so the bounded "
            "queue overflowed and the connection was closed rather than growing.",
            "Reconnect; the terminal marks the gap instead of pretending it was continuous.",
            retryable=True,
            origin=DAEMON,
        ),
        # --- Protocol ---
        _entry(
            "INVALID_MESSAGE",
            status.HTTP_400_BAD_REQUEST,
            "The message is not valid",
            "A frame did not satisfy the v1 contract.",
            "Report it: a well-behaved client cannot produce this.",
            origin=DAEMON,
        ),
        _entry(
            "PROTOCOL_VERSION_UNSUPPORTED",
            status.HTTP_400_BAD_REQUEST,
            "Protocol version is not supported",
            "The peer speaks a protocol version this server does not.",
            "Update the daemon (or the server) so both speak v1.",
            origin=DAEMON,
        ),
        _entry(
            "MESSAGE_TYPE_UNSUPPORTED",
            status.HTTP_400_BAD_REQUEST,
            "The message type is not supported",
            "The frame's type is not in the allowlist for this direction.",
            "Update the daemon.",
            origin=DAEMON,
        ),
        _entry(
            "FRAME_TOO_LARGE",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "The frame exceeds the size limit",
            "A control frame was larger than its bound (64 KiB, or 8 MiB for a "
            "filesystem response).",
            "Narrow the request — fewer entries, or a smaller file.",
            origin=DAEMON,
        ),
        _entry(
            "INVALID_SESSION",
            status.HTTP_400_BAD_REQUEST,
            "The session reference is not valid",
            "A frame named a session that does not match the connection it arrived on.",
            "Reload the page.",
            origin=DAEMON,
        ),
        # --- Runtime ---
        _entry(
            "RUNTIME_NOT_ALLOWED",
            status.HTTP_400_BAD_REQUEST,
            "Runtime is not allowed",
            "The requested runtime is not in the closed allowlist (claude, codex, shell).",
            "Choose an allowlisted runtime.",
            origin=DAEMON,
        ),
        _entry(
            "RUNTIME_NOT_FOUND",
            status.HTTP_409_CONFLICT,
            "Runtime is not available on this node",
            "The CLI binary was not detected on the node.",
            "Install it on the node, then run `agentd runtime list` to confirm.",
            origin=DAEMON,
        ),
        _entry(
            "RUNTIME_DISABLED",
            status.HTTP_409_CONFLICT,
            "Runtime is disabled on this node",
            "The node's config has this runtime turned off.",
            "Enable it in `/etc/agentd/config.yaml` and restart the daemon.",
            origin=DAEMON,
        ),
        _entry(
            "RUNTIME_NOT_EXECUTABLE",
            status.HTTP_409_CONFLICT,
            "Runtime binary cannot be executed",
            "The configured binary exists but is not executable by the daemon's user.",
            "Fix its permissions, then `agentd doctor`.",
            origin=DAEMON,
        ),
        # --- Session and terminal ---
        _entry(
            "SESSION_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Session not found",
            "The session does not exist on Central, or no longer exists on the node.",
            "Reload the session list.",
            origin=DAEMON,
        ),
        _entry(
            "SESSION_ALREADY_EXISTS",
            status.HTTP_409_CONFLICT,
            "Session already exists",
            "A session with this id is already running on the node.",
            "Reload; the existing session is still usable.",
            origin=DAEMON,
        ),
        _entry(
            "SESSION_NOT_RUNNING",
            status.HTTP_409_CONFLICT,
            "Session is not running",
            "The session has already ended.",
            "Create a new session.",
            origin=DAEMON,
        ),
        _entry(
            "SESSION_INVALID_STATE",
            status.HTTP_409_CONFLICT,
            "Session has already ended",
            "The operation does not apply to a session in its current state.",
            "Reload to see the current state.",
            origin=DAEMON,
        ),
        _entry(
            "SESSION_LIMIT_REACHED",
            status.HTTP_409_CONFLICT,
            "The node has reached its session limit",
            "This node already runs the maximum number of concurrent sessions.",
            "End a session, or use another node.",
            origin=DAEMON,
        ),
        _entry(
            "SESSION_START_FAILED",
            status.HTTP_502_BAD_GATEWAY,
            "Runtime failed to start",
            # Fixed message on purpose: the daemon's reason may name a path or a
            # command line, and it goes to the log instead.
            "The node accepted the request but the CLI did not start.",
            "Check the node's log for this request id; verify the runtime with "
            "`agentd runtime list`.",
            retryable=True,
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "SHELL_ALREADY_OPEN",
            status.HTTP_409_CONFLICT,
            "This session already has a system terminal",
            "One live system terminal per CLI session (ADR 0021): the existing one is "
            "still open somewhere, or a previous tab did not close cleanly.",
            "Return to the tab holding it, or close it and open a new one. An "
            "abandoned terminal is also reaped by the idle timeout.",
            # Central-side: the parent is resolved here and the node never sees the
            # request, so no daemon origin.
        ),
        _entry(
            "INVALID_TERMINAL_SIZE",
            status.HTTP_400_BAD_REQUEST,
            "Terminal size is out of range",
            "The requested rows/columns are outside the accepted bounds.",
            "Resize the window and retry.",
            origin=DAEMON,
        ),
        _entry(
            "TERMINAL_ALREADY_CONTROLLED",
            status.HTTP_409_CONFLICT,
            "Terminal already has a writer",
            "Someone else holds the writer role for this terminal.",
            "Attach read-only, or take over if you have permission.",
            origin=DAEMON,
        ),
        # --- Workspace ---
        _entry(
            "WORKSPACE_OUTSIDE_ALLOWED_ROOT",
            status.HTTP_400_BAD_REQUEST,
            "Workspace is outside the allowed roots",
            "The path resolves outside every root the node permits.",
            "Choose a path inside an allowed root (`agentd workspace list`).",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "WORKSPACE_NOT_FOUND",
            status.HTTP_400_BAD_REQUEST,
            "Workspace not found",
            "The directory does not exist on the node.",
            "Create it, or pick another.",
            origin=DAEMON,
        ),
        _entry(
            "WORKSPACE_NOT_DIRECTORY",
            status.HTTP_400_BAD_REQUEST,
            "Not a directory",
            "The path exists but is not a directory.",
            "Choose a directory.",
            origin=DAEMON,
        ),
        _entry(
            "WORKSPACE_PERMISSION_DENIED",
            status.HTTP_403_FORBIDDEN,
            "Permission denied",
            "The daemon's user cannot read the directory.",
            "Grant the node's run user access, or choose another directory.",
            origin=DAEMON,
        ),
        _entry(
            "WORKSPACE_INVALID",
            status.HTTP_400_BAD_REQUEST,
            "Invalid path",
            "The path is not acceptable — not absolute, or malformed.",
            "Provide an absolute path inside an allowed root.",
            origin=DAEMON,
        ),
        # --- Files (read-only browse and preview) ---
        _entry(
            "FILE_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Cannot access path",
            # One message for missing, denied-by-policy and outside-root, so a caller
            # cannot use the response to probe what exists (ADR 0014).
            "The file does not exist, or is not accessible through this workspace.",
            "Refresh the tree.",
            origin=DAEMON,
        ),
        _entry(
            "FILE_INVALID_PATH",
            status.HTTP_400_BAD_REQUEST,
            "Invalid path",
            "The path is malformed or attempts to leave the workspace.",
            "Select the file from the tree instead of typing a path.",
            audited=True,
        ),
        _entry(
            "FILE_PERMISSION_DENIED",
            status.HTTP_403_FORBIDDEN,
            "Permission denied",
            "The daemon's user cannot read the file.",
            "Grant the node's run user access.",
            origin=DAEMON,
        ),
        _entry(
            "FILE_DENIED",
            None,
            "This file type cannot be previewed",
            "The file matches the node's sensitive-file policy, so it was never read.",
            "None: the content is deliberately not available through the browser.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "FILE_TOO_LARGE",
            None,
            "The file is too large to preview",
            "The file exceeds the preview cap (2 MiB by default).",
            "Open it on the node instead.",
            origin=DAEMON,
        ),
        _entry(
            "FILE_BINARY",
            None,
            "This file is not text",
            "The content is binary, so there is nothing useful to render.",
            "None.",
            origin=DAEMON,
        ),
        # --- Daemon update (P4-10) ---
        _entry(
            "UPDATE_NOT_ALLOWED",
            status.HTTP_409_CONFLICT,
            "That version is not an allowlisted release",
            "The version is not published for this architecture, it is a downgrade, "
            "or the daemon has no way to install it (it runs unprivileged by design).",
            "Run `sudo agentd update` on the node; see the update-failure runbook.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "UPDATE_DOWNLOAD_FAILED",
            status.HTTP_502_BAD_GATEWAY,
            "The release could not be downloaded",
            "The node could not reach the manifest or the artifact.",
            "Check the node's connectivity, then retry.",
            retryable=True,
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "UPDATE_CHECKSUM_MISMATCH",
            status.HTTP_502_BAD_GATEWAY,
            "The downloaded release does not match its published checksum",
            "The bytes served differ from the bytes published. Nothing was installed.",
            "Do not retry blindly — treat it as a security event and verify the "
            "artifacts directory (see the update-failure runbook).",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "UPDATE_HEALTHCHECK_FAILED",
            status.HTTP_502_BAD_GATEWAY,
            "The updated daemon did not become healthy",
            "The new version started but failed its own checks, so it was rolled back.",
            "The node is running the previous version. Capture `agentd doctor` output "
            "and report it.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "UPDATE_ROLLED_BACK",
            status.HTTP_502_BAD_GATEWAY,
            "The update was rolled back",
            "A stage after the swap failed, so the previous binary was restored.",
            "No outage. Diagnose from the stage in the audit trail.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "UPDATE_IN_PROGRESS",
            status.HTTP_409_CONFLICT,
            "An update is already running on this node",
            "One update at a time: two concurrent swaps of the same file would leave "
            "the second one's backup holding the first one's binary.",
            "Wait for the running update to report.",
            retryable=True,
            origin=DAEMON,
        ),
    ]
)


# --- Cross-language vocabulary -------------------------------------------- #

_CONTRACT_ENVELOPE = (
    Path(__file__).resolve().parents[3] / "contracts/v1/schemas/control-envelope.schema.json"
)


def protocol_error_codes() -> frozenset[str]:
    """The closed error enum from the v1 control envelope.

    Read from the schema rather than restated, so the catalog is checked against the
    contract itself instead of against a copy of it that could drift.
    """
    schema = json.loads(_CONTRACT_ENVELOPE.read_text(encoding="utf-8"))
    return frozenset(schema["properties"]["error"]["properties"]["code"]["enum"])


def entry(code: str) -> ErrorEntry | None:
    return CATALOG.get(code)


def safe_message(code: str, fallback: str = "The request could not be completed") -> str:
    """The message a client may be shown for a code.

    Used where a daemon error is mapped outward: the catalog's wording is returned and
    the daemon's own string is dropped, which is what keeps a node's paths and internal
    state out of an API response.
    """
    found = CATALOG.get(code)
    return found.message if found is not None and found.message else fallback
