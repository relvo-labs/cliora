# 02 — Central 服務與資料庫（RW-03、RW-04）

## 1. RW-03：`central` 服務

### 1.1 不新增 Dockerfile

`deploy/backend.Dockerfile` 直接可用，且已具備 Railway 需要的三個性質：非 root（uid 10001）、image 內無 secret、不在啟動時 migrate。已確認 image 內的相對位置：

- `WORKDIR /app`，`backend/` 的內容整份在 `/app`，因此 `/app/alembic.ini` 存在（`script_location = app/db/migrations`）。
- `PATH=/app/.venv/bin`，且 `alembic==1.14.0` 是 **main dependency**（不在 dev group），因此 `uv sync --no-dev` 的 image 內 `alembic` 可執行。
- `app.bootstrap`、`app.retention` 都在 `/app/app/` 下，`python -m …` 可用。

唯一不能沿用的是 `ENTRYPOINT`：它寫死 `--host 0.0.0.0 --port 8000`，前者在 IPv6 私網上不可達。Railway 的 `startCommand` 會覆寫 exec-form ENTRYPOINT，因此**不需要改 Dockerfile**，用 config-as-code 覆寫即可。

> 若日後 Railway 的覆寫語意改變，退路是新增 `deploy/railway/central.Dockerfile`（`FROM` 既有 image 只換 CMD）。不要為此把 `deploy/backend.Dockerfile` 改成 shell form —— 那會讓 compose 部署失去 SIGTERM 直達 uvicorn 的性質，等於為了 Railway 弄壞另一套部署。

### 1.2 `deploy/railway/central.railway.json`

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "deploy/backend.Dockerfile",
    "watchPatterns": [
      "backend/**",
      "deploy/backend.Dockerfile",
      "deploy/railway/central.railway.json"
    ]
  },
  "deploy": {
    "startCommand": "sh -c 'exec uvicorn app.main:app --host :: --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips=*'",
    "preDeployCommand": "alembic upgrade head",
    "healthcheckPath": "/readyz",
    "healthcheckTimeout": 120,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "drainingSeconds": 25,
    "overlapSeconds": 0
  }
}
```

逐項理由：

| 欄位 | 值 | 為什麼 |
|---|---|---|
| `dockerfilePath` | `deploy/backend.Dockerfile` | Railway 預設找 repository 根的 `Dockerfile`；本專案沒有。build context 是 repository 根，與 compose 的 `context: ../..` 一致 |
| `watchPatterns` | 只含 backend 與自身設定 | 否則改一行前端會重新部署 Central，帶來一次不必要的斷線 |
| `startCommand` | `sh -c 'exec uvicorn … --host ::'` | `sh -c` 才能展開 `${PORT}`；`exec` 讓 uvicorn 取代 shell 成為訊號接收者，否則 SIGTERM 停在 shell、drain 不會跑 |
| `--host ::` | IPv6 any | 私網為 IPv6；在 `net.ipv6.bindv6only=0` 的 Linux 上同時接受 IPv4-mapped 連線，因此一個值同時滿足私網與平台探測 |
| `--proxy-headers --forwarded-allow-ips=*` | 信任前置代理 | 路徑上一定有兩層代理（Railway edge + console nginx）。`*` 是可接受的，因為 `central` 沒有公開網域，唯一能連到它的就是專案私網 |
| `preDeployCommand` | `alembic upgrade head` | 失敗即不部署且不重試，等價於 compose 的 `service_completed_successfully`。`cwd` 為 `/app`，`alembic.ini` 在該處，URL 由 `app.settings` 提供 |
| `healthcheckPath` | `/readyz` | 需搭配 §1.4 的狀態碼修正才有意義 |
| `healthcheckTimeout` | 120 | Central 啟動只需連上 DB 並讀一次 `alembic_version`；300 s 預設會讓一個真正壞掉的部署卡五分鐘才判失敗 |
| `drainingSeconds` | 25 | 必須大於 `CLIORA_SHUTDOWN_DRAIN_SECONDS`（15）。這是 compose `stop_grace_period: 30s` 那條規則的同一件事 |
| `overlapSeconds` | 0 | 重疊期間兩個 Central 各自持有一半 daemon socket 且 DB 池加倍；狀態既是 process-local，重疊沒有任何好處 |
| `restartPolicyMaxRetries` | 10 | 設定錯誤（例如 dev secret）會讓 `Settings` 直接 raise；無限重啟只會刷日誌 |

### 1.3 服務層設定

| 設定 | 值 | 說明 |
|---|---|---|
| 服務名 | `central` | 私網名稱 `central.railway.internal` 會出現在 console 設定裡，改名等於改 console 設定 |
| 公開網域 | **不要** | Central 只透過私網被 console 存取。若給了公開網域，`/api/metrics` 與 `/readyz` 就繞過 console 的 404/no-log 規則直接對外 |
| replica | 1 | 見 00 §3 |
| region | `asia-southeast1` | 與 Postgres、console 同區 |
| `PORT` | `8080` | 明確設定，不依賴平台注入 |
| Config as code path | `deploy/railway/central.railway.json` | 在服務設定中指定 |

### 1.4 `/readyz` 語意修正（本期唯一的程式改動）

現況：`backend/app/main.py` 的 `ready()` 無論 `database`/`migration` 是否為真都回 200，ready 與否只寫在 body 的 `status` 欄位。compose 的 healthcheck 因此要用一段 Python 解析 JSON。

Railway 只看狀態碼，於是照抄設定會得到「一個連不上資料庫的 Central 通過健康檢查並接下流量」。

同時這也修掉一個既有落差：`scripts/p4/drills/db-exhaustion.sh:33` 印出「Expect some 503s」，但 `_database_ready()` 會吃掉池逾時的例外並回 200——那個 drill 的預期從來沒有成立過。

變更：

```python
@app.get("/readyz")
async def ready(response: Response) -> dict[str, object]:
    ...
    # Railway（以及任何只讀狀態碼的 orchestrator）看不到 body。readiness 必須表現在
    # 狀態碼上，否則「未 migrate 或連不上 DB 的容器不得接流量」這條規則在該平台不存在。
    if not ready_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {...}
