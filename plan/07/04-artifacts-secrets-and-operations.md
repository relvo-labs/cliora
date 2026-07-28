# 04 — 變數契約、Artifacts 與營運作業（RW-06、RW-08、RW-09）

## 1. RW-06：變數與 secret 契約

### 1.1 `deploy/railway/env.md`

一份表格，說明每個變數屬於哪個服務、是否必填、由誰提供、以及**設錯的後果**。它取代 `.env.example` 在 Railway 上的角色（Railway 沒有可提交的 env 檔，因此契約必須是文件 + 檢查腳本）。

| 服務 | 變數 | 必填 | 值 / 來源 | 設錯的後果 |
|---|---|---|---|---|
| central | `CLIORA_ENVIRONMENT` | ✅ | `production` | 非 production 時 dev secret 檢查不啟動，可能帶著可偽造的 JWT secret上線 |
| central | `CLIORA_DATABASE_URL` | ✅ | `postgresql+asyncpg://…@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/…` | 少了 `+asyncpg` → SQLAlchemy 選到同步 driver，啟動即錯；用 public host → 流量繞出私網並多付延遲 |
| central | `CLIORA_JWT_SECRET` | ✅ | `openssl rand -base64 48` | 留預設值 → 啟動失敗（刻意） |
| central | `CLIORA_TOKEN_PEPPER` | ✅ | `openssl rand -base64 48` | 同上；**輪替＝所有 node 需重新 enroll** |
| central | `CLIORA_PUBLIC_BASE_URL` | ✅ | `https://<自訂網域>` | 錯了會寫進每個 node 的 config；改動需逐台 `agentd register` |
| central | `PORT` | ✅ | `8080` | 與 console 的 `CLIORA_BACKEND_PORT` 不一致 → 全部 `/api` 502 |
| central | `CLIORA_SHUTDOWN_DRAIN_SECONDS` | — | `15`（預設） | 大於 `drainingSeconds` → drain 被 SIGKILL 截斷 |
| central | `CLIORA_ARTIFACTS_DIR` | — | 空 或 `/srv/artifacts` | 空＝安裝／下載端點 404、manifest 回空（可接受的初期狀態） |
| central | `CLIORA_METRICS_ENABLED` | — | `false` | `true` 而沒給 ≥16 字元 token → 啟動失敗（刻意） |
| console | `PORT` | ✅ | `8080` | — |
| console | `CLIORA_BACKEND_HOST` | ✅ | `central.railway.internal` | 拼錯 → 全部 `/api`、`/ws` 502 |
| console | `CLIORA_BACKEND_PORT` | ✅ | `8080` | 同上 |
| console | `VITE_PRODUCT_NAME` | — | `Cliora` | build 時烘進 bundle，改了要重建 |
| console | `VITE_API_BASE_URL` | ❌ **必須留空/不設** | — | 非空 → API 走絕對網址、terminal WS 仍走 `location.host`：登入正常但終端機全滅 |

另外記錄「**不要設**」的清單：`CLIORA_P0_*`（端點已於 P4-07 移除，`extra="ignore"` 會靜默接受並毫無作用，留著只會誤導）、以及任何 timeout/limit（預設值是 ADR 決定的量測結果，要改先改 ADR）。

### 1.2 `scripts/railway/check-env.sh`

在部署前對目標環境跑（`railway variables --service … --json` 取值）。任一項不符即非零 exit：

1. 必填變數存在且非空。
2. `CLIORA_ENVIRONMENT == production`。
3. `CLIORA_JWT_SECRET`、`CLIORA_TOKEN_PEPPER` 不等於 `dev-only-change-me`，且長度 ≥ 32。
4. `CLIORA_DATABASE_URL` **能被解析**：scheme 必須是 `postgresql+asyncpg`，host 必須以 `.railway.internal` 結尾，且 userinfo 中的密碼經 percent-decode 後與 Postgres 服務的密碼相同——reference variable 不會自動 encode，密碼含 `@`、`:`、`/` 時會組出錯誤但看起來正常的 URL。
5. `CLIORA_PUBLIC_BASE_URL` 是 `https://`、非 `*.up.railway.app`、且與 console 的自訂網域相同。
6. console 的 `VITE_API_BASE_URL` 未設定或為空。
7. `PORT`（central）＝ `CLIORA_BACKEND_PORT`（console）。
8. `CLIORA_METRICS_ENABLED` 為 `true` 時 token 長度 ≥ 16。
9. `drainingSeconds`（讀 `central.railway.json`）> `CLIORA_SHUTDOWN_DRAIN_SECONDS`。
10. 三個服務與 Postgres 在同一 region。

