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

## Port forwarding

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `SECRET_KEY_MISSING` | 503 | This deployment cannot store integration credentials | A provider credential can only be stored encrypted, and this deployment has no encryption key configured. Storing it in plain text is refused rather than done quietly, because plaintext already written cannot be un-disclosed. | Ask the deployment administrator to set CLIORA_SECRET_ENCRYPTION_KEY (openssl rand -base64 32), then enable the integration again. | no | no | central |
| `TUNNEL_INTEGRATION_DISABLED` | 404 | Port forwarding is not enabled for this deployment | The capability is switched off in the platform's integration settings, which is where an administrator supplies the provider account it would run on. | Ask an administrator to enable port forwarding in Integration settings and supply the provider credential. | no | no | central |
| `TUNNEL_NODE_DISABLED` | 409 | This node does not take part in port forwarding | Either the node is switched off for port forwarding in its platform settings, or the node's own configuration vetoes it. The two have different remedies, which is why the message names which one refused. | If it is the platform setting, turn it on from the node's port-forwarding page. If the node vetoed it locally, its owner has to change `tunnel.enabled` in /etc/agentd/config.yaml — the platform cannot override that. | no | no | central |
| `TUNNEL_PROVIDER_NOT_CONFIGURED` | 409 | This node cannot open a tunnel yet | The node is missing a prerequisite: the ssh client, outbound access to the provider, or the pinned provider host key. | Run `agentd doctor` on the node; it names which of the three is missing. | no | no | daemon |
| `TUNNEL_PROVIDER_UNAVAILABLE` | 502 | The tunnel provider could not be reached | The node could not establish its outbound connection to the tunnel provider. That is usually a network path problem rather than a platform fault. | Retry shortly. If it persists, confirm the node can reach the provider on port 443. | yes | no | daemon |
| `TUNNEL_PROVIDER_UNAUTHORIZED` | 502 | The tunnel provider rejected the stored credential | The provider did not accept the credential. It answers this by silently downgrading to an anonymous, time-limited tunnel, so the tunnel is torn down rather than handed over as if it were the one that was asked for. | Ask an administrator to update the provider credential in Integration settings. | no | yes | daemon |
| `TUNNEL_PROVIDER_UNTRUSTED` | 502 | The tunnel provider's host key did not match | The provider presented a host key that does not match the one pinned on the node, and the connection was stopped. This is what an intercepted outbound connection looks like; it is also what a legitimate key rotation looks like. | Contact an administrator. Do not disable host key checking to get past this. | no | yes | daemon |
| `TUNNEL_PORT_NOT_ALLOWED` | 409 | That port may not be forwarded | Ports below 1024 are never forwarded, and this node's allowed range may be narrower still. The narrowest of the platform, node and local settings wins. | Use a port at or above 1024 that is inside the range shown on the node's port-forwarding page. | no | no | daemon |
| `TUNNEL_LIMIT_REACHED` | 409 | The tunnel limit has been reached | One of three limits is full: the platform's concurrent budget, this node's cap, or your own. The message on screen says which. | Close a tunnel that is no longer needed, or ask an administrator to raise the budget to match the provider plan. | no | no | daemon |

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

## Project layer

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `PROJECT_NOT_FOUND` | 404 | Project not found | The project does not exist, or was archived and then removed from view. | Reload the project list. | no | no | central |
| `PROJECT_SLUG_TAKEN` | 409 | A project with this slug already exists | Slugs are unique across the platform, and fixed once the project exists. | Choose a different slug. The display name can still be whatever you like. | no | no | central |
| `PROJECT_SLUG_INVALID` | 422 | Slug must be lowercase letters, digits and hyphens | The supplied slug has an unusable character, or a name written entirely in non-Latin script left nothing to derive one from. | Supply a slug explicitly, for example `traqora-api`. | no | no | central |
| `PROJECT_STATUS_INVALID` | 422 | Unknown project status | A project is active, paused or archived; nothing else. | Use one of the three states. | no | no | central |
| `PROJECT_ARCHIVED` | 409 | This project is archived | An archived project accepts no new sessions and no new workspace bindings. Everything already running is untouched. | Un-archive the project first, or use a different one. | no | no | central |
| `PROJECT_WORKSPACE_NOT_FOUND` | 404 | Workspace binding not found | The binding was already removed, or belongs to another project. | Reload the project. | no | no | central |
| `SESSION_PROJECT_MISMATCH` | 400 | The workspace does not belong to this project | A session may name a project only when its workspace is one of that project's bindings. The match is exact, so a subdirectory of a bound path is not itself bound. | Pick a path from the project's bindings, bind this one first, or create the session without a project. | no | no | central |