```

`/healthz` 不變（liveness，只證明 process 活著）。

**必須同步檢查的呼叫點**（每一處都要在 PR 中說明結論，不可只改主程式）：

| 位置 | 現行行為 | 修正後 |
|---|---|---|
| `deploy/compose/compose.yaml` backend healthcheck | 以 `urllib` 讀 body 判斷 | 可簡化為只看狀態碼；`urlopen` 對 503 會拋 `HTTPError`，exit 非零，語意仍正確 |
| `scripts/p4/verify-edge.sh:227` | 斷言 `/readyz` 回 200 | 不變（該處已等到 ready）；但需確認等待迴圈在 503 時會重試而非早退 |
| `scripts/p4/verify-edge.sh:101,104` | `curl -fsS` 等待啟動 | `-f` 對 503 失敗 → 迴圈繼續重試，行為正確 |
| `scripts/e2e/run-stack.sh:81-82` | 同上 | 同上 |
| `scripts/p4/backup-restore-drill.sh:244` | `curl -fsS` 取 body | 同上；並確認「還原後 Central 回報 ready」的斷言仍成立 |
| `scripts/p4/drills/run-all.sh:108` | 同上 | 同上 |
| `scripts/p4/drills/db-exhaustion.sh:27` | 記錄狀態碼，文字預期 503 | **這次才真的會出現 503**；drill 文字與實作終於一致 |
| `scripts/p4/load/capacity.py:206` | readiness 探測 | 確認非 200 時的處理不會把整個 harness 判成失敗 |
| `.github/workflows/p1.yml:188-189` | `curl -fsS` 等待 | 行為正確 |
| `backend/tests/test_api_foundation.py:27,59` | 讀 body 的 key | 補上狀態碼斷言：ready → 200、DB 不可用 → 503 |

新增測試（`backend/tests/test_api_foundation.py`）：`test_readyz_returns_503_when_the_database_is_unreachable`、`test_readyz_returns_503_when_the_applied_migration_is_not_head`。

### 1.5 設定變數對映

| `CLIORA_*` | Railway 上的值 | 備註 |
|---|---|---|
| `CLIORA_ENVIRONMENT` | `production` | 觸發 `reject_dev_secrets_in_production`；忘記設 secret 會啟動失敗而不是跑在預設值上 |
| `CLIORA_DATABASE_URL` | 見 §2.2 的 reference variable 組合 | 必須是 `postgresql+asyncpg://` |
| `CLIORA_JWT_SECRET` | `openssl rand -base64 48` | 輪替＝所有登入 session 失效（可接受的例行操作） |
| `CLIORA_TOKEN_PEPPER` | `openssl rand -base64 48` | **單向門**：輪替使所有 enrollment token 與 node credential 失效，全 fleet 需重新 enroll |
| `CLIORA_PUBLIC_BASE_URL` | `https://<自訂網域>` | 一次性決定；寫進 installer 與每個 node 的 config |
| `CLIORA_ARTIFACTS_DIR` | 第一階段留空；RW-08 後 `/srv/artifacts` | 空值使 `/api/downloads`、`/api/install-script` 回 404，manifest 回空（非 404） |
| `CLIORA_METRICS_ENABLED` | `false` | 開啟時必須同時給 ≥16 字元的 `CLIORA_METRICS_SCRAPE_TOKEN`，否則啟動失敗 |
| `CLIORA_SHUTDOWN_DRAIN_SECONDS` | `15` | 與 `drainingSeconds: 25` 成對維護 |
| `PORT` | `8080` | 見 §1.3 |