**腳本不得印出任何 secret 值**，只印變數名與判斷結果。這與 `traceability` 的 artifact 規則一致，也是因為 CI 日誌會被保留。

## 2. RW-08：Artifacts 與一行安裝

### 2.1 為什麼這件事需要決定

`app/services/releases.py` 的 manifest 與 `app/api/http/downloads.py` 都讀**本地檔案系統**的 `CLIORA_ARTIFACTS_DIR`，而且 manifest 是 fail-closed 的：只有「名稱在 allowlist、檔案存在、`checksums.txt` 有它的 digest、大小相符」四項齊備才會發布一筆。Railway 容器的檔案系統是暫時性的，因此必須明確決定 artifacts 從哪來。

（順帶：這個設計不是可以繞過的。`agentd update` 的 protocol 只帶 version，不帶 URL/檔名/digest——這正是 SEC-002 的實現方式。把 artifacts 改成從 S3/GitHub 直接讓 daemon 抓，等於推翻該設計，屬於 ADR 變更而非部署選項。）

### 2.2 兩個方案

| | **A：建置時烘進 image（採用）** | B：Railway volume |
|---|---|---|
| 做法 | `deploy/backend.Dockerfile` 增加一個**條件式步驟**：給了 `AGENTD_VERSION` 與 `AGENTD_RELEASE_BASE_URL` 就下載該 release 與 `checksums.txt`，**逐一驗 SHA-256 後**寫入 `/srv/artifacts`（唯讀）；沒給就什麼都不做並 exit 0 | 在 `central` 掛 volume 至 `/srv/artifacts`，以 `railway ssh` 執行下載腳本 |
| artifacts 不可變 | ✅ 與 image 一同版本化，可重現 | ❌ 執行期可變 |
| digest 驗證時機 | build 時（失敗即 build 失敗） | 發佈時（人為操作） |
| replica 限制 | 無額外限制 | volume ⇒ **不可 replica** |
| 部署停機 | 無（可正常 healthcheck 切換） | **每次部署都有停機**（同一 volume 不允許兩個部署同時掛載） |
| 發佈新 daemon 版本的成本 | 重新部署 Central（約一分鐘，session 不受影響） | 不需重新部署 |
| 寫入權限風險 | 無（build 以 root 進行） | volume 的 owner 未必是 uid 10001，可能完全無法寫入 |

採用 A。daemon release 是低頻事件，用「一次 Central 重新部署」換掉「永久的 replica 限制 + 每次部署停機 + 一個可變的安全關鍵目錄」是明顯的划算交易。

B 保留為退路：若需要在不重新部署 Central 的情況下發佈 artifacts（例如緊急回滾 daemon 版本），再評估。屆時第一件事是 `railway ssh --service central -- touch /srv/artifacts/.probe` 確認 uid 10001 可寫。

### 2.3 實作方式（與原規劃的差異）

原規劃寫的是新增一支 `deploy/railway/central.Dockerfile`，用 `FROM` 接既有階段。實作時無法這樣做：**Dockerfile 不能 `FROM` 另一個檔案裡的 stage**，硬做就得整段複製 runtime 階段，於是兩份會漂移。

改為在 `deploy/backend.Dockerfile` 內加一個條件式步驟，兩個部署共用同一份：

- `ARG AGENTD_VERSION=""`、`ARG AGENTD_RELEASE_BASE_URL=""`。
- `COPY scripts/railway/bake_artifacts.py` + `deploy/install.sh`，執行後刪掉。
- 沒有版本 → 腳本印一行說明並 exit 0，**compose build 完全不受影響、不新增 build 期網路依賴**。
- 有版本 → 下載兩個 arch 的 tarball 與 `checksums.txt`，全部 digest 對上才落地；任一不符即 build 失敗。
- 落地後 `chown 10001:10001` + `chmod -R a-w`：這是 compose 用 `:ro` 掛載表達的同一件事（Central 發佈它們，沒有理由能改它們）。

