# Security review — plan/28 (visual refresh)

- Date: 2026-09-08
- Scope: `frontend/src`, `frontend/public`, `frontend/index.html`, `scripts/vr/`,
  documentation and traceability. **No file under `backend/`, `daemon/`,
  `contracts/` or `deploy/` was touched**, and no contract version changed.
- Related: ADR 0027 (this phase), ADR 0016 (RBAC, fonts, no CDN in `dist`),
  ADR 0017 (CSP), ADR 0015 (read-only preview), ADR 0023 (privileged posture),
  ADR 0024 / 0026 (the two write paths)

The seven questions are the ones `plan/28/06-verification-and-exit.md` §6 asks.
Each answer carries its evidence, because "we did not change authorization" is
exactly the kind of claim that is easy to make and easy to be wrong about.

---

## 1. Did any UI change relax authorization?

**No. Every display condition is byte-for-byte identical.**

The risk is real rather than theoretical: this phase moved the navigation rail
into a new component, moved three status indicators out of the work header, and
moved Terminate into an action menu. Any of those was an opportunity to
accidentally simplify a condition.

**The three navigation permission checks.** They moved from `AppLayout.vue` to
`PrimaryNav.vue`. Diffed as text:

```
$ git show HEAD:frontend/src/components/layout/AppLayout.vue \
    | grep hasPermission
  auth.hasPermission(ACTION_ENROLLMENT_MANAGE),
const canViewAudit = computed(() => auth.hasPermission(ACTION_AUDIT_VIEW));
  auth.hasPermission(ACTION_INTEGRATION_MANAGE),

$ grep hasPermission frontend/src/components/layout/PrimaryNav.vue
  auth.hasPermission(ACTION_ENROLLMENT_MANAGE),
const canViewAudit = computed(() => auth.hasPermission(ACTION_AUDIT_VIEW));
  auth.hasPermission(ACTION_INTEGRATION_MANAGE),
```

**The workspace capability checks**, including both upload gates:

```
$ diff <(git show HEAD:frontend/src/views/SessionWorkspaceView.vue \
           | grep -E "capabilities\.value\?\.|canUpload(Images|Files) = |nodePosture\.value\?\.(image_upload|file_upload|privileged_terminal)") \
       <(grep -E "capabilities\.value\?\.|canUpload(Images|Files) = |nodePosture\.value\?\.(image_upload|file_upload|privileged_terminal)" \
           frontend/src/views/SessionWorkspaceView.vue)
$ echo $?
0
```

Identical. That covers `can_terminate`, `can_takeover`, `can_browse_files`,
`can_open_shell`, `canUploadImages` and `canUploadFiles` — including the double
condition on the two upload paths (a server-side capability **and** the node's
own report), which ADR 0024 §2 and ADR 0026 require.

**Two things this phase did change about permission-adjacent UI, both
deliberately in the safe direction:**

- **The collapsed rail hides labels, never items.** An item hidden for lack of
  permission stays hidden in both states. If collapse had removed items from the
  DOM instead, "hidden because collapsed" and "hidden because unauthorized"
  would have become indistinguishable to anyone reading the DOM.
- **Below 768px the rail becomes a menu, and the terminal's input permission
  does not change.** `research/style.md` §24 previously said "tablet is
  read-only mode", which stated a *layout* decision as an *authorization* one.
  That sentence is removed and replaced with the opposite rule in writing:
  reachable is not the same as permitted, and device width does not alter what
  the user may type.

**Not done, on purpose:** no client-side route guard was added. `router/index.ts`
already carries the note explaining why (a client guard decides what renders,
not what is allowed), and `/audit` and `/settings/integrations` still reach the
server and show its 403.

---

## 2. Is `public/theme-boot.js` inside the CSP?

**Yes, and that is why it is a file rather than an inline script.**

The CSP is `script-src 'self'` with no `'unsafe-inline'`
(`deploy/nginx/nginx.conf:134`, `deploy/railway/nginx.conf.template:114`), and
neither file was modified by this phase. An inline bootstrap would be blocked by
the browser, and the symptom would be the worst kind: "the theme sometimes
doesn't apply", with no error the user could report usefully.

It is referenced from `index.html` as `<script src="/theme-boot.js">`, served
from the same origin, and adds no `connect-src`, `img-src` or `font-src`
requirement. It is in `public/` rather than `src/` so Vite does not hash the
name and the path in `index.html` can be fixed.

