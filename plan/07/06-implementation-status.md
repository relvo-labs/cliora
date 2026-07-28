# 06 — Railway 部署實作狀態

> **目前狀態：可離線交付的部分全部完成並在本機實跑驗證；需要 Railway 帳號與真實 node 的部分
> 未開工。** 也就是：三個服務的設定檔、edge template、readiness 語意修正、三支檢查腳本（含
> 48 個測試）、ADR 0020、部署文件與 runbook、traceability gate/link 都在 repo 裡且綠燈；實際
> 建立專案、綁網域、跑 `agentd` 端到端與量測 NFR 尚未進行。
>
> 本文件只記錄可定位的證據。

## Ticket 狀態

| Ticket | 內容 | Wave | 狀態 | 實際證據 |
|---|---|---:|---|---|
| RW-01 | ADR 0020：拓撲、region、replica=1、artifacts、public base URL、readiness 語意、TLS 分界 | 0 | ✅ 完成 | `docs/adr/0020-railway-deployment-topology.md`（12 項決策，含被否決的方案 B/C 與否決理由） |
| RW-02 | requirement 影響矩陣、traceability 掛載計畫 | 0 | ✅ 完成 | `plan/07/01` §4 矩陣；gate/link 已落地（見下） |
| RW-03 | `central` 服務設定、`::`/PORT/start command、drain、`/readyz` 回 503 | 1 | ◐ 檔案完成，未部署 | `deploy/railway/central.railway.json`；`backend/app/main.py:ready()`；3 個新測試；實跑證據見 §2 |
| RW-04 | Postgres、DB URL 契約、連線池、preDeploy migration | 1 | ◐ 契約完成，未部署 | `deploy/railway/env.md`（含 reference-variable 組法與 percent-encode 陷阱）；`check_env.py` 強制；`max_connections` 待實測 |
| RW-05 | `console` 服務、nginx template、私網 upstream、parity gate | 1 | ✅ 完成（含實跑） | `deploy/railway/{console.Dockerfile,nginx.conf.template,console.railway.json}`；`scripts/railway/check-edge-parity.sh`；`nginx -t` 與真實流量驗證見 §2 |
| RW-06 | 變數契約與 `check-env.sh` | 2 | ✅ 完成 | `deploy/railway/env.md`；`scripts/railway/{check-env.sh,check_env.py}`；24 個測試 |
| RW-07 | 自訂網域、`CLIORA_PUBLIC_BASE_URL` 定案、HTTPS/HSTS/WSS 實測 | 2 | ⬜ 未開工（需帳號與網域） | 檢查已就位：`check_env.py` 拒絕 `*.up.railway.app` 與非 https；`verify-deployment.sh` 驗 301/憑證 |
| RW-08 | artifacts 進 image、manifest 與 install-script 端到端 | 2 | ◐ 實作完成且零設定即可用，未對真實部署跑 | 預設由 image 內編譯，版號取自 `daemon/VERSION`、目錄由 image 自設，平台端不需任何變數；`scripts/railway/pack-agentd.sh`（13 個測試，含 tar 根目錄成員與可重現性）。設 `AGENTD_RELEASE_BASE_URL` 則改走下載並驗證 digest 的 `scripts/railway/bake_artifacts.py`（12 個測試，含 digest 不符不落地）；理由見 ADR 0020 §8 |
| RW-09 | 第一位 Admin、備份、外部 uptime、retention 手動流程 | 2 | ◐ 程序文件完成，未執行 | `docs/deployment-railway.md`：兩種 create-admin 路徑、備份、監控表、retention 三步 |
| RW-10 | `verify-deployment.sh` 與 drain 驗證程序 | 3 | ✅ 腳本完成（本機實跑 23 檢查） | `scripts/railway/verify-deployment.sh`、`idle_socket_probe.py`；證據見 §2 |
| RW-11 | 真實 node 端到端九步、NFR-001/003 量測 | 3 | ⬜ 未開工（需帳號與真實 Linux host） | — |
| RW-12 | CI/CD、rollback 演練、文件、traceability、exit report | 3 | ◐ CI 與文件完成，演練未做 | `.github/workflows/ci.yml` 的 `deploy-config` job；`docs/deployment-railway.md`、`docs/runbooks/railway-edge-502.md`；gates/links 已落地 |

## 2. 本機實跑證據

全部在 2026-07-27 於本機執行。Railway 帳號未使用；用真實 `nginx:1.27-alpine` 與真實 Central／PostgreSQL 組成等價鏈路。