## Task layer

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `TASK_NOT_FOUND` | 404 | Task not found | The card, epic, story or dependency does not exist in this project. | Reload the board. | no | no | central |
| `TASK_VERSION_CONFLICT` | 409 | This card was changed by someone else | Every write carries the version it was read at, so two people dragging one card cannot silently overwrite each other. The response carries the card's current version. | The board reloads the card; try the move again. | no | no | central |
| `TASK_DEPENDENCY_UNSATISFIED` | 409 | A blocking card is not finished | Entering `ready` or a later lane claims the card is workable, and an unfinished dependency contradicts that. `details.blocking_refs` names the cards. | Finish the named cards, or drop the dependency if it no longer holds. | no | no | central |
| `TASK_DEPENDENCY_CYCLE` | 409 | That would create a circular dependency | The blocking card already depends on this one, directly or through others. `details.path` shows the loop. | Remove one edge of the loop first. | no | no | central |
| `TASK_STAGE_INVALID` | 422 | Unknown value | A lane, risk, priority, source or delivery outside the process definition's vocabulary. | Read the project's process definition for the accepted values. | no | no | central |
| `TASK_ACCEPTANCE_CRITERIA_INVALID` | 422 | Acceptance criteria must be a list of objects | The task context renderer requires each criterion to be an object. | Send each criterion as an object with a text field. | no | no | central |
| `TASK_CONTEXT_TOO_LARGE` | 422 | Acceptance criteria do not fit the task context budget | Acceptance criteria are preserved in full in the 4 KB agent context pack, so their rendered form has a fixed upper bound. | Shorten or combine acceptance criteria; optional task description sections are omitted automatically. | no | no | central |
| `FORBIDDEN_FIELD` | 422 | That field cannot be set this way | Refused rather than ignored: a silently dropped field is a change the caller believes it made. Review gates in particular have their own endpoint and their own action. | Use the endpoint that owns the field. | no | no | central |
| `GATE_UNKNOWN` | 404 | Unknown review gate | The process definition has no gate by that key. | Read the project's process definition for the gate keys. | no | no | central |
| `GATE_DISABLED` | 409 | This gate is unavailable in this deployment | A gate may depend on an integration that is switched off — the mockup gate needs tunnel integration. It is disabled on read rather than left unsatisfiable, because a gate nobody can ever tick is a deadlock. | Enable the integration, or proceed without that gate. | no | no | central |
| `GATE_REQUIRES_HUMAN_ACTOR` | 403 | A review gate must be approved by a person | An agent's output is not an approval. A session credential cannot reach this endpoint at all; this code is the second line of defence. | Approve it yourself in the console. | no | no | central |

## Requirements and decomposition

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `REQUIREMENT_NOT_FOUND` | 404 | Requirement not found | The requirement does not exist in this project. | Reload the requirements list. | no | no | central |
| `REQUIREMENT_NOT_SPECIFIED` | 409 | Write a specification before approving | Approval is approval *of* something: a requirement with no specification version has nothing to approve. | Add a specification version first. | no | no | central |
| `SPEC_HAS_OPEN_QUESTIONS` | 409 | Unresolved questions remain | A specification cannot be approved while a question has neither an answer nor an explicit 'known unknown' marking. `details.questions` names them. | Answer them, or mark them as known unknowns, then approve. | no | no | central |
| `REQUIREMENT_ALREADY_APPROVED` | 409 | This requirement is approved | Specification versions are append-only up to approval; after it, a change of mind is a new requirement rather than a rewritten one. | Raise a new requirement. | no | no | central |
| `REQUIREMENT_NOT_APPROVED` | 409 | Approve the specification before decomposing it | Decomposing something nobody has agreed to produces work that will be thrown away. This is refused by the API rather than hidden in the UI, because V2.5 sends an agent down the same path. | Approve the specification first. | no | no | central |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal not found | The decomposition proposal does not exist. | Reload the requirement. | no | no | central |
| `PROPOSAL_ALREADY_DECIDED` | 409 | This proposal was already decided | Acceptance creates real cards, so it happens once. A second decision would duplicate them. | Create a new proposal if the plan changed. | no | no | central |

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

