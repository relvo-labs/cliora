# Security review — privileged node posture (plan/12, ADR 0023)

- Date: 2026-08-01
- Scope: `agentd` 0.5.0, contract v1.7.0, migration `0017`
- Change under review: codex launches with its approvals and sandbox disabled by default;
  the system terminal can reach root through sudo; Cliora's tmux environment moved to a
  daemon-owned socket with mouse reporting on
- Related reviews: `security-review-p8.md` (the system terminal itself),
  `security-review-p11.md` (the third-party tunnel)

## 1. What this change actually alters

| | before | after |
|---|---|---|
| service identity | non-root | **non-root (unchanged, `EnsureNonRoot` intact)** |
| ceiling of a session on the node | the service user | **root, via `sudo`** |
| codex | approvals + OS sandbox | **neither** |
| who may name a launch argument | nobody outside the node | **nobody outside the node (unchanged)** |
| who may set a node's posture | — | **only the machine's own files** |

The premise, from the requester and recorded in ADR 0023 §Context: a node is a disposable,
isolated VM; damage inside one is repaired by rebuilding it. This review does not re-argue
that premise. It checks that the change is confined to what the premise covers, and that
everything outside it still holds.

## 2. Accepted risks (stated as accepted, not as mitigated)

1. **Arbitrary code execution and privilege escalation inside a node.** Accepted. Any user
   holding `terminal.shell` on a session they own can become root on that machine, and codex
   can modify anything the machine holds without asking. This is the requested posture.
2. **Node-local secrets are readable by whoever holds a terminal.** Unchanged rather than
   accepted-anew: `credentials.yaml` (0600) and the tunnel credential in an `ssh` argv
   (ADR 0022 D18) were already readable by processes running as the service user, and a
   terminal has always run as that user. Root adds nothing here.
3. **Node-local audit disappears with the VM.** sudo records escalations in the node's
   `auth.log`; rebuilding the VM discards it. Accepted, and a direct consequence of the
   premise.

## 3. What must still hold, and why it does

### 3.1 The platform cannot choose a node's posture

Checked, three ways:

- **Schema.** `sandbox_bypass` and `privileged_terminal` appear only on `runtime-item` and
  `node-register` — messages the *node* produces. No Central-authored message
  (`session.start`, `daemon.update`, `tunnel.open`, `terminal-size`) carries either, nor
  `args`/`flags`/`sandbox`; asserted by
  `test_scope_011_the_posture_fields_are_report_only`.
- **Code.** The daemon's posture comes from `config.yaml`, the systemd unit and the sudoers
  drop-in. `agentd posture` is the only writer and it is a root-run CLI command, deliberately
  not reachable from `daemon.update` (which carries a version and nothing else, ADR 0017).
- **Gate.** `GATE-PV-ARGV-CHANNEL` fails on any new argv-shaped or posture-setting property
  in a schema, config struct or Central-built payload, and on the flag constant being
  declared more than once. Verified to fail when a field is injected.

**Finding: none.** A compromised Central can start sessions on a node (as before) but cannot
make a node privileged, cannot add a launch flag, and cannot turn a sandbox off.

### 3.2 The console does not claim a posture the machine is not in

`sandbox_bypass` is probed from the installed binary (`codex --help`) rather than read from
config, so a node whose CLI does not accept the flag reports `enforced` — which is what will
happen at launch. The alternative (report the request) would be a false statement in the one
place the user checks before typing.

Verified by `TestUnsupportedFlagIsReportedNotAssumed` and the console tests in
`NodeDetailPosture.test.ts`, including the case where a node reports no codex at all.

**Residual gap (accepted, documented):** the probe runs once per daemon process. A codex
upgrade that removes the flag is reflected after the next daemon restart or reconnect, not
immediately. Recorded in the runbook §3.

### 3.3 The node keeps a veto the platform cannot override

`--no-privileged-terminal` / `agentd posture --privileged-terminal=false` and
`runtime.codex.sandbox_bypass: false`, both on the machine. `GATE-PV-ARGV-CHANNEL` also
fails if either veto disappears from the code, because a posture with no opt-out is a
different decision from the one that was approved.

### 3.4 Writing sudoers cannot brick the machine

