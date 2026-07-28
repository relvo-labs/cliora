# 03 — Edge／Console 與 single-origin（RW-05、RW-07）

## 1. 為什麼 console 必須是反向代理

兩處程式決定了這件事，不是偏好問題：

- `frontend/src/api/client.ts:72` — `BASE = import.meta.env.VITE_API_BASE_URL ?? ""`，預設相對路徑。
- `frontend/src/composables/useTerminalSession.ts:85-87` — terminal WebSocket 用 `location.protocol` / `location.host` 組成 `wss://<當前主機>/ws/sessions/{id}/terminal?ticket=…`，**不讀任何 env**。

再加上 CSP 的 `connect-src 'self' wss: ws:`，以及 `backend/app/main.py` 沒有 CORSMiddleware：整個系統是 same-origin 設計。所以 Railway 上的公開服務必須同時提供靜態 console 與 `/api`、`/ws`。

## 2. RW-05 交付物

```
deploy/railway/
  console.Dockerfile              # node build → nginx runtime（與 deploy/frontend.Dockerfile 同構）
  nginx.conf.template             # Railway 版 edge 設定（無 TLS、listen ${PORT}）
  console.railway.json            # config-as-code
  central.railway.json            # （RW-03）
  env.md                          # （RW-06）變數契約
  README.md                       # 目錄導覽與四個最容易踩到的點
scripts/railway/
  check-edge-parity.sh            # 兩份 nginx 設定的 CSP / 關鍵值一致性
```

> **實作修正（RW-05 完成時）**：原本計畫自寫一支 `15-railway-resolver.envsh` 從
> `/etc/resolv.conf` 取 nameserver。實測發現 `nginx:1.27-alpine` **已內建**
> `/docker-entrypoint.d/15-local-resolvers.envsh`，功能完全相同（含 IPv6 加方括號），只需
> 設 `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1` 並在 template 使用 `${NGINX_LOCAL_RESOLVERS}`。
> 自寫版本已刪除。同時實測到一個原本不知道的陷阱：手動放進 `/docker-entrypoint.d/` 的
> `*.envsh` **必須有可執行權限**，否則 entrypoint 會印 "Ignoring ..., not executable" 並跳過，
> 於是 `resolver` 渲染成空值、nginx 啟動失敗——訊息完全不會提到 resolver 來源。

### 2.1 `console.Dockerfile`

與 `deploy/frontend.Dockerfile` 的差別只有三處，其餘照抄（多階段、`npm ci`、runtime 不含 node 與原始碼）：

1. 不 `COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf`，改成把 template 放到 `/etc/nginx/templates/nginx.conf.template`，並設 `ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx`。nginx 官方 image 的 `20-envsubst-on-templates.sh` 會在啟動時把 template 展開成 `/etc/nginx/nginx.conf`。
2. `ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1`，開啟 image 內建的 `15-local-resolvers.envsh`。（若日後真的需要自寫一支放進 `/docker-entrypoint.d/`：副檔名必須是 `.envsh`——entrypoint 對 `*.envsh` 用 `source`、對 `*.sh` 用執行，只有被 source 的檔案能把變數帶進後續 envsubst；而且**必須有可執行權限**，否則會被 "Ignoring ..., not executable" 跳過。兩者任一漏掉，症狀都是 nginx 因 `resolver` 為空而啟動失敗，訊息不會提到來源。）
3. `EXPOSE` 改為說明性的註解即可（實際 port 由 `${PORT}` 決定），不再 `EXPOSE 443`。

`ARG VITE_PRODUCT_NAME` / `ARG VITE_API_BASE_URL` 保留。**`VITE_API_BASE_URL` 必須保持空字串**——非空會讓 API 走絕對網址而 terminal WS 仍留在 `location.host`，形成「登入正常、終端機全滅」的半壞狀態。

### 2.2 Resolver（改用 image 內建）

nginx 只在載入設定時解析 upstream 名稱一次，並把 IP 快取到下次重載。Railway 服務每次部署都會換私網 IP，因此靜態 upstream 的後果不是「偶爾失敗」，而是「Central 每部署一次，console 就 502，直到 console 也被重新部署」。

修法是讓 `proxy_pass` 走變數（請求時才解析），這需要一個 `resolver`。nginx 不會自己讀 `/etc/resolv.conf`，但 `nginx:1.27-alpine` 內建的 `15-local-resolvers.envsh` 會：設 `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1` 後，它把 nameserver（IPv6 自動加方括號）匯出成 `NGINX_LOCAL_RESOLVERS`，供 envsubst 填入。

若容器完全沒有 nameserver，該變數為空、`resolver` 渲染成空值、nginx 拒絕啟動——方向正確：沒有 resolver 卻讓 nginx 起來，會變成「console 活著但所有 `/api` 都 502」，比啟動失敗難診斷得多。

### 2.3 `nginx.conf.template`

