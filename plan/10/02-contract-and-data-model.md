# 02 — 契約 v1.6.0 與資料模型（TN-03、TN-04）

## TN-03：契約 v1.6.0（compatible）

新增訊息型別與兩個 binary kind。`version` 整數仍為 `1`（加法式演進，沿用 1.1.0–1.5.0 的做法）。**必須先於任何 consumer 合併。**

### 1.1 控制面訊息（走既有 node socket，經 `registry.request` 相關聯）

| 型別 | 方向 | payload | 回應 |
|---|---|---|---|
| `tunnel.open` | Central → daemon | `{tunnel_id, port, mode}`；`mode` 目前只有 `"http"` | `tunnel.opened` `{tunnel_id, target_reachable}` 或 `error` |
| `tunnel.close` | Central → daemon | `{tunnel_id}` | `tunnel.closed` `{tunnel_id}` |
| `tunnel.list` | Central → daemon | `{}` | `tunnel.list_result` `{tunnels:[{tunnel_id, port}]}` |

`tunnel.open` 有兩個作用，兩個都不可省：

1. **政策前置檢查**：daemon 依 `tunnel:` 設定驗 port（`03-…md` §1.2），使用者立刻看到「這個 port 不允許」而不是等到第一次請求 502。
2. **建立 `tunnel_id` → port 的權威對照表**。這是整個設計的施力點：資料面訊息**只帶 `tunnel_id`**，port 從不在線上出現，因此篡改資料面也無法指向別的 port（`00-…md` §7 的阻擋規則）。

`target_reachable` 是一次性的 TCP 連線探測結果（`03-…md` §1.4），只針對這一個 port，不是掃描。`false` 不是錯誤——dev server 可能還沒起來，隧道照建，UI 顯示「目前沒有服務在聽」。

**重連後的復原**：daemon 是無記憶的（可能剛重啟）。Central 在收到該 node 的 `node.register` 之後，對所有 `closed_at IS NULL` 且未到期的 tunnel 重送 `tunnel.open`（幂等）。這與 P2 的 attach 復原同一個模式：durable state 在 Central，daemon 只持有活的東西。

### 1.2 資料面訊息（走新的 data-plane socket）

| 型別 | 方向 | payload |
|---|---|---|
| `tunnel.request` | C→D | `{stream_id, tunnel_id, method, target, headers, has_body}` |
| `tunnel.response` | D→C | `{stream_id, status, headers}` |
| `tunnel.body_end` | 雙向 | `{stream_id}` |
| `tunnel.abort` | 雙向 | `{stream_id, code}`；`code` 取自錯誤碼 enum |
| `tunnel.ws_open` | C→D | `{stream_id, tunnel_id, target, subprotocols?, headers}` |
| `tunnel.ws_opened` | D→C | `{stream_id, subprotocol?}` |
| `tunnel.ws_close` | 雙向 | `{stream_id, code, reason?}` |

Schema 要點（每一條都對應一個 invalid fixture）：

| 欄位 | 規則 | 為什麼 |
|---|---|---|
| `stream_id` | `format: uuid` | 與 binary frame 的 16 byte id 一致 |
| `tunnel_id` | `format: uuid` | 只有這個欄位能決定目的地 |
| `method` | enum：`GET POST PUT PATCH DELETE HEAD OPTIONS` | 封閉集合。`CONNECT`／`TRACE` 不在其中，不是遺漏 |
| `target` | pattern `^/[^\s\x00-\x1f#]*$`，maxLength 4096 | **必須以 `/` 開頭**：絕對 URL 會讓 daemon 端的 `net/http` 把主機當成目的地，那是 SSRF。不含 fragment（瀏覽器本來就不送），不含控制字元與空白（擋 request line 注入） |
| `headers` | `array` of `{name, value}`，name pattern `^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$`，value pattern `^[\t\x20-\x7e\x80-\xff]*$`，最多 64 對，單值 8192，總量 32 KiB | name 用 RFC 9110 的 token 字元集、value 禁 CR/LF：**這是 header 注入與請求走私的機械化守門**，不是格式潔癖。用 array 而非 object 是因為 `Set-Cookie` 等 header 可重複 |
| `status` | integer 100–599 | |
| `has_body` | boolean | 沒有它，daemon 無法區分「空 body」與「body 還沒到」 |
| 全部 payload | `additionalProperties: false` | 禁止出現 `host`／`port`／`url`／`scheme`（`00-…md` §7） |

### 1.3 Binary frame：kind 3 與 kind 4

