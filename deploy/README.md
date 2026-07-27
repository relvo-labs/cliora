# Cliora daemon deployment (P1-W6)

One-line Linux install of the `agentd` daemon. See ADR 0011 and `plan/02/06-installer-artifacts.md`.

## One-line install

```bash
curl -fsSL https://platform.example.com/api/install-script | sudo bash -s -- \
  --server https://platform.example.com \
  --token  enroll_xxxxxxxx \
  --name   dev-vm-01 \
  --user   neil
```

`install.sh` ([./install.sh](./install.sh)) is deliberately thin: it detects the
distribution and CPU architecture, downloads the matching `agentd` tarball from
`--server`, **verifies its SHA256 against `checksums.txt`**, then hands off to
`agentd install`. Every real step lives in the Go binary and is unit-tested
(`daemon/internal/install`). The enrollment token is never printed.

`agentd install` (root, via sudo):

1. Calls `POST /api/nodes/register` with the enrollment token → `{node_id, server_url}; the daemon sends its generated public key`.
2. Writes `/etc/agentd/config.yaml` and `/etc/agentd/credentials.yaml` at **0600**, owned by `--user`.
3. Creates `/var/lib/agentd` and `/var/log/agentd`, owned by `--user`.
4. Installs the binary at `/usr/local/bin/agentd`.
5. Writes the systemd unit and `enable --now`s it. The service runs as `--user` — **never root** (SEC-007).

## Lifecycle commands

| Command | Purpose |
| --- | --- |
| `agentd install …` | register + write files + systemd unit + start (sudo) |
| `agentd uninstall [--purge]` | stop/disable, remove unit + `/etc/agentd`; `--purge` also clears state/logs (sudo) |
| `agentd start` / `stop` / `status` | systemd lifecycle wrappers |
| `agentd register …` | re-enroll: rewrite `credentials.yaml` only (sudo) |
| `agentd doctor` | offline-capable diagnostics (see below) |
| `agentd workspace list` | print configured allowed roots |
| `agentd config validate` / `runtime list` | config + runtime introspection |
| `agentd version [--json]` | print the running version (one bare line; `--json` adds arch/os) |
| `agentd update [--version x.y.z] [--allow-downgrade] [--dry-run]` | verified self-update with rollback (sudo) — see below |

`agentd doctor` reports: non-root, config parse + 0600, credentials 0600 (once
enrolled), tmux presence, **Central TCP reachability**, allowed-root
readability, runtime detection, and the **update readiness** checks (staging
directory permissions, presence of a rollback binary). It fails (non-zero) on any
hard problem and never prints a secret.

## Updating a node (P4-10)

`sudo agentd update` downloads the requested release from this node's configured
Central, verifies its SHA-256 against `GET /api/releases/manifest`, replaces the
binary atomically, restarts the unit, and **rolls back if the health check fails**.

Two things about it are deliberate:

- **There is no way to name an artifact.** The flags are `--version`,
  `--allow-downgrade` and `--dry-run` — no `--url`, `--file` or `--checksum`. The
  download location and the digest come from the manifest plus the local config, so
  a node can only ever install an allowlisted release (SEC-002).
- **It needs sudo, and the daemon itself will refuse.** Replacing the binary and
  restarting the unit require root; the long-running daemon runs unprivileged and is
  not given a way to escalate (SEC-007). A `daemon.update` request from the console
  therefore answers `UPDATE_NOT_ALLOWED` and tells the operator to run the command
  here. It also avoids the trap that whoever runs `systemctl restart agentd` must not
  *be* the unit being restarted, or it cannot health check or roll back.

`--dry-run` performs the manifest lookup, the download, the digest check and the
staged-binary version check, then stops without replacing anything. It works without
root, so a release can be rehearsed before the real run.

**tmux sessions are not affected.** The tmux server is a separate process; a restart
detaches the terminal stream and nothing else. See
`docs/runbooks/update-failure.md` for what a user sees, how to read each failure
stage, and how to roll back by hand.

## Producing artifacts

Release artifacts come from GoReleaser ([daemon/.goreleaser.yaml](../daemon/.goreleaser.yaml)):

```bash
cd daemon && goreleaser release --clean        # or `--snapshot` for a dry run
```

This yields `agentd_<ver>_linux_amd64.tar.gz`, `agentd_<ver>_linux_arm64.tar.gz`
and `checksums.txt`. Deploy them plus `install.sh` into the directory named by
the backend `CLIORA_ARTIFACTS_DIR` setting; Central then serves them at
`GET /api/downloads/{filename}` and `GET /api/install-script` (public, allowlisted,
path-traversal-proof — see `backend/app/api/http/downloads.py`).

## Install matrix (P1-16) — CI-gated

The exit-gate matrix runs install → start → verify WSS register+heartbeat →
`systemctl restart` re-register → `agentd doctor` green → uninstall-clean on:

- Ubuntu 22.04, Ubuntu 24.04, Debian 12
- `linux/amd64` and `linux/arm64`

**Sandbox limitation:** this matrix cannot run in the local dev sandbox — it
needs real root, systemd (PID 1), and multiple OS images. It belongs to the
Wave 6 CI runners. What *is* verified locally: the install package unit tests
(`go test ./internal/install`), the artifact-server + checksum contract
(download → SHA256 verify → extract → run), the generated config round-tripping
through the real validator, the systemd unit contents, and `agentd doctor`'s
fault diagnostics.
