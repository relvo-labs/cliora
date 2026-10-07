# Daemon 0.7.1 — upload liveness release

- Tier: M / T2; issue: #146; base: `183a1f5f6769ef9ef42bed5869d51ebe25a82de8` (includes #144).
- Goal: make the merged upload-liveness fix discoverable and installable as a distinct daemon patch version.
- Authority: branch/PR, local packaging and verification authorized. Human merge retained. No live node restart, credential access, production data change, or release publication from an unmerged candidate.

## Bounded scope

1. Bump `daemon/VERSION` to `0.7.1`, align development fallback and guard their consistency with a focused test.
2. Add concise release notes: upstream #143/#144, known one-stuck-IO-slot limitation, packaging/manifest prerequisites, non-automatic node update, operator verification and rollback.
3. Reuse `scripts/railway/pack-agentd.sh`, the existing backend image packaging and release manifest. Do not introduce a new release framework, change updater privilege, or alter CI triggers.

## Evidence and sequencing

- Exact writer reads `.agent/skills/cliora-project-context/SKILL.md`, `go-daemon-development/SKILL.md`, `cliora-security-review/SKILL.md`, release/update ADR and relevant technical requirements before mutation.
- First coherent checkpoint is committed/pushed as Draft PR by the parent after complete diff/trigger inspection.
- Freeze candidate; build linux/amd64 and linux/arm64 packages twice using Go `1.26.5`. Verify SHA-256, archive root/mode, ELF architecture, executable amd64 version/JSON and candidate lineage.
- Run package/manifest/backend release tests, complete daemon race suite and update/install integration where executable in this environment; record unavailable real-systemd/fleet gates separately.
- One independent exact-head review; at most one consolidated blocker repair via the exact writer. Ready only after fresh evidence and no unresolved P0/P1.

## Rollout boundary

After human merge, rebuild/deploy Central from the merged source so `/api/releases/manifest` and downloads expose 0.7.1. Verify served artifacts, then upgrade only explicitly identified nodes through the existing operator update route and verify registration/daemon version. An existing same-version 0.7.0 binary does not acquire #144 merely from a browser or Central update. Source, local candidate, published manifest and live node version are separate acceptance states.

Current implementation takes precedence over ADR 0017's proposed GitHub publication: `daemon/.goreleaser.yaml` retains `release.disable: true`. Railway's default image build invokes the existing packer with `daemon/VERSION`; no GitHub Release or new release framework is required. The optional external-artifact route needs matching published artifacts. Preserve a manifest-available previous release through the existing deployment process before planning a CLI downgrade; a freshly rebuilt image may contain only 0.7.1.

## Exclusions

No GitHub Release/tag from unmerged source, automatic fleet rollout, new update authorization, CI-policy migration, frontend redesign, or claim of successful real systemd restart without evidence.
