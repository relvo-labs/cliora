# 00 — P4 執行總控（管理、維運與上線強化）

## 1. 成功定義與非目標

P4 要退休七個最高風險：**(a)** 授權是否在 HTTP／browser WS／daemon WS／UI 四處由**同一份 domain policy** 決定，且 attach/takeover/terminate/read file 有**資源範圍與 owner 規則**（不是「有 role 就能動任何資源」），Viewer 的偽造 mutation 一律失敗；**(b)** 每個 SEC-006 重要操作是否產生**單一、可追蹤、已最小化**的 audit（actor + resource + `request_id` + aware time），且沒有任何 secret／terminal bytes／file content 漏進 audit／log／metrics；**(c)** Dashboard 是否只顯示**真實聚合**並在資料不新鮮或部分失敗時明確標示 freshness／partial，而不是用快取或空值偽裝即時；**(d)** 指標與告警是否足以在**代表性負載**（100 nodes、10 sessions/node、500 terminal WS）下發現 heartbeat loss／queue saturation／timeout surge／DB exhaustion，且 slow client 與 flood 不造成 unbounded memory；**(e)** daemon update 是否**只接受 allowlisted release**、強制驗 checksum、原子替換、health check 失敗可 rollback、期間不以 root 常駐、且 existing tmux session 的保留與 reconciliation 有文件與測試；**(f)** PostgreSQL 備份／還原是否可演練且**證明不含 terminal raw log**，正式部署的 HTTPS/WSS、secret 注入、migration 順序、readiness 與 graceful shutdown 是否可驗證；**(g)** 原型殘留（硬編碼值、CDN 字型、`min-width`、孤兒元件、P0 dev relay）是否已從 production bundle／app 移除。

P4 必須交付：

- **RBAC 完整化（P4-W1）**：單一 source of truth 的 permission matrix（domain 層），涵蓋 Admin/Developer/Viewer × node／enrollment／session／terminal writer／files／audit 的每個 action；**resource scope/owner 規則**（誰能 terminate 誰的 session、誰能 takeover、Viewer 能 attach 什麼）；經 idempotent Alembic seed migration 綁定並測 clean／repeat／prior-data／**permission contraction**（移除權限也要生效）；每個 endpoint 與每個 WS message type 都有 allow/deny 測試。
- **Audit 完整化與可查詢（P4-W2）**：coverage 涵蓋 login／security event、enrollment、node register/disable/remove、credential revoke、session create/attach/takeover/terminate/failed、敏感路徑拒絕、**daemon update**；metadata 最小化 + redact + aware timestamp + actor/resource/`request_id`；Admin audit 查詢 API 與 UI（filter、pagination、empty/loading/error、timezone）；retention/backup 決策落地。
- **Dashboard 與 error management（P4-W3）**：真實 aggregates（online/offline nodes、running sessions、per-runtime、runtime health、recent activity、異常 Node）；stale/partial 明確標示 freshness；node/session/error detail 有可行建議且**不把 daemon internal error 原樣暴露**；所有原型硬編碼值／token／版本／日期／CDN 依賴移除。
- **Observability 與容量（P4-W4）**：backend metrics（connections、sessions、WS bytes/messages、queue、timeout、HTTP latency、DB pool）與 daemon heartbeat metrics（CPU/memory/load/disk/session/uptime）皆可 scrape 且 log 可 correlation；alerts/runbooks（heartbeat loss、queue saturation、timeout surge、DB exhaustion、update failure）；代表性負載測試與 slow client/flood 有界證明。
- **Daemon release/update（P4-W5）**：amd64/arm64 reproducible artifacts、`checksums.txt`、**version manifest 端點**、簽章/來源策略；update 只接受 allowlisted release、驗 checksum、原子替換、health check、失敗 rollback、non-root；升級時 tmux session 保留／reconciliation 有文件與測試；`doctor`/`version`/UI 顯示 current/latest/update status，**client 不得任意指定 URL/binary**。
- **Backup、deployment 與 release gate（P4-W6）**：PostgreSQL backup/restore 演練（並證明不含 terminal raw log）；production HTTPS/WSS、secret 注入、migration order、readiness、graceful shutdown；瀏覽器 Chrome/Edge/Safari/Firefox smoke 與 Linux 支援矩陣；security review（stolen token、replay、forged frames、path attacks、viewer input、WS flood、log leakage）；release checklist（accessibility、performance、E2E、race、dependency/artifact scan）。
- **FR-WORKSPACE-004/005（P4-13）**：`workspace_favorites` 表 + 最近使用 workspace，整合進 P3 tree 與建立 session 流程。這是 P4 唯一新增的資料面功能；**仍必須經 daemon allowed-root 驗證**，收藏只是 Central 的 UX 捷徑，不得成為繞過路徑驗證的旁路。

