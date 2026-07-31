<!-- GENERATED FILE — do not edit.
     Source: backend/app/api/error_catalog.py
     Regenerate: uv run --project backend python ../scripts/p4/render_error_catalog.py --write
-->

# Error catalog

Every stable error code a client can receive, the safe message it carries, and what to
do about it. The `code` is the contract; the message is wording and may improve.

Two rules this table encodes:

- **Daemon internal errors never reach a client.** A daemon error frame is mapped to a
  code below and answered with *this* message. The daemon's own string — which can
  contain an absolute path, a command line or internal state — goes to the server log
  with the request id (ADR 0014).
- **Retry is only offered where it can work.** Offering it on a permanent failure
  teaches users to ignore it, so `Retryable` is part of the contract rather than a UI
  choice.

`Audited` marks the refusals that also write a security event
(`docs/permission-matrix.md`, ADR 0016). Ordinary read 403s and validation errors are
deliberately not audited: at their volume they would bury the signal.

`Origin` is `daemon` for codes that can arrive from a node — those are also in the
closed enum in `contracts/v1/schemas/control-envelope.schema.json`.


## Authentication and authorization

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `UNAUTHENTICATED` | 401 | Missing bearer token | The request carried no valid access token, or the session expired. | Sign in again. | yes | no | central |
| `INVALID_CREDENTIALS` | 401 | Invalid username or password | The username or the password did not match. | Check both and try again; repeated failures are recorded. | yes | yes | central |
| `ACCOUNT_DISABLED` | 401 | Account is disabled | An Admin disabled this account, so it can no longer sign in. | Ask an Admin to re-enable it. | no | yes | central |
| `TOKEN_EXPIRED` | 401 | Token has expired | The access token's short lifetime elapsed. | The browser refreshes automatically; sign in again if it cannot. | yes | no | central |
| `TOKEN_INVALID` | 401 | Token is not valid | The token was malformed, or was revoked by a sign-out or a role change. | Sign in again. | no | yes | central |
| `FORBIDDEN` | 403 | You do not have permission for this action | Your role does not allow this action, or the resource belongs to someone else. | Ask an Admin if you need the permission. | no | yes | central |

## Request shape

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `INVALID_ARGUMENT` | 400 | Invalid argument | A value in the request was not acceptable. | Correct the value and resend. | no | no | central |
| `INVALID_QUERY` | 422 | The query is outside the permitted bounds | A filter was unknown, a time range too wide, or a page size too large. | Narrow the range or reduce the page size; the message names the limit. | no | no | central |
| `NOT_FOUND` | 404 | Not found | The resource does not exist, or was removed. | Reload the list. | no | no | central |
| `INTERNAL_ERROR` | 500 | An internal error occurred | Something failed on the server, or it is briefly overloaded. The detail is in the server log only. | Retry; if it persists, report the request id shown here. | yes | no | central |
| `CANCELLED` | — | The request was cancelled | The browser abandoned the request — a closed tab, or a superseded search. | None: this is not a failure. | no | no | central |

## Enrollment

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `ENROLLMENT_TOKEN_INVALID` | 401 | Enrollment token is not valid | The token is unknown, expired, revoked, or already used up. | Create a new enrollment token and re-run the installer. | no | yes | daemon |