## File upload

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `FILE_UPLOAD_TOO_LARGE` | — | The image is larger than 4 MiB | Central refuses the request before reading the whole body, and the daemon refuses it again before writing anything. | Compress or resize the image and try again. | no | no | central |
| `FILE_UPLOAD_UNSUPPORTED_TYPE` | — | Only PNG, JPEG, GIF and WebP images can be dropped | The content did not match one of the four accepted image signatures. The declared content type is not what decides this. | Convert the file to a supported image format. SVG and PDF are not images here. | no | no | daemon |
| `FILE_UPLOAD_QUOTA_EXCEEDED` | — | This session has reached its image quota | Either the cumulative byte quota or the per-day file count for this workspace is full. | Remove images you no longer need from .cliora/uploads/ on the node (a terminal session is the way to do that); expired ones are removed automatically after 7 days. | no | yes | daemon |
| `FILE_UPLOAD_FAILED` | — | The node could not store the image | Writing to the workspace failed — no disk space, no permission, or .cliora exists but is not a directory. | Ask an administrator to check the node; `agentd doctor` names the file to fix. | yes | no | daemon |
| `FILE_UPLOAD_DISABLED` | — | This node does not accept image drop | The node's config sets filesystem.upload.enabled to false. Whether a workspace may be written to is the node's decision, not the platform's. | None from the browser; the node's owner controls this setting. | no | no | daemon |
| `FILE_EXISTS` | — | A file or directory with that name already exists | Upload never replaces anything: the node creates the file with O_EXCL, so a name that is already taken is refused and not one existing byte is touched. That property is why this path needs no version token and has no undo. | Upload it under a different name, or replace the file from a terminal session if replacing is what you meant. | no | no | daemon |
| `FILE_UPLOAD_NO_SPACE` | — | The node does not have enough free disk space | The workspace filesystem is below the node's configured free-space floor, or the file would not leave twice its own size free. This check is what stands in for a retention period on this path: uploaded files belong to the user, so nothing expires them. | Free space on the node, or ask an administrator to; `agentd doctor` reports the figure it is comparing against. | yes | no | daemon |
| `FILE_INVALID_NAME` | — | That filename cannot be used | A filename must be a single path segment: no separator, no control characters, at most 255 bytes. Checked after URL decoding, because percent-encoding can otherwise smuggle a separator through. | Rename the file and try again. | no | no | central |

## Daemon update

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `UPDATE_NOT_ALLOWED` | 409 | That version is not an allowlisted release | The version is not published for this architecture, it is a downgrade, or the daemon has no way to install it (it runs unprivileged by design). | Run `sudo agentd update` on the node; see the update-failure runbook. | no | yes | daemon |
| `UPDATE_DOWNLOAD_FAILED` | 502 | The release could not be downloaded | The node could not reach the manifest or the artifact. | Check the node's connectivity, then retry. | yes | yes | daemon |
| `UPDATE_CHECKSUM_MISMATCH` | 502 | The downloaded release does not match its published checksum | The bytes served differ from the bytes published. Nothing was installed. | Do not retry blindly — treat it as a security event and verify the artifacts directory (see the update-failure runbook). | no | yes | daemon |
| `UPDATE_HEALTHCHECK_FAILED` | 502 | The updated daemon did not become healthy | The new version started but failed its own checks, so it was rolled back. | The node is running the previous version. Capture `agentd doctor` output and report it. | no | yes | daemon |
| `UPDATE_ROLLED_BACK` | 502 | The update was rolled back | A stage after the swap failed, so the previous binary was restored. | No outage. Diagnose from the stage in the audit trail. | no | yes | daemon |
| `UPDATE_IN_PROGRESS` | 409 | An update is already running on this node | One update at a time: two concurrent swaps of the same file would leave the second one's backup holding the first one's binary. | Wait for the running update to report. | yes | no | daemon |