P4 明確**不做**：Web 檔案編輯／寫入／上傳／下載、任意 shell、Central SSH、Git automation、Terminal 全量保存或 session replay、CLI 語意解析、多 agent orchestration／task routing、Kubernetes agent、message broker、backend 水平擴充、多租戶 billing／token 成本分析、全文（內容）搜尋、即時 filesystem watch、macOS daemon（PRD §4／tech §24 永久非目標）。另外 **P4 特別要避免的「順手擴張」**：把 metrics export 做成完整監控平台或自訂儀表板（只做 exporter + 一份 Grafana 參考 dashboard 與 alert 規則）、把 audit 做成 SIEM／可匯出報表引擎（只做 filter + pagination + 明確 retention）、把 update 做成自動排程／批次升級（MVP 是手動觸發，Central 只提供 manifest 與可稽核的觸發）、把 RBAC 做成自訂角色／權限編輯 UI（三個固定角色，permission 由 migration 定義）。需要其中任一項時，先依 `research/01/06-requirement-traceability.md` §6 變更 canonical requirements。

## 2. 固定實作基線

| 項目 | P4 決定 |
|---|---|
| Layout | 沿用現況。backend 新增 `app/services/authz.py`（resource-scope/owner 規則，rbac.py 保留 action 詞彙）、`app/api/http/audit.py`、`app/services/audit_query.py`、`app/api/http/dashboard.py`、`app/services/dashboard.py`、`app/api/http/releases.py`、`app/services/releases.py`、`app/api/http/metrics.py`（exporter）、`app/repositories/{audit,node_metrics,favorites}.py` 擴充；daemon 新增 `internal/update/`（manifest fetch、checksum、atomic swap、rollback）與 `connection/update_handlers.go`；frontend 新增 `views/{DashboardView,AuditView}.vue`、`components/dashboard/*`、`components/audit/*`、`stores/{dashboard,audit,favorites}.ts` |
| Runtime | 沿用 ADR 0001：Python 3.12.3、Go 1.26.5、Node 22.14.0。**不新增前端執行期依賴**（Dashboard/Audit 以現有 Naive UI + design tokens 實作）；後端 exporter 以標準庫產生 Prometheus text format，**不引入 client library**（避免與現有 in-process registry 雙軌） |
| 授權模型 | `rbac.py` 保持「action 詞彙 + role→actions」；新增 `authz.py` 提供 `authorize_session_action(user, session, action)` 等 **resource-scope 判斷**，回傳統一的 `ApiError("FORBIDDEN", …, 403)`。HTTP boundary、browser WS handshake、terminal 訊息迴圈、UI capability flag **四處共用同一函式**（UI 透過 `/api/auth/me` 取得已計算的 capability 清單，不在前端重寫規則） |
| Owner 規則（P4-01 定案） | 見 §7 第 1 項的預設：session **owner + Admin** 可 terminate；**owner 或具 `terminal.takeover` 者**可 takeover（皆寫 audit）；具 `session.view` 者可 read-only attach；`session.create` 者只能為自己建立 |
| Audit | 沿用 `app/services/audit.py` 單一寫入點；**新增 `request_id` 進 metadata**（取自 `app.logging.request_id_var`，daemon 觸發的事件取該次 relay 的 request_id）；新增 `daemon.update` 系列 action；查詢一律 server 端分頁 + 條件過濾；retention 以**設定值 + 明文文件化的清理程序**實作，不做自動刪除排程（見 §6） |
| Metrics | 沿用 `app/metrics.py` 與 `daemon/internal/metrics` 為唯一收集點，新增 tech §18.1/18.2 缺少的系列；export 端點 **Prometheus text format**，**需授權**（`audit.view` 或獨立的 scrape token）且可完全關閉；label 僅低基數（`op`/`code`/`reason`/`runtime`/`status`/`role`），**禁止 node_id/user_id/session_id/path/keyword 作為 label** |
| Daemon 資源歷史 | heartbeat `resources` 除既有的記憶體 registry 外，**降頻**寫入新表 `node_metric_samples`（預設每 60 s 一筆／每 node，bounded retention）供 Dashboard 與趨勢使用；寫入失敗不影響 heartbeat 處理 |
| Update 來源 | **只接受 Central 的 release manifest**（`GET /api/releases/manifest`，回 version + per-arch filename + sha256），binary 只從 Central `GET /api/downloads/{allowlisted}` 取得；daemon 端**不接受任何來自 control frame 或 CLI flag 的任意 URL／檔名／binary path**（SEC-002 延伸）。checksum 驗證失敗即中止，不落地 |
| Update 執行 | `agentd update` 由 node 端 CLI 觸發（sudo，短暫提權僅為替換檔案與重啟 unit），或由 Central 送 `daemon.update` control frame 使 daemon 自行執行同一流程；長駐程序仍為 non-root（SEC-007）。tmux server 由 session 使用者持有、與 daemon 程序分離，因此升級期間 session 續存，重啟後走 P2 既有 recovery（ADR 0012） |
| 部署 | 新增 `deploy/compose/`（nginx + backend + frontend static + postgres，選配 prometheus/grafana profile）與 `deploy/nginx/`；secret 一律由環境注入，image 不含 secret；migration 由**獨立一次性 job** 在 backend 啟動前執行（不在 lifespan 自動 migrate）；`/readyz` 已比對 migration head，沿用 |
| Graceful shutdown | 收到 SIGTERM 後停止接受新連線 → 對 browser terminal WS 送明確關閉理由並 drain（上限 `shutdown_drain_seconds`）→ 關 daemon WS（daemon 走既有 backoff 重連）→ dispose DB engine。**不終止任何 tmux session** |
| Time | 內部 aware time；傳輸 RFC 3339 UTC `Z`；畫面本地化並顯示時區。heartbeat 逾時、update health check、drain、alert for-duration、relay timeout 皆 **monotonic** |
| 對外錯誤 | 沿用 `app/api/errors.py` 的 `{error:{code,message},request_id}`；**daemon internal error 一律映射為 stable code + safe message**，原始字串只進 log。UI 對每個 code 顯示「原因 + 下一步」 |

