# 00 — P2 執行總控（Session 與 Terminal）

## 1. 成功定義與非目標

P2 要退休六個最高風險：**(a)** P0 遺留的 recovered reattach 阻塞是否可根治（tmux attach client 殘留）、**(b)** session 生命週期狀態機是否在 offline/missing-runtime/invalid-workspace/duplicate/race 下仍一致且可回復、**(c)** runtime launcher 是否只以 allowlisted argv 啟動且 launch 前重做 workspace canonical validation、**(d)** browser↔Central↔daemon 的 terminal relay 是否在 burst/slow-client/斷線/偽造 frame 下有界且能安全清理、**(e)** single-writer/viewer 與 takeover 是否 server 端強制（偽造 input 一律拒絕）、**(f)** 端到端延遲是否符合 PRD < 200 ms。

P2 必須交付：

- **Session domain**：`STARTING/RUNNING/DISCONNECTED/EXITED/FAILED/TERMINATING/TERMINATED` 狀態與合法 transition；create/list/detail/attach/terminate/delete metadata；mutation 明確定義 conflict/idempotency/timeout/rollback。Central 只接受 `runtime ID + workspace + name + rows/columns`，**不接受 command/binary/shell string**。
- **Data**：`terminal_sessions`、`session_connections` 兩張表（Alembic upgrade/downgrade + rollback 測試）；session metadata durable，**terminal bytes 不入 DB/log**。RBAC 新增 session/terminal action 並以 versioned seed migration 落地。
- **Daemon**：把目前只存在於 dev relay 的 dispatch 接進 production `internal/connection` 連線；runtime adapter 建 allowlisted argv；tmux session 以 internal UUID 命名並帶可重建 metadata；terminate graceful/force policy；daemon restart 掃描 `cliora-<uuid>` 與 Central reconcile；process/PTY/goroutine/cancellation ownership 清楚。
- **Terminal relay**：`/ws/sessions/{session_id}/terminal` browser WS（ws-ticket + session RBAC）；control text frame + terminal binary frame；resize/heartbeat/attach/resume/exit/error 完整；per-session `BrowserChannel` queue/frame/scrollback 上限與 backpressure metric；timeout/cancel/disconnect 清 correlation、task 與 subscription。
- **Writer/viewer**：預設一個 writer，其餘 viewer read-only；writer disconnect 保留窗、釋放與 takeover（resource RBAC + confirm + 通知現任 + audit）；viewer 偽造 input frame 由 server 拒絕。
- **Frontend**：Sessions list、New Session dialog（Node/runtime/workspace 相依選項，offline/missing-runtime/forbidden 於提交前與 server 端雙重阻擋，starting/timeout/conflict/daemon-failure/retry）、Session Workspace route（三欄、可調整/收合、狀態可恢復）、xterm production composable（原始 bytes、resize debounce/fit、scrollback/search/copy、stale/gap、exit 不盲目重連、切 session 完整 dispose）。
- **Audit/observability**：session create/attach/takeover/terminate/failure 記 metadata audit（不含 terminal content）；terminal/session/queue/timeout/reconnect metrics；request/node/session/user ID correlation log；argv 可能敏感值 redact。

P2 明確**不做**：workspace 檔案樹、檔名搜尋與唯讀預覽（P3，`filesystem.*`/`workspace.list_dir`/`file.read`）、RBAC 完整營運/Audit 檢視介面（P4）、Dashboard 真實聚合（P4）、`workspace_favorites` 與「最近使用 workspace」（FR-WORKSPACE-004/005，可延後至 P3/P4）、session replay 與 terminal 全量保存（永久非目標）、多 agent orchestration、任意 shell、Central SSH、水平擴充。**P0 dev gateway（`/ws/p0/*`、`CLIORA_P0_ENABLED`、fixed identity、shared token）在 P2 被認證的 session-scoped relay 取代後移除或封存於明確 dev flag，正式路徑不得依賴它。**

## 2. 固定實作基線

