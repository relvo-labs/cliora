# Security review — system terminal (plan/08, ADR 0021)

Scope: the `shell` runtime and everything reachable through it. The workspace tab
work (WT-01 to WT-03) adds no data-plane surface and is not reviewed here.

**Evidence rule** (same as `docs/security-review-p4.md`). Every row names a test or
a file. "Implemented" is the claim, not the evidence. A partly-covered row says so
and the gap appears in [Findings](#findings) rather than being smoothed over.

**Why this review is not optional.** The automated scope guard for `SCOPE-011`
(`test_scope_guards.py::test_scope_011_the_front_end_cannot_name_a_command`) stays
green through this entire change, because the front end still names no command. A
reader of CI would conclude the capability was reviewed. It was not; it was decided
in ADR 0021 and checked here.

---

## 1. Attack table

| # | Attempt | Expected | Evidence | Verdict |
|---:|---|---|---|---|
| 1 | Non-owner with a valid ws-ticket connects to somebody else's shell | Handshake refused | `may_view_session` special-cases `runtime == "shell"` to owner-only and is the WS handshake gate (`app/api/ws/terminal.py:87`). `backend/tests/test_authz.py::test_nobody_but_the_owner_can_watch_a_shell` asserts it for all three roles | **pass** |
| 2a | Viewer posts `/api/sessions/{id}/shell` | 403 at the **action** layer, before the parent is loaded | `backend/tests/db/test_sessions_api.py::test_viewer_is_refused_at_the_action_layer` | **pass** |
| 2b | Developer opens a shell in a colleague's session | 403 at the **scope** layer | `test_a_developer_cannot_open_a_shell_in_someone_elses_session`; the Admin equivalent is `test_an_admin_cannot_open_a_shell_in_someone_elses_session`. This is the load-bearing one now that Developer holds `terminal.shell` (D7) | **pass** |
| 3 | Role demoted between minting the ticket and connecting | Refused | The handshake re-checks against the loaded user rather than trusting the ticket (`ws/terminal.py:87`, unchanged by this work); write eligibility is re-checked per keystroke (`:177`) | **pass (inherited)** |
| 4 | Node has disabled the shell; Central is asked anyway | 409 `RUNTIME_NOT_FOUND`, and the daemon refuses independently | `test_a_node_that_disabled_the_shell_refuses_it`; daemon side `daemon/internal/config` (`TestShellRuntimeDisabledIsNotOverwrittenByTheDefault`) proves the operator's `enabled: false` is not re-enabled by the new default | **pass** |
| 5 | A frame names a binary alongside `runtime: "shell"` | Rejected identically by all three consumers | `contracts/v1/fixtures/invalid/session-start-shell-with-binary.json` via `make contract` (Python schema, Go codec, TypeScript decoder) | **pass** |
| 6 | Full shell lifecycle, then read the audit trail, logs and metrics | No terminal bytes, no command strings, no binary path | Only session-level events are written, with `runtime` in the metadata (`services/sessions.py`); `FORBIDDEN_METADATA_KEYS` and `test_audit_redaction.py` are unchanged and still apply. **This is a deliberate observability gap, not coverage**: commands are not recorded at all (ADR 0021 §5) | **pass, with a stated gap** |
| 7 | `terminal.control_acquire` against a shell session | Dropped | `may_takeover_session` returns `False` for any shell; `backend/tests/test_authz.py::test_a_shell_cannot_be_taken_over`. The WS control handler gates on that predicate (`ws/terminal.py:221`) | **pass** |
| 8 | Use a shell session id on the filesystem endpoints | 403 | `may_browse_files` returns `False` for a shell; `test_a_shell_session_id_is_not_a_route_to_the_filesystem_relay`. Closes the lateral route to the same data under a different owner check | **pass** |
| 9 | Browser killed without sending anything | Terminated after the idle window | `services/shell_reaper.py`; `backend/tests/test_shell_reaper.py` covers reap, reattach-saves-it, flap-cannot-extend, and CLI-is-never-reaped | **pass** |
| 10 | Daemon execution identity | Non-root | `config.EnsureNonRoot()` from `daemon/cmd/agentd/run.go`, `User=` in `internal/install/systemd.go` (both pre-existing, unchanged). Carried into deployment as a tick in `docs/release-checklist.md` §4.5, because code cannot check how an operator edited a unit file | **pass — and now load-bearing** |
| 11 | A shell inside a shell | Refused | `may_open_shell` returns `False` for a shell parent; `test_a_terminal_cannot_be_opened_inside_a_terminal` | **pass** |
| 12 | Two terminals in one session (double click, stale tab) | Second refused, and the database refuses it too | `SHELL_ALREADY_OPEN` (`test_a_second_terminal_for_the_same_session_is_refused`) plus the partial unique index in migration `0013` | **pass** |

## 2. The one that matters most

Row 10 is not a checkbox. **The shell escalates nothing** — it exposes the privileges
the daemon already holds as an interactive surface. Every other control in this table
bounds *who* reaches that surface; none of them bounds *what it can do*. The daemon's
execution identity is therefore the ceiling of the entire feature.

Consequence to carry forward: if `agentd` is ever run as root — by a packaging change,
an operator working around a permission problem, or a future feature that "needs" it —
the risk class of this feature changes silently, and nothing in CI will say so. That is
recorded in ADR 0021 §4 and repeated here on purpose.

## 3. Findings

### Finding 1 — the scope guard cannot see this change

`test_scope_011_the_front_end_cannot_name_a_command` passes before and after. The
property it tests (no command on the wire) is still true and still worth testing; it
simply does not cover the capability that was added. **Not a defect in the test** — a
limit of what an automated guard can express about scope. Mitigation: `SCOPE-011.AC-01`
is now `lifecycle: deprecated` with a `supersedes` link from `FR-SHELL-001.AC-03` and a
recorded rationale, so the next reader finds the decision from the registry rather than
from a green tick.

### Finding 2 — permissive defaults concentrate the risk on ownership

D6 and D7 (2026-07-31) put `terminal.shell` in Developer's hands and enable the runtime
by default, including on nodes that upgrade into it. Neither is a defect; both were
decided in the open. The consequence is that scarcity of access is no longer a control,
so rows 1, 2b, 7, 8 and 10 carry the whole boundary. Each has its own test, and 2b has a
test distinct from 2a specifically because they fail at different layers and one passing
does not imply the other.

### Finding 3 — a shell survives its watcher for up to 15 minutes

`shell_idle_terminate_seconds` defaults to 900. Between a browser crash and the reap, an
unattended shell exists on the node. This is a deliberate trade against reload/suspend
churn, not an oversight; it is tunable per deployment, and the value should be revisited
once there is real usage data.

## 4. Not covered here

- **Real-node end-to-end — partly closed.** Every row in the table above is
  exercised against a fake registry or a unit boundary. The happy path is no longer:
  `frontend/tests/e2e/session.spec.ts` opens a TERMINAL tab on a node running a real
  `bash`, runs a command, reads the output back through the relay, and asserts that
  closing the tab ends that session — executed on Chromium and Firefox. What remains
  uncovered end-to-end is the **refusal** paths (rows 1, 2a, 2b, 4, 7, 8): those are
  asserted at the API and authz boundary only, because provoking them through a
  browser needs a second user and a second node that the stack does not stand up.
  WebKit is CI-only (its system libraries need root).
- **Terminal content.** By construction: it is never persisted, so there is nothing to
  review. That is also why there is no audit answer to "what did they run".
