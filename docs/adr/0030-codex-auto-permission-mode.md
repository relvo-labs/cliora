# ADR 0030 — Codex auto permission mode by default

- Status: accepted
- Date: 2026-10-13
- Accepted by: Neil
- Amends: ADR 0023 §1 only. Its node-local authority, compile-time argument table,
  measured wire reporting, sudo, non-root identity, audit and tmux controls stand.
- Related: ADR 0021 §1/§4, SEC-002, FR-RUNTIME-003.AC-02,
  FR-RUNTIME-004.AC-02/AC-03/AC-04, SEC-007.AC-02/AC-03
- Issue: relvo-labs/cliora #155
- Contract: unchanged (v1.7.0 posture fields retain their meaning)

## Context

Nodes have launched Codex with approvals and its sandbox disabled since ADR 0023.
Operators report blocked actions, most often network access, with no approval path
available: yolo selects `approval_policy=never`.

The issue's local investigation of codex-cli 0.162.1 found a managed-requirements
fallback message in the binary: if managed policy forbids `danger-full-access`,
yolo can fall back to read-only permissions with approvals disabled. That would
explain network restrictions with no way to request approval. **This fallback has
not yet been reproduced on a real node.** Both accounts tested locally allowed
full access; the binary message is a finding, not proof of the reported node's cause.

The same investigation confirmed that `--approve-for-me` selects
`approval_policy=on-request`, `approvals_reviewer=auto_review` and
`sandbox_mode=workspace-write`. In the local test a network request failed in the
sandbox, then succeeded after approval review. Workspace operations remain usable;
network access, writes outside the workspace and sudo need review beyond the sandbox.
An auto-review denial can lead to a safer approach or an explanation to the user;
Codex also offers `/approve` to retry. Auto mode does not promise every action approval.

Changing only an absent-key default would miss installed nodes: the installer has
written `sandbox_bypass: true` explicitly. The migration must cover that value too.

## Decision

### 1. A closed node-local enum replaces the legacy boolean

```yaml
runtime:
  codex:
    enabled: true
    binary: /usr/local/bin/codex
    permission_mode: auto
```

| Node setting | Daemon argument | Meaning |
|---|---|---|
| `auto` (default) | `--approve-for-me` | workspace-write sandbox with auto-reviewed, on-request approvals |
| `cli_default` | none | Codex's own configuration decides |
| `full_access` | `--dangerously-bypass-approvals-and-sandbox` | explicit node-local opt-in to yolo |

Only Codex accepts `permission_mode`. Unknown values are validation errors, not
argument strings. All flags remain in the daemon's compile-time table in
`daemon/internal/runtime/launch.go`; config and wire never carry an argv string.
There is no Central API or console path to change the mode.

Legacy mapping is deliberate: `sandbox_bypass: true`, and neither key present,
become `auto`; `sandbox_bypass: false` becomes `cli_default`, preserving the
operator's refusal of daemon flags. Setting both keys is an error explaining to
keep only `permission_mode`, including when either value is YAML null. An explicit
null (`null`, `~` or a bare key) for either key is invalid rather than absent.
Only an explicit new-key `full_access` can select yolo.
Load records the source as `config`, `legacy-key` or `default` for startup reporting.
The installer writes `permission_mode: auto` with the other choices explained nearby.

### 2. Probe the selected flag; unsupported means no flag

Detection checks for a help line declaring the selected flag, with only whitespace
and an optional short-option alias before it. Prose mentions, longer lookalikes and
a different long alias do not count as support.
An unsupported flag leaves the runtime usable with no added flag (`cli_default`),
with a SandboxNote, a doctor warning and a startup log explaining the result.
**Auto never falls back to full access.** `cli_default` needs no permission-flag probe.
Doctor and `runtime_codex_permission` startup logs state the requested mode, source
and whether its flag was applied; these diagnostics stay on the node.

### 3. Keep the wire and session audit meaning

`runtime-item.sandbox_bypass` remains the measured daemon launch posture: true only
when the full-access flag is actually applied. Auto reports false because its
sandbox remains enabled; an unsupported flag and `cli_default` also report false.
The console continues to show sandbox enforced for false. It does not distinguish
auto from CLI default; doing so needs a separate contract decision.

No contract, backend or frontend change is needed. Backend session audit `sandbox`
values remain unchanged by construction. Terminal privilege is a separate node
choice: this decision changes no sudoers rule, unit hardening, ownership, lifetime,
non-root execution or terminal recording rule from ADR 0023 and ADR 0021.
Existing sessions keep the mode they started with; restart agentd to apply a config
change to new launches. An upgrade does not rewrite the file or running Codex argv.

## Rejected alternatives

- **Keep yolo as the default.** A blocked action still has no approval path, and the
  managed-requirements fallback finding gives another reason to avoid that default.
- **Change new installs only.** Installer-written legacy true would keep upgraded
  nodes on the posture that triggered this issue.
- **Remove yolo.** The operator of a disposable isolated VM may still choose full
  access explicitly on that node; retain it behind the new key rather than infer consent.

## Verification

Config tables cover defaults, both legacy values, each enum value, conflicting keys,
unknown values and the non-Codex rejection. Runtime tests cover both flags separately,
unsupported flags (including a yolo-only binary with auto selected), measured bypass,
and bounded probing. Installer config round-trips to auto; fakecli preserves its
`sandbox=` e2e output and adds `permission=`. The argv-channel gate guards the node's
CLI-default refusal and keeps both flag constants in the daemon table.

Real-node reproduction of the managed-requirements fallback remains outstanding;
`agentd doctor` and `scripts/pv/node-posture-check.sh` provide the local observations
for node acceptance without turning the finding into an assumed cause.