下載與驗證邏輯放在 `scripts/railway/bake_artifacts.py` 而不是 Dockerfile 的一行 shell，因為它是安全關鍵步驟：`scripts/railway/tests/test_bake_artifacts.py` 用 `file://` 的假 release 目錄涵蓋 digest 不符、digest 缺項、tarball 缺項、`checksums.txt` 無法解析、版本字串可構成惡意檔名、明文 base URL、以及「無版本時不得寫任何東西」。其中一項測試會拿 `backend/app/services/releases.py` 的 `ARTIFACT_PATTERN` 去驗證這支腳本產生的每個檔名——兩份 allowlist 遲早會不一致，而不一致的方向決定 node 到底能不能更新。

原規劃版本（供對照，已不採用）：

```dockerfile
# Railway 版 Central：與 deploy/backend.Dockerfile 完全相同的應用層，額外把一個
# 已驗證的 agentd release 烘進 /srv/artifacts。
#
# 為什麼在 build 做而不是執行期：/api/downloads 與 release manifest 讀本地檔案，而
# Railway 的容器檔案系統是暫時性的。烘進 image 讓 artifacts 與 image 一起版本化、
# 不可變，並且 digest 驗證失敗就是 build 失敗——而不是某天某個 node 更新到一半才發現。
ARG AGENTD_VERSION
FROM <既有 build 階段>            # 直接 include deploy/backend.Dockerfile 的兩個階段
...
FROM runtime AS railway
ARG AGENTD_VERSION
ARG AGENTD_RELEASE_BASE=https://github.com/<owner>/<repo>/releases/download
USER root
RUN set -eu; mkdir -p /srv/artifacts; cd /srv/artifacts; \
    python - "$AGENTD_RELEASE_BASE/v$AGENTD_VERSION" "$AGENTD_VERSION" <<'PY'
# stdlib only：不為了一次下載而把 curl 裝進 runtime image。
# checksums.txt 是唯一的 digest 來源，與 install.sh 及 agentd update 用的是同一份檔案。
import hashlib, pathlib, sys, urllib.request
base, version = sys.argv[1], sys.argv[2]
names = [f"agentd_{version}_linux_{a}.tar.gz" for a in ("amd64", "arm64")] + ["checksums.txt"]
for n in names:
    pathlib.Path(n).write_bytes(urllib.request.urlopen(f"{base}/{n}").read())
expected = {}
for line in pathlib.Path("checksums.txt").read_text().splitlines():
    digest, _, name = line.partition("  ")
    expected[name.lstrip("*")] = digest
for n in names[:-1]:
    got = hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest()
    if got != expected.get(n):
        raise SystemExit(f"checksum mismatch for {n}: {got} != {expected.get(n)}")
print("verified", *names[:-1])
PY
COPY deploy/install.sh /srv/artifacts/install.sh
RUN chown -R 10001:10001 /srv/artifacts && chmod -R a-w /srv/artifacts
USER cliora
```

`chmod a-w`：Central 只需要讀 artifacts。`deploy/compose/compose.yaml` 用 `:ro` 表達同一件事（「Central 發布它們，沒有理由能改它們」），Railway 沒有唯讀掛載可用，就用檔案權限表達。

`central.railway.json` 的 `dockerfilePath` 改指這支，並把 `AGENTD_VERSION` 設為 Railway 服務變數（build 時可用）。`watchPatterns` 加上 `deploy/railway/central.Dockerfile`、`deploy/install.sh`。

### 2.4 驗收（端到端，不是逐項檢查）

```bash
D=<自訂網域>
curl -sS  https://$D/api/releases/manifest | python -m json.tool      # latest 非 null，兩個 arch
curl -sSI https://$D/api/downloads/checksums.txt | head -1            # 200
curl -sS  https://$D/api/install-script | head -5                     # install.sh 內容
# 路徑穿越仍被拒
curl -sS -o /dev/null -w '%{http_code}\n' "https://$D/api/downloads/..%2f..%2fetc%2fpasswd"   # 404
# 真實 node 上（RW-11 會做完整版）
sudo agentd update --dry-run                                          # 下載 + digest 檢查通過後停止
```

`--dry-run` 是關鍵的一項：它會走完 manifest 查詢、下載、digest 檢查與 staged binary 的版本檢查才停手，因此能證明 TECH-SEC-12 在 Railway 上仍然成立，而且不需要 root、不會真的換掉 binary。

## 3. RW-09：一次性與週期性營運作業

### 3.1 第一位 Admin

兩條路，都不把管理員密碼放進服務變數（那會讓它永久留在平台設定裡）：

