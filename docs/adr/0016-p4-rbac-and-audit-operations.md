# ADR 0016: P4 RBAC & audit operations model

Status: accepted (2026-07-25). Governs Phase 4 (Operations & Hardening); confirmed defaults per product decision (see `plan/05`).

## Context

P1–P3 shipped action-level authorization: `require_action()` at the HTTP boundary, `has_action()` inside the terminal WS loop, and a role→actions mapping seeded by migrations `0002`/`0006`/`0007`. That model is sufficient while every action is either global (`node.view`, `enrollment.manage`) or self-scoped by construction. It is **not** sufficient for session-scoped actions, and P4 is where that becomes a live defect rather than a theoretical one:

- `session.terminate` and `terminal.takeover` check the role only. `TerminalSession.user_id` exists but is never consulted, so **any Developer can terminate or seize the writer role of any other user's session**.
- `audit.view` was seeded to Admin in `0002` and defined in `rbac.py`, but no endpoint has ever used it — a dead permission, and no way to read the audit trail SEC-006 mandates.
- Audit entries carry actor and resource but not `request_id`, so an audit row cannot be correlated with the logs from the same request.

P4 also has to retire the last prototype artefacts, one of which is a genuine authorization surface. This ADR fixes the authorization and audit model before any new endpoint ships.

## Decisions

### Product name is **Cliora**

Closes decision gate 1 of `research/01/00-implementation-roadmap.md` §7 (open since P0: "Cliora or Cask"). Cliora is the canonical product name. The name stays **configurable** in the UI (`VITE_PRODUCT_NAME`, already implemented) so a deployment can rebrand, but package identities are normalized: `frontend/package.json` `cliora-console-prototype` → `cliora-console`, `backend/pyproject.toml` `cliora-central-p0` → `cliora-central`. "Cask" is dropped.

### Permission matrix has one source of truth

`app/services/rbac.py` gains a declarative `ROLE_ACTIONS: dict[str, frozenset[str]]` plus `ALL_ACTIONS`. Three automated consistency assertions make drift a test failure rather than a discovery:

1. `ROLE_ACTIONS` equals what the seed migrations actually produce in the database after `upgrade head`.
2. `ALL_ACTIONS` equals the `ACTION_*` constants exported by `frontend/src/api/dto.ts`.
3. Every member of `ALL_ACTIONS` is used by at least one endpoint or WS handler (an explicit, reviewed allowlist covers actions not yet wired — the mechanism that would have caught `audit.view`).

`docs/permission-matrix.md` is generated from `ROLE_ACTIONS` (by `scripts/p4/render_permission_matrix.py`) and asserted to match, so the document cannot rot.

**No seed migration was required.** Comparing the declared matrix against migrations `0002` + `0006` + `0007` showed they already agree exactly, and P4 adds no new action key (audit reuses `audit.view`, favorites reuse `session.create`, node update reuses `node.manage`, metrics export uses a scrape token rather than an action). The gap was never seeding — it was enforcement. An empty revision would only have added a no-op to the migration history, so `0008` is left to P4-04's audit indexes and the parity is guaranteed by a test instead.

### Authorization is two layers, and both are mandatory

| Layer | Where | Answers |
|---|---|---|
| Action | `api/http/deps.py::require_action()` | "may this role ever do this kind of thing?" |
| Resource scope | **`app/services/authz.py`** (new) | "may this user do it to *this* resource?" |

Every session-scoped or node-scoped mutation passes both. `authz.py` is the **only** place resource-scope logic lives; `has_action()` outside `authz.py`/`deps.py`/capability computation is a defect, enforced by a grep check in review.

### Owner rules

| Operation | Rule |
|---|---|
| `session.view` / read-only attach | any holder of `session.view` (Viewer included, consistent with P2) |
| `session.write` (writer at handshake) | `terminal.operate` **and** (owner **or** holder of `terminal.takeover`) |
| `session.takeover` | **same as write eligibility** — whoever may hold the writer role may reclaim it; always audited, current writer notified |
| `session.terminate` | `session.terminate` **and** (owner **or** holder of `node.manage`, i.e. Admin) |
| `session.create` | `user_id` is assigned by the server from the authenticated user; never accepted from the client |
| `file.browse` | `file.browse` **and** `session.view` on the owning session (P3 semantics unchanged) |
| `node.manage` | role-only; nodes have no owner |