以 `deploy/nginx/nginx.conf` 為基礎，逐段差異如下。**未列出的部分（`worker_connections 4096`、`tcp_nodelay`、`server_tokens off`、gzip 清單、log format、`client_max_body_size 16m`、`large_client_header_buffers`）全部照抄，理由也照抄。**

| 段落 | compose 版 | Railway 版 | 為什麼 |
|---|---|---|---|
| listen | `listen 80` + `listen 443 ssl http2` | 單一 `listen ${PORT}` | TLS 在 Railway edge 終結，容器只看得到 HTTP |
| 憑證 | `ssl_certificate` 等 6 個指令 | 全部移除 | 容器內沒有憑證檔；留著會直接啟動失敗 |
| ACME | `/.well-known/acme-challenge/` | 移除 | 憑證由平台簽發與續期 |
| HTTP→HTTPS | port 80 的 `return 301` | `map $http_x_forwarded_proto` + server 層 `return 301` | 只有 forwarded header 明確說 `http` 時才重導 |
| upstream | `upstream cliora_backend { server backend:8000; keepalive 32; }` | 移除 upstream block，改 `resolver` + `set $cliora_upstream …` + `proxy_pass http://$cliora_upstream$request_uri` | 見 §2.2 |
| `/ws/` timeout | `proxy_read_timeout 3600s` | 不變 | Railway edge 對 WS 無 idle 限制，但 console 的 nginx 仍在路徑上，且此值必須高於 uvicorn `ws_ping_interval`（20 s） |
| security header 集合 | 每個 location 重複一次 | 不變，同樣重複 | `add_header` 不會繼承進宣告了自己 `add_header` 的 location。這個坑在 compose 版的檔頭已寫得很清楚，Railway 版沒有理由重犯 |
| CSP | 單行長字串 | **逐字元相同** | 由 `check-edge-parity.sh` 強制 |
| `= /api/metrics` | `return 404` | 不變 | `location /api/` 是前綴匹配，沒有精確匹配就等於對外公開 |
| `/healthz`、`/readyz` | proxy 且 `access_log off` | 不變 | 外部 uptime 檢查需要 `/readyz`（Railway 部署後不再健康檢查） |
| 新增 | — | `location = /edge-health { access_log off; return 200 "ok\n"; }` | console 服務自身的 healthcheck 目標，不依賴 Central 是否 ready |

關鍵段落：

```nginx
# 只有在 edge 明確告知客戶端使用 http 時才重導。預設 0（不重導）是為了平台內部探測：
# healthcheck 不帶 X-Forwarded-Proto，若預設重導，console 會永遠健康檢查失敗。
# 代價要說清楚：這一條是 fail-open 的，因此 RW-10 必須用真實的
# `curl -I http://<domain>` 證明外部 http 確實拿到 301，而不是相信這段註解。
map $http_x_forwarded_proto $cliora_insecure {
    default  0;
    http     1;
}

server {
    listen ${PORT};
    server_name _;

    resolver ${NGINX_LOCAL_RESOLVERS} valid=10s ipv6=on;
    resolver_timeout 5s;

    if ($cliora_insecure) { return 301 https://$host$request_uri; }

    # ... security header 集合（每個 location 重複）...

    location /ws/ {
        set $cliora_upstream "${CLIORA_BACKEND_HOST}:${CLIORA_BACKEND_PORT}";
        proxy_pass http://$cliora_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;   # edge 已終結 TLS；讓 Central 看到真實的對外協定
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
        proxy_cache off;
    }

    location /api/ {
        set $cliora_upstream "${CLIORA_BACKEND_HOST}:${CLIORA_BACKEND_PORT}";
        proxy_pass http://$cliora_upstream$request_uri;
        # ... 其餘同 compose 版，proxy_read_timeout 240s（> daemon update 的 180 s 預算）
    }

    location = /api/metrics { return 404; }
}
```

三個容易踩到的細節：

1. **envsubst 只會替換 `${VAR}` 形式且在其變數清單內的名稱**。nginx 自己的變數要寫成 `$host`、`$request_uri`（無大括號），否則會被 envsubst 吃掉變成空字串。這是這份 template 最容易產生「設定看起來對、行為完全錯」的地方。
2. **`proxy_pass` 一旦帶變數就必須自己接 URI**。`proxy_pass http://$upstream;`（無 URI）會丟掉路徑；`$request_uri` 才包含原始路徑與 query string——而 terminal WS 的 `?ticket=…` 就在 query string 裡，掉了就是所有終端機握手失敗。
3. `resolver … ipv6=on` 是預設值，但明寫出來，因為私網只有（或優先）AAAA 記錄。

### 2.4 `console.railway.json`

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "deploy/railway/console.Dockerfile",
    "watchPatterns": [
      "frontend/**",
      "deploy/railway/console.Dockerfile",
      "deploy/railway/nginx.conf.template",
      "deploy/railway/console.railway.json"
    ]
  },
  "deploy": {
    "healthcheckPath": "/edge-health",
    "healthcheckTimeout": 60,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "drainingSeconds": 5,
    "overlapSeconds": 0
  }
}
```

`drainingSeconds: 5` 對 console 就夠：它不持有 session 狀態，靜態請求很短。**但要理解代價**：console 重新部署會切斷經過它的 WebSocket。因此 `watchPatterns` 只列前端與 edge 設定——後端改動不應該重啟 edge。

服務層設定：服務名 `console`；公開網域＝自訂網域（RW-07）；replica 1；region `asia-southeast1`；變數 `PORT=8080`、`CLIORA_BACKEND_HOST=central.railway.internal`、`CLIORA_BACKEND_PORT=8080`、`VITE_PRODUCT_NAME=Cliora`；Config as code path 指向 `deploy/railway/console.railway.json`。

## 3. RW-07：自訂網域與公開身分

### 3.1 順序（不可調換）

1. 在 `console` 服務加自訂網域，設好 DNS，等憑證簽發完成。
2. 把 `central` 的 `CLIORA_PUBLIC_BASE_URL` 設為 `https://<自訂網域>`，重新部署。
3. 之後才開始 enroll 任何 node。