任何偏離上表的實作差異先記 ADR（0016/0017/0018）再改，不以未量測預設值當永久產品限制。

## 3. 垂直架構與 ownership

```text
Browser (Vue Router + Pinia)
  ├─ DashboardView（stores/dashboard）：GET /api/dashboard/summary
  │     freshness 標示、partial 區塊降級、offline fleet、empty deployment、角色差異
  ├─ AuditView（stores/audit，需 audit.view）：GET /api/audit?filters&cursor
  │     server 端分頁、filter（action/actor/node/session/時間範圍）、timezone 顯示
  ├─ NodeDetail：current/latest daemon version + update status（唯讀顯示，不指定 URL/binary）
  └─ capability flags 來自 /api/auth/me（server 計算），UI 隱藏 ≠ 授權

FastAPI Central
  api/http/deps.py        require_action()（action 層）
  services/authz.py       resource scope / owner 規則（session/node/file 的單一判斷處）★新增
  api/http/audit.py       audit 查詢（audit.view）→ services/audit_query.py（bounded page、無內容欄位）
  api/http/dashboard.py   aggregates（node.view）→ services/dashboard.py
                          （每區塊獨立取數 + per-block freshness/degraded 標記）
  api/http/releases.py    GET /api/releases/manifest（version + arch + sha256；來源為 artifacts_dir）
  api/http/metrics.py     Prometheus text exporter（授權 + 可關閉）← app/metrics.py 同一 registry
  api/ws/nodes.py         heartbeat → registry.set_resources()（既有）+ 降頻寫 node_metric_samples
  api/ws/terminal.py      writer/viewer/takeover → 改為呼叫 services/authz.py（不再就地判斷）
  services/audit.py       單一 audit 寫入點（新增 request_id + daemon.update 事件）
  services/registry.py    NodeConnectionRegistry.request()（P1/P2/P3 已 production）
        └─ /ws/nodes/{node_id}
             └─ Go daemon
                  connection/dispatch   新增 daemon.update → internal/update
                  internal/update/      manifest fetch → checksum → 暫存 → 備份 → 原子替換
                                        → 重啟 unit → health check → 失敗 rollback
                  internal/metrics      既有 registry（新增 update 結果計數）
                  internal/systeminfo   既有 resources 取樣（heartbeat 已帶）

Ops
  deploy/compose/         nginx + backend + frontend + postgres（+ prometheus/grafana profile）
  deploy/nginx/           TLS 終端、WSS upgrade、安全標頭、body/frame 上限
  scripts/p4/             evidence.sh、backup-restore-drill.sh、load/ 負載 harness
  docs/runbooks/          heartbeat-loss、queue-saturation、timeout-surge、db-exhaustion、update-failure、backup-restore
```

