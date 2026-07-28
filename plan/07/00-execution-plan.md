# 00 — Railway 部署執行總控

## 1. 成功定義

這一期要退休五個風險，每一個都是「照抄 compose 設定就會踩到、且上線後才會發現」的類型：

- **(a) 部署即斷線**：`drainingSeconds` 預設 0 使 `app.main._drain()` 永遠跑不完，瀏覽器拿到無理由斷線、in-flight daemon request 被 SIGKILL 帶走。
- **(b) readiness 形同虛設**：Railway 只看狀態碼，`/readyz` 在 degraded 時回 200，於是「未 migrate 或連不上 DB 的 Central 不得接流量」這條規則在 Railway 上不存在。
- **(c) 私網不通或部署後 502**：uvicorn 綁 `0.0.0.0` 在 IPv6 私網上不可達；nginx 靜態 upstream 會快取 Central 舊 IP，於是「Central 部署成功、console 卻 502 直到你也重新部署 console」。
- **(d) 拆成兩個網域就壞掉**：terminal WebSocket 走 `location.host`，跨網域時 API 正常但終端機全滅；CSP `connect-src 'self'` 也會擋掉。
- **(e) 安全性質靜默降級**：TLS 由平台終結後，HSTS/CSP/`X-Frame-Options` 誰負責、`/api/metrics` 是否仍不對外、artifacts checksum 是否還能被驗證，全都變成沒有人擁有的問題。

成功的定義是：

1. 一個公開 HTTPS 網域同時服務 console、`/api` 與 `/ws`；HTTP 被重導，沒有第二個 origin。
2. `git push` → CI 綠 → 部署；migration 在容器啟動前跑完，失敗則部署不進行。
3. 部署期間：**沒有任何 CLI session 被終止**，瀏覽器收到 `terminal.server_shutdown`，daemon 依既有 backoff 重連（NFR-002）。
4. 一個真實 Linux host 上的 `agentd` 能用一行安裝指令對著這個網域完成 enrollment、跑 session、讀檔、更新，全程 WSS。
5. `scripts/railway/verify-deployment.sh` 對真實網域跑完並全綠；輸出是 release evidence，不是人工敘述。
6. 跨區延遲對 NFR-001 的實際影響有量測數字與明確的 release decision，不是「應該還行」。

## 2. 範圍

### 納入

- Railway 上的三個服務：`central`（FastAPI）、`console`（nginx + 靜態前端 + 反向代理）、`Postgres`。
- `deploy/railway/` 下的 config-as-code、Dockerfile、nginx template 與 entrypoint。
- `scripts/railway/` 下的環境檢查、artifacts 發佈、黑箱部署驗證腳本。
- Central 的 readiness 語意修正（`/readyz` 在 degraded 時回 503）與其所有呼叫點。
- 變數/secret 契約、自訂網域、artifacts volume、備份與監控的一次性作業與 runbook。
- CI/CD 串接、rollback 演練、traceability gate/link/waiver 與 exit report。

### 不納入

- 不改 protocol、RBAC、audit 語意、filesystem policy 或 session 生命週期。
- 不做 Central 水平擴充。registry 與 relay 是 process-local，多 replica 是**錯誤**而非降級（`docs/deployment.md` 已寫明）；要改需要共享狀態設計，不在本期。
- 不退休 `deploy/compose/`。Railway 是第二個部署目標，不是替代品。
- 不把 `deploy/nginx/nginx.conf` 改成「兩邊通用」的抽象。兩份檔案各自可讀，用 gate 擋 CSP 字串漂移。
- 不引入外部 secret manager、Terraform/Pulumi、Kubernetes 或多雲抽象層。
- 不新增產品功能，也不藉部署之名調整 PRD 需求。唯一的程式改動是 (b) 的 readiness 狀態碼，並在 ADR 記錄理由。
- 不把 `python -m app.retention prune` 排成 cron。ADR 0016 明確決定「由 operator 執行，不由背景排程刪 audit」；要改需要修 ADR，不在本期順手做。

## 3. 固定基線決策

