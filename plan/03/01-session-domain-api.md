# 01 — P2-W1：Session Domain 與 API

對應 `research/01/03-phase-2-session-terminal.md` §P2-W1。涵蓋 ticket **P2-04**（data + RBAC seed）、**P2-05**（domain service）、**P2-06**（HTTP API 與 relay 接線）。需求：FR-SESSION-001/002/003/004/005、FR-RUNTIME-002/003、FR-WORKSPACE-003、FR-CONN-004/006、SEC-002、PRD §9.3/9.4、§11.6。

## 目標

在 Central 建立 session 的 durable metadata、合法狀態機與 HTTP API，並成為 `NodeConnectionRegistry.request()` 的**首個 production caller**。Central 只接受 `runtime ID + workspace + name + rows/columns`，永不接受 command/binary/shell string；實際檔案系統與 process 安全判斷由 daemon 執行（P2-W2）。session metadata durable，terminal bytes 不入 DB。

## 現況（P2 起點）

- **無 session model**：DB 尚無 `terminal_sessions`；`app/api/http/nodes.py` 的 `session_count` 硬編為 0；`AuditLog.session_id` 欄位已存在但無人寫入（`app/db/models.py`）。
- **correlation 已就緒但無 caller**：`app/services/registry.py` 的 `NodeConnectionRegistry.request(node_id, type_, payload, *, timeout_seconds, request_id=None)` 具 pending map、per-node send-lock、`REQUEST_TIMEOUT`、斷線時 `_fail_pending`；`resolve_response()` 由 `app/api/ws/nodes.py` 控制迴圈的 `else` 分支呼叫（daemon 回應會被正確 match）。P2-06 是第一個呼叫 `request()` 的 production route。
- **RBAC/DTO/error**：`require_action(action)`（`app/api/http/deps.py`）、`ApiError` + `install_error_handlers`（`app/api/errors.py`，safe body `{error:{code,message},request_id}`）、`app/api/http/schemas.py`（pydantic DTO）、`services/rbac.py`（action 常數）皆可沿用。
- **workspace roots 已建模**：`NodeWorkspaceRoot(node_id, path, display_name, is_enabled)`（`app/db/models.py`），register 時由 daemon 上報並 `selectinload` 隨 node 載入 — 這是 Central 授權 workspace 的依據。

## P2-04：資料層與 RBAC seed

**新增 migration（Alembic head 續 `0004`）**：

`terminal_sessions`（對齊 PRD §12.6，tz-aware）：

| 欄位 | 型別 | 說明 |
|---|---|---|
| id | UUID PK | Central 生成；daemon 據此命名 `cliora-<id>` |
| node_id | UUID FK→nodes | `ondelete=RESTRICT`（保留稽核，node 為軟刪除） |
| user_id | UUID FK→users | 建立者 |
| name | varchar(128) | session 名稱 |
| runtime | varchar | `claude`/`codex`（allowlist，不存任意值） |
| workspace | varchar(4096) | 工作目錄（須為某 enabled root 之子路徑） |
| status | varchar | 狀態機值（見下） |
| pid | integer null | daemon 回報 |
| rows / columns | integer | 2..300 / 2..500 |
| started_at | timestamptz null | 進入 RUNNING 時間 |
| last_activity_at | timestamptz null | 最後 attach/活動 |
| ended_at | timestamptz null | 結束時間 |
| exit_code | integer null | 見 §決策 0004（可能為 attach client 狀態） |
| error_message | text null | 失敗原因（safe，不含內部路徑） |
| created_at | timestamptz | |

`session_connections`（audit 與 writer/viewer 追蹤，欄位由 P2-02 定稿）：`id`、`session_id` FK、`user_id` FK、`role`（`writer`/`viewer`）、`connected_at`、`last_seen_at`、`closed_at`、`close_reason`。索引：`terminal_sessions(node_id)`、`(user_id)`、`(status)`；`session_connections(session_id)`。

**RBAC seed（versioned migration，沿用 `.agent/skills/seed-migration`）**：新增並綁定角色 → action：`session.create`、`session.view`、`session.terminate`、`terminal.write`（writer）、`terminal.takeover`。Admin 全部；Developer 除 takeover 之管理面外具 create/view/terminate/write；Viewer 僅 `session.view` 與唯讀 attach。以 `services/rbac.py` 常數對應，並在 `backend/tests/db` 的 `_CLEANUP_TABLES` 補上新表。

驗收：Alembic clean upgrade、重跑、downgrade（先建立引用資料再回退，確認 rollback 無孤兒/無部分寫入）；tz-aware round-trip；seed clean/repeat/prior-data/permission-contraction 一致。

## P2-05：Session domain service 與狀態機

**狀態與合法 transition**（FR-SESSION-002；於 `services/sessions.py` 以顯式表定義，禁止任意跳轉）：

