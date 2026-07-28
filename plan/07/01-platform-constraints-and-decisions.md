# 01 — 平台限制與決策（RW-01、RW-02）

## 1. Railway 平台事實表

這張表是後面所有 ticket 的前提。**標「已查證」者來自 Railway 官方文件；標「須實測」者必須由 RW-10 的腳本在真實環境確認後才可寫進 ADR 當結論。**

| # | 事實 | 狀態 | 對 Cliora 的直接後果 |
|---:|---|---|---|
| 1 | 私網為 IPv6；2025-10-16 之後建立的環境同時解析 IPv4/IPv6，舊環境**只有** IPv6。官方建議應用監聽 `::` | 已查證 | uvicorn 必須 `--host ::`；沿用 image 內的 `--host 0.0.0.0` 在舊環境完全不可達，在新環境「看起來能動」，於是問題會在遷移環境時才爆 |
| 2 | 內部名稱為 `<service>.railway.internal` | 已查證 | console 的 upstream 是 `central.railway.internal:${PORT}` |
| 3 | 服務每次部署的私網 IP 會變 | 須實測（nginx 端症狀已可預期） | nginx 若用靜態 `upstream { server … }`，config 載入時解析一次並快取，Central 重新部署後 console 會 502 直到 console 也重啟。必須用「變數 + `resolver`」在請求時解析 |
| 4 | `drainingSeconds` 預設 **0**：SIGTERM 後不給任何寬限期即 SIGKILL；平台不發送其他訊號 | 已查證 | 必須設 ≥ 20（本期用 25）。否則 `_drain()` 的三件事（通知瀏覽器、關 daemon socket、讓 in-flight request 收斂）全部不會發生 |
| 5 | `overlapSeconds`：新部署上線到舊部署移除之間的重疊窗 | 已查證（預設值未在文件中明示） | 明確設 0。重疊期間會有兩個 Central 同時持有 daemon socket 與 DB 連線 |
| 6 | healthcheck 會反覆請求 `healthcheckPath` 直到 **HTTP 200**，才切換流量；預設 timeout 300 s；**部署完成後不再監看** | 已查證 | `/readyz` 必須在 degraded 時回非 200，否則 readiness 沒有作用；且上線後需要外部 uptime 檢查 |
| 7 | `preDeployCommand` 在 build 之後、部署之前，於同一 image、同一組環境變數、**獨立容器**中執行；**非零 exit 會使部署不進行且不重試**；不可寫入 volume | 已查證 | 這正是 migration 需要的語意，等價於 compose 的 `service_completed_successfully`。因為不可寫 volume，artifacts 不能在此步驟發佈 |
| 8 | start command 覆寫 image 的 **exec-form ENTRYPOINT**；exec form 不做變數展開 | 已查證 | `startCommand` 要寫成 `sh -c 'exec uvicorn … --port ${PORT}'`；`exec` 讓 uvicorn 成為 PID 1 的實際接收者，SIGTERM 不被 shell 吃掉（與 `deploy/backend.Dockerfile` 裡「不用 shell form」的理由相同） |
| 9 | edge：HTTP/1.1 與 HTTP/2；WebSocket 走 HTTP/1.1；HTTP 請求最長 15 分鐘（有資料傳輸時）、無資料傳輸 5 分鐘關閉；request body 須在 5 分鐘內上傳完；header 合計上限 32 KB | 已查證 | `/api` 的最慢合法請求是 daemon update relay（180 s，ADR 0017），遠低於上限。header 32 KB 對 Bearer token 綽綽有餘 |
| 10 | **WebSocket 連線不受上述 duration/inactivity 限制，可無限期閒置** | 已查證 | Railway edge 不會造成 P4 那個「固定週期斷線」的失敗模式。但 console 內的 nginx 仍有自己的 `proxy_read_timeout`，必須維持在 uvicorn `ws_ping_interval`（預設 20 s）之上 |
| 11 | volume：每服務最多 1 個；**有 volume 就不能有 replica**；重新部署會有停機（不允許兩個部署同時掛載） | 已查證 | artifacts 掛在 `central` 上等於接受「每次部署有短暫停機」。replica=1 本來就是既定事實，這部分不算額外代價 |
| 12 | reference variable：`${{ServiceName.VAR}}`、`${{shared.VAR}}`，可與字串組合 | 已查證 | 用來把 Postgres 的憑證組成 asyncpg URL，不必把密碼複製到第二個服務 |
| 13 | 系統變數含 `RAILWAY_PUBLIC_DOMAIN`、`RAILWAY_PRIVATE_DOMAIN` 等；`PORT` 是否自動注入未在變數參考中明列 | 已查證（`PORT` 部分為文件缺口） | 不依賴自動注入：兩個服務都**明確設定** `PORT=8080`，start command 用 `${PORT:-8080}` 兜底 |
| 14 | region 含 `asia-southeast1`（新加坡，`asia-southeast1-eqsg3a`）；edge 為 anycast | 已查證 | 台灣使用者 → 新加坡 RTT 通常 40–60 ms。這會直接進入 NFR-001 的「終端機輸入到顯示」路徑，必須量測（RW-11） |
| 15 | Postgres 服務提供 `DATABASE_URL`（私網）與 `DATABASE_PUBLIC_URL`（TCP proxy） | 須實測變數名稱 | `DATABASE_URL` 是 `postgresql://`，與 `Settings.database_url` 需要的 `postgresql+asyncpg://` 不同；public URL 供本機一次性作業使用 |
| 16 | Railway 的 GitHub 整合可在部署前等待 CI | 須實測（選項名稱與方案可用性） | 若不可用，改由 GitHub Actions 在 `check` job 之後執行 `railway up --service`（RW-12 兩案並列） |