What it is allowed to do is bounded by a gate rather than by a promise
(`GATE-VR-NO-GLYPH-ICON`, second half):

```
$ scripts/vr/vr-gates.sh glyph-icon
ok: theme-boot.js is 9 code lines, imports nothing
```

The gate fails if the file exceeds 12 code lines, if it contains `import`,
`require(`, `fetch(` or `eval(`, or if it is missing entirely. All four failure
modes were exercised:

```
17 code lines  -> FAIL: frontend/public/theme-boot.js has 17 code lines (limit 12).
fetch("/x")    -> FAIL: frontend/public/theme-boot.js imports or fetches something.
file removed   -> FAIL: frontend/public/theme-boot.js is missing — the theme would
                        apply after first paint (FOUC).
```

The script reads one `localStorage` key, validates it against exactly the two
shipped theme ids, and sets one attribute. A stale or hand-edited value is
rejected rather than written through, so it cannot produce a `data-theme`
attribute that no CSS rule matches.

**Outstanding:** the browser-side confirmation that no CSP violation is logged
needs a deployed edge. `frontend/tests/e2e/theme.spec.ts` contains that
assertion ("no CSP violation from the boot script"); it runs in CI with the full
stack and is listed in `skipped.txt` for any local pack.

---

## 3. What does `localStorage` hold?

**Four display preferences. No identifier, no token, no path.**

```
$ grep -rn "localStorage.setItem" frontend/src frontend/public | grep -v test
frontend/src/stores/preferences.ts:78:    localStorage.setItem(key, value);
frontend/src/stores/auth.ts:34:      localStorage.setItem(ACCESS_KEY, pair.access_token);
frontend/src/stores/auth.ts:35:      localStorage.setItem(REFRESH_KEY, pair.refresh_token);
```

The two `auth.ts` writes are pre-existing and untouched. `preferences.ts` is the
only new writer, and it writes exactly four keys:

| Key | Value | Type |
|---|---|---|
| `cliora-theme` | `graphite` \| `porcelain` | a theme id |
| `cliora-nav-collapsed` | `true` \| `false` | a boolean |
| `cliora-terminal-font-size` | 12–20 | a number |
| `cliora-inspector-width` | 220–360 | a number |

The one worth stating explicitly, because it is the near miss: **the file panel
stores its *width*, not the directory that was open in it.** A width is a
number; a path is user data and would be a new disclosure in a place nobody
would think to look for one.

Reads are bounds-checked rather than clamped: a stored value outside its range is
treated as absent, so a hand-edited or corrupted entry produces the default
rather than a value the user never chose. Writes are best-effort and wrapped —
private mode and blocked-storage origins throw, and a preference that cannot be
saved still applies for the session.

---

## 4. Are there any new external requests?

**No. One fewer, in fact, in the sense that matters.**

```
$ grep -rE "https?://(fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg|jsdelivr)" dist/
$ echo $?
1
```

ADR 0016's build-time rule ("`dist` carries no CDN reference") still holds. This
phase ships **no font files and adds no webfont**: `research/style.md` §22 named
Inter and JetBrains Mono, and this phase replaced both with the system stacks
that were actually in use. That is a correction, not a change of policy —
`useTerminalSession.ts:216` asked for `"JetBrains Mono"`, which has never been
bundled, so the terminal has always rendered in whatever came next in the list.
Deleting the name makes the code agree with ADR 0016.

Lucide icons are bundled Vue components rendering inline `<svg>` elements. They
are not `<img>` tags and not fetched sprites, so `img-src` is unaffected.

Bundle measurement (VR-01 §4), gzip, both builds on this host:

| | before | after | delta |
|---|---:|---:|---:|
| JS | 1023.0 kB | 1037.7 kB | **+14.7 kB** |
| CSS | 30.1 kB | 34.7 kB | **+4.6 kB** |

+19.3 kB gzip total, under the 20 kB threshold plan/28 set as the signal that
tree-shaking had failed — and that figure is the *net* of twelve new Lucide
icons plus eleven new components. Removing `naive-ui` contributes nothing to it
because it was never imported, so it was never in the bundle to begin with; what
its removal changes is §7.

---

## 5. Can a displayed path leak a node's absolute path?

**No wider than before. One display surface is new; its content is not.**

