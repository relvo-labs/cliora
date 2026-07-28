# Cliora Railway 部署可實作規劃

本目錄把「把 Cliora 部到 Railway 上」從一個平台操作，變成一組可審查、可驗證、可回復的工程 ticket。它**不新增產品功能**，也不改 protocol、RBAC 或安全 policy；ticket 統一使用 `RW-` 前綴。

## 為何需要這一期

`deploy/compose/` 已經是一份完整、註解詳盡的單機部署，`docs/deployment.md` 也把 migration 順序、drain、rollback 寫清楚了。但那份拓撲的每一個關鍵性質都由 **compose + nginx + 本機檔案系統**提供，而 Railway 三者都不給：

| 現行拓撲依賴什麼 | Railway 上發生什麼 |
|---|---|
| `stop_grace_period: 30s` 保護 15 秒 drain | Railway 的 `drainingSeconds` **預設 0**，SIGTERM 之後立刻 SIGKILL。drain 不會跑完，每次部署都給瀏覽器一次「無理由斷線」——正是 drain 存在的目的 |
| `depends_on: migrate: service_completed_successfully` | 沒有 compose 依賴圖。migration 必須改用 `preDeployCommand`（失敗會擋住部署，這點可用） |
| healthcheck 讀 `/readyz` 的 **JSON body** 判斷 ready | Railway 只看 **HTTP 狀態碼**，而 `/readyz` 在 degraded 時仍回 200。照抄設定等於沒有 readiness gate |
| nginx 在同一 bridge network 上 `server backend:8000` | 私網是 IPv6、名稱是 `*.railway.internal`，且**每次部署 IP 會變**。uvicorn 綁 `0.0.0.0` 在私網上完全不通；nginx 用靜態 upstream 會把第一次解析的 IP 快取到下次重啟 |
| TLS 憑證檔案掛進 nginx（`CLIORA_TLS_DIR`） | TLS 在 Railway edge 終結，容器只看得到 HTTP。443 server block 起不來 |
| `CLIORA_ARTIFACTS_DIR` 指向 host 目錄 | 容器檔案系統是暫時性的。release manifest 與 `/api/downloads` 讀本地檔，因此 artifacts 必須落在 volume——而掛 volume 就換來「每次部署有停機」 |
| 一份 `.env` 就是全部設定 | 變數散在服務、環境與 reference variable 之間；`DATABASE_URL` 是 `postgresql://`，但 `Settings` 要 `postgresql+asyncpg://` |

還有一項與功能正確性直接相關：`frontend/src/composables/useTerminalSession.ts:85` 的 terminal WebSocket 是用 `location.host` 組出來的，**不吃 `VITE_API_BASE_URL`**。也就是說「前端一個網域、後端另一個網域」的直覺做法會讓 API 通、終端機全滅。single-origin 不是偏好，是現有程式的前提。

這一期要交付的就是：把上面每一項都變成明確決定、可執行設定與可跑的驗證，而不是上線後靠事故發現。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍、固定基線決策表、目標拓撲、ticket 波次與共同 DoD |
| [01-platform-constraints-and-decisions.md](./01-platform-constraints-and-decisions.md) | RW-01/02：Railway 平台事實、三個拓撲方案與取捨、requirement 影響矩陣、ADR 0020 應記錄什麼 |
| [02-central-service-and-database.md](./02-central-service-and-database.md) | RW-03/04：Central 服務（PORT、IPv6 binding、start command、drain、readiness 語意修正）、Postgres、連線池、preDeploy migration |
| [03-edge-console-and-single-origin.md](./03-edge-console-and-single-origin.md) | RW-05/07：console/edge 服務、私網 upstream 與 resolver、header/CSP 平移與防漂移、自訂網域與 `CLIORA_PUBLIC_BASE_URL` |
| [04-artifacts-secrets-and-operations.md](./04-artifacts-secrets-and-operations.md) | RW-06/08/09：變數與 secret 契約、artifacts volume 與發佈、第一位 Admin、retention、備份、監控 |
| [05-verification-and-exit.md](./05-verification-and-exit.md) | RW-10/11/12：黑箱 edge 驗證腳本、真實 node 端到端與 NFR 量測、CI/CD、rollback 演練、traceability 掛載與退出條件 |
| [06-implementation-status.md](./06-implementation-status.md) | RW ticket 實作狀態與實際證據；目前均未開工，並列出必須在平台上實測才能確認的項目 |

## 使用規則

1. **先做 RW-01。** 拓撲（single-origin 的實現方式）、region、artifacts 存放位置、`CLIORA_PUBLIC_BASE_URL` 這四項一旦有 node 完成 enrollment 就難以更改，其中 pepper 與 public base URL 幾乎是一次性決定。
2. **不為了配合平台而放寬安全性質。** HTTPS/WSS、CSP 無外部來源、`/api/metrics` 不對外、非 root 容器、image 不含 secret——這些在 Railway 上一樣成立，做不到就記 waiver，不悄悄降級。
3. **平台聲明不算證據。** 「Railway 會終結 TLS」「WebSocket 不受 idle timeout 限制」都要由 `scripts/railway/verify-deployment.sh` 對真實網域跑出來，理由與 `scripts/p4/verify-edge.sh` 完全相同：讀設定檔證明不了行為。
4. **單一 replica 是設計，不是暫時將就。** `app/services/registry.py` 與 `app/services/terminal_relay.py` 的狀態是 process-local。Railway 的水平擴充在這個架構下會讓一半的 node 看起來離線，不是「效能不佳」而是「錯誤」。
5. **既有 compose 拓撲不退休。** Railway 設定是**新增**的第二套部署目標；兩套共用同一份 image、同一份 CSP 字串與同一組驗證意圖，並用 gate 擋住兩者漂移。

## 完成結果

完成後：一次 `git push` 會經 CI 後部署到 Railway；migration 在應用啟動前以獨立步驟跑完並可擋下部署；瀏覽器與 daemon 都只看到一個 HTTPS 網域；部署期間 CLI session 不中斷、瀏覽器收到明確的重連通知、daemon 自行重連；`/api/metrics` 對外 404；artifacts 與 checksum 可被 `agentd install`/`update` 驗證；每一項都有一支能重跑的黑箱腳本與一份 release evidence，而不是一段「我試過可以」的記憶。
