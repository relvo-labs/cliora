# 05 — 邊緣、API 與前端（TN-09、TN-10、TN-11）

## TN-09：Edge、CSP 與 wildcard 網域

### 1.1 兩份 nginx 都要新增 wildcard server block

`deploy/nginx/nginx.conf`（單機）與 `deploy/railway/nginx.conf.template`（Railway）各新增一個 `server` block：

```nginx
server {
    listen 443 ssl;                      # Railway 模板為 listen $PORT;
    # 只做粗分流：第一個 label 是 26 字元 base32。**zone 字串不寫在這裡**——
    # 權威判定在 Central 的 host gate（§TN-08 §2.1），所以 zone 只存在
    # CLIORA_TUNNEL_BASE_DOMAIN 一個地方，nginx 與 settings 之間沒有漂移面。
    # 附帶好處：Railway 模板不必把 zone 塞進 regex（envsubst 會把值原樣插入，
    # 而未轉義的 `.` 在 regex 裡匹配任意字元）。
    server_name ~^[0-9a-z]{26}\.;

    # 這個 server 不服務任何靜態檔、不套 console 的 header 集合（ADR 0022 §CSP）。
    # 它只有一件事：把一切原樣交給 Central，並保留原始 Host。
    location / {
        proxy_pass http://$cliora_upstream$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Host $host;             # host gate 依賴這一個值
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;  # WS upgrade（HMR）
        proxy_set_header Connection $connection_upgrade;
        proxy_request_buffering off;             # 串流上傳
        proxy_buffering off;                     # 串流下載與 SSE
        proxy_read_timeout 3600s;                # WS 長連線；HTTP 的上界在 Central
        client_max_body_size 32m;                # 與 tunnel_request_body_max_bytes 一致
    }
}
```

| 決定 | 理由 |
|---|---|
| `server_name` 用**正則限定 26 字元 base32 label**，但**不含 zone** | 不是「任何子網域都轉給 Central」：多一層子網域、大寫、超長 label 在 edge 就落到預設 server。zone 的比對交給 Central（單一來源），因此不合的 host 得到 404 而非被 edge 靜默吞掉 |
| 既有的 `server_name _;`（`deploy/nginx/nginx.conf:99`）不必改 | nginx 的匹配順序是 exact → wildcard → **regex** → default，所以新 block 會先中。憑證可**逐 server block 各掛一張**，console 那張不必重簽 |
| 憑證必須用 **DNS-01** 簽發 | HTTP-01 簽不出 wildcard。這是與現有 `fullchain.pem` 不同的簽發流程，屬於 `TN-02` #2 的實測範圍；若網域走 Cloudflare 代理，深度 2 的 `*.t.<domain>` 不在 Universal SSL 內，需 ACM 或改用獨立 apex（見 `01-…md` §2.1 對 D3 的影響） |
| 不套 console 的 header | D20。若 tunnel host 也送 `frame-ancestors 'none'`，iframe 會被自己的 CSP 擋掉——而症狀會像是「app 拒絕被內嵌」，是最難查的一種 |
| `proxy_buffering off` 兩個方向 | 沒有它，SSE 與串流下載會被 nginx 緩衝到結束才送出，看起來像「app 很慢」 |
| `client_max_body_size` 與 settings 對齊 | 兩個上限不一致的症狀是 413 從 edge 回而錯誤碼不是平台的 `TUNNEL_BODY_TOO_LARGE`，使用者拿到一個 nginx 的預設頁面 |
| **必須新增 `map $http_upgrade $connection_upgrade` 到 `http` block** | 既有的 `/ws/` location 是純 WS，所以寫死 `proxy_set_header Connection "upgrade"`（`deploy/nginx/nginx.conf:141`）。tunnel 的 location 同一個路徑上同時有普通 HTTP 與 WS upgrade，寫死 `upgrade` 會讓普通請求帶著一個不該有的 `Connection` header 到 Central。`map`（`default upgrade; '' close;`）是唯一正確的形狀，且兩份設定都要加 |
| `proxy_read_timeout 3600s` | HTTP 的實際上界由 Central 的 `tunnel_stream_total_seconds`（300s）決定；edge 只需要不比它早殺 |