沿用既有 18 byte header（`1` byte version、`1` byte kind、`16` byte id），**id 欄位在 kind 3／4 是 stream id，不是 session id**：

| kind | 內容 | 上限 |
|---|---|---|
| 3 | HTTP body chunk（請求或回應，方向由 socket 方向決定） | 64 KiB（`MAX_PAYLOAD`） |
| 4 | WebSocket message：**第 1 個 payload byte 是 opcode**（`0x01` text、`0x02` binary），其後為訊息內容 | 64 KiB |

kind 4 為什麼不與 kind 3 共用：WS 的 text／binary 區別必須保留（瀏覽器端 `send()` 的型別要對上），把它藏在 kind 3 裡就得在「HTTP body 也有第一個 byte」的情況下做例外。兩個 kind 讓解碼器能無條件斷言「kind 4 的 payload 至少 2 byte 且首 byte ∈ {1,2}」。

必須放寬的兩處硬編碼：

| 位置 | 現況 | 變更 |
|---|---|---|
| `backend/app/protocol/codec.py:100` | `encode_binary(kind: Literal[1, 2], session_id, payload)` | 允許 `3`／`4`，參數名改為中性的 `stream_or_session_id` |
| 同檔 `:108-118` `decode_binary` | `if kind not in (1, 2)` | 加 `3`／`4`，並對 kind 4 檢查 `len(payload) >= 2 and payload[0] in (1, 2)` |
| `daemon/internal/protocol/codec.go:395-396` | `if (kind != 1 && kind != 2) \|\| len(payload) == 0` | 同上，Go 端同樣的 kind 4 檢查 |
| `frontend/src/protocol/decode.ts` | 只解 kind 1／2 | **不改**：瀏覽器永遠不會看到 tunnel frame（它走 HTTP／WS，不是控制通道）。與 1.3.1 對 filesystem frame 的處理同一個理由 |

`LARGE_FRAME_TYPES`（`codec.py:23`）**不擴充**：tunnel 的控制訊息都是小的，body 走 binary frame 分塊，沒有任何 tunnel JSON frame 需要超過 64 KiB。

### 1.4 錯誤碼（新增九個）

`TUNNEL_NOT_FOUND`、`TUNNEL_DISABLED`、`TUNNEL_PORT_NOT_ALLOWED`、`TUNNEL_LIMIT_REACHED`、`TUNNEL_TARGET_UNREACHABLE`、`TUNNEL_STREAM_LIMIT`、`TUNNEL_BODY_TOO_LARGE`、`TUNNEL_BACKPRESSURE`、`TUNNEL_EXPIRED`。

複用既有碼：`NODE_OFFLINE`（node 沒連線）、`NODE_DISABLED`、`REQUEST_TIMEOUT`（daemon 不回 `tunnel.opened`）、`FRAME_TOO_LARGE`、`INVALID_MESSAGE`、`INTERNAL_ERROR`。

授權失敗**不新增碼**：cookie 無效／過期 → HTTP 401 + `/__cliora/expired` 頁面；無 `tunnel.view` → 403（action 層）。理由與 plan/08 §2.5 相同：能用既有層級表達的，不要在錯誤字典裡多開一個入口。

`TUNNEL_NOT_FOUND` 有一條特殊規則：**slug 不存在、已關閉、已到期三種情況必須回相同的回應**（狀態碼、body、header 全同），否則回應差異就是一個 slug 列舉工具（`TN-13` 第 1 項）。

### 1.5 產物與驗收

| 檔案 | 變更 |
|---|---|
| `contracts/v1/schemas/control-envelope.schema.json` | `type` enum 加 13 個型別；`error.code` enum 加 9 個碼；`allOf` 加對應的 payload `$ref`；`error` 型別的既有規則不動 |
| `contracts/v1/schemas/messages/tunnel-*.schema.json` | 七個新 payload schema（open／opened／close-id／list-result／request／response／ws-open／ws-opened／ws-close），`tunnel-header.schema.json` 為共用的 header 對形狀 |
| `contracts/v1/fixtures/valid/` | `tunnel-open.json`、`tunnel-request-get.json`、`tunnel-request-post-body.json`、`tunnel-response-streaming.json`、`tunnel-ws-open.json` |
| `contracts/v1/fixtures/invalid/` | **四筆黃金測資**：`tunnel-request-absolute-url.json`（`target` 是 `http://…` → 拒）、`tunnel-request-crlf-header.json`（header value 含 `\r\n` → 拒）、`tunnel-request-with-port.json`（多一個 `port` 欄位 → `additionalProperties` 拒）、`tunnel-request-connect-method.json`（`method: "CONNECT"` → 拒） |
| `contracts/v1/fixtures/manifest.json` | 新測資雜湊 |
| `contracts/CHANGELOG.md` | `## 1.6.0 — <日期> (compatible)`：列出新型別、兩個 binary kind 的語意（含 kind 4 的 opcode byte）、九個錯誤碼、**明確寫下「資料面訊息不含任何目標位址欄位；目的地由 `tunnel_id` 在 daemon 端解析」**，以及 data-plane 為獨立 socket 這件事 |