| 驗證 | 命令 | 結果 |
|---|---|---|
| edge template 可被 nginx 接受 | `docker run … nginx:1.27-alpine sh -c '/docker-entrypoint.sh nginx -t'` | `syntax is ok` / `test is successful` |
| 真實流量（console → 本機 Central） | `scripts/railway/verify-deployment.sh http://127.0.0.1:8880` | **23 checks / 0 failures / 2 skipped** |
| 其中：WS 授權 | 同上 | 未帶 ticket 的 terminal socket 穿過代理完成 handshake，隨即被關 1008 |
| 其中：閒置 WS | 同上（帶 admin 憑證） | `SURVIVED 8.0s fully idle and still responsive`（真實 Ed25519 handshake，probe node 事後自動移除） |
| 其中：9 MiB body | 同上 | 得到 422（非 413） |
| `/readyz` 真實 503 | Central 指向不存在的資料庫 | `503 {"status":"degraded","database":false,…}`；同時 `/healthz` 仍 200 |
| `/readyz` 真實 200 | Central 指向已 migrate 的資料庫 | `200 {"status":"ready","database":true,…}` |
| parity gate 抓得到漂移 | 從 template 刪掉 `worker-src 'self' blob:` | `FAIL: CSP differs…` exit 1；還原後 exit 0 |
| 腳本測試 | `make railway-test` | 36 passed |
| 後端測試 | `uv run --project backend pytest backend/tests -q` | 見 §4 |
| traceability | `scripts/trace validate --level static`、`coverage --scope all --strict`、`render --check` | passed / `blocking=0` / current |

`verify-deployment.sh` 的兩個 skip 是誠實的 skip 並附前置條件：真實 plain-HTTP 與憑證檢查（需公開網域）、以及端到端 8 MiB 檔案讀取（需已 enroll 的 node）。ADR 0019 的「skip 不是 pass」在此適用。

## 3. 實作過程中修正的規劃錯誤

寫下來，因為每一項都是「照著規劃做會壞掉」：

| 規劃原本寫的 | 實際情況 | 現在的做法 |
|---|---|---|
| 自寫 `15-railway-resolver.envsh` 取 nameserver | `nginx:1.27-alpine` **已內建** `15-local-resolvers.envsh`（功能相同，含 IPv6 加方括號）；而且手動放進 `/docker-entrypoint.d/` 的 `.envsh` **沒有執行權限就會被跳過**，症狀是 nginx 因 `resolver` 為空而啟動失敗 | 刪掉自寫版，設 `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1` 並用 `${NGINX_LOCAL_RESOLVERS}` |
| 新增 `deploy/railway/central.Dockerfile`，`FROM` 既有 stage | Dockerfile **不能 `FROM` 另一個檔案的 stage**；複製 runtime 階段等於製造第二份會漂移的檔案 | 在 `deploy/backend.Dockerfile` 加條件式步驟；無 `AGENTD_VERSION` 時完全不動作，compose build 不受影響 |
| 路徑穿越測試「應回 404」 | 實測回 **200**，因為 nginx 先解碼 `%2f`、解析 `..`，請求被正規化成 `/etc/passwd` 並由 SPA fallback 回 index.html。沒有洩漏，但那個斷言打不到 Central——Central 的 allowlist 整個移除也會過 | 拆成兩項：回應內容不得像系統檔；另外用三個會原樣抵達 Central 的名稱測 allowlist |
| parity 檢查直接 grep `proxy_read_timeout` | 抓到 `deploy/nginx/nginx.conf` **註解裡**當作反例寫的 `proxy_read_timeout 20s`，回報了不存在的不一致 | 比對前先用 `sed 's/#.*//'` 去掉註解 |
| 用 `urlsplit` 就能抓到未編碼的 DB 密碼 | Python 在**最後一個** `@` 切 userinfo，所以看起來完全正常；SQLAlchemy 的 regex 用 `[^@]*`，停在**第一個** `@`，把密碼餘段當成 host。兩者不一致，只用 `urlsplit` 的檢查會過 | 直接檢查 userinfo 區段是否含未編碼的 `@` 或多餘的 `:` |
| `--host ::` 在 `bindv6only=0` 的 Linux 上同時接受 IPv4-mapped，「一個值同時滿足私網與平台探測」（`00` §52、`02` §51） | **不成立。** asyncio 在 `AF_INET6` socket 上明確設 `IPV6_V6ONLY=1`，sysctl 因此無關。實測：`host='::'` → 1 個 socket、`IPV6_V6ONLY=1`、IPv4 connection refused。症狀是平台探測**完全不到達 uvicorn**（log 裡沒有任何 `GET /readyz` access 行），503 來自平台 proxy 而不是 `/readyz`，於是看起來像 readiness 失敗 | `--host ""`：空字串在 asyncio 是 `None`，會綁**每個** family。實測得到 `['AF_INET6', 'AF_INET']` 兩個 socket，`[::1]` 與 `127.0.0.1` 皆回 200 |

## 4. 需要在平台上實測才能定案的項目