### 1.2 CSP：四處字串一起改

`frame-ancestors 'none'` → `frame-ancestors 'self'`（console 頁面本身仍不得被外部內嵌）並新增 `frame-src 'self' https://*.t.<domain>`。四個位置：

| 檔案：行 | 內容 |
|---|---|
| `deploy/nginx/nginx.conf:134` | WS/API server 的 CSP |
| `deploy/nginx/nginx.conf:221` | `/assets/` |
| `deploy/nginx/nginx.conf:236` | SPA fallback |
| `deploy/railway/nginx.conf.template:114`、`:203`、`:216` | 同上三處 |

`scripts/railway/check-edge-parity.sh` 會在兩份不一致時失敗（`make railway-check`）。**zone 是部署變數，但 CSP 是靜態字串**——這是一個真實的張力，處理方式：兩份設定都以模板變數帶入 zone，parity 腳本比對「模板展開前」的字串，並新增一項斷言「`frame-src` 的來源與 `CLIORA_TUNNEL_BASE_DOMAIN` 一致」（在 `scripts/railway/tests` 內以固定輸入測）。若 zone 未設定，兩份都不得出現 `frame-src`——功能關閉時不留下放寬的 CSP。

### 1.3 Railway 與 compose 的設定差異

| 項目 | compose | Railway |
|---|---|---|
| wildcard DNS | 使用者自己的 DNS，`*.t.<domain>` → edge | 自訂網域加 wildcard（`TN-02` #3 實測） |
| TLS | 現有 `CLIORA_TLS_DIR` 需一張含 `*.t.<domain>` 的憑證 | 平台 edge 終結（ADR 0020 §7），wildcard 憑證由平台簽發（實測） |
| 變數 | `.env` 加 `CLIORA_TUNNEL_BASE_DOMAIN` | `deploy/railway/env.md` 新增一列，`console` 與 `central` 兩個服務都要（console 用於 nginx 模板，central 用於 host gate） |

`docs/deployment.md` 與 `docs/deployment-railway.md` 各補一節：如何設定 zone、如何確認 `TN-02` 六項、以及**未設定 zone 時功能關閉是預期行為**。

### 1.4 驗收

- `make railway-check` 全綠（含新增的 `frame-src` 一致性測試）。
- `scripts/tunnel/verify-zone.sh` 對 staging zone 六項通過（`TN-02` §2.1）。
- 對 tunnel host 取 header：無 CSP、無 HSTS、無 `X-Frame-Options`；對 console host 取 header：CSP 含 `frame-src` 且只有 zone 一個來源。

---

## TN-10：REST API 與稽核

### 2.1 端點（`backend/app/api/http/tunnels.py`）

| 方法 | 路徑 | action | 回應 |
|---|---|---|---|
| `GET` | `/api/tunnels?node_id=&mine=` | `tunnel.view` | `TunnelSummary[]` |
| `POST` | `/api/tunnels` | `tunnel.manage` | `TunnelDetail`（201） |
| `DELETE` | `/api/tunnels/{id}` | `tunnel.manage` + `may_close_tunnel` | 204 |
| `POST` | `/api/tunnels/{id}/extend` | `tunnel.manage` + `may_close_tunnel` | `TunnelDetail`（新 `expires_at`，上限 `tunnel_max_ttl_seconds`） |
| `POST` | `/api/tunnels/{id}/access` | `tunnel.view` + `may_access_tunnel` | `{url}`（一次性 ticket，`04-…md` §2.2） |

`TunnelSummary` 欄位：`id`、`node_id`、`node_name`、`port`、`label`、`url`、`state`、`created_by_username`、`created_at`、`expires_at`、`capabilities{can_close, can_access}`。

| 決定 | 理由 |
|---|---|
| `state` 由伺服器推導（`active` / `unavailable` / `expired` / `closed`） | 沒有 DB 欄位（`02-…md` §2.1）。`unavailable` = row 活著但 node 的 data-plane 沒連線 |
| `capabilities` 由伺服器算 | 沿用 `SessionSummary.capabilities` 與 `can_open_shell`（`SessionWorkspaceView.vue:51`）的既有做法：UI 隱藏按鈕從來不是授權 |
| 建立時 `port` 由 body 帶，**不接受 host／scheme／path** | 契約層面已經沒有這些欄位，API 層也不得新增 |
| 所有端點在 `tunnel_base_domain` 為空時回 **404** | 功能關閉是明確狀態（D2）。回 501／403 會讓 UI 需要處理第三種狀態 |

