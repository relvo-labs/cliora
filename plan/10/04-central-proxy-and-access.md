# 04 — Central 代理與存取授權（TN-07、TN-08）

## TN-07：tunnel registry 與 stream manager

### 1.1 兩張 process-local 表

新增 `backend/app/services/tunnels.py`（服務＋registry）與 `backend/app/services/tunnel_stream.py`（stream manager），沿用 `services/registry.py`／`services/terminal_relay.py` 的形狀與註解紀律。

| 表 | 內容 | 生命週期 |
|---|---|---|
| `TunnelDataPlaneRegistry` | `node_id → 連線（websocket、send_lock、送出 queue、活躍 stream 數）` | 隨 data-plane socket 建立／移除。與 `NodeConnectionRegistry` **分開**：控制面斷線不代表資料面斷線，反之亦然，兩者混在一張表裡會讓「node 在線但預覽不通」變成無法表達的狀態 |
| `TunnelRegistry` | `slug → (tunnel_id, node_id, port, expires_at)` 的活躍索引 | 由 DB 載入（啟動時＋每次建立／關閉時更新）。**代理熱路徑不查 DB**：一次頁面載入是數十個請求，每個請求一次 `SELECT` 就是把預覽變成資料庫壓力測試 |

`TunnelRegistry` 的一致性規則：DB 是權威，記憶體是索引。建立／關閉／延期一律先寫 DB 再更新索引；啟動時 `SELECT` 所有 `closed_at IS NULL AND expires_at > now()` 建索引；到期由**惰性檢查**（每次查表比對 `expires_at`）處理，不用背景排程器——理由與 `retention.py` 檔頭相同：本專案沒有背景排程器，也不為了一件事新增一個。

### 1.2 建立與關閉

`TunnelService.create(user, node_id, port, label, ttl)`：

1. action 層 `tunnel.manage` → 資源層 `may_create_tunnel`（`02-…md` §2.2）。
2. `port < 1024` → `TUNNEL_PORT_NOT_ALLOWED`（Central 端擋第一層；DB CHECK 是第二層；daemon 是第三層）。
3. 額度：`tunnels_per_node_max`、`tunnels_per_user_max` → `TUNNEL_LIMIT_REACHED`。
4. node 必須 online（`registry.is_connected` + `compute_status`）→ 否則 `NODE_OFFLINE`；node 停用 → `NODE_DISABLED`。
5. 產生 slug（`security/node_keys.py:_new_ulid_like()` 的小寫輸出，D12），寫 DB（`uq_node_tunnels_live_port` 會擋同 port 重複 → 轉成 409 並回既有那一條的資訊，而不是製造第二個 URL）。
6. 送控制面 `tunnel.open`（`registry.request`，timeout `tunnel_open_timeout_seconds`）。daemon 拒絕 → **rollback DB row**（不留下一條無法使用的隧道）。
7. 稽核 `tunnel.create`，metadata 只含 `node_id`、`port`、`slug`、`expires_at`——**不含 label**（使用者可能把路徑或專案名寫進 label，label 是自由文字，稽核不吃自由文字）。
8. 回傳 `{id, slug, url, port, expires_at, target_reachable}`。

`close(user, tunnel_id)`：`may_close_tunnel` → 寫 `closed_at`／`closed_by` → 移除索引 → 中止該 tunnel 的所有活躍 stream（1 秒內，`00-…md` §1 第 6 項）→ 送 `tunnel.close` → 稽核 `tunnel.close`。**順序重要**：先讓 URL 失效，再通知 daemon。反過來的話有一個窗口是「daemon 已關但 Central 還在放行」。

### 1.3 Stream manager

```
open_http_stream(tunnel, request) -> StreamHandle
open_ws_stream(tunnel, ws_request) -> StreamHandle
```

每個 stream 持有：`stream_id`、`tunnel_id`、`node_id`、方向佇列（BrowserChannel 形狀）、`asyncio.Future` 供 `tunnel.response` 解析、位元組計數、`last_activity`（單調時鐘）。

