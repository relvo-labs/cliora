# Cliora P3 可實作規劃（Workspace 與 Files）

本目錄把 `research/01` 的 **Phase 3（Workspace Files）** 轉成可直接建立 ticket、撰寫程式與驗收的執行規格。P3 的產品成果，是讓授權使用者在既有 Session Workspace 內**安全地瀏覽目錄樹、以檔名搜尋、並以 Monaco 唯讀預覽程式碼**；任何輸入都無法逃離該 Node 設定的 allowed roots，敏感檔案預設拒絕、binary 與 oversize 檔案不外洩內容，且 Central 全程只做 relay/authorize、不代替 daemon 讀取 Node filesystem。P3 不實作檔案編輯、上傳、下載、Git 操作或任何任意 filesystem API（永久非目標），也不做 RBAC 完整營運介面與 Dashboard 真實聚合（P4）。

> 命名說明：plan 資料夾編號比 research 的 Phase 編號多 1。`plan/01`=Phase 0（Terminal PoC）、`plan/02`=Phase 1（Node Control Plane）、`plan/03`=Phase 2（Session 與 Terminal），皆已交付。本目錄 `plan/04` 對應 **Phase 3（Workspace Files）**，ticket 前綴為 `P3-`；research 內的 work package 仍以 `P3-W1`…`P3-W6` 稱之。

## 前置狀態（P0/P1/P2 已交付，P3 直接沿用）

- **路徑安全核心已存在**：`daemon/internal/workspace/guard.go` 的 `Guard.Resolve(target)` 已實作 tech §11.2 的容器判斷（reject empty/null byte → `filepath.Abs` → clean → `EvalSymlinks`(target 與 root) → `filepath.Rel` containment，**禁用 `strings.HasPrefix`**），回傳 `WORKSPACE_INVALID/OUTSIDE_ALLOWED_ROOT/NOT_FOUND/NOT_DIRECTORY/PERMISSION_DENIED`。P2 只在 session launch 呼叫它；**P3 的每次 list/read/search 都必須重新以它 canonicalize，不得信任 client breadcrumb 或前次 listing**。`go test -race ./internal/workspace` 已覆蓋 traversal/symlink/prefix-collision/null-byte。
- **daemon 已預留 filesystem 設定**：`daemon/internal/config/config.go` 已有 `WorkspaceConfig{AllowedRoots, ExcludedPatterns}` 與 `FilesystemConfig{MaxPreviewSize}`（`DefaultMaxPreviewSize`，unknown-field 拒絕、負值拒絕已測）。P3 於此擴充 `excluded_directories`、`denied_patterns`（exact/extension/glob/directory 四類）、`search{max_depth,max_results,max_scanned,timeout_seconds}`，全部以可設定 bounded 值實作。
- **daemon 已有 production control dispatch**：`daemon/internal/connection/connection.go`（`dispatch()` switch，約 line 362）已接上 `session.start/stop/attach/terminal.resize`，並示範「resolveBinary（allowlist）→ `guard.Resolve` → 啟動」的安全順序。P3 在同一 switch 新增 `filesystem.list/read/search`（與必要的 `workspace.roots`）handler，路由到新的 `internal/files` 套件。
- **Central relay/correlation 已就緒**：`app/services/registry.py` 的 `NodeConnectionRegistry.request()`（pending map、per-node send-lock、`REQUEST_TIMEOUT`、斷線 `_fail_pending`）在 P2 已是 production caller（session HTTP API）。P3 的 filesystem HTTP relay 是它的下一組 caller。`app/api/errors.py`（safe body `{error:{code,message},request_id}`）、`app/api/http/deps.py` 的 `require_action()`、`app/services/rbac.py` 皆沿用。
- **RBAC 已有 file action 佔位**：`app/services/rbac.py` 已定義 `FILE_BROWSE = "file.browse"`（P1/P2 未綁定使用）。P3 以 versioned seed migration 綁定角色並成為 filesystem 端點的授權依據。
- **Frontend 三欄工作區已存在、預留 P3 掛點**：`frontend/src/views/SessionWorkspaceView.vue` line 174 有 `<!-- File tree + preview land in P3. -->` 佔位；`components/session/*`、`stores/sessions.ts`、`composables/useTerminalSession.ts`、`theme/` semantic tokens 皆可沿用。**Monaco 尚未安裝**（`package.json` 目前只有 `@xterm/*`、`naive-ui`）；P3-W5 需新增 `monaco-editor` 依賴並自帶 worker（不可 CDN 外連）。
- **契約基線 v1.2**：`contracts/v1/`（schemas/messages、fixtures valid/invalid、`manifest.json`）已凍結 P0 v1 與 P2 v1.2 的 node/session/terminal 訊息。P3 凍結 **v1.3**：新增 `filesystem.*`（與 `workspace.roots*`）訊息 schema、fixtures 與三語言 codec。
- **P2 exit = Go**（`docs/p2-report.md`）：session context（`terminal_sessions`、workspace root metadata、RBAC、audit、ws-ticket）皆已可用，P3 直接建立在此 session context 之上。P2 report 的 P3 follow-ups 已明列：檔案樹/檔名搜尋/Monaco 唯讀預覽（依賴 P2 session context）、`workspace_favorites`/最近使用 workspace（FR-WORKSPACE-004/005，可延後）。

