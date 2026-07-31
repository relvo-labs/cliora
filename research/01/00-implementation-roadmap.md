# 00 — 實作總覽

## 1. 目標與成功定義

交付一個瀏覽器式的多節點 CLI Agent 中央管理平台，使授權使用者能註冊 Linux Node、在允許的 Workspace 啟動 Claude/Codex 原生 CLI、持續操作與重新連線 Terminal，並安全地唯讀瀏覽檔案。

MVP 成功需同時成立：

- Daemon 僅由 Node 主動以 WSS 連向 Central，Central 不使用 SSH。
- CLI 保留原生 TTY、快捷鍵與審批互動語意。
- Session 生命週期與瀏覽器分離，重新整理或短暫斷線不終止 CLI。
- Renderer 不能指定任意 command、binary 或 shell string。
- Workspace 每次操作都在解析 symlink 後驗證 allowed root。
- 單一 writer、多個 viewer 的 Terminal 規則明確且可稽核。
- PostgreSQL 保存 durable metadata，但不保存 Terminal raw bytes。
- 所有時間採 aware timestamp；傳輸為 RFC 3339 UTC，畫面才轉成本地時間。

## 2. 原型盤點與處置

目前 `frontend` 是單檔 Vue 展示原型，可保留其資訊架構與視覺方向，但不可直接當作 production architecture。

| 原型能力 | 處置 | 正式實作要求 |
|---|---|---|
| Dashboard、Nodes、Sessions、Enrollment、Workspace | 沿用頁面概念 | 拆成 route/view/component，接 typed API |
| Session Workspace | 沿用主要布局 | Terminal 最大、狀態可恢復。**plan/08 改版**：兩欄 + 中央區 tab；左欄 Session 清單與面板拖曳/收合已放棄 |
| Node filter、session modal | 沿用互動意圖 | 真實 validation、RBAC、loading/error/offline |
| Terminal 文字展示 | 僅作視覺參考 | 換成 xterm.js，不可用 input 模擬 Terminal |
| File tree/preview | 僅作視覺參考 | typed relay + Monaco read-only + deny reasons |
| 硬編碼 nodes/sessions/token/version | 移除 | API/store 提供，禁止展示真實完整 token |
| 全域 CSS 與極小字級 | 重構 | design tokens、Naive UI overrides、可讀性與 a11y |
| `min-width: 1180px` | 重新設計 | 依 style responsive 規則處理 overflow/收合 |
| `Cask` 品牌字樣 | 已決策：放棄 | 正式名稱為 **Cliora**（ADR 0016，2026-07-25）；UI 仍以 `VITE_PRODUCT_NAME` 可設定 |

## 3. 目標程式結構

實際 scaffold 時依 repository 現況微調，不預設 Turborepo 已存在。

```text
backend/                 FastAPI / SQLAlchemy 2 / Alembic
  app/api/               HTTP 與 WebSocket boundary
  app/services/          use cases、RBAC、state transitions
  app/repositories/      PostgreSQL persistence
  app/protocol/          versioned envelopes 與 fixtures
daemon/                  Go daemon
  cmd/agentd/            serve / doctor / version
  internal/connection/   outbound WSS、heartbeat、backoff
  internal/runtime/      Claude/Codex allowlisted adapters
  internal/session/      tmux、PTY attach、ownership
  internal/workspace/    path validation 與 read-only files
frontend/                Vue 3 / TypeScript / Vite
  src/api/               API client 與 DTO
  src/stores/            僅共享狀態
  src/composables/       WS/xterm/Monaco lifecycle owner
  src/views/             route-level UI
  src/components/        presentation components
  src/theme/             tokens 與 Naive UI overrides
contracts/               JSON fixtures/schema（跨語言）
tests/                   integration / E2E harness
```

## 4. 階段與依賴

