# 07 — 部署、備份、安全審查與 MVP Exit Gate（P4-W6）

涵蓋 ticket **P4-12**（部署與備份）、**P4-14**（安全審查）與 **P4-15**（驗證、證據與 MVP exit）。對應 `research/01/05` §P4-W6 與 §階段出口、tech §17.1、§19、§20、§23、PRD §19（20 項 MVP 驗收條件）、NFR-001…005。

延續 P0/P1/P2/P3 的驗證紀律（`plan/01/07`、`plan/02/08`、`plan/03/08`、`plan/04/07`）。**P4 是最後一個 release gate**：這裡不通過，MVP 就不發布。

---

## P4-12：部署與備份

### 現況

repo 內**沒有任何 `docker-compose*`、`Dockerfile` 或 nginx 設定**。已有的：`/healthz`、`/readyz`（後者已比對 alembic migration head，見 `app/main.py`）、`Settings` 的 production 驗證器（拒絕 dev secret、拒絕 p0_enabled）、`deploy/install.sh` + `deploy/README.md`（daemon 側）。lifespan 目前只 `configure_logging()` 與 `reset_database()`。

### 1. 部署資產

```text
deploy/compose/
  compose.yaml              nginx + backend + frontend(static) + postgres
                            profile: observability → prometheus + grafana
  compose.override.example.yaml
  .env.example              所有必要環境變數與說明（無真值）
deploy/nginx/
  nginx.conf                TLS 終端、HTTP→HTTPS redirect、WSS upgrade、
                            安全標頭、body/frame 上限、靜態檔快取
deploy/backend.Dockerfile   uv sync --locked → 非 root user 執行 uvicorn
deploy/frontend.Dockerfile  npm ci && npm run build → 產物交給 nginx（多階段）
deploy/migrate.sh           一次性 migration job（見下）
docs/deployment.md          部署、升級、rollback、還原程序
```

- **HTTPS/WSS（tech §23 #1）**：nginx 終端 TLS，`/api` 與 `/ws` 反向代理，`proxy_set_header Upgrade/Connection` 與足夠的 `proxy_read_timeout`（terminal WS 是長連線，預設 60 s 會斷線——必須明確設定並測試）。`ws_max_size` 與 nginx `client_max_body_size` 需與 contract 的 8 MiB filesystem 上限相容（1.3.1 已確認 uvicorn 16 MiB；nginx 側需對齊）。
- **安全標頭**：HSTS、`X-Content-Type-Options`、`Referrer-Policy`、`X-Frame-Options`/CSP。**CSP 必須允許 Monaco 的 worker**（`worker-src 'self' blob:`）且**不允許外部來源**——這與 P4-07 移除 Google Fonts CDN 是同一件事的兩面：CSP 若加上就會讓殘留的 CDN import 直接失效，所以 P4-07 必須先完成。
- **Secret 注入（tech §23 #4）**：`CLIORA_JWT_SECRET`、`CLIORA_TOKEN_PEPPER`、`CLIORA_DATABASE_URL`、（若啟用）`CLIORA_METRICS_SCRAPE_TOKEN` 全部由環境注入；image 內不含任何真值；`.env.example` 只有說明。`Settings` 的 production 驗證器已拒絕 dev 預設值——補一個測試：以 production + 預設 secret 啟動應失敗。
- **Migration 順序**：**不在 lifespan 自動 migrate**（避免多副本競爭與意外升級）。`deploy/migrate.sh` 為獨立一次性 job，部署流程為 `migrate → backend 啟動 → readyz 綠 → nginx 導流`。`/readyz` 已在 migration head 不符時回 `degraded`，因此順序錯誤會被 readiness 抓到——補一個測試：DB 落後一個 revision 時 `/readyz` 為 degraded 且 `migration: false`。
- **Graceful shutdown**：`Settings.shutdown_drain_seconds`（預設 15，monotonic）。SIGTERM 後：停止接受新 WS/HTTP → 對每個 browser terminal WS 送明確的關閉控制訊息（讓前端顯示「伺服器維護中，正在重新連線」而非不明斷線）並在 drain 上限內收尾 → 關閉 daemon WS（daemon 走既有 backoff 重連，FR-CONN-003）→ dispose DB engine。**任何情況都不終止 tmux session**（NFR-002：「瀏覽器中斷不得直接終止 CLI Session」的延伸——Central 重啟也不行）。測試：以 fake clock 驗 drain 上限、驗 tmux session 存活（integration）、驗前端收到明確理由。