## Agent runner

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `TASK_NOT_READY` | 409 | Only a card in the ready lane can be dispatched to an agent | The card is in another lane. Dispatch is an execution action, and a card that is not ready has not been agreed to be worked on yet. | Move the card to Ready first. | no | no | central |
| `RUN_ALREADY_ACTIVE` | 409 | This card already has a run in progress | A card has at most one run in flight; a second would mean two agents changing the same work with no way to reconcile them. | Wait for the run to finish, or cancel it first. | no | no | central |
| `RUN_NOT_ACTIVE` | 409 | This run has already finished | Cancel only applies to a run that is queued or running. | Look at the run's result; if it needs doing again, dispatch the card again. | no | no | central |
| `TASK_REQUIRES_SECRETS` | 409 | Cards that declare required secrets can be dispatched from V2.3 | The card names secrets it needs, and this version manages no secrets at all. Accepting the dispatch would run the card **without** them, which looks like a broken agent rather than a missing feature. | Remove the declaration to run without them, or wait for V2.3. | no | no | central |
| `TASK_DELIVERY_UNSUPPORTED` | 409 | That delivery mode takes effect in a later version | This version delivers by attaching artifacts to the card. Branches and pull requests arrive with the platform's own git write path. | Set delivery to none or artifact for now; the response names the version the declared mode starts working in. | no | no | central |
| `PROJECT_NO_REPOSITORY` | 409 | This project has no repository registered | An agent fetches the code itself, so the platform has to know where the code is. Nothing on the card can supply that — it is project settings. | Register the repository in the project's settings, then dispatch again. The response carries a link to the right page. | no | no | central |
| `REPOSITORY_HOST_NOT_ALLOWED` | 400 | This deployment does not allow repositories on that host | Two allowlists apply: the deployment's and each node's. This is the deployment's, and it is empty until an administrator sets it. | Ask an administrator to add the host to CLIORA_GIT_ALLOWED_HOSTS. | no | no | central |
| `REPOSITORY_EXISTS` | 409 | That repository is already registered for this project | A project may list several repositories, but not the same one twice. | Use the existing entry, or remove it first if the branch needs changing. | no | no | central |
| `AGENT_DISABLED` | 409 | That agent is disabled | The card named a specific agent, and it is switched off. This is refused at dispatch rather than queued, because a disabled agent is a decision somebody made rather than a machine that will come back. | Enable the agent, or dispatch without naming one. | no | no | central |
| `AGENT_RUNTIME_MISMATCH` | 409 | That agent does not offer the runtime this card needs | The named node reported no usable non-interactive interface for the runtime required — often because that CLI is installed but too old. | Pick another agent, or update the CLI on that node and let it re-register. | no | no | central |
| `AGENT_RUNS_DISABLED` | 409 | Agent runs are switched off in this deployment | A daemon tried to register as a runner while `CLIORA_AGENT_RUNS_ENABLED` is false. The node keeps serving interactive sessions. | Enable the flag on Central if unattended execution is wanted here. | no | no | daemon |
| `RUNNER_NOT_REGISTERED` | 409 | That node has not registered as a runner | A poll arrived before registration — usually a daemon that reconnected and has not yet re-announced itself. | None; the daemon registers on its next connection and resumes polling. | yes | no | daemon |
| `RUNNER_DISABLED` | 409 | That agent is switched off | An administrator disabled it, so it is refused work even though its node is online. | Enable it on the Agents page. | no | no | daemon |
| `RUN_NOT_FOUND` | 404 | Run not found | The run id is unknown here — usually a late or duplicated frame from a node about a run that has already been reclaimed. | None; this is normal after a lease expires. | no | no | daemon |
| `RUN_INVALID_STATE` | 409 | That run has already finished | A lease renewal or progress report arrived for a run in a terminal state. | None; the node stops reporting once it sees the run is gone. | no | no | daemon |
| `RUN_SOURCE_UNAVAILABLE` | 409 | The agent could not fetch the code | One of three things: the machine has no credential for that repository, the host is not on that node's allowlist, or the ref does not exist. The details say which — **and never echo the URL**, because somebody may have pasted a credential into it. | Check the details: supply the credential on that machine, add the host to the node's allowlist, or correct the branch on the card. | no | no | daemon |
| `RUN_DISK_QUOTA` | 409 | The agent ran out of its disk allowance | A run directory or the node's total exceeded its quota. Quotas exist because a runaway build would otherwise fill the disk and take interactive sessions down with it. | Wait for the cleanup loop, or raise `runner.run_quota_bytes` on that node if the work genuinely needs more. | no | no | daemon |
| `RUN_IDLE_TIMEOUT` | 409 | The agent stopped producing events | Liveness is judged from the runtime's event stream, not from a wall clock. No event arrived within the idle limit, so the run was stopped. | Look at the last entries in the run log; if the work legitimately goes quiet for longer, raise `runner.idle_timeout_seconds`. | no | no | daemon |
| `RUN_TIMEOUT` | 409 | The run hit its wall-clock limit | The backstop, not the liveness test: the run was still emitting events and simply did not finish in time. | Split the card, or raise the run timeout for this deployment. | no | no | daemon |
| `RUN_RUNTIME_UNAVAILABLE` | 409 | The runtime is not usable on that node | The CLI is missing, not executable, or too old to expose a non-interactive interface with an event stream. | Install or update the CLI on that machine and let the daemon re-register. | no | no | daemon |
| `RUN_CANCELLED` | 409 | The run was cancelled | Somebody pressed cancel, or the node was shutting down. | Dispatch the card again when you are ready. | no | no | daemon |
| `RUN_INTERNAL_ERROR` | 500 | The agent run failed for an internal reason | Something went wrong inside the daemon's run path. The detail is in that node's log with the request id. | Retry; if it persists, collect the daemon log around that run id. | yes | no | daemon |