不需要在 Railway 設定的：`CLIORA_P0_*`（P4-07 已移除，`extra="ignore"` 會靜默吃掉遺留值）、所有 timeout/limit（預設值即 ADR 決定的量測值，改動需要 ADR）。

### 1.6 驗收（RW-03）

```bash
# 1. 非 root
railway ssh --service central -- id            # uid=10001(cliora)
# 2. 監聽 IPv6 與正確 port
railway ssh --service central -- sh -c 'ss -ltnp 2>/dev/null || netstat -ltn'   # :::8080
# 3. readiness 語意
railway ssh --service central -- python -c \
  "import urllib.request as u; print(u.urlopen('http://[::1]:8080/readyz').status)"   # 200
# 4. 部署日誌中確認 preDeploy 先跑
railway logs --service central | grep -E "alembic|central_startup"
# 5. drain 真的跑完（觸發一次重新部署後）
railway logs --service central | grep shutdown_drained    # duration_ms < 15000
# 6. 日誌不含 secret / terminal bytes
railway logs --service central | grep -Ei "secret|pepper|Bearer [A-Za-z0-9]" | head
```

失敗模式對照：

| 症狀 | 原因 |
|---|---|
| console 對 `/api` 一律 502，但 `central` 日誌顯示「Uvicorn running」 | 綁在 `0.0.0.0` 而非 `::`（或 `PORT` 不一致） |
| 部署成功但每次都有瀏覽器抱怨突然斷線，日誌無 `shutdown_drained` | `drainingSeconds` 未設（預設 0） |
| 部署後才發現 schema 沒更新 | `preDeployCommand` 未設；此時 `/readyz` 會回 503 並擋住流量（這是設計，不是故障） |
| 啟動即 crash，日誌為 `ValueError: JWT secret and token pepper must be set in production` | 少設 secret；這是刻意的失敗 |

## 2. RW-04：Postgres 與連線

### 2.1 服務設定

| 項目 | 值 |
|---|---|
| 來源 | Railway 的 PostgreSQL（16） |
| region | `asia-southeast1`（與 `central` 同區；跨區等於每次查詢都付一次 RTT） |
| 公開 TCP proxy | 預設不使用；只在一次性作業（§3、04 §3）時暫時啟用 |
| 備份 | 啟用平台自動備份，並額外執行 `pg_dump` 到專案外（見 04 §4） |

