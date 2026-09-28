# 05 — 前端（`BP-06` 生命週期與圖片／`BP-07` PDF.js）

兩張票刻意拆開：`BP-06` **不新增依賴**，可以先把「單一 owner、清理、狀態、session 綁定」
這一半獨立審完；`BP-07` 只多一件事，就是 PDF.js 與它的供應鏈。

## 0. 共同規則

- 只用 `theme/tokens.css` 的語意 token，**沒有任何字面色彩**（`GATE-VR-NO-LITERAL-COLOR`）。
  canvas 的背景與邊框也不例外：預覽底色取 `--surface-*` token 的計算值再畫。
- 共用元件先用 `components/ui/`；圖示按鈕用 `UiIconButton`（`label` 必填）。失敗訊息放在
  `UiInlineNotice`／`ErrorNotice`，**不用 Toast**。
- `message?: string`，不把 `caught` 直接丟進畫面。
- 行動端是全幅、files 的子狀態，返回鍵行為沿用 plan/29 `MS-07`／`MS-08`；
  返回時保留資料夾、搜尋與捲動位置，並把焦點還給開啟預覽的那一列（plan/29 `MS-16`）。
- 路徑**不進 URL、不進 history state**（#76 的既有規則）。

## `BP-06` 生命週期與圖片

**寫入集：** `composables/useBinaryPreview.ts`（新）、`stores/binaryPreview.ts`（新，只放
`clear()` 與 metadata）、`components/file/ImagePreview.vue`（新）、`PreviewPane.vue`
（路由分支）、`PreviewDenied.vue`（新分支文案）、`api/client.ts` 與 `api/dto.ts`（新方法
`fetchBinaryPreview` 與 `can_preview_binary`）、`utils/auditActions.ts`（標籤）、
`router/authLoss.ts`（`wipeUserScoped` 加**一行**）。

**前置：** `BP-04` 合併；**#76 已合併**（沒有它，auth-loss 與 session 綁定沒有地方掛）。

### 1. 路由：誰走文字，誰走二進位

```
canPreviewBinary = capabilities.can_preview_binary === true      // 伺服器合成，ADR 0029 §9
routeHint(relPath) = /\.(png|jpe?g|webp|gif|pdf)$/i              // 只是提示，不是授權
```

| `canPreviewBinary` | `routeHint` | 走哪條 |
|---|---|---|
| true | 命中 | `fetchBinaryPreview` |
| true | 未命中 | 既有 `readFileContent`（文字） |
| false | 任何 | 既有 `readFileContent`；遇到 `FILE_BINARY` 時顯示既有面板，**不變** |

daemon 回 `FILE_PREVIEW_UNSUPPORTED`/`unsupported_type` 時（例如 `notes.pdf` 其實是文字），
面板提供「改用文字預覽」。那是讀取另一條**既有**路徑，不是降級成下載。

### 2. `useBinaryPreview`：唯一的 owner

它擁有且只有它擁有：`AbortController`、`Uint8Array`、`ImageBitmap`、PDF.js 的
loading task 與 document（`BP-07`）、所有 canvas。大物件全部 `markRaw`／`shallowRef`，
不進 Pinia 的 reactive state。

**取得：** `POST /api/sessions/{id}/files/binary-preview`，路徑放在 JSON body `{"path": …}`，
**URL 不帶任何 query**（ADR 0029 §6：URL 會進 access log）。`fetch` 帶 `signal`，以 `ReadableStream` 讀取，累計長度不得超過
`Content-Length` 與 `X-Cliora-Preview-*` 宣告的上限。讀完後長度必須等於 `Content-Length`，
否則當成 `transfer_failed`。進度（已收／總量）透過 `aria-live="polite"` 以節流方式宣告。

**圖片解碼：** 先依標頭的寬高再檢查一次上限（縱深防禦），再
`createImageBitmap(new Blob([bytes], {type: mime}), {imageOrientation: "from-image"})`，
畫到 `<canvas role="img" aria-label="{檔名}，{寬}×{高} 像素">`。
`bitmap` 畫完後保留（縮放要用），`Uint8Array` 立即丟棄。

**縮放：** 預設符合寬度；工具列 ＋／−／符合寬度，每個 ≥ 44×44；pointer events 做雙指縮放與拖曳。
backing canvas 的像素數永遠 ≤ 16 777 216，超過時改用 CSS transform 放大，不再重畫。

### 3. 清理：觸發與動作