**Amendment (2026-07-25, during P4-03):** an earlier draft made takeover "owner **or** holder of `terminal.takeover`", without requiring `terminal.operate`. That is a hole under **demotion**: a Developer who created a session and is later reduced to Viewer still *owns* it, so the owner branch would keep letting them seize the writer role and type into a live CLI. `terminal.operate` is therefore required for write **and** takeover, including for the owner — permission contraction must actually contract. Covered by `test_owner_without_operate_cannot_write` and `test_demoted_owner_loses_write_and_terminate`.

Developers **can see** other users' sessions (`session.view`) but cannot terminate them. They *may* hold or take over the writer role on a colleague's session, because they hold `terminal.takeover` — that is an explicit, announced and audited act, not silent access. Denials all raise the same `FORBIDDEN` / 403 with an identical message — the response must not reveal whether the resource exists or who owns it. Where a resource may legitimately be absent, `session.view` is evaluated first and only then may a 404 be returned; otherwise 403.

### The browser re-authorizes every inbound control message

The terminal WS checks authorization at handshake **and** on every inbound control frame, not once at attach. A viewer's binary input or `terminal.control_acquire` is dropped and counted, never applied.

### UI capability comes from the server

`GET /api/auth/me` returns the server-computed capability list, and session DTOs carry per-resource flags (`can_write`, `can_terminate`). The frontend never re-implements owner rules. Every `v-if`-hidden control must have a corresponding server-side 403 test: **UI hiding is not authorization**.

### Audit coverage, and one event = one row

Coverage is the union of SEC-006 (8 items) and tech §13.3 (11 items). P4 adds `user.session_revoked`, `node.enable`, `credential.rotate`, `daemon.update_started`, `daemon.update_result`, and `authz.denied`.

Audit is written **only in the service layer**; API handlers never write a second row. Paths without a service (the terminal WS loop) carry an explicit comment marking them as the sole writer. Each covered operation has a test asserting the row count for that action is exactly 1.

`authz.denied` records **security-relevant refusals only** — mutations and cross-owner access attempts. Ordinary read 403s and validation 422s are not audited; auditing them would bury the signal.

### Audit metadata: minimized, correlated, bounded

- `AuditService.record()` automatically attaches `request_id` from `app.logging.request_id_var` (HTTP), from the originating `registry.request()` id (daemon relay), or `None` plus `source` (daemon-initiated / background). It goes in the JSONB metadata rather than a new column; ADR revisit condition: if actor+time+request_id queries need an index, promote it to a column.
- `redact_mapping()` becomes recursive (nested dicts/lists), gains key fragments (`bearer`, `cookie`, `api_key`, `apikey`, `session_token`), and adds value-level masking of obvious JWT and `enroll_`-prefixed strings as defence in depth. The primary rule remains: do not pass secrets in.
- Metadata is capped at 4 KiB; overflow is truncated and flagged `truncated: true`.
- Never recorded, anywhere, asserted by test: terminal bytes, file content, directory listings, search keywords in the clear, passwords, tokens, private keys, full server absolute paths (workspace is recorded as a directory name or root id). P3's sensitive-read granularity is unchanged: classification + extension only.

### Reading the audit trail is not itself audited

`GET /api/audit` (Admin, `audit.view`) does not write an audit row. Rationale: an Admin reviewing the trail would otherwise inflate it without adding accountability, and the read is already visible in request logs. Revisit if a compliance requirement demands access logging.

Queries are bounded: page 50 (max 200), time range max 90 days, opaque `(created_at, id)` cursor pagination rather than offset. Unknown action values are rejected with 422 rather than pattern-matched, so the endpoint cannot become an arbitrary query surface.

### Retention is a documented procedure, not a scheduler

`audit_retention_days` = 365, `node_metric_retention_days` = 30 (both settings). Expiry is handled by `scripts/p4/prune-retention.sh` → an explicit CLI subcommand that **defaults to dry-run and requires `--yes`**, documented in `docs/runbooks/backup-restore.md` with a mandatory "take a backup first" step. MVP deliberately ships no background scheduler: a mis-scheduled deletion of the audit trail is a worse failure than manual retention, and there is no other background job in the system to piggyback on.

### The P0 development relay is retired

`app/main.py`'s `/ws/p0/daemon` and `/ws/p0/sessions/{id}/terminal`, the `authorized()` shared-static-token check, `app/relay/{queue,registry}.py`, the `p0_enabled` / `p0_token` / `node_id` settings, `daemon/cmd/agentd/p0.go`, and the `dev-central` / `dev-daemon` Make targets are removed in P4-07. ADR 0006 is superseded.

