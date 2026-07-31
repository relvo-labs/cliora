# Release note — the system terminal (`shell` runtime)

**Send this before upgrading any existing node.** Audience: whoever owns a node
running `agentd`. Not an internal document — this is the notice the upgrade is
blocked on (`plan/08/00-execution-plan.md` §8).

---

## What changes

Cliora's session workspace gains a **TERMINAL** tab: an interactive shell on the
node, in the browser, alongside the CLI. Users no longer have to leave Cliora to
run `git status`, read a log, or install a package.

## What changes on your node, without you doing anything

**Upgrading the daemon enables it.** Your `config.yaml` was written before this
runtime existed, so it has no `runtime.shell` block — and an absent block means
*enabled*. After the upgrade, users who hold the permission can open a shell on
your node.

We are telling you rather than asking because the shell grants no privilege the
daemon did not already have (see below). We are telling you *before* the upgrade
because it is a capability change, not a fix, and you may want to say no.

**To say no**, before or after upgrading:

```yaml
# /etc/agentd/config.yaml
runtime:
  shell:
    enabled: false
    binary: bash
```

```sh
sudo systemctl restart agentd
sudo journalctl -u agentd | grep runtime_shell   # expect enabled=false source=config
```

That decision is yours permanently. Cliora cannot re-enable it, and no future
default change will overwrite an explicit `enabled: false`.

**To check what a node currently does**, the daemon logs it once at startup:

```sh
sudo journalctl -u agentd | grep runtime_shell
# runtime_shell enabled=true source=default   ← on, because nobody has decided
# runtime_shell enabled=true source=config    ← on, because your config says so
```

A node with no `bash` on `PATH` reports the runtime as unavailable and requests
are refused — enabled does not mean usable.

## Who can use it

- Holders of the `terminal.shell` permission: **Admin and Developer**. Viewer
  never gets it.
- **Only on sessions they own.** Not on a colleague's session, and nobody —
  including an Admin — can attach to somebody else's terminal.
- One live terminal per session, and it ends when the tab closes, when the parent
  session ends, or after 15 minutes with nobody watching.

## What it can reach, and what bounds it

The terminal is **not** confined to the session's workspace directory. It is a
shell on the host, so it reaches whatever the `agentd` service user reaches. It
grants nothing new: the same privileges were already available to the daemon for
starting CLI processes and reading workspace files.

That makes one thing load-bearing: **`agentd` must not run as root.** It refuses
to start as root and the shipped systemd unit sets `User=`, so a standard install
is fine. If you have hand-edited the unit file or run the binary directly in a
container, check it before upgrading:

```sh
systemctl show agentd -p User
```

## What is recorded

- **Recorded:** that a terminal was opened, attached to and closed — who, which
  node, which session, when.
- **Not recorded:** anything typed or printed. No command history, no replay, no
  recording. Terminal content never reaches Cliora's database or logs, by design
  and unchanged from CLI sessions — the first thing such a log would capture is a
  password typed at a prompt.

If you need host-level attribution of what ran, that has to come from the host's
own auditing (auditd, process accounting). Cliora will tell you a shell existed,
not what it did.

## What to do

1. Read §"What changes on your node". Decide whether you want it.
2. If not, write `enabled: false` — either now or right after the upgrade.
3. Confirm `agentd` does not run as root.
4. Upgrade (`sudo agentd update --version <x.y.z>`; running sessions survive it —
   see `docs/runbooks/update-failure.md` §1).
5. Check the startup line to confirm the node ended up where you intended.

Operational detail, tuning and incident response:
[`docs/runbooks/system-terminal.md`](./runbooks/system-terminal.md). The design
decisions and their trade-offs:
[ADR 0021](./adr/0021-system-terminal-and-shell-runtime.md).