資源 owner：每個 HTTP request 在 boundary 完成 authN → `require_action()`（action 層）→ **`services/authz.py`（resource scope 層）** → service；兩層都必須通過，缺一即為缺口。browser terminal WS 在 handshake 與**每個 inbound 控制訊息**都重新過同一組判斷（P2 已有 ws-ticket 綁 user+session，P4 補 owner 規則）。Dashboard 的每個區塊由 `services/dashboard.py` 內**獨立**的取數函式擁有，任一函式失敗只讓該區塊 degraded，不讓整個回應失敗。metrics registry 由 `app/metrics.py` 與 `daemon/internal/metrics` 各自以鎖保護，exporter 只讀 snapshot。daemon update 由 `internal/update` 的單一流程擁有，全程持有 lock 避免併發 update，並在每個階段寫 structured log + audit 事件。負載 harness 與 evidence 腳本各自獨立可重跑，不依賴前一次狀態。

## 4. 執行順序與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | **P4-01** | 決策 ADR **0016**（RBAC & audit 營運模型：permission matrix 定稿、resource scope/owner 規則、capability 傳遞方式、audit coverage 與 metadata 粒度、`request_id` 來源、retention 策略）、**0017**（release/update & deployment 基線：manifest 格式、簽章/來源策略、update 步驟與 rollback、tmux 保留語意、compose/TLS/secret/migration order/graceful shutdown）、**0018**（observability & capacity 基線：metrics 清單與 label 規則、export 端點與授權、資源歷史取樣率與 retention、alert 門檻與 for-duration、負載測試方法與判定） | 無 |
| 0 | **P4-02** | protocol **v1.4** 凍結：`daemon.update`（payload：`{target_version}`，**無 URL／無 binary path**）、`daemon.update_result`（`{from_version,to_version,status,stage,error_code?}`）；新增 error code `UPDATE_NOT_ALLOWED`／`UPDATE_CHECKSUM_MISMATCH`／`UPDATE_DOWNLOAD_FAILED`／`UPDATE_HEALTHCHECK_FAILED`／`UPDATE_ROLLED_BACK`／`UPDATE_IN_PROGRESS`；fixtures（valid + invalid：帶 URL、帶 path、未知欄位、非法版本字串）+ `manifest.json` + Python/Go/TS 三語言 codec accept/reject | P4-01 |
| 1 | **P4-03（Gate）** | **P4-W1 RBAC 完整化**：`app/services/authz.py`（resource scope/owner 單一判斷處）、permission matrix single source + 產生式文件、seed migration `0008`（idempotent，含 contraction 測試）、`audit.view` 真正被端點使用、`api/ws/terminal.py` 改走 authz、`/api/auth/me` 回傳 server 計算的 capability 清單、**每個 endpoint × 每個 WS message type × 三角色 allow/deny 矩陣測試**、Viewer forged mutation 全數失敗 | P4-01 |
| 2 | P4-04 | **P4-W2 audit 完整化**：coverage 表對齊 SEC-006（補 `daemon.update*`）、metadata 加 `request_id` + actor/resource、`redact_mapping` 強化與負面測試、migration `0009`（`audit_logs.user_id` 索引 + 查詢複合索引）、retention/backup 決策落地為設定 + runbook | P4-03 |
| 2 | P4-06 | **P4-W3 aggregates**：`services/dashboard.py` + `api/http/dashboard.py`（per-block 取數、per-block `freshness`/`degraded`、bounded recent activity、異常 Node 判定），`node_metric_samples` 表（migration `0010`）與 heartbeat 降頻寫入 | P4-03 |
| 2 | P4-10 | **P4-W5 daemon release/update**：`api/http/releases.py`（manifest）、`internal/update`（fetch→checksum→暫存→備份→原子替換→重啟→health check→rollback）、`agentd update` 實作取代 stub、`daemon.update` handler、doctor/version 顯示、audit + metrics、tmux 保留與 reconciliation 文件與測試 | P4-02、P4-03 |
| 3 | P4-05 | **P4-W2 audit 查詢與 UI**：`api/http/audit.py` + `services/audit_query.py`（filter/cursor pagination/bounded）、`views/AuditView.vue` + `stores/audit.ts`（全狀態矩陣、timezone、無敏感欄位、鍵盤可用） | P4-04 |
| 3 | P4-07 | **P4-W3 原型退場與 error management**：`styles.css` 拆解（保留仍被使用的 `.primary/.danger/.head/.panel` 遷入 scoped/token 化元件，刪除死 class）、**移除 Google Fonts CDN `@import`**（改自帶或系統字型堆疊）、移除 `min-width:1180px` 改依 style §24 桌機基線處理 overflow、刪除孤兒 `AppShell.vue`、`package.json` 更名、**退場 P0 dev relay**（`/ws/p0/*` + `app/relay/*` + `p0_*` 設定）、error code→safe message→UI 建議映射表 | P4-03 |
| 3 | P4-09 | **P4-W4 observability**：`app/metrics.py` 補 tech §18.1 系列（connections/sessions/WS bytes+messages/queue/timeout/HTTP latency/DB pool）、daemon 補 §18.2 與 update 結果、`api/http/metrics.py` exporter（授權 + 可關閉）、correlation log 欄位齊備、`docs/runbooks/*` + alert 規則檔 | P4-04、P4-06 |
| 4 | P4-08 | **P4-W3 Dashboard UI**：`views/DashboardView.vue` + `components/dashboard/*`（Metric Card／Health Card／Activity Timeline／Node Summary，style §10/§23）、freshness 與 partial 呈現、empty deployment／offline fleet／forbidden／error 全狀態、`/` 改 redirect 至 dashboard、nav 新增 Dashboard 與（Admin）Audit | P4-06、P4-07 |
| 4 | P4-11 | **P4-W4 容量**：`scripts/p4/load/`（100 nodes 模擬 daemon、10 sessions/node、500 terminal WS）、slow client／flood 有界證明（記憶體與 queue 上限）、latency 與 DB pool 觀測、`artifacts/p4/<run>/capacity.json` | P4-09 |
| 4 | P4-13 | **FR-WORKSPACE-004/005**：migration `0011`（`workspace_favorites`）、`services/favorites.py` + 端點、最近使用 workspace（由 `terminal_sessions` 推導，無新表）、`NewSessionDialog` 與 P3 tree 整合；**收藏/最近仍每次經 daemon 驗證 allowed root** | P4-03 |
| 5 | P4-12 | **P4-W6 部署與備份**：`deploy/compose/` + `deploy/nginx/`（TLS/WSS/安全標頭/上限）、secret 注入契約、migration 為獨立 job、graceful shutdown drain 實作與測試、`scripts/p4/backup-restore-drill.sh`（含「還原後不含 terminal raw log」掃描）、部署與 rollback runbook | P4-09、P4-10 |
| 5 | P4-14 | **P4-W6 安全審查**：tech §23 十五項逐項簽核證據、攻擊套件（stolen/expired token、replay、forged frames、path attacks、viewer forged input、WS flood、log/audit/DB leakage 掃描）、dependency/artifact scan、`docs/security-review-p4.md` | P4-03…P4-12 |
| 5 | **P4-15** | **P4-W6 驗證與 exit**：`p4.yml`、`scripts/p4/evidence.sh`、**PRD §19 二十項 MVP 驗收旅程**逐項證據、browser matrix（Chrome/Edge/Safari/Firefox）、Linux 支援矩陣、NFR 量測與 release decision、traceability §10、`docs/p4-report.md` Go/No-Go；**同時關閉 P3 遺留的 `p3.yml` 真實 runner 缺口** | 全部 |

