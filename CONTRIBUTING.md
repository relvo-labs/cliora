# 參與 Cliora 開發

先讀 [README](README.md) 了解目前能力與限制，再讀 [.agent/skills/README.md](.agent/skills/README.md)、[AUTHORING.md](.agent/skills/AUTHORING.md) 與 [cliora-project-context](.agent/skills/cliora-project-context/SKILL.md)。
產品需求以 [research/prd.md](research/prd.md) 為準，技術與視覺規格在 [research/tech.md](research/tech.md)、[research/style.md](research/style.md)；範圍變更先記錄決策，再同步 contract、consumer 與追溯資料。
P0–P4 報告是歷史證據；本文件的命令已對照 `master@aa732f0` 靜態核對，尚待本次改寫的執行驗證。

## Bootstrap

在 repository 根目錄操作，使用 Linux 一般使用者、Bash、Make、curl、tmux 3.4 以上與 Docker。
工具版本：Python 3.12.3、Go 1.26.5、Node 22.14.0、npm 10；uv 在 CI 固定為 0.11.31。
Python／Go／Node 的版本檔是 `.python-version`／`.go-version`／`.nvmrc`；P4 部分 jobs 改讀 `daemon/go.mod` 或只指定 Node 22，並非每個 job 都讀相同檔案。

```bash
python --version
uv --version
go version
node --version
npm --version
tmux -V
make bootstrap
```

`make bootstrap` 執行 locked `uv sync --project backend --locked`、`frontend/` 的 `npm ci`、`daemon/` 的 `go mod download`。
依賴變更要更新相應 lockfile；不要把本機套件或工具版本當成 CI 證據。

## 不需 DB 的 gates（依此順序）

所有 `make` 指令的 cwd 都是 **repository 根目錄**；Makefile 自己切換子目錄。
先清除測試 DB 變數，讓這一輪保持 hermetic；`backend/tests/db` 未設定測試 URL 時會 skip，不能因此宣稱 DB 測試已通過。

```bash
unset CLIORA_TEST_DATABASE_URL CLIORA_DATABASE_URL
make format-check
make lint
make typecheck
make unit
make contract
make build
make traceability-validate
make railway-parity
make railway-test
make railway-check
make layout-gates
make vr-gates
make check
make traceability-selectors
make traceability-coverage
make traceability-coverage-baseline
make traceability-test
make traceability
```

| Gate | Makefile 內部 cwd／內容 |
|---|---|
| `make format-check` | root：Ruff format；`daemon/`：gofmt；`frontend/`：Prettier。 |
| `make lint` | root：Ruff；`daemon/`：go vet；`frontend/`：ESLint。 |
| `make typecheck` | root：mypy `backend/app`；`frontend/`：vue-tsc。 |
| `make unit` | root：pytest `backend/tests`；`daemon/`：`go test -race ./...`；`frontend/`：Vitest。 |
| `make contract` | root：Python contract；`daemon/`：protocol Contract tests；`frontend/`：`src/protocol` tests，共用 `contracts/v1/` fixtures。 |
| `make build` | root：uv build；`daemon/`：agentd／fakecli；`frontend/`：vue-tsc + Vite。 |
| `make traceability-validate` | root：static validation、generated render `--check`。 |
| `make railway-parity` | root：兩份 edge 設定的 CSP、安全標頭、body 上限與 `/ws/` timeout parity。 |
| `make railway-test` | root：artifact baker／部署變數契約的正反測試。 |
| `make railway-check` | root：彙總 parity + railway-test。 |
| `make layout-gates` | root：版面高度來源、panel sizing、sidebar 與規格一致性；文字檢查，不做瀏覽器量測。 |
| `make vr-gates` | root：literal color、legacy token、glyph icon、theme contract；不代表視覺驗收。 |
| `make check` | 依 Makefile 順序彙總 format → lint → typecheck → unit → contract → build → traceability-validate → railway-check → layout-gates → vr-gates。 |
| `make traceability-selectors` | root：primary assertion selectors 可解析。 |
| `make traceability-coverage` | root：全部需求 strict coverage。 |
| `make traceability-coverage-baseline` | root：baseline-debt allowlist；目前為空，防止債務被悄悄加回。 |
| `make traceability-test` | root：追溯工具自身的 tests。 |
| `make traceability` | root：validate → selectors → coverage → baseline → tests；[ADR 0019](docs/adr/0019-requirement-traceability.md)。 |