## 文件順序

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 範圍、非目標、固定基線、垂直架構、ticket 波次、共同完成定義與 P3 預設限制 |
| [01-path-security-and-protocol.md](./01-path-security-and-protocol.md) | P3-01（決策 ADR 0014/0015）、P3-02（protocol v1.3 凍結）、P3-03（P3-W1 path security library 強化、TOCTOU、fuzz/property、error taxonomy） |
| [02-directory-list-and-search-relay.md](./02-directory-list-and-search-relay.md) | P3-04（daemon `filesystem.list`/`filesystem.search` handler）、P3-06 Central 端 relay/API（P3-W2）：typed request/response、bounds/cancel/ordering、ignore rule、no absolute-path leakage |
| [03-read-only-file-policy.md](./03-read-only-file-policy.md) | P3-05（daemon `filesystem.read` handler，P3-W3）：stat→bounded LimitReader、binary detection、sensitive deny（exact/ext/glob/dir）、permission deny、language/encoding/mtime/size/denial reason、TOCTOU（replacement/symlink swap） |
| [04-file-tree-ui.md](./04-file-tree-ui.md) | P3-07（P3-W4）：lazy expand、full state matrix、keyboard tree semantics、search→tree context、node/session 切換 cache 失效、不外洩 server absolute path |
| [05-monaco-preview.md](./05-monaco-preview.md) | P3-08（P3-W5）：新增 `monaco-editor`（自帶 worker）、readOnly/搜尋/word wrap/copy/goto line/refresh、model ownership + bounded cache、denial 畫面、allowed→denied 清空、a11y |
| [06-audit-and-observability.md](./06-audit-and-observability.md) | P3-09：sensitive-read-failed audit（僅分類 + 相對識別，無內容，SEC-006）、filesystem metrics、correlation log、redaction |
| [07-verification-and-exit.md](./07-verification-and-exit.md) | P3-10（P3-W6）：測試矩陣、CI gates、性能量測（list <2s、≤2 MB preview <3s）、安全套件、操作證據包、P3 exit gate、ADR 清單、風險與 P4 follow-ups |
| [08-implementation-status.md](./08-implementation-status.md) | 實作進度與證據（各 ticket 狀態、已驗證證據、續作點）— 隨實作更新，初始為未開工 |

## 使用規則

1. **先過 `P3-01`（決策 ADR）與 `P3-02`（protocol v1.3 凍結），且 `P3-03`（path security library）通過安全 gate**，再並行 daemon relay、Central relay 與 Frontend。**path security 是 P3 的硬性 Gate**：其 fuzz/property 與 traversal/symlink/sensitive/binary/oversize 測試未全綠前，不得對外開放任何 filesystem 端點。
2. 修改契約的 PR 必須先於 consumer 合併，並同步 schema、`contracts/v1/fixtures/manifest.json`、fixtures 與 Python/Go/TS 三個 consumer。每項 task 都需提交其列出的產物與測試；「可手動展示」不能替代自動測試。日常 integration 一律用 fixture workspace（含惡意路徑/敏感/binary/oversize/symlink swap fixtures），不依賴個人真實路徑。
3. 依 `.agent/skills/cliora-project-context`：先檢視 repo 現況、不假設規劃中的目錄已存在、做最小可行變更，並保全 trust-boundary invariants（outbound-only daemon WSS、**Central 不代替 daemon 讀 Node filesystem**、**每次操作重新 canonicalize、不信任前次 listing**、PostgreSQL/log 不存 file 或 terminal content）。相關技能：`go-daemon-development`、`fastapi`、`vue-naive-ui-workflow`、`cliora-security-review`、`timezone-precision`、`webapp-testing`、`terminal-websocket-protocol`（relay 骨架）。
4. 需求變更先更新 `research/prd.md`／`tech.md`／`style.md`，再同步 `research/01/06-requirement-traceability.md`，不得在 implementation ticket 中暗自擴張範圍（尤其**不得新增編輯/上傳/下載/Git/全文搜尋任意參數**）。
5. 所有時間採 tz-aware；持久化（僅 audit metadata）用 timezone-aware PostgreSQL 型別，傳輸 RFC 3339 UTC（`Z`），畫面才本地化；search timeout、read timeout、relay request timeout 以 **monotonic** 計算。

## 完成結果

P3 通過時，使用者在 Session Workspace 可從該 Node allowed root 展開檔案樹（lazy load、ignore rule、hidden/excluded 明示）、以檔名搜尋（有 depth/result/scanned/time 上限且可 cancel）並回到 tree context、點檔以 Monaco 唯讀預覽合法程式碼（語法高亮、行號、word wrap、搜尋、copy、goto line、refresh）。`.env`/key/token 等敏感檔案、binary、oversize、權限不足、不確定型別一律以具體「不可預覽」畫面拒絕並提供下一步；任何 `../`、absolute escape、prefix collision、symlink chain/swap、broken link、null byte 都被 daemon 拒絕。切換 Node/session 或檔案從允許變成拒絕時，畫面不殘留前一檔內容；Monaco model 無 leak。sensitive read 失敗留下不含內容的 audit；filesystem 操作有 bounds/timeout/cancel/disconnect 的 metric。目錄列表在代表性環境 <2 秒、≤2 MB 預覽 <3 秒，或已有量測與改善門檻。所有路徑逃逸與敏感內容測試必須全過，否則不可發布。