### 2. Backup / Restore 演練

`scripts/p4/backup-restore-drill.sh`：

1. 在來源 DB 建立可辨識的資料（users/roles、nodes、sessions、audit、`node_metric_samples`、favorites）。
2. `pg_dump`（記錄實際命令與版本）。
3. 還原至一個**全新**資料庫。
4. **驗證**：三角色權限完整、node/session/audit 筆數與內容一致、`alembic current` 與 head 相符、應用可以連上還原後的 DB 並通過 `/readyz`。
5. **「不含 terminal raw log」掃描**（research 明確要求）：對 dump 檔做內容掃描，斷言不含 terminal 控制序列樣式（如 ANSI escape 密集片段）、不含檔案內容標記、不含 password/token 明文、不含 Ed25519 私鑰。這個掃描的價值在於**證明資料模型的承諾**（PostgreSQL 不保存 terminal bytes）在真實 dump 上成立，而不只是在程式碼註解裡。
6. 產出 `artifacts/p4/<run>/backup-restore.md`：命令、時間、資料量、驗證結果、掃描結果。

`docs/runbooks/backup-restore.md` 記錄：備份頻率建議、保留策略、還原程序、還原後的必要檢查、以及與 retention 清理程序（P4-04）的先後關係（**清理前必須有備份**）。

### 3. Rollback 演練

`docs/deployment.md` 記錄應用層 rollback：回到前一版 image + **是否需要 DB downgrade**（原則：P4 的 migration `0008`–`0012` 皆需可 downgrade，且已有 up/down/up 測試；但若已有新資料寫入，downgrade 可能有損——每個 migration 的 downgrade 註解必須寫明「是否有損」）。演練一次「部署 → 發現問題 → rollback → 服務恢復」並記錄。

---

## P4-14：安全審查

### 1. tech §23 十五項基準逐項簽核

每一項都要有**可定位的證據**（測試名稱、檔案位置或演練記錄），不接受「已實作」這種敘述：

| # | 基準 | 預期證據來源 |
|---:|---|---|
| 1 | 只允許 HTTPS／WSS | `deploy/nginx/nginx.conf` + 部署演練（HTTP → 301）；production 設定驗證 |
| 2 | Daemon 不以 root 長期執行 | `internal/install/systemd.go`（`User=`）、`config.EnsureNonRoot()`、doctor 檢查、P4-10 的 update 非 root 保證 |
| 3 | Enrollment token 一次性或限時 | P1 `test_enrollment_api.py`（expiry/max_uses/revoke） |
| 4 | Node secret 不明文保存於中央 | `0003_ed25519_node_credentials`（僅存 public key）、`test_node_credentials.py` |
| 5 | Workspace 每次操作都驗證 root | P3-03 gate（`internal/workspace/root.go` + `FuzzOpenFile`）、P4-13 收藏不繞過 |
| 6 | Symlink 必須解析 | P3 `root_test.go`（symlink chain/swap/broken link） |
| 7 | 前端不可傳任意 Command | contract fixtures（`session.start` 無 argv、`filesystem.*` 無 rg 參數、`daemon.update` 無 URL/path，`additionalProperties:false`） |
| 8 | Terminal 原始內容不寫入 Log | P2/P3 log 斷言 + P4 log 掃描 + backup dump 掃描 |
| 9 | 敏感檔案預設禁止預覽 | P3 `TestReadPolicyMatrix` + installer 預設政策（P3 defect 2 的回歸測試） |
| 10 | Session 建立、接管、終止需 Audit | P2 audit 測試 + P4-04 coverage 測試（單一性） |
| 11 | WebSocket 必須做身分與權限檢查 | P1 Ed25519 challenge、P2 ws-ticket、**P4-03 的 WS message type × 角色矩陣** |
| 12 | Binary download 必須驗證 Checksum | `install.sh`、`internal/install/verify.go`、**P4-10 的 update checksum 測試** |
| 13 | Daemon Config／Credential 權限 0600 | `internal/config/credentials.go` + install 測試 + doctor |
| 14 | 限制單一使用者與 Node 的 Session 數量 | `sessions_per_node_max`（P2）+ **per-user 上限（需確認是否已實作；若無則本期補**，PRD §20 與 tech §23 #14 要求「單一使用者**與** Node」兩者） |
| 15 | 限制 Terminal Queue 與 Frame 大小 | P0/P2 queue bounds、contract frame 上限（含 1.3.1 的分流）、P4-11 的 slow client 有界證明 |

