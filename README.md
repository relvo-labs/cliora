# Cliora

## 這是什麼（30 秒版）

Cliora 讓你從瀏覽器建立並操作一個跑在自己 Linux 主機上的 CLI coding agent session。`agentd` 會為每次工作建立一個 **Cliora 管理的 tmux session**，啟動 Claude CLI、Codex CLI 或允許的 shell runtime；瀏覽器透過 FastAPI **Central** 中介的認證 WebSocket 收看輸出與輸入指令。關掉分頁只會斷開瀏覽器連線，Cliora 建立的 tmux session 會繼續在主機上執行，之後可從另一個裝置重新連回去（見〈tmux session 語意〉）。**目前不會收編任意既有的 tmux／CLI process；可重連的是由 Cliora 建立與登記的 session。**

**目標讀者**：希望從瀏覽器或手機啟動、監看及接手 CLI coding-agent session，而不必一直維持 SSH 視窗的開發者；以及要替多台主機（Cliora 稱為 *node*）建立一次性安裝、管理上線狀態與存取權限的管理員。目前只承載原生 CLI 互動，不解析、不代管、不自動化 agent 的審批或工具呼叫（`research/prd.md` §4 非目標 1–5）。

**目前的成熟度邊界**：程式碼與測試把功能分批遞交（內部代號 P0–P4，以及之後的系統終端機、埠轉發、檔案上傳等幾波）。**P0** 是最早、刻意無資料庫、無正式驗證的原型垂直切片（Browser → Central → daemon → tmux → 決定性的 Fake CLI），連同它專用的開發用 WebSocket relay（`/ws/p0/*`、`CLIORA_P0_ENABLED`、共用靜態 token）**已經在後續階段整個移除**（[ADR 0006](docs/adr/0006-p1-auth-handoff.md) 由 [ADR 0016](docs/adr/0016-p4-rbac-and-audit-operations.md) 取代並在 P4-07 刪除相關程式碼），**不是**今天可以執行的路徑。從 P1 起，任何本機或 demo 路徑都一律走完整的 PostgreSQL 控制平面：使用者帳號密碼登入取得 JWT，節點以 Ed25519 challenge–response 向 Central 認證（見下方〈P1 認證與節點註冊〉）。今天最接近「明確禁止用於 production」的邊界，是 `Settings` 在 `CLIORA_ENVIRONMENT=production` 時，只要偵測到仍是開發預設的 `CLIORA_JWT_SECRET` 或 `CLIORA_TOKEN_PEPPER` 就直接拒絕啟動（`backend/tests/test_settings.py::test_development_secrets_fail_closed_in_production`）——這台專案本身仍是 pre-1.0（`daemon/VERSION` 為 `0.7.0`，backend／frontend 為 `0.1.0`），沒有對外客戶或正式維運紀錄可引用，請把它當作已經過大量自動化驗證、但尚未經正式維運驗證的系統。

---

## 最短本機成功路徑（Quick Start）

目前 repository tree 可執行的路徑如下。

### 先決條件

- Linux 與 tmux 3.4 以上
- Python 3.12.3 與 uv
- Go 1.26.5
- Node 22.14.0 與 npm 10
- Docker（用來跑本機 PostgreSQL 16）

用 `python --version`、`uv --version`、`go version`、`node --version`、`npm --version`、`tmux -V` 驗證。版本號來自 `.python-version`、`.go-version`、`.nvmrc`，CI 也讀同一份。

### 安裝與靜態檢查

```bash
make bootstrap
make check
```

`make check` 會跑格式檢查、lint/vet、型別檢查、單元測試、contract 測試、build，以及 traceability 與 Railway 邊界設定的靜態檢查（見 `Makefile`）。

### 啟動一個可以在瀏覽器操作的完整 demo

需要一個本機 PostgreSQL：

```bash
docker run -d --name cliora-pg -p 5432:5432 \
  -e POSTGRES_USER=cliora -e POSTGRES_PASSWORD=cliora -e POSTGRES_DB=cliora_test \
  postgres:16-alpine
```

開兩個終端機：

```bash
# 終端機 A：Central + 一個以 Fake CLI 充當 "claude" runtime 的真實 enrolled 節點（rootless）
make dev-stack
```

`make dev-stack` 會自己跑 migration、建立第一個管理員、啟動 Central、簽發 enrollment token 並用它註冊一個節點，等節點回報 online 後印出：

