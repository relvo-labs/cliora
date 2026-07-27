# 04 — Observability、Alerts 與容量（P4-W4）

涵蓋 ticket **P4-09**（metrics 擴充、export、correlation log、alerts/runbooks）與 **P4-11**（代表性負載測試與有界性證明）。對應 `research/01/05` §P4-W4、tech §18.1/18.2/18.3、NFR-001/002/003/004。

---

## 現況

**已有的收集點**（P3 建立，兩份程式的註解都明確寫「tech §18 暫緩開放 Prometheus port，這裡是收集點，未來的 exporter（P4）讀同一結構」）：

- `backend/app/metrics.py`：thread-safe counters + bucketed histograms（buckets `0.05…10 s`），`increment()`／`observe()`／`counter_value()`／`histogram_value()`／`snapshot()`／`reset()`。目前只有 7 個 filesystem 系列。
- `daemon/internal/metrics/metrics.go`：counters + histograms（buckets `1…10^7`），`Increment()`／`Observe()`／`Snapshot()`。目前只有 6 個 filesystem 系列。
- `app/logging.py`：JSON formatter，自動帶 `request_id`（contextvar）+ record extras，含 9 個敏感 key 片段的 redaction。

**缺口**：tech §18.1 的 11 項 backend 指標只有 duration/timeout 兩類有部分覆蓋（且僅限 filesystem）；tech §18.2 的 daemon 指標**完全沒有進入 metrics registry**（資源值只經 heartbeat 送到 Central 的記憶體 registry）；**沒有任何 export 端點**；沒有 alert 規則或 runbook；沒有負載測試。DB pool 沒有明確上界（`create_async_engine(url, pool_pre_ping=True)`，用 SQLAlchemy 預設 5+10），因此 `database_pool_usage` 目前無意義。

---

## P4-09：Metrics 擴充、Export、Correlation Log、Alerts

### 1. Backend metrics（tech §18.1 全清單）

| 指標 | 型別 | Labels（低基數） | 來源 |
|---|---|---|---|
| `online_nodes` | gauge | — | `services/dashboard.py` 的 nodes block（或 exporter 取數時計算） |
| `active_daemon_connections` | gauge | — | `NodeConnectionRegistry.connection_count()` |
| `active_terminal_connections` | gauge | — | `services/terminal_relay.py` 的 hub 計數 |
| `running_sessions` | gauge | `runtime` | `terminal_sessions` 聚合 |
| `websocket_messages_total` | counter | `direction`(in/out)、`channel`(node/terminal)、`kind`(control/binary) | `api/ws/nodes.py`、`api/ws/terminal.py` |
| `websocket_bytes_total` | counter | 同上 | 同上 |
| `daemon_request_duration_seconds` | histogram | `type`(message type) | `services/registry.py` 的 `request()`（**通用化 P3 的 filesystem duration**） |
| `daemon_request_timeout_total` | counter | `type` | `registry.request()` 逾時路徑 |
| `terminal_client_queue_size` | histogram | — | `relay`/`terminal_relay` 的佇列觀測（bytes 與 frames 各一） |
| `terminal_queue_overflow_total` | counter | `reason` | 既有 overflow 路徑（送 `terminal.gap` + 1013 之處） |
| `http_request_duration_seconds` | histogram | `method`、`route`(template)、`status_class`(2xx/4xx/5xx) | 新增 middleware（沿用 `RequestIdMiddleware` 旁邊） |
| `database_pool_usage` | gauge | `state`(checked_out/available/overflow) | SQLAlchemy engine pool 狀態 |
| `audit_error_total` | counter | `action` | `services/audit.py` 寫入失敗（通用化 P3 的 `filesystem_audit_error_total`） |
| `metric_persist_error_total` | counter | — | `node_metric_samples` 寫入失敗（P4-06） |
| `authz_denied_total` | counter | `action`、`role`、`reason`(action/scope) | `services/authz.py`、`deps.py` |

**Label 白名單（硬性規則，ADR 0018）**：只允許 `op`／`type`／`code`／`reason`／`runtime`／`status`／`status_class`／`role`／`direction`／`channel`／`kind`／`method`／`route`／`state`／`stage`。**禁止** `node_id`／`user_id`／`session_id`／`path`／`filename`／`keyword`／`username`／任何自由文字。以測試斷言：對 registry 的 label key 做白名單檢查（新增一個 `metrics.increment`/`observe` 的 debug-mode 驗證，或在測試中掃描 `snapshot()` 的所有 key）。理由：高基數 label 會讓 metrics 後端記憶體爆掉，且 node/user id 進 metrics 等於把可識別資訊放進一個沒有 redaction 的 sink。

`route` 必須是**路由模板**（`/api/sessions/{session_id}/files/content`）而非實際路徑，否則就是高基數。

### 2. DB pool 明確化

