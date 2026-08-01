# ADR 0023 — Privileged node posture: no sandbox, sudo, and a terminal that scrolls

- Status: accepted
- Date: 2026-08-01
- Amends: ADR 0021 §4.2 item 2 (the "non-root daemon" compensating control). ADR 0021 is
  not superseded — its ownership, lifetime and audit controls stand unchanged.
- Related: ADR 0004 (terminal bytes are never persisted), ADR 0011 (installer and unit),
  ADR 0012/0013 (session recovery and lifecycle), ADR 0017 (update health check runs as the
  service user), ADR 0022 (third-party tunnel; its credential lives in the node's `ssh` argv)
- Requirements: `SEC-007.AC-02/AC-03`, `FR-RUNTIME-003.AC-02`, `FR-RUNTIME-004.AC-02/03/04`,
  `FR-SHELL-001.AC-09`, `FR-TERM-004.AC-06/AC-07`
- Contract: v1.7.0
- Plan: `plan/12/`

## Context

Three changes were asked for on 2026-08-01, together with the reason:

> agentd 上的 codex 預設要帶 `--dangerously-bypass-approvals-and-sandbox` 參數執行，
> 我們已經做了 vm 隔離我不擔心 vm 壞掉，壞掉就再做一個就好，terminal 現在不能上下 scroll
> 要修正，且 terminal 要開放 sudo 才行。

### The premise, written down because it is doing the work

**A Cliora node is a disposable, isolated VM. Damage to one is repaired by rebuilding it,
not by recovering it.** Everything below follows from that, so it is recorded as the
premise rather than smuggled in as a mitigation. Two consequences:

- Destruction *inside* a node moves from the risk list to the accepted-cost list. There is
  no point inventing a control whose only job is to protect something the owner is willing
  to throw away.
- Effects that cross the VM boundary — other nodes, other tenants, Central — stay on the
  risk list. The premise covers a machine, not the platform.

**If the premise does not hold** — someone installs agentd on a machine they would not
rebuild — the posture must be refused per node: install with `--no-privileged-terminal`
and set `runtime.codex.sandbox_bypass: false`. That is the only place this decision is
adjustable, and it is on the node, not in the console.

### The three changes are one change

Read separately, each looks like a convenience: a CLI flag, a scroll fix, a sudoers line.
Read together they are a change of posture:

| | before | after |
|---|---|---|
| service identity | non-root | **non-root (unchanged)** |
| ceiling of the system terminal | the service user | **root, one `sudo` away** |
| codex | approvals + OS sandbox | **neither** |
| tmux environment | the node owner's default server | **owned by the daemon** |

The scroll fix belongs in this ADR because it is what forced the tmux environment to
become the daemon's: the fix is a tmux option, and setting options on a server shared with
the node owner's own sessions would change their environment without asking.

## Decision

### 1. codex launches without approvals or a sandbox, by default

The daemon adds `--dangerously-bypass-approvals-and-sandbox` when starting `codex`.

The flag lives in a compile-time table in the daemon (`daemon/internal/runtime/launch.go`).
The node's only control is a boolean, `runtime.codex.sandbox_bypass`; absent means enabled,
matching how `runtime.shell` defaults in ADR 0021 — an upgraded node takes the posture
without an operator editing a file. That is a capability change, so `Load` records whether
the value came from the file or the default, and the daemon logs which on the way up.

**Rejected: a free-form `args`/`argv` field in the config or on the wire.** It moves the
decision about what a node executes into a string somebody else can write, and the obvious
next step ("let an Admin set it in the console") would look like relocation rather than a
scope change. `RuntimeConfig` has no argv field on purpose; `session.start` stays closed
over its five fields with `additionalProperties: false`.

### 2. `SCOPE-011` was not narrowed again

The half ADR 0021 §1 kept is still true and still enforced end to end: **the front end and
Central never name a command, binary, argv, environment or entrypoint.** The daemon adds a
flag of its own; nobody else contributes a string to it.

This is asserted rather than asserted-in-prose:

- `contracts/v1/fixtures/invalid/session-start-with-args.json` — a launch flag on
  `session.start` is rejected by Python, Go and TypeScript alike.
- `contracts/v1/fixtures/invalid/session-start-with-sandbox-request.json` — so is *asking
  for a posture*. That is the shape the next request will take ("just for this session"),
  and the first fixture alone would not catch it.
- `backend/tests/test_scope_guards.py` — `session.start` has exactly five properties, and
  the posture fields exist only on node → Central announces.
- `scripts/pv/check-no-argv-channel.sh` (`GATE-PV-ARGV-CHANNEL`) — no schema, config struct
  or Central payload grows an argv-shaped field, and the flag constant is declared exactly
  once.

ADR 0021 §Context recorded what the previous scope change looked like from CI: green tests,
unchanged coverage, an untouched release gate. Adding a flag table would look exactly the
same. Hence this document, and hence a gate whose only job is to notice the next attempt.

### 3. The reported posture is measured, never assumed

`runtime-item.sandbox_bypass` reports what the runtime **will actually be launched with**.
Detection probes `codex --help` once for the flag; a build that does not accept it is
launched without it and reported as `enforced`, with a `[warn]` in `agentd doctor`.

Both simpler options are wrong in opposite directions. Reporting the *configured* value
makes the console claim a posture the machine is not in — the user then attributes codex's
prompts to the wrong cause. Refusing to start a session when the flag is unsupported turns
one third-party CLI upgrade into a fleet-wide outage. The flag is somebody else's
interface; it can be renamed.

### 4. sudo: non-root, but able to escalate

The privileged posture is two things on the machine:

1. the systemd unit does **not** set `NoNewPrivileges=true`, and
2. `/etc/sudoers.d/60-agentd` grants the service user `ALL=(ALL) NOPASSWD:ALL`.

`config.EnsureNonRoot()` stays exactly where it is: the daemon still refuses to run as
root, in `run` and in `doctor`.

`NoNewPrivileges=true` is the real gate — `no_new_privs` disables setuid, so sudo cannot
work while it is set, whatever sudoers says. It is commented out with an explanation rather
than deleted, because a hardening directive that simply vanished reads as an oversight; the
next reviewer restores it and the symptom is "sudo stopped working" with nothing pointing
at the change.

**Rejected: `User=root`.** It would void `EnsureNonRoot`, the update health check's whole
notion of "readable by the service user" (ADR 0017), and workspace file ownership — and it
would remove the one thing sudo gives us that root does not: a record. Every escalation
lands in the node's `auth.log`.

**Rejected: a command allowlist.** Inside a shell that can already run anything, an
allowlist either contains `sudo bash` — full access plus a list that rots — or does not,
in which case the first user who needs a package edits it to full access, unreviewed. And
`NOPASSWD` is not laziness: the service account generally has no password to type, and
codex in bypass mode runs `sudo` unattended, where a prompt hangs it until timeout and
presents as "codex is stuck" rather than "codex lacks permission".

`agentd posture` is the supported way to apply or revoke this on an already-installed node.
It is deliberately *not* reachable from Central: a remotely triggered command that could
change the unit would be a remotely triggered command that could grant root. `agentd
update` still replaces only the binary.

### 5. What ADR 0021's compensating controls look like now

ADR 0021 §4.2 item 2 said: *"the shell escalates nothing; it exposes the privileges the
daemon already has… The daemon's execution identity **is** the ceiling of this feature. If
that ever becomes root, the risk class of this ADR changes and it must be revisited."*

**The execution identity did not become root. The ceiling did.** In effect this is the
situation that item predicted, so it is revisited here and that item no longer holds.

Still standing from ADR 0021 §4:

1. **Ownership** — a user may open a shell only in a session they own, and nobody, Admin
   included, may attach to someone else's.
2. **Bounded lifetime** — a shell dies with its parent CLI session, with its watcher, and
   with the idle reaper.
3. **Session-level audit** — create / attach / terminate, with the runtime recorded.

Replacing item 2, two new controls:

4. **The posture is visible.** Nodes list, node detail, the session header and the system
   terminal's own notice all state it, and `session.create` audit metadata carries
   `sandbox` and `privileged` as they were **at the moment the session started**. When the
   compensating control is gone, what is left to offer the user is knowing which boundary
   they are inside — so it is a first-class part of the product, not a tooltip.
5. **The node's own veto.** `--no-privileged-terminal` and `sandbox_bypass: false`, both on
   the machine, neither reachable from the platform.

### 6. Records: what sudo leaves, and what we still do not keep

- The platform does **not** record terminal input or output. ADR 0004 and `TECH-SEC-08` are
  unchanged, and this ADR trades nothing away there.
- sudo writes every escalation to the node's `auth.log` / journal: which user, when, what
  command. This is the **operating system's** record, not the platform's — Central does not
  read it, collect it, or relax any privacy statement because of it.
- Its value is narrow and worth stating: under ADR 0021 §5 (commands are not recorded) it is
  the only thing that exists at all if someone later has to reconstruct what happened on a
  node. Its two limits are equally worth stating: it disappears when the VM is rebuilt (a
  direct consequence of the premise), and it records sudo invocations, not terminal content.

### 7. Scrollback has two tracks, and only one of them is scrollable

Measured on 2026-08-01 (tmux 3.2a, `@xterm/xterm` 5.5.0):

- `tmux attach` emits `ESC[?1049h` immediately: the client runs on the **alternate
  screen**, where xterm.js has no scrollback of its own.
- tmux then emits `ESC[?1000l ESC[?1002l ESC[?1006l` — it **disables** mouse reporting by
  default. xterm.js therefore takes the `!buffer.hasScrollback` branch and translates the
  wheel into **arrow keys**. That is why scrolling up in a shell session walked the shell's
  command history: the terminal was not failing to scroll, the scroll was being turned into
  something else.
- With `mouse on`, tmux emits `ESC[?1002h ESC[?1006h`, xterm.js forwards SGR mouse events,
  and the wheel drives tmux copy mode. No xterm.js code changes.
- tmux's default `history-limit` is **2000**. `session.scrollback_limit: 5000` had been
  written into every generated config since P1 and read by nothing, so
  `FR-TERM-004.AC-04` ("at least 5000 lines") was not met on any node. It is now wired to
  the generated tmux config, and the config's floor is the requirement's.

So: **tmux's history is the scrollback the user can see.** The 2 MiB reattach snapshot
lands in xterm.js's *normal* buffer and is immediately covered by the alternate screen — it
is a continuity mechanism at reconnect, not a way to look at history, and
`FR-TERM-004.AC-07` now says so. Recorded because the next person to work on scrollback
will otherwise start by changing the snapshot size, which is a road that looks right and
goes nowhere.

**Rejected: `terminal-overrides ',*:smcup@:rmcup@'`** (stop tmux using the alternate
screen so xterm.js's own scrollback fills). Full-screen TUIs — claude, codex — repaint
constantly, and every repaint would pour a screenful of noise into the scrollback.

**Rejected: a console-side "scroll mode" button** sending copy-mode keys. Several hundred
lines of front end to reimplement something tmux already has.

### 8. The tmux environment belongs to the daemon

Sessions move to a dedicated socket (`-L cliora`) with a generated config
(`/run/agentd/tmux.conf`, via the unit's `RuntimeDirectory=agentd`). Before this, production
used tmux's default socket — the node owner's own server — where `mouse on`, `status off`
and `history-limit` would have been changes to *their* environment, arriving unannounced.

The cost is real and one-off: **a tmux session belongs to its server, so the upgrade that
introduces this ends the sessions that were running.** They cannot be moved. The daemon
scans the old socket at startup, logs what it finds, and surfaces it in `doctor`; it kills
nothing. This is a one-time exception to the recovery promise in ADR 0004 and it goes in
the release note, not in a footnote.

`mouse` and `status` are re-applied per session, which repairs a server that predates the
config. `history-limit` cannot be repaired that way — a pane reads it at creation — so on
such a server the scrollback depth stays as it was until the last session ends. That gap
is in the runbook rather than papered over.

**Trade-off the user will notice, and the only regression in this change:** with mouse
reporting on, drag-select belongs to tmux. Browser-native selection now needs **Shift +
drag** (xterm.js forces selection when Shift is held). Note it is Shift + *drag*: xterm.js
ignores a wheel event with Shift held, so "Shift to scroll" would be wrong advice. Both
sentences are printed under the terminal, because neither is discoverable and a release
note is not re-read.

**Not adopted: OSC 52 clipboard integration** (`@xterm/addon-clipboard` plus
`set-clipboard on`), which would let a tmux copy-mode yank reach the browser clipboard. It
also lets remote content write to a user's system clipboard, which is a new surface and
deserves its own decision rather than a seat on this one.

## Consequences

- Contract **v1.7.0** (compatible): `runtime-item.sandbox_bypass` and
  `node-register.privileged_terminal`, both optional, both report-only. No new error codes:
  an unsupported flag is not an error and neither is an unprivileged node.
- `nodes.privileged_terminal` (indexed) and `node_runtimes.sandbox_bypass`, migration
  `0017`. Indexed because "which of my nodes can reach root from a browser" is a
  fleet-level question.
- New audit action `node.posture_changed`, written only when the reported posture actually
  changes — a reconnect is not a change, and one row per reconnect would bury the ones that
  matter.
- `session.create` audit metadata gains `sandbox` and `privileged`, snapshotted at start.
  `shell` and `fake` report `sandbox: "n/a"`: they have no sandbox to bypass, and
  `enforced` would be a false statement in a record whose only purpose is to be trusted
  later.
- **RBAC is unchanged.** No `terminal.privileged` action: `terminal.shell` already decides
  who may open a terminal, and no action can decide whether `sudo` works inside one. If a
  future requirement needs both postures for different users on the same machine, the
  answer is two nodes, not an action that cannot be enforced.
- **Upgrading a node grants it the codex posture** (absent `sandbox_bypass` means enabled),
  and reinstalling grants the sudo posture unless refused. Both need the release note and
  the runbook, not silence — the same rule ADR 0021 set for the shell runtime.
- `agentd` 0.5.0 ships all of this; `agentd posture` is new; `agentd doctor` reports the
  sandbox flag, the tmux socket and scrollback, `no_new_privs`, sudo, and any disagreement
  between what the config reports and what the machine does.
- `.agent/skills/cliora-project-context` and `go-daemon-development` are amended: their
  invariant lists said "preserve native Claude/Codex terminal semantics" and "run non-root",
  which after this ADR would be read as instructions to undo it.