```
Stack ready at http://127.0.0.1:8000 (admin: e2e-admin / e2e-admin-pw).
```

（帳密可用環境變數 `E2E_ADMIN_USER` / `E2E_ADMIN_PASSWORD` 覆寫；細節見 `scripts/e2e/run-stack.sh`。）

```bash
# 終端機 B：前端開發伺服器
make dev-frontend
```

打開 `http://localhost:5173`，用終端機 A 印出的帳密登入，就會看到一個 online 的節點，可以建立 session、在瀏覽器打開終端機並輸入文字——這條路徑跑的是決定性的 Fake CLI，不是真正的 Claude/Codex（那是安裝到真實節點上的 `agentd` 才會啟動的 runtime，見〈架構概覽〉）。

只想做後端 API 開發、不需要完整節點，可以單獨跑 `make dev-central`（讀 `CLIORA_DATABASE_URL`，預設指向 `postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora`），但沒有 `dev-stack` 幫你做的 enrollment，節點需要另外走真實流程。

---

## 架構概覽

```
Browser (Vue 3 + xterm.js + Monaco)
   │  HTTPS / 認證過的 WebSocket
   ▼
FastAPI Central  ── 使用者認證(JWT) · 節點註冊表 · terminal relay · enrollment · RBAC · audit log
   │  outbound WSS（永遠由節點主動連出，Central 不主動連節點，FR-CONN-001）
   ▼
Go daemon "agentd"  ── 連線管理 · runtime 偵測(claude/codex) · tmux/PTY session 管理 · workspace 驗證
   │
   ▼
tmux session  ──  claude / codex（正式節點）或 deterministic Fake CLI（demo/測試）
```

Central 的節點註冊表與 terminal relay 是**單一行程內**的狀態（見 `app/services/registry.py`、`app/services/terminal_relay.py` 的 module docstring）：目前只能垂直擴充，多副本部署會讓節點連線各自散落在不同副本、彼此看不見對方（`docs/deployment.md` 開頭即說明，也是 §「部署」的第一個風險）。

### P1 認證與節點註冊（Ed25519）

- **瀏覽器使用者**：帳號密碼登入，密碼以 Argon2id 雜湊；換回 15 分鐘的 access JWT 與 14 天、可撤銷的 refresh token。瀏覽器無法在 WebSocket 握手時夾帶 header，也不能把長效 JWT 放進 query string，所以連 terminal WebSocket 前要先用有效的 access token 換一張**一次性、60 秒過期、綁定使用者與資源**的 ws-ticket（[ADR 0007](docs/adr/0007-p1-authentication.md)）。
- **節點（daemon）**：enrollment 時 daemon 用 OS CSPRNG 產生一組 **Ed25519** 金鑰對，只把公鑰送給 Central、私鑰以 `0600` 寫進本機的 `credentials.yaml`；Central 從不接觸私鑰。之後每次 WebSocket 連線，Central 送一個新的 32-byte nonce，daemon 對 domain-separated 的位元組簽章回傳，Central 用存好的公鑰驗證後才放行（[ADR 0008](docs/adr/0008-p1-node-credential-and-protocol.md)）。這是破壞性安全遷移：migration `0003` 撤銷了所有舊版共享密鑰憑證，既有節點必須重新 enroll。
- 一行安裝指令、`agentd` 生命週期指令（`install` / `uninstall` / `doctor` / `update` 等）與簽章驗證的細節在 [`deploy/README.md`](deploy/README.md)。

### tmux session 語意

- 每個 Cliora session 對應**恰好一個** tmux session，命名為 `cliora-<uuid>`（`daemon/internal/tmux/client.go`），與主機上其他 tmux session 用前綴隔開。
- 瀏覽器分頁關閉或網路中斷**只是分離（detach）連線**；只有使用者明確按下「停止」才會真的結束 tmux session（`Manager.Stop`，`daemon/internal/session/manager.go`）。
- 重新連線時，daemon 對同一個 tmux session 執行 `tmux attach-session -d`：`-d` 會把任何殘留的舊 attach client（例如上一輪 daemon 掛掉後留下的、還活著的 client）直接踢掉，讓新的附加不會被卡住（[ADR 0012](docs/adr/0012-p2-recovery-attach-model.md)，回歸測試見 `daemon/internal/session/recovery_test.go`）。
- 重新連線的畫面快照上限 2 MiB、超出只保留最新內容並標成截斷；使用者在瀏覽器裡往上捲動看到的歷史，來自 daemon 端 tmux 自己的 scrollback（`history-limit`），兩者是不同機制，不要混為一談（`research/prd.md` FR-TERM-004）。

