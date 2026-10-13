# Runbook — privileged node posture (sudo, codex sandbox, terminal scrolling)

Covers ADR 0023 / `plan/12`, with the Codex default amended by [ADR 0030](../adr/0030-codex-auto-permission-mode.md) (2026-10-13). The sudo and tmux controls apply to `agentd` 0.5.0 and later; the permission-mode enum applies after the issue #155 upgrade.

The posture of a node is two independent facts:

| Fact | Granted by | Reported as |
|---|---|---|
| The system terminal can reach root through `sudo` | the systemd unit (no `NoNewPrivileges`) **plus** `/etc/sudoers.d/60-agentd` | `privileged_terminal` on the node |
| codex uses a node-local permission mode | `runtime.codex.permission_mode` in `/etc/agentd/config.yaml` **plus** a CLI build that accepts the selected flag | `sandbox_bypass` true only for applied `full_access`; false for `auto`, `cli_default` or an unsupported flag |

They are deliberately separate: one is this machine's privilege model, the other is a
third-party CLI's behaviour. A node can be in any combination.

## 1. What posture is this node in?

```bash
sudo agentd posture      # read-only; prints the unit, the drop-in, sudo, and the config
agentd doctor            # same facts plus the tmux and runtime side
```

Also visible in the console: the Nodes list, the node detail page ("執行姿態"), the session
header, and the system terminal's own notice. The console shows **what the node reported**,
so a node that has not reconnected since a change still shows the old posture.

## 2. Turn sudo off (or back on)

```bash
sudo agentd posture --privileged-terminal=false   # revoke
sudo agentd posture --privileged-terminal         # grant
```

This rewrites the unit, adds or removes the sudoers drop-in, updates the reported value in
`config.yaml`, and restarts the service. It is idempotent: run it twice and the second run
does nothing, so following this runbook twice does not kick users off the machine.

It never runs from Central. There is no API, message or console button that changes a
node's posture — by design (ADR 0023 §4).

## 3. Select the Codex permission mode

Edit the existing `runtime.codex` block in `/etc/agentd/config.yaml`, keeping only
`permission_mode` and removing any legacy `sandbox_bypass` key:

```yaml
runtime:
  codex:
    enabled: true
    binary: /usr/local/bin/codex
    permission_mode: auto
```

`auto` is the default: workspace-write sandbox and auto-reviewed, on-request approvals.
`cli_default` adds no daemon flag and leaves the decision to Codex's configuration.
`full_access` explicitly opts into yolo, disabling approvals and the sandbox.
Legacy true upgrades to auto; legacy false maps to cli_default. Both keys together,
unknown values, explicit YAML null values (`null`, `~` or a bare key), and either
permission key on any non-Codex runtime are errors.

Restart with `sudo systemctl restart agentd`. Confirm with `agentd doctor`: it reports
requested and effective permission mode, source, whether the flag applied, and sandbox
posture. Startup logs use `runtime_codex_permission`. If the selected flag is unsupported,
Codex starts without a flag, doctor warns, and the console reports sandbox enforced.
Auto never falls back to full access. The console shows sandbox state, not the mode.

**Existing sessions keep the posture they started with.** The flag is part of the process's
argv; only new sessions pick up the change. Upgrading changes legacy true to auto for new
launches without rewriting the node's config or its already-running processes.

## 4. sudo does not work, but the node says it should

Check in this order — each one has a different fix and the same symptom.

1. **`no_new_privs` is set.** `agentd doctor` prints `no-new-privs=1`. The unit still has
   `NoNewPrivileges=true` (an update does not rewrite the unit; a manual edit or a
   config-management tool may have restored it). Fix: `sudo agentd posture
   --privileged-terminal`. The failure message inside the terminal is:

   ```
   sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
   ```

