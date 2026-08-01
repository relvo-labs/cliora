# Release note — privileged node posture (agentd 0.5.0)

**Send this before upgrading any existing node.** Audience: whoever owns a node running
`agentd`. Not an internal document — this is the notice the upgrade is blocked on
(`plan/12/06-verification-and-exit.md` §4.3).

---

## Read this first: two things happen to your node without you doing anything

**1. codex will run with no approval prompts and no sandbox.** Your `config.yaml` predates
the `sandbox_bypass` key, and an absent key means *enabled*. After the upgrade, codex on
your node edits files, installs packages and runs commands without asking.

**2. Sessions running at the moment you upgrade will end.** Cliora's tmux sessions move to a
dedicated tmux server, and a tmux session cannot be moved between servers. This is one-time
and it is not recoverable. The old panes are **not killed** — you can still attach to them
from a shell on the machine and salvage anything unfinished (see the runbook).

Both are deliberate. The default posture assumes a Cliora node is a disposable, isolated VM
that gets rebuilt rather than repaired (ADR 0023). If that is not true of your machine, say
no — how is at the bottom.

## What else changes

**The browser terminal scrolls.** It did not before: tmux attaches on the alternate screen
and disables mouse reporting, so the wheel was being translated into arrow keys — scrolling
up in a shell walked your command history instead of showing earlier output. The wheel now
drives tmux's copy mode, and the scrollback is at least 5000 lines (tmux's default was 2000,
so the 5000-line guarantee in our own spec had never actually been met).

**One regression, and it is the only one:** with mouse reporting on, tmux owns drag-select.
To select text with the browser, hold **Shift while dragging**, then copy as usual. (Shift +
*wheel* does nothing — that is xterm.js behaviour, not a bug in this change.) Both hints are
printed under every terminal.

**`sudo` works in the system terminal on newly installed nodes.** An *upgrade* does not
change this on your machine: the systemd unit is not rewritten by an update, so an existing
node keeps `NoNewPrivileges=true` and sudo keeps failing there until someone explicitly runs
`sudo agentd posture --privileged-terminal`. New installs are privileged by default and the
installer says so before it writes anything.

**The console now shows the posture** — Nodes list, node detail, the session header, and the
system terminal's notice. A change of posture is written to the audit trail
(`node.posture_changed`), and every session records the posture it started under.

**agentd still never runs as root.** That has not changed and is not a formality: it keeps
file ownership sane, keeps the update health check meaningful, and means every escalation
goes through `sudo` and lands in your machine's `auth.log`. Cliora does not collect that log
and still does not record anything typed in a terminal.

## To say no

**codex sandbox** — before or after upgrading:

```yaml
# /etc/agentd/config.yaml
runtime:
  codex:
    enabled: true
    binary: /usr/local/bin/codex
    sandbox_bypass: false     # ← agentd will not add the bypass flag
```

then `sudo systemctl restart agentd`. The platform has no way to override this.

**sudo in the terminal** — an existing node is unprivileged unless you opt in, so there is
nothing to do. To check, or to revoke on a node where it was granted:

```bash
sudo agentd posture                                # what is installed right now
sudo agentd posture --privileged-terminal=false     # revoke
```

**A new install that should not be privileged:** add `--no-privileged-terminal` to the
install command, and set `sandbox_bypass: false` afterwards.

## Checking the result

```bash
agentd doctor          # sandbox posture per runtime, tmux socket and scrollback, sudo, no_new_privs
sudo agentd posture    # the unit, the sudoers drop-in, and whether they agree with the config
```

Full details, including the four distinct reasons sudo can fail and what each looks like:
`docs/runbooks/privileged-node-posture.md`.
