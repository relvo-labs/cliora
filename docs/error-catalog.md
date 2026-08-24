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
| `RANK_NEIGHBOR_STALE` | 409 | The cards you dropped between are no longer next to each other | A move names the two cards it lands between, not an index — on a filtered board an index does not mean what the server would take it to mean. This says the pair no longer describes a gap: one was deleted or moved, or somebody else reordered. `details` carries the neighbours' current ranks, so the board can re-render without a second request. | The board reloads and the card stays where it was; try the move again. | no | no | central |
| `FILTER_FIELD_NOT_ALLOWED` | 400 | That field cannot be filtered or sorted on | The filter language is an allowlist rather than a query language: fifteen fields and eight operators, each pair with one compilation path. `details.field` names the field and `details.allowed_fields` lists what is available. | Use one of the listed fields. | no | no | central |
| `FILTER_OP_NOT_ALLOWED` | 400 | That operator is not available on that field | Operators are per field — `contains` belongs only to the label array, and `gt`/`lt` only to timestamps. `details.allowed_ops` lists the ones this field accepts, because what the reader has to do is pick a different operator rather than go and read the documentation. | Use one of the operators in `details.allowed_ops`. | no | no | central |
| `FILTER_TOO_COMPLEX` | 400 | The filter is past one of its limits | Depth of 3, twenty leaf conditions, and fifty values in a list. `details.limit` says which one, with the actual and the maximum — a filter that is refused without naming the limit cannot be fixed except by guessing. | Simplify the filter; `details.limit` names which bound was crossed. | no | no | central |
| `VIEW_NAME_CONFLICT` | 409 | A view with that name already exists here | Names are unique per owner — per project for a shared view, per person for a personal one. A deleted view's name becomes free again, because the index behind this is partial. | Choose another name, or reuse the existing view. | no | no | central |
| `VIEW_NOT_OWNED` | 403 | That personal view belongs to somebody else | **403 rather than 404**, deliberately: somebody else's personal view is already absent from the listing, so saying it is not yours discloses nothing a caller could not infer — and it lets a client tell it apart from a view that was deleted. | Duplicate it into a personal view of your own instead. | no | no | central |
| `BULK_LIMIT_EXCEEDED` | 400 | Too many cards in one bulk update | Each card goes through the same write path a single card does — the Done Gate, the dependency check, the audit and activity trails and the knowledge outbox — so a batch is a hundred of those in one transaction, not one statement. `details.limit` and `details.received` give both numbers. | Split the selection into batches of at most the stated limit. | no | no | central |
| `TASK_DEPENDENCY_UNSATISFIED` | 409 | A blocking card is not finished | Entering `ready` or a later lane claims the card is workable, and an unfinished dependency contradicts that. `details.blocking_refs` names the cards. | Finish the named cards, or drop the dependency if it no longer holds. | no | no | central |
| `TASK_DEPENDENCY_CYCLE` | 409 | That would create a circular dependency | The blocking card already depends on this one, directly or through others. `details.path` shows the loop. | Remove one edge of the loop first. | no | no | central |
| `TASK_STAGE_INVALID` | 422 | Unknown value | A lane, risk, priority, source or delivery outside the process definition's vocabulary. | Read the project's process definition for the accepted values. | no | no | central |
| `TASK_ACCEPTANCE_CRITERIA_INVALID` | 422 | Acceptance criteria must be a list of objects | The task context renderer requires each criterion to be an object, and from V2.4 its result must be one of four values. `details.allowed` names them. | Send each criterion as an object with a text field, and a result of passed, failed, partial or not_verified. | no | no | central |
| `TASK_CONTEXT_TOO_LARGE` | 422 | Acceptance criteria do not fit the task context budget | Acceptance criteria are preserved in full in the 4 KB agent context pack, so their rendered form has a fixed upper bound. | Shorten or combine acceptance criteria; optional task description sections are omitted automatically. | no | no | central |
| `FORBIDDEN_FIELD` | 422 | That field cannot be set this way | Refused rather than ignored: a silently dropped field is a change the caller believes it made. Review gates in particular have their own endpoint and their own action. | Use the endpoint that owns the field. | no | no | central |
| `GATE_UNKNOWN` | 404 | Unknown review gate | The process definition has no gate by that key. | Read the project's process definition for the gate keys. | no | no | central |
| `GATE_DISABLED` | 409 | This gate is unavailable in this deployment | A gate may depend on an integration that is switched off — the mockup gate needs tunnel integration. It is disabled on read rather than left unsatisfiable, because a gate nobody can ever tick is a deadlock. | Enable the integration, or proceed without that gate. | no | no | central |
| `GATE_REQUIRES_HUMAN_ACTOR` | 403 | A review gate must be approved by a person | An agent's output is not an approval. A session credential cannot reach this endpoint at all; this code is the second line of defence. | Approve it yourself in the console. | no | no | central |
| `TASK_DONE_GATE_UNMET` | 409 | This card is missing some of its completion evidence | Entering `done` claims the work is finished, and the platform holds the facts that support that claim. `details.missing` names **every** unmet item, not the first one — the action for a missing summary and a missing report are different. | Supply the named items. An administrator may force the move with a reason, which stays visible on the card. | no | no | central |
| `TASK_FORCE_REASON_REQUIRED` | 400 | Forcing a card into done requires a reason | The reason is stored on the card and on the timeline, and it is what makes the exit visible rather than silent. | Send force_reason with the patch. | no | no | central |
| `PROCESS_OVERRIDE_UNKNOWN_KEY` | 422 | That process item does not exist | A project may disable existing readiness items and gates, never add one. An unrecognised key is refused rather than stored, because a stored one is silently ineffective and the person who typed it believes it worked. `details.unknown` names them. | Check the key against the project's process definition. | no | no | central |
| `TASK_DELIVERY_NEEDS_SOURCE` | 409 | A pull request needs code to deliver | The card asks to deliver as a pull request while declaring that it fetches no code. The two are separate fields on purpose, and this combination has nothing to open a pull request on. | Set source to repo, or deliver as none or artifact. | no | no | central |
| `TASK_PR_TARGET_MISSING` | 409 | A pull request needs a target branch | Refused at dispatch rather than at delivery, where the run would already have spent its work. | Set the card's target branch. | no | no | central |
| `TASK_EXISTING_PR_OUT_OF_NAMESPACE` | 409 | That branch is outside the platform's namespace | The platform pushes only inside `cliora/`, so continuing an existing pull request works for the ones it opened itself and no others. **This reads as a defect and is a boundary**: the constraint is compiled into the daemon and is what makes 'where can the platform push' answerable without looking at data. | Deliver as a branch and merge it yourself, or continue a pull request the platform opened. | no | no | central |
| `TASK_PROVIDER_UNSUPPORTED` | 409 | This deployment has no pull-request integration for that host | Refused at dispatch rather than after the work: a half-built provider that fails at delivery costs a whole run. | Deliver as a branch, or use a repository on a supported host. | no | no | central |
| `VERIFICATION_COMMANDS_INVALID` | 422 | A verification command is not in the expected shape | Commands are argv arrays rather than shell strings, so pipelines and `&&` do not apply — split them into separate commands. The encoded length is measured **when the command is saved** rather than when a run is offered, because a command that stores fine and silently never ships would make 'this project's verification never ran' a fact nobody goes looking for. | Shorten the name or the arguments, or split the command in two. | no | no | central |
| `PLAN_STEPS_INVALID` | 422 | A plan step is not in the expected shape | Each step is an object whose status is one of five values. `details.allowed` names them. | Send each step as an object with a title and one of the five statuses. | no | no | central |
| `PLAN_NOTE_REQUIRED` | 400 | Revising a plan requires a note | Why the plan changed is the reason a version row exists rather than a mutable column, so the second version onward must carry one. | Send a note describing what changed and why. | no | no | central |
| `PLAN_SEQ_CONFLICT` | 409 | Another writer recorded a plan at the same time | Two submissions took the same version number. The server retries once by itself; a second collision means something is writing faster than this table is for. | Retry the submission. | yes | no | central |
| `VERIFICATION_REPORT_INVALID` | 422 | The verification report is not in the expected shape | `details.field` names the field. A `source` in the payload is **not** an error — it is accepted, discarded, and recorded as discarded, because the credibility level is decided by the write path. | Correct the named field. The result is one of five values. | no | no | central |
| `EVIDENCE_KIND_INVALID` | 422 | Unknown evidence kind | The kind decides the credibility level, so it comes from a closed set. `details.allowed` names it. | Use one of the listed kinds. | no | no | central |
| `EVIDENCE_KIND_NOT_WRITABLE` | 403 | That kind of evidence is written by the platform, not by an agent | The kind decides the source, so an agent writing a machine-fact kind is **refused rather than downgraded** — a downgraded row would still assert something nobody observed. | Record it as a finding, a limitation or a risk. | no | no | central |
| `EVIDENCE_PAYLOAD_TOO_LARGE` | 413 | That piece of evidence is too large | Evidence is a structured fact somebody scans, not a file store. Artifacts already have a quota, a retention period and a download path. | Attach it to the card as an artifact instead. | no | no | central |
| `EVIDENCE_RUN_LIMIT` | 413 | This run has recorded as much evidence as it may | A per-run ceiling, so one run cannot fill the card's evidence list. | Summarise, or attach the detail as an artifact. | no | no | central |

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
| `TASK_KIND_FORBIDS_SECRETS` | 409 | A clarification or decomposition card carries no secrets | Neither kind needs a credential to read code and ask questions, so the declaration is refused at dispatch rather than honoured. Refused *before* the allowlist check on purpose: the fix is to clear the field, not to widen the project's allowlist. | Clear the card's required secrets. | no | no | central |
| `TASK_KIND_DELIVERY_NOT_ALLOWED` | 409 | This kind of card can only deliver nothing or an artifact | Clarification, decomposition and mockup cards produce no code change, so a branch or pull request would fail at delivery having spent a whole run. | Set the card's delivery to `none` or `artifact`. | no | no | central |
| `TASK_KIND_NEEDS_REQUIREMENT` | 409 | This card is not linked to a requirement | A clarification or decomposition run works *on* a requirement; without one there is nothing for it to read or to write back to. | Dispatch it from the requirement's page, or set the card's requirement. | no | no | central |
| `TASK_MOCKUP_INTEGRATION_DISABLED` | 409 | This deployment has no tunnel integration, so it does not do mockups | The mockup gate does not exist without a way to show a running preview (ADR 0022, D31). **Ordinary UI cards are unaffected** and so is attaching a screenshot as an artifact — what is missing is the governance gate. | Enable the tunnel integration, or make this an ordinary implementation card. | no | no | central |
| `TASK_KIND_LOCKED` | 409 | This card has been run, so its kind is fixed | Its specification versions, question thread and run log are explained by the kind it had; changing the kind afterwards would leave an implementation card that inexplicably produced a specification. | Create a new card of the kind you want. | no | no | central |
| `TASK_KIND_MISMATCH` | 409 | This route serves a different kind of card | `/spec` serves clarification cards and `/proposal` serves decomposition cards. The card's kind decides which writes it may make. | Use the route matching this card's kind. | no | no | central |
| `QUESTION_ALREADY_PENDING` | 409 | The previous question has not been answered yet | One question at a time. Five at once returns three answers and two the agent cannot tell were skipped. `details.pending_question` is the one waiting. Two *related* sub-questions in one message are allowed. | Combine them into one message, or wait for a reply. | no | no | central |
| `SPEC_SECTION_UNKNOWN` | 422 | That specification section does not exist | The nine section keys are closed so that two writers cannot invent two spellings of one idea. `details.allowed` lists them. | Use one of the listed section keys. | no | no | central |
| `SPEC_VERSION_LIMIT` | 409 | This requirement has too many specification versions | A backstop against a loop, not a design constraint: a real clarification converges in a handful of rounds. | Approve the current version, or raise a new requirement. | no | no | central |
| `SPEC_QUESTION_AMBIGUOUS` | 422 | A question has both an answer and a known-unknown marking | Either resolves it for the approval gate, so filling both lights the button while hiding which state it is in — and 'this is the answer' and 'we decided not to resolve this' are what a reviewer needs to tell apart. | Keep the answer, or keep the known-unknown marking. | no | no | central |
| `PROPOSAL_EMPTY` | 422 | The proposal contains no tasks | A decomposition with no cards is not a decomposition. | Submit a tree with at least one task. | no | no | central |
| `PROPOSAL_TOO_LARGE` | 422 | That is too many cards for one decomposition | Not a granularity judgement — the server cannot make one — but a runaway backstop. Hitting it usually means the requirement should be split first. | Split the requirement, or decompose one epic at a time. | no | no | central |
| `PROPOSAL_TREE_INVALID` | 422 | The proposal tree does not hold together | A duplicate id, or a parent or dependency pointing at a node that is not in the tree. Checked at submission rather than at acceptance, because a reference among unselected items would otherwise surface much later. | Fix the named node and resubmit. | no | no | central |
| `PROPOSAL_TREE_CYCLE` | 422 | The proposal's dependencies form a cycle | `details.cycle` names the path. Naming it matters: 'there is a cycle' in a forty-node tree is not actionable. | Break the cycle and resubmit. | no | no | central |
| `PROPOSAL_FIELD_FORBIDDEN` | 422 | A decomposition may not declare that field | `required_secrets` is a person's decision on a card, not a proposal's. Refused rather than stripped, because stripping leaves the agent believing it declared something. | Remove the field; a person adds secrets to the card afterwards. | no | no | central |
| `PROPOSAL_RISK_UNDERSTATED` | 422 | This card mentions a high-risk area but is not marked high risk | Secrets, authentication, payments, migrations and infrastructure are stop condition 4. The term match is coarse on purpose and errs toward noise: an unnecessary badge costs one untick, a missed one puts a payments card in `ready` as low risk. | Set the card's risk to high, or reword it if the match is wrong. | no | no | central |
| `PROPOSAL_REJECT_NEEDS_NOTE` | 422 | Rejecting a proposal needs a reason | The reason is the only signal that accumulates on this path: the next decomposition of the same requirement receives it as a negative example. | Write why it was turned down. | no | no | central |
| `PROPOSAL_OVERRIDE_NOT_ACCEPTED` | 422 | That field cannot be edited while accepting | Either the item is not in this acceptance — an edit would then be applied silently at some later one — or the field is `readiness`, which would turn 'a card missing readiness lands in backlog' into a rule that disappears. | Select the item first, or edit the card after it is created. | no | no | central |

