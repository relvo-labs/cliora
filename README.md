# Cliora

Cliora 是自架的 CLI coding-agent 管理平台，讓你從瀏覽器或手機操作自己 Linux 節點上的 Claude／Codex session，並集中管理節點、權限與稽核。

> [!IMPORTANT]
> 目前仍是 **pre-1.0**：[`daemon/VERSION`](daemon/VERSION) 為 `0.7.0`，backend／frontend 為 `0.1.0`。
> 下方 demo 的 **Fake CLI runtime** 代替 Claude；Central、PostgreSQL、enrollment、daemon 與 tmux 都走實際路徑。
> demo 的隧道 provider 也是假替身，顯示的 `.example.invalid` URL 不可開啟。
> 截至 2026-10-06，最近一組 PR Actions 的 [CI](https://github.com/relvo-labs/cliora/actions/runs/37484315813)、[P1](https://github.com/relvo-labs/cliora/actions/runs/37484315820)、[P2](https://github.com/relvo-labs/cliora/actions/runs/37484315846)、[P3](https://github.com/relvo-labs/cliora/actions/runs/37484315834)、[P4](https://github.com/relvo-labs/cliora/actions/runs/37484315769)、[WT](https://github.com/relvo-labs/cliora/actions/runs/37484315716) 皆失敗，只有 [Requirement Traceability](https://github.com/relvo-labs/cliora/actions/runs/37484315712) 成功。
> 這組 run 的 head 是 `c59410b`；本 README 核對的 `master@aa732f0` 沒有對應 run，不能宣稱該版本已通過 CI。
> CI 的 frontend job 停在 npm audit；依賴問題見 [#99](https://github.com/relvo-labs/cliora/issues/99)，瀏覽器驗證缺口見 [#117](https://github.com/relvo-labs/cliora/issues/117)。

## 可以做什麼

| 操作面 | 目前入口與能力 |
|---|---|
| 瀏覽器工作區 | 建立、重連、終止 CLI session；xterm.js 接收原始 PTY 輸出，採單一 writer 與唯讀 viewer，可要求接管。 |
| 檔案面板 | 檔案樹、檔名搜尋、唯讀 Monaco 文字預覽、圖片投放、一般檔案上傳及下載；圖片／PDF 預覽另需啟用 rollout。 |
| 手機 | 響應式 session 清單、terminal／files 切換與安全輸入控制；Playwright 有手機模擬專案，仍需實機驗收。 |
| Nodes／daemon | 查看 online／degraded／offline／disabled 與 runtime 狀態；enrollment、憑證撤銷、`agentd` 安裝、診斷與更新。 |
| 管理介面 | Dashboard、Admin／Developer／Viewer RBAC、workspace 收藏與最近使用、audit 查詢與整合設定；首位管理員由 bootstrap 建立。 |
| 系統終端機 | 在 CLI session 旁開啟 `shell` runtime；有獨立的 owner／權限與閒置終止規則，可由節點關閉。 |
| 埠轉發 | 整合 Pinggy，由節點的 SSH 子行程對外連線；開發中應用程式的流量經 provider，不經 Central。 |
| 本機開發工具 | `Makefile` 管理三語言檢查；Fake CLI、enroll-dev 與隧道替身供 demo／E2E 使用。 |

平台承載原生 CLI 互動，不解析 agent 對話、不建立中央審批或任務分派，也不自動化 Git 操作。
預覽保持唯讀；瀏覽器只能新增上傳的檔案，編輯、改名、刪除交給 CLI 或 terminal。
Claude／Codex 的安裝與帳號由節點使用者準備；demo 不需要真實 agent 帳號。

## 架構

```text
Browser / Mobile（Vue 3、xterm.js、Monaco）
       │ HTTPS / 認證 WebSocket
       ▼
FastAPI Central ── PostgreSQL（帳號、node/session metadata、RBAC、audit）
       ▲
       │ outbound WSS：由節點主動連出；Central 不 SSH 進節點
       │
Go daemon agentd ── runtime 偵測、workspace 驗證、PTY、session 管理
       │
       ▼
daemon 專用 tmux ── claude / codex / shell（demo：Fake CLI）

節點上的開發應用程式 ── SSH tunnel ── Pinggy ── 外部瀏覽器
```

Central 的 [connection registry](backend/app/services/registry.py) 與 [terminal relay](backend/app/services/terminal_relay.py) 都是 **process-local**，多副本無法共享連線，目前採單一行程／單一副本。
瀏覽器登入使用 Argon2id 密碼驗證與 JWT；terminal WebSocket 使用一次性 ws-ticket。
節點以 Ed25519 challenge–response 認證，Central 只持有公鑰；私鑰留在節點。
詳細邊界見 [認證 ADR](docs/adr/0007-p1-authentication.md)、[節點憑證 ADR](docs/adr/0008-p1-node-credential-and-protocol.md) 與 [部署說明](docs/deployment.md)。

每個登記的 CLI session 對應 `cliora-<uuid>` tmux session；關閉分頁只會 detach，runtime 自行退出或明確終止才會結束它。
Cliora 不收編任意既有 tmux／CLI process。重連使用 `tmux attach-session -d`，並傳送最多 2 MiB 的快照；超出只保留最新內容並標示截斷。
快照與 tmux 的 `history-limit` scrollback 是不同機制，見 [重連 ADR](docs/adr/0012-p2-recovery-attach-model.md)。

## 本機試用

這條路徑啟動一個 rootless enrolled 節點，以 Fake CLI 演示 terminal；使用專用、可丟棄的 DB。
本次文件改寫僅完成靜態核對，以下步驟仍待執行驗證。

### 先決條件

- Linux、Bash、GNU Make、curl、Python 3；以一般使用者啟動 daemon。
- tmux 3.4 以上、Python 3.12.3 與 uv、Go 1.26.5、Node 22.14.0 與 npm 10。
- Docker 可啟動 PostgreSQL 16；本機 `55432`、`8000`、`5173`、`5199` 埠可用。

版本來源為 [`.python-version`](.python-version)、[`.go-version`](.go-version)、[`.nvmrc`](.nvmrc)；CI 的部分 P4 jobs 使用 Go module／Node major，詳見 [CONTRIBUTING](CONTRIBUTING.md)。
下列指令從 repository 根目錄執行；三個終端機都先切到同一目錄。

```bash
make bootstrap
```

### 1. 終端機 A：專用 PostgreSQL

前景執行，停止後自動刪除容器；這組帳密只用於本機 demo。

```bash
docker run --rm --name cliora-demo-pg -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=cliora -e POSTGRES_PASSWORD=cliora \
  -e POSTGRES_DB=cliora_demo postgres:16-alpine
```

### 2. 終端機 B：Central + enrolled daemon

先確認 DB 可連線，再啟動 stack：

```bash
docker exec cliora-demo-pg pg_isready -U cliora -d cliora_demo
make dev-stack DB_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:55432/cliora_demo
```

若 DB 尚未 ready，等 PostgreSQL 印出可接受連線訊息後重試 `pg_isready`。
stack 會 migration、建立 admin、簽發 enrollment token、註冊 `e2e-node`，等它 online 後印出：

```text
Stack ready at http://127.0.0.1:8000 (admin: e2e-admin / e2e-admin-pw).
```

帳密可由 `E2E_ADMIN_USER`／`E2E_ADMIN_PASSWORD` 覆寫；若設定 `CLIORA_ADMIN_PASSWORD`，須與登入密碼一致。
完整腳本見 [`scripts/e2e/run-stack.sh`](scripts/e2e/run-stack.sh)。

### 3. 終端機 C：確認健康並開啟前端

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
make dev-frontend
```

`/healthz` 應回傳 `{"status":"ok"}`；`/readyz` 應為 HTTP 200，且 DB 與 migration 檢查成功。
若 `/readyz` 是 503，先看回應中的檢查結果與 stack 終端輸出，不要只以程序仍在執行判定成功。

### 4. 瀏覽器中的成功訊號

1. 開啟 [http://localhost:5173](http://localhost:5173)，用 `e2e-admin`／`e2e-admin-pw` 登入。
2. 在 Nodes 看見 `e2e-node` 為 online；建立 session，選 `claude` 與 stack 印出的 workspace root。
3. 開啟 CLI，看到 `FAKECLI_READY`；輸入 `:unicode`，應看到 `中文 café 🚀`。
4. 重新整理後連回同一個 session；在檔案面板開啟 `src/main.py`，應看到 `E2E_PREVIEW_MARKER`。

這證明的是 demo 的登入、enrollment、terminal 與文字預覽路徑；真實 agent、真實 provider、TLS 部署與實機手機驗收另見下表。

### 清理

先在 UI 終止本次建立的 CLI sessions（其子 shell 也會終止），再對終端機 C、B、A 依序按 Ctrl-C。
stack 清理自己的程序群與暫存 workspace，PostgreSQL 的 `--rm` 容器停止後刪除；試用資料不保留。
不要對其他 tmux sessions 或既有 DB 執行清理。開發、測試與 API-only 啟動見 [CONTRIBUTING](CONTRIBUTING.md)。

## 成熟度與限制

| 範圍 | 目前邊界 | 證據／追蹤 |
|---|---|---|
| 版本與交付 | pre-1.0；P0–P4 是歷史階段，報告的 Go 有條件，不代表目前 CI 全綠。 | [版本](daemon/VERSION)、[P4 報告](docs/p4-report.md)、[Actions](https://github.com/relvo-labs/cliora/actions) |
| Demo | agent runtime 與 tunnel provider 使用替身；system shell 仍是節點上的實際 shell。 | [stack](scripts/e2e/run-stack.sh) |
| Session | 只重連 Cliora 登記的 session；接管後前端角色更新仍有已知問題。 | [重連 ADR](docs/adr/0012-p2-recovery-attach-model.md)、[#133](https://github.com/relvo-labs/cliora/issues/133) |
| Central 容量 | 單副本；P4 full 為 100 nodes／500 sockets，PR 與 `master` dispatch 只跑 5-node smoke。full 條件仍寫 `main`／`release/*`，目前沒有 `main`。 | [workflow](.github/workflows/p4.yml)、[重疊文件 PR #69](https://github.com/relvo-labs/cliora/pull/69) |
| 手機與瀏覽器 | 模擬專案不能代替 iOS Safari／Android Chrome、鍵盤、IME 與輔助技術實機測試。 | [mobile 狀態](plan/29/09-implementation-status.md)、[#82](https://github.com/relvo-labs/cliora/issues/82)、[#117](https://github.com/relvo-labs/cliora/issues/117) |
| Workspace 寫入 | image drop 與 file upload 預設開啟且可由節點拒絕；一般 upload 上限 4 MiB／檔、256 MiB／session、200 檔／日，不覆寫。一般檔案無 retention，counter 在 daemon 重啟歸零；image drop 預設在後續 session 啟動時清理超過 7 天的圖片。 | [寫入 ADR](docs/adr/0024-workspace-write-posture.md)、[upload ADR](docs/adr/0026-general-file-upload.md) |
| 圖片／PDF 預覽 | 程式已存在；Central rollout 預設關閉，需 edge 驗證與節點 live capability；Viewer 可唯讀預覽，但不因此取得下載權限。 | [ADR 0029](docs/adr/0029-read-only-binary-preview.md)、[設定](backend/app/settings.py) |
| 系統終端機／Codex | shell 不受 workspace root 限制；privileged posture 可用 sudo 到 root。Codex 的 `sandbox_bypass` 缺省開啟，設計對象是可拋棄的隔離 VM；只有節點能選擇姿態。 | [shell ADR](docs/adr/0021-system-terminal-and-shell-runtime.md)、[posture ADR](docs/adr/0023-privileged-node-posture.md) |
| 埠轉發 | provider 故障即不可用；流量不經平台，無 preview 存取 log／內容政策；免費 hostname 可能揭露節點公網 IP。 | [PG 報告](docs/pg-report.md)、[release note](docs/release-note-tunnel.md) |
| 安全性 | HTTPS/WSS 與 production 預設密鑰拒絕已配置；仍有跨節點訊息授權、ws-ticket 清理及 rate limiting 的 open issues。 | [安全審查](docs/security-review-p4.md)、[#47](https://github.com/relvo-labs/cliora/issues/47)、[#56](https://github.com/relvo-labs/cliora/issues/56)、[#57](https://github.com/relvo-labs/cliora/issues/57)、[#58](https://github.com/relvo-labs/cliora/issues/58)、[#59](https://github.com/relvo-labs/cliora/issues/59) |
| 隱私與權限文件 | terminal 不設內容錄影；文字路徑／搜尋 query 的 access log 與 edge 暫存仍有追蹤項，不能宣稱所有 sink 絕不落地；產生的權限表也有漏列。 | [#84](https://github.com/relvo-labs/cliora/issues/84)、[#85](https://github.com/relvo-labs/cliora/issues/85)、[#87](https://github.com/relvo-labs/cliora/issues/87) |
| 維運驗證 | 自簽 TLS 測試不證明 `ssl_stapling`；systemd 安裝矩陣與部分告警演練需真實節點。skip 要另外記錄。 | [P4 gaps](docs/p4-report.md)、[release checklist](docs/release-checklist.md) |

## 依讀者找文件

| 讀者 | 先讀 | 接著看 |
|---|---|---|
| 評估者 | [產品需求](research/prd.md)（願景與非目標） | [P0](docs/p0-report.md)、[P1](docs/p1-report.md)、[P2](docs/p2-report.md)、[P3](docs/p3-report.md)、[P4](docs/p4-report.md) 歷史報告；[WT](docs/wt-report.md)、[PG](docs/pg-report.md)、[LY](docs/ly-report.md) 功能報告 |
| 維運／部署者 | [單機 Compose](docs/deployment.md)、[Railway](docs/deployment-railway.md) | [daemon 安裝與生命週期](deploy/README.md)、[runbooks](docs/runbooks/)、[release checklist](docs/release-checklist.md)；CI 觸發以 [CONTRIBUTING](CONTRIBUTING.md) 為準 |
| 貢獻者 | [CONTRIBUTING](CONTRIBUTING.md) | [技術規劃](research/tech.md)、[plan](plan/)（[P0](plan/01/README.md)、[P1](plan/02/README.md)）、[追溯報告](docs/traceability-report.md) 與 [明細](docs/traceability/) |
| 整合／安全審查者 | [ADR](docs/adr/)、[協定變更](contracts/CHANGELOG.md)、[v1 schemas／fixtures](contracts/v1/) | [權限矩陣](docs/permission-matrix.md)（已知缺漏見 #87）、[錯誤碼](docs/error-catalog.md)、[安全審查](docs/security-review-p4.md) 與 [CONTRIBUTING 的信任邊界](CONTRIBUTING.md#信任邊界與回歸入口) |

## Repository 結構

```text
backend/       FastAPI Central、Alembic migrations、Python tests、perf harness
frontend/      Vue console、xterm／Monaco／PDF.js、Vitest 與 Playwright
daemon/        Go agentd、tmux／PTY、workspace、installer／updater、測試替身
contracts/     三語言共用的 protocol v1 schemas 與 fixtures
deploy/        Compose、nginx、Railway、安裝／migration 入口
scripts/       E2E stack、各項 gates、traceability 與維運演練
docs/          ADR、功能／安全報告、runbooks、產生的追溯文件
research/      PRD、技術與視覺規格
plan/          各波執行計畫；後期多以 NN-implementation-status.md 記錄狀態
.agent/skills/ 專案規範與工作方法
```