`Settings` 新增 `db_pool_size`（10）、`db_max_overflow`（10）、`db_pool_timeout_seconds`（5）、`db_pool_recycle_seconds`（1800）；`Database.__init__` 傳入。pool 逾時映射為 `INTERNAL_ERROR`/503 + safe message，並計入 `database_pool_usage` 與 log。測試：以極小 pool（1+0）併發打，斷言逾時回 503 而非 hang，且 metric 遞增。

### 3. Daemon metrics（tech §18.2）

daemon 端 `internal/metrics` 新增：`daemon_uptime_seconds`、`daemon_active_sessions`、`daemon_cpu_usage`／`memory_usage`／`load_average`／`disk_usage`（gauge，來自既有 `systeminfo.ResourceSampler`）、`daemon_reconnect_total{reason}`、`daemon_heartbeat_sent_total`、`daemon_update_total{status,stage}`（P4-10）、`daemon_session_start_total{runtime,result}`。

**傳輸方式沿用 tech §18.2「先透過 heartbeat 回報」**：daemon **不開 Prometheus port**（避免在每個 node 上開監聽埠——與 outbound-only 的信任邊界一致）。heartbeat 已帶 `resources`；本期只需確保 `active_sessions` 與 uptime 正確，並在 Central 端把它們轉成 metrics + 持久化（P4-06 的 `node_metric_samples`）。daemon 內部的 metrics registry 供 `agentd doctor` 與本機除錯輸出使用（新增 `agentd doctor --metrics` 或 `agentd metrics` 印出 snapshot，**不開網路埠**）。

### 4. Export 端點

`GET /api/metrics`：

- **預設關閉**（`Settings.metrics_enabled = False`）；啟用後需**專用 `metrics_scrape_token`**（**定案，ADR 0018**：不複用 `audit.view`，否則只為 scrape 就得建一個具 audit 讀取權的服務帳號；Prometheus 不持有 user session）。是否再綁內網介面由 `docs/deployment.md` 依部署拓樸決定。
- 輸出 **Prometheus text exposition format**，以標準庫字串產生（不引入 client library，避免與既有 registry 雙軌）。histogram 以 `_bucket{le=...}`／`_sum`／`_count` 展開（`app/metrics.py` 的 histogram 已存 cumulative-ready 結構，需在 exporter 端做 cumulative 累加——**注意目前 `observe()` 只把值放進第一個符合的 bucket（非 cumulative），exporter 必須累加，且要補測試**）。
- gauge 類（online_nodes、pool usage、running sessions）在 scrape 時即時取數，逾時（如 1 s）則略過該指標並輸出 `cliora_scrape_error{block=...} 1`，**不讓 scrape 失敗**。
- 端點本身不進 audit、不寫高頻 log。

### 5. Correlation log（tech §18.3）

共通欄位已在 `JsonFormatter`：`timestamp`／`level`／`service`／`logger`／`message`／`request_id` + extras。本期確保**每個重要路徑都帶齊** `node_id`／`session_id`／`user_id`／`event`／`code`／`duration_ms`：

- session 生命週期（create/start/attach/takeover/terminate/failed）。
- daemon 連線（authenticated/register/heartbeat-miss/disconnect/reconnect）。
- terminal relay（writer 取得/釋放/queue overflow/gap/disconnect）。
- filesystem（P3 已有，沿用）。
- update（P4-10 每個 stage）。
- 授權拒絕（`authz_denied`）。

**redaction 驗證**：沿用 P3 的做法——以 `JsonFormatter` 的**實際輸出**斷言不含 terminal bytes、file content、search keyword 明文、password、token、Ed25519 私鑰、完整 workspace 絕對路徑（除非該路徑是使用者自己輸入且已在 P2 接受的顯示範圍）。新增一個掃描測試：對一輪完整 E2E 的 log 做正則掃描（進 `p4.yml` 的 security job）。

daemon 端 log 沿用其既有 structured logger，確保帶 `node_id`／`session_id`／`request_id` 以便與 Central 對接（同一 `request_id` 可在兩邊找到）。測試：一次 filesystem/update 請求，斷言 Central 與 daemon log 出現相同 `request_id`。

### 6. Alerts 與 Runbooks

- **Alert 規則檔**：`deploy/prometheus/alerts.yml`（Prometheus rule 格式），門檻與 for-duration 見 `00-execution-plan.md` §6：heartbeat loss、queue saturation、timeout surge、DB exhaustion、update failure。另加：`authz_denied_total` 突增（可能是攻擊或權限設定錯誤）、`audit_error_total` > 0（稽核鏈路故障是安全事件）。
- **Runbooks**：`docs/runbooks/` 六份：`heartbeat-loss.md`、`queue-saturation.md`、`timeout-surge.md`、`db-exhaustion.md`、`update-failure.md`、`backup-restore.md`。每份固定結構：**症狀 → 對應告警 → 立即影響 → 診斷步驟（含要看哪個 metric/log 查詢/audit action）→ 緩解 → 根因排查 → 驗證恢復 → 事後動作**。
- **可觸發性驗收**（research 要求「告警可在演練環境觸發並依 runbook 處置」）：`scripts/p4/drills/` 提供每個告警的觸發腳本（停掉 daemon → heartbeat loss；灌 flood → queue saturation；讓 daemon 不回應 → timeout surge；把 pool 設為 1 併發打 → DB exhaustion；讓 checksum 不符 → update failure）。演練記錄進 `artifacts/p4/<run>/drills.md`，每項附「告警觸發時間、runbook 步驟是否可執行、恢復時間」。