| 項目 | P2 決定 |
|---|---|
| Layout | 沿用現況；backend 新增 `app/api/http/sessions.py`、`app/api/ws/terminal.py`、`app/services/sessions.py`、`app/repositories/sessions.py`；daemon 擴充 `internal/session`、`internal/runtime`，並在 `internal/connection` 接上 control dispatch；frontend 新增 `views/SessionsView.vue`、`views/SessionWorkspaceView.vue`、`components/session/*`、`stores/sessions.ts` |
| Runtime | 沿用 ADR 0001：Python 3.12.3、Go 1.26.5、Node 22.14.0、tmux ≥3.4 |
| Session host | 系統 `tmux`，名稱嚴格 `cliora-<lowercase UUID>`（沿用 P0）；PTY 以 `creack/pty`（沿用 P0） |
| Session ID | Central 生成 UUID（durable），daemon 據以命名 tmux 並回報；binary frame 以 16-byte session UUID 定址（沿用 P0 header：version、kind 1=input/2=output、session UUID、payload） |
| 建立輸入 | 僅 `runtime`（allowlist `claude`/`codex`）、`workspace`（allowed root 下合法目錄）、`name`、`rows`(2..300)/`columns`(2..500)；**第一階段不接受任意啟動參數與環境變數**（FR-SESSION-001 選填欄位延後） |
| Writer policy | owner 為預設 writer，viewer 唯讀；writer 斷線保留窗後釋放；takeover 需 resource RBAC + 顯式確認 + 通知現任 + audit（沿用 traceability §5 決策） |
| Scrollback/續傳 | reattach 以 tmux `capture-pane` 取最新 bounded snapshot（上限見 §6），截斷時 `truncated=true` 並送 `terminal.gap {reason:"reattach_boundary"}`；**不保證 exact replay，不於 Central 保存 raw bytes**（沿用 ADR 0004） |
| Terminal storage | 沿用 ADR 0004：terminal input/output 不進 log/audit/DB |
| Browser WS auth | `/ws/sessions/{id}/terminal` 以一次性短效 ws-ticket 認證（沿用 P1 `ws_ticket`，綁 user+session resource），連線後做 session 層 RBAC；**不放長效 JWT 於 query string 或 log** |
| Time | 內部 aware time；傳輸 RFC 3339 UTC `Z`；attach/terminate timeout、writer 保留窗、reconnect backoff 以 monotonic clock |

任何偏離上表的實作差異先記 ADR 再改，不以未量測預設值當永久產品限制。

## 3. 垂直架構與 ownership

```text
Browser (Vue Router + Pinia)
  ├─ HTTP: api/client → /api/sessions（create/list/detail/terminate/delete/attach）
  │        auth guard、RBAC、typed DTO、safe error、request_id
  └─ Terminal WS: /ws/sessions/{id}/terminal（ws-ticket 認證 → session RBAC）
           control text frame + terminal binary frame；useTerminalSession 擁有 socket/xterm/addons/observer

FastAPI Central
  api/http/sessions.py   session HTTP boundary（authN+authZ+validation）→ services/sessions.py
  api/ws/terminal.py     browser terminal WS boundary + per-session BrowserChannel（byte-aware bounded queue）
  services/sessions.py   狀態機、transition、conflict/idempotency、writer/viewer/takeover 規則
  repositories/sessions.py  terminal_sessions / session_connections（唯一寫 durable state 之處；不寫 terminal bytes）
  services/registry.py   NodeConnectionRegistry.request()（P2 首個 production caller）→ 對 daemon 發 session.start/stop/list/recover 並 correlate
        └─ /ws/nodes/{node_id}（P1 已建立的 Ed25519 daemon 連線）
             └─ Go daemon
                  connection/  單一 read owner + 單一 write owner；**接上 control dispatch（目前 readLoop 為 no-op）**
                  session/     tmux/PTY lifecycle：start/attach/resize/stop、restart 掃描與 reconcile
                  runtime/     claude/codex allowlisted BuildCommand（P2 真正啟動）
                  workspace/   launch 前 canonical validation（root 下、symlink 解析後仍在 root）
```

資源 owner：每個 session HTTP request 在 boundary 完成 authN/authZ/validation 後才進 service；service 內以單一 transaction 完成 metadata mutation，daemon 交互經 `registry.request()`（帶 timeout、correlation、late-response cleanup）。每條 browser terminal WS 由一個 handler 擁有 read task、per-session `BrowserChannel` 與 writer 標記；session→BrowserChannel/subscription 是唯一 fan-out owner。Daemon 一個 goroutine 擁有 socket read、一個擁有 write；每個 session 的 tmux/PTY attach、capture、cancellation 由 session owner 序列化，attach 切換期間序列化 capture 與 live subscription，shutdown 時可被取消並等待結束。