## Node and relay

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `NODE_NOT_FOUND` | 404 | Node not found | The node does not exist, or was removed. | Reload the node list. | no | no | central |
| `NODE_OFFLINE` | 409 | Node is not connected | The daemon has no live connection, so nothing can be relayed to it. | Check the node: `systemctl status agentd` and `agentd doctor`. | yes | no | daemon |
| `NODE_DISABLED` | 409 | Node is disabled | An Admin disabled this node; it stays connected but refuses new operations. | Re-enable it from the node detail page. | no | no | daemon |
| `NODE_BUSY` | 503 | Too many in-flight requests for this node | The node already has the maximum number of requests awaiting a reply. | Wait and retry; if it persists the daemon may be wedged. | yes | no | daemon |
| `NODE_AUTH_FAILED` | 401 | auth failed | The daemon could not prove it holds the node's private key. | Rotate the credential, or re-enroll the node. | no | yes | daemon |
| `REQUEST_TIMEOUT` | 504 | Node did not respond in time | The daemon did not answer within the timeout for this operation. | Retry. For an update this is expected and not a failure — the daemon restarts and reports afterwards. | yes | no | daemon |
| `QUEUE_OVERFLOW` | — | Terminal output outpaced this browser | Output arrived faster than this browser could consume it, so the bounded queue overflowed and the connection was closed rather than growing. | Reconnect; the terminal marks the gap instead of pretending it was continuous. | yes | no | daemon |

## Protocol

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `INVALID_MESSAGE` | 400 | The message is not valid | A frame did not satisfy the v1 contract. | Report it: a well-behaved client cannot produce this. | no | no | daemon |
| `PROTOCOL_VERSION_UNSUPPORTED` | 400 | Protocol version is not supported | The peer speaks a protocol version this server does not. | Update the daemon (or the server) so both speak v1. | no | no | daemon |
| `MESSAGE_TYPE_UNSUPPORTED` | 400 | The message type is not supported | The frame's type is not in the allowlist for this direction. | Update the daemon. | no | no | daemon |
| `FRAME_TOO_LARGE` | 413 | The frame exceeds the size limit | A control frame was larger than its bound (64 KiB, or 8 MiB for a filesystem response). | Narrow the request — fewer entries, or a smaller file. | no | no | daemon |
| `INVALID_SESSION` | 400 | The session reference is not valid | A frame named a session that does not match the connection it arrived on. | Reload the page. | no | no | daemon |

## Runtime

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `RUNTIME_NOT_ALLOWED` | 400 | Runtime is not allowed | The requested runtime is not in the closed allowlist (claude, codex, shell). | Choose an allowlisted runtime. | no | no | daemon |
| `RUNTIME_NOT_FOUND` | 409 | Runtime is not available on this node | The CLI binary was not detected on the node. | Install it on the node, then run `agentd runtime list` to confirm. | no | no | daemon |
| `RUNTIME_DISABLED` | 409 | Runtime is disabled on this node | The node's config has this runtime turned off. | Enable it in `/etc/agentd/config.yaml` and restart the daemon. | no | no | daemon |
| `RUNTIME_NOT_EXECUTABLE` | 409 | Runtime binary cannot be executed | The configured binary exists but is not executable by the daemon's user. | Fix its permissions, then `agentd doctor`. | no | no | daemon |

## Session and terminal

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `SESSION_NOT_FOUND` | 404 | Session not found | The session does not exist on Central, or no longer exists on the node. | Reload the session list. | no | no | daemon |
| `SESSION_ALREADY_EXISTS` | 409 | Session already exists | A session with this id is already running on the node. | Reload; the existing session is still usable. | no | no | daemon |
| `SESSION_NOT_RUNNING` | 409 | Session is not running | The session has already ended. | Create a new session. | no | no | daemon |
| `SESSION_INVALID_STATE` | 409 | Session has already ended | The operation does not apply to a session in its current state. | Reload to see the current state. | no | no | daemon |
| `SESSION_LIMIT_REACHED` | 409 | The node has reached its session limit | This node already runs the maximum number of concurrent sessions. | End a session, or use another node. | no | no | daemon |
| `SESSION_START_FAILED` | 502 | Runtime failed to start | The node accepted the request but the CLI did not start. | Check the node's log for this request id; verify the runtime with `agentd runtime list`. | yes | yes | daemon |
| `SHELL_ALREADY_OPEN` | 409 | This session already has a system terminal | One live system terminal per CLI session (ADR 0021), and another tab or window is attached to the existing one right now. | Return to the tab holding it, or close it there. A terminal nobody is attached to is not a refusal: the next open replaces it. | no | no | central |
| `INVALID_TERMINAL_SIZE` | 400 | Terminal size is out of range | The requested rows/columns are outside the accepted bounds. | Resize the window and retry. | no | no | daemon |
| `TERMINAL_ALREADY_CONTROLLED` | 409 | Terminal already has a writer | Someone else holds the writer role for this terminal. | Attach read-only, or take over if you have permission. | no | no | daemon |