**第 14 項需要特別檢查**：目前 `Settings` 只有 `sessions_per_node_max`，沒有 per-user 上限。若確認缺少，P4-14 必須補上 `sessions_per_user_max`（設定值，預設如 20）+ 服務層檢查 + `SESSION_LIMIT_REACHED` + 測試，並在 ADR 記錄。這是一個 P4 才會被發現的真實缺口，正是逐項簽核的價值。

### 2. 攻擊套件（research §P4-W6 指定）

| 攻擊 | 測試內容 | 期望 |
|---|---|---|
| **Stolen / expired token** | 用過期 access token、已撤銷 refresh、token_version 已遞增的 token、別人的 ws-ticket | 401；ws-ticket 綁 user+session 且單次使用（P2 已有，本期複驗 + 加入 audit 檢查） |
| **Replay** | 重放 enrollment token、重放 Ed25519 challenge id、重放已用過的 ws-ticket | 全部拒絕（P1/P2 已有，納入 P4 security job） |
| **Forged frames** | daemon 連線送 user 級 mutation（`session.stop` 等）、browser 送 daemon-only 型別、未知型別、超大 frame、非法 binary kind、`request_id` 偽造/late response | 一律拒絕或丟棄；不改變狀態；不 hang（1.3.1 的 `FRAME_TOO_LARGE` 明確錯誤而非 hang 是此類的既有修正） |
| **Path attacks** | `..`、absolute、prefix collision、symlink chain/swap、null byte、broken link、非 regular file；以及**收藏路徑**與 **update 版本字串**兩個新入口 | 全部拒絕（P3 gate + P4-10/P4-13 的新測試） |
| **Viewer forged input** | Viewer 在 WS 上送 binary input、`terminal.control_acquire`、直接呼叫每個 mutation endpoint | 全部失敗、無副作用、記 `authz.denied` audit（P4-03 矩陣測試） |
| **WS flood** | 高速控制訊息、高速 binary input、大量並發連線、slow client | 有界（queue 上限、overflow → gap + 1013、`NODE_BUSY`、連線數上限）；其他使用者不受影響（P4-11） |
| **Log / audit / DB leakage** | 對一輪完整 E2E 的 Central log、daemon log、audit 表、DB dump、CI log、metrics 輸出做正則掃描 | 無 terminal bytes、無 file content、無 search keyword 明文、無 password/token/私鑰、無不必要 absolute path、metrics 無高基數 label |

### 3. Dependency / artifact scan

- Python：`uv` lock 的已知漏洞掃描（`pip-audit` 或 GitHub advisory）。
- Node：`npm audit --omit=dev`（production 依賴），對無法修的項目記錄理由。
- Go：`govulncheck ./...`。
- Artifacts：release tarball 的 checksum 與 reproducible build 比對（P4-10）。
- 產出 `docs/security-review-p4.md`：十五項簽核表 + 攻擊套件結果 + 掃描結果 + **每個 finding 的嚴重度與處置**。**未處理的 Critical/High 一律阻擋發布**（research §階段出口）。

---

## P4-15：驗證、證據與 MVP Exit

### 1. 測試分層