個別 gates 便於歸因；彙總 gates 會重跑依賴。`make check` 不需 tmux、瀏覽器或 DB，但它不涵蓋所有 CI jobs。
CI 另有 npm audit、防 provider credential 外洩、mobile 文字 gates、Docker image／nginx 執行、整合與 browser matrix 等檢查，見 [ci.yml](.github/workflows/ci.yml)。

## 測試 DB、migration 與 backend

**不要使用正式或 demo DB**：DB fixtures 會清空 users、nodes、sessions、audit 等資料，migration downgrade 也會丟失資料。
先關閉 README demo。以下另開 PostgreSQL，`55433` 供測試、`cliora_test` 與 `cliora_e2e` 分開。
終端機 A 從 root 前景執行，等 DB ready：

```bash
docker run --rm --name cliora-test-pg -p 127.0.0.1:55433:5432 \
  -e POSTGRES_USER=cliora -e POSTGRES_PASSWORD=cliora \
  -e POSTGRES_DB=cliora_test postgres:16-alpine
```

終端機 B，cwd **root**：

```bash
docker exec cliora-test-pg pg_isready -U cliora -d cliora_test
export DB_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:55433/cliora_test
export CLIORA_DATABASE_URL="$DB_URL"
export CLIORA_TEST_DATABASE_URL="$DB_URL"
make migrate
ADMIN_USER=migration-rollback CLIORA_ADMIN_PASSWORD=local-test-pw make create-admin
```

