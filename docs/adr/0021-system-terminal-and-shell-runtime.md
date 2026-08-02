# ADR 0021 — System terminal (`shell` runtime)

- Status: accepted (§4.2 item 2 amended by ADR 0023, 2026-08-01)
- Date: 2026-07-31
- Supersedes: narrows `SCOPE-011` ("使用者不得從前端執行任意 Shell Command"). The
  non-goal is not withdrawn — see §Decision 1 for exactly which half of it survives.
- Related: ADR 0004 (terminal bytes never persisted), ADR 0012 (browser-independent
  sessions), ADR 0013 (session lifecycle), ADR 0014/0015 (filesystem confinement and
  read-only preview policy), ADR 0016 (RBAC action layer vs resource scope)
- Plan: `plan/08/`

## Context

The Session Workspace gives a user one thing on a node: a CLI runtime in a tmux
session, plus a read-only view of the workspace files. Anything else — `git status`,
reading a log that is not in the workspace, installing a dependency the CLI asked
for — means leaving the browser and finding another way onto the machine. In practice
that means the product's own boundary is routed around by SSH, which is worse than the
boundary being drawn somewhere honest.

This ADR adds an interactive shell as a third centre-pane tab. It is the first data-plane
capability since the MVP that can leave the workspace directory, so it is recorded as a
scope change rather than a feature.

**The automated guard does not catch this.** `SCOPE-011.AC-01` is verified by
`backend/tests/test_scope_guards.py::test_scope_011_the_front_end_cannot_name_a_command`,
which asserts that `session.start` is closed over five fields and that none of `command`,
`args`, `argv`, `shell`, `env` or `entrypoint` exists on the wire. Adding a `shell` value
to the `runtime` enum leaves that test green, coverage unchanged and the release gate
untouched. Anybody reading CI would conclude the change was reviewed. It was not — it was
decided, in the open, here.

## Decision

### 1. `SCOPE-011` is narrowed, not withdrawn

The half that survives, and is still enforced end to end: **the front end never names a
command, binary, argv, environment or entrypoint.** It sends a runtime id; the node
resolves the binary from its own `config.yaml`. `session-start.schema.json` keeps
`additionalProperties: false`, and a golden invalid fixture asserts that a frame carrying
`binary`/`command` alongside `runtime: "shell"` is rejected by all three consumers.

The half that is given up: the user can now run arbitrary commands *inside* an
allowlisted shell, on nodes that have not disabled it.

Withdrawing the whole non-goal was rejected. It would discard a property that is still
true, still tested and still doing work.

### 2. The shell is a runtime, not a second channel

`shell` joins the runtime allowlist and flows through the existing session pipeline.
`daemon/internal/session/manager.go:78` — `StartSession(id, runtimeID, workspace, binary,
rows, columns)` — is already runtime-generic, and everything above it keys on session id:
ws-ticket minting, the relay hub, single-writer arbitration, the 2 MiB reattach snapshot,
the two-stage graceful→forced stop, and the audit events.

A separate shell channel was rejected: it would require a second implementation of every
one of those, which is the same as maintaining a second security boundary and hoping the
two agree.

Making the shell a second tmux window inside the CLI session was also rejected: the
filesystem relay resolves a workspace from a session id (`manager.go:168`), and one row
cannot carry two lifecycles.

### 3. What it bypasses

Stated plainly, because a compensating control can only be judged against the real list.

| Existing control | Still effective for a shell session? |
|---|---|
| Allowed-root prefix authorization (`app/services/sessions.py:58`) | **Only at launch.** The cwd is a legal workspace; `cd ..` is not prevented |
| Per-operation canonicalization (`TECH-SEC-05`) | Effective for the filesystem relay; **irrelevant inside the shell** |
| Read-only preview, sensitive-file refusal (`TECH-SEC-09`) | Effective for preview; **`cat` inside the shell is unrestricted** |
| `SEC-002` — front end names no command | **Effective** (§1) |
| `TECH-SEC-08` — terminal bytes never logged | **Effective**, and deliberately not traded away (§5) |
| Daemon runs non-root | **Effective, and now load-bearing** (§4) |

### 4. Compensating controls

The defaults chosen on 2026-07-31 are permissive — `terminal.shell` is held by Admin *and*
Developer, and the runtime is enabled by default on a node — so the boundary is carried by
these four, not by scarcity of access:

1. **Ownership.** A user may open a shell only in a session they own, and **no other user,
   Admin included, may attach to it.** `may_view_session`, `may_write_session`,
   `may_takeover_session` and `may_browse_files` all special-case `runtime == "shell"`.
   Terminate is the one asymmetry: an Admin may kill an orphan shell they cannot watch.
2. **Non-root daemon.** The shell escalates nothing; it exposes the privileges the daemon
   already has as an interactive surface. The daemon's execution identity *is* the ceiling
   of this feature. If that ever becomes root, the risk class of this ADR changes and it
   must be revisited.
3. **Bounded lifetime.** Bound to a parent CLI session (DB-level partial unique index),
   terminated when the tab closes or the parent ends, and reaped by an idle timeout when
   neither happens.
4. **Session-level audit.** Create / attach / terminate are recorded with `runtime` in the
   metadata, so the trail answers "who opened a shell, on which node, when".