## 2. 這些事實如何對上既有設計

`deploy/compose/` 與 `deploy/nginx/nginx.conf` 的註解已經把每個關鍵值的理由寫下來了。Railway 版必須逐條對照，**保留理由、替換機制**：

| 既有機制（compose） | 理由（不變） | Railway 上的機制 |
|---|---|---|
| `stop_grace_period: 30s` > `shutdown_drain_seconds: 15` | SIGKILL 落在 drain 中間，就會產生 drain 本來要避免的無理由斷線 | `drainingSeconds: 25` |
| `depends_on: migrate: service_completed_successfully` | 長駐容器不得在 boot 時 migrate（replica 互相競爭、重啟變成非計畫 schema 變更） | `preDeployCommand: alembic upgrade head` |
| healthcheck 解析 `/readyz` 的 body | 未 migrate 或連不上 DB 的容器不得接流量 | `healthcheckPath: /readyz` + **`/readyz` degraded 回 503** |
| `expose: 5432`（不 publish） | DB 只給 backend 與 migrate 看得到 | Postgres 不加公開 TCP proxy 網域；只在需要本機一次性作業時臨時使用 |
| nginx `proxy_read_timeout 3600s` on `/ws/` | 必須高於 uvicorn `ws_ping_interval`，否則所有 WS 定期同時死亡 | 沿用 3600s（Railway edge 對 WS 無 idle 限制，但 console 的 nginx 仍是路徑上的一段） |
| `client_max_body_size 16m` | 不得讓合法的 8 MiB 檔案讀取被不懂 protocol 的元件回 413 | 沿用 |
| CSP 無任何外部來源 + `worker-src blob:` | Monaco 需要 blob worker；外部來源會讓 operator 瀏覽器對第三方發請求 | 沿用同一字串，並用 parity gate 擋漂移 |
| `location = /api/metrics { return 404; }` | `location /api/` 是前綴匹配，沒有精確匹配就等於對外公開 metrics | 沿用 |
| 443 server block + 憑證檔 + 301 | 正式環境只允許 HTTPS/WSS | TLS 由 edge 終結；改為依 `X-Forwarded-Proto` 判斷並 301 |

## 3. single-origin：三個方案與決定

前端有兩個硬約束，決定了這題的答案：

- `frontend/src/api/client.ts:72`：`BASE` 預設空字串，即相對路徑。
- `frontend/src/composables/useTerminalSession.ts:85-87`：terminal WebSocket 用 `location.protocol` 與 `location.host` 組出 `wss://<當前主機>/ws/sessions/…`，**完全不看 `VITE_API_BASE_URL`**。

因此「前端一個網域、後端另一個網域」會產生一個特別惡劣的半壞狀態：登入、node 列表、檔案樹全部正常（只要加了 CORS 與放寬 `connect-src`），但終端機一律連不上，而且症狀出現在使用者點進 session 之後。