| 層級 | 必跑內容 | 主要 owner |
|---|---|---|
| Contract | v1.4 `daemon.update*` schema、三語言 fixtures、round trip；forbidden（帶 URL/path、非法版本、未知欄位、bad enum、naive time）拒絕 | protocol |
| Unit（backend） | **permission matrix 窮舉（P4-03 Gate）**；authz owner 規則兩側；audit coverage 單一性 + metadata 禁止清單 + redaction（含嵌套/截斷）；audit 查詢（filter/cursor/422 邊界）；dashboard per-block degraded/stale/快取/角色差異；metrics label 白名單 + exporter 格式 + histogram cumulative；DB pool 逾時；releases manifest（fail-closed）；favorites（prefix 授權/owner/idempotency） | Central |
| Unit（daemon） | update 全 stage 成功與每個失敗路徑 + rollback + 併發 + 介面無 URL/path 參數；metrics 新系列；doctor 新檢查；`-race` | daemon |
| Unit（frontend） | `stores/{dashboard,audit,favorites}`；`DashboardView` 九狀態；`AuditView` 全狀態 + 時區；error catalog → UI 建議；原型退場後的元件遷移回歸 | frontend |
| Migration | `0008`–`0012` 各自 up/down/up、套用於既有資料、seed 四情境（clean/repeat/prior-data/contraction）、索引存在性、CASCADE | Central |
| Integration | Central↔真實 daemon：update 成功/checksum 不符/rollback/**升級後 tmux session 存活與 reattach**；graceful shutdown 期間 session 存活；heartbeat → `node_metric_samples` 降頻寫入；daemon disconnect 中途 relay cleanup | Central+daemon |
| Browser（E2E） | login → **dashboard**（真實數字/stale/partial/空部署/offline fleet/角色差異）→ nodes → session → terminal → files → **audit（Admin）/forbidden（Developer）** → favorites/recent → node update 顯示 → keyboard-only + screen reader；**Chromium / Firefox / WebKit** | frontend |
| Performance | terminal 延遲 < 200 ms（負載下複驗）、node 列表 < 2 s、目錄列表 < 2 s、≤2 MB 預覽 < 3 s（P3 已量測，複驗）、dashboard/audit 回應時間 | cross-stack |
| Capacity | 100 nodes／10 sessions per node／500 terminal WS；slow client/flood 有界；記憶體/pool/task 無洩漏 | cross-stack |
| Security | 十五項基準 + 攻擊套件 + 洩漏掃描 + dependency/artifact scan | cross-stack |
| Ops drills | 五個告警觸發 + runbook 可執行；backup/restore；rollback；daemon update/rollback | ops |

測試不得依賴外部網路或個人真實路徑；PostgreSQL 以 CI service container 或 ephemeral schema 提供並清理（沿用 P1–P3）；time/timeout/drain/alert for-duration 用 fake/monotonic clock。**E2E 使用獨立資料庫**（P3 的教訓：`run-stack.sh` 會寫入真實資料，本機驗證時用獨立 DB 並在結束後 drop，避免污染有計數斷言的 `cliora_test`）。

### 2. 必要 CI gates（`.github/workflows/p4.yml`）

- `backend-db`：format/lint/typecheck、migration `upgrade head` → `downgrade 0007` → `upgrade head`、unit + DB 測試（含 permission matrix）。
- `daemon`：`go vet`、`go test -race ./...`、`-tags integration -race ./internal/{session,connection,files,workspace,update}`、build amd64/arm64、**reproducible build 檢查（同 commit 兩次 checksum 相同）**。
- `contract`：Python/Go/TS 對 v1.4 `manifest.json` 一致 accept/reject。
- `frontend`：lint/typecheck/build、**`dist` 無 CDN／無 P0／無原型殘留 grep**、vitest（含 Monaco leak gate、Dashboard/Audit 狀態）。
- `install-update-matrix`：Ubuntu 22.04／24.04／Debian 12 × amd64／arm64 的 install → start → 註冊 → **update 成功 → checksum 不符 → rollback** → doctor → uninstall-clean（沿用 `p1.yml` 的 matrix 形態；這是本機沙箱做不到的部分）。
- `browser-e2e`：Playwright **Chromium + Firefox + WebKit**（`--with-deps`），full-stack。**同時關閉 P3 遺留的 WebKit 缺口**。
- `security`：攻擊套件、洩漏掃描、`pip-audit`／`npm audit`／`govulncheck`、alert 規則 `promtool check rules`。
- `performance`：latency artifact（merge/RC）。
- `capacity`：100 nodes／500 WS harness（merge/RC）。
- `ops-drills`：backup/restore 演練 + 五個告警觸發（merge/RC）。
- `evidence`：`scripts/p4/evidence.sh` 產出完整證據包。

每個 PR 跑 format/lint、typecheck、unit、contract、build、migration；合併主分支與 RC 另跑 install-update matrix、E2E matrix、security、performance、capacity 與 ops-drills。CI log 不列印 secret/token/**terminal content**/**file content**/keyword 明文。