| 觸發 | 來源 | 動作 |
|---|---|---|
| 預覽路徑改變、關閉、元件卸載 | `PreviewPane` | 完整 dispose |
| session id 改變 | `sessionId` watch（同 `stores/files.ts:138-146` 的 `useSession` 規則） | 完整 dispose，**先清再換** |
| `can_preview_binary` 變 false | capability watch | 完整 dispose，改顯示既有面板 |
| 登出、另一分頁登出、refresh 被拒 | #76 `authLoss.ts` 的 `isAuthenticated` watch（`flush:"sync"`） | `binaryPreview.clear()` → 完整 dispose |
| 使用者 id 改變 | #76 `authLoss.ts` 的 `user.id` watch | 同上 |
| identity pending | #76 `authLoss.ts` 的 `identityPending` watch | **只 abort**，保留畫面（可能是同一人） |
| 遲到的回應屬於別的 session | 請求發出時記下 session id | 丟棄，不畫（同 `stores/files.ts:199-202`） |

**完整 dispose** 的順序：abort fetch → `renderTask.cancel()` → `pdf.destroy()`（`BP-07`）→
`bitmap.close()` → 每個 canvas `width = height = 0` → 丟掉 `Uint8Array` → 狀態回 `idle`。
object URL：**設計上不建立**。若日後裝置 fallback 需要，由同一個 owner 建立，並在上表每一個觸發點 revoke。

### 4. 狀態與文案（每一種都要能區分，不共用空狀態）

| 狀態 | 何時 | 使用者看到的下一步 |
|---|---|---|
| `loading` | 取得中 | 進度與「取消」 |
| `ready` | 已畫出 | 縮放／翻頁 |
| `cancelled` | 使用者取消或離開 | 回到清單，不顯示錯誤 |
| `denied_sensitive` | `FILE_DENIED` + 敏感分類 | 無；「此檔案受保護，不提供預覽」。不顯示片段、不顯示解析後名稱 |
| `denied_access` | `FILE_DENIED`（其他）、`FILE_NOT_FOUND` | 重新整理清單。措辭不利於路徑試探 |
| `permission` | `FILE_PERMISSION_DENIED` | 洽節點擁有者 |
| `too_large` | `FILE_TOO_LARGE` | 顯示實際大小與上限；「用終端機處理」 |
| `limit` | `FILE_PREVIEW_LIMIT` | 顯示是像素、邊長還是複雜度；**不提供下載** |
| `invalid` | `FILE_PREVIEW_INVALID`/`malformed` | 「檔案可能損毀」；**不提供下載** |
| `changed` | `FILE_PREVIEW_INVALID`/`changed` | 「檔案正在變動」，提供重試 |
| `unsupported` | `FILE_PREVIEW_UNSUPPORTED`/`unsupported_type` | 「改用文字預覽」（§1） |
| `pdf_password_required` | PDF.js 要求密碼（`loadingTask.onPassword` 被呼叫，或 `PasswordException`） | 「此 PDF 需要密碼才能開啟，預覽不支援」（OD-8）。**不顯示密碼輸入框**；`onPassword` 直接 `loadingTask.destroy()`，不呼叫它的 callback |
| `pdf_too_many_pages` | `numPages` > 上限 | 顯示頁數與上限 |
| `render_failed` | 瀏覽器解碼或渲染失敗 | 「此瀏覽器無法顯示這個檔案」；**不提供下載** |
| `unsupported_browser` | 沒有 `createImageBitmap`，或 PDF.js 無法載入 | 說明是瀏覽器限制（OD-9） |
| `offline` | `NODE_OFFLINE` | 節點離線，常駐的行內錯誤加誠實的重試 |
| `forbidden` | 403 | 「沒有權限檢視檔案」 |
| `busy` | 429／`NODE_BUSY` | 稍後重試 |
| `transfer_failed` | 長度不符、`FILE_PREVIEW_EXPIRED`、逾時 | 重試 |
| `session_ended` | session 已結束 | 不發請求，不顯示按了沒用的重試 |

GIF 在 `ready` 時加一行標示：「動畫僅顯示第一幀」（OD-1）。
**任何一個狀態都沒有「下載」或「另存」。** #71 合併後，下載入口由它自己的條件決定，
不放在上表的 `limit`／`invalid`／`render_failed` 裡（ADR 0029 §16、T16）。

### 5. 先寫的 RED 測試（Vitest，fresh Pinia，**不預先綁 store**，#76 的教訓）

