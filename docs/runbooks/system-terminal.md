# Runbook — the system terminal (`shell` runtime)

**Applies to:** every node running a daemon that contains the `shell` runtime.
**Owner:** whoever operates the node. Related: [ADR 0021](../adr/0021-system-terminal-and-shell-runtime.md),
[security review](../security-review-p8.md), `plan/08/`.

The one sentence to carry into everything below: **the system terminal escalates
nothing.** It exposes the privileges `agentd` already holds as an interactive
surface. Every control described here bounds *who* reaches that surface; none of
them bounds *what it can do* once reached. The daemon's execution identity is the
ceiling of the whole feature.

---

## 1. The thing to know before you upgrade a node

**A daemon upgrade turns this on.** A `config.yaml` written before the `shell`
runtime existed has no `runtime.shell` block, and an absent block means *enabled*.
So an existing node gains remote shell access the moment it runs the new binary,
without anyone editing a file.

That was decided deliberately (ADR 0021, D6: the requirement was a complete
terminal, and per-node file edits are not compatible with that), and it is a
capability change rather than a fix. Do not roll it out silently — see
`docs/release-note-system-terminal.md` for the note to send first.

Who can then use it: a user holding the `terminal.shell` action (**Admin and
Developer**; never Viewer) **on a session they own**, on this node. Not on
somebody else's session, and no attaching to somebody else's terminal.

## 2. Confirm which nodes have it, and from where

The daemon says so at startup, once, in one line:

```sh
sudo journalctl -u agentd | grep runtime_shell
# runtime_shell enabled=true source=default
```

| `source` | Meaning |
|---|---|
| `default` | This node's config says nothing about the shell. It is on because that is the default — the upgraded-node case. |
| `config` | The block is written in `config.yaml`. Whatever it says is what an operator chose. |

`source=default` is the one to look for after a fleet upgrade: those are the nodes
whose owners have not yet made a decision.

Central's view of the same fact is the node detail page's runtime list, which
reports every allowlisted runtime with its availability. A node with the runtime
enabled but no `bash` on `PATH` reports `available: false`, and Central refuses
the request with 409 `RUNTIME_NOT_FOUND` — **enabled does not mean usable.**

## 3. Turn it off on a node

The node owner has the only veto, and it is permanent: Central cannot re-enable
it, and no future default change will overwrite an explicit `false`.

```yaml
# /etc/agentd/config.yaml
runtime:
  claude:
    enabled: true
    binary: /usr/local/bin/claude
  shell:
    enabled: false      # ← the veto
    binary: bash        # required even when disabled: Validate() rejects an
                        # enabled shell with an empty binary, and keeping the
                        # value here means re-enabling is a one-word edit
```

```sh
sudo systemctl restart agentd
sudo journalctl -u agentd | grep runtime_shell   # expect enabled=false source=config
```

Existing shell sessions are not killed by the restart (tmux outlives the daemon —
see `update-failure.md` §1); they are collected by the idle reaper, or you can end
them from the console. New ones are refused from that point on, by the daemon
independently of Central.

To use a different shell, name it: `binary: /bin/zsh`. There is no argv field on
purpose (a login shell means pointing `binary` at a wrapper), because a field for
arguments is the first step towards letting a caller name a command — which is
the property `SEC-002` exists to keep.

## 4. What the audit trail will and will not tell you

**Will:** that a shell existed. Create, attach and terminate are session-level
audit events with `runtime: shell` in the metadata, so "who opened a shell on
which node, and when" is answerable.

**Will not:** what was typed or printed. Terminal bytes never reach the database
or the log (ADR 0004, `TECH-SEC-08`) and that applies here unchanged. There is no
command history, no replay, no recording.

This is a deliberate trade, and the reason is worth keeping in mind when someone
asks for the feature: the first thing a command log captures is a password typed
at a prompt. If an investigation needs to know what ran on a host, the answer has
to come from that host's own auditing (auditd, shell history, process
accounting) — not from Cliora.

```sql
-- who has opened a system terminal, most recent first
SELECT created_at, user_id, node_id, session_id, action
FROM audit_logs
WHERE metadata ->> 'runtime' = 'shell'
ORDER BY created_at DESC
LIMIT 50;
```

## 5. Lifetime, and the abandoned-shell case

A system terminal is bound to the CLI session it was opened from and cannot
outlive it. Four things end it, and the redundancy is the point — the first two
depend on a browser that may be gone:

1. **The user leaving it** — closing the TERMINAL tab, navigating out of the
   workspace, reloading, or closing the browser tab. All four send the terminate;
   the unload cases use a `keepalive` request, because an ordinary one would be
   cancelled along with the page.