## Workspace

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `WORKSPACE_OUTSIDE_ALLOWED_ROOT` | 400 | Workspace is outside the allowed roots | The path resolves outside every root the node permits. | Choose a path inside an allowed root (`agentd workspace list`). | no | yes | daemon |
| `WORKSPACE_NOT_FOUND` | 400 | Workspace not found | The directory does not exist on the node. | Create it, or pick another. | no | no | daemon |
| `WORKSPACE_NOT_DIRECTORY` | 400 | Not a directory | The path exists but is not a directory. | Choose a directory. | no | no | daemon |
| `WORKSPACE_PERMISSION_DENIED` | 403 | Permission denied | The daemon's user cannot read the directory. | Grant the node's run user access, or choose another directory. | no | no | daemon |
| `WORKSPACE_INVALID` | 400 | Invalid path | The path is not acceptable — not absolute, or malformed. | Provide an absolute path inside an allowed root. | no | no | daemon |

## Files

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `FILE_NOT_FOUND` | 404 | Cannot access path | The file does not exist, or is not accessible through this workspace. | Refresh the tree. | no | no | daemon |
| `FILE_INVALID_PATH` | 400 | Invalid path | The path is malformed or attempts to leave the workspace. | Select the file from the tree instead of typing a path. | no | yes | central |
| `FILE_PERMISSION_DENIED` | 403 | Permission denied | The daemon's user cannot read the file. | Grant the node's run user access. | no | no | daemon |
| `FILE_DENIED` | — | This file type cannot be previewed | The file matches the node's sensitive-file policy, so it was never read. | None: the content is deliberately not available through the browser. | no | yes | daemon |
| `FILE_TOO_LARGE` | — | The file is too large to preview | The file exceeds the preview cap (2 MiB by default). | Open it on the node instead. | no | no | daemon |
| `FILE_BINARY` | — | This file is not text | The content is binary, so there is nothing useful to render. | None. | no | no | daemon |

## Daemon update

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `UPDATE_NOT_ALLOWED` | 409 | That version is not an allowlisted release | The version is not published for this architecture, it is a downgrade, or the daemon has no way to install it (it runs unprivileged by design). | Run `sudo agentd update` on the node; see the update-failure runbook. | no | yes | daemon |
| `UPDATE_DOWNLOAD_FAILED` | 502 | The release could not be downloaded | The node could not reach the manifest or the artifact. | Check the node's connectivity, then retry. | yes | yes | daemon |
| `UPDATE_CHECKSUM_MISMATCH` | 502 | The downloaded release does not match its published checksum | The bytes served differ from the bytes published. Nothing was installed. | Do not retry blindly — treat it as a security event and verify the artifacts directory (see the update-failure runbook). | no | yes | daemon |
| `UPDATE_HEALTHCHECK_FAILED` | 502 | The updated daemon did not become healthy | The new version started but failed its own checks, so it was rolled back. | The node is running the previous version. Capture `agentd doctor` output and report it. | no | yes | daemon |
| `UPDATE_ROLLED_BACK` | 502 | The update was rolled back | A stage after the swap failed, so the previous binary was restored. | No outage. Diagnose from the stage in the audit trail. | no | yes | daemon |
| `UPDATE_IN_PROGRESS` | 409 | An update is already running on this node | One update at a time: two concurrent swaps of the same file would leave the second one's backup holding the first one's binary. | Wait for the running update to report. | yes | no | daemon |

Coverage is asserted by `backend/tests/test_error_catalog.py`: every code Central raises must appear here, every entry here must be raised by Central or present in the protocol's error enum, and every code must be listed in exactly one section above.