`frontend/src/api/client.ts` 新增五個方法（沿用 `openShell`／`listSessions` 的形狀）；`api/dto.ts` 新增型別與兩個 `ACTION_*` 常數。

### 2.2 稽核（三個 action）

`app/services/audit.py` 新增 `TUNNEL_CREATE = "tunnel.create"`、`TUNNEL_CLOSE = "tunnel.close"`、`TUNNEL_ACCESS_DENIED = "tunnel.access_denied"`，並加入 `ALL_ACTIONS`（`:78`）。每個都必須有真實寫入點，否則 `test_every_audit_action_has_a_write_site` 會失敗。

| action | metadata | 明確不含 |
|---|---|---|
| `tunnel.create` | `node_id`、`port`、`slug`、`expires_at`、`target_reachable` | `label`（自由文字） |
| `tunnel.close` | `node_id`、`port`、`slug`、`reason`（`user`／`expired`／`node_removed`） | — |
| `tunnel.access_denied` | `slug`、`reason`（`no_cookie`／`wrong_tunnel`／`expired_cookie`／`no_permission`／`not_found`） | 請求路徑、query、header、UA |

`tunnel.access_denied` 有一個**節流**要求：一個被機器人掃過的 zone 會產生大量 401。決定：**每 (slug, reason) 每分鐘最多一列**（process-local 計數，超出的只進 `tunnel_access_denied_total` 計數器）。理由與 `ADR 0016` 對「不稽核一般讀取 403」的判斷相同——把訊號埋在噪音裡等於沒有訊號。`reason = not_found` 額外只在**存在過的 slug**上記錄，隨機掃描一律只計數不落列。

`frontend/src/utils/auditActions.ts` 新增三個動作的中文標籤。

### 2.3 驗收

- 端點測試：五個端點 × 三角色的授權矩陣；`tunnel_base_domain` 為空時全部 404；`extend` 超過上限被拒。
- 稽核測試：三個 action 各有寫入點；節流生效（第二次同 (slug, reason) 不落列但計數器增加）；redaction 測試斷言 metadata 不含路徑／query／header。
- `make test-db` 全綠。

---

## TN-11：前端

### 3.1 Node 詳情頁：Tunnels 區塊

`frontend/src/views/NodeDetailView.vue` 新增一個 `<section class="panel">`（現有六個：System `:221`、Runtimes `:259`、Workspace roots `:275`、系統資源 `:288`、安裝與更新狀態 `:324`、最近錯誤 `:414`）。

內容：

- 表格：port、label、狀態徽章（沿用 `components/common/StatusBadge.vue`）、到期時間（相對時間用 `utils/time.ts`）、建立者、操作（複製 URL／開啟／延長／關閉）。
- 「新增」表單：port（number input，min 1024）、label（選填）、TTL（下拉：8h／24h）。
- **「開啟」不是 `<a href="{url}">`**：必須先呼叫 `/access` 取得帶 ticket 的 URL 再導覽。這一點容易寫錯，因為 `url` 欄位看起來就可以直接開——直接開的結果是 401 頁面。UI 上「複製 URL」複製的是**不帶 ticket 的乾淨網址**（貼給同事，對方登入後在自己的平台上開），並在旁邊一句話說明「此網址需平台登入才能開啟」（D10 的使用者可見形式）。
- node 停用／離線時，區塊顯示原因並停用新增按鈕（`AsyncState.vue` 的既有模式）。

### 3.2 Session Workspace：`WEB` tab

`frontend/src/views/SessionWorkspaceView.vue` 的 `tabs` computed（`:86-110`）新增第四個 tab。沿用 `WorkspaceTabs.vue:12-20` 的既有 `WorkspaceTab` 契約（roving tabindex、`←/→/Home/End`、選中以字重＋底線非僅顏色），**不新增 tab 元件**。

