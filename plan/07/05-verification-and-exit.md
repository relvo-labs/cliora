# 05 — 驗證、CI/CD 與退出（RW-10、RW-11、RW-12）

## 1. RW-10：`scripts/railway/verify-deployment.sh`

與 `scripts/p4/verify-edge.sh` 同一個理念：**執行設定，而不是閱讀設定**。差別是它對真實的公開網域跑，不自建 nginx 容器。

```bash
scripts/railway/verify-deployment.sh https://cliora.example.com [output-dir]
# 預設 output-dir = artifacts/rw/local；輸出 deployment-verification.md 與 result.json
```

腳本結構沿用 `verify-edge.sh` 的 `ok/fail/CHECKS/FAILURES` 記帳與 Markdown 報告，最後以失敗數為 exit code。

| # | 檢查 | 方法 | 為什麼這一項會壞 |
|---:|---|---|---|
| 1 | HTTP → HTTPS | `curl -sSI http://$D/` 應為 301 且 `Location` 為 https | console 的重導是 fail-open 的（見 03 §2.3）；只有真實請求能證明 edge 會帶 `X-Forwarded-Proto: http` |
| 2 | 六個 security header 存在於 `/`、`/assets/*.js` 兩種回應 | 逐項 grep | `add_header` 不繼承進宣告了自己 `add_header` 的 location——這個坑在 compose 版已經發生過一次 |
| 3 | CSP 值與 `deploy/railway/nginx.conf.template` 完全相同，且不含任何外部來源 | 字串比對 + 檢查沒有 `http(s)://` 出現在 policy 中 | 一次 CDN 引用回歸就會讓 operator 的瀏覽器對第三方發請求 |
| 4 | CSP 含 `worker-src 'self' blob:` | 字串包含 | 缺了 Monaco 白屏，只有 console error 可看 |
| 5 | `Cache-Control`：`/` 為 `no-store`，`/assets/` 為 `immutable` | header 比對 | index.html 被快取 → 瀏覽器一直載入指向已刪除 asset 的舊 bundle |
| 6 | `/api/metrics` 回 404 | 狀態碼 | `location /api/` 是前綴匹配；少了精確匹配就是對外公開整組 series |
| 7 | `/readyz` 回 200；且刻意情境下 degraded 回 503 | 狀態碼 | Railway 只看狀態碼，這是 readiness 是否真的存在的唯一證明 |
| 8 | WebSocket 握手可用：未帶 ticket 連 `/ws/sessions/…/terminal` 應被拒（非 101 或立即關閉），帶合法 ticket 應為 101 | Python `websockets` 或 `curl --include -H 'Upgrade: websocket'` | 證明 WS 通過 edge + console 兩層代理且授權檢查未被繞過（TECH-SEC-11） |
| 9 | WebSocket 閒置存活 > 90 s | 建立連線後不送資料，等待並確認未被關閉 | Railway 文件說 WS 免除 idle 限制，但 console 的 `proxy_read_timeout` 若被設低於 uvicorn 的 20 s ping，所有終端機會固定週期同時死亡。這一項不能縮短，門檻本身就是被測物 |
| 10 | `client_max_body_size` 不低於 8 MiB 契約 | 以檔案送出 9 MiB POST body，斷言**不是** 413（且狀態碼必須是三位數才算量到） | 低於 8 MiB 的限制會把合法讀取變成 413，且錯誤來自一個不懂 protocol 的元件。整條檔案讀取路徑仍需 node（RW-11） |
| 11 | `/api/install-script` 與 `/api/downloads/checksums.txt` | 兩者皆 200（已發佈）或皆 404（artifacts 停用，記 skip）；一個 200 一個 404 即 FAIL | TECH-SEC-12 的前置；狀態不一致代表發佈只做了一半 |
| 12 | 下載 allowlist | `passwd`、`agentd_1.0.0_linux_riscv.tar.gz`、`checksums.txt.bak` 皆須 404 | 這三個名稱會原樣送到 Central，真正測到 allowlist（SEC-002） |
| 12b | 編碼過的路徑穿越 | `/api/downloads/..%2f..%2fetc%2fpasswd` 的**回應內容**不得像系統檔 | 原本這項寫成「應回 404」，實測回 200——因為 **nginx 會先解碼 `%2f` 並解析 `..`**，請求被正規化成 `/etc/passwd`，落到 `location /` 由 SPA fallback 回 index.html。沒有洩漏，但那個 404 期望根本沒打到 Central，Central 的 allowlist 整個拿掉也一樣會過 |
| 13 | 回應不洩漏平台細節 | 檢查沒有 `Server: nginx/1.27.x` 版本、沒有 uvicorn 版本 | `server_tokens off` 是否真的生效 |