關鍵路徑為 `P4-01 → P4-02 → P4-03(Gate) → P4-04/P4-06/P4-10 → P4-05/P4-07/P4-09 → P4-08/P4-11/P4-13 → P4-12/P4-14 → P4-15`。Wave 內可並行，但修改契約、seed migration 或 authz 規則的 PR 必須先於 consumer 合併；**P4-03 未通過授權 gate 前，不得合併任何新的對外端點（P4-05/P4-06/P4-09/P4-10/P4-13 的端點一律等待）**。

## 5. 每張 ticket 的完成格式

每張 ticket 至少附：變更檔案、契約/假設、成功與失敗測試（含 **forbidden（三角色 × 每個 action）**、**resource-scope 拒絕**、timeout/cancel/disconnect、partial backend failure、empty/offline、permission contraction、rollback/restore 失敗路徑）、實際執行命令（`make check`、`make test-db`、`make integration`、`make e2e`、`go test -race`、`alembic upgrade/downgrade`、負載與備份演練腳本）、log/metric/audit 影響（且證明無 secret/token/**terminal content**/**file content**/高基數 label）、以及對應 requirement（`FR-AUTH-001/002`、`FR-NODE-002/005`、`FR-INSTALL-004/005`、`FR-SESSION-003/004`、`FR-WORKSPACE-004/005`、`SEC-001…007`、`NFR-001…005`、PRD §19 條目編號）。

