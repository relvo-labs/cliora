# 04 — File Tree UI（P3-W4）

對應 `research/01/04-phase-3-workspace-files.md` §P3-W4，涵蓋 ticket **P3-07**。需求：FR-FILE-001/006/007、FR-WORKSPACE-002、style.md 狀態契約與 a11y、tech §16.1。

## 目標

在既有 `SessionWorkspaceView.vue`（line 174 佔位）掛上檔案樹面板：lazy expand 的目錄樹、完整非同步狀態、可鍵盤操作、搜尋結果回到 tree context、切 Node/session 清空不相容 cache，且**不把 server absolute path 暴露到 UI/log**。點選檔案交給 [05](./05-monaco-preview.md) 的 PreviewPane。

## 現況（P3 起點）

- `frontend/src/views/SessionWorkspaceView.vue`：P2 已建三欄布局（Terminal 最大、面板可調整/收合、狀態可恢復），line 174 明確標註 `<!-- File tree + preview land in P3. -->`。
- 可沿用：`stores/sessions.ts`、`composables/useAsyncResource.ts`（idle/loading/success/empty/error 骨架）、`components/common/*`（`StatusBadge` 等）、`theme/` semantic tokens、`api/client`（typed、safe error、request_id）。
- 無 `components/file/*`、`stores/files.ts`、`composables/useFileTree.ts` — 本 ticket 新增。

## 新增檔案

- `stores/files.ts`：per-(node,session) 的 tree cache（已展開節點的 children、載入狀態、搜尋狀態），提供 `loadChildren(relPath)`、`refreshDir(relPath)`、`search(keyword)`、`clearForSession(sessionId)`。
- `composables/useFileTree.ts`：擁有 tree 狀態機、展開/收合、keyboard navigation、`AbortController` 生命週期；離頁/切 session 時 abort 進行中的請求並清 cache。
- `components/file/FileTree.vue`、`FileTreeNode.vue`（遞迴節點）、`FileSearchBar.vue`、`FileTreeToolbar.vue`（refresh）。

## 行為要求

**Lazy expand（FR-FILE-001）**：初始只載入 root 層；展開目錄時才 `GET /files/tree?path=<rel>`；已載入的子層快取於 store，重複展開不重打 API（除非 refresh）。excluded 目錄顯示為「已排除」且不可展開（對齊 daemon `excluded/expandable`）。

**完整狀態矩陣（style 狀態契約，不可只靠顏色）**：每個節點與整棵樹處理 `idle`、`loading`（展開中／根載入中，顯示 child skeleton）、`success`、`empty`（空資料夾明確提示）、`stale/reconnecting`（daemon 短暫不可達）、`offline/disconnected`（node offline：整樹 disabled + 說明，不可展開）、`forbidden`（無 file.browse：明確 403 提示）、`partial`（`truncated`：顯示「還有更多」與載入下一頁 cursor）、`error`（safe message + retry）。狀態以 icon+文字表達，不只顏色。

**Keyboard tree semantics（a11y）**：以 `role="tree"`/`treeitem`/`group`、`aria-expanded`、`aria-level`、`aria-selected` 實作；鍵盤：上下移動 focus、右展開/左收合、Enter/Space 開檔或切換、Home/End；**focus 與 selection 分離**（移動 focus 不自動開檔，避免大量預覽請求）；`aria-busy` 標示載入中；可見 focus ring（尊重 reduced-motion）。

**Icon 辨識**：folder（開/合）、file（依 language_hint/副檔名）、symlink、hidden（`.` 開頭，若 ADR 0015 設為顯示則以弱化樣式）、excluded（「已排除」徽章）皆以形狀/文字區分，不只顏色。

**檔名搜尋（FR-FILE-007）→ tree context**：`FileSearchBar` 送 `GET /files/search?keyword=`；結果列點擊後**回到 tree**——展開該檔所在路徑並選中節點（用 `rel_path` 逐段展開），而非另開孤立列表；搜尋 `partial`/`stopped_reason` 明示（「僅顯示前 200 筆／已達逾時」）；搜尋可取消（切換 keyword 或離開 abort 前一請求）。

**Refresh（FR-FILE-006）**：toolbar 提供「重新整理目前目錄」（重打該層、丟棄該層 cache）；預覽的「重新整理內容」由 PreviewPane 負責。MVP **不做**即時 watch。

**Cache 失效**：切換 Node 或 session、session 進入終態、或登出時，`clearForSession` 清空不相容 tree cache 與搜尋狀態，避免顯示前一 session 的路徑；in-flight 請求一律 abort。

**不外洩 absolute path**：tree 只用 daemon/Central 回的 `rel_path` 與 `root_display_name`；tooltip/複製/log 皆不顯示 server absolute path（後端本就不回傳，前端亦不重建）。

## 測試（vitest + Playwright，沿用 P2 gating）

**Unit（vitest + @vue/test-utils）**：`useFileTree` 展開載入/快取命中/refresh 丟棄；狀態機各分支（loading/empty/offline/forbidden/partial/error）；搜尋結果映射回 tree 展開路徑；切 session `clearForSession` 清空且 abort in-flight（無殘留 timer/promise）；keyboard 導航（focus 移動不觸發開檔）。

**E2E（Playwright，full-stack env flag）**：login→session workspace→展開目錄→lazy load 子層→大目錄 partial 載入下一頁→refresh 反映刪除/新增→搜尋並跳回 tree→切 session 後樹清空→node offline 時整樹 disabled→無 file.browse 角色 forbidden。keyboard-only 走訪；螢幕閱讀器可讀節點名稱/展開狀態/載入狀態。

**對應需求**：FR-FILE-001（tree、lazy、icon、metadata）、FR-FILE-006（refresh）、FR-FILE-007（搜尋回 tree）、FR-WORKSPACE-002（瀏覽），style 狀態/ a11y 契約。