| 方案 | 做法 | 優點 | 代價 | 判斷 |
|---|---|---|---|---|
| **A（採用）** | `console` 服務 = nginx + 靜態檔 + 反向代理 `/api`、`/ws` 到私網的 `central` | 與 compose 拓撲行為一致；CSP/header 只有一份語意；前端零改動；`central` 完全不對外 | 多一個服務；必須處理私網 IPv6 + resolver（本期最技術性的一段） | 採用 |
| B | `central` 用 FastAPI `StaticFiles` 直接吐 console，單服務 | 服務最少；沒有私網問題 | 出現**第二套** security header/CSP 實作（middleware），與 nginx 版必然漂移；要自行處理 `index.html` no-store 與 `/assets/` immutable；動到應用程式碼 | 不採用，但列為 A 若在平台上不可行時的退路（見 §6） |
| C | 前端與後端各自公開網域 + CORS + 放寬 CSP `connect-src` | 平台設定最簡單 | 需改 `useTerminalSession.ts`、加 CORS middleware、放寬 CSP，安全面淨損；且要維護兩個 origin 的憑證與 cookie/token 語意 | 不採用 |

補充：目前 `backend/app/main.py` **沒有** CORSMiddleware，`auth.py` 也沒有 `set_cookie`（token 走 Bearer）。這說明整個應用一直是 same-origin 假設下設計的；方案 C 等於推翻該假設，屬於架構變更，不是部署選項。

## 4. Requirement 影響矩陣（RW-02 產出）

| Requirement / control | Railway 上由誰保證 | 是否被削弱 | 需要的補償或驗證 |
|---|---|---|---|
| FR-CONN-002.AC-01、SEC-005.AC-01、TECH-SEC-01（HTTPS/WSS） | Railway edge 終結 TLS；console 對非 https 301 | 否，但責任分界改變 | RW-10 對真實網域驗 301、HSTS、WSS 可用；**私網段（edge→central、central→DB）為平台內部明文**，須在 ADR 0020 明確記錄為已知邊界 |
| FR-CONN-001.AC-01（daemon 主動連線） | 不變。Central 從不主動連 node | 否 | RW-11 以真實 node 驗證 |
| FR-CONN-003 / NFR-002.AC-01、AC-02（重連、重啟後重新註冊） | daemon 既有 backoff + `_drain()` 的 1012 關閉 | 只在 `drainingSeconds` 設錯時被削弱 | RW-10 觀察一次真實部署的 `shutdown_drained` 日誌與 node 重新註冊 |
| NFR-002.AC-03、AC-04（瀏覽器中斷不終止 session、狀態可恢復） | 不變（drain 不觸碰 tmux） | 否 | RW-11 在部署當下確認 node 上 `tmux ls` 仍在、重新 attach 有 scrollback |
| NFR-001.AC-01（終端機額外延遲 < 200 ms） | 使用者 → 新加坡 → node 的實際路徑 | **可能被削弱**（跨海 RTT 直接進入路徑） | RW-11 實測並記錄；未達標則需 release decision 或具名 waiver，不得預設達標 |
| NFR-001.AC-02～AC-04（列表/目錄/預覽秒數） | 同上，加上 DB 在同 region | 可能被削弱 | RW-11 實測 |
| NFR-003.AC-04（500 個同時 terminal WS） | 單一 Railway 容器的資源上限 | 須重新界定 | RW-11 用 `scripts/p4/load/` 的既有 harness 在 Railway 實例規格上重跑；上限低於 500 時，記錄實測值與所需規格，不改 PRD |
| FR-INSTALL-002/003（一行安裝、自動安裝） | `/api/install-script` 與 `/api/downloads` 需要 artifacts 在本地 | 第一階段**停用**（端點 404） | RW-08 掛 volume 並端到端驗證後才恢復；停用期間 node 以手動 `agentd install` 進場並在 runbook 註明 |
| FR-INSTALL-005 / TECH-SEC-12（更新、checksum 驗證） | manifest 由本地 artifacts 推導 | 隨 artifacts 停用而停用（manifest 回空，非 404，daemon 可正確判斷「無更新」） | RW-08 後以 `agentd update --dry-run` 驗證下載＋digest |
| SEC-003.AC-01（token 保護）、TECH-SEC-03/04 | 不變（DB + pepper） | 否 | `CLIORA_TOKEN_PEPPER` 一次性：輪替會使**所有 node credential 失效**，須全數重新 enroll |
| SEC-007 / TECH-SEC-02（不以 root 常駐） | daemon 在客戶主機（不變）；Central 容器以 uid 10001 執行 | 否 | RW-03 以 `railway ssh` 執行 `id` 確認非 root |
| TECH-SEC-08（terminal 內容不進 log） | 不變；但 Railway 會集中收集 stdout | 否，須確認 | RW-03 檢視部署日誌，確認無 terminal bytes、無 token；`structlog` 輸出即現況 |
| TECH-SEC-11（WS 身分與權限檢查） | 不變（ws-ticket + resource scope） | 否 | 既有測試涵蓋；RW-10 額外驗「無 ticket 連線被拒」 |
| TECH-SEC-15（queue/frame 上限） | 不變（Central 內建） | 否 | — |
| SEC-006（audit）、ADR 0016 retention | 不變 | 否 | RW-09 記錄手動 prune 流程；**不排 cron**（見 04 §4） |
| NFR-004（可維運性） | daemon 側不變 | 否 | Central 側新增：外部 uptime 檢查（因平台部署後不再 healthcheck） |