### 瀏覽器端 token 刷新與已知的 race（refresh race）

多分頁同時使用、或者 access token 快過期時觸發並發刷新，曾經出現「舊分頁刷新失敗把新分頁剛換到的新 token 蓋掉」「已登出後，一個晚到的刷新成功又把 session 復活」兩類問題，已於 commit `b1053bd`（`fix(auth): stabilize refresh sessions across tabs`）修正並補上迴歸測試（`frontend/src/api/client.test.ts`、`frontend/src/stores/auth.test.ts`）：

- `ApiClient.refresh()`（`frontend/src/api/client.ts`）用單一 in-flight promise 把並發的 401 收斂成一次刷新請求；刷新成功時若目前存的 refresh token 已經被別的分頁換過，就丟棄這次「過期」的結果而不覆蓋，讓原本的請求改用新 token 重試；若目前已經是登出狀態（token 被清空），一個晚到的成功也不會把 session 復活。
- `installAuthStorageSync()`（`frontend/src/stores/auth.ts`）監聽 `storage` 事件，把其他分頁寫入 `localStorage` 的 token 變化鏡射進目前分頁的 Pinia state，並用遞增的 generation 計數器避免過期的非同步回應覆寫較新的狀態。

這條路徑已有針對性測試覆蓋，但屬於分散式狀態同步問題，**沒有形式化證明「不存在任何 race」**；改動這段邏輯時請先讀那兩個測試檔。

---

## 測試

| 指令 | 涵蓋範圍 | 需要什麼 |
|---|---|---|
| `make check` | format / lint / typecheck / 三語言單元測試 / contract / build / traceability 靜態檢查 / Railway 邊界設定檢查 | 無 tmux、無瀏覽器、無 DB |
| `make integration` | daemon 的 `-tags integration` 套件（session / connection / files / workspace / tunnel） | 需要 tmux |
| `make e2e` | Playwright 基本模式；只會啟動 Vite，未提供完整 Central／node 的案例會依前置條件 skip | 需要安裝瀏覽器；不等同 full-stack |
| `E2E_FULL_STACK=1 ./scripts/e2e/run-stack.sh bash -c 'cd frontend && npm run test:e2e'` | 先拉起真實 Central + enrolled node，再執行 session／file 等 full-stack 案例；CI P2 使用此模式 | PostgreSQL、tmux、瀏覽器及可用的本機埠 |
| `make test-db` | `backend/tests/db` 下的 DB-backed 認證/enrollment/node/status/audit 測試 | 需要已 migrate 的 PostgreSQL（`CLIORA_DATABASE_URL` 與 `CLIORA_TEST_DATABASE_URL`） |
| `make traceability` | 需求-測試追溯（[ADR 0019](docs/adr/0019-requirement-traceability.md)）：每條 PRD 驗收條件都要連到一個確實存在的斷言 | 無 |
| `make perf` | P2/P3 的延遲/退化量測，結果寫進 `artifacts/{p2,p3}/local/` | 需要 tmux |

CI 設定在 `.github/workflows/`。七個 workflow 目前都接受手動
`workflow_dispatch`，以及 `opened`、`reopened`、`synchronize`、
`ready_for_review` 四種 PR 事件；每個 job 另有 draft guard。因此建立或更新 Draft PR
不會執行 job，沒有對應 PR 事件的 branch push、以及 merge 到 `master` 也不會自行啟動
workflow；Draft 轉 Ready 會執行，而直接以非 Draft 開啟／重開 PR、或更新已 Ready 的
PR 也會依目前設定執行。
`ci.yml` 是三語言基礎 gate；`p1.yml`–`p4.yml` 疊加整合、DB、瀏覽器 E2E
與容量測試；`traceability.yml` 跑追溯驗證；`wt.yml` 覆蓋系統終端機。workflow
定義存在不等於某個 commit 已通過；請把實際 run 的 head SHA 與結果綁在一起判讀。