| 項目 | 決定 | 為什麼不是別的做法 |
|---|---|---|
| 服務數量 | 3 個：`central`、`console`、`Postgres` | `console` 同時是靜態站與反向代理，因此只有一個公開 origin；`central` 不掛公開網域 |
| single-origin 實現 | `console` 的 nginx 反向代理 `/api`、`/ws` 到 `central.railway.internal` | terminal WS 走 `location.host`（`useTerminalSession.ts:85`）；CSP 是 `connect-src 'self'`。改成 FastAPI 直接吐靜態檔會產生第二套 header/CSP 實作，長期必漂移（見 01 §3） |
| 公開網域 | 第一天就綁**自訂網域**，`CLIORA_PUBLIC_BASE_URL` 用它 | 該值寫進 installer 與每個 node 的 `config.yaml`；`*.up.railway.app` 會隨服務改名/重建而變，等於要求全 fleet 重新設定 |
| replica 數 | 固定 1（`central`、`console` 皆然） | process-local registry/relay；且 artifacts volume 與 replica 互斥 |
| region | `asia-southeast1`（新加坡），三服務 + DB 同 region | 跨 region 私網延遲直接吃掉 NFR-001 的 200 ms 額外延遲預算，且 DB 每次查詢都付一次 RTT |
| 監聽位址 | `--host ::`，port 取 `$PORT`（明確設 `PORT=8080`） | 私網是 IPv6；`::` 在 `bindv6only=0` 的 Linux 上同時服務 IPv4-mapped，因此一個值同時滿足私網與 edge |
| start command | Railway service 的 `startCommand`（`sh -c 'exec …'`） | Railway 的 start command 覆寫 image 的 exec-form ENTRYPOINT，且 exec form 不做變數展開；用 `sh -c` + `exec` 取得 `$PORT` 又不讓 shell 吃掉 SIGTERM |
| migration | `preDeployCommand: alembic upgrade head` | 非零 exit 會擋住部署，等價於 compose 的 `service_completed_successfully`；仍然**不在 lifespan 裡 migrate** |
| drain | `drainingSeconds: 25`，`CLIORA_SHUTDOWN_DRAIN_SECONDS=15` | 平台預設 0 秒；此處是 compose `stop_grace_period: 30s` 那條規則的 Railway 版本，兩者必須同時維護 |
| 部署重疊 | `overlapSeconds: 0` | 重疊期間會有兩個 Central 同時持有 daemon socket 與 DB 連線（池加倍）。狀態既是 process-local，重疊沒有好處；接受一次短暫空窗，session 不受影響 |
| healthcheck | `healthcheckPath: /readyz`，且 `/readyz` **degraded 時回 503** | Railway 只看狀態碼。順帶修掉一個既有落差：`scripts/p4/drills/db-exhaustion.sh` 已在文件裡預期看到 503，但目前的 `/readyz` 永遠回 200 |
| DB 連線字串 | 以 reference variable 手組 `postgresql+asyncpg://…@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/…`，**不改程式** | `DATABASE_URL` 是 `postgresql://`，`Settings.database_url` 要 asyncpg driver；在變數層轉換可被審閱，也不在程式裡塞平台特例 |
| DB 連線池 | 沿用 `db_pool_size=10`、`db_max_overflow=10`；上線前確認 Postgres `max_connections` ≥ 60 | 單 replica 上限 20，加 preDeploy 與人工連線仍有餘裕；`overlapSeconds=0` 讓它不會加倍 |
| artifacts | 第一階段 `CLIORA_ARTIFACTS_DIR` 留空（端點 404）；對外開放前掛 volume 至 `/srv/artifacts` | manifest 與 `/api/downloads` 讀本地檔（`services/releases.py`）。掛 volume 換來「部署有停機且不可 replica」，因此把這個代價推遲到真的需要一行安裝時 |
| secret 注入 | 全部走 Railway 服務變數；image 不含 secret；`CLIORA_ENVIRONMENT=production` | `Settings.reject_dev_secrets_in_production` 會讓忘記設定變成啟動失敗，而非可偽造的 token |
| metrics | 預設 `CLIORA_METRICS_ENABLED=false`；edge 對 `/api/metrics` 回 404 | 對外的 metrics 端點是控制平面上的常駐讀取面。要 scrape 就在專案內加 Prometheus 服務走私網（04 §5 選配） |
| TLS | Railway edge 終結；`console` 依 `X-Forwarded-Proto` 對非 https 回 301，並繼續發 HSTS/CSP | 容器只看得到 HTTP，若不看 forwarded header 就沒有任何 HTTP→HTTPS 保證（TECH-SEC-01、SEC-005） |
| 前端建置變數 | `VITE_API_BASE_URL` 必須為空字串；`VITE_PRODUCT_NAME` 由 build arg 帶入 | 空字串＝相對路徑＝same-origin。非空會讓 API 跨網域而 WS 仍留在 `location.host`，是最難診斷的半壞狀態 |
| 觀測 | 外部 uptime 檢查打 `/readyz` | Railway 的 healthcheck **只在部署時執行，之後不再監看**；沒有外部檢查就沒有任何人會發現上線後 DB 斷了 |