| 規則 | 值 | 說明 |
|---|---|---|
| 併發上限 | `tunnel_streams_per_tunnel_max`（64）、`tunnel_streams_per_node_max`（256） | 超出 → `TUNNEL_STREAM_LIMIT`（503）。per-tunnel 擋單一應用的連線風暴，per-node 擋多個 tunnel 合起來吃掉 node |
| 佇列 | `tunnel_stream_queue_bytes`（2 MiB／stream） | 超出 → 只中止該 stream（`TUNNEL_BACKPRESSURE`），共用 socket 永不阻塞（D15） |
| 逾時 | 首位元組 30s、閒置 60s、HTTP 總時長 300s、WS 閒置 300s | 全部以單調時鐘計（`clock.monotonic_seconds`），理由同 ws-ticket：牆鐘偏移不得延長任何期限 |
| 清理 | stream 結束（正常／中止／逾時／瀏覽器斷線／data-plane 斷線）一律走同一個 `finally` | 沿用 `registry.request` 的 `finally` 紀律（`services/registry.py` 的註解：總是移除 pending 條目）。**一個沒有 `finally` 的 stream 表就是一個記憶體洩漏** |

`route_*`：data-plane socket 的讀取迴圈把 `tunnel.response`／`tunnel.body_end`／`tunnel.abort`／`tunnel.ws_*` 依 `stream_id` 派送；binary kind 3／4 依 stream id 送進對應佇列。**未知 stream id 一律丟棄並計數**（late／duplicate／已中止），與 `resolve_response` 對未知 request_id 的處理完全相同。

### 1.4 Metrics（`app/metrics.py`）

`tunnel_active_total`（gauge）、`tunnel_streams_active`（gauge）、`tunnel_requests_total{result}`（counter）、`tunnel_bytes_total{direction}`（counter）、`tunnel_request_duration`（histogram）、`tunnel_stream_queue_bytes`（histogram，enqueue 後觀測，理由同 `terminal_relay.route_output` 的註解）、`tunnel_stream_aborted_total{reason}`、`tunnel_access_denied_total{reason}`。

**label 不含 slug、path、port、user**。`result`／`direction`／`reason` 都是封閉詞彙。

### 1.5 驗收

- 單元測試（不需 DB）：stream 生命週期六條路徑各一例、兩個併發上限、backpressure 只殺一條、未知 stream id 被丟棄、逾時四種、data-plane 斷線清空所有 stream。
- DB 測試：建立成功、同 port 重複 409、額度、node offline、daemon 拒絕時 rollback（**斷言 DB 沒有殘留 row**）、關閉後索引與 stream 都清乾淨。
- `pytest backend/tests -q` 與 `make test-db` 全綠。

---

## TN-08：host gate、代理端點與 cookie 授權

### 2.1 Host gate（`app/api/middleware.py`）

一個在最外層的 middleware，依 `Host` 把請求分成兩個互斥的世界：

| Host | 允許的路徑 | 其他一切 |
|---|---|---|
| console host（`public_base_url` 的 host，或任何非 zone 的 host） | 既有全部路由 | `/__cliora/*` 與代理流量 → **404** |
| `<slug>.<tunnel_base_domain>` | `/__cliora/session`、`/__cliora/expired`、以及代理流量（其餘所有路徑與方法） | `/api/*`、`/ws/sessions/*`、`/ws/nodes/*`、`/healthz`、`/readyz`、`/metrics` → **404** |

| 決定 | 理由 |
|---|---|
| 兩個方向都擋 | `FR-TUNNEL-002.AC-04`。沒有這條，一個被 XSS 的 app 頁面就能對同 host 的 `/api` 發請求；即使它拿不到 Bearer token，這個表面也不該存在 |
| 用 404 而不是 403 | 403 會確認「這個路徑在這個 host 上存在但你不能用」。404 什麼都不確認 |
| `tunnel_base_domain` 為空時 | 整個代理分支不註冊，middleware 退化成 no-op。**功能關閉是一個明確狀態，不是一個旗標**（D2） |
| slug 解析 | 只接受 `<26 字元 base32>.<zone>` 的精確形狀；多層子網域（`a.b.<zone>`）→ 404 | 避免「`evil.<slug>.<zone>` 是誰」這種問題存在 |