### 1.1 部署 drain 的驗證（半自動）

腳本無法自己觸發部署，因此這一段寫成明確程序並把輸出併入報告：

```bash
# 1. 建立一個 session 並開著瀏覽器（或用 scripts/p4/load/terminal_clients.py 建一個訂閱者）
# 2. 觸發一次重新部署（改一個無害變數即可）
# 3. 觀察三件事
railway logs --service central | grep -E "shutdown_drained|shutdown_drain_timeout"
#    → 必須看到 shutdown_drained，且 duration_ms < 15000（未 timeout）
#    → 瀏覽器端 console 收到 terminal.server_shutdown（reason + session_preserved: true）
#    → node 上 tmux ls 仍列出原 session；重新連線後有 scrollback
```

三件事任一不成立，就不能宣稱 NFR-002.AC-02/AC-03 在 Railway 上成立。最可能的原因是 `drainingSeconds` 未設（平台預設 0）。

## 2. RW-11：真實 node 端到端與 NFR 量測

### 2.1 端到端（一台真實 Linux host，非容器）

依序完成，每一步記錄實際輸出：

1. Admin 在 console 建立 enrollment token。
2. 一行安裝：`curl -fsSL https://<網域>/api/install-script | sudo bash -s -- --server https://<網域> --token … --name … --user …`。
3. `agentd doctor` 全綠——特別是 **Central TCP reachability**（它現在打的是 Railway edge）。
4. node 在 console 顯示 online；heartbeat 間隔符合 `heartbeat_interval_seconds`。
5. 建立 session（Fake CLI 或真實 runtime）→ 終端機有輸出 → 輸入有回應 → resize 生效。
6. 檔案樹展開、預覽一個 ~1 MB 檔（Monaco 正常渲染）、搜尋、以及一次被拒的敏感路徑（audit 有記錄）。
7. `sudo systemctl restart agentd` → 重新註冊、session 仍存活、可重新 attach。
8. `sudo agentd update --dry-run` → manifest + 下載 + digest 檢查通過。
9. 觸發一次 Central 重新部署 → daemon 重連（NFR-002.AC-02）、session 不受影響。

### 2.2 NFR 量測（必須有數字，不得預設達標）

輸出到 `artifacts/rw/<run-id>/`：

| 量測 | 方法 | 門檻 | 備註 |
|---|---|---|---|
| 終端機額外延遲 | 沿用 `backend/perf/relay_bench.py` 的量測方式，但對 Railway 的公開網域跑；同時記錄本機 → 網域的基準 RTT | NFR-001.AC-01：< 200 ms | **路徑上新增了跨海 RTT（台灣→新加坡約 40–60 ms）與一跳 console 代理**。要把「網路 RTT」與「Cliora 額外延遲」分開報告，否則無法判斷是產品變慢還是地理距離 |
| Node 列表 | `curl -w '%{time_total}'` × 20 取 p50/p95 | NFR-001.AC-02：< 2 s | DB 與 Central 同 region，主要成本是使用者到 edge 的 RTT |
| 目錄列表 / 檔案預覽 | 同上，經真實 node | AC-03 < 2 s、AC-04 < 3 s | |
| 同時 terminal WS 上限 | `scripts/p4/load/capacity.py` 對 Railway 實例規格重跑 | NFR-003.AC-04：500 | 若達不到，記錄「在 X vCPU / Y GB 上實測為 N 條」與所需規格，**不改 PRD 數字**，交 release decision |

若 NFR-001 因地理距離無法達標，正確的處理是：記錄拆解後的數字、在 `docs/deployment-railway.md` 說明「Central region 應接近使用者」的部署建議，並開一張具名 waiver（見 §4.3）。不接受把門檻悄悄重新定義成「不含網路 RTT」——那是改需求，要走 PRD 變更流程。

## 3. RW-12：CI/CD、rollback、文件

### 3.1 部署觸發

兩案，擇一並在 ADR 記錄：

