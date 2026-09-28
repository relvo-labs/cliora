# Security review — read-only binary preview (plan/31, ADR 0029)

**Status: not started.** The review itself is `BP-08`'s (plan/31/06), an independent,
read-only pass over the implementation; its verdict gates `BP-11`, and a `FAIL` reopens
ADR 0029. Nothing above the appendix is written yet, and nothing in the appendix is a
verdict. The appendix is the evidence `BP-07` owes that review (plan/31/05 `BP-07` §1,
§5): the review of the one new dependency, done **before** any PDF component was written.

---

## Appendix A — `BP-07` dependency review: `pdfjs-dist` (2026-09-28)

Collected by the `BP-07` writer. Each row names the command or file it came from, so
`BP-08` and the `BP-11` pre-release recheck can repeat it.

### A.1 Version and advisories

| Item | Evidence | Result |
|---|---|---|
| Latest release | `npm view pdfjs-dist dist-tags time`: `latest` = **6.3.289**, published 2026-08-29T12:52Z. The previous release is 6.2.108 (2026-07-28) | 6.3.289 is the latest stable release and above the ≥ 6.2.108 floor (ADR 0029 §12) |
| Pin | `frontend/package.json`: `"pdfjs-dist": "6.3.289"` (exact, no `^`). Lockfile: `resolved https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.3.289.tgz`, `integrity sha512-ZHjSVpDa3D6izMq8/04lvkhkATUmL9px6ChPaXc1k6nU2Mrhlg1/7F0bdUqCwUjw3NsPTfPZsMDUU6ZIcRaeQw==` | pinned |
| Published advisories for the package | `gh api '/advisories?ecosystem=npm&affects=pdfjs-dist'` (2026-09-28): three, none withdrawn. **CVE-2026-16633 / GHSA-hq66-cqwq-w95j** (high, `>= 5.6.83, < 6.2.108`, patched 6.2.108); **CVE-2024-4367 / GHSA-wgrm-67xf-hhpq** (high, `<= 4.1.392`, patched 4.2.67); CVE-2018-5158 / GHSA-7jg2-jgv3-fmr4 (high, `< 2.0.550`) | all three are patched in the pinned version |
| Advisories affecting the pinned version | `gh api '/advisories?ecosystem=npm&affects=pdfjs-dist@6.3.289' --jq length` → **0** (2026-09-28T05:49Z) | none open |
| Advisories affecting the transitive dependency | `gh api '/advisories?ecosystem=npm&affects=@napi-rs/canvas' --jq length` → **0** | none |
| `npm audit` | Before the pin (`HEAD` lockfile) and after it: the **same six findings**, none in `pdfjs-dist` or `@napi-rs/*`. They are dompurify (moderate ×4, via monaco-editor; monaco itself is listed as low), @vitest/mocker / vitest (moderate, dev), postcss (moderate, dev) and js-yaml (high, dev tooling). Raw JSON: `npm audit --json`, compared by package name | no finding introduced; the six **pre-existing** ones are reported separately (see A.8) |

**Recheck gate.** The advisory query and `npm audit` must be run again before `BP-11` starts
(plan/31/05 `BP-07` §1). Any open advisory against the pinned version blocks release.

### A.2 Licences

| Package | Version | Licence | How it is present |
|---|---|---|---|
| `pdfjs-dist` | 6.3.289 | Apache-2.0 (`node_modules/pdfjs-dist/LICENSE`) | direct dependency; the display build, the worker and the assets below |
| `@napi-rs/canvas` | 1.0.9 | MIT | **optional** dependency of `pdfjs-dist`, used only by PDF.js running in Node (`NodeCanvasFactory`, reached through `process.getBuiltinModule("module").createRequire(...)`) |
| `@napi-rs/canvas-linux-x64-gnu` (and one per platform in the lockfile) | 1.0.9 | MIT | prebuilt native binary for that optional dependency; npm installs only the one for the host platform (about 34 MB) |