`Host` 來自 edge（`nginx` 保留原始 Host，`TN-09`）。**Central 不信任 `X-Forwarded-Host` 做 host gate 判定**：那是一個可被客戶端偽造的 header，而這裡的判定決定了 `/api` 是否存在。

### 2.2 授權交握（三跳）

```
① console origin
   POST /api/tunnels/{id}/access        （Bearer JWT；tunnel.view + may_access_tunnel）
   → 200 {url: "https://<slug>.<zone>/__cliora/session?ticket=<one-shot>&to=%2F"}

② tunnel host
   GET  /__cliora/session?ticket=…&to=…
   → 消費 ticket（一次性、TTL 30s）
   → Set-Cookie: __Host-cliora_tunnel=<簽章 token>; Secure; HttpOnly;
                 SameSite=None; Partitioned; Path=/; Max-Age=1800
   → 302 到 `to`（只接受以 `/` 開頭的相對路徑，否則導向 `/`）

③ tunnel host
   後續所有請求帶 cookie；middleware 驗證 → 代理
```

| 決定 | 理由 |
|---|---|
| ticket 用既有 `WsTicketService` 的形狀但**獨立實例** | 一次性、TTL 30s、單調時鐘、綁 `(user, resource="tunnel:<id>")`。共用同一個實例會讓 terminal ticket 與 tunnel ticket 的 TTL 政策綁在一起 |
| cookie 值是**獨立簽發的 JWT**（`aud="tunnel"`、`sub=user_id`、`tid=tunnel_id`、`exp`），用同一個 `jwt_secret` | 無狀態，所以 Central 重啟不會讓所有 iframe 同時掉線（in-memory ticket 會）。`aud="tunnel"` 讓它在 `/api` 的 Bearer 驗證處必然失敗（`FR-TUNNEL-002.AC-03`），這一條要有測試 |
| `__Host-` 前綴 | 禁止 `Domain` 屬性、強制 `Secure` 與 `Path=/`。zone 內任一 app 因此無法覆寫別人的授權 cookie（cookie tossing） |
| `SameSite=None; Partitioned` | iframe 內是 cross-origin 情境。`Partitioned`（CHIPS）讓它在第三方 cookie 分割下仍可用，且被綁在 console 這個 top-level 網站的分割區內——比 `SameSite=None` 單獨使用更嚴 |
| `to` 參數的白名單 | 只接受相對路徑。開放重導向在一個「使用者被訓練成會點平台給的連結」的產品裡是真的會被利用的 |
| `/__cliora/session` 的回應必須帶 `Referrer-Policy: no-referrer` | 沒有它，302 之後瀏覽器會把**帶 ticket 的 URL 當成 `Referer`** 送給 app，於是一次性憑證出現在 dev server 的 access log 裡。ticket 只有 30 秒且已被消費，危害有限，但這是零成本可關掉的縫。**這是 tunnel host 上唯一由平台加上的回應 header**——它加在 `/__cliora/*` 上，不加在代理流量上，所以不違反 D14 |
| dev 環境 | `tunnel_cookie_insecure=true` 時省略 `Secure`／`Partitioned`（`<slug>.tunnel.localhost` 在 Chrome／Firefox 上被視為可信來源，通常不需要）；production 由 validator 拒絕（`02-…md` §2.3） |

**每次請求的驗證順序**（全部失敗都導向 `/__cliora/expired`，401）：

1. cookie 存在且簽章有效、`aud == "tunnel"`、未過期。
2. `tid` 對應的 slug 與 `Host` 一致（一個 tunnel 的 cookie 不能用在另一個 tunnel 的 host）。
3. tunnel 在 `TunnelRegistry` 中活躍且未到期。
4. `(user, tunnel)` 的授權在 10 秒正向快取內為真；快取未命中則查 DB（使用者未停用、仍持有 `tunnel.view`）。這就是 D7 誠實寫下來的撤銷延遲。

### 2.3 代理端點

```python
@router.api_route("/{path:path}", methods=[...])   # 僅在 tunnel host 上掛載
async def proxy(...) -> StreamingResponse
@router.websocket("/{path:path}")
async def proxy_ws(...)
```