- **方案 1（優先）**：Railway 的 GitHub 整合 + 「部署前等待 CI 通過」。最少活動零件，`watchPatterns` 已把兩個服務的觸發範圍分開。需先確認該選項在使用的方案上可用。
- **方案 2（退路）**：GitHub Actions 新增 `.github/workflows/railway.yml`，只在 `master` 且 `needs: [check]` 成功後執行 `railway up --service central` / `--service console`，token 走 repository secret。好處是部署條件完全寫在 repo 裡、可審；代價是多一份需要維護的 workflow 與一枚長期 token。

兩案都必須成立的性質：**CI 未綠不部署**。`make check` 已含 traceability static gate，因此「文件漂移」也擋在部署之前。

部署前置檢查（兩案皆然）：`scripts/railway/check-env.sh` 與 `scripts/railway/check-edge-parity.sh` 為 `make check` 的一部分或 workflow 的前置 job。

### 3.2 Rollback 演練

沿用 `docs/deployment.md` 的原則（應用層先試、schema 層才動 migration），各演練一次並記錄：

| 情境 | 操作 | 驗證 |
|---|---|---|
| 應用層回滾 | Railway 的 rollback（回到上一個部署）或 redeploy 前一個 commit | `/readyz` 200、console 可登入、node 仍 online、session 存活 |
| schema 回滾 | 先備份 → `railway ssh --service central -- alembic downgrade <rev>` → 部署舊 image | 明確記錄該 revision 的 `downgrade()` docstring 說明會失去什麼 |
| 設定回滾 | 誤設 `CLIORA_PUBLIC_BASE_URL` 後改回 | 已 enroll 的 node 是否需要 `agentd register`（答案：需要，若曾以錯值 enroll） |

### 3.3 文件

- `docs/deployment-railway.md`：第一次部署順序、變數清單指向 `deploy/railway/env.md`、升級、rollback、備份、retention 手動流程、監控、以及**與 compose 拓撲的差異表**。
- `docs/adr/0020-railway-deployment-topology.md`：見 01 §5。
- `docs/runbooks/railway-edge-502.md`（新增）：console 502 的診斷順序——先 `/edge-health`（區分 edge 與 Central）、再 `railway logs --service console` 看 resolver 錯誤、再看 `CLIORA_BACKEND_HOST/PORT` 與 `central` 的 `PORT`、最後才看 Central 是否綁在 `::`。這四步的排序就是這一期學到的東西，值得寫下來。
- `docs/deployment.md` 加一段指向 Railway 版，並明確說明兩者是並存的部署目標。

## 4. Traceability 掛載（RW-02 規劃、RW-12 落地）

### 4.1 新 gate

加進 `traceability/gates.json`：

```json
{
  "id": "GATE-RAILWAY-EDGE-PARITY",
  "owner": "operations", "layer": "static",
  "command": ["scripts/railway/check-edge-parity.sh"],
  "working_directory": ".", "timeout_seconds": 60,
  "trigger": ["pull_request", "main", "release"],
  "required_for": ["changed", "all"]
}
```

| Gate ID | layer | command | trigger | required_for | environment |
|---|---|---|---|---|---|
| `GATE-RAILWAY-EDGE-PARITY` | static | `scripts/railway/check-edge-parity.sh` | PR/main/release | changed, all | — |
| `GATE-RAILWAY-CONFIG-TESTS` | unit | `make railway-test` | PR/main/release | changed, all | — |
| `GATE-RAILWAY-ENV` | operations | `scripts/railway/check-env.sh` | release, manual | all | `railway-cli`, `railway-production` |
| `GATE-RAILWAY-DEPLOY-VERIFY` | e2e | `scripts/railway/verify-deployment.sh` | release, manual | all, security | `railway-production` |
| `GATE-RAILWAY-NODE-E2E` | manual | `scripts/trace manual-template --procedure railway-node-e2e` | release, manual | mvp | `railway-production`, `real-linux-host` |
| `GATE-RAILWAY-LATENCY` | performance | `scripts/p4/load/capacity.py`（對 Railway 網域） | release, manual | nfr | `railway-production`, `asia-southeast1` |

後三者是 `manual`/外部環境 gate：依 ADR 0019 §「skip 不是 pass」，未執行就是 `skipped` 並記 prerequisite，不得由工具推導成 pass。

### 4.2 新 link

以 `role: "supporting"` 加入，**不動既有 primary link**——baseline 已清零（`traceability/baseline-debt.json` 為空、`coverage --strict` 回 0），把新 gate 設成 primary 會改變既有 criterion 的必要 link 集合，等於在部署工作裡動需求覆蓋率。`applicability` 沿用 `["mvp"]`（coverage 的 scope 過濾讀 requirement 層的 applicability，link 層不參與，因此沿用最不會有意外）。