**另外**：`p3.yml` 必須在 P4 期間跑綠一次（P3 exit 的唯一未關項），並在 `docs/p3-report.md` 把 Conditional Go 改為 Go。P4 不能在 P3 仍未關閉的狀態下宣告 MVP 完成。

### 3. 操作證據包

於 `artifacts/p4/<run-id>/`（CI artifact）保存：

- `versions.txt`、`commands.txt`（每道 gate 與 exit status；任一非零則腳本非零退出——沿用 `scripts/p3/evidence.sh` 的設計，讓證據包不可能描述沒發生過的綠燈）。
- `contract.xml`、`unit-{backend,daemon,frontend}.xml`、`integration.txt`、`race.txt`、`e2e-{chromium,firefox,webkit}.xml`、`migration.txt`。
- `permission-matrix.md`：每個 endpoint／WS message type × 三角色 × owner/非 owner 的實際結果表（由測試輸出產生）。
- `audit-coverage.md`：每個重要操作 → 實際產生的 audit（action、欄位、筆數=1）與 metadata 掃描結果。
- `dashboard-states.md` + `screenshots/`：九個狀態的實際畫面（含空部署、offline fleet、partial、forbidden、stale）。
- `update-matrix.md`：成功／checksum 不符／網路失敗／rollback／restart recovery／tmux 存活的實際結果，含每個平台。
- `capacity.json`、`latency.json`：NFR 判定（含環境）。
- `drills.md`：五個告警的觸發時間、runbook 可執行性、恢復時間。
- `backup-restore.md`：命令、驗證、**dump 掃描結果**。
- `security-report.md` + `docs/security-review-p4.md`：十五項簽核、攻擊套件、掃描 finding 與處置。
- `prototype-retirement.md`：`dist` grep 結果、遷移前後截圖清單。
- `mvp-acceptance.md`：**PRD §19 二十項逐項證據**（見下）。

### 4. MVP 最終驗收旅程（research §MVP 最終驗收旅程 + PRD §19）

以一次連貫的操作（盡可能自動化為 E2E + 演練腳本）產生證據，並逐項對應 PRD §19 的 20 個條目：

| PRD §19 | 條目 | 證據來源 |
|---:|---|---|
| 1 | Admin 產生安裝 Token | `auth.spec.ts`/`nodes.spec.ts` + enrollment DB 測試 |
| 2 | 一行指令安裝 Go Daemon | `install-update-matrix` job（六平台） |
| 3 | 安裝後自動啟動並註冊 | 同上（systemd + WSS register） |
| 4 | 顯示 Node Online／Offline | dashboard/nodes E2E + heartbeat 逾時演練 |
| 5 | 顯示 Claude/Codex 可用性 | runtime status E2E |
| 6–9 | 選 Node／切換 runtime／瀏覽 root／指定合法目錄 | session E2E + workspace 授權測試 |
| 10 | Daemon 在指定目錄啟動 CLI | daemon integration（真實 tmux） |
| 11 | Web Terminal 完整操作 CLI | P0/P2 Fake CLI + **isolated live smoke**（真實 Claude/Codex，手動記錄） |
| 12 | CLI 原生審批畫面 | 同上（live smoke 的截圖與操作記錄） |
| 13 | 關閉瀏覽器 session 不結束 | P2 recovery 測試 + E2E refresh |
| 14 | 重新連線執行中 session | 同上 |
| 15–17 | 目錄樹／唯讀預覽／敏感檔不可預覽 | P3 `files.spec.ts` + denial matrix |
| 18 | Node 離線不可建 session | domain + E2E |
| 19 | 正常終止 session | lifecycle integration + E2E |
| 20 | **所有重要操作均有 Audit Log** | P4-04 coverage 測試 + `audit-coverage.md` + Audit UI E2E |