| 面向 | 做法 |
|---|---|
| 請求 body | 以 ASGI `receive()` 邊讀邊送 kind 3 frame；累計超過 `tunnel_request_body_max_bytes` → 413 `TUNNEL_BODY_TOO_LARGE`，並中止 stream |
| 回應 | `StreamingResponse`，`status` 與 header 來自 `tunnel.response`。**首位元組之前不送 header**，所以 `TUNNEL_TARGET_UNREACHABLE` 可以變成一個乾淨的 502 錯誤頁；一旦 header 已送出，後續失敗只能中斷連線（HTTP 沒有第二次機會，這一點要寫進 runbook） |
| `target` | `path` + 原始 query string 原樣組合。**不做 URL 正規化**（不 decode 再 encode）：`%2F` 與 `/` 對某些框架的路由是不同的東西，正規化會改變語意 |
| header 白名單 | 見 §2.4 |
| WebSocket | `websocket.accept(subprotocol=…)` 只在收到 `tunnel.ws_opened` 之後；失敗則以 close code 1011＋原因關閉，不 accept 一個註定失敗的連線 |
| 瀏覽器斷線 | `WebSocketDisconnect`／`ClientDisconnect` → `tunnel.abort`，讓 node 端也停止讀取（否則一個關掉的分頁會讓 dev server 繼續產出到一個沒人收的佇列） |

### 2.4 Header 政策（Central 端）

**請求方向轉發**（白名單，最多 64 對）：`accept`、`accept-encoding`、`accept-language`、`content-type`、`content-length`、`content-encoding`、`if-none-match`、`if-modified-since`、`range`、`user-agent`、`referer`、`origin`、`sec-websocket-*`、`sec-fetch-*`、`x-requested-with`、`cache-control`、`pragma`。

**明確不轉發**：`cookie`、`authorization`（`03-…md` §2.3 的取捨）、`host`、全部 hop-by-hop、全部 `x-forwarded-*`（由 daemon 端重新產生，避免客戶端偽造）。

**回應方向**：原樣轉發，除 hop-by-hop 與 `03-…md` §2.3 的三項處理。**Central 不加 `Content-Security-Policy`、不加 `X-Frame-Options`、不加 HSTS**（D20：tunnel host 不套 console 的 header 集合）。

一個容易被漏掉的細節：`content-length` 與 `transfer-encoding` **不得同時出現在轉發結果**。Central 用 `StreamingResponse` 時由 uvicorn 決定 chunked，所以若 `tunnel.response` 帶了 `content-length`，要嘛沿用它並保證位元組數相符，要嘛移除它。**決定：移除 `content-length`，一律 chunked。** 理由：daemon 端已在串流，位元組數在中止情境下無法保證相符，而一個不相符的 `content-length` 是最典型的請求走私前提。代價是瀏覽器看不到下載進度百分比——寫進 `docs/tn-report.md` 的已知限制。

### 2.5 驗收

- host gate：兩個方向各三例（console host 上打代理路徑 404、tunnel host 上打 `/api` 404、tunnel host 上打 `/ws/sessions/x` 404、偽造 `X-Forwarded-Host` 不改變判定、多層子網域 404、zone 未設定時代理路徑不存在）。
- 授權：無 cookie 401、他人 tunnel 的 cookie 401、cookie 當 Bearer 打 `/api` 失敗、ticket 二次使用失敗、`to` 為絕對 URL 時導向 `/`、tunnel 關閉後 cookie 立即失效。
- 代理：GET／POST／PUT／PATCH／DELETE／HEAD／OPTIONS 七個方法各一例；query 原樣（含 `%2F`）；`range` 請求；SSE 保持 3 秒；WS text／binary 往返；body 超限 413；`content-length` 不出現在回應。
- 回應位元組**逐 byte 相同**（拿一個 1 MiB 的二進位檔比對 sha256）——這是 `FR-TUNNEL-003.AC-03`「不改寫」的機械化證明。
- `pytest backend/tests -q`、`make test-db` 全綠。