| criterion | type | target | 說明 |
|---|---|---|---|
| `FR-CONN-002.AC-01`、`SEC-005.AC-01`、`TECH-SEC-01.AC-01` | verified_by | gate `GATE-RAILWAY-DEPLOY-VERIFY` | Railway 拓撲下的 HTTPS/WSS 實測 |
| `NFR-002.AC-02`、`NFR-002.AC-03` | verified_by | gate `GATE-RAILWAY-NODE-E2E` | 重啟後重新註冊、session 不被部署終止 |
| `NFR-001.AC-01`…`AC-04` | measured_by | gate `GATE-RAILWAY-LATENCY` | 跨區量測 |
| `NFR-003.AC-04` | measured_by | gate `GATE-RAILWAY-LATENCY` | 500 WS 在 Railway 規格上的實測 |
| `FR-INSTALL-002.AC-01`、`TECH-SEC-12.AC-01` | verified_by | gate `GATE-RAILWAY-DEPLOY-VERIFY` | install-script / checksum 端到端 |
| 上述各 criterion | planned_by | plan `plan/07/…`（對應文件） | 本期規劃來源 |

### 4.3 可能需要的 waiver

若 RW-11 顯示 NFR-001 或 NFR-003 在 Railway 上不達標，開一張 `WVR-2026-0NN`（`traceability/waivers.json`）：criteria 具名、`reason` 寫明是地理距離／實例規格而非實作缺陷、`impact` 寫明使用者感受、`compensating_controls` 至少含「部署建議：Central region 靠近使用者」與「已記錄實測值與所需規格」、`expires_at` 與 `revisit_trigger`（例如「改變 region 或實例規格時」）、兩位以上 approver。

ADR 0019 §7 規定安全類要求不可用一般 waiver 放行——因此**任何 SEC/TECH-SEC 項目在 Railway 上做不到，都不是 waiver 能處理的**，必須修設定或不上線。

## 5. 退出條件

- 00 §8 的完成定義全部成立。
- `scripts/railway/{check-env,check-edge-parity,verify-deployment}.sh` 三支都能重跑、都有報告產出，且各自能被故意弄壞而確實失敗（至少各示範一項）。
- RW-11 的端到端九步全部有記錄輸出；NFR 量測有數字，未達標者有 release decision 或具名 waiver。
- 兩種 rollback 各演練一次並記錄。
- `make check`、`make traceability` 綠；新 gate 在 `gates.json` 中、新 link 不改變既有 coverage 結果（`coverage --strict` 仍回 0）。
- `docs/deployment-railway.md`、ADR 0020、`docs/runbooks/railway-edge-502.md` 存在且與實際設定一致。
- `plan/07/06-implementation-status.md` 更新為實際狀態，含所有「須實測」項目的結論。

## 6. 失敗回復

| 失敗 | 回復 |
|---|---|
| console 對 `/api` 全 502 | 依 `railway-edge-502.md` 四步；最常見是 `central` 綁 `0.0.0.0`（改 startCommand）或 `PORT` 兩邊不一致 |
| Central 啟動即 crash | 讀日誌；`ValueError: JWT secret and token pepper must be set in production` 是刻意的設定檢查，不是 bug |
| 部署後 schema 未更新 | `preDeployCommand` 未設；`/readyz` 會回 503 擋住流量。設好後重新部署 |
| 部署造成瀏覽器無理由斷線 | `drainingSeconds` 未設或小於 15 |
| 每次 Central 部署後 console 就 502 | nginx 用了靜態 upstream；改成變數 + resolver（03 §2.2） |
| 終端機一律連不上但 API 正常 | `VITE_API_BASE_URL` 非空，或 console 沒代理 `/ws/`，或 `proxy_pass` 遺漏 `$request_uri` 導致 `?ticket=` 消失 |
| Monaco 白屏 | CSP 缺 `worker-src 'self' blob:` |
| 已 enroll 的 node 全部失效 | `CLIORA_TOKEN_PEPPER` 被輪替。無法回復（單向門）——只能全數重新 enroll；這就是它被列為一次性決定的原因 |
| node 連到錯誤網域 | `CLIORA_PUBLIC_BASE_URL` 曾為 `*.up.railway.app`。逐台 `sudo agentd register --server https://<正確網域> --token …` |
