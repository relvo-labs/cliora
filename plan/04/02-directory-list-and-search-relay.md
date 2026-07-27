# 02 — Directory List 與檔名搜尋 Relay（P3-W2）

對應 `research/01/04-phase-3-workspace-files.md` §P3-W2，涵蓋 ticket **P3-04**（daemon `filesystem.list`/`filesystem.search` handler）與 **P3-06**（Central `app/services/files.py` + `app/api/http/files.py` relay/authorize）。需求：FR-FILE-001、FR-FILE-007、FR-WORKSPACE-001/002、SEC-001/002、tech §11.3/11.4/11.8。

## 目標

讓前端能對某 session 對應的 Node，取得**單層目錄列表**（lazy load）與**檔名搜尋**結果。daemon 做實際 filesystem 讀取與安全判斷（經 P3-03 guard），Central 只 relay/authorize，兩者都不外洩 server absolute path，且 list/search 都有明確 bounds、ordering、timeout 與 cancel。**Central 不代替 daemon 讀 Node filesystem。**

## P3-04：Daemon list / search handler

在 `daemon/internal/connection/dispatch()`（`connection.go` switch，約 line 362）新增：

```go
case "filesystem.list":
    m.handleList(ctx, env, data, send)
case "filesystem.search":
    m.handleSearch(ctx, env, data, send)
```

實作放 `daemon/internal/files/`（`list.go`、`search.go`），沿用 P2 `handleStart` 的安全順序：先 `ValidateControl` → 解析 payload → **以 session 的 workspace 為基準呼叫 P3-03 guard 取得 root-confined dir handle** → 執行 → 經單一 write owner `send` 回覆。

**`filesystem.list`**：
- 以 `OpenDirInRoot`（P3-03）取得目錄 handle，`ReadDir` 後對每個 entry 標記 `type`(directory/file/symlink)、`size`、`modified_at`(RFC3339 UTC)、`hidden`（`.` 開頭）、`symlink`、`excluded`（命中 `excluded_directories`）、`expandable`（目錄且未 excluded）。
- **Ignore rule（tech §11.4）**：`excluded_directories`（`.git/objects`、`node_modules`、`.venv`、`dist`、`build`、`__pycache__`）採「顯示但預設不載入」——回 `excluded:true, expandable:false`，前端顯示「已排除」，不遞迴。
- **Deterministic ordering**：目錄先於檔案、同類以 name 升冪（locale-independent byte order），確保跨呼叫穩定與可測。
- **Entry limit + 分頁**：單次回傳上限（ADR 0015，如 2000），超過回 `truncated:true` + `next_cursor`；`cursor` 由 daemon 定義（offset 或最後 name），Central 原樣轉傳，不外洩絕對路徑。
- **Per-request timeout**：handler 以 `ctx`（帶 deadline）執行；逾時安全結束，不半寫。
- entry 的 `rel_path` 一律相對 workspace root，**絕不回傳 server absolute path**。

**`filesystem.search`（檔名 only，tech §11.8）**：
- 遞迴 walk workspace（root-confined），比對 `keyword`（檔名子字串，或 ADR 0014 允許的簡單 glob），**不讀檔案內容、不執行 shell/rg**。
- bounds：`max_depth`(10)、`max_results`(200)、`max_scanned`（掃描檔案數上限）、`timeout_seconds`(10)，皆從 config，達任一上限即停並回 `partial:true` + `stopped_reason`(depth|results|scanned|timeout) + `scanned_count`。
- **可 cancel**：walk 綁 `ctx`；Central 取消 request（前端 abort 或 relay timeout）時 daemon 停止 walk、釋放資源，不留 goroutine。
- excluded_directories 不進入遞迴（避免掃 `node_modules`）。
- 結果 `rel_path` 相對 root，回 `name`/`type`/`modified_at`，不回內容。

**測試（`go test -race`，`-tags integration` 用 fixture workspace）**：large directory（entry limit + 分頁）、excluded dir 標記與不遞迴、ordering deterministic、hidden entry、list timeout、search 各 stopped_reason（depth/results/scanned/timeout）、search cancel（ctx 取消後無 leaked goroutine，`-race`）、permission error（不可讀子目錄回 `WORKSPACE_PERMISSION_DENIED`，不中斷整體）、symlink entry 標記但不自動穿越、broken link 不 crash、絕對路徑不出現在任何回覆。