驗收：`make contract` 三語一致（Python 90+／Go／TS）；四筆 invalid fixture 在 Python 與 Go 兩端都被拒且錯誤碼相同；`make traceability-validate` 通過。

---

## TN-04：資料模型、RBAC、settings 與 error catalog

### 2.1 Migration `0014_node_tunnels.py`

現有最新為 `0013_shell_session_parent.py`。

```
node_tunnels
  id            UUID  PK
  node_id       UUID  NOT NULL  REFERENCES nodes(id)      ON DELETE CASCADE
  port          INTEGER NOT NULL                          CHECK (port BETWEEN 1024 AND 65535)
  slug          TEXT  NOT NULL  UNIQUE
  label         TEXT  NULL
  mode          TEXT  NOT NULL  DEFAULT 'http'
  created_by    UUID  NOT NULL  REFERENCES users(id)
  created_at    TIMESTAMPTZ NOT NULL
  expires_at    TIMESTAMPTZ NOT NULL
  closed_at     TIMESTAMPTZ NULL
  closed_by     UUID  NULL      REFERENCES users(id)
  last_stream_at TIMESTAMPTZ NULL

  ix_node_tunnels_node          (node_id)
  ix_node_tunnels_created_by    (created_by)
  uq_node_tunnels_live_port     UNIQUE (node_id, port) WHERE closed_at IS NULL
```

| 決定 | 理由 |
|---|---|
| `CHECK (port BETWEEN 1024 AND 65535)` | D8 的「`<1024` 一律拒」在資料庫層也成立。三層（DB／Central／daemon）都擋，是因為這一條錯了的後果是把 `sshd` 轉出去 |
| `slug UNIQUE` 而非 PK | slug 永不重用（D12），關閉的 row 保留下來就是它不被重用的機制 |
| `uq_node_tunnels_live_port` 部分唯一 | 同一 node 同一 port 同時只能有一條活的隧道，否則兩個 URL 指同一個服務、關掉一個另一個還通，使用者無法理解。用 `closed_at IS NULL` 過濾才允許「關掉再開」 |
| `expires_at` NOT NULL | TTL 是必要欄位而非選項（D13）。「永久隧道」要靠續期，不靠 NULL |
| 沒有 `status` 欄位 | 狀態是**推導**的：`closed_at` / `expires_at` / node 是否連線三者合成。存一份 status 就會有一份跟事實不同的 status——`registry.compute_status` 已經替 node 做過同樣的決定（`services/registry.py` 末段） |
| `ON DELETE CASCADE` on `node_id` | node 是 soft-delete（`NodeManagementService.remove`），所以這條實務上不會觸發；留著是為了 hard-delete 的維運路徑不會留下孤兒 |

下行 migration 直接 drop table（沒有需要保留的資料），但必須通過 upgrade→downgrade→upgrade 的重複執行測試。

### 2.2 Migration `0015_seed_tunnel_actions.py`

idempotent seed，授予 **Admin 與 Developer** `tunnel.view`＋`tunnel.manage`；**Viewer 不得取得**。沿用 P4 的四種情境測試：clean、repeat、prior-data、**permission contraction**（把權限拿掉也要生效）。

三處必須同步，少一處 `backend/tests/db/test_permission_matrix.py` 就會失敗（不得 skip）：

| 檔案 | 變更 |
|---|---|
| `backend/app/services/rbac.py:26-36` | `TUNNEL_VIEW = "tunnel.view"`、`TUNNEL_MANAGE = "tunnel.manage"` |
| 同檔 `:53-59` | 兩者加入 `_DEVELOPER_ACTIONS`（`:60` 的 `_ADMIN_ACTIONS` 自動繼承，不要重複列）；`_VIEWER_ACTIONS`（`:48`）**不動** |
| `frontend/src/api/dto.ts` | `export const ACTION_TUNNEL_VIEW`／`ACTION_TUNNEL_MANAGE` |

`docs/permission-matrix.md` 以 `scripts/p4/render_permission_matrix.py --write` 重新產生（檔頭已標明是產生檔）。

資源層（`services/authz.py`）新增三個判定，與 action 層分開（ADR 0016 的分層）：