| # | 待確認 | 由哪張 ticket | 若假設不成立 |
|---:|---|---|---|
| 1 | `startCommand` 是否確實覆寫 exec-form `ENTRYPOINT`，且 `sh -c 'exec …'` 後 SIGTERM 到得了 uvicorn | RW-03 | 需要一支只換 CMD 的 Dockerfile；**不可**把 `deploy/backend.Dockerfile` 改成 shell form（會弄壞 compose 的 SIGTERM 直達） |
| 2 | 服務私網 IP 是否每次部署改變 | RW-05 | 不變的話 resolver 做法仍正確（成本極低），只是 502 診斷可簡化 |
| 3 | `railway ssh` 可用、可互動輸入、容器內有 shell | RW-03/09 | 建 admin 改走 Postgres 公開 TCP proxy，用完關閉 |
| 4 | Postgres 實際變數名與 `max_connections` | RW-04 | 調整連線字串組法與池大小，並記錄新分母（`database_pool_usage` 告警依賴它） |
| 5 | Postgres idle timeout 是否 < `db_pool_recycle_seconds`(1800) | RW-04 | 調低 recycle，否則連線會在請求中途被對端關閉 |
| 6 | build 階段能否取得服務變數當 build arg | RW-05/08 | `VITE_PRODUCT_NAME`／`AGENTD_VERSION` 改由 railway.json 或固定值提供 |
| 7 | edge 對外部 plain HTTP 是否帶 `X-Forwarded-Proto: http` | RW-10 | 目前的 301 是 fail-open；不帶就等於沒有 HTTP→HTTPS 保證，須改為無條件重導並確認不會打敗平台探測 |
| 8 | WS 閒置 > 90 s 是否存活（文件稱免除 idle 限制） | RW-10 | 先排除 console 的 `proxy_read_timeout`；確認是平台行為後重新評估能否上線 |
| 9 | 「部署前等待 CI」選項是否可用 | RW-12 | 改用 GitHub Actions `railway up`（`plan/07/05` §3.1 方案 2） |
| 10 | `asia-southeast1` 實測 RTT 對 NFR-001 的影響 | RW-11 | release decision 或具名 waiver；不改 PRD 數字 |
| 11 | 實例規格能撐幾條同時 terminal WS | RW-11 | 記錄實測值與所需規格；NFR-003.AC-04 可能需 waiver |
| 12 | 容器是否以 uid 10001 執行、日誌是否不含 secret／terminal bytes | RW-03 | 後者不成立是必須修的洩漏，不是可接受的差異 |

## 5. 本期改動的既有檔案

| 檔案 | 改動 | 影響 |
|---|---|---|
| `backend/app/main.py` | `/readyz` degraded 時回 503（新增 `Response` 參數與註解） | 唯一的產品程式改動 |
| `backend/tests/test_api_foundation.py` | 3 個新測試：ready→200、DB 不可達→503、migration 非 head→503（皆以 monkeypatch 固定兩個分支，不依賴本機有沒有 DB） | 45 passed |
| `deploy/backend.Dockerfile` | 條件式 artifacts 步驟；ENTRYPOINT 註解說明覆寫時必須綁 `::` | 無版本時行為與過去完全相同 |
| `deploy/compose/compose.yaml` | healthcheck 從解析 body 簡化為只看狀態碼 | 語意不變（`urlopen` 對 503 拋錯即 unhealthy） |
| `Makefile` | 新增 `railway-parity` / `railway-test` / `railway-check`，並納入 `check` | `make check` 現在也擋 edge 漂移 |
| `.github/workflows/ci.yml` | 新增 `deploy-config` job：`make railway-check` + 對真實 nginx image 跑 `nginx -t` | 靜態、無網路、無帳號 |
| `traceability/gates.json` | 6 個新 gate | `validate` passed |
| `traceability/links.json` | 19 條 `role: supporting` 的 link（不動既有 primary，故不改變覆蓋率結論） | `coverage --strict` 仍 `blocking=0` |
| `docs/traceability/matrix.md` | 由 `scripts/trace render --write` 重新產生 | 未手改 |
| `docs/deployment.md` | 指向 Railway 版並說明 `/readyz` 狀態碼改變 | 兩份部署文件不再互不知情 |

`/readyz` 的其他呼叫點（`scripts/p4/verify-edge.sh`、`scripts/e2e/run-stack.sh`、`scripts/p4/backup-restore-drill.sh`、`scripts/p4/drills/*`、`scripts/p4/load/capacity.py`、`.github/workflows/p1.yml`）逐一檢查後**不需修改**：它們都用 `curl -fsS` 輪詢或 catch `URLError`（`HTTPError` 是其子類），因此現在改為等待「真正 ready」而非「進程活著」，是更強的條件。`scripts/p4/drills/db-exhaustion.sh` 文件中「Expect some 503s」的敘述在這次改動後才第一次成立。