第 11/12 項的 **live smoke**（真實 Claude/Codex CLI 的審批互動）無法自動化，必須以手動操作記錄 + 截圖作為證據，並在報告中明確標示為手動驗證。

### 5. Exit Gate checklist

#### 功能與營運

- [ ] 三角色權限在 HTTP／browser WS／daemon WS／UI 四處一致，attach/takeover/terminate/file browse 有 owner 規則，矩陣測試無遺漏 route。
- [ ] 每個重要操作產生單一可追蹤 audit（actor/resource/`request_id`/aware time）；Admin 可過濾與分頁查閱並看到本地時區。
- [ ] Dashboard 顯示真實聚合，stale/partial/empty/offline/forbidden 各有明確畫面，**不偽裝即時資料**。
- [ ] 所有原型硬編碼值、CDN 依賴、`min-width`、孤兒元件與 P0 dev relay 已移除（`dist` 與程式碼 grep 為證）。
- [ ] `agentd update` 成功／checksum 不符／網路失敗／rollback／restart recovery 全通過；升級期間 tmux session 存活且重啟後可 reattach。
- [ ] backup/restore 演練通過且 dump 掃描無 terminal raw log；rollback 演練通過；五個告警可觸發且 runbook 可執行。
- [ ] FR-WORKSPACE-004/005 已交付，或已在報告中記為明確的 release decision。

#### 安全（發布前提，任一未過即 No-Go）

- [ ] tech §23 十五項全數簽核且有可定位證據（含第 14 項的 per-user session 上限）。
- [ ] 攻擊套件全過：stolen/expired token、replay、forged frames、path attacks（含收藏與 update 兩個新入口）、viewer forged input、WS flood、log/audit/DB/metrics 洩漏掃描。
- [ ] 無未處理的 Critical/High finding（dependency/artifact scan 含在內）。
- [ ] Metrics export 預設關閉、需授權、無高基數 label；audit/log/DB 無 secret、terminal bytes 或 file content。
- [ ] production 設定拒絕 dev secret 與 p0；HTTPS/WSS 強制；安全標頭與 CSP 生效且 Monaco worker 仍可用。

#### 效能、工程與可維運

- [ ] NFR-001（terminal < 200 ms、node 列表 < 2 s、目錄列表 < 2 s、≤2 MB 預覽 < 3 s）有量測結果；未達標項有明確 release decision。
- [ ] NFR-003（100 nodes／10 sessions per node／500 terminal WS）有量測；slow client/flood 記憶體有界；無 pending/task/goroutine/連線洩漏（`-race`）。
- [ ] NFR-002（自動重連、Central 重啟後重新註冊、瀏覽器中斷不終止 CLI、狀態可恢復）有測試或演練證據。
- [ ] NFR-005：Chrome/Edge/Safari/Firefox 最新版 smoke 通過；Ubuntu 22.04／24.04／Debian 12 × amd64／arm64 install-update matrix 通過。
- [ ] 乾淨 checkout 依 README 可 bootstrap、migrate、build、test、run；依 `docs/deployment.md` 可從零部署一套可用環境。
- [ ] CI gates 全綠且 artifact 可追溯到 commit；**`p3.yml` 已在真實 runner 綠燈**（P3 遺留項關閉，`docs/p3-report.md` 改為 Go）。
- [ ] `research/01/06-requirement-traceability.md` §10 以實際證據更新 FR-AUTH/NODE/INSTALL/SESSION/WORKSPACE、SEC-001…007 與 NFR-001…005；`docs/permission-matrix.md`／`docs/error-catalog.md`／`docs/runbooks/*` 與程式碼一致（自動化斷言）。

任一項未過即維持 P4 open。不可因「Dashboard 看起來正常」或「update 在本機成功」即豁免授權矩陣、洩漏掃描、install-update matrix、容量有界性證明或安全簽核。

### 6. ADR / 決策清單