`make migrate`／`make create-admin` 內部 cwd 為 `backend/`。admin bootstrap 可重複執行；密碼從 `CLIORA_ADMIN_PASSWORD` 讀取，`ADMIN_USER` 預設 `admin`。
接著驗證和 P4 相同的 rollback 路徑；以下 cwd 是 **backend/**，只在這個可丟棄 DB 執行：

```bash
uv run --project . alembic current
uv run --project . alembic downgrade 0007_seed_file_browse
uv run --project . alembic upgrade head
uv run --project . alembic downgrade base
uv run --project . alembic upgrade head
```

回到 **root** 執行 DB suite，再讓全部 backend tests 在 DB 模式下執行：

```bash
make test-db
uv run --project backend pytest backend/tests -q
```

`make test-db` 內部 cwd 是 `backend/`，同時設定 `CLIORA_DATABASE_URL` 與 `CLIORA_TEST_DATABASE_URL` 後執行 `pytest tests/db -q`。
兩個 URL 都必須指向已 migrate 的測試 DB；只設測試 URL 會讓應用程式的獨立 audit session 連錯資料庫，見 [追溯報告](docs/traceability-report.md)。
新增 migration 放在 `backend/app/db/migrations/versions/`；資料與 roles／permissions seed 都經 migration 管理。
應用 lifespan 不自動 migration；Compose 使用 one-shot migrate service，Railway 使用 pre-deploy command。
`/readyz` 在 DB 無法連線或 revision 不符 head 時回 503，部署順序是 migration → Central → ready → edge。
實際 downgrade 前讀該 revision 的 `downgrade()`，備份並確認會丟失的欄位／資料；維運入口見 [`deploy/migrate.sh`](deploy/migrate.sh)。

## Daemon integration 與效能

cwd **root**；需要可用的 tmux：

```bash
make integration
make perf
```

`make integration` 內部 cwd 是 `daemon/`，使用 `-tags integration` 與 race detector，涵蓋 session／connection／files／workspace／tunnel。
CI 的部分 daemon jobs 還會測 `internal/update` 或 `./...`；安裝矩陣需要真實 root、systemd、Ubuntu 22.04／24.04／Debian 12 與 amd64／arm64，見 [deploy/README.md](deploy/README.md)。
`make perf` 在 `backend/` 跑 relay／files harness，再於 `daemon/` 跑 filesystem latency；結果寫到 `artifacts/{p2,p3}/local/`。
這些量測不包含使用者到節點的整段網路 RTT；不要直接宣稱部署後的端到端延遲。
已知測試問題：[停止訊號 #89](https://github.com/relvo-labs/cliora/issues/89)、[分類延遲 #92](https://github.com/relvo-labs/cliora/issues/92)。需在本次環境重現，不預先判定會失敗。

## Frontend 與 E2E

Frontend 的 format／lint／typecheck／Vitest／build 已由前述 gates 執行；單獨調查時可在 `frontend/` 使用 [package.json](frontend/package.json) 的 scripts。
Playwright 安裝需要能安裝系統函式庫的環境。cwd **frontend/**：

```bash
npx playwright install --with-deps chromium firefox webkit
npm audit --audit-level=high
```

回到 **root**，先跑基本模式：

```bash
unset E2E_FULL_STACK
make e2e
```

`make e2e` 內部 cwd 是 `frontend/`，只由 Playwright 啟動 Vite；mocked cases 可執行，需真實登入／online node 的 cases 依前置條件 skip。
完整模式使用獨立 DB，啟動實際 Central、enrolled daemon、tmux 與 Fake CLI；Playwright 仍負責 Vite。cwd **root**：

```bash
docker exec cliora-test-pg createdb -U cliora cliora_e2e
export CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:55433/cliora_e2e
export CLIORA_TEST_DATABASE_URL="$CLIORA_DATABASE_URL"
E2E_FULL_STACK=1 ./scripts/e2e/run-stack.sh bash -c 'cd frontend && npm run test:e2e'
```

使用 fresh container 時只需建立 `cliora_e2e` 一次；重跑前確認舊 stack 已停止、測試 session 已清理。
保留通過／失敗／skip 數與各 project 結果。config 含 chromium、firefox、webkit，以及 mobile-chrome-emulated／mobile-safari-emulated；手機模擬不算實機鍵盤、safe area 或 IME 驗收。
圖片／PDF tests 有自己的 capability／rollout 前置條件，不能以 skip 當成預覽已驗證。
E2E 已知落差見 [#116](https://github.com/relvo-labs/cliora/issues/116)、[#117](https://github.com/relvo-labs/cliora/issues/117)；本機 Chromium 成功不能替其他引擎背書。
結束後確認 stack 子行程、daemon 專用 tmux sessions 已清理，再對 DB 終端機 A 按 Ctrl-C；`--rm` 刪除專用容器與其匿名資料 volume。

## 開發啟動與設定

- 完整互動 demo：root 的 `make dev-stack` + `make dev-frontend`，見 [README 本機試用](README.md#本機試用)。
- API-only：root 的 `make dev-central`，**不會** migration、bootstrap 或 enrollment；先準備 DB 與 admin。它讀 `CLIORA_DATABASE_URL`，`Settings` 預設是 `postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora`。
- `make dev-stack` 會以 `DB_URL` 設定 `CLIORA_DATABASE_URL`；Makefile 的 `DB_URL` 預設是同埠的 `cliora_test`，與 Settings 不同。不要只覆寫前者沒讀到的變數。
- Central 設定由 [`backend/app/settings.py`](backend/app/settings.py) 的 `CLIORA_` 環境變數讀取；`CLIORA_ENVIRONMENT=production` 要自有 `CLIORA_JWT_SECRET`／`CLIORA_TOKEN_PEPPER`，開發預設會拒絕啟動，回歸見 `backend/tests/test_settings.py::test_development_secrets_fail_closed_in_production`。
- daemon 設定是節點的 `/etc/agentd/config.yaml`／`credentials.yaml`（`0600`）；allowed roots、runtime、上傳／下載／預覽與 posture 都由節點決定。
- Vite 以 `CLIORA_DEV_PROXY_TARGET` 設定 server-side `/api`／`/ws` proxy；不要把它改成 client bundle 的 `VITE_API_BASE_URL`。`CENTRAL_PORT` 改變時同步調整 proxy；E2E 目前固定連 8000／5173。
- `E2E_ADMIN_USER`／`E2E_ADMIN_PASSWORD` 控制 demo 帳密；`CLIORA_ADMIN_PASSWORD` 與登入密碼要一致。`E2E_TUNNEL_APP_PORT` 預設 5199。
- 只想更新產生的追溯文件時用 root 的 `make traceability-render`；它會寫檔，之後須重新檢查。產生的 error catalog／permission matrix 從 source renderer 更新，不能手改；目前矩陣缺漏見 [#87](https://github.com/relvo-labs/cliora/issues/87)。

## 信任邊界與回歸入口

- Browser 只送 allowlisted runtime ID，`session.start` 沒有 binary／argv／env；daemon 決定 launch。互動式 `shell` 可執行任意命令，且不受 workspace root 限制；不要把協定 allowlist 誤寫成 shell 的命令限制。
- `agentd` 長駐非 root；privileged posture 會給服務帳號 passwordless sudo，使 system terminal 子行程能到 root。`codex` 預設啟用固定的 sandbox／approvals bypass；node 可關閉，平台不能覆寫，見 [ADR 0023](docs/adr/0023-privileged-node-posture.md)。
- [ADR 0007](docs/adr/0007-p1-authentication.md)：Argon2id、15 分鐘 access JWT、14 天可撤銷 refresh token、一次性 60 秒 ws-ticket。瀏覽器原生 WebSocket 握手不能自訂 header，也不應將長效 JWT 放入 query。票綁定 user／resource，不等於已完成資源授權，consumer 必須重新檢查。
- [ADR 0008](docs/adr/0008-p1-node-credential-and-protocol.md)：OS CSPRNG 產生 Ed25519 keypair，私鑰 `0600`，Central 驗證新的 32-byte nonce 與 domain-separated 簽章；migration `0003` 撤銷舊共享密鑰憑證，舊節點須重新 enroll。
- RBAC 同時檢查角色與 resource scope，UI 隱藏不能代替 server guard；Developer 可查看／接管同事的 CLI session，但不能終止非本人 session，Admin 可管理，Viewer 不持有 mutation actions。
- workspace 每次操作在 Central 驗證邊界、daemon 重新解析與 confined open；`/a/projects-other` 不可視為 `/a/projects` 子目錄。回歸在 `daemon/internal/workspace/`；Central 不掛載節點檔案系統。
- image drop 與 file upload 都要 confined、bounded、audited、可由節點拒絕。一般 upload 不覆寫、不建目錄、固定 `0644`，需通過敏感檔名／位置政策；無自動 retention。image drop 使用平台命名目錄，預設在後續 session 啟動時清理超過 7 天的圖片。
- terminal／file content、密碼、token、私鑰不應進服務 log、audit 或備份；[`scripts/p4/backup-restore-drill.sh`](scripts/p4/backup-restore-drill.sh) 掃實際 DB dump，但不證明所有 access log／edge 暫存都安全，見 [#84](https://github.com/relvo-labs/cliora/issues/84)、[#85](https://github.com/relvo-labs/cliora/issues/85)。
- CLI session 的 `Manager.Stop` 在 `daemon/internal/session/manager.go`；daemon 重連使用 `daemon/internal/tmux/client.go` 的 `-d` eviction；`daemon/internal/session/recovery_test.go` 測 orphan／rapid reattach。runtime 自行退出、admin 停用並終止或刪除 node 也可結束 session，不能宣稱只有「停止」按鈕才會結束。
- 跨分頁 refresh 修正在 `b1053bd`（`fix(auth): stabilize refresh sessions across tabs`）：`ApiClient.refresh()` 以單一 in-flight promise 合併刷新，丟棄過時結果、以新 token 重試原請求；晚到的成功不覆蓋較新的 token 或復活已登出的 session。`installAuthStorageSync()` 以 `storage` 事件同步 `localStorage`，generation 防止過期非同步回應覆寫。讀 [`frontend/src/api/client.ts`](frontend/src/api/client.ts)、[`frontend/src/stores/auth.ts`](frontend/src/stores/auth.ts) 與 [client tests](frontend/src/api/client.test.ts)／[auth tests](frontend/src/stores/auth.test.ts)。已有回歸測試，沒有形式化「零 race」證明。
- P0 的 `/ws/p0/*`、`CLIORA_P0_ENABLED` 與共用靜態 token 已於 P4-07 移除，舊變數不會啟用任何 relay；[ADR 0006](docs/adr/0006-p1-auth-handoff.md) 由 [ADR 0016](docs/adr/0016-p4-rbac-and-audit-operations.md) 取代。
- 功能波安全審查另見 [p8](docs/security-review-p8.md)、[p11](docs/security-review-p11.md)、[p12](docs/security-review-p12.md)、[p13](docs/security-review-p13.md)、[p15](docs/security-review-p15.md)；它們是具名歷史審查，仍須對照目前 open issues。

## 部署、release 與 CI／PR

變更由工作分支提交 PR，base 使用 **`master`**。PR 說明列問題與結果、測試命令／cwd／結果、skip 前提、實際 run URL 與 head SHA；不要以 workflow 定義或舊報告代替本次驗證。
本次 README 改寫追蹤 [#141](https://github.com/relvo-labs/cliora/issues/141)，與 Draft [#69](https://github.com/relvo-labs/cliora/pull/69) 的 README trigger 說明重疊；該 PR 其他部署／release 文件不在這次改寫範圍。

七個 workflows 在 [`.github/workflows/`](.github/workflows/)：`ci.yml` 基礎 gates；`p1.yml`–`p4.yml` 整合／DB／瀏覽器／容量；`traceability.yml` 需求追溯；`wt.yml` 系統終端機。
它們接受 `workflow_dispatch` 與 PR 的 `opened`、`reopened`、`synchronize`、`ready_for_review`；每個 job 有 draft guard。
建立／更新 Draft PR 的 jobs 會 skip，手動 dispatch 可以執行 Draft 分支；轉 Ready、直接開啟／重開非 Draft PR、更新 Ready PR 都會執行符合條件的 jobs。
普通 branch push、merge 到 `master`、tag push 都沒有 push trigger；不可期待它們自動驗證。traceability impact job 只在 PR 事件執行，P1 release job 另外要求 `refs/tags/v*`。
手動 dispatch 的操作交由有權限的維護者；dispatch 接受不等於完成或成功，read-back 要核對 event、ref、head SHA、每個 job 與 artifacts。

P4 capacity 每次可執行的 run 都跑 5 nodes／10 sockets smoke；100 nodes／500 sockets full 另要求 `refs/heads/main` 或 `refs/heads/release/*`。
repo default 是 `master`，目前沒有 `main`，所以從 `master` 手動 dispatch 不會測 full；完整 release gate 需在精確 `release/*` ref dispatch 並核對 SHA，見 [p4.yml](.github/workflows/p4.yml)。
`heartbeat-loss`／`timeout-surge`／`update-failure` 演練各有 systemd、已連線節點或 release artifact 前提；缺少時記錄 skip。OS install matrix 與實機 browser 驗收是另外的環境要求。

部署指引：[單機 Compose](docs/deployment.md)、[Railway](docs/deployment-railway.md)、[daemon 安裝](deploy/README.md)、[runbooks](docs/runbooks/)。兩種拓樸共用 Central／console 的來源與安全政策，Railway console 另有專用 Dockerfile／edge template；`scripts/railway/check-edge-parity.sh` 只核對已列出的設定，不證明線上部署成功。
節點生命週期使用 `agentd` 的 `install`／`uninstall`／`doctor`／`update` 等子命令；一行安裝與 checksum 驗證的步驟留在 daemon 安裝文件。
子文件仍有 push-based CI、`main` 與 pepper 輪替的舊描述；本文件以目前程式與 workflow 為準，相關文件更新由 #69／後續工作處理。

- `CLIORA_JWT_SECRET` 輪替使以舊 key 簽署的 access／refresh JWT 失效，使用者需重新登入。
- `CLIORA_TOKEN_PEPPER` 目前用在 enrollment token 的 HMAC；輪替使既有 enrollment token 無法驗證。Ed25519 節點身分不依賴 pepper，不能沿用「所有 enrolled nodes 都要重 enroll」的舊說法。
- SIGTERM drain 通知 `terminal.server_shutdown`、關閉節點連線並讓它們重連；不送 `session.stop`，不結束 tmux CLI。保留適當 stop grace period，見 `backend/tests/test_shutdown_drain.py`。
- 正式部署需 HTTPS/WSS、自有密鑰、可用 artifacts、備份還原與 retention prune 前備份；TLS 測試用自簽憑證，`ssl_stapling` 需在實際 edge 驗證。release checklist 的條件要逐項以當次證據完成。
- [`scripts/p4/verify-edge.sh`](scripts/p4/verify-edge.sh) 執行真實 edge assertions；部署／容量／告警的環境與命令見 [release checklist](docs/release-checklist.md)。

Artifact 維護者另需 GoReleaser。`make release-snapshot` 在 `daemon/` 產出不需 tag 的本機 tarballs／checksums；`make release` 要 HEAD 的 `v*` tag **完全符合** `daemon/VERSION`，輸出 `daemon/dist/`。
`daemon/.goreleaser.yaml` 設定 `release.disable: true`，這兩個 target 不發布 GitHub Release；P1 的 release job 需手動 dispatch 至 version tag，產物是 Actions artifact。
Central 容器預設在 build 時編譯 amd64／arm64 agentd；下載／更新只做 SHA256 checksum 驗證，不能宣稱存在獨立的 release signing。
daemon 改動要核對 `daemon/VERSION` 與 fallback version；未遞增版本而重建映像會讓 fleet 無法辨識新 binary，見 [Railway 部署](docs/deployment-railway.md)。

目前失敗與待處理項目以 [open issues](https://github.com/relvo-labs/cliora/issues) 為準；同一 gate 在未修改 base 也失敗時，保留兩份結果並引用既有 issue，未覆蓋的問題交由維護者另立 issue，不悄悄放寬 gate。