A node may still set `runtime.shell.enabled: false`. That is a veto, not the default
posture, and must not be described as the first line of defence.

### 5. Commands are not recorded

Rejected: logging shell input for auditability. It contradicts ADR 0004 and `TECH-SEC-08`,
and the first thing such a log would capture is a password typed at a prompt. The audit
trail records that a shell existed, not what was typed in it. This is a deliberate,
documented gap in observability, not an oversight.

### 6. A shell dies with its watcher; a CLI session does not

`FR-SESSION-006` requires a CLI session to survive a browser disconnect — that is the
product's core promise. A shell does the opposite: when the last subscriber goes away it is
terminated after `shell_idle_terminate_seconds`.

The two behaviours are opposite **on purpose**. A long-running CLI session has value while
nobody is watching; an unattended root-adjacent shell has only risk. Recorded here so that
the difference is not later "fixed" into consistency.

### Amendment (2026-07-31): "already open" is decided by who is watching, not by the row

The first implementation shipped the three layers of §4.3 as three *statements* and
only two of them as code. `FR-SHELL-001.AC-08` says a terminal ends when the user
closes it **or leaves the workspace**; only the close was wired. Leaving has three
distinct exits and no single hook covers the others — in-app navigation (unmount),
reload / tab close (`pagehide`, and the request must be `keepalive` or it dies with
the document), and a route-param change that *reuses* the component. So a reload left
the shell running, the front end forgot its id, and the next open was refused with
`SHELL_ALREADY_OPEN` for up to `shell_idle_terminate_seconds` — with no closable tab,
because the close affordance keyed off the state the reload discarded.

The backstop could not save it either: the idle reaper's timers are process memory
armed only by a WebSocket teardown, so a restart (`cancel_all`) or a disconnect that
happened while Central was down left a live shell with nothing to collect it, and a
failed reap (offline node) was written off after one attempt.

Three changes, all of which keep one live shell per CLI session:

1. All three exits terminate the shell, so the cooperative layer is now real rather
   than aspirational.
2. On a second open, the **relay's subscriber list** decides which meaning of
   "already open" applies: someone watching → `SHELL_ALREADY_OPEN`, and the message's
   "return to the tab holding it" is then literally true; nobody watching → the row is
   one the browser failed to report, so the reaper's work is done on demand (audited
   with `reason: abandoned`) and a fresh terminal opens. This is not a relaxation of
   §4.3 — the invariant is the same evidence the reaper already acts on, applied when
   there is a caller to answer instead of only on a timer.
3. The reaper retries a bounded number of times, and re-arms its timers at startup for
   every shell the database says is live.

What is deliberately *not* adopted: handing the existing shell back to the new caller
(reattaching to it). §6 says an unattended shell has only risk, so it is ended, not
inherited — a reload gets a new terminal, not the old one's scrollback.

## Consequences

- Contract **v1.5.0**: `runtime` gains `shell` in `session-start.schema.json` and
  `runtime-item.schema.json`. Payload shapes are unchanged — no field is added anywhere.
- A new RBAC action `terminal.shell` (Admin + Developer) and a new resource-scope rule set;
  `docs/permission-matrix.md` is regenerated from `ROLE_ACTIONS`.
- `terminal_sessions.parent_session_id` plus a partial unique index enforcing one live
  shell per CLI session.
- Shell sessions count against `sessions_per_node_max` and `sessions_per_user_max`; they are
  hidden from the Sessions list (they are a view of a CLI session, not a work item) but
  counted honestly everywhere capacity is reported.
- **Upgrading an existing node grants it this capability**, because an absent
  `runtime.shell` block is treated as enabled. This is a capability change and must ship
  with a release note and a runbook entry, not silently.
- `SCOPE-011.AC-01` becomes `lifecycle: deprecated` with a `supersedes` link from
  `FR-SHELL-001.AC-03`; the scope-guard test stays, because the property it tests is still
  required.

## Amendment (2026-08-01, by ADR 0023): the second compensating control no longer holds

§4.2 item 2 said the daemon's execution identity **is** the ceiling of the system terminal,
and that if it ever became root this ADR must be revisited. It has been revisited.

The execution identity did **not** become root — `EnsureNonRoot` is unchanged and the
service still runs as the non-root user. The *ceiling* did: on a node installed with the
privileged posture, the unit omits `NoNewPrivileges` and `/etc/sudoers.d/60-agentd` grants
the service user passwordless sudo, so the terminal reaches root on demand (ADR 0023 §4).
In effect this is the situation item 2 predicted, and that item is therefore withdrawn.

Items 1, 3 and 4 of §4.2 — ownership, bounded lifetime, session-level audit — stand
unchanged, as do §1 (`SCOPE-011` is narrowed, not withdrawn; ADR 0023 §2 did not narrow it
further), §5 (commands are still not recorded) and §6 (a shell dies with its watcher).

Two controls replace item 2: the posture is **visible** wherever a user is about to work
(node list, node detail, session header, the terminal's own notice, and the `session.create`
audit metadata), and the **node keeps a veto** it can exercise without the platform
(`--no-privileged-terminal`, `runtime.codex.sandbox_bypass: false`). See ADR 0023 §5.

One line of this ADR's own text is now wrong if read literally: §4.2's "the shell escalates
nothing; it exposes the privileges the daemon already has". On a privileged node the shell
escalates, deliberately.