任何偏離上表的實作，先寫進 ADR 0020 再改。

## 4. 目標拓撲

```text
                          Internet (HTTPS/WSS only)
                                   │
                     Railway edge（TLS 終結、HTTP/1.1+HTTP/2、
                     WebSocket 不受 idle/duration 限制）
                                   │  自訂網域 cliora.example.com
                                   ▼
┌──────────────────────────── service: console（public, replica=1）────────────┐
│ nginx:1.27-alpine + frontend/dist（build 時產生，image 內無 node/原始碼）      │
│  listen ${PORT}（純 HTTP，無 443 block、無憑證檔）                            │
│  X-Forwarded-Proto != https → 301                                            │
│  HSTS / CSP / X-Frame-Options / COOP / Permissions-Policy（每個 location 重複）│
│  location = /api/metrics → 404                                               │
│  location /api/  ─┐  location /ws/ ─┐   （proxy_pass 走變數 + resolver，      │
│  location /healthz、/readyz（不記 log）  才不會快取到 Central 的舊 IP）        │
└───────────────────┼──────────────────┼───────────────────────────────────────┘
                    │ 私網 IPv6        │ 私網 IPv6（WSS 已在 edge 解除加密）
                    ▼                  ▼
┌──────────────────────── service: central（private only, replica=1）──────────┐
│ deploy/backend.Dockerfile（非 root uid 10001、image 無 secret）               │
│ startCommand: sh -c 'exec uvicorn app.main:app --host :: --port ${PORT}'      │
│ preDeployCommand: alembic upgrade head                                       │
│ healthcheckPath: /readyz（503 = 未 ready）  drainingSeconds: 25               │
│ /srv/artifacts ← volume（第二階段才掛；掛了就不可 replica、部署有停機）        │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ 私網（asyncpg）
                                ▼
                    service: Postgres 16（同 region、有備份）

     daemon 永遠在使用者自己的 Linux host 上，主動 outbound 連 wss://<自訂網域>/ws/nodes
     （FR-CONN-001：Central 不主動連 node，因此 Railway 不需要任何 inbound 規則到 node）
```

要點：Railway 上**沒有任何 agentd**。`agentd` 是裝在使用者主機上的、跑 tmux 的常駐程序；Railway 只承載 Central 與 console。這也是這個架構天生適合 PaaS 的原因——控制平面無狀態（除 DB 與 artifacts），執行面全在客戶側。

## 5. 執行波次與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | **RW-01** | ADR 0020：single-origin 實現方式、region、replica=1、artifacts 位置、public base URL 一次性、readiness 狀態碼變更、TLS 責任分界 | 無 |
| 0 | **RW-02** | requirement 影響矩陣（哪些由平台承擔／被削弱／需補償）、traceability 掛載計畫（新 gate/link/waiver 草案） | RW-01 |
| 1 | **RW-03** | `central` 服務可跑：`deploy/railway/central.railway.json`、`PORT`/`::`/start command、`drainingSeconds`、`/readyz` 回 503 與全部呼叫點更新 | RW-01 |
| 1 | **RW-04** | `Postgres` 服務、`CLIORA_DATABASE_URL` reference-variable 契約、連線池與 `max_connections` 確認、`preDeployCommand` migration | RW-03 |
| 1 | **RW-05** | `console` 服務：`deploy/railway/console.Dockerfile`、`nginx.conf.template`、resolver entrypoint、私網 upstream、header/CSP 平移與 parity gate | RW-03 |
| 2 | **RW-06** | 變數與 secret 契約 `deploy/railway/env.md` + `scripts/railway/check-env.sh`（缺漏、dev 預設值、URL scheme、非 same-origin 設定一律非零 exit） | RW-03/04/05 |
| 2 | **RW-07** | 自訂網域、`CLIORA_PUBLIC_BASE_URL` 定案、HTTP→HTTPS 與 HSTS 實測、WSS 端到端 | RW-05/06 |
| 2 | **RW-08** | artifacts volume + `scripts/railway/publish-artifacts.sh`（自 GitHub Release 取檔並驗 `checksums.txt`）、manifest 與 `/api/install-script` 端到端 | RW-07 |
| 2 | **RW-09** | 營運一次性作業：第一位 Admin、備份與還原、外部 uptime 檢查、retention 手動流程、（選配）私網 Prometheus | RW-07 |
| 3 | **RW-10** | `scripts/railway/verify-deployment.sh`：對真實網域的黑箱驗證（redirect、header/CSP、WS 存活、8 MiB 讀取、`/api/metrics` 404、readiness、drain 行為） | RW-07 |
| 3 | **RW-11** | 真實 node 端到端與 NFR 量測：enrollment → session → terminal → files → update；跨區延遲、Central 重啟後重連、500 WS 目標的可行性重新界定 | RW-08/10 |
| 3 | **RW-12** | CI/CD 串接與 rollback 演練、`docs/deployment-railway.md` + runbook、traceability gate/link/waiver 落地、exit report | 全部 |