| 面向 | 決定 |
|---|---|
| tab 出現條件 | 使用者持有 `tunnel.view` **且** zone 已設定（由 `/api/auth/me` 或 node detail 回應帶一個 `tunnel_enabled` 旗標）。條件由伺服器合併計算，與 `can_open_shell`（`:51`）同一手法 |
| 面板內容 | 上方一列：tunnel 選擇器（該 node 的活躍 tunnel）＋位址列（顯示 iframe 目前路徑，可編輯後 Enter 導覽）＋重新載入＋「新視窗開啟」；下方 iframe 佔滿剩餘高度 |
| iframe 屬性 | `referrerpolicy="no-referrer"`、`allow=""`（最小化）、**無 `sandbox`**（D19）。`src` 為 `/access` 回來的帶 ticket URL |
| 高度 | flex column + `flex: 1 1 auto; min-height: 0`（plan/09 決策 D3）。**不得用 grid 列樣板依子元素順序決定高度**——plan/09 §1 的三處面板塌陷就是這樣來的，CI 有 grep gate 在擋 |
| 位址列的限制 | 只能改路徑，不能改 host。**跨 origin 的 iframe 讀不到目前 URL**，所以位址列顯示的是「我們最後一次導覽到的路徑」，不是 iframe 的真實位置。這一點要在 UI 上誠實（欄位標籤寫「導覽到」而非「目前位址」），因為做不到就是做不到 |
| 沒有 tunnel 時 | 空狀態＋「到 Node 頁建立」的連結（若持有 `tunnel.manage`，也提供就地建立的表單） |
| app 拒絕內嵌時 | 無法從 iframe 內偵測 `X-Frame-Options` 失敗（跨 origin，`onload` 也會觸發）。決定：**在 `/access` 之前先由後端探測一次**（Central 對該 tunnel 發一個 `HEAD /` 走既有代理路徑，讀回應 header 判斷 `X-Frame-Options`／`frame-ancestors`），結果放在 `TunnelDetail.embeddable`。UI 依此決定是內嵌還是直接顯示「此應用不允許內嵌，請以新視窗開啟」。這是一個明確的伺服器端一次性探測，不是輪詢 |
| 錯誤狀態 | `NODE_OFFLINE`／`TUNNEL_EXPIRED`／`TUNNEL_TARGET_UNREACHABLE`／`TUNNEL_DISABLED` 四種各有文案與可行動的下一步（沿用 `utils/errorCatalog.ts` 讀 catalog 的既有機制，不要在前端硬寫文案） |

### 3.3 不做的事

- **不做多 tunnel 分頁**（一次一個 iframe）。理由同 plan/08 D2 的單一預覽 tab：使用者沒有這個需求，而多 iframe 會讓「哪一個在吃頻寬」變成一個需要 UI 的問題。
- **不做 iframe 內的 DevTools／console 轉發**。跨 origin 讀不到，唯一的做法是注入腳本，而注入是 D14 禁止的。
- **不在 tab 內做 tunnel 建立以外的 node 管理**（延長／關閉留在 Node 頁）。

### 3.4 驗收

- 單元測試（vitest，jsdom）：tab 出現／不出現的三個條件、空狀態、四種錯誤文案、`embeddable=false` 時不渲染 iframe、位址列導覽組出正確的 URL、「複製 URL」複製的是不帶 ticket 的網址（**這一條是安全相關的斷言**：帶 ticket 的網址一旦被複製貼上就是一次性憑證外流）。
- Playwright（`frontend/tests/e2e/tunnel.spec.ts`）：真 node 上跑一個確定性的 web app（`06-…md` §4.2 的 `cmd/faketunnelapp`），在 `WEB` tab 內斷言 iframe 載入、iframe 的 origin **不等於** console 的 origin、WS echo 往返成功、深層路由重新載入後仍可用、切到 `CLI` 再切回來 iframe 不重新載入（`v-show`，plan/08 D4 的同一條規則）。
- 版面：1440×900 與 1000×800 下 iframe 高度 ≥ 面板 clientHeight 的 90%（plan/09 的量測式斷言形狀），整頁無垂直滾動。