### 測試（P4-09）

- 每個新指標在對應情境下遞增／被觀測（unit + DB 測試）。
- **label 白名單掃描**（任一違規即失敗）。
- exporter：格式正確（可被 `promtool check metrics` 或自寫 parser 驗證）、histogram cumulative 正確（`_bucket` 單調遞增且 `le=+Inf` == `_count`）、未授權 401/403、關閉時 404、gauge 取數逾時不讓 scrape 失敗。
- DB pool 逾時行為。
- correlation：同一 `request_id` 貫穿 Central↔daemon；log redaction 掃描。
- runbook 與 alert 規則檔的存在性 + alert 規則語法檢查（`promtool check rules`）。

---

## P4-11：容量與有界性

### 目標（NFR-003）

100 nodes、每 node 10 個同時 session、全平台 500 個同時 terminal WebSocket。research 驗收：「slow client/flood 不造成 unbounded memory」。

### Harness

`scripts/p4/load/`，三個可獨立執行的部分（皆為單機可跑，**不需要 100 台真實 VM**）：

1. **`fake_nodes.py`（或 Go 版）**：以 100 個 goroutine/task 各自建立一條到 Central 的 daemon WSS 連線，完成 Ed25519 challenge（用測試用 credential 批次註冊）、送 heartbeat、回應 `session.start`/`attach`/`filesystem.*` 等請求。**它是 protocol-level 的假 daemon**，不啟動真 tmux，因此可在單機模擬 100 nodes。真實 tmux 行為已由 P2/P3 的 integration 測試覆蓋。
2. **`terminal_clients.py`**：建立 500 條 browser terminal WS（含 ws-ticket 取得），其中一部分為 **slow client**（故意不讀 socket）、一部分為 **flood client**（高速送 input），其餘正常。量測：輸入到顯示的往返延遲分佈（NFR-001 < 200 ms）、queue 深度、overflow 次數、gap 事件、被關閉的連線數。
3. **`session_churn.py`**：持續建立/終止 session 至每 node 10 個上限，驗證 `sessions_per_node_max` 生效、`SESSION_LIMIT_REACHED` 正確、無 pending/goroutine leak。

### 必須證明的有界性

| 項目 | 判定 |
|---|---|
| Central RSS | 負載期間有上界且在負載結束後回落（記錄峰值；沒有隨時間單調成長） |
| Terminal queue | 每 client 的 bytes/frames 不超過 `terminal_queue_max_bytes`/`max_frames`；slow client 觸發 overflow → `terminal.gap` + 1013 關閉，**不拖垮其他 client** |
| Pending requests | 每 node 不超過 `pending_requests_max`(128)，超過回 `NODE_BUSY`；斷線時全數 fail 且 correlation table 清空（P3 已驗證 128 上限，本期在 100 nodes 併發下複驗） |
| DB pool | 使用率有上界；逾時回 503 而非 hang；無連線洩漏（負載結束後 checked_out 歸零） |
| Task/goroutine | 負載結束後 asyncio task 數與 daemon goroutine 數回到基線（no leak） |
| Latency | terminal 往返 p50/p95/p99；node 列表 < 2 s；dashboard summary 回應時間 |

### 判定與產出

`artifacts/p4/<run-id>/capacity.json`：環境（CPU/記憶體/Python/Go 版本）、實際達到的 node/session/WS 數、各項延遲分佈、記憶體曲線、queue/overflow/timeout/NODE_BUSY 計數、pool 使用率、leak 檢查結果、以及**每項 NFR 的 pass/fail**。未達標項在 `docs/p4-report.md` 記 release decision（含影響與緩解）。

harness 以「超標即非零退出」的方式實作（沿用 P2 `relay_bench.py`／P3 `files_bench.py`／`bench_test.go` 的預算模式），使其可進 CI 的 merge/RC 階段而不只是一次性量測。

### 測試（P4-11）

- harness 自身的小規模 smoke（如 5 nodes／10 WS）進每次 PR，確保它不腐化。
- 完整規模（100/500）在 merge 主分支與 RC 執行（`p4.yml` 的 `capacity` job，`continue-on-error: false`）。
- slow client 與 flood 的有界性測試可在小規模確定性地驗證（1 個 slow client + 已知 queue 上限），大規模只是複驗。

**對應需求**：NFR-001（latency）、NFR-002（可用性/重連）、NFR-003（規模）、NFR-004（可維運性：structured log、log level、doctor、版本、連線測試、runtime 偵測）、tech §18、PRD §20.5（WebSocket 大量輸出風險）。