關鍵路徑：

```text
RW-01 → RW-02
   └→ RW-03 → RW-04 ─┐
             RW-05 ─┴→ RW-06 → RW-07 →┬→ RW-08 →┬→ RW-11 → RW-12
                                       ├→ RW-09  │
                                       └→ RW-10 ─┘
```

RW-01 未定案前不要動 `deploy/railway/` 的內容：single-origin 的實現方式決定了 console 服務存不存在，也決定 RW-05 有沒有必要。

## 6. 每張 ticket 的完成格式

每張 RW ticket 至少附：

- 影響的 requirement/control ID（PRD `FR-*`/`SEC-*`/`NFR-*`、tech `TECH-SEC-*`）與該項在 Railway 上由誰負責。
- 變更檔案的**完整路徑清單**，以及對既有檔案的改動理由；不得只說「調整設定」。
- 平台設定值：服務名、變數、config-as-code 欄位與其值，可被貼進 review。
- **實測命令與輸出**：`curl`、`railway logs`、`railway ssh`、腳本 exit status。平台文件說會怎樣不算證據。
- 失敗模式：這項設錯會壞在哪裡、外顯症狀是什麼、以及是「立刻壞」還是「下次部署才壞」。
- 回復方式：改回什麼值、要不要重新部署、要不要重新 enroll node。
- 不得寫入 artifact 的資料：secret 值、token、terminal bytes、檔案內容、使用者私人絕對路徑。

## 7. 阻擋規則

### PR 階段

- `deploy/railway/**` 或 `scripts/railway/**` 改動而 `deploy/railway/env.md` 未同步：阻擋。
- 兩份 nginx 設定的 CSP 字串不一致：阻擋（parity gate，見 03 §5）。
- `/readyz` 語意改動未同時更新全部呼叫點（`scripts/p4/verify-edge.sh`、`scripts/e2e/run-stack.sh`、`scripts/p4/backup-restore-drill.sh`、`scripts/p4/drills/*`、`.github/workflows/p1.yml`、`deploy/compose/compose.yaml`）：阻擋。
- `make check` 與 `make traceability` 仍為既有阻擋條件；本期不放寬。

### 上線階段

- `scripts/railway/check-env.sh` 非零：不部署。
- `scripts/railway/verify-deployment.sh` 有任一 FAIL：不對外開放網域。
- 未實測「部署期間 session 存活」與「daemon 重新註冊」：不可宣稱 NFR-002 成立。
- NFR-001 跨區量測未完成：可上線，但必須有明確 release decision 或 waiver（不得預設「達標」）。
- artifacts 端點未驗 checksum 端到端：不得公布一行安裝指令（TECH-SEC-12、SEC-002）。

## 8. 完成定義

同時成立才算完成：

- 三個服務在同一 region、各 1 replica、`central` 沒有公開網域，console 有自訂網域與有效憑證。
- `git push` → CI 綠 → 自動部署 → migration 先跑 → `/readyz` 200 → 接流量，全程可在 Railway 日誌與 GitHub run 中重建時序。
- 一次刻意的部署中，`central` 日誌出現 `shutdown_drained` 且 `duration_ms` 在 15 s 內；同時瀏覽器端觀察到 `terminal.server_shutdown`；`tmux ls` 在 node 上仍列出原 session。
- 一台真實 Linux host 以一行安裝指令完成 enrollment 並可跑 session/檔案瀏覽/`agentd update --dry-run`。
- `verify-deployment.sh` 全綠，輸出納入 release evidence，且能故意破壞其中一項（例如關掉 `/api/metrics` 的 404 block）而確實 FAIL。
- `docs/deployment-railway.md` 與 runbook 存在，且對 rollback（應用層與 schema 層）各演練過一次。
- traceability：新 gate 進 `traceability/gates.json`，受影響 criterion 有 `verified_by`/`measured_by` link，跨區 NFR 若未達標則有具名 waiver；`make traceability` 綠。
