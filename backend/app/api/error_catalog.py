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
            "One live system terminal per CLI session (ADR 0021), and another tab or "
            "window is attached to the existing one right now.",
            "Return to the tab holding it, or close it there. A terminal nobody is "
            "attached to is not a refusal: the next open replaces it.",
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
        # --- Project layer (ADR 0027) ---
        #
        # There is deliberately no `PROJECT_*` code for "the project layer is
        # disabled". With the flag off those paths answer a bare 404, because a body
        # naming the feature would leak exactly what the 404 withholds — that the
        # capability exists and is merely switched off (deps.require_projects_enabled).
        #
        # There is also no new code for a rejected workspace path: binding reuses
        # `WORKSPACE_OUTSIDE_ALLOWED_ROOT` below. A second, synonymous code would give
        # "why is this path not allowed" two answers depending on which endpoint the
        # user happened to reach.
        _entry(
            "PROJECT_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Project not found",
            "The project does not exist, or was archived and then removed from view.",
            "Reload the project list.",
        ),
        _entry(
            "PROJECT_SLUG_TAKEN",
            status.HTTP_409_CONFLICT,
            "A project with this slug already exists",
            "Slugs are unique across the platform, and fixed once the project exists.",
            "Choose a different slug. The display name can still be whatever you like.",
        ),
        _entry(
            "PROJECT_SLUG_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Slug must be lowercase letters, digits and hyphens",
            "The supplied slug has an unusable character, or a name written entirely "
            "in non-Latin script left nothing to derive one from.",
            "Supply a slug explicitly, for example `traqora-api`.",
        ),
        _entry(
            "PROJECT_STATUS_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown project status",
            "A project is active, paused or archived; nothing else.",
            "Use one of the three states.",
        ),
        _entry(
            "PROJECT_ARCHIVED",
            status.HTTP_409_CONFLICT,
            "This project is archived",
            "An archived project accepts no new sessions and no new workspace "
            "bindings. Everything already running is untouched.",
            "Un-archive the project first, or use a different one.",
        ),
        # --- Task layer (ADR 0028) ---
        #
        # Two pairs here look similar and are not, and the difference is what makes
        # them worth separate codes: `TASK_DEPENDENCY_UNSATISFIED` is a card that will
        # be movable later, `TASK_DEPENDENCY_CYCLE` is a graph that can never be
        # satisfied; `GATE_UNKNOWN` is a typo, `GATE_DISABLED` is a state of the
        # deployment. Collapsing either pair would leave the user unable to tell
        # "wait" from "fix something".
        _entry(
            "TASK_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Task not found",
            "The card, epic, story or dependency does not exist in this project.",
            "Reload the board.",
        ),
        _entry(
            "TASK_VERSION_CONFLICT",
            status.HTTP_409_CONFLICT,
            "This card was changed by someone else",
            "Every write carries the version it was read at, so two people dragging "
            "one card cannot silently overwrite each other. The response carries the "
            "card's current version.",
            "The board reloads the card; try the move again.",
        ),
        _entry(
            "TASK_DEPENDENCY_UNSATISFIED",
            status.HTTP_409_CONFLICT,
            "A blocking card is not finished",
            "Entering `ready` or a later lane claims the card is workable, and an "
            "unfinished dependency contradicts that. `details.blocking_refs` names "
            "the cards.",
            "Finish the named cards, or drop the dependency if it no longer holds.",
        ),
        _entry(
            "TASK_DEPENDENCY_CYCLE",
            status.HTTP_409_CONFLICT,
            "That would create a circular dependency",
            "The blocking card already depends on this one, directly or through "
            "others. `details.path` shows the loop.",
            "Remove one edge of the loop first.",
        ),
        _entry(
            "TASK_STAGE_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown value",
            "A lane, risk, priority, source or delivery outside the process "
            "definition's vocabulary.",
            "Read the project's process definition for the accepted values.",
        ),
        _entry(
            "TASK_ACCEPTANCE_CRITERIA_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Acceptance criteria must be a list of objects",
            "The task context renderer requires each criterion to be an object, and "
            "from V2.4 its result must be one of four values. `details.allowed` names "
            "them.",
            "Send each criterion as an object with a text field, and a result of "
            "passed, failed, partial or not_verified.",
        ),
        # --- V2.4: the Done Gate and the one exit around it (ADR 0033 sec 5) ---
        _entry(
            "TASK_DONE_GATE_UNMET",
            status.HTTP_409_CONFLICT,
            "This card is missing some of its completion evidence",
            "Entering `done` claims the work is finished, and the platform holds the "
            "facts that support that claim. `details.missing` names **every** unmet "
            "item, not the first one — the action for a missing summary and a missing "
            "report are different.",
            "Supply the named items. An administrator may force the move with a "
            "reason, which stays visible on the card.",
        ),
        _entry(
            "TASK_FORCE_REASON_REQUIRED",
            status.HTTP_400_BAD_REQUEST,
            "Forcing a card into done requires a reason",
            "The reason is stored on the card and on the timeline, and it is what "
            "makes the exit visible rather than silent.",
            "Send force_reason with the patch.",
        ),
        _entry(
            "TASK_DELIVERY_NEEDS_SOURCE",
            status.HTTP_409_CONFLICT,
            "A pull request needs code to deliver",
            "The card asks to deliver as a pull request while declaring that it fetches "
            "no code. The two are separate fields on purpose, and this combination has "
            "nothing to open a pull request on.",
            "Set source to repo, or deliver as none or artifact.",
        ),
        _entry(
            "TASK_PR_TARGET_MISSING",
            status.HTTP_409_CONFLICT,
            "A pull request needs a target branch",
            "Refused at dispatch rather than at delivery, where the run would already "
            "have spent its work.",
            "Set the card's target branch.",
        ),
        _entry(
            "TASK_EXISTING_PR_OUT_OF_NAMESPACE",
            status.HTTP_409_CONFLICT,
            "That branch is outside the platform's namespace",
            "The platform pushes only inside `cliora/`, so continuing an existing pull "
            "request works for the ones it opened itself and no others. **This reads as "
            "a defect and is a boundary**: the constraint is compiled into the daemon "
            "and is what makes 'where can the platform push' answerable without looking "
            "at data.",
            "Deliver as a branch and merge it yourself, or continue a pull request the "
            "platform opened.",
        ),
        _entry(
            "TASK_PROVIDER_UNSUPPORTED",
            status.HTTP_409_CONFLICT,
            "This deployment has no pull-request integration for that host",
            "Refused at dispatch rather than after the work: a half-built provider that "
            "fails at delivery costs a whole run.",
            "Deliver as a branch, or use a repository on a supported host.",
        ),
        _entry(
            "VERIFICATION_COMMANDS_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A verification command is not in the expected shape",
            "Commands are argv arrays rather than shell strings, so pipelines and `&&` "
            "do not apply — split them into separate commands. The encoded length is "
            "measured **when the command is saved** rather than when a run is offered, "
            "because a command that stores fine and silently never ships would make "
            "'this project's verification never ran' a fact nobody goes looking for.",
            "Shorten the name or the arguments, or split the command in two.",
        ),
        _entry(
            "PLAN_STEPS_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A plan step is not in the expected shape",
            "Each step is an object whose status is one of five values. "
            "`details.allowed` names them.",
            "Send each step as an object with a title and one of the five statuses.",
        ),
        _entry(
            "PLAN_NOTE_REQUIRED",
            status.HTTP_400_BAD_REQUEST,
            "Revising a plan requires a note",
            "Why the plan changed is the reason a version row exists rather than a "
            "mutable column, so the second version onward must carry one.",
            "Send a note describing what changed and why.",
        ),
        _entry(
            "PLAN_SEQ_CONFLICT",
            status.HTTP_409_CONFLICT,
            "Another writer recorded a plan at the same time",
            "Two submissions took the same version number. The server retries once by "
            "itself; a second collision means something is writing faster than this "
            "table is for.",
            "Retry the submission.",
            # The one retryable code in this group, and the affordance is asserted
            # against the browser's copy: a retry button that appears where retrying
            # cannot help is worse than none.
            retryable=True,
        ),
        _entry(
            "VERIFICATION_REPORT_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The verification report is not in the expected shape",
            "`details.field` names the field. A `source` in the payload is **not** an "
            "error — it is accepted, discarded, and recorded as discarded, because the "
            "credibility level is decided by the write path.",
            "Correct the named field. The result is one of five values.",
        ),
        _entry(
            "EVIDENCE_KIND_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown evidence kind",
            "The kind decides the credibility level, so it comes from a closed set. "
            "`details.allowed` names it.",
            "Use one of the listed kinds.",
        ),
        _entry(
            "EVIDENCE_KIND_NOT_WRITABLE",
            status.HTTP_403_FORBIDDEN,
            "That kind of evidence is written by the platform, not by an agent",
            "The kind decides the source, so an agent writing a machine-fact kind is "
            "**refused rather than downgraded** — a downgraded row would still assert "
            "something nobody observed.",
            "Record it as a finding, a limitation or a risk.",
        ),
        _entry(
            "EVIDENCE_PAYLOAD_TOO_LARGE",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That piece of evidence is too large",
            "Evidence is a structured fact somebody scans, not a file store. Artifacts "
            "already have a quota, a retention period and a download path.",
            "Attach it to the card as an artifact instead.",
        ),
        _entry(
            "EVIDENCE_RUN_LIMIT",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "This run has recorded as much evidence as it may",
            "A per-run ceiling, so one run cannot fill the card's evidence list.",
            "Summarise, or attach the detail as an artifact.",
        ),
        _entry(
            "PROCESS_OVERRIDE_UNKNOWN_KEY",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That process item does not exist",
            "A project may disable existing readiness items and gates, never add one. "
            "An unrecognised key is refused rather than stored, because a stored one "
            "is silently ineffective and the person who typed it believes it worked. "
            "`details.unknown` names them.",
            "Check the key against the project's process definition.",
        ),
        _entry(
            "TASK_CONTEXT_TOO_LARGE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Acceptance criteria do not fit the task context budget",
            "Acceptance criteria are preserved in full in the 4 KB agent context pack, "
            "so their rendered form has a fixed upper bound.",
            "Shorten or combine acceptance criteria; optional task description sections "
            "are omitted automatically.",
        ),
        _entry(
            "FORBIDDEN_FIELD",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That field cannot be set this way",
            "Refused rather than ignored: a silently dropped field is a change the "
            "caller believes it made. Review gates in particular have their own "
            "endpoint and their own action.",
            "Use the endpoint that owns the field.",
        ),
        _entry(
            "GATE_UNKNOWN",
            status.HTTP_404_NOT_FOUND,
            "Unknown review gate",
            "The process definition has no gate by that key.",
            "Read the project's process definition for the gate keys.",
        ),
        _entry(
            "GATE_DISABLED",
            status.HTTP_409_CONFLICT,
            "This gate is unavailable in this deployment",
            "A gate may depend on an integration that is switched off — the mockup "
            "gate needs tunnel integration. It is disabled on read rather than left "
            "unsatisfiable, because a gate nobody can ever tick is a deadlock.",
            "Enable the integration, or proceed without that gate.",
        ),
        _entry(
            "GATE_REQUIRES_HUMAN_ACTOR",
            status.HTTP_403_FORBIDDEN,
            "A review gate must be approved by a person",
            "An agent's output is not an approval. A session credential cannot reach "
            "this endpoint at all; this code is the second line of defence.",
            "Approve it yourself in the console.",
        ),
        _entry(
            "REQUIREMENT_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Requirement not found",
            "The requirement does not exist in this project.",
            "Reload the requirements list.",
        ),
        _entry(
            "REQUIREMENT_NOT_SPECIFIED",
            status.HTTP_409_CONFLICT,
            "Write a specification before approving",
            "Approval is approval *of* something: a requirement with no specification "
            "version has nothing to approve.",
            "Add a specification version first.",
        ),
        _entry(
            "SPEC_HAS_OPEN_QUESTIONS",
            status.HTTP_409_CONFLICT,
            "Unresolved questions remain",
            "A specification cannot be approved while a question has neither an "
            "answer nor an explicit 'known unknown' marking. `details.questions` "
            "names them.",
            "Answer them, or mark them as known unknowns, then approve.",
        ),
        _entry(
            "REQUIREMENT_ALREADY_APPROVED",
            status.HTTP_409_CONFLICT,
            "This requirement is approved",
            "Specification versions are append-only up to approval; after it, a "
            "change of mind is a new requirement rather than a rewritten one.",
            "Raise a new requirement.",
        ),
        _entry(
            "REQUIREMENT_NOT_APPROVED",
            status.HTTP_409_CONFLICT,
            "Approve the specification before decomposing it",
            "Decomposing something nobody has agreed to produces work that will be "
            "thrown away. This is refused by the API rather than hidden in the UI, "
            "because V2.5 sends an agent down the same path.",
            "Approve the specification first.",
        ),
        _entry(
            "PROPOSAL_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Proposal not found",
            "The decomposition proposal does not exist.",
            "Reload the requirement.",
        ),
        _entry(
            "PROPOSAL_ALREADY_DECIDED",
            status.HTTP_409_CONFLICT,
            "This proposal was already decided",
            "Acceptance creates real cards, so it happens once. A second decision "
            "would duplicate them.",
            "Create a new proposal if the plan changed.",
        ),
        _entry(
            "PROJECT_WORKSPACE_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Workspace binding not found",
            "The binding was already removed, or belongs to another project.",
            "Reload the project.",
        ),
        _entry(
            "SESSION_PROJECT_MISMATCH",
            status.HTTP_400_BAD_REQUEST,
            "The workspace does not belong to this project",
            "A session may name a project only when its workspace is one of that "
            "project's bindings. The match is exact, so a subdirectory of a bound "
            "path is not itself bound.",
            "Pick a path from the project's bindings, bind this one first, or create "
            "the session without a project.",
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
        # --- Image drop (P13, ADR 0024) ---
        _entry(
            "FILE_UPLOAD_TOO_LARGE",
            None,
            "The image is larger than 4 MiB",
            "Central refuses the request before reading the whole body, and the "
            "daemon refuses it again before writing anything.",
            "Compress or resize the image and try again.",
            origin=CENTRAL,
        ),
        _entry(
            "FILE_UPLOAD_UNSUPPORTED_TYPE",
            None,
            "Only PNG, JPEG, GIF and WebP images can be dropped",
            "The content did not match one of the four accepted image signatures. "
            "The declared content type is not what decides this.",
            "Convert the file to a supported image format. SVG and PDF are not images here.",
            origin=DAEMON,
        ),
        _entry(
            "FILE_UPLOAD_QUOTA_EXCEEDED",
            None,
            "This session has reached its image quota",
            "Either the cumulative byte quota or the per-day file count for this "
            "workspace is full.",
            # This used to say "delete them from the file tree", which has never been
            # possible — there is no delete affordance, and ADR 0026 deliberately did
            # not add one. Pointing at the terminal is the only honest advice.
            "Remove images you no longer need from .cliora/uploads/ on the node "
            "(a terminal session is the way to do that); expired ones are removed "
            "automatically after 7 days.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "FILE_UPLOAD_FAILED",
            None,
            "The node could not store the image",
            "Writing to the workspace failed — no disk space, no permission, or "
            ".cliora exists but is not a directory.",
            "Ask an administrator to check the node; `agentd doctor` names the file to fix.",
            # Retryable: the common causes (disk pressure, a transient permission
            # problem) clear on their own, and a retry cannot write twice — the
            # daemon names each file itself, so nothing is overwritten.
            retryable=True,
            origin=DAEMON,
        ),
        # --- General file upload (P15, ADR 0026) ---
        _entry(
            "FILE_EXISTS",
            None,
            "A file or directory with that name already exists",
            "Upload never replaces anything: the node creates the file with O_EXCL, "
            "so a name that is already taken is refused and not one existing byte is "
            "touched. That property is why this path needs no version token and has "
            "no undo.",
            "Upload it under a different name, or replace the file from a terminal "
            "session if replacing is what you meant.",
            origin=DAEMON,
        ),
        _entry(
            "FILE_UPLOAD_NO_SPACE",
            None,
            "The node does not have enough free disk space",
            "The workspace filesystem is below the node's configured free-space floor, "
            "or the file would not leave twice its own size free. This check is what "
            "stands in for a retention period on this path: uploaded files belong to "
            "the user, so nothing expires them.",
            "Free space on the node, or ask an administrator to; `agentd doctor` "
            "reports the figure it is comparing against.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "FILE_INVALID_NAME",
            None,
            "That filename cannot be used",
            "A filename must be a single path segment: no separator, no control "
            "characters, at most 255 bytes. Checked after URL decoding, because "
            "percent-encoding can otherwise smuggle a separator through.",
            "Rename the file and try again.",
            origin=CENTRAL,
        ),
        _entry(
            "FILE_UPLOAD_DISABLED",
            None,
            "This node does not accept image drop",
            "The node's config sets filesystem.upload.enabled to false. Whether a "
            "workspace may be written to is the node's decision, not the platform's.",
            "None from the browser; the node's owner controls this setting.",
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
        # --- P11: port forwarding through a third-party tunnel provider (ADR 0022) ---
        # Six of these travel on the wire: the daemon raises them and Central relays the
        # code, never the daemon's own string. Three are Central-only settings states the
        # daemon can never produce (TUNNEL_INTEGRATION_DISABLED, TUNNEL_NODE_DISABLED,
        # SECRET_KEY_MISSING), and each was added together with the service that raises it,
        # because an entry for a code nothing produces is a documented error nobody can see.
        _entry(
            "TUNNEL_INTEGRATION_DISABLED",
            status.HTTP_404_NOT_FOUND,
            "Port forwarding is not enabled for this deployment",
            "The capability is switched off in the platform's integration settings, which is "
            "where an administrator supplies the provider account it would run on.",
            "Ask an administrator to enable port forwarding in Integration settings and "
            "supply the provider credential.",
        ),
        _entry(
            "TUNNEL_NODE_DISABLED",
            status.HTTP_409_CONFLICT,
            "This node does not take part in port forwarding",
            "Either the node is switched off for port forwarding in its platform settings, "
            "or the node's own configuration vetoes it. The two have different remedies, "
            "which is why the message names which one refused.",
            "If it is the platform setting, turn it on from the node's port-forwarding page. "
            "If the node vetoed it locally, its owner has to change `tunnel.enabled` in "
            "/etc/agentd/config.yaml — the platform cannot override that.",
        ),
        _entry(
            "SECRET_KEY_MISSING",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "This deployment cannot store integration credentials",
            "A provider credential can only be stored encrypted, and this deployment has no "
            "encryption key configured. Storing it in plain text is refused rather than done "
            "quietly, because plaintext already written cannot be un-disclosed.",
            "Ask the deployment administrator to set CLIORA_SECRET_ENCRYPTION_KEY "
            "(openssl rand -base64 32), then enable the integration again.",
        ),
        _entry(
            "TUNNEL_PROVIDER_NOT_CONFIGURED",
            status.HTTP_409_CONFLICT,
            "This node cannot open a tunnel yet",
            "The node is missing a prerequisite: the ssh client, outbound access to the "
            "provider, or the pinned provider host key.",
            "Run `agentd doctor` on the node; it names which of the three is missing.",
            origin=DAEMON,
        ),
        _entry(
            "TUNNEL_PROVIDER_UNAVAILABLE",
            status.HTTP_502_BAD_GATEWAY,
            "The tunnel provider could not be reached",
            "The node could not establish its outbound connection to the tunnel provider. "
            "That is usually a network path problem rather than a platform fault.",
            "Retry shortly. If it persists, confirm the node can reach the provider on port 443.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "TUNNEL_PROVIDER_UNAUTHORIZED",
            status.HTTP_502_BAD_GATEWAY,
            "The tunnel provider rejected the stored credential",
            "The provider did not accept the credential. It answers this by silently "
            "downgrading to an anonymous, time-limited tunnel, so the tunnel is torn "
            "down rather than handed over as if it were the one that was asked for.",
            "Ask an administrator to update the provider credential in Integration settings.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "TUNNEL_PROVIDER_UNTRUSTED",
            status.HTTP_502_BAD_GATEWAY,
            "The tunnel provider's host key did not match",
            "The provider presented a host key that does not match the one pinned on the "
            "node, and the connection was stopped. This is what an intercepted outbound "
            "connection looks like; it is also what a legitimate key rotation looks like.",
            "Contact an administrator. Do not disable host key checking to get past this.",
            audited=True,
            origin=DAEMON,
        ),
        _entry(
            "TUNNEL_PORT_NOT_ALLOWED",
            status.HTTP_409_CONFLICT,
            "That port may not be forwarded",
            "Ports below 1024 are never forwarded, and this node's allowed range may be "
            "narrower still. The narrowest of the platform, node and local settings wins.",
            "Use a port at or above 1024 that is inside the range shown on the node's "
            "port-forwarding page.",
            origin=DAEMON,
        ),
        _entry(
            "TUNNEL_LIMIT_REACHED",
            status.HTTP_409_CONFLICT,
            "The tunnel limit has been reached",
            "One of three limits is full: the platform's concurrent budget, this node's "
            "cap, or your own. The message on screen says which.",
            "Close a tunnel that is no longer needed, or ask an administrator to raise "
            "the budget to match the provider plan.",
            origin=DAEMON,
        ),
        # --- V2.2 agent runner: dispatch (ADR 0029) ---
        # The order these can occur in is fixed (plan/18/00-…md D13) precisely so that
        # the *first* thing a person is told is the thing they can act on.
        _entry(
            "TASK_NOT_READY",
            status.HTTP_409_CONFLICT,
            "Only a card in the ready lane can be dispatched to an agent",
            "The card is in another lane. Dispatch is an execution action, and a card "
            "that is not ready has not been agreed to be worked on yet.",
            "Move the card to Ready first.",
        ),
        _entry(
            "RUN_ALREADY_ACTIVE",
            status.HTTP_409_CONFLICT,
            "This card already has a run in progress",
            "A card has at most one run in flight; a second would mean two agents "
            "changing the same work with no way to reconcile them.",
            "Wait for the run to finish, or cancel it first.",
        ),
        _entry(
            "RUN_NOT_ACTIVE",
            status.HTTP_409_CONFLICT,
            "This run has already finished",
            "Cancel only applies to a run that is queued or running.",
            "Look at the run's result; if it needs doing again, dispatch the card again.",
        ),
        # V2.3 replaced `TASK_REQUIRES_SECRETS` rather than removing it: secrets exist
        # now, so the refusals are about *this card* rather than about the version.
        # **Two codes, because they are fixed on different pages** (ADR 0032 §0).
        _entry(
            "TASK_SECRETS_NOT_ALLOWED",
            status.HTTP_409_CONFLICT,
            "This card asks for a secret name the project does not allow",
            "A card may only declare names on its project's allowlist. The allowlist is "
            "intent — which names a card *may* ask for — and it is deliberately not "
            "derived from the secrets that happen to exist.",
            "Add the name to the project's allowlist, or correct the card. The response "
            "names the offending entries and links to the settings page.",
        ),
        _entry(
            "TASK_SECRETS_MISSING",
            status.HTTP_409_CONFLICT,
            "This card asks for a secret that has not been created",
            "The name is allowed, but nothing has been stored under it — most often "
            "because the secret was deleted. Running anyway would start the card "
            "**without** a value it says it needs, which looks like a broken agent.",
            "Create the secret in project settings, or remove the declaration.",
        ),
        _entry(
            "TASK_BRANCH_NOT_DELIVERABLE",
            status.HTTP_409_CONFLICT,
            "That branch is outside the cliora/ namespace",
            "The platform only ever pushes inside `cliora/<card>-<run>`, so a card "
            "continuing a branch elsewhere could never deliver. Refused here rather "
            "than at the push, where the run has already done its work.",
            "Set delivery to artifact, or continue a branch the platform created.",
        ),
        _entry(
            "AGENT_TAG_MISMATCH",
            status.HTTP_409_CONFLICT,
            "That agent does not have the tags this card needs",
            "Naming an agent does not create eligibility. People name a machine "
            "precisely because it is the only one with what the card needs, so letting "
            "the name override the tag would run the card somewhere it fails minutes in.",
            "The response names the missing tags: pick another agent, or add them to "
            "that node's agentd configuration.",
        ),
        _entry(
            "AGENT_REFUSES_UNTAGGED",
            status.HTTP_409_CONFLICT,
            "That agent only claims cards that declare a tag",
            "The node is reserved for tagged work (`run_untagged: false`). Without that "
            "setting a dedicated machine fills up with ordinary untagged cards.",
            "Give the card a tag that machine has, or dispatch to another agent.",
        ),
        _entry(
            "AGENT_REFUSES_SECRETS",
            status.HTTP_409_CONFLICT,
            "That agent does not accept secrets",
            "The node's owner declared `accept_secrets: false`, which is the operator's "
            "veto over which machines may hold a credential (ADR 0032 §0).",
            "Dispatch to a node that accepts secrets, or remove the declaration.",
        ),
        _entry(
            "SECRET_NAME_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That is not a usable secret name",
            "A secret's name becomes an environment variable, so it must be upper-case "
            "letters, digits and underscores.",
            "Rename it, for example GITHUB_TOKEN.",
        ),
        _entry(
            "SECRET_NAME_RESERVED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That name would replace part of the execution environment",
            "Names like PATH or HOME, and the GIT_/SSH_/CLIORA_ prefixes, are reserved. "
            "A secret called GIT_ASKPASS would take over the credential helper the "
            "platform's own git path is built on.",
            "Choose a name outside the reserved set.",
        ),
        _entry(
            "SECRET_KIND_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unknown secret kind",
            "A secret's kind decides where its value goes on the node, so it is a "
            "closed set (ADR 0032 §4).",
            "Use env, git_pat, git_ssh_key or provider_token.",
        ),
        _entry(
            "SECRET_EXISTS",
            status.HTTP_409_CONFLICT,
            "This project already has a secret with that name",
            "Names are unique per project among the secrets that have not been deleted.",
            "Rotate the existing one instead of creating a second.",
        ),
        _entry(
            "SECRET_IN_USE",
            status.HTTP_409_CONFLICT,
            "A registered repository authenticates with this secret",
            "Deleting it would leave that repository pointing at a credential that no "
            "longer exists, and the failure would surface minutes into a run.",
            "Point the repository at another credential first; the response names it.",
        ),
        _entry(
            "SECRET_TOO_LARGE",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That value is larger than a secret should be",
            "Eight KiB, which is 2.4x the largest legitimate input measured (an "
            "RSA-4096 private key at 3 369 bytes). Eight of these also have to fit "
            "inside one 64 KiB dispatch frame alongside the task context.",
            "An ed25519 key is 399 bytes and does the same job.",
        ),
        _entry(
            "GIT_SECRET_DELIVERY_DISABLED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This deployment does not deliver git credentials from the platform",
            "Off by default (2026-08-13 ruling): at this stage git authentication is "
            "configured on the node by its owner, and the platform does not manage it. "
            "Storing a credential that would never be delivered is a setting that looks "
            "finished and is not.",
            "Configure git authentication on the node, or set "
            "CLIORA_GIT_SECRET_DELIVERY_ENABLED on Central.",
        ),
        _entry(
            "TASK_DELIVERY_UNSUPPORTED",
            status.HTTP_409_CONFLICT,
            "That delivery mode is not available on this deployment",
            "This version delivers by attaching artifacts to the card. Branches and "
            "pull requests arrive with the platform's own git write path.",
            "Set delivery to none or artifact for now; the response names the version "
            "the declared mode starts working in.",
        ),
        _entry(
            "PROJECT_NO_REPOSITORY",
            status.HTTP_409_CONFLICT,
            "This project has no repository registered",
            "An agent fetches the code itself, so the platform has to know where the "
            "code is. Nothing on the card can supply that — it is project settings.",
            "Register the repository in the project's settings, then dispatch again. "
            "The response carries a link to the right page.",
        ),
        _entry(
            "REPOSITORY_HOST_NOT_ALLOWED",
            status.HTTP_400_BAD_REQUEST,
            "This deployment does not allow repositories on that host",
            "Two allowlists apply: the deployment's and each node's. This is the "
            "deployment's, and it is empty until an administrator sets it.",
            "Ask an administrator to add the host to CLIORA_GIT_ALLOWED_HOSTS.",
        ),
        _entry(
            "REPOSITORY_EXISTS",
            status.HTTP_409_CONFLICT,
            "That repository is already registered for this project",
            "A project may list several repositories, but not the same one twice.",
            "Use the existing entry, or remove it first if the branch needs changing.",
        ),
        _entry(
            "AGENT_DISABLED",
            status.HTTP_409_CONFLICT,
            "That agent is disabled",
            "The card named a specific agent, and it is switched off. This is refused "
            "at dispatch rather than queued, because a disabled agent is a decision "
            "somebody made rather than a machine that will come back.",
            "Enable the agent, or dispatch without naming one.",
        ),
        # --- V2.2 card artifacts (ADR 0030 Part B) ---
        # The three quota codes answer 413 and each says which layer was hit. None of
        # them fails silently: an agent that could not attach its work has to be able
        # to say so on the card.
        _entry(
            "ARTIFACT_TOO_LARGE",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "That file is larger than the per-file limit",
            "One artifact may not exceed the deployment's single-file limit.",
            "Split it, compress it, or attach a summary and keep the full output elsewhere.",
        ),
        _entry(
            "ARTIFACT_RUN_LIMIT",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "This run has attached as many artifacts as it may",
            "A single run has a cap on how many files it can attach, so one loop "
            "cannot fill a project's quota by itself.",
            "Attach one combined file instead of many.",
        ),
        _entry(
            "ARTIFACT_PROJECT_QUOTA",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "This project's artifact quota is full",
            "Artifacts follow the card and are never deleted on a timer, so a project "
            "accumulates them until somebody decides which to remove.",
            "Delete artifacts that are no longer needed — deletion frees the bytes "
            "even though the record of the deletion stays.",
        ),
        _entry(
            "ARTIFACT_DIGEST_MISMATCH",
            status.HTTP_400_BAD_REQUEST,
            "The upload did not match its stated digest",
            "Not tamper protection — the connection is already TLS. It catches a "
            "**truncated** upload, which should fail rather than become a broken "
            "artifact nobody can open.",
            "Retry the upload.",
            retryable=True,
        ),
        _entry(
            "ARTIFACT_DELETED",
            status.HTTP_410_GONE,
            "That artifact was deleted",
            "Its bytes are gone; the record of who deleted it and why is deliberately still there.",
            "The card shows the reason next to the entry.",
        ),
        _entry(
            "RUN_TOKEN_TTL_EXCEEDED",
            status.HTTP_409_CONFLICT,
            "This run would need a credential that outlives the platform's limit",
            "A run credential may not live longer than the deployment's ceiling on "
            "agent credentials. That started to bite when the run wall clock grew to "
            "six hours, so it is refused here rather than issued and expiring mid-run.",
            "Lower the run timeout, or raise CLIORA_RUN_TOKEN_TTL_HOURS.",
        ),
        # --- V2.2 agent runner: the wire's own codes (ADR 0029/0031) ---
        # These arrive from a node, so a client can see any of them through the relay
        # and each needs guidance rather than a bare string.
        _entry(
            "AGENT_RUNS_DISABLED",
            status.HTTP_409_CONFLICT,
            "Agent runs are switched off in this deployment",
            "A daemon tried to register as a runner while `CLIORA_AGENT_RUNS_ENABLED` "
            "is false. The node keeps serving interactive sessions.",
            "Enable the flag on Central if unattended execution is wanted here.",
            origin=DAEMON,
        ),
        _entry(
            "RUNNER_NOT_REGISTERED",
            status.HTTP_409_CONFLICT,
            "That node has not registered as a runner",
            "A poll arrived before registration — usually a daemon that reconnected "
            "and has not yet re-announced itself.",
            "None; the daemon registers on its next connection and resumes polling.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "RUNNER_DISABLED",
            status.HTTP_409_CONFLICT,
            "That agent is switched off",
            "An administrator disabled it, so it is refused work even though its node is online.",
            "Enable it on the Agents page.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Run not found",
            "The run id is unknown here — usually a late or duplicated frame from a "
            "node about a run that has already been reclaimed.",
            "None; this is normal after a lease expires.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_INVALID_STATE",
            status.HTTP_409_CONFLICT,
            "That run has already finished",
            "A lease renewal or progress report arrived for a run in a terminal state.",
            "None; the node stops reporting once it sees the run is gone.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_SOURCE_UNAVAILABLE",
            status.HTTP_409_CONFLICT,
            "The agent could not fetch the code",
            "One of three things: the machine has no credential for that repository, "
            "the host is not on that node's allowlist, or the ref does not exist. The "
            "details say which — **and never echo the URL**, because somebody may have "
            "pasted a credential into it.",
            "Check the details: supply the credential on that machine, add the host to "
            "the node's allowlist, or correct the branch on the card.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_DISK_QUOTA",
            status.HTTP_409_CONFLICT,
            "The agent ran out of its disk allowance",
            "A run directory or the node's total exceeded its quota. Quotas exist "
            "because a runaway build would otherwise fill the disk and take interactive "
            "sessions down with it.",
            "Wait for the cleanup loop, or raise `runner.run_quota_bytes` on that node "
            "if the work genuinely needs more.",
            origin=DAEMON,
        ),
        _entry(
            # Deliberately separate from RUN_TIMEOUT: to a person one means "it is
            # stuck, look at the last event" and the other means "it cannot finish,
            # look at whether the card is too big".
            "RUN_IDLE_TIMEOUT",
            status.HTTP_409_CONFLICT,
            "The agent stopped producing events",
            "Liveness is judged from the runtime's event stream, not from a wall clock. "
            "No event arrived within the idle limit, so the run was stopped.",
            "Look at the last entries in the run log; if the work legitimately goes "
            "quiet for longer, raise `runner.idle_timeout_seconds`.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_TIMEOUT",
            status.HTTP_409_CONFLICT,
            "The run hit its wall-clock limit",
            "The backstop, not the liveness test: the run was still emitting events and "
            "simply did not finish in time.",
            "Split the card, or raise the run timeout for this deployment.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_RUNTIME_UNAVAILABLE",
            status.HTTP_409_CONFLICT,
            "The runtime is not usable on that node",
            "The CLI is missing, not executable, or too old to expose a non-interactive "
            "interface with an event stream.",
            "Install or update the CLI on that machine and let the daemon re-register.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_CANCELLED",
            status.HTTP_409_CONFLICT,
            "The run was cancelled",
            "Somebody pressed cancel, or the node was shutting down.",
            "Dispatch the card again when you are ready.",
            origin=DAEMON,
        ),
        _entry(
            "RUN_INTERNAL_ERROR",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "The agent run failed for an internal reason",
            "Something went wrong inside the daemon's run path. The detail is in that "
            "node's log with the request id.",
            "Retry; if it persists, collect the daemon log around that run id.",
            retryable=True,
            origin=DAEMON,
        ),
        _entry(
            "AGENT_RUNTIME_MISMATCH",
            status.HTTP_409_CONFLICT,
            "That agent does not offer the runtime this card needs",
            "The named node reported no usable non-interactive interface for the "
            "runtime required — often because that CLI is installed but too old.",
            "Pick another agent, or update the CLI on that node and let it re-register.",
        ),
        # --- V2.5: clarification, decomposition and document patch proposals ---
        #
        # Twenty-three codes and no new HTTP shape: every refusal here is either "this
        # kind of card cannot do that" or "an agent may not decide that". The phase adds
        # no outward surface, so every entry below is about a boundary rather than a
        # failure (ADR 0034).
        _entry(
            "TASK_KIND_FORBIDS_SECRETS",
            status.HTTP_409_CONFLICT,
            "A clarification or decomposition card carries no secrets",
            "Neither kind needs a credential to read code and ask questions, so the "
            "declaration is refused at dispatch rather than honoured. Refused *before* "
            "the allowlist check on purpose: the fix is to clear the field, not to widen "
            "the project's allowlist.",
            "Clear the card's required secrets.",
        ),
        _entry(
            "TASK_KIND_DELIVERY_NOT_ALLOWED",
            status.HTTP_409_CONFLICT,
            "This kind of card can only deliver nothing or an artifact",
            "Clarification, decomposition and mockup cards produce no code change, so "
            "a branch or pull request would fail at delivery having spent a whole run.",
            "Set the card's delivery to `none` or `artifact`.",
        ),
        _entry(
            "TASK_KIND_NEEDS_REQUIREMENT",
            status.HTTP_409_CONFLICT,
            "This card is not linked to a requirement",
            "A clarification or decomposition run works *on* a requirement; without one "
            "there is nothing for it to read or to write back to.",
            "Dispatch it from the requirement's page, or set the card's requirement.",
        ),
        _entry(
            "TASK_MOCKUP_INTEGRATION_DISABLED",
            status.HTTP_409_CONFLICT,
            "This deployment has no tunnel integration, so it does not do mockups",
            "The mockup gate does not exist without a way to show a running preview "
            "(ADR 0022, D31). **Ordinary UI cards are unaffected** and so is attaching a "
            "screenshot as an artifact — what is missing is the governance gate.",
            "Enable the tunnel integration, or make this an ordinary implementation card.",
        ),
        _entry(
            "TASK_KIND_LOCKED",
            status.HTTP_409_CONFLICT,
            "This card has been run, so its kind is fixed",
            "Its specification versions, question thread and run log are explained by "
            "the kind it had; changing the kind afterwards would leave an implementation "
            "card that inexplicably produced a specification.",
            "Create a new card of the kind you want.",
        ),
        _entry(
            "TASK_KIND_MISMATCH",
            status.HTTP_409_CONFLICT,
            "This route serves a different kind of card",
            "`/spec` serves clarification cards and `/proposal` serves decomposition "
            "cards. The card's kind decides which writes it may make.",
            "Use the route matching this card's kind.",
        ),
        _entry(
            "QUESTION_ALREADY_PENDING",
            status.HTTP_409_CONFLICT,
            "The previous question has not been answered yet",
            "One question at a time. Five at once returns three answers and two the "
            "agent cannot tell were skipped. `details.pending_question` is the one "
            "waiting. Two *related* sub-questions in one message are allowed.",
            "Combine them into one message, or wait for a reply.",
        ),
        # --- V2-C1 conversation (ADR 0035/0036/0037) ------------------------
        #
        # Two of these should never be returned in a healthy deployment
        # (`CONVERSATION_CURSOR_AHEAD`, `TURN_ALREADY_QUEUED`). They are worth more as
        # alarms than as statistics, and their alert threshold is *greater than zero*.
        _entry(
            "QUESTION_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "That question is not on this card",
            "A question belonging to another card is reported as absent rather than as "
            "forbidden: 'not here' is true and says nothing about what exists elsewhere.",
            "Reload the card and answer a question listed on it.",
        ),
        _entry(
            "QUESTION_ALREADY_ANSWERED",
            status.HTTP_409_CONFLICT,
            "Somebody has already answered this question",
            "Two people replying to one question is a normal event in a team, not an "
            "error state. `details` carries who answered and when, so the client can "
            "show the answer rather than only the failure.",
            "Read the existing answer; add a comment if you have more to say.",
        ),
        _entry(
            "QUESTION_NOT_OPEN",
            status.HTTP_409_CONFLICT,
            "That question is no longer open",
            "A question that timed out is kept rather than deleted, so it can still be "
            "read — but answering it no longer starts a turn. `details.state` says "
            "which state it is in.",
            "Dispatch the card again, or ask a new question.",
        ),
        _entry(
            "RUN_NOT_WAITING_FOR_INPUT",
            status.HTTP_409_CONFLICT,
            "That run is not waiting for an answer",
            "A run that is queued, claimed or running has nothing to resume. Reaching "
            "this with an open question means Central failed to park the run when the "
            "question was asked, which is a defect rather than a user error — so it is "
            "reported instead of being papered over.",
            "Reload the card; if it persists, report it with the request id.",
        ),
        _entry(
            "CONVERSATION_CURSOR_AHEAD",
            status.HTTP_409_CONFLICT,
            "That conversation cursor is ahead of the card",
            "The caller's stored position is beyond anything this card has. Answering "
            "with an empty page would leave it stuck there permanently with no signal, "
            "so it is refused and `details.conversation_seq` says where the card is.",
            "Reset the cursor to the value in `details` and read again.",
            retryable=True,
        ),
        _entry(
            "MESSAGE_IDEMPOTENCY_CONFLICT",
            status.HTTP_409_CONFLICT,
            "That idempotency key was used for a different message",
            "A key identifies one message. Reusing it with different content would make "
            "the retry indistinguishable from a new message, which is the ambiguity the "
            "key exists to remove.",
            "Use a new key, or resend the original content.",
        ),
        _entry(
            "TURN_ALREADY_QUEUED",
            status.HTTP_409_CONFLICT,
            "A continuation for that answer already exists",
            "One answer creates at most one agent turn. This is enforced by a unique "
            "index rather than by a check, because the failure it prevents — the agent "
            "replying twice — has no other symptom.",
            "Wait for the existing turn; no second one is needed.",
        ),
        _entry(
            "MESSAGE_TOO_LARGE",
            status.HTTP_400_BAD_REQUEST,
            "That message is longer than a card message may be",
            "`details` carries the limit and the actual length. This is a distinct code "
            "rather than a generic validation failure because the right response to it "
            "is specific: the text is safe, it needs shortening.",
            "Shorten the message, or attach the long form as an artifact.",
        ),
        _entry(
            "AGENT_CANNOT_DECIDE",
            status.HTTP_403_FORBIDDEN,
            "Deciding is a person's action",
            "An agent may propose; accepting or rejecting a proposal requires "
            "`task.approve`, which a run credential never holds. The refusal is explicit "
            "so that it is legible and audited, rather than a generic denial.",
            "Post the content as a proposal and let a person decide.",
        ),
        # --- V2-K1 project memory (ADR 0038 / 0039) -------------------------
        #
        # Two of the six answer with **404 where 403 would be the obvious choice**, and
        # that is the whole design of this group: a 403 confirms that the thing exists
        # and you may not have it, which is precisely the disclosure project isolation
        # is for.
        _entry(
            "KNOWLEDGE_DISABLED",
            status.HTTP_404_NOT_FOUND,
            "This project has no memory",
            "Project memory is enabled per project, not per deployment, because a "
            "500-file project and a 50,000-file monorepo need different answers. The "
            "status is 404 rather than 403 on purpose: it does not disclose whether the "
            "project exists and has the feature switched off.",
            "Enable project memory in the project's settings (needs `project.manage`).",
        ),
        _entry(
            "SOURCE_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "That source is no longer available",
            "One of three things, and the message does not distinguish them because two "
            "of the three must not be distinguishable: the source was superseded or its "
            "original was deleted, the citation label belongs to an older context pack, "
            "or it belongs to another project. Answering 403 for the last case would "
            "confirm that it exists.",
            "Run `cliora knowledge context` again to get current citations.",
        ),
        # **`CROSS_PROJECT_DENIED` is deliberately absent**, and its absence is the
        # design rather than an omission. `plan/25` listed it, and every call site it
        # could have had turns out to be one where a 403 would disclose that an id
        # exists somewhere: a run token naming another project's repository, source or
        # card must be told 404. The only shape that discloses nothing would be a caller
        # naming its own project's boundary, and no endpoint lets a run token name a
        # project at all — the project comes from the token. A code with no site is a
        # code somebody eventually raises in the wrong place.
        _entry(
            "SOURCE_EXCLUDED",
            status.HTTP_409_CONFLICT,
            "Somebody excluded this source from this card",
            "An exclusion is per card and reversible, unlike a deletion. It exists so "
            "that one card can ignore a document without removing it from the other "
            "forty cards that cite it.",
            "Ask whoever excluded it, or cite a different source.",
        ),
        _entry(
            "CONTEXT_BUDGET_EXCEEDED",
            status.HTTP_409_CONFLICT,
            "This card's context cannot be assembled within its budget",
            "The pack is cut in a fixed order — retrieved sources first, then older "
            "conversation — and the project's rules and the open questions are never "
            "cut. Reaching this means those alone do not fit, which is a data problem "
            "rather than a load problem: silently truncating them would hand an agent a "
            "half-read question.",
            "Shorten the project's policy text, or split the card.",
        ),
        _entry(
            "KNOWLEDGE_SYNC_TOO_LARGE",
            status.HTTP_400_BAD_REQUEST,
            "This repository sync is over a limit",
            "`details.limit` names which one — files, bytes or rate — and carries the "
            "count and the ceiling. A single oversized file is skipped instead and "
            "reported in `skipped`, because losing a project's whole memory over one "
            "large CHANGELOG is the wrong trade.",
            "Narrow the sync with `.clioraignore`, or raise the project's repo_sync "
            "limits in its knowledge settings.",
            # Retryable in the sense the affordance means: the same call with a smaller
            # payload succeeds. The rate-limited variant is retryable on a clock.
            retryable=True,
        ),
        _entry(
            "SPEC_SECTION_UNKNOWN",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That specification section does not exist",
            "The nine section keys are closed so that two writers cannot invent two "
            "spellings of one idea. `details.allowed` lists them.",
            "Use one of the listed section keys.",
        ),
        _entry(
            "SPEC_VERSION_LIMIT",
            status.HTTP_409_CONFLICT,
            "This requirement has too many specification versions",
            "A backstop against a loop, not a design constraint: a real clarification "
            "converges in a handful of rounds.",
            "Approve the current version, or raise a new requirement.",
        ),
        _entry(
            "SPEC_QUESTION_AMBIGUOUS",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A question has both an answer and a known-unknown marking",
            "Either resolves it for the approval gate, so filling both lights the button "
            "while hiding which state it is in — and 'this is the answer' and 'we decided "
            "not to resolve this' are what a reviewer needs to tell apart.",
            "Keep the answer, or keep the known-unknown marking.",
        ),
        _entry(
            "PROPOSAL_EMPTY",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The proposal contains no tasks",
            "A decomposition with no cards is not a decomposition.",
            "Submit a tree with at least one task.",
        ),
        _entry(
            "PROPOSAL_TOO_LARGE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That is too many cards for one decomposition",
            "Not a granularity judgement — the server cannot make one — but a runaway "
            "backstop. Hitting it usually means the requirement should be split first.",
            "Split the requirement, or decompose one epic at a time.",
        ),
        _entry(
            "PROPOSAL_TREE_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The proposal tree does not hold together",
            "A duplicate id, or a parent or dependency pointing at a node that is not in "
            "the tree. Checked at submission rather than at acceptance, because a "
            "reference among unselected items would otherwise surface much later.",
            "Fix the named node and resubmit.",
        ),
        _entry(
            "PROPOSAL_TREE_CYCLE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The proposal's dependencies form a cycle",
            "`details.cycle` names the path. Naming it matters: 'there is a cycle' in a "
            "forty-node tree is not actionable.",
            "Break the cycle and resubmit.",
        ),
        _entry(
            "PROPOSAL_FIELD_FORBIDDEN",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A decomposition may not declare that field",
            "`required_secrets` is a person's decision on a card, not a proposal's. "
            "Refused rather than stripped, because stripping leaves the agent believing "
            "it declared something.",
            "Remove the field; a person adds secrets to the card afterwards.",
        ),
        _entry(
            "PROPOSAL_RISK_UNDERSTATED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "This card mentions a high-risk area but is not marked high risk",
            "Secrets, authentication, payments, migrations and infrastructure are stop "
            "condition 4. The term match is coarse on purpose and errs toward noise: an "
            "unnecessary badge costs one untick, a missed one puts a payments card in "
            "`ready` as low risk.",
            "Set the card's risk to high, or reword it if the match is wrong.",
        ),
        _entry(
            "PROPOSAL_REJECT_NEEDS_NOTE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Rejecting a proposal needs a reason",
            "The reason is the only signal that accumulates on this path: the next "
            "decomposition of the same requirement receives it as a negative example.",
            "Write why it was turned down.",
        ),
        _entry(
            "PROPOSAL_OVERRIDE_NOT_ACCEPTED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That field cannot be edited while accepting",
            "Either the item is not in this acceptance — an edit would then be applied "
            "silently at some later one — or the field is `readiness`, which would turn "
            "'a card missing readiness lands in backlog' into a rule that disappears.",
            "Select the item first, or edit the card after it is created.",
        ),
        _entry(
            "PATCH_PROPOSAL_NOT_FOUND",
            status.HTTP_404_NOT_FOUND,
            "Patch proposal not found",
            "The document patch proposal does not exist.",
            "Reload the project's proposals.",
        ),
        _entry(
            "PATCH_PROPOSAL_TARGET_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The patch proposal's target or sections are malformed",
            "The path must be repository-relative. The platform never opens it — the "
            "check is so that a person's review screen does not render something shaped "
            "like an attack.",
            "Use a repository-relative path and one of the four section keys.",
        ),
        _entry(
            "PATCH_PROPOSAL_TOO_LARGE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The patch is too large",
            "Refused at submission rather than truncated at render: a truncated diff "
            "looks complete, and a person decides on it.",
            "Split it into separate proposals per document.",
        ),
        _entry(
            "PATCH_PROPOSAL_ALREADY_DECIDED",
            status.HTTP_409_CONFLICT,
            "This patch proposal was already decided",
            "Accept and reject are one-shot; the row keeps who decided and when.",
            "Submit a new proposal if the document changed again.",
        ),
        _entry(
            "PATCH_PROPOSAL_REJECT_NEEDS_NOTE",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Rejecting a patch proposal needs a reason",
            "Same rule as a decomposition proposal: a rejection with no reason is "
            "indistinguishable from no row three months later.",
            "Write why it was turned down.",
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