```bash
# 方案 1（建議）：在容器內互動執行，密碼只存在於這個 shell 的環境
railway ssh --service central
  read -rs CLIORA_ADMIN_PASSWORD && export CLIORA_ADMIN_PASSWORD
  python -m app.bootstrap create-admin --username admin
  unset CLIORA_ADMIN_PASSWORD; exit

# 方案 2：本機執行，透過 Postgres 的公開 TCP proxy（用完立刻關閉該網域）
CLIORA_DATABASE_URL='postgresql+asyncpg://…@<proxy-host>:<port>/railway' \
CLIORA_ADMIN_PASSWORD='…' \
  uv run --project backend python -m app.bootstrap create-admin --username admin
```

方案 2 的代價是暫時把資料庫暴露在公網 TCP proxy 上，所以只在方案 1 不可用時使用，並在完成後移除該網域。

### 3.2 Audit retention

**不排 cron。** ADR 0016 明確決定 expiry 由 operator 執行、不由背景排程處理，理由是「誤排程刪掉 audit trail 比手動保留更糟」。Railway 的 cron service 很容易加，正因如此要在文件裡明確寫下不加，以及要加的前置條件（先修 ADR 0016，且 cron 之前必須有一次成功備份）。

實際流程寫進 `docs/deployment-railway.md`：

```bash
# 1. 先備份（這是唯一會刻意刪除 audit 歷史的操作）
# 2. 乾跑：不帶 --yes 只報告
railway ssh --service central -- python -m app.retention prune
# 3. 確認數字合理後才執行
railway ssh --service central -- python -m app.retention prune --yes
```

### 3.3 備份與還原

- 啟用 Railway Postgres 的自動備份。
- **額外**用 `pg_dump` 保存一份到平台之外：平台備份與平台帳號共命運，而備份的目的之一就是「平台或帳號出問題時還有東西」。
- `scripts/p4/backup-restore-drill.sh` 目前針對本機 docker Postgres。RW-09 不改寫它，而是記錄如何用它驗證 Railway 的 dump：把 Railway 的 dump 檔餵給同一支腳本的還原與掃描階段，取得「dump 不含 terminal 輸出、檔案內容或明文憑證」的證明。這支腳本的掃描部分是備份流程唯一能證明**沒有洩漏**的地方，不能因為換了平台就跳過。
- 還原演練至少做一次，並記錄 RTO 實測值。

### 3.4 上線後監控（因為平台不做）

Railway 的 healthcheck **只在部署時執行**。上線後 DB 斷線、pool 耗盡、migration 不一致都不會有任何平台層面的反應（單 replica 也沒有可切換的對象）。因此必須有外部檢查：

| 檢查 | 目標 | 判準 | 對應 runbook |
|---|---|---|---|
| readiness | `https://<網域>/readyz` | 非 200 即告警（修正後 degraded 會回 503） | `docs/runbooks/db-exhaustion.md` |
| liveness | `https://<網域>/healthz` | 非 200 即告警 | — |
| console | `https://<網域>/edge-health` | 非 200 即告警（可區分「edge 掛了」與「Central 掛了」） | 新增於 `docs/deployment-railway.md` |
| 憑證 | 自訂網域憑證到期日 | < 14 天告警 | 平台自動續期，但要知道它沒續 |

工具不指定（外部 uptime 服務或另一個排程都可），但**必須存在**，且要能區分 console 與 Central——沒有這項區分，一次 502 會讓人先去看 Central 的日誌，而問題可能在 edge 的 upstream 解析。

### 3.5 （選配）私網 metrics

若要 Prometheus：在專案內加第四個服務，`CLIORA_METRICS_ENABLED=true` + `CLIORA_METRICS_SCRAPE_TOKEN`（≥16 字元），scrape target 設為 `central.railway.internal:8080/api/metrics`。edge 對 `/api/metrics` 的 404 保持不動——這正是 ADR 0018「metrics 不應成為控制平面上的常駐對外讀取面」的做法。Prometheus 服務需要 volume 才能保存資料，因而受 replica 與部署停機限制；對監控服務而言可以接受。

不做這個也可以：`/readyz` + 外部 uptime 檢查已能覆蓋最重要的失敗模式；`deploy/prometheus/alerts.yml` 的規則需要 metrics 才有意義，所以要不要開等於「要不要那些告警」，這是明確的取捨而不是遺漏。