Rationale: the P2 relay (`services/terminal_relay.py` + `api/ws/terminal.py`) fully replaced it, so `app/relay/*` is unmaintained code on a live code path, and `/ws/p0/*` is the **only** WebSocket endpoint authorized by a shared static token. It fails closed in production (the `environment == "production"` validator), which is why it was acceptable through P3 — but "disabled in production" is a weaker property than "absent". Development loses nothing: `scripts/e2e/run-stack.sh` already brings up Central plus a real rootless-enrolled daemon.

This is a deliberate deletion, recorded here so it is not mistaken for silent scope reduction.

### Prototype retirement boundary

- **Fonts:** the Google Fonts `@import` at the top of `frontend/src/styles.css` is removed and replaced by a **system font stack** (`system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans TC", sans-serif`). No self-hosted woff2 subset in MVP: zero bundle cost, adequate Latin and Traditional Chinese coverage on the supported platforms, and it is a prerequisite for the CSP in ADR 0017. A build-time grep asserts `dist` contains no CDN reference.
- **Shared classes:** `.primary`, `.danger`, `.head`, `.panel` are still used by 9 files, so they are **migrated** into shared components / scoped styles file-by-file with before-after visual regression screenshots, not deleted wholesale. Everything else in `styles.css` (`.metrics`, `.dashgrid`, `.nodecard`, `.timeline`, `.sidefoot`, `.side nav`, `.system`, `.account`, `.bar`) is unused and deleted. P4-08 re-implements the dashboard visuals from design tokens — the prototype CSS is not copied forward.
- **`min-width: 1180px`** is removed. style §24 defines desktop-only at a 1440×900 minimum; narrow viewports are handled per-view (table horizontal scroll, the sidebar breakpoint `AppLayout` already has) rather than by forcing a page-level horizontal scrollbar globally.
- **`TokenShowcaseView` is kept** as a dev-only design reference behind the existing `import.meta.env.DEV` route, with a `dist` grep asserting it is absent from the production bundle. It costs nothing and is the only place the token system is visible in one screen.
- Prettier's exemption list (currently excluding `src/App.vue` and `src/styles.css`) is removed once the prototype files are gone: a retired prototype should not leave a formatting exemption behind.

### Workspace favorites scope (FR-WORKSPACE-004/005)

Favorites are **per user and per node** (a path is only meaningful on the node it lives on), unique on `(user_id, node_id, path)` so re-favoriting is idempotent. Recent workspaces are **derived from `terminal_sessions`** — no second table — returning the user's 5 most recent distinct `(node_id, workspace)` pairs (configurable, max 20). A favorite may only be deleted by its owner; a request for someone else's returns 404, not 403.

Authorization is `session.create`: the feature exists to make session creation faster, and Viewers cannot create sessions. If this is ever extended to read-only browsing convenience it becomes `file.browse` and must be added to the permission matrix test in the same change.

**Favorites are a UX shortcut, never an authorization source.** Creating a session from a favorite runs the identical path: Central's workspace-prefix authorization, then the daemon's `os.Root` canonicalization and containment check (ADR 0014). A stored path is never treated as pre-validated. Adding a favorite also validates the path against the node's enabled roots using the same function P2 uses at session creation, and stale favorites (root removed, node disabled/deleted, path now outside a root) are surfaced as explicitly unusable with a reason rather than failing silently.

### Node removal stays a soft delete

Unchanged from ADR 0011: `nodes.deleted_at` + retained audit. No destructive hard delete in MVP.

## Consequences

- **Behaviour change, not just addition.** Users who could previously terminate or take over any session no longer can. Existing P2 tests encode the old permissive expectation and must be updated in the same change; the release notes must state it.
- Adding a route without adding it to the permission matrix test fails CI. This is intentional friction.
- Denials are uniform, which costs some debuggability: an operator seeing a 403 needs the `authz.denied` audit row plus the `request_id` log to tell "wrong role" from "wrong owner". Both are recorded.
- Rejected: **per-resource ACLs / sharing** (three fixed roles plus ownership covers the MVP; ACLs need a UI and a data model P4 will not build); **custom roles or a permission-editing UI** (permissions stay defined by migration, so they are reviewable and reversible); **auditing every 403** (noise); **a background retention job** (see above); **keeping `/ws/p0/*` behind a feature flag** (a flag is a weaker guarantee than deletion, and nothing depends on it).