2. **The parent ending** — terminating or losing the CLI session cascades to its
   shell.
3. **The idle reaper** — a shell whose watcher disconnected and did not come back
   is terminated after `shell_idle_terminate_seconds` (**default 900**, i.e. 15
   minutes). Reconnecting cancels it; disconnect/reconnect churn cannot extend the
   deadline; a CLI session is never reaped this way. An offline node is retried a
   few times rather than written off, and Central re-arms these timers at startup
   for every shell the database still shows as live — otherwise a restart would
   drop the timer for a browser that was already gone.
4. **The owner opening a new one** — if the existing shell has no subscriber, the
   next open ends it (audited with `reason: abandoned`) and starts a fresh one.

So after a browser crash or a lost network, **an unattended shell can exist on
the node for up to 15 minutes** — unless its owner comes back sooner, in which
case (4) ends it immediately. That window is a trade against reload and suspend
churn (security review Finding 3), and it is tunable per deployment. If your
threat model does not accept it, lower it:

```sh
CLIORA_SHELL_IDLE_TERMINATE_SECONDS=300
```

Only one live shell per session exists at a time, enforced by a partial unique
index in the database. `SHELL_ALREADY_OPEN` means specifically that **another tab
or window is attached to the existing one right now** — that is a refusal the user
resolves by going back to that tab. A terminal nobody is watching is not refused;
it is replaced, per (4). Before that distinction existed, a reload produced a
refusal the user could not act on: the terminal was live, the reloaded page no
longer knew its id, and nothing could be closed until the reaper fired.

## 6. Incident response

### "Someone has a shell on a node they should not"

The fastest correct order, because each step closes a different door:

1. **End the session.** Terminate it from the console (Sessions → the parent
   session → Terminate; the shell goes with the parent) or on the node:
   `tmux ls` then `tmux kill-session -t cliora-<session-id>` (every Cliora session
   is a tmux session named with that prefix).
2. **Remove the action.** Take `terminal.shell` off the role, or move the user to
   Viewer. Role changes are re-checked at the WebSocket handshake and per
   keystroke, so this lands on live connections, not just new ones.
3. **Veto on the node** (§3) if the node should never have offered it. This is the
   control that does not depend on Central being correct.
4. **Read the audit trail** for the shape of it (§4) — and remember it will not
   tell you what ran. Go to the host's own auditing for that.

### The privileged posture (ADR 0023) — read this before the next section

Since agentd 0.5.0 a node can be installed in the **privileged posture**: the unit omits
`NoNewPrivileges` and `/etc/sudoers.d/60-agentd` grants the service user passwordless sudo,
so the system terminal reaches root on demand. On such a node, "remote root for everyone
holding `terminal.shell` on a session they own" is the **intended** state, not a finding.
The premise is that the node is a disposable, isolated VM (ADR 0023 §Context).

Which posture a node is in:

```sh
sudo agentd posture      # the unit, the sudoers drop-in, sudo itself, and the reported value
```

Everything below still applies, with one correction: the daemon must still not *run* as
root even in the privileged posture. See `privileged-node-posture.md` for granting,
revoking, and the four distinct reasons sudo can fail.

### "The daemon is running as root"

Treat as a serious finding, not a hygiene item — in either posture. Running as root is not
the same as being able to escalate: escalation goes through `sudo`, which the node's own
`auth.log` records and which the node owner can revoke, while `User=root` leaves no record,
makes every workspace file root-owned, and breaks the update health check's identity
assumptions (ADR 0017).

```sh
systemctl show agentd -p User -p Group
ps -o user= -p "$(systemctl show -p MainPID --value agentd)"
```

`agentd run` refuses to start as root (`config.EnsureNonRoot()`), and the shipped
unit file sets `User=`, so this should be unreachable — but a hand-edited unit or
a container that runs the binary directly can reach it. If you find it: stop the
service, fix the unit's `User=`, restart, and check whether anything happened
while it was root (§4).

### "A shell session is stuck"

It is an ordinary session, so it fails and recovers like one: the daemon
reconciles against tmux and Central on restart (ADR 0012), and terminate is
graceful-then-forced. If Central shows a live shell that tmux does not have, the
next reconciliation clears it. If tmux has one Central does not,
`tmux kill-session` is safe — nothing else is attached to it.

## 7. Related runbooks

- `privileged-node-posture.md` — sudo in the terminal, the codex sandbox, and terminal
  scrolling (ADR 0023). Also: why upgrading to 0.5.0 ends the sessions that were running.
- `update-failure.md` — the upgrade that delivers this capability, and why
  sessions survive a restart.
- `heartbeat-loss.md` — a node going offline takes its shells with it.