跨語言行為改變時，同一變更必須同步 schema、`manifest.json`、fixtures 與 Python/Go/TS 三個 consumer。**DB 變更必須附 upgrade→downgrade→upgrade 與「套用於既有資料」的測試**；seed/權限變更必須附 clean／repeat／prior-data／contraction 四種情境。UI 變更必須附狀態矩陣（`idle`/`loading`/`success`/`empty`/`stale`/`offline`/`forbidden`/`partial`/`error`）、鍵盤與 focus 驗證，且狀態不可只靠顏色表達。timeout/drain/alert for-duration 以 fake/monotonic clock 測。**Dashboard 與 audit 的測試必須包含「後端某一段失敗」與「完全沒有 node/session」兩種情境**，否則不算完成。

## 6. P4 預設限制與參數（待量測，記入 ADR 0016/0017/0018）

| 項目 | 初值 | 滿額/逾時/失敗行為 |
|---|---:|---|
| Audit 查詢單頁 | 50（上限 200） | server 端 cursor 分頁；超出上限回 422 |
| Audit 查詢時間範圍上限 | 90 天／單次查詢 | 超出回 422 並提示縮小範圍 |
| Audit retention | 保留 365 天（設定值） | 逾期資料由**文件化的維運清理程序**處理（runbook + 腳本），不自動排程刪除 |
| Recent activity 區塊 | 最近 20 筆（bounded） | 只取 audit 的安全欄位；不含 metadata 全文 |
| Dashboard 聚合快取 | 5 s（process 內） | 逾時重新取數；回應必帶每區塊 `generated_at` |
| Dashboard freshness 門檻 | `stale` > 30 s、`degraded` = 該區塊取數失敗 | 標示 stale/partial，**不以舊值偽裝即時** |
| Node 資源取樣持久化 | 每 node 每 60 s 一筆 | 寫入失敗只記 metric，不影響 heartbeat |
| Node 資源歷史 retention | 30 天（設定值） | 同 audit：runbook 清理 |
| Metrics export | `GET /api/metrics`（Prometheus text），預設**關閉** | 需專用 `metrics_scrape_token`（ADR 0018 定案，不複用 `audit.view`）；label 高基數即為缺陷 |
| Alert：heartbeat loss | 單 node `> node_degraded_within_seconds`（90 s）持續 2 min | warn；`> 5 min` 或 fleet 比例 > 20% 為 critical |
| Alert：queue saturation | terminal queue 使用率 > 80% 持續 1 min | warn；overflow 事件即 critical（已有 `terminal.gap` + 1013） |
| Alert：timeout surge | `*_relay_timeout_total` 5 min 增量 > 10 | warn；> 50 critical |
| Alert：DB exhaustion | pool 使用率 > 80% 持續 2 min | warn；checkout 等待 > 1 s critical |
| Alert：update failure | 任一 `UPDATE_*` 失敗事件 | critical（附 rollback 是否成功） |
| DB pool | `pool_size=10`、`max_overflow=10`、`pool_timeout=5 s`（設定值，目前為 SQLAlchemy 預設） | 逾時回 503 + safe message；計入 metric |
| Graceful shutdown drain | 15 s（設定值，monotonic） | 逾時強制關閉；**任何情況都不終止 tmux session** |
| Update health check | 重啟後 30 s 內須 doctor 通過 + 重新註冊成功 | 未通過即 rollback 至備份 binary 並回 `UPDATE_HEALTHCHECK_FAILED` |
| Update 併發 | 單一 node 同時只允許一個 update | 第二次回 `UPDATE_IN_PROGRESS` |
| 負載目標 | 100 nodes、10 sessions/node、500 terminal WS（NFR-003） | 記憶體有界、無 unbounded queue、latency 記錄；未達標列 release decision |
| Node 列表載入 | < 2 s（NFR-001） | 未達標列 release decision |
| Terminal 額外延遲 | < 200 ms（NFR-001，P2 已量測，P4 於負載下複驗） | 未達標列 release decision |

限制與參數皆以可設定 bounded 值實作，量測後在 ADR 接受或修訂，不硬編碼為永久產品限制。

## 7. 決策閘門（P4-01 前必須記錄）