## 5. ADR 0020 必須記錄的決定

RW-01 的產出是 `docs/adr/0020-railway-deployment-topology.md`，至少定案：

1. **拓撲**：方案 A（console 反向代理），含被否決的 B/C 與否決理由（`useTerminalSession.ts` 的 `location.host`、第二套 CSP 實作）。
2. **region 與單一 replica**：`asia-southeast1`；replica 固定 1 並說明這是正確性要求（process-local registry/relay），不是成本選擇。
3. **`CLIORA_PUBLIC_BASE_URL` 為一次性決定**：值寫進 installer 與每個 node 的 config；連同 `CLIORA_TOKEN_PEPPER` 一起列為「單向門」。
4. **readiness 語意變更**：`/readyz` 在 degraded 時回 503。理由是平台只讀狀態碼；並記錄這順帶修正了 `scripts/p4/drills/db-exhaustion.sh` 文字（已預期 503）與實作（永遠 200）之間的既有落差。
5. **TLS 責任分界**：公網段由 Railway 終結；`X-Forwarded-Proto` 是 console 判斷的依據；私網段（edge→central、central→Postgres）為平台內部網路且未加密，這是接受的邊界，並說明為何不在私網段自行加 TLS（憑證管理成本高於收益，且威脅模型是平台內部網路）。
6. **artifacts 分階段**：先停用（端點 404、manifest 空）、後掛 volume；明確寫下「掛 volume ⇒ 不可 replica ＋ 每次部署有停機」。
7. **不排程 retention**：維持 ADR 0016 的「operator 執行」決定；若日後要 cron，必須先修 ADR 0016 並加上「先備份」的前置。
8. **metrics 預設關閉**，且 edge 一律 404；要 scrape 只能走專案內私網。
9. **compose 拓撲不退休**，兩套並存的維護規則（CSP parity gate、drain 值成對維護）。

## 6. 退路與觸發條件

| 若發生 | 改用 | 觸發判準 |
|---|---|---|
| 私網 + nginx resolver 在平台上無法穩定運作（RW-05 卡住超過一輪驗證） | 方案 B（FastAPI `StaticFiles` + 一支 security-header middleware） | 必須同時交付：middleware 的 header 由測試逐項斷言、`index.html` no-store 與 `/assets/` immutable 各有測試、CSP 字串與 nginx 版共用同一常數並由 parity gate 檢查 |
| Railway edge 對 WebSocket 的實測行為與文件不符（出現週期性斷線） | 先確認是否為 console nginx 的 `proxy_read_timeout`；排除後記為平台限制並評估是否仍可上線 | RW-10 的 WS 存活檢查（> 60 s 閒置）失敗 |
| `asia-southeast1` 的實測延遲使 NFR-001 明顯不可達 | 評估改 region 或改為「使用者與 node 同區、Central 就近」的部署建議；不改 PRD 數字 | RW-11 量測結果 |
| Postgres `max_connections` 低於池上限所需 | 調降 `db_pool_size`/`db_max_overflow` 並記錄新的分母（`database_pool_usage` 的告警依賴它） | RW-04 查得的實際值 |