| 測試 | 斷言 |
|---|---|
| `routes_by_capability_then_hint` | 三列路由表 |
| `path_travels_in_body` | `fetchBinaryPreview` 送出的是 POST、`Content-Type: application/json`，URL 以 `/binary-preview` 結尾且**沒有 `?`**，路徑只出現在 body |
| `session_switch_mid_transfer_never_paints` | A 的回應在切到 B 之後才到 → canvas 從未被畫、狀態是 B 的 |
| `auth_loss_clears_in_same_tick` | 觸發 `isAuthenticated=false` → 同一個同步呼叫內 `bitmap.close` 已呼叫、canvas 0×0 |
| `user_switch_clears` | `user.id` 由 u1 → u2 → 已 dispose |
| `identity_pending_aborts_only` | 只有 abort，畫面保留 |
| `capability_drop_clears` | `can_preview_binary` true → false → dispose，並顯示既有 `FILE_BINARY` 面板 |
| `no_object_url_no_img` | 整個流程 `URL.createObjectURL` 從未被呼叫；DOM 裡沒有 `<img>`、`<a download>`、`<iframe>`、`<object>`、`<embed>` |
| `length_mismatch_is_error` | 串流比 `Content-Length` 短 → `transfer_failed`，沒有部分畫面 |
| `header_limits_rechecked` | 標頭宣告 9000×9000 → 不呼叫 `createImageBitmap` |
| `states_are_distinct` | §4 每個狀態的文案彼此不同，而且都不含「下載」 |
| `focus_returns_to_row` | 關閉後焦點回到開啟預覽的那一列 |
| `inflight_zero_after_dispose` | 每個 dispose 觸發後，進行中的請求數為 0 |

### 6. 驗收清單

- [ ] §5 全綠；`typecheck`／`lint`／`format`／`unit`／`build`／`layout-gates`／`vr-gates` 綠。
- [ ] `PreviewPane.vue` 的 Monaco 路徑沒有行為改變（既有測試未修改即通過）。
- [ ] `stores/files.ts` 沒有 diff（plan/29 MS-14 的唯讀依賴規則）。
- [ ] `authLoss.ts` 的 diff 只有一行呼叫。

### 7. 不在範圍

PDF（`BP-07`）、縮圖、動畫、任何存檔入口。

---

## `BP-07` PDF.js 渲染器

**寫入集：** `frontend/package.json`＋lockfile（**唯一新依賴** `pdfjs-dist`，pin 精確版本）、
`frontend/vite.config.ts`（worker 與靜態資產）、`frontend/src/pdf/setup.ts`（新，唯一建立
`getDocument` 的地方）、`components/file/PdfPreview.vue`（新）、
`frontend/tests/e2e/binary-preview*.spec.ts`（新）。

**前置：** `BP-06` 合併。

### 1. 依賴審查（開工第一天，在寫任何元件之前）

| 項目 | 要產出的證據 |
|---|---|
| 版本 | 當時最新、且**已修補所有已公開 PDF.js advisory** 的穩定版，寫進 `package.json` 精確版本，不用 `^`。截至 2026-09-27 為 **≥ 6.2.108**，明列兩則：CVE-2024-4367／GHSA-wgrm-67xf-hhpq（4.2.67 修正）、**CVE-2026-16633／GHSA-hq66-cqwq-w95j**（受影響 `>= 5.6.83, < 6.2.108`；在啟用 scripting、預設即啟用，且沒有限制 `script-src` 的 CSP 時可執行任意 script；2026-09-27 以 GitHub Advisory API 查證）。**閘門：** pin 當天與 `BP-11` 發布前各查一次 GitHub Advisory Database 與 `npm audit`，有未修補的 advisory 就不得出貨 |
| 授權 | 該版本 `LICENSE` 為 Apache-2.0；transitive 依賴清單與各自授權 |
| 已知漏洞 | `npm audit` 與 GitHub advisory 查詢結果 |
| 大小 | 主 chunk 的增量必須為 0（lazy import）；lazy chunk 與 worker 的實際大小 |
| CSP | 用真實 CSP 標頭（`nginx.conf:134` 原字串）跑 build 後的 bundle：worker、wasm、字型、cMap 全部能載入，console 沒有 CSP violation（`BP-OM-04`） |
| 瀏覽器下限 | 現代 build 在 `08-…md` 裝置矩陣上的最低可用版本（`BP-OM-07`，OD-9） |

任何一項不過，就停在這裡回報，不以「先做再說」往下走。

### 2. 設定（`pdf/setup.ts`，唯一出口）

```ts
getDocument({
  data: bytes,                 // 不給 URL：沒有 range／stream 請求
  isEvalSupported: false,
  enableScripting: false,      // CVE-2026-16633 類；由哪一層讀取此選項要在 pin 的版本上確認
  enableXfa: false,
  disableAutoFetch: true,
  disableStream: true,
  disableRange: true,
  stopAtErrors: true,          // 待驗證：不得誤拒常見良性 PDF（07-…md 語料）
  cMapUrl: SELF_HOSTED_CMAPS,  // CJK PDF 需要，繁中使用者是主要客群
  cMapPacked: true,
  standardFontDataUrl: SELF_HOSTED_FONTS,
  wasmUrl: SELF_HOSTED_WASM,   // 版本若有此選項
});
// 渲染時 annotationMode: AnnotationMode.ENABLE；不建立 AnnotationLayer／TextLayer
loadingTask.onPassword = () => { void loadingTask.destroy(); state = "pdf_password_required"; };
// 不呼叫 onPassword 的 updatePassword callback：本期沒有任何密碼輸入（OD-8）
```