> **狀態：P4-01 已完成（2026-07-25）**。下列全部決策已寫入 `docs/adr/0016-p4-rbac-and-audit-operations.md`、`0017-p4-release-update-and-deployment.md`、`0018-p4-observability-and-capacity.md`，**以 ADR 為準，本節僅為索引**。ADR 0006 已標記 superseded-by 0016。
>
> **產品決策（2026-07-25 由 owner 拍板）**：
> - **正式產品名稱為 Cliora**（關閉 `research/01/00` §7 決策閘門第 1 項，自 P0 懸置至今）。UI 仍以 `VITE_PRODUCT_NAME` 可設定；package 名稱正規化：`cliora-console-prototype`→`cliora-console`、`cliora-central-p0`→`cliora-central`。「Cask」放棄。
> - **update 提權採方案 (a)**：operator 執行 `sudo agentd update`；無提權途徑的 node 收到 `daemon.update` 一律回 `UPDATE_NOT_ALLOWED` 並要求 operator 處理。**不為了 UI 一鍵更新而安裝受限 sudoers／helper unit，也不讓 daemon 長駐 root**（ADR 0017）。
> - **MVP 不對 release artifact 加簽**：維持 `checksums.txt` + HTTPS + 封閉 allowlist（tech §23 #12）。殘餘風險「可寫入 `artifacts_dir` 即可投毒」已記入 ADR 0017 與 `docs/security-review-p4.md`，並附緩解（目錄權限、發布流程、reproducible build 可重算 digest）與 revisit trigger。
> - **Audit retention 採文件化手動程序**（`scripts/p4/prune-retention.sh`，dry-run 預設 + `--yes`），audit 365 天／metrics 30 天；MVP 不引入背景 scheduler（ADR 0016）。
> - **Metrics export 預設關閉 + 專用 `metrics_scrape_token`**（不複用 `audit.view`；Prometheus 不持有 user session）（ADR 0018）。
> - **P0 dev relay 退場**（ADR 0016）：`/ws/p0/*`、`app/relay/*`、`p0_*` 設定、`cmd/agentd/p0.go`、`dev-central`／`dev-daemon` 於 P4-07 移除。
>
> **計畫階段拍板、已於 ADR 追認**：
> - **Owner 規則**：session `terminate` = **owner 或具 `node.manage` 的 Admin**；`takeover` = **owner 或具 `terminal.takeover`**（皆寫 audit，並通知現任 writer）；read-only `attach` = 具 `session.view` 即可（沿用 P2「Viewer 唯讀 attach」）；`session.create` 只能為自己建立（`user_id` 由 server 指派，不由 client 傳）。
> - **UI capability 來源**：`/api/auth/me` 回傳 server 計算的 capability 清單，前端**不重寫規則**；UI 隱藏永遠不是授權。
> - **Audit metadata 粒度**：新增 `request_id`；沿用 P3 的「敏感檔僅記分類 + 副檔名」；**不新增成功 file read 的 audit**（量大且非 SEC-006 要求，維持 P3 決定）。
> - **Metrics export**：預設關閉、需授權、Prometheus text format、以標準庫產生（不引入 client library）、禁止高基數 label。
> - **Update 來源**：只接受 Central manifest + Central 下載端點，checksum 強制；**protocol payload 不含 URL/path/binary**（SEC-002 延伸）。
> - **P0 dev relay 退場**：`/ws/p0/*`、`app/relay/*`、`p0_enabled`/`p0_token`/`node_id` 設定與 `/poc/*` 路由於 P4-07 移除（P2 relay 已完全取代；ADR 0006 隨之標記 superseded）。此為**刻意的清理決定**，記入 ADR 0016 以免被視為暗中縮減範圍。
> - **Node remove 維持 soft delete**（沿用 ADR 0011），不做破壞性硬刪除。

以下十二項於 P4-01 全部答畢並寫入 ADR；保留清單供 review 對照，**實作以 ADR 為準**。