| 判定 | 規則 |
|---|---|
| `may_create_tunnel(user, node)` | `tunnel.manage` **且** node 未停用。node 沒有 owner，所以這裡只有 action + node 狀態 |
| `may_close_tunnel(user, tunnel)` | `tunnel.manage` **且**（`created_by == user` **或** 持有 `node.manage`） |
| `may_access_tunnel(user, tunnel)` | `tunnel.view` **且** tunnel 未關閉未到期。**不做 owner 限定**：多人協作看同一個預覽是這個功能的正常用法（D9），邊界是「必須是平台使用者」 |

### 2.3 Settings（`backend/app/settings.py`）

```python
# --- P10 隧道與反向代理（ADR 0022）---
tunnel_base_domain: str = ""          # 空 → 整個功能關閉（D2）
tunnel_cookie_insecure: bool = False  # 僅開發用；production 由 validator 拒絕
tunnel_default_ttl_seconds: int = 8 * 3600
tunnel_max_ttl_seconds: int = 24 * 3600
tunnels_per_node_max: int = 5
tunnels_per_user_max: int = 10
tunnel_streams_per_node_max: int = 256
tunnel_streams_per_tunnel_max: int = 64
tunnel_request_body_max_bytes: int = 32 * 1024 * 1024
tunnel_stream_queue_max_bytes: int = 2 * 1024 * 1024
tunnel_open_timeout_seconds: float = 10
tunnel_first_byte_timeout_seconds: float = 30
tunnel_stream_idle_seconds: float = 60
tunnel_stream_total_seconds: float = 300
tunnel_ws_idle_seconds: float = 300
tunnel_access_ticket_ttl_seconds: int = 30
tunnel_access_cookie_ttl_seconds: int = 30 * 60
tunnel_access_cache_ttl_seconds: float = 10
```

兩個 validator（沿用該檔既有的 `reject_dev_secrets_in_production` 形狀）：

1. `tunnel_cookie_insecure` 為真且 `environment == "production"` → 啟動失敗。一個沒有 `Secure` 的授權 cookie 在正式環境是明文憑證。
2. `tunnel_base_domain` 非空時必須是合法的、**至少兩段**的網域，且**不得等於 `public_base_url` 的 host**。zone 等於 console 網域會讓 D1 的 origin 隔離在設定層被推翻——這種錯誤要在啟動時就爆，不能等到有人發現 token 被讀走。

每一個常數旁邊都要寫「為什麼是這個數字」，沿用該檔既有的註解密度。特別是 `tunnel_stream_idle_seconds`：它為什麼是閒置而非總時長（SSE），以及 `tunnel_access_cache_ttl_seconds` 為什麼是誠實寫下來的撤銷延遲（D7）。

### 2.4 Error catalog

`backend/app/api/error_catalog.py` 新增九筆（見 `TN-03` §1.4），每筆要填 `http_status`、`message`、`cause`、`next_step`、`retryable`、`audited`、`origin`。`docs/error-catalog.md` 由 `scripts/p4/render_error_catalog.py` 重新產生（不要手改）。

幾筆的 `next_step` 值得先想好，因為它們是使用者唯一會看到的東西：

| 碼 | next_step |
|---|---|
| `TUNNEL_TARGET_UNREACHABLE` | 「請確認該 Node 上的服務正在監聽這個 port（例如 `npm run dev` 是否仍在執行）。」 |
| `TUNNEL_PORT_NOT_ALLOWED` | 「請改用 1024 以上、且在該 Node 允許範圍內的 port。」 |
| `TUNNEL_BACKPRESSURE` | 「這條連線的資料量超過緩衝上限而被中止，其他連線不受影響；重新載入即可。」 |
| `TUNNEL_EXPIRED` | 「隧道已到期。請重新建立，或在到期前延長。」 |

### 2.5 驗收

- `make test-db` 全綠，含 `0014`／`0015` 的 upgrade→downgrade→upgrade 重複執行。
- `backend/tests/db/test_permission_matrix.py` 全綠；三角色對 tunnel 端點各有一例：**Viewer 403（action 層）、Developer 關他人 tunnel 403（scope 層）、Developer 關自己的成功**——三例失敗的層級不同，只測一個看不出另一個是否真的在擋。
- `port` CHECK 約束有一例負向測試（直接 INSERT `port = 22` 必須被資料庫拒絕）。
- settings 的兩個 validator 各有一例負向測試。
- `docs/error-catalog.md` 與 `docs/permission-matrix.md` 為重新產生的結果，diff 只含預期項。
