# Daemon 0.7.1 — image upload liveness

This patch gives the fix merged in #144 for #143 a distinct daemon version. Image
persistence runs off the connection dispatcher with one daemon-wide admission slot,
preserving quota serialization while terminal/control traffic and reconnect remain
usable. Excess image uploads receive `NODE_BUSY` (HTTP 503). The accompanying #144
web changes distinguish body transfer from storage confirmation, bound completion
waiting, and fence stale callbacks; these require the corresponding web deployment.
The production-specific trigger from #143 remains unconfirmed.

Kernel I/O cannot be forcibly cancelled. If image persistence never returns, its
worker retains the single image-upload slot, including across reconnects; subsequent
image uploads remain busy. Cancellation or timeout can leave a retention-managed
image, and a manual retry can add another. There is no hard kernel-I/O deadline.

Release acceptance has three separate states:

- **Local candidate:** `daemon/VERSION` declares `0.7.1`; a plain Go build reports
  `0.7.1-dev`. Local packages and tests do not establish publication or fleet uptake.
- **Published Central manifest:** after merge, rebuild/deploy the Railway Central
  image from the merged source. By default `deploy/backend.Dockerfile` invokes
  `scripts/railway/pack-agentd.sh`, reading `VERSION` to build linux/amd64 and
  linux/arm64 tarballs plus `checksums.txt` into `/srv/artifacts`. Confirm
  `GET /api/releases/manifest` lists 0.7.1 for both architectures and verify served
  downloads against their recorded SHA-256. If the optional
  `AGENTD_RELEASE_BASE_URL` route is configured, it requires separately available,
  matching artifacts; it does not build them. GoReleaser currently has
  `release.disable: true`; the current pipeline does not publish GitHub Releases.
  There are no current GitHub Releases or release URLs to use for this candidate.
- **Upgraded fleet:** a version bump or Central/browser deployment alone does not
  upgrade nodes. On each explicitly identified, authorized node, use its configured
  Central and the existing CLI:

  ```sh
  sudo agentd update --version 0.7.1 --dry-run
  sudo agentd update --version 0.7.1
  agentd version --json
  ```

  Confirm the installed version is `0.7.1`, service health, Central re-registration
  with that version, terminal reconnect, and existing tmux session survival. The
  updater verifies the manifest and checksum, probes the staged version, replaces
  atomically, and rolls back on restart/healthcheck failure. Config and credentials
  stay intact. For an intentional downgrade, first ensure the previous version's
  artifacts remain in Central's manifest, then use
  `sudo agentd update --version 0.7.0 --allow-downgrade --dry-run`, followed by the
  same command without `--dry-run`. A rebuilt image may contain only 0.7.1, so
  rollback artifact availability must be arranged through the existing deployment
  process. See [the update failure runbook](runbooks/update-failure.md).

Local verification cannot establish real systemd restart/rollback or fleet acceptance.
The production Central origin and node list were not supplied; no live node access,
restart, publication, or deployment was performed. Canonical packaging, full daemon
race checks, and backend release/Railway checks remain parent-owned gates.