1. **Permission matrix 定稿與 owner 規則**：PRD §8.1 表格（8 列功能 × 3 角色）與現有 10 個 action key 的完整對照；attach/takeover/terminate/read file 的資源範圍；Developer 是否能看見他人 session（**定案：可見（`session.view`）但不可 terminate/takeover**）。
2. **Audit coverage 與單一性**（ADR 0016）：**定案** SEC-006 八項 ∪ tech §13.3 十一項，新增 `user.session_revoked`／`node.enable`／`credential.rotate`／`daemon.update_started`／`daemon.update_result`／`authz.denied`；audit **只由 service 層寫入**（無 service 的路徑以註解標示唯一寫入點），每個事件有「筆數恰為 1」的測試；**只記安全相關拒絕**（mutation 與跨 owner），一般讀取 403 與 validation 422 不記。
3. **Retention 與備份**（ADR 0016）：**定案** audit 365 天／`node_metric_samples` 30 天；以 `prune-retention` CLI（dry-run 預設 + `--yes`）手動執行，runbook 要求「清理前先備份」；**不引入背景 scheduler**。備份範圍與「不含 terminal raw log」的 dump 掃描屬 P4-12。
4. **Metrics export 形態與授權**（ADR 0018）：**定案** `GET /api/metrics`、Prometheus text、標準庫產生、預設關閉、**專用 `metrics_scrape_token`**；是否再綁內網介面由部署文件決定。label 白名單見 ADR（14 個允許 key；`node_id`/`user_id`/`session_id`/`path`/`keyword`/`username` 禁用，測試掃描 series key）。
5. **資源歷史取樣**（ADR 0018）：**定案** 每 node 每 60 s 一筆原始樣本、查詢時聚合、30 天 retention、寫入失敗只記 `metric_persist_error_total` 不影響 heartbeat。
6. **Alert 門檻與 for-duration**（ADR 0018）：**定案** 沿用 §6 表並新增 authz-denial spike 與 `audit_error_total > 0`；規則置於 `deploy/prometheus/alerts.yml` 並以 `promtool check rules` 驗證；**每個告警必須能由 `scripts/p4/drills/` 主動觸發**，無法觸發者不算交付。
7. **Release 與簽章策略**（ADR 0017）：**定案** MVP 不加簽（維持 `checksums.txt` + HTTPS + 封閉 allowlist），殘餘風險與緩解、revisit trigger 已記入 ADR 與安全審查；補 `-trimpath`；reproducible 以「同 commit 兩次建置 checksum 相同」驗證；`release.disable` 解除，改由 version tag 觸發。
8. **Update 語意**（ADR 0017）：**定案** 六個 stage + process lock；rollback 邊界為 **binary 回復 + unit 重啟，不回復 config/credentials**；health check 為「30 s 內 doctor 通過且重新註冊成功」；提權採方案 (a)（operator sudo），無提權途徑即回 `UPDATE_NOT_ALLOWED`；tmux 保留由 ADR 0012 recovery 路徑保證並以三個 integration 情境測試。
9. **部署形態**（ADR 0017）：**定案** compose = nginx + backend + frontend + postgres，prometheus/grafana 為**選配 `observability` profile**（非預設啟動）；TLS **預設自備憑證掛載**（內網常無 ACME 所需公開 DNS），ACME 僅記錄為替代；nginx 必須顯式設 `proxy_read_timeout`（預設 60 s 會切斷 terminal 長連線）並對齊 8 MiB filesystem 回應上限；secret 由環境注入；**migration 為獨立一次性 job，不在 lifespan 自動執行**。
10. **Graceful shutdown 語意**（ADR 0017）：**定案** drain 15 s（monotonic）；browser 收到明確關閉理由後自行重連；daemon 沿用既有 backoff；**任何 shutdown 路徑都不終止 tmux session**。
11. **原型退場邊界**（ADR 0016 + `03-dashboard-and-error-management.md` §P4-07）：**定案** 字型改**系統字型堆疊**（移除 Google Fonts CDN `@import`）；`.primary`/`.danger`/`.head`/`.panel` 遷入共用元件或 scoped style（9 個檔逐檔遷移 + 視覺回歸截圖），其餘原型 class 刪除；移除 `body{min-width:1180px}`，改由各 view 依 style §24 處理 overflow（`AppLayout` 已有 900 px breakpoint）；`TokenShowcaseView` 保留為 dev-only 但以 `dist` grep 斷言不進 production bundle。
12. **FR-WORKSPACE-004/005 範圍**（ADR 0016）：**定案** 收藏為 **per-user + per-node**、`recent` 5 筆（上限 20）、收藏可刪除且只能刪自己的；授權用 `session.create`（收藏用途是加速建立 session，Viewer 無此需求）。

## 8. 明確非目標與變更控制

P4 不加入 Web 檔案編輯／寫入／上傳／下載、任意 shell、Central SSH、Git automation、Terminal 全量保存／session replay、CLI 語意解析、多 agent orchestration、task routing、Kubernetes agent、message broker、backend 水平擴充、Redis／sticky routing（tech §17.2/17.3 明確延後）、多租戶 billing／token 成本分析、全文搜尋、即時 filesystem watch、macOS daemon、自訂角色／權限編輯 UI、自訂儀表板、audit 匯出報表引擎、自動排程／批次 daemon 升級、APM/tracing 平台整合。需要其中任一項時，先依 `research/01/06-requirement-traceability.md` §6 變更 canonical requirements（PRD 目標/非目標與 requirement ID → tech trust boundary/protocol/data/failure/security/observability/test → style UI/state contract → 追蹤矩陣與階段出口），不能只在 implementation ticket 中暗自擴張。

**P4 是最後一個 phase，因此「延後到下一階段」不再是有效的處置**。任何在 P4 發現但不修的問題，必須在 `docs/p4-report.md` 以**明確的 release decision** 記錄：問題、影響範圍、為何可接受、偵測與緩解方式、以及後續處理的觸發條件。未達標的 NFR 同理。無法被記錄成可接受風險的 Critical/High security finding 一律阻擋發布。