2. **The drop-in has the wrong mode or owner.** sudo **silently ignores** a file in
   `/etc/sudoers.d` that is more permissive than `0440` — no error, no log line, the file
   just has no effect. Check with `stat -c '%a %U' /etc/sudoers.d/60-agentd`; it must be
   `440 root`. Fix: `sudo agentd posture --privileged-terminal` (it rewrites the file
   correctly rather than patching the mode by hand).

3. **The drop-in is missing.** `sudo agentd posture` prints `sudoers: … absent`. Same fix.

4. **The config and the machine disagree.** `agentd doctor` prints
   `[warn] posture: config reports privileged_terminal: … but sudo …`. The console believes
   the config, so this is the case where the console is lying. Fix: run `sudo agentd
   posture --privileged-terminal[=false]` for the posture you actually want.

**Never edit `/etc/sudoers.d/60-agentd` by hand.** A syntax error there takes sudo away
from the whole machine, including the sudo needed to repair it. `agentd posture` validates
with `visudo -c` on a temp file, installs atomically, verifies that sudo works for the
service user, and rolls back if it does not.

If sudo is already broken machine-wide: boot a recovery shell (or use the VM console as
root) and `rm /etc/sudoers.d/60-agentd`. On a disposable node, rebuilding is faster.

## 5. The terminal still does not scroll

The wheel drives tmux's copy mode, which needs three things:

```bash
tmux -L cliora show-options -gv mouse            # want: on
tmux -L cliora display-message -p -t <session> '#{history_limit}'   # want: >= 5000
ls -l /run/agentd/tmux.conf                      # the generated config the server started with
```

- **`mouse` is `off`:** the tmux server predates this daemon version. Options are re-applied
  per session, so a *new* session scrolls; an old one may not. End the old sessions.
- **`history_limit` is 2000:** same cause, and it cannot be repaired in place — a pane reads
  its history limit when it is created. All sessions on that server must end before the
  server restarts with the generated config. `tmux -L cliora kill-server` does that, and it
  ends every Cliora session on the node.
- **`/run/agentd/tmux.conf` is missing:** the unit has no `RuntimeDirectory=agentd`, or the
  daemon could not write it (it logs a warning and carries on). Reinstall or add the
  directive.

Changing `session.scrollback_limit` follows the same rule: it applies to panes created after
the tmux server restarts.

## 6. Users report they can no longer select text with the mouse

Expected, and the only regression in this change. With mouse reporting on, tmux owns
drag-select. Browser-native selection is **Shift + drag** (then the usual copy shortcut).
The hint under each terminal says so.

Shift + *wheel* does nothing — xterm.js ignores a wheel event with Shift held. If someone
reports "Shift doesn't scroll", they have been given the wrong instruction.

## 7. Sessions disappeared after upgrading to 0.5.0

One-time, expected, and not recoverable. Sessions moved to a dedicated tmux server
(`-L cliora`); a tmux session belongs to its server and cannot be moved between them, so
sessions running on the default socket at upgrade time are no longer served. They are **not
killed** — those panes may hold unfinished work.

```bash
tmux ls                                  # the old (default) socket
tmux attach -t cliora-<uuid>             # look at what is in there, from a shell on the node
tmux kill-session -t cliora-<uuid>       # clear it when you are done
```

The daemon logs a warning at startup while any remain, and `agentd doctor` shows the count.
Nothing clears them automatically: an automatic kill would destroy work to tidy a log line.

## 8. Installing a node that must *not* be privileged

```bash
curl -fsSL https://platform.example.com/api/install-script | sudo bash -s -- \
  --server https://platform.example.com --token enroll_xxx --name shared-box \
  --user neil --no-privileged-terminal
```

Codex still defaults to auto with its workspace sandbox; choose `cli_default` in the
node config if Codex should decide its own permissions. The terminal privilege default
assumes a disposable, isolated VM (ADR 0023 §Context). Any machine you
would repair rather than rebuild should be installed this way — and the console will show it
as unprivileged, so the choice remains visible afterwards.
