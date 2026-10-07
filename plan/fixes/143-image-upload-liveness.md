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

## Implementation and remaining boundaries

Implementation PR: #144. Controlled regressions confirm all three defect classes;
the production-specific trigger remains unknown.

Image persistence has one daemon-wide admission slot, preserving image-quota
serialization across Sessions and reconnects. Excess uploads receive `NODE_BUSY`
(HTTP 503); file-store quotas remain separate and unchanged. UI separates body
transfer from storage confirmation, supports cancellation and a 60-second deadline,
and fences stale state/path insertion on replacement, route/connection/role change
and disposal. No automatic retry of an ambiguous write.

Kernel I/O cannot be forcibly interrupted: a hung write retains the image slot,
while control traffic and reconnect remain usable. Cancellation/timeout may leave
a retention-managed image; manual retry can add another. Admission does not govern
independent user-CLI writes.

Regression coverage includes slow persistence/control liveness, reconnect and
quota admission, XHR completion/error handling, stale callback fencing, and native
XHR fault-state browser tests at desktop/mobile widths. Browser Central and
terminal peers are fixtures, not full-stack or physical-device certification.
Detailed validation and production-acceptance tracking live in #143 / #144;
raw logs and screenshots remain repository-external. No merge or deployment.