| 階段 | 可展示成果 | 主要風險退休條件 | 依賴 |
|---|---|---|---|
| Phase 0 | Fake CLI 可從 Browser 操作並重連 | PTY/tmux、binary stream、resize、backpressure PoC 通過 | 無 |
| Phase 1 | Node 可註冊並顯示狀態/runtime | enrollment、daemon auth、heartbeat、offline 計算通過 | P0 契約 |
| Phase 2 | 可建立、操作、重連、終止真實 CLI | session recovery、single writer、queue bounds 通過 | P1 |
| Phase 3 | 可安全瀏覽並唯讀預覽檔案 | traversal/symlink/sensitive/binary/oversize 全拒絕 | P2 session context |
| Phase 4 | 可依角色營運、稽核、監控及更新 | RBAC、audit、release/security gate 通過 | P1–P3 |

階段是 release gate，不代表所有人必須串行。每階段可同時推進 contract、Central、Daemon、Frontend、test harness，但共享契約要先定稿。

## 5. 共通工程契約

### API 與錯誤

- HTTP/WS 在 boundary 完成 authentication、resource-level authorization 與 validation。
- 回應使用 stable machine error code、safe message、`request_id`；不回傳 stack、secret 或內部 path 細節。
- mutation 明確定義 idempotency、timeout、conflict 與 rollback。
- 所有 WS task、goroutine、subscription、xterm 與 Monaco model 只有一個 owner 並可清理。

### Protocol

- control 使用 versioned JSON text frame；Terminal bytes 使用 binary frame。
- request/response 具 `request_id`、方向、timeout、correlation 與 error code。
- frame、queue、scrollback 有上限；定義 slow client、gap、duplicate、unknown frame 行為。
- 跨 Python、Go、TypeScript 使用同一批 golden fixtures/contract tests。

### UI 狀態

每個資料與即時元件都必須處理：`idle`、`loading/connecting`、`success/connected`、`empty`、`stale/reconnecting`、`offline/disconnected`、`forbidden`、`partial`、`error`。狀態不可只靠顏色表達。

### Security 與 privacy

- secret 只顯示一次、at rest 使用 hash/受保護 credential，log 一律 redact。
- Daemon non-root；credential/config 權限 `0600`；下載 artifact 驗 checksum。
- Terminal input/output 不進一般 log、audit 或 PostgreSQL。
- 任何檔案存取都重新 canonicalize，不信任前次 tree listing。

## 6. 共通完成定義（Definition of Done）

一個工作包只有在下列條件全數滿足時才算完成：

- 行為、failure modes、權限與 timeout 有明確契約。
- backend/daemon/frontend 型別與 protocol fixture 同步。
- unit test 涵蓋成功、invalid、forbidden、timeout/disconnect 與 cleanup。
- 風險功能有 integration 或 E2E 證據。
- lint、typecheck、unit、build，以及適用的 race/E2E 通過。
- 結構化 log/metric/audit 已定義，且無 secret/terminal content。
- UI 有 keyboard、focus、label、contrast、reduced-motion 與操作狀態驗證。
- 文件與 `06-requirement-traceability.md` 已同步。

## 7. 決策閘門

Phase 0 結束前應明確記錄：

1. ~~產品正式名稱（Cliora 或 Cask）~~ → **已決定：Cliora**（ADR 0016，2026-07-25；package 名稱一併正規化為 `cliora-console`／`cliora-central`）。
2. monorepo/獨立 package layout 與 lockfile 策略。
3. protocol v1 envelope、binary frame metadata 與 resume/gap 語意。
4. tmux 命名、metadata 與 daemon restart 掃描策略。
5. authentication session/token 方案及 browser WS handshake 方式。
6. MVP 的 writer takeover 規則（僅 owner、顯式請求或 admin override）。
7. 檔案大小、queue、frame、scrollback、session 數的實際上限。

## 8. 明確非目標

MVP 不加入 Web IDE 編輯、任意 shell、Central SSH、Git automation、Terminal 全量保存、session replay、多 agent orchestration、task routing、Kubernetes agent、broker 或水平擴充。需要其中任一項時，先變更 canonical requirements。