## 4. 執行順序與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | **P2-01** | **Gate-0**：關閉 P0 recovery blocker（殘留 tmux attach client 阻塞 recovered reattach）；process-level 隔離測試證明 rapid reattach 與 daemon-restart recovery 無 leaked client；決策 control-mode pipe bridge vs attach subprocess-group cleanup → ADR 0012 | 無 |
| 0 | P2-02 | 決策 ADR：session 狀態機與 transition、writer/takeover policy、scrollback/snapshot 上限、`session_connections` 模型、browser terminal WS 認證（ws-ticket+session scope）、P2 limits | 無 |
| 0 | P2-03 | protocol v1.2 凍結：`session.start/started/start_failed/stop/stopped/list/list_result/recover/status_changed`、`terminal.attach/attached/detach/resize/gap/exited/error`、writer `terminal.control_acquire/control_release`、新 error codes；fixtures + manifest + 三語言 codec | P2-02 |
| 1 | P2-04 | Alembic migration：`terminal_sessions`、`session_connections`；RBAC session/terminal action 之 versioned seed migration（clean/repeat/prior-data/contraction 測試） | P2-02 |
| 1 | P2-05 | Session domain service + repository：狀態機、合法 transition、guard（offline/disabled node、missing/ disabled runtime、invalid workspace、duplicate、rollback） | P2-03、P2-04 |
| 1 | P2-06 | Session HTTP API（POST/GET list/detail/terminate/delete + attach ticket），RBAC boundary，safe error；**接上 `NodeConnectionRegistry.request()`（首個 production caller）** | P2-05 |
| 2 | P2-07 | Daemon session lifecycle 接進 production `internal/connection`：`session.start/stop/list/recover` handler、runtime allowlist launcher、launch 前 workspace canonical validation、tmux 命名/metadata、terminate graceful/force、ownership/cancellation | **P2-01**、P2-03 |
| 2 | P2-08 | Daemon restart reconciliation：掃描 `cliora-<uuid>`、與 Central 對帳、`session.status_changed` 事件、孤兒 session 處置 | P2-07 |
| 3 | P2-09 | Browser terminal WS relay（`/ws/sessions/{id}/terminal`）：ws-ticket+RBAC handshake、per-session `BrowserChannel`、control/binary frame、resize/heartbeat/attach-resume/exit/error、queue/frame/scrollback bounds + backpressure metric、timeout/cancel/disconnect cleanup | P2-06、P2-07 |
| 3 | P2-10 | Single writer / viewers / takeover：writer 選定、viewer 唯讀、writer disconnect 保留與釋放、takeover（RBAC+confirm+notify+audit）、server 拒絕偽造 input | P2-09 |
| 4 | P2-11 | Frontend：Sessions list + New Session dialog（相依選項、offline/missing-runtime/forbidden 前置阻擋、validation/starting/timeout/conflict/daemon-failure/retry） | P2-06 |
| 4 | P2-12 | Frontend：Session Workspace route（三欄布局、可調整/收合、header 狀態/reconnect/terminate、切 session 保留狀態） | P2-11 |
| 4 | P2-13 | xterm production composable：原始 bytes、resize debounce/fit、scrollback/search/copy、stale/gap、exit 不盲目重連、切 session/離頁完整 dispose；以 ws-ticket + session-scoped WS 取代 P0 dev token | P2-09、P2-12 |
| 4 | P2-14 | Writer/viewer UI：角色明示（不只顏色）、takeover 請求/確認/通知、danger action confirm 保持 focus | P2-10、P2-13 |
| 5 | P2-15 | Audit 與 observability slice：session 事件 audit（無 terminal content）、metrics、correlation log、argv redaction | P2-06、P2-09、P2-10 |
| 5 | P2-16 | 驗證：contract/unit/daemon-race/integration/E2E、latency 量測、slow-consumer RSS 證據、操作證據包、exit review（`docs/p2-report.md`） | 全部 |

關鍵路徑為 `P2-01 → P2-03 → P2-05 → P2-06/P2-07 → P2-09 → P2-13 → P2-16`。Wave 內可並行，但修改契約或 schema 的 PR 必須先於 consumer 合併。

## 5. 每張 ticket 的完成格式