```text
(建立) → STARTING
STARTING → RUNNING            daemon session.started
STARTING → FAILED             session.start_failed / 逾時 / daemon error
RUNNING → DISCONNECTED        無 attach client（writer 保留窗到期）或 daemon 短暫斷線
DISCONNECTED → RUNNING        reattach 成功
RUNNING/DISCONNECTED → EXITED daemon terminal.exited（CLI 自行結束）
RUNNING/DISCONNECTED → TERMINATING  使用者 terminate
TERMINATING → TERMINATED      daemon session.stopped / force kill 後
任意非終態 → FAILED           不可回復錯誤（記 error_message）
```

終態（`EXITED/FAILED/TERMINATED`）不可再 transition；非法 transition 回 `SESSION_INVALID_STATE`。transition 觸發來源分三類並於 service 分別處理：HTTP mutation、daemon `status_changed`/回應、Central timeout/monotonic 判定。

**服務行為**：

- `create(user, node_id, runtime, workspace, name, rows, columns)`：boundary 後 (1) node 存在且 **Online**（offline/disabled → `NODE_OFFLINE`/`NODE_DISABLED`，對齊 FR-SESSION 前置與 MVP #18「offline 不可建 session」）；(2) runtime 在該 node 可用且未 disabled（否則 `RUNTIME_NOT_FOUND`/`RUNTIME_DISABLED`）；(3) `workspace` 為某 **enabled** `NodeWorkspaceRoot.path` 的子路徑（Central 做前置授權，daemon 做最終 canonical 驗證，否則 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`）；(4) 未超過每 node session 上限（`SESSION_LIMIT_REACHED`）。以單一 transaction 寫入 `STARTING`，再 `registry.request(node_id, "session.start", …, timeout=30s)`；成功轉 `RUNNING` 並記 pid，失敗轉 `FAILED` 並回滾/標記。
- **idempotency/conflict**：以 client 提供的 idempotency key（或 request_id）避免重複 create；同名/同資源重試回既有 session 而非重建，衝突回 `SESSION_ALREADY_EXISTS`。
- `list/detail`：durable metadata 讀取；detail 併回目前 connection roles（writer/viewer 數）。
- `terminate(session)`：轉 `TERMINATING`，`registry.request(node_id, "session.stop", …, timeout=20s)`（daemon graceful→force）；成功轉 `TERMINATED`。逾時/daemon error 有明確 safe error 與狀態。
- `delete`：僅終態可刪 metadata（或軟刪保留稽核，依 P2-02）；非終態拒絕。

驗收（unit，fake clock + fake registry，沿用 `backend/tests/test_correlation.py` 的 `FakeWebSocket`/直呼 `request`/`resolve_response` 模式）：每條 transition 的 allow/deny；offline/disabled node、missing/disabled runtime、invalid workspace（root 外、prefix collision 字串）、duplicate/idempotent create、terminate 逾時、rollback 無部分寫入。

## P2-06：Session HTTP API 與 relay 接線

新增 `app/api/http/sessions.py`（prefix `/api/sessions`，於 `main.py` 註冊），對齊 PRD §11.6：

```text
POST   /api/sessions                    require_action(session.create)
GET    /api/sessions                    require_action(session.view)   支援 node/status filter、分頁
GET    /api/sessions/{id}               require_action(session.view)
POST   /api/sessions/{id}/terminate     require_action(session.terminate)
DELETE /api/sessions/{id}               require_action(session.terminate)
POST   /api/sessions/{id}/attach        require_action(session.view)   → 回 ws-ticket（綁 user+session）
```

- DTO 加入 `app/api/http/schemas.py`：`CreateSessionRequest`、`SessionSummaryDTO`、`SessionDetailDTO`、`AttachTicketResponse`；欄位型別、時間（RFC 3339 UTC）、status enum 與 frontend `dto.ts` 對齊。
- `attach` 呼叫 P1 `WsTicketService` 簽發綁 `(user_id, session_id)` 的 single-use ticket，供 P2-09 的 terminal WS handshake 消費；ticket 不落 log。
- 錯誤：service 拋 `ApiError` 經 global handler 統一輸出 safe body；`NODE_OFFLINE`→409、`NODE_BUSY`→503、`REQUEST_TIMEOUT`→504、RBAC→403、驗證→422/400；不洩漏 daemon 內部訊息或 node 絕對路徑細節。
- **這是 `registry.request()` 首個 production caller**：確認 timeout、late-response、斷線 `_fail_pending` 在真實 route 下無 pending/future leak。新增 `Settings` 逾時參數（如 `session_start_timeout_seconds` 等），不硬編。

驗收（DB-backed，需 `CLIORA_TEST_DATABASE_URL`，httpx `AsyncClient` + fake daemon WS）：三角色（Admin/Developer/Viewer）對 create/view/terminate 的 allow/deny；create→daemon started→RUNNING、start_failed→FAILED、terminate→stopped→TERMINATED 全鏈；offline node 建立被拒；attach 回可用 ticket；timeout 清 correlation；分頁/filter 正確；log/audit 無 secret/terminal content。