## Ticket conversation

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `QUESTION_NOT_FOUND` | 404 | That question is not on this card | A question belonging to another card is reported as absent rather than as forbidden: 'not here' is true and says nothing about what exists elsewhere. | Reload the card and answer a question listed on it. | no | no | central |
| `QUESTION_ALREADY_ANSWERED` | 409 | Somebody has already answered this question | Two people replying to one question is a normal event in a team, not an error state. `details` carries who answered and when, so the client can show the answer rather than only the failure. | Read the existing answer; add a comment if you have more to say. | no | no | central |
| `QUESTION_NOT_OPEN` | 409 | That question is no longer open | A question that timed out is kept rather than deleted, so it can still be read — but answering it no longer starts a turn. `details.state` says which state it is in. | Dispatch the card again, or ask a new question. | no | no | central |
| `RUN_NOT_WAITING_FOR_INPUT` | 409 | That run is not waiting for an answer | A run that is queued, claimed or running has nothing to resume. Reaching this with an open question means Central failed to park the run when the question was asked, which is a defect rather than a user error — so it is reported instead of being papered over. | Reload the card; if it persists, report it with the request id. | no | no | central |
| `CONVERSATION_CURSOR_AHEAD` | 409 | That conversation cursor is ahead of the card | The caller's stored position is beyond anything this card has. Answering with an empty page would leave it stuck there permanently with no signal, so it is refused and `details.conversation_seq` says where the card is. | Reset the cursor to the value in `details` and read again. | yes | no | central |
| `MESSAGE_IDEMPOTENCY_CONFLICT` | 409 | That idempotency key was used for a different message | A key identifies one message. Reusing it with different content would make the retry indistinguishable from a new message, which is the ambiguity the key exists to remove. | Use a new key, or resend the original content. | no | no | central |
| `TURN_ALREADY_QUEUED` | 409 | A continuation for that answer already exists | One answer creates at most one agent turn. This is enforced by a unique index rather than by a check, because the failure it prevents — the agent replying twice — has no other symptom. | Wait for the existing turn; no second one is needed. | no | no | central |
| `MESSAGE_TOO_LARGE` | 400 | That message is longer than a card message may be | `details` carries the limit and the actual length. This is a distinct code rather than a generic validation failure because the right response to it is specific: the text is safe, it needs shortening. | Shorten the message, or attach the long form as an artifact. | no | no | central |
| `AGENT_CANNOT_DECIDE` | 403 | Deciding is a person's action | An agent may propose; accepting or rejecting a proposal requires `task.approve`, which a run credential never holds. The refusal is explicit so that it is legible and audited, rather than a generic denial. | Post the content as a proposal and let a person decide. | no | no | central |