`SessionHeader` shows the workspace path with middle truncation, a `title`
holding the full value, and a copy button. All three are new *affordances*. The
value is `session.workspace`, which was already rendered in the work header
(`SessionWorkspaceView.vue:478-480` before this phase) and comes from the same
API field. Nothing that was hidden became visible.

Two boundaries were checked and are unchanged:

- **The file tree still receives only the folder name.** `workspaceLabel` takes
  the last path segment; the node's absolute path does not reach the tree (the
  P3 relative-path rule).
- **Preview and upload paths are unchanged.** `PreviewPane`, `FileTree` and the
  upload queue pass the same relative paths as before.

Middle truncation was chosen over end truncation for a reason that is about
usefulness rather than disclosure: eliding the end removes the directory name,
which is the segment carrying the information. Either way the full value is
already in `title`, so truncation is not a confidentiality control and is not
treated as one.

---

## 6. Can a new component leak server detail into an error message?

**No, and the type system now refuses the shape that would.**

`ErrorNotice` keeps its four-part structure from `docs/error-catalog.md` (safe
message, cause, next step, request id) with its logic unchanged — the phase only
restyled it.

The two new message components take **`message?: string`, deliberately not
`unknown`**:

```ts
// UiInlineNotice
/**
 * Only a string. Deliberately not `unknown`: given a wider type, the next
 * caller passes a caught exception straight through, and an exception's
 * message can carry server internals.
 */
message?: string;
```

With an `unknown` prop the convenient thing to write is
`<UiInlineNotice :message="caught" />`, and that ships whatever the server said —
a stack frame, a query, an internal host name. Turning a failure into a sentence
a user can act on stays the caller's job, through `utils/errorCatalog`.

`Toast` goes further: **its type has no error member at all.**

```ts
export type ToastKind = "success" | "info";
```

This is a correctness rule as much as a security one — a message that removes
itself after four seconds is one the user may never have read — but it also means
no failure text can reach the one component that disappears on a timer. Upload
failures, terminate failures and connection failures all stay in the region they
belong to.

---

## 7. What does removing `naive-ui` do to the supply chain?

**22 packages fewer, and the dependency was never used.**

```
$ python3 -c 'import json; print(len(json.load(open("frontend/package-lock.json"))["packages"]))'
355            # was 377
```

Removed: `naive-ui`, `@css-render/plugin-bem`, `@css-render/vue3-ssr`,
`@emotion/hash`, `@juggle/resize-observer`, `@types/katex`, `@types/lodash`,
`@types/lodash-es`, `async-validator`, `css-render`, `css-render/csstype`,
`date-fns`, `date-fns-tz`, `evtd`, `highlight.js`, `lodash`, `lodash-es`,
`seemly`, `treemate`, `vdirs`, `vooks`, `vueuc`. Nothing was added.

`npm audit --audit-level=high` reports 0 vulnerabilities after the change, and
the build succeeds without any of the 22 present.

The justification for removing rather than retaining is in ADR 0027 §6 and is
worth restating here because it inverts the shared design foundation's wording:
that document says integration "retains … Naive UI", but Naive UI had **zero**
components in use, **one** type-only import, and that import's file was itself
imported by nothing. Retaining something never used is introducing it. The four
accessibility behaviours the foundation expected from it are hand-built instead
(`useFocusTrap`, ~130 lines, shared by the dialog and the file drawer) — two of
the four already existed and were correct.

Reduced surface, no new surface, and 22 fewer packages whose transitive updates
this project no longer tracks.

---

## Verdict

No finding. No authorization surface, wire contract, CSP, or write path changed.
The changes that touch security-adjacent behaviour all move in the same
direction:

- one sentence that stated a layout decision as an authorization decision is
  removed from `research/style.md` §24, and replaced by the explicit opposite;
- 22 packages leave the supply chain;
- two new message components cannot be handed an exception object;
- a font name that never resolved is deleted, so the code matches ADR 0016;
- `localStorage` gains four values, none of which is an identifier, a token, or
  a path.

**Still to run, on a host with a browser and a full stack** (listed in
`artifacts/vr/local/skipped.txt`, not silently omitted):

1. no CSP violation from `theme-boot.js` against the real edge configuration;
2. the theme switch leaving the session, scrollback and unsent input intact
   (`NFR-006.AC-07`, `FR-TERM-001.AC-15`);
3. the 36-cell acceptance matrix.

None of the three can change the answers above — they are all display
behaviour — but until they run, item 2 in particular is an argument rather than
a measurement, and the exit report should say so.