## P3-06：Central filesystem relay 與 HTTP API

新增 `app/services/files.py` 與 `app/api/http/files.py`（prefix `/api/sessions/{session_id}/files`，於 `main.py` 註冊），成為 `NodeConnectionRegistry.request()` 的新一組 production caller。

```text
GET  /api/sessions/{id}/files/tree?path=<rel>&cursor=<c>   require_action(file.browse)  → filesystem.list
GET  /api/sessions/{id}/files/search?keyword=<k>&root=<r>  require_action(file.browse)  → filesystem.search
GET  /api/sessions/{id}/files/content?path=<rel>           require_action(file.browse)  → filesystem.read（見 03）
```

**relay/authorize 行為（`app/services/files.py`）**：
- **session→node 解析**：以 `session_id` 查 `terminal_sessions` 取得 `node_id` 與 `workspace`（P2 已建模）；session 不存在/非本人可見 → RBAC/404 safe error。node offline/disabled → `NODE_OFFLINE`/`NODE_DISABLED`（不打 daemon）。
- **前置授權**：`path`（workspace-relative）join 到 session workspace 後，確認仍在該 session 的 workspace 子樹（Central 做**前置**檢查，daemon 做**最終** canonical 判斷）；含 absolute/`..`/null byte 的輸入在 boundary 即 422，不轉傳 daemon。
- **relay**：經 `registry.request(node_id, "filesystem.list"/"search", payload, timeout=...)`，correlate response；沿用 P2 的 pending map/timeout/late-response/斷線 `_fail_pending`。timeout 從 `Settings`（`file_list_timeout_seconds` 等），不硬編。
- **cancel**：前端 `AbortController` 中斷連線時，取消對應 registry request（送 daemon cancel 或讓 daemon ctx 逾時），清 correlation entry，不留 pending future。
- **relay bounds**：沿用 per-node `pending_requests_max`(128)，超過回 `NODE_BUSY`(503)；回應 body 大小以 daemon 已 bounded 的內容為準（Central 不再放大）。
- **safe error 映射**：`NODE_OFFLINE`→409、`NODE_BUSY`→503、`REQUEST_TIMEOUT`→504、RBAC→403、驗證→422、`WORKSPACE_*`/`FILE_*`→400/403/404（依 ADR 0014 對外合併，不洩漏存在性與內部路徑）；global handler 統一 safe body `{error:{code,message},request_id}`。
- **不洩漏**：回前端的 DTO 只含 `rel_path`/`root_display_name`，**移除任何 server absolute path**；log 只記 code + request/session/node id，不記 path 內容或列表。

**DTO（`app/api/http/schemas.py`，與 frontend `dto.ts` 對齊）**：`FileEntryDTO`、`FileTreeResponse`（entries + truncated + next_cursor + root_display_name）、`FileSearchResponse`（results + partial + stopped_reason + scanned_count）。時間 RFC3339 UTC，type enum 對齊。

**測試（DB-backed，需 `CLIORA_TEST_DATABASE_URL`，httpx `AsyncClient` + fake daemon WS）**：三角色對 file.browse 的 allow/deny；tree/search 成功鏈（Central→fake daemon→回列表）；absolute/`..`/null byte 於 boundary 被 422 不轉傳；offline/disabled node 被拒不打 daemon；timeout 清 correlation；cancel（client abort）無 pending future leak；`NODE_BUSY` 於 pending 滿；回應 DTO 無 server absolute path（掃描斷言）；log/audit 無 path 內容。

## 對應需求

FR-FILE-001（tree lazy load）、FR-FILE-007（檔名搜尋，keyword/root/max_results 輸入、path/name/type/modified 輸出）、FR-WORKSPACE-001/002（root metadata 與瀏覽）、SEC-001（路徑隔離，每次重新驗證）、SEC-002（不接受 command/任意參數）。