| ADR | P4 必答問題 | 截止 |
|---|---|---|
| 0016 RBAC & audit 營運模型 | permission matrix、owner 規則、capability 傳遞、audit coverage 與單一性、metadata 粒度與 `request_id`、retention、P0 relay 退場 | P4-01（P4-03/04/05/07 前） |
| 0017 Release/update & deployment | manifest 格式與來源、簽章策略與 reproducible 驗證、update 步驟與 rollback 邊界、提權方案 (a)/(b)、tmux 保留語意、compose/TLS/secret/migration order/graceful shutdown | P4-01（P4-10/12 前） |
| 0018 Observability & capacity | metrics 清單與 label 白名單、export 端點與授權、資源取樣與 retention、alert 門檻與 for-duration、負載測試方法與判定 | P4-01（P4-06/09/11 前） |

若某項無法達成（例如簽章基礎設施不可得、100-node 環境無法取得），必須回報**替代方案與殘餘風險**並記入 release decision，而不是降低驗收標準或悄悄跳過。

### 7. 已知風險與相依

- **RBAC 是本期最高風險**：目前「有 role 就能動任何資源」是一個真實的越權缺口（任何 Developer 可終止他人 session、可搶走 writer）。它不是新功能而是**修正既有行為**，因此可能影響 P2 的既有測試預期——P4-03 必須同時更新那些測試並在 ADR 說明行為變更。
- **原型退場會造成 UI 迴歸**：`styles.css` 的 `.primary`/`.head`/`.panel`/`.danger` 仍被 9 個檔案使用（6 個 view + `NewSessionDialog` + `PreviewPane` + `TokenShowcaseView`），一次性刪除會破畫面。必須逐檔遷移 + 視覺回歸截圖，且與 P4-08（Dashboard 新頁）分開 PR，避免混在一起無法定位迴歸來源。
- **CSP 與既有 CDN import 互斥**：P4-12 若先於 P4-07 上線，Google Fonts 會被 CSP 擋掉造成字型異常。順序必須是 P4-07 → P4-12。
- **update 的提權取捨是安全與便利的正面衝突**：自動更新需要提權，而 SEC-007 要求 non-root 常駐。方案 (a)（operator sudo）安全但無法從 UI 一鍵完成；方案 (b)（受限 sudoers/helper unit）便利但擴大攻擊面。ADR 0017 必須明確選擇並寫下殘餘風險；**不得為了讓 UI 按鈕能用而讓 daemon 長駐 root**。
- **Central 重啟後狀態收斂**：registry 是記憶體狀態，重啟後 Dashboard 會短暫顯示 stale。這是正確行為（不偽裝即時），但需要在 UI 與 runbook 都說清楚，否則會被誤判為故障。
- **P3 遺留缺口**：`p3.yml` 從未在真實 runner 執行（含 WebKit）。P4 的 release gate 必須把它一起關掉，否則 MVP 是建立在未驗證的 P3 CI 之上。
- **沙箱與 CI 的分工必須誠實標示**：install-update matrix、真實 systemd restart、WebKit、真實 TLS、100-node 規模在本工作目錄都跑不了（memory `installer-sandbox-limits`）。本機通過不等於 CI 通過，證據包必須分開記錄兩者。
- **「最後一個 phase」的壓力**：P4 沒有下一期可以延後。任何不修的問題都必須成為書面的 release decision（問題、影響、為何可接受、偵測與緩解、後續觸發條件），這比修不完更危險的是把它忘掉。

### 8. Go / No-Go review

Exit review 輸出 `docs/p4-report.md`：結果、未通過項、實測參數（授權矩陣覆蓋率、audit coverage、dashboard 降級行為、metrics 與告警演練、update 各情境、容量與延遲、backup/restore 時間）、已知 gap 與 release decision、採納的 ADR（0016/0017/0018）、以及**MVP 發布建議**。

只有以下全部成立才可標記 Go：§5 三段 checklist 全過、tech §23 十五項簽核無未處理 Critical/High、PRD §19 二十項皆有測試或操作證據、NFR 有量測結果（未達標者有明確 release decision）、`p3.yml` 已綠、發布版本可重建／可部署／可 rollback／可觀測並有 runbook。

若不可行，報告須列出替代方案、需修改的架構、重新估算與下一個 time-boxed 工作，而非以降低驗收標準的方式宣告 MVP 完成。
