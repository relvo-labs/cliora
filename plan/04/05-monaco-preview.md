# 05 — Monaco Read-Only Preview（P3-W5）

對應 `research/01/04-phase-3-workspace-files.md` §P3-W5，涵蓋 ticket **P3-08**。需求：FR-FILE-002/003/004/005/006、SEC-004、style a11y、tech §16.4。

## 目標

在 Session Workspace 以 Monaco **唯讀**預覽合法程式碼；每個 model 有單一 owner，切檔 dispose 或使用**有上限**的受控 cache（避免一次載入大量 model）；binary/oversize/sensitive/permission/not-found 各有具體「不可預覽」畫面與下一步；檔案從允許變成拒絕時清除既有內容，避免 stale sensitive data 留在畫面。

## 現況與依賴

- **Monaco 尚未安裝**：`frontend/package.json` 目前只有 `@xterm/*`、`naive-ui`、`lucide-vue-next`。本 ticket 新增 `monaco-editor`（pin 版本）。
- **必須自帶 worker、無 CDN 外連**：以 Vite worker import（`monaco-editor/esm/vs/editor/editor.worker?worker` 等）或 `vite-plugin-monaco-editor` 打包 worker，確保離線可 build 且不違反部署（無外部 CDN）。只註冊需要的語言（減少 bundle）；語言由後端 `language_hint` 決定。
- 沿用 `theme/` semantic tokens：Monaco 主題與 terminal 共用深色工作區語言（自訂 theme 對齊 tokens，不用預設 vs-dark 硬色）。

## 新增檔案

- `composables/useMonacoModel.ts`：擁有 editor instance 與 model **bounded cache**（LRU，上限見 ADR 0015）；`openFile(relPath)`：查 cache 或 `GET /files/content?path=`；`disposeModel(relPath)`、`disposeAll()`；離頁/切 session 一律 `disposeAll` 並釋放 editor。
- `components/file/PreviewPane.vue`：容器、header（檔名、read-only 標示、refresh、copy、goto line）、Monaco 掛載點、denial 畫面 slot。
- `components/file/PreviewDenied.vue`：oversize/binary/sensitive/permission/not-found 的具體畫面。

## 行為要求

**唯讀能力（FR-FILE-002，tech §16.4）**：`readOnly:true`、syntax highlight（依 `language_hint`）、line numbers、search（Monaco find widget）、word wrap 可切換、copy、goto line、refresh（重打 content 端點、替換該 model 內容）。**無編輯、無 minimap 寫入、無 command palette 危險項**；`domReadOnly` 與 context menu 僅保留唯讀動作。

**Model 生命週期（tech §16.4，防 leak）**：
- 每個檔一個 model，key = `(node,session,relPath)`；owner 是 `useMonacoModel`。
- 切檔：`editor.setModel(next)`，舊 model 若超出 bounded cache 立即 `model.dispose()`；cache 命中則重用。cache 上限（ADR 0015，如 8）以 LRU 淘汰並 dispose。
- 切 session/離頁：`disposeAll()` + `editor.dispose()` + worker 釋放；`onScopeDispose`/`onBeforeUnmount` 保證清理。**rapid switching 不得累積 model 或 worker**（測試以 leak gate 斷言，沿用 P2 `useTerminalSession.test.ts` 的 leak-gate 模式）。

**Denial 畫面（各具體且有下一步）**：
- `FILE_TOO_LARGE`：顯示「檔案過大，超過預覽上限」+ 實際 size + 上限；下一步：無（MVP 不提供完整載入）。
- `FILE_BINARY`：顯示「不支援預覽」+ MIME/size/mtime（FR-FILE-004）。
- `FILE_DENIED`（sensitive）：顯示「此檔案為敏感類型，預設不可預覽」+ 分類原因；**不顯示任何內容片段、不顯示 server absolute path**（SEC-004）。
- `FILE_PERMISSION_DENIED`：顯示「無讀取權限」。
- `FILE_NOT_FOUND`/`WORKSPACE_*`：顯示「檔案已不存在或無法存取」+ refresh 建議（依 ADR 0014 對外合併訊息）。

**allowed→denied 清空（安全關鍵）**：當先前可預覽的檔案，重新 refresh 或再次開啟時後端回 denial（檔案被替換成敏感檔、變 oversize、權限改變、或被刪除），**立即清除 editor model 內容並切換到 denial 畫面**，不得殘留前一次的（可能已變敏感的）內容。切檔時先清空當前顯示再載入下一檔，避免短暫殘影。

**a11y（style 契約）**：PreviewPane header 有可讀檔名與「唯讀」語意標示；Monaco 的 `aria-label` 帶檔名與 read-only；denial 畫面用文字（非只顏色）說明原因與下一步，可被螢幕閱讀器讀出；focus 進入/離開 editor 有明確順序；尊重 reduced-motion。

**不外洩**：前端只用 `rel_path`/`language_hint`/`content`；不重建或顯示 server absolute path；copy 只複製檔案內容（合法可預覽檔），denial 畫面無可複製內容。

## 測試（vitest + Playwright）

**Unit（vitest）**：`useMonacoModel` 開檔/cache 命中/LRU 淘汰 dispose；**rapid switching leak gate**（連續切 N 檔後存活 model ≤ cache 上限、worker 數穩定）；切 session `disposeAll` 後無殘留；denial 各 code 對應正確畫面；allowed→denied 清空當前內容（斷言 editor value 被清）。

**E2E（Playwright）**：預覽 `.py`/`.ts`（語法高亮、行號、search、word wrap、copy、goto line、refresh）；預覽 `.env`/`*.pem`/`id_rsa` → sensitive denial 無內容；binary → 不支援預覽 + metadata；oversize → 過大提示；快速切多檔無視覺殘留與（透過 leak gate）model leak；把可預覽檔在 daemon 端替換為敏感檔後 refresh → 內容被清、顯示 denial；screen reader 讀出檔名、read-only 與 denial 說明。

**對應需求**：FR-FILE-002（Monaco 唯讀預覽全功能）、FR-FILE-003（oversize 畫面）、FR-FILE-004（binary 畫面 + metadata）、FR-FILE-005/SEC-004（sensitive denial 無內容）、FR-FILE-006（refresh、allowed→denied 清空）。