## Card artifacts

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `ARTIFACT_TOO_LARGE` | 413 | That file is larger than the per-file limit | One artifact may not exceed the deployment's single-file limit. | Split it, compress it, or attach a summary and keep the full output elsewhere. | no | no | central |
| `ARTIFACT_RUN_LIMIT` | 413 | This run has attached as many artifacts as it may | A single run has a cap on how many files it can attach, so one loop cannot fill a project's quota by itself. | Attach one combined file instead of many. | no | no | central |
| `ARTIFACT_PROJECT_QUOTA` | 413 | This project's artifact quota is full | Artifacts follow the card and are never deleted on a timer, so a project accumulates them until somebody decides which to remove. | Delete artifacts that are no longer needed — deletion frees the bytes even though the record of the deletion stays. | no | no | central |
| `ARTIFACT_DIGEST_MISMATCH` | 400 | The upload did not match its stated digest | Not tamper protection — the connection is already TLS. It catches a **truncated** upload, which should fail rather than become a broken artifact nobody can open. | Retry the upload. | yes | no | central |
| `ARTIFACT_DELETED` | 410 | That artifact was deleted | Its bytes are gone; the record of who deleted it and why is deliberately still there. | The card shows the reason next to the entry. | no | no | central |
| `RUN_TOKEN_TTL_EXCEEDED` | 409 | This run would need a credential that outlives the platform's limit | A run credential may not live longer than the deployment's ceiling on agent credentials. That started to bite when the run wall clock grew to six hours, so it is refused here rather than issued and expiring mid-run. | Lower the run timeout, or raise CLIORA_RUN_TOKEN_TTL_HOURS. | no | no | central |

Coverage is asserted by `backend/tests/test_error_catalog.py`: every code Central raises must appear here, every entry here must be raised by Central or present in the protocol's error enum, and every code must be listed in exactly one section above.