已知、寫在報告裡而非藏起來的落差（`docs/p4-report.md` §4）：完整規模的容量壓測（100 節點/500 連線）目前只能從 `release/*` 手動 dispatch `p4.yml`；workflow 條件也列了 `main`，但 repository 的 default 是 `master` 且沒有 `main` branch，因此從 default branch 手動執行仍只會跑 5 節點 smoke。其他可執行的 PR／手動 run 也只跑 smoke。五個告警演練裡有三個（`heartbeat-loss`、`timeout-surge`、`update-failure`）需要 systemd 與一個真實安裝的節點，在一般 sandbox/開發機上會被跳過而非算通過；多 OS/多瀏覽器引擎的安裝矩陣需要真正的 CI runner。這些都是「已實作、已審查，但不是每次都被自動執行」的項目，不是缺陷。

---

## 安全性

`docs/security-review-p4.md` 對照 15 條安全基準與一份攻擊手法清單逐項給證據（測試檔或演練產物），摘要如下——完整內容與每一條的證據連結請直接看該檔：

- **正式環境只認 HTTPS/WSS**，且 `Settings` 在偵測到開發預設密鑰時拒絕以 `production` 環境啟動。
- **daemon 服務程序預設以非 root 身分長駐**；但啟用「privileged node posture」時，服務帳號會取得 passwordless sudo，瀏覽器開啟的 system terminal 可透過其子程序提升到 root。這是明示的高權限模式，不是「daemon 永遠沒有提權路徑」（[ADR 0021](docs/adr/0021-system-terminal-and-shell-runtime.md)、[ADR 0023](docs/adr/0023-privileged-node-posture.md)）。
- **enrollment token 一次性或限時**，節點憑證用 Ed25519（見上）而非共享密鑰，私鑰永不進中央資料庫。
- **workspace 路徑在 Central 與 daemon 兩端各自重新驗證**，symlink 全部解析，前綴碰撞（如 `/a/projects-other` 誤判為 `/a/projects` 底下）已有回歸測試。
- **session-start 協定不能由前端指定 binary／argv／任意路徑**：Central 只送 allowlisted runtime ID，由 daemon 決定啟動命令。但一旦使用者開啟允許的 `shell` runtime，該互動式 shell 本身可以執行任意命令；若節點採 privileged posture，也可能透過 sudo 取得 root。這兩層邊界不可混為一談。
- **檔案寫入預設開啟**：image drop 與一般 file upload 預設為 enabled。一般上傳允許呼叫端指定 workspace 內的檔名，限制為每檔 4 MiB、每 session 256 MiB、每日 200 檔；repo 沒有自動 retention，且 in-memory counter 會在 `agentd` 重啟後歸零。部署者需把 workspace 視為持久資料邊界，必要時關閉功能或另訂清理政策（[ADR 0026](docs/adr/0026-general-file-upload.md)）。
- **終端機內容、檔案內容、搜尋關鍵字、密碼、token、私鑰都不寫進 log、audit table 或備份 dump**——這條有一支腳本專門去真的資料庫 dump 裡掃這些東西（`scripts/p4/backup-restore-drill.sh`）。
- **RBAC 是兩層**：角色可不可以做這件事（Admin/Developer/Viewer，見 `docs/permission-matrix.md`，此檔為程式碼自動產生）之外，還要檢查對這一個資源有沒有權限（例如 Developer 只能終止自己擁有的 session，除非是 Admin）。
- **系統終端機（system terminal）與提權姿態**：node 可以用 sudo 讓系統終端機取得 root，這件事必須在介面上明示，不能悄悄發生（`docs/adr/0023-privileged-node-posture.md`）；`codex` runtime 在 node 上預設關閉審批流程與沙箱（`sandbox_bypass` 缺省即視為啟用），這是給「可拋棄的隔離 VM」設計的姿態，不是通用預設，node 可以自行關閉且平台無法覆寫。

**已知的殘留限制**（不是待修的臭蟲，是寫下來的取捨，見 `docs/p4-report.md` §4）：TLS 只用自簽憑證測過，`ssl_stapling` 未被實際驗證過；Central 是 process-local 單一實例，無法水平擴充；`CLIORA_TOKEN_PEPPER` 輪替會讓所有 enrollment token 與節點憑證同時失效，必須視為一次性操作而非例行輪替（`docs/deployment.md`）。

---

## 部署

支援兩種目標拓樸，兩者共用同一批容器映像與安全設定，並用 `scripts/railway/check-edge-parity.sh` 防止兩份 edge 設定（CSP、安全標頭、body 上限、`/ws/` timeout）互相漂移：