### 2.2 `CLIORA_DATABASE_URL` 契約

Railway 的 `DATABASE_URL` 是 `postgresql://…`，`Settings.database_url` 需要 `postgresql+asyncpg://…`。**在變數層轉換，不在程式裡加平台特例**：

```
CLIORA_DATABASE_URL=postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.POSTGRES_PASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}
```

（實際變數名以 Postgres 服務面板提供者為準——RW-04 的第一步就是把該服務的變數清單抄進 `deploy/railway/env.md`，不要憑記憶填。）

三個要注意的點：

1. **必須用 `RAILWAY_PRIVATE_DOMAIN`**，不是 public host。走 public TCP proxy 等於把資料庫流量繞出私網，還多付一次延遲。
2. **不要附加 `?sslmode=…`**。asyncpg 不吃 libpq 的 `sslmode` 參數；私網連線不需要它。若日後要求 TLS，用 `connect_args` 而不是 query string，並先改 ADR。
3. 密碼可能含 URL 保留字元。reference variable 不會自動 percent-encode，若密碼含 `@`、`:`、`/` 就會組出錯誤的 URL。`scripts/railway/check-env.sh` 必須實際解析這個 URL 而非只檢查前綴。

### 2.3 連線池

`Settings` 的預設：`db_pool_size=10`、`db_max_overflow=10`、`db_pool_timeout_seconds=5`、`db_pool_recycle_seconds=1800`。

單 replica 的上限是 20 條。加上：

- `preDeployCommand` 的 alembic（短暫，數條）；
- 人工 `railway ssh` 操作（數條）；
- `overlapSeconds=0` 所以**不會**出現兩個 Central 各佔 20 條。

RW-04 必須做的事：查出該 Postgres 方案實際的 `max_connections`（`railway ssh` 到 Postgres 服務或以 psql 執行 `SHOW max_connections;`），確認 ≥ 60。若低於此值就調降 `db_pool_size`／`db_max_overflow` 並在 ADR 記錄——因為 `database_pool_usage` 指標與「池耗盡」告警的分母就是這兩個值，改了不記錄等於讓告警失去意義（ADR 0018 已寫明這點）。

`db_pool_recycle_seconds=1800` 的註解說它「well inside the typical proxy/database idle timeout」。RW-04 要確認 Railway Postgres 的 idle timeout 是否小於 1800 s；若是，調低並記錄。

### 2.4 migration 與 rollback

- 正向：`preDeployCommand: alembic upgrade head`。失敗 → 不部署 → 舊版本繼續服務（這是好結果）。
- 檢視：`railway ssh --service central -- alembic current`。
- 反向：**不要**把 downgrade 放進任何自動化。`deploy/migrate.sh downgrade` 是刻意互動式的；Railway 上等價操作是 `railway ssh --service central -- alembic downgrade <revision>`，且必須先備份。`docs/deployment.md` 的「應用層 rollback 先試」原則不變：0008–0011 是 additive，舊版通常能對新 schema 運作。

### 2.5 驗收（RW-04）

```bash
# 池與版本
railway ssh --service central -- alembic current            # 顯示 head revision
railway ssh --service central -- python -c "from app.settings import get_settings as g; s=g(); print(s.database_url.split('@')[0], s.db_pool_size, s.db_max_overflow)"
# max_connections
railway connect Postgres -c 'SHOW max_connections;'
# readiness 綜合
curl -sS -o /dev/null -w '%{http_code}\n' https://<自訂網域>/readyz   # 200
```

再加一項刻意的負面驗證：把 `CLIORA_DATABASE_URL` 暫時改成不存在的資料庫並重新部署，確認 (a) `preDeployCommand` 失敗、(b) 部署不進行、(c) 舊部署仍在服務。做完立刻改回。這一項證明的是「設定錯誤會被擋下」，而它是 Railway 上最容易被誤以為存在的保護。