Neither `@napi-rs` package has an install script (`npm view … scripts`: only the
publisher's build, test and release scripts; no `preinstall`, `install` or `postinstall`). The
native module is **not** in the browser bundle: the only occurrence of the name in `dist/` is
the string inside the unreachable Node-only branch of the PDF.js chunk. It still lands in
`node_modules` on every `npm ci`, which is a supply-chain surface of the build machine, not of
the product. `BP-08` should decide whether that is acceptable. Omitting optional dependencies
globally is not an option, because Vite's own native bindings (rollup, esbuild) are optional too.

Bundled asset licences (read from each file; the licence files ship alongside the assets under
`dist/pdfjs/`):

| Asset | Licence |
|---|---|
| `wasm/openjpeg.wasm` (+ JS fallback) | OpenJPEG, BSD 2-clause (`LICENSE_OPENJPEG`) |
| `wasm/jbig2.wasm` (+ JS fallback) | PDFium, BSD 3-clause style (`LICENSE_JBIG2`) |
| `wasm/qcms_bg.wasm` | MIT (`LICENSE_QCMS`) |
| `standard_fonts/Foxit*.pfb` | PDFium, BSD 3-clause style (`LICENSE_FOXIT`) |
| `standard_fonts/Liberation*.ttf` | **GNU GPL v2 with a font exception**, under Red Hat's Liberation EULA (`LICENSE_LIBERATION`). The exception covers documents that embed the font; serving the font files themselves from our origin is redistribution under GPLv2. That is compatible with shipping the licence next to them, as done here, but it is the one copyleft item in the dependency, so it is flagged for `BP-08` / release (A.8) |
| `iccs/CGATS001Compat-v2-micro.icc` | CC0 1.0 (`iccs/LICENSE`) |
| `cmaps/*.bcmap` | covered by the package's Apache-2.0 `LICENSE` (no separate file) |

### A.3 What the pinned release does with the locked options

Read from `node_modules/pdfjs-dist/build/pdf.mjs` and `pdf.worker.mjs` at 6.3.289:

| Option | Consumer in 6.3.289 | Consequence |
|---|---|---|
| `enableScripting` | **Not read by `getDocument`.** Read only by the annotation layer (`AnnotationLayer`, `params.enableScripting === true`) and by the viewer (`web/pdf_viewer.mjs`) | The option alone controls nothing here. The controls are structural: no annotation DOM is ever built (`src/pdf/imports.test.ts` forbids the names), and the scripting sandbox is neither imported (`pdf.sandbox*` is forbidden by the same test) nor shipped (next rows). Kept in the locked set for the day a release reads it again |
| `isEvalSupported` | **Not present anywhere** in the build (0 occurrences in `pdf.mjs`, `pdf.worker.mjs`, `pdf.sandbox.mjs`) | The CVE-2024-4367 class (glyphs compiled with `new Function`) has no code path left. The CSP (no `'unsafe-eval'`) remains the second layer. The E2E `cve_2024_4367_shape` checks that the shape stays inert |
| `enableXfa`, `disableAutoFetch`, `disableStream`, `disableRange`, `stopAtErrors` | read by `getDocument` (`src.enableXfa === true`, `src.stopAtErrors !== true` → `ignoreErrors`, …) | effective as intended |
| `cMapUrl`, `standardFontDataUrl`, `wasmUrl`, `iccUrl` | read by `getDocument`. All four same-origin, so `useWorkerFetch` becomes true and the **worker** fetches them (`connect-src 'self'`) | `iccUrl` is not in plan/31/05's list. It was added because this release ships `iccs/` for CMYK conversion, and self-hosting it keeps "no third-party origin" true |
| `data` (bytes, not `url`) | `getDataProp`; the buffer is **transferred** to the worker | no network stream, no range request; the console's own copy is detached |

**The scripting engine.** `wasm/` in this release also contains `quickjs-eval.js` and
`quickjs-eval.wasm`, a JavaScript engine loaded **only** by `build/pdf.sandbox.mjs`
(`${wasmUrl}quickjs-eval.js`, `pdf.sandbox.mjs:202`). Copying `wasm/` wholesale would have
put a document-JavaScript engine on the origin. `vite.config.ts` copies `wasm/` **without**
`quickjs-eval.*`, the unit test `the self-hosted assets never include the scripting engine`
asserts it, and the E2E `bundle_initial_chunk_unchanged` asserts the built site does not
serve it.

**The fake worker.** Given a `workerSrc`, PDF.js falls back to parsing on the main thread if the
worker fails to start (`#setupFakeWorker`, which `import()`s the worker module into the page).
`src/pdf/setup.ts` creates the `Worker` itself and hands it over as a `port`
(`PDFWorker.create({ port })`), a path with no fallback, and terminates it on every disposal.

### A.4 Worker and asset paths

| Asset | Source in the package | Served at |
|---|---|---|
| Worker | `pdfjs-dist/build/pdf.worker.min.mjs`, imported with `?url` (emitted verbatim, hashed) | `/assets/pdf.worker.min-<hash>.mjs`, a same-origin module worker (`worker-src 'self'`) |
| Display API | `pdfjs-dist` (`build/pdf.mjs`), dynamically imported with the first PDF | `/assets/setup-<hash>.js` |
| CMaps, standard fonts, wasm, ICC | `cmaps/`, `standard_fonts/`, `wasm/` (minus QuickJS), `iccs/` | `/pdfjs/<dir>/<file>`, emitted by the self-written `cliora-pdfjs-assets` plugin in `vite.config.ts` (no new plugin dependency); served from `node_modules` by the same plugin in `vite dev` |

Never imported: `pdfjs-dist/web/*` (viewer), `pdfjs-dist/legacy/*`, `build/pdf.sandbox*`.

### A.5 Size

`npm run build`, byte counts from `stat` (gzip -9 in brackets):

| Output | Before BP-06 | After BP-06 | After BP-07 |
|---|---:|---:|---:|
| Initial load: `index-*.js` | 134 481 | 135 058 | **135 058** (PDF.js adds 0) |
| Initial load: `index-*.css` | 16 061 | 16 061 | 16 061 |
| Lazy: PDF.js display chunk `setup-*.js` | — | — | 437 614 (130 318) |
| Lazy: `PdfPreview-*.js` | — | — | 6 811 (3 158) |
| Lazy: worker `pdf.worker.min-*.mjs` | — | — | 1 265 413 (374 166) |
| On demand: `dist/pdfjs/` (all four dirs) | — | — | 3 050 547 (cmaps 1.7 MB, fonts 820 KB, wasm 1.1 MB, ICC 24 KB); a document fetches only what it uses |

The +577 bytes in the initial chunk belong to `BP-06`: the `fetchBinaryPreview` request method
in `api/client.ts` and the `stores/binaryPreview.ts` store that `router/authLoss.ts` must import.
Both sit in the first-load graph because the plan puts them there (plan/31/09 DV-19).

### A.6 CSP (`BP-OM-04`)

Run against the built bundle (`vite preview`), with the **production header string** read from
`deploy/nginx/nginx.conf` and injected on every non-API response (as nginx's server-level
`add_header` applies it to every static file, the worker included). The browser is Chromium
(Playwright `chromium` and `mobile-chrome-emulated` projects, headless shell revision 1234):

- `binary-preview-pdf.spec.ts#no_csp_violation`: a CJK PDF loads
  `/pdfjs/cmaps/UniCNS-UCS2-H.bcmap` and `Adobe-CNS1-UCS2.bcmap` (200), and a JPX PDF loads
  `/pdfjs/wasm/openjpeg.wasm` (200, `application/wasm`). `securitypolicyviolation` events: 0.
  Console CSP messages: 0. Every request went to the page's own origin.
- Every other PDF and image E2E asserts 0 violations as well.

**Result: no CSP change is needed** in Chromium. WebKit and Firefox were not run: their
Playwright browsers are not installed on this host. iOS Safari and Android Chrome on devices
belong to `BP-10`.

A limitation of the CJK check: headless Chromium here has no CJK system font, so the
non-embedded CID font renders blank. The CMap path works under the CSP; whether the glyphs are
**correct** is a device check (plan/31/08 `BP-10` #6).

### A.7 Browser floor (`BP-OM-07`, OD-9) and the encrypted-but-openable signal (`BP-OM-12`)

- **Floor.** The modern build calls these builtins without a fallback (grep of
  `build/pdf.mjs` / `pdf.worker.mjs`): `Map.prototype.getOrInsertComputed` (17 / 16 call
  sites), `Math.sumPrecise` (1 / 14), `Promise.try` (4 / 4) and `Uint8Array.fromBase64`
  (1 / 1). The legacy build polyfills them (core-js). So the modern build needs a **current**
  engine. That matches PRD `NFR-005` ("前端支援最新版" Chrome, Edge, Safari, Firefox), and
  OD-9 (a) stands. `src/pdf/setup.ts#pdfSupported` checks exactly these four plus `Worker`:
  an older engine gets `unsupported_browser` before anything is fetched, rather than failing
  mid-document. The device matrix still has to confirm that the oldest supported iPhone on
  the latest Safari passes (`BP-10`). If it does not, OD-9 returns to the product owner for
  (b), the legacy build.
- **Encrypted but openable.** OD-8 is (a), so this is reported only. A signal exists in
  6.3.289: after opening without a password, `pdf.getMetadata()` returns
  `info.EncryptFilterName` (non-null, e.g. `Standard`, when the file has an `/Encrypt`
  dictionary; `pdf.worker.mjs:60190`), and `pdf.getPermissions()` returns a non-null set
  (`#readPermissions`, `pdf.worker.mjs:40777`). It is not used. It would only matter if OD-8
  changed to (b).

### A.8 Items for the coordinator

- Six pre-existing `npm audit` findings (A.1), not introduced here. The runtime ones come via
  `monaco-editor` → `dompurify`.
- The optional native dependency `@napi-rs/canvas` enters `node_modules` with `pdfjs-dist`
  (A.2); a decision for `BP-08`.
- The self-hosted Liberation standard fonts are GPLv2 with a font exception (A.2); a
  licence acknowledgement for the release (`BP-11`). If it is not wanted, `standard_fonts/`
  can drop the `Liberation*` files. PDF.js is then expected to fall back to system fonts for
  the standard 14, but that is **not verified** here.
