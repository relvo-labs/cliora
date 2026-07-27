# ADR 0011: P1 installer and artifacts

Status: accepted (2026-07-24)

- **Split of responsibility**: `install.sh` only detects distro/arch, downloads the matching `agentd` binary from `--server`, verifies its SHA256, and calls `agentd install …`. All real logic (register, write config/credential, systemd unit, verify connection) lives in the Go binary — the shell script stays thin and auditable.
- **Platforms (confirmed)**: MVP is **Linux only** — Ubuntu 22.04, Ubuntu 24.04, Debian 12, on `linux-amd64` and `linux-arm64`. macOS is out of scope for P1.
- **Layout**: binary at `/usr/local/bin/agentd`; `/etc/agentd/config.yaml` and `/etc/agentd/credentials.yaml` at `0600`; state in `/var/lib/agentd/`; logs in `/var/log/agentd/` or journald.
- **systemd unit**: `Type=simple`, `User`/`Group` = the `--user` argument, `ExecStart=/usr/local/bin/agentd run --config /etc/agentd/config.yaml`, `Restart=always`, `RestartSec=5`, `LimitNOFILE=65535`, `NoNewPrivileges=true`, `PrivateTmp=true`, `After`/`Wants=network-online.target`, `WantedBy=multi-user.target`. `PrivateHome` is **not** enabled (it would hide the user's CLI config and workspaces). The daemon never runs long-term as root (SEC-007).
- **Artifacts**: GoReleaser produces `agentd_<ver>_linux_{amd64,arm64}.tar.gz` + `checksums.txt`. Checksum verification is mandatory on install (and on the P4 update path). Node removal is a **soft delete** (retain record + audit), not a destructive delete.
- **`agentd update`**: present as a CLI stub in P1; the actual self-update/rollback flow is deferred to P4.