## Project memory

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `KNOWLEDGE_DISABLED` | 404 | This project has no memory | Project memory is enabled per project, not per deployment, because a 500-file project and a 50,000-file monorepo need different answers. The status is 404 rather than 403 on purpose: it does not disclose whether the project exists and has the feature switched off. | Enable project memory in the project's settings (needs `project.manage`). | no | no | central |
| `SOURCE_NOT_FOUND` | 404 | That source is no longer available | One of three things, and the message does not distinguish them because two of the three must not be distinguishable: the source was superseded or its original was deleted, the citation label belongs to an older context pack, or it belongs to another project. Answering 403 for the last case would confirm that it exists. | Run `cliora knowledge context` again to get current citations. | no | no | central |
| `SOURCE_EXCLUDED` | 409 | Somebody excluded this source from this card | An exclusion is per card and reversible, unlike a deletion. It exists so that one card can ignore a document without removing it from the other forty cards that cite it. | Ask whoever excluded it, or cite a different source. | no | no | central |
| `CONTEXT_BUDGET_EXCEEDED` | 409 | This card's context cannot be assembled within its budget | The pack is cut in a fixed order — retrieved sources first, then older conversation — and the project's rules and the open questions are never cut. Reaching this means those alone do not fit, which is a data problem rather than a load problem: silently truncating them would hand an agent a half-read question. | Shorten the project's policy text, or split the card. | no | no | central |
| `KNOWLEDGE_SYNC_TOO_LARGE` | 400 | This repository sync is over a limit | `details.limit` names which one — files, bytes or rate — and carries the count and the ceiling. A single oversized file is skipped instead and reported in `skipped`, because losing a project's whole memory over one large CHANGELOG is the wrong trade. | Narrow the sync with `.clioraignore`, or raise the project's repo_sync limits in its knowledge settings. | yes | no | central |

