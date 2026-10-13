# Daemon 0.8.0 — codex auto permission mode by default

This minor release gives the change merged in #156 for #155 a distinct daemon
version. It changes how agentd launches codex on every node that upgrades, so read
§1 before rolling it out. Decision record: [ADR 0030](adr/0030-codex-auto-permission-mode.md).
No contract, Central, migration or frontend change ships with it; a 0.8.0 node and an
older one can register with the same Central.

## 1. What changes on an upgraded node — read this first

agentd used to start codex with `--dangerously-bypass-approvals-and-sandbox` (yolo):
no sandbox and `approval_policy=never`, so an action blocked at runtime — most often
network access — had no approval path. 0.8.0 starts codex with `--approve-for-me`
(auto mode): the workspace-write sandbox, with actions that cross it (network, writes
outside the workspace, sudo) sent to Codex auto-review before they run.

The node setting is now `runtime.codex.permission_mode`:

| Config on the node | 0.7.1 launched codex with | 0.8.0 launches codex with |
|---|---|---|
| no key (default) | yolo | `--approve-for-me` |
| `sandbox_bypass: true` (written by every installer since 0.5.0) | yolo | `--approve-for-me` |
| `sandbox_bypass: false` | no flag | no flag (`cli_default`) |
| `permission_mode: auto` | — | `--approve-for-me` |
| `permission_mode: cli_default` | — | no flag |
| `permission_mode: full_access` | — | yolo |

**The legacy `true` row is deliberate:** installer-written `sandbox_bypass: true`
does *not* keep yolo. A node that genuinely needs yolo must say so with
`permission_mode: full_access` and drop `sandbox_bypass`. Setting both keys, an
unknown or `null` value, or either key on a runtime other than codex makes agentd
refuse to start with an explanation, rather than guess.

Visible differences:

- **The console flips from “sandbox: disabled” to “sandbox: enabled”** for codex on
  nodes that move to auto. That is the truth: auto keeps the sandbox. The console
  cannot yet tell auto from `cli_default` (#157).
- **Codex may pause for auto-review** on network/out-of-workspace/sudo actions, and
  auto-review can deny one. Codex then looks for a safer route or tells the user;
  `/approve` in the codex TUI retries a recent denial once.
- **If the installed codex does not accept `--approve-for-me`**, agentd starts it
  with no flag and says so in the startup log and `agentd doctor`. It never falls
  back to yolo. Upgrade codex on the node to fix it; the flag was verified
  on codex-cli 0.162.1 for this work.

## 2. Running sessions keep their old posture

A codex session launched before the upgrade keeps the argv it was started with — the
upgrade neither rewrites the config file nor touches running processes. Close and
reopen a codex session to get auto mode. The same applies after editing
`permission_mode`: restart agentd, then start a new session.

## 3. Release states

- **Local candidate:** `daemon/VERSION` declares `0.8.0`; a plain Go build reports
  `0.8.0-dev`.
- **Published Central manifest:** after merge, rebuild/deploy Central from the merged
  source. `deploy/backend.Dockerfile` runs `scripts/railway/pack-agentd.sh`, which
  reads `VERSION` and builds linux/amd64 and linux/arm64 tarballs plus
  `checksums.txt`. Confirm `GET /api/releases/manifest` lists 0.8.0 for both
  architectures and that served downloads match their SHA-256. GoReleaser still has
  `release.disable: true`; no GitHub Release is published.
- **Upgraded fleet:** a version bump or Central deployment does not upgrade nodes. On
  each explicitly identified node:

  ```sh
  sudo agentd update --version 0.8.0 --dry-run
  sudo agentd update --version 0.8.0
  agentd version --json
  sudo agentd doctor
  ```

  Confirm version `0.8.0`, service health, Central re-registration, the startup log
  line `runtime_codex_permission` (`effective_mode=auto`, `flag_applied=true`), and — in a **new**
  codex session — that a network command first blocked by the sandbox runs after
  auto-review approval.

## 4. Rollback

To return a single node to yolo without downgrading, set
`permission_mode: full_access` (removing `sandbox_bypass`), restart agentd and open a
new session. To downgrade the binary, first make sure 0.7.1's artifacts are still in
Central's manifest (a freshly rebuilt image may contain only 0.8.0), then
`sudo agentd update --version 0.7.1 --allow-downgrade --dry-run` and the same command
without `--dry-run`. **A 0.7.1 binary rejects a config containing `permission_mode`**
(unknown field) — remove that key and restore `sandbox_bypass` before downgrading.
See [the update failure runbook](runbooks/update-failure.md).

## 5. Not verified

The change has not run on an enrolled node. The hypothesis that a managed Codex
requirement silently degraded yolo to read-only (ADR 0030 §Context) is unconfirmed.
Real systemd restart/rollback and fleet acceptance are outside local verification.