- **單機 Docker Compose**：nginx 終止 TLS、一個 Central、一個 PostgreSQL。步驟、密鑰輪替代價、升級/回滾與備份程序見 [`docs/deployment.md`](docs/deployment.md)。
- **Railway**：Central 走內部私網、console 走公開網域，`agentd` 完全不受影響（仍在使用者自己的主機上、仍是它主動連出）。步驟、與 compose 拓樸的差異表見 [`docs/deployment-railway.md`](docs/deployment-railway.md)。

部署前務必知道的風險（都已寫進上述文件，這裡只點名）：

- **不能水平擴充**——見〈架構概覽〉，Central 的連線登記與 terminal relay 是行程內狀態。
- **兩個密鑰輪替代價不對稱**：輪替 `CLIORA_JWT_SECRET` 只是讓所有人重新登入；輪替 `CLIORA_TOKEN_PEPPER` 會讓**所有**節點都需要重新 enroll，是單向門而非例行操作。
- **migration 絕不在應用程式啟動時自動跑**（避免多副本各自搶著跑 migration），而是獨立的一次性步驟，`/readyz` 會在 schema 版本與程式碼不一致時回 503，讓還沒 migrate 的容器永遠拿不到流量。
- **關站有 drain**：收到 SIGTERM 後，Central 會先通知每個訂閱中的瀏覽器「即將重啟、session 會保留」、再關閉節點連線讓它們走既有的重連退避，全程不對任何節點送出真正的 `session.stop`——重啟不等於幫你關掉任何一個 CLI session。
- Go/No-Go 判斷本身列了尚待完成的條件（見 `docs/p4-report.md` §5）：針對真正的 `release/*` 分支手動 dispatch 完整 `p4.yml`（含全規模容量與三個瀏覽器引擎），並核對 run head SHA；正式環境的兩個密鑰都已換成真的；在第一次跑 retention prune 之前先做過一次備份還原演練；針對實際要用的 nginx 設定跑過 `scripts/p4/verify-edge.sh`。目前不可用 default `master` 取代 `release/*`，因為 full-capacity 條件誤寫成不存在的 `main`。這些是部署前的檢查清單項目，不是「已完成」的陳述。

---

## 文件索引

- **產品需求（願景，非全部已實作）**：[`research/prd.md`](research/prd.md)
- **技術規劃**：[`research/tech.md`](research/tech.md)
- **架構決策紀錄（ADR）**：[`docs/adr/`](docs/adr/)——按時間序記錄每個階段的取捨，含本 README 引用的 [0006](docs/adr/0006-p1-auth-handoff.md)、[0007](docs/adr/0007-p1-authentication.md)、[0008](docs/adr/0008-p1-node-credential-and-protocol.md)、[0012](docs/adr/0012-p2-recovery-attach-model.md)、[0023](docs/adr/0023-privileged-node-posture.md)
- **各階段執行計畫與實作狀態**：[`plan/`](plan/)（例如 [`plan/01`](plan/01/README.md) 是 P0、[`plan/02`](plan/02/README.md) 是 P1；較後期目錄多含 `NN-implementation-status.md`，早期目錄則以 README／報告記錄狀態）
- **Go/No-Go 報告**：[`docs/p0-report.md`](docs/p0-report.md) 到 [`docs/p4-report.md`](docs/p4-report.md)，以及後續功能波的 [`docs/wt-report.md`](docs/wt-report.md)（系統終端機）、[`docs/pg-report.md`](docs/pg-report.md)（埠轉發）、[`docs/ly-report.md`](docs/ly-report.md)（版面）
- **安全審查**：[`docs/security-review-p4.md`](docs/security-review-p4.md) 及各功能波各自的審查（`docs/security-review-p8.md`、`p11`、`p12`、`p13`、`p15`）
- **權限矩陣（程式碼自動產生）**：[`docs/permission-matrix.md`](docs/permission-matrix.md)
- **需求追溯報告**：[`docs/traceability-report.md`](docs/traceability-report.md)、明細見 [`docs/traceability/`](docs/traceability/)
- **通訊協定變更歷史**：[`contracts/CHANGELOG.md`](contracts/CHANGELOG.md)、schema 見 [`contracts/v1/`](contracts/v1/)
- **daemon 安裝與生命週期**：[`deploy/README.md`](deploy/README.md)
- **維運手冊（各類事故的處理步驟）**：[`docs/runbooks/`](docs/runbooks/)
- **錯誤碼對照**：[`docs/error-catalog.md`](docs/error-catalog.md)
