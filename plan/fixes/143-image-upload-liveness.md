# #143 — Image upload completion and Session liveness

Tier: M / T2. Issue: relvo-labs/cliora#143. Base: 20a2fab47407b9d5b5b74edbb8d61700b048ee24.

## Evidence and hypotheses
User reports intermittent image upload stuck at 100% followed by hard-to-interact Session; production trigger is not yet reproduced. Image could not be inspected because vision auth expired.

Ranked, falsifiable paths on current master:
1. `connection.dispatch` directly invokes `handleFsUpload`; `SaveImage` walks quota and performs filesystem writes + Sync. A controlled slow image storage operation should delay subsequent terminal/control frames on baseline.
2. `ApiClient.uploadOnce` has no XHR timeout/ontimeout handler; progress=1 can precede the HTTP response. A complete body without response should leave upload pending indefinitely on baseline. MDN confirms timeout default 0 means unbounded wait.
3. `useImageDrop` mutates shared current/state from asynchronous callbacks without generation fencing. Delayed callbacks from a cancelled/replaced operation can alter new operation state. Reordered completions should expose the stale result.

## Sequence and acceptance
- Read project context, Vue, Go daemon, terminal protocol, security and affected backend local skills before mutations; inspect requirements ADR 0024, plan/13 and existing worker ownership.
- Build red-capable regressions for observed paths before production edits. Retain RED evidence outside repository.
- Make smallest coherent changes: bounded off-dispatch image work preserving quota serialization and workspace guards; explicit finite upload completion/error lifecycle and stale-result rejection; truthful transfer vs storage-confirmation UI. Use existing protocol/error enums; map bounded-worker refusal correctly through Central when needed.
- Check connection cancellation/late replies and rollback/no damage invariants. A worker does not make uninterruptible kernel IO cancellable; disclose residual limitations rather than claiming a hard IO deadline.
- Focused tests, affected full unit/type/lint/build checks, daemon race checks and real browser fault-path acceptance on desktop/mobile. E2E sessions must be API-cleaned in finally even on failures.
- First checkpoint commit must be pushed with Draft PR immediately after checking hosted trigger suppression. Current legacy workflows include synchronize/opened but skip draft jobs; use [skip ci] on checkpoints to avoid automatic hosted runs. Do not edit CI in this issue. Do not mark Ready with a skip marker on exact head: use a final no-skip commit while Draft, review final head, then Ready.
- One fresh independent review of frozen exact head; one consolidated repair through same writer session if necessary. Only after fresh gates and resolved blockers: Ready for Neil review. No merge/deployment authority.

## Non-goals
No generic list/search fix (#118), redesign, migrations, broader file editing, runtime change, new permission or upload destination contract. No restarting user Sessions or changing production nodes.

## Local implementation checkpoint (2026-10-07)

Base and HEAD remain `20a2fab47407b9d5b5b74edbb8d61700b048ee24` on
`fix/image-upload-liveness`; changes are uncommitted. This session's higher-priority
writer boundary forbids commits, pushes and PR operations; publication is pending
with the parent. No external writes or production operations were performed.

Controlled RED regressions confirmed the three defect classes: an upload blocked
at workspace/storage entry stalls inline control dispatch; upload XHR waits with
no finite deadline; obsolete callbacks can mutate state and return an insertable
path. The actual intermittent production trigger and screenshot details remain
unknown.

Implementation: one daemon-wide image worker, immediate NODE_BUSY admission,
strict decoding and persistence off dispatch, cancelled-connection reply fencing,
and a retained slot across disconnect until IO returns. This serializes image
quota recount/publication even for Sessions sharing a workspace. File-store was
inspected but left unchanged: its quotas are distinct and mutex-protected.
Central maps NODE_BUSY to safe HTTP 503. Browser XHR uses a 60-second deadline,
with no automatic retry of an ambiguous completion. UI distinguishes body transfer
from pending node confirmation, offers cancel, and fences callbacks and terminal
insertion on replacement, cancellation, route/terminal change and disposal.

Evidence is outside source at `/opt/data/cliora-upload-hang-run/verification/`:
- RED: frontend-red.log (7 failing, 22 passing); daemon-red.log (control deadline
  failed under held storage); backend-red.log (busy mapping failed).
- GREEN: frontend-final-full.log (53 files / 1,343 tests); frontend-final-focused.log
  (85 tests after caller fence); frontend-lint-final.log, frontend-typecheck-final.log,
  frontend-build-final.log; backend-green.log (181 tests); backend-lint.log;
  daemon-race.log (full race suite, 14 tested packages); daemon-reconnect.log and
  daemon-reconnect-quota.log (focused race regression).
- Browser: browser-final.log, 2 Chromium tests at desktop 1440 and mobile width 390;
  pending-{1440,390}.png and retry-{1440,390}.png. Native XHR talks to a task-owned
  HTTP peer which consumes the body before delaying its response; Central and
  terminal relay are local fixtures. The spec owns/cleans its HTTP server and
  timers in finally, and creates no backend Sessions. This is viewport evidence,
  not physical mobile-device or full-stack production evidence.

Remaining limits: kernel IO cannot be interrupted by cancellation; one hung image
write retains the upload slot and later uploads receive NODE_BUSY, while control
traffic/reconnect remain usable. A cancelled/timed-out request may still persist a
retention-managed image; retry can add another image. Admission limits daemon-owned
workers, not writes made independently by a user CLI. Full-stack upload tests against
an isolated Central database, actual device acceptance, publication and the parent's
fresh frozen-head review remain pending. No Ready/reviewer action was taken.