This is the only operation in the change that can leave a machine unable to repair itself.
Controls, in order: the user name is validated against a POSIX pattern before anything is
written; the file is written to a temp file in the same directory; `visudo -c` must accept
it; installation is an atomic rename; `sudo -n true` must then succeed for the service user;
if it does not, the previous file is restored — and if the restore fails, the error says so
instead of claiming a rollback. Missing `visudo` is a refusal, not a warning.

Verified by `sudoers_test.go` (rejected names, mode 0440, nothing left behind on a rejected
file, refusal without a validator, rollback and restore). All tests run against an injected
path and validator, so the suite never touches the real `/etc/sudoers.d`.

**Note on `NOPASSWD:ALL`:** an allowlist was rejected (ADR 0023 §4) because inside a shell
that can run anything it is either equivalent to full access or gets edited to full access
unreviewed. This review agrees, and adds: `NOPASSWD` is also what keeps codex from hanging
on an invisible password prompt, which would present as a product bug rather than a
permission boundary.

### 3.5 The escalation surface is wider than the terminal

Dropping `NoNewPrivileges` applies to the whole service cgroup, not just the shell runtime.
Anything the daemon starts — codex, claude, their child processes, the tunnel's `ssh` — can
also escalate on a privileged node. This follows from the requested posture and is not
separable from it: a shell that can sudo is a service user that can sudo. Stated here
because a reader could otherwise assume the grant is scoped to the terminal.

### 3.6 Terminal content is still not recorded

ADR 0004 and `TECH-SEC-08` unchanged. The change adds no logging of terminal bytes, and the
new audit rows carry posture only: `node.posture_changed` records the boolean and its
previous value; `session.create` records `sandbox` and `privileged`. No command text, no
paths, no output. `shell`/`fake` report `sandbox: "n/a"` rather than a value that would read
as a guarantee.

### 3.7 Nothing crosses the node boundary

- Contract v1.7.0 adds two optional booleans; no new socket, no new binary frame kind, no
  new endpoint, no CSP or edge change.
- RBAC unchanged. No new action: `terminal.shell` already decides who may open a terminal,
  and no action can decide whether sudo works inside one. If different users on the same
  machine need different postures, the answer is two nodes.
- Migration `0017` adds two booleans defaulting to `false`, so a node that has not reported
  reads as unprivileged. Absent never means privileged.

### 3.8 The tmux move

Cliora's sessions now live on `-L cliora` with a config in `/run/agentd` (mode 0600, owned by
the service user via `RuntimeDirectory=`). This *reduces* interference with the node owner's
own tmux server, which was previously shared. Mouse reporting is a usability change, not a
security one, with one honest cost: drag-select belongs to tmux, and browser-native selection
now needs Shift+drag. OSC 52 clipboard integration was not adopted — it would let remote
content write to a user's system clipboard and deserves its own decision.

**One-time availability cost:** the upgrade ends sessions running on the old socket (a tmux
session cannot move between servers). Not a security finding; it is in the release note and
the runbook, and nothing is killed automatically.

## 4. Findings

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | info | Escalation is available to every daemon-started process, not only the terminal (§3.5) | Documented in this review and ADR 0023 §4; inherent to the requested posture |
| 2 | info | The sandbox-flag probe is cached per daemon process (§3.2) | Documented in the runbook; a restart refreshes it |
| 3 | low | `node.posture_changed` depends on the node re-registering, so a machine changed while offline is reported late | Accepted: the console shows the last reported posture, and `agentd posture` is authoritative on the machine |

No high or medium findings. No change was required to the platform's authorization,
transport, credential handling or audit redaction.

## 5. Sign-off conditions

- [x] The posture cannot be set from Central, and a gate keeps it that way.
- [x] The console reports measured posture, never requested posture.
- [x] Both vetoes exist on the node and are covered by tests and a gate.
- [x] Sudoers writes are validated, atomic, verified and reversible.
- [x] Terminal content is still never recorded; new audit rows carry posture only.
- [x] Accepted risks are written as accepted, with the premise they rest on named.
- [ ] **Requester acknowledgement of §2** (the accepted-risk list) — the premise in ADR 0023
      §Context is the requester's statement, and the accepted risks follow from it, so the
      list needs their confirmation rather than an engineering sign-off.