每張 ticket 至少附：變更檔案、契約/假設、成功與失敗測試（含 forbidden/timeout/disconnect/rollback/race）、實際執行命令（`make contract/unit/integration/e2e`、`go test -race`）、log/metric/audit 影響（且證明無 secret/token/**terminal content**）、以及對應 requirement（`FR-SESSION-*`、`FR-TERM-*`、`FR-RUNTIME-002/003`、`FR-WORKSPACE-003`、`FR-CONN-*`、`SEC-001/002/003/006`、`NFR-*`）。跨語言行為改變時，同一變更必須同步 schema、`manifest.json`、fixtures 與 Python/Go/TS 三個 consumer。DB 行為改變時，同一變更必須提供 upgrade + downgrade migration 與 rollback 測試。時間/retry/timeout/writer 保留窗以 fake/monotonic clock 測；UUID/ULID/nonce 用可注入 deterministic source。

## 6. P2 預設限制與參數（待量測，記入 ADR 0012/0013）

| 項目 | 初值 | 滿額/逾時行為 |
|---|---:|---|
| 每 node session 上限 | 10（NFR-003 基準） | 超過回 `SESSION_LIMIT_REACHED`，不建立 |
| 全平台 terminal WS | 500（NFR-003 基準） | P2 以量測驗證；超載時新連線排隊或拒絕，不 unbounded |
| Control request timeout | session.start 30s、stop 20s、attach 15s、list 15s（tech §7.3） | `REQUEST_TIMEOUT`，清 correlation entry，session 標記對應狀態 |
| Terminate graceful 等待 | 10s（graceful signal 後） | 逾時送 force kill，最後更新狀態 |
| Writer 斷線保留窗 | 30s（monotonic） | 逾時釋放 writer，session 進 `DISCONNECTED`/可被 takeover |
| Reattach snapshot 上限 | 2 MiB（tmux capture-pane） | 截斷 `truncated=true` + `terminal.gap{reattach_boundary}` |
| Per-session terminal queue | bytes + frames 雙上限（沿用 P0 byte-aware queue） | overflow 送 `terminal.gap` 或 close 1013，不阻塞上游 PTY reader |
| Control frame 上限 | 64 KiB（`MaxPayload`，沿用 P0） | `FRAME_TOO_LARGE` 安全 close |
| Terminal binary frame 上限 | 沿用 P0 二進位上限 | 超過安全 close，不寫 payload log |
| Per-node pending requests | 128（沿用 P1 `pending_requests_max`） | 超過回 `NODE_BUSY` |
| Reconnect backoff | 1/2/5/10/30s + ≤250ms jitter（沿用 FR-TERM-006/P0） | 成功即重置 |
| 端到端額外延遲 | < 200 ms（NFR/PRD） | 量測後定稿，未達標列 release decision |

限制與參數皆以可設定值實作，量測後在 ADR 接受或修訂，不硬編碼為永久產品限制。

## 7. 決策閘門（P2-02 前必須記錄）

1. **Session 狀態機**：`STARTING/RUNNING/DISCONNECTED/EXITED/FAILED/TERMINATING/TERMINATED` 的合法 transition、觸發來源（HTTP mutation vs daemon `status_changed` vs timeout）、以及 `DISCONNECTED`（無 attach client）與 node offline 的區別。
2. **Writer/takeover policy**：writer 保留窗長度、釋放條件、takeover 是否需 admin override 或 owner 同意、通知與 audit 內容（沿用 traceability §5 預設：owner 為 writer、viewer 不可輸入、顯式授權才接管）。
3. **Scrollback/續傳**：tmux `capture-pane` snapshot 上限與 `terminal.gap` 語意；是否啟用 daemon ring buffer（FR-TERM-004 二選一，MVP 採 tmux scrollback）。
4. **`session_connections` 模型**：欄位（session_id、user_id、role writer/viewer、connected_at、last_seen_at、closed_at）、是否 durable 或僅記憶體；audit 需求下最小持久化。
5. **Browser terminal WS 認證**：ws-ticket 綁 `(user_id, session_id)`、TTL、single-use、handshake 失敗與過期行為；`ws://` 僅限明確 dev flag。
6. **P2 limits**：每 node session 數、terminal queue bytes/frames、snapshot 上限、writer 保留窗、terminate graceful 等待——皆以可設定值並量測定稿。
7. **exit code 保真度**：ADR 0004 記錄 P0 的 `terminal.exited.code` 是 attach client 狀態而非 runtime 真實 exit code；P2 是否以 `#{pane_dead_status}` 於 reap 前查詢真實 exit code（建議納入，否則明確記為已知限制）。

## 8. 明確非目標與變更控制

P2 不加入 workspace 檔案樹/搜尋/預覽（P3）、RBAC 完整營運與 Audit 檢視 UI（P4）、Dashboard 真實聚合（P4）、`workspace_favorites`/最近使用 workspace、session replay、terminal 全量保存、任意啟動參數/環境變數自訂、macOS daemon、任意 shell、Central SSH、多 agent orchestration 或水平擴充。需要其中任一項時，先依 `research/01/06-requirement-traceability.md` §6 變更 canonical requirements，再更新本目錄與階段出口，不能只在 implementation ticket 中暗自擴張。