**加密的處理（OD-8 建議預設）：** 只有「需要密碼才能開啟」的 PDF 會被拒絕，而且是由渲染器拒絕。
只有權限密碼（空使用者密碼）的 PDF 可以不經提示開啟，照常唯讀顯示。權限位元只限制列印、複製與編輯，
而預覽本來就不提供這三者。daemon **不**做加密判定（ADR 0029 §4），所以前端文案不得宣稱「已在伺服器端偵測加密」。
若 OD-8 改選 (b)（任何加密都拒絕），需要一個 PDF.js 對「無密碼即可開啟的加密文件」的訊號；
該 API 未驗證（`BP-OM-12`），要在本票第一天確認，確認不了就回報，不以啟發式替代。

- 以 lint 規則或測試禁止 `pdfjs-dist/web/*`（viewer）與 `pdf.sandbox`／scripting 的 import。
- 靜態資產（`cmaps/`、`standard_fonts/`、`wasm/`）在 build 時由 `vite.config.ts` 裡的
  **自寫**小 plugin 從 `node_modules/pdfjs-dist/` 複製到 `dist/pdfjs/`。
  不為此新增 `vite-plugin-static-copy` 之類的依賴。
- worker 以 `new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url)` 這類同源資產載入。
  **確切路徑依版本而定**，開工時核對。

### 3. 呈現

- 單欄、全幅；工具列：上一頁／下一頁／頁碼輸入（`inputmode="numeric"`）／符合寬度／＋／−，每個 ≥ 44×44，
  貼底時處理 `env(safe-area-inset-bottom)`。
- 只保留目前頁與相鄰一頁，最多 3 個 canvas；捲動或翻頁時取消離開視窗的 `RenderTask`。
- 每頁 `aria-label="第 n／N 頁"`；頁碼變更以 `aria-live="polite"` 宣告。
  **文字層不做**（OD-3），所以 release note 要寫明「螢幕報讀器讀不到 PDF 內文」。
- 載入完成先讀 `numPages`，超過上限就在渲染第一頁**之前**進 `pdf_too_many_pages`。
- 每頁 10 秒逾時，逾時只影響該頁（`render_failed`，顯示在該頁位置），不拖垮整份。

### 4. 先寫的 RED 測試

| 層 | 測試 | 斷言 |
|---|---|---|
| unit | `setup_options_are_locked` | `getDocument` 收到的選項與 §2 完全相同；任何呼叫端都不能覆寫 |
| unit | `no_viewer_or_scripting_import` | 靜態掃描 bundle 輸入：沒有 `web/`、`sandbox`、`scripting` |
| unit | `destroy_on_every_trigger` | `BP-06` §3 的每一個觸發點都呼叫了 `pdf.destroy()`，worker 被終止 |
| unit | `page_limit_before_render` | `numPages=10000` → 沒有任何 `page.render` 被呼叫 |
| E2E（真實 CSP） | `pdf_active_content_inert` | 內含 JS、URI 連結、Launch、表單 submit、附件的 PDF：沒有 navigation、沒有 popup、沒有額外網路請求、DOM 裡沒有 `<a>` |
| E2E（真實 CSP） | `no_csp_violation` | 開一份 CJK PDF 與一份含 JPX 影像的 PDF，`securitypolicyviolation` 事件數為 0 |
| E2E | `password_pdf_refused` | RC4-40／AES-128／AES-256 且有使用者密碼的 PDF：顯示 `pdf_password_required`，DOM 裡**沒有** `input[type=password]`，worker 已終止 |
| E2E | `permissions_only_pdf_renders` | 空使用者密碼、只有權限密碼的 PDF：正常顯示第 1 頁，且沒有列印／複製／存檔入口（OD-8 建議預設；若 OD-8 選 (b)，這條改為斷言被拒） |
| E2E | `cve_2024_4367_shape` | 公開 PoC 形狀的字型：沒有 script 執行（監聽 `window` 上的標記變數） |
| E2E | `bundle_initial_chunk_unchanged` | 首頁的 JS 大小與基準相同（PDF.js 只在 lazy chunk） |

### 5. 驗收清單

- [ ] §1 的依賴審查證據寫進 `docs/security-review-p31.md` 的附錄（`BP-08` 審閱）。
- [ ] §4 全綠；既有 E2E 不退步。
- [ ] 首頁 bundle 大小不變；lazy chunk 大小有記錄。
- [ ] 沒有第三方 origin；CSP 標頭沒有改（若必須改，停下來另行審查）。

### 6. 不在範圍

文字層、搜尋、連結導覽、表單、密碼、列印、縮圖、PDF 大綱（outline）。