理由：`CLIORA_PUBLIC_BASE_URL` 會進入 `POST /api/nodes/register` 的回應與 installer，最終寫進每個 node 的 `/etc/agentd/config.yaml`。先用 `*.up.railway.app` enroll、之後才換網域，等於要對每一台 node 執行 `agentd register`。這一項與 `CLIORA_TOKEN_PEPPER` 同列「單向門」。

### 3.2 驗收

```bash
D=<自訂網域>
curl -sSI  http://$D/            | head -1                 # 301
curl -sSI  https://$D/           | grep -Ei 'strict-transport|content-security|x-frame|referrer|permissions|cross-origin'
curl -sS   -o /dev/null -w '%{http_code}\n' https://$D/api/metrics    # 404
curl -sS   -o /dev/null -w '%{http_code}\n' https://$D/readyz         # 200
curl -sSI  https://$D/assets/$(curl -sS https://$D/ | grep -o 'assets/[^"]*\.js' | head -1 | cut -d/ -f2) | grep -i cache-control   # immutable
curl -sSI  https://$D/ | grep -i cache-control                        # no-store
```

再加一項只有真實瀏覽器能證明的：開啟 console → 登入 → 進入一個 session，確認 **Monaco 預覽可正常渲染**（CSP 的 `worker-src 'self' blob:` 生效）且**終端機有輸出**（WS 走同一 origin）。`verify-deployment.sh` 會做前者的 header 檢查，但「Monaco 是不是白屏」這件事只有瀏覽器知道——P4 的報告已經為這個具體失敗模式付過學費。

## 4. 兩份 nginx 設定的漂移防護

`scripts/railway/check-edge-parity.sh` 比對 `deploy/nginx/nginx.conf` 與 `deploy/railway/nginx.conf.template`，任一項不符即非零 exit：

| 檢查項 | 判準 |
|---|---|
| CSP 字串 | 兩檔中出現的 `Content-Security-Policy` 值集合完全相同，且各自內部所有出現處一致 |
| security header 名稱集合 | HSTS、`X-Content-Type-Options`、`Referrer-Policy`、`X-Frame-Options`、COOP、`Permissions-Policy` 六項在兩檔的每個「有 `add_header` 的 location」都出現 |
| `client_max_body_size` | 兩檔相同且 ≥ 16m |
| `/ws/` 的 `proxy_read_timeout` | 兩檔相同且 ≥ 300s |
| `= /api/metrics` | 兩檔都存在且為 `return 404` |
| `/assets/` 與 `/` 的 `Cache-Control` | immutable / no-store，兩檔一致 |

掛進 `make check`（新增 target `edge-parity`，加入 `check` 的依賴），並在 `traceability/gates.json` 註冊為 `GATE-RAILWAY-EDGE-PARITY`（layer `static`、owner `operations`、trigger `pull_request`/`main`/`release`）。

這支腳本刻意只做**字串一致性**，不解析 nginx 語意——行為正確性由 `verify-deployment.sh` 對真實網域執行來證明。分工與 P4 相同：靜態檢查擋漂移，執行檢查擋錯誤。

## 5. 已知取捨

| 取捨 | 說明 |
|---|---|
| `/readyz` 對外可讀 | 回傳 `database`、`daemon_connected` 兩個布林。compose 版行為相同；外部 uptime 檢查需要它。若不接受，改為只允許特定來源，但會失去平台外監控能力——本期選擇維持公開並在 ADR 記錄 |
| HTTP→HTTPS 為 fail-open | 沒有 `X-Forwarded-Proto` 時不重導（為了平台內部探測）。必須由 RW-10 對真實 http 請求驗證 301 |
| console 重新部署會切斷 WS | 靜態資源與 edge 設定的改動會斷線一次。`watchPatterns` 把後端改動排除在外，讓這種斷線只發生在真的改了 edge 時 |
| 多一跳代理 | 瀏覽器 → Railway edge → console nginx → central。多一次進程內轉發，對 terminal 延遲的影響須併入 RW-11 的量測，不假設可忽略 |