## Document patch proposals

| Code | HTTP | Message | Cause | Next step | Retryable | Audited | Origin |
|---|---:|---|---|---|:--:|:--:|:--:|
| `PATCH_PROPOSAL_NOT_FOUND` | 404 | Patch proposal not found | The document patch proposal does not exist. | Reload the project's proposals. | no | no | central |
| `PATCH_PROPOSAL_TARGET_INVALID` | 422 | The patch proposal's target or sections are malformed | The path must be repository-relative. The platform never opens it — the check is so that a person's review screen does not render something shaped like an attack. | Use a repository-relative path and one of the four section keys. | no | no | central |
| `PATCH_PROPOSAL_TOO_LARGE` | 422 | The patch is too large | Refused at submission rather than truncated at render: a truncated diff looks complete, and a person decides on it. | Split it into separate proposals per document. | no | no | central |
| `PATCH_PROPOSAL_ALREADY_DECIDED` | 409 | This patch proposal was already decided | Accept and reject are one-shot; the row keeps who decided and when. | Submit a new proposal if the document changed again. | no | no | central |
| `PATCH_PROPOSAL_REJECT_NEEDS_NOTE` | 422 | Rejecting a patch proposal needs a reason | Same rule as a decomposition proposal: a rejection with no reason is indistinguishable from no row three months later. | Write why it was turned down. | no | no | central |

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
| `TASK_SECRETS_NOT_ALLOWED` | 409 | This card asks for a secret name the project does not allow | A card may only declare names on its project's allowlist. The allowlist is intent — which names a card *may* ask for — and it is deliberately not derived from the secrets that happen to exist. | Add the name to the project's allowlist, or correct the card. The response names the offending entries and links to the settings page. | no | no | central |
| `TASK_SECRETS_MISSING` | 409 | This card asks for a secret that has not been created | The name is allowed, but nothing has been stored under it — most often because the secret was deleted. Running anyway would start the card **without** a value it says it needs, which looks like a broken agent. | Create the secret in project settings, or remove the declaration. | no | no | central |
| `TASK_BRANCH_NOT_DELIVERABLE` | 409 | That branch is outside the cliora/ namespace | The platform only ever pushes inside `cliora/<card>-<run>`, so a card continuing a branch elsewhere could never deliver. Refused here rather than at the push, where the run has already done its work. | Set delivery to artifact, or continue a branch the platform created. | no | no | central |
| `AGENT_TAG_MISMATCH` | 409 | That agent does not have the tags this card needs | Naming an agent does not create eligibility. People name a machine precisely because it is the only one with what the card needs, so letting the name override the tag would run the card somewhere it fails minutes in. | The response names the missing tags: pick another agent, or add them to that node's agentd configuration. | no | no | central |
| `AGENT_REFUSES_UNTAGGED` | 409 | That agent only claims cards that declare a tag | The node is reserved for tagged work (`run_untagged: false`). Without that setting a dedicated machine fills up with ordinary untagged cards. | Give the card a tag that machine has, or dispatch to another agent. | no | no | central |
| `AGENT_REFUSES_SECRETS` | 409 | That agent does not accept secrets | The node's owner declared `accept_secrets: false`, which is the operator's veto over which machines may hold a credential (ADR 0032 §0). | Dispatch to a node that accepts secrets, or remove the declaration. | no | no | central |
| `SECRET_NAME_INVALID` | 422 | That is not a usable secret name | A secret's name becomes an environment variable, so it must be upper-case letters, digits and underscores. | Rename it, for example GITHUB_TOKEN. | no | no | central |
| `SECRET_NAME_RESERVED` | 422 | That name would replace part of the execution environment | Names like PATH or HOME, and the GIT_/SSH_/CLIORA_ prefixes, are reserved. A secret called GIT_ASKPASS would take over the credential helper the platform's own git path is built on. | Choose a name outside the reserved set. | no | no | central |
| `SECRET_KIND_INVALID` | 422 | Unknown secret kind | A secret's kind decides where its value goes on the node, so it is a closed set (ADR 0032 §4). | Use env, git_pat, git_ssh_key or provider_token. | no | no | central |
| `SECRET_EXISTS` | 409 | This project already has a secret with that name | Names are unique per project among the secrets that have not been deleted. | Rotate the existing one instead of creating a second. | no | no | central |
| `SECRET_IN_USE` | 409 | A registered repository authenticates with this secret | Deleting it would leave that repository pointing at a credential that no longer exists, and the failure would surface minutes into a run. | Point the repository at another credential first; the response names it. | no | no | central |
| `SECRET_TOO_LARGE` | 413 | That value is larger than a secret should be | Eight KiB, which is 2.4x the largest legitimate input measured (an RSA-4096 private key at 3 369 bytes). Eight of these also have to fit inside one 64 KiB dispatch frame alongside the task context. | An ed25519 key is 399 bytes and does the same job. | no | no | central |
| `GIT_SECRET_DELIVERY_DISABLED` | 422 | This deployment does not deliver git credentials from the platform | Off by default (2026-08-13 ruling): at this stage git authentication is configured on the node by its owner, and the platform does not manage it. Storing a credential that would never be delivered is a setting that looks finished and is not. | Configure git authentication on the node, or set CLIORA_GIT_SECRET_DELIVERY_ENABLED on Central. | no | no | central |
| `TASK_DELIVERY_UNSUPPORTED` | 409 | That delivery mode is not available on this deployment | This version delivers by attaching artifacts to the card. Branches and pull requests arrive with the platform's own git write path. | Set delivery to none or artifact for now; the response names the version the declared mode starts working in. | no | no | central |
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
