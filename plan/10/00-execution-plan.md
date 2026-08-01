> **⚠️ 已作廢（2026-08-01）。** 改以整合第三方隧道服務交付，見 [plan/11](../11/)。
> 作廢理由與「哪些結論被沿用、哪些被反轉」見 [README.md](./README.md) 開頭。
> 以下內容保留為 plan/11 的替代方案論證與日後自建的現成規格，**不得據此開工**。

# 00 — 執行總控（埠轉發隧道與反向代理）

## 1. 成功定義

本期要交付一件事，並且不得在交付它的過程中弄壞三件既有的事。

**要交付的：** 平台上的一個 node 可以被指定「轉出 port N」，平台生成一個穩定網址，任何以 HTTP／WebSocket 說話的應用都能透過該網址在平台內（iframe）或新視窗中使用；node 上不新增任何對外監聽埠。

**不得弄壞的：**

1. **終端機延遲。** `NFR-001`。隧道流量與終端機位元組不得共用同一條 socket 的寫入序（決策 D5），且必須以量測證明（`TN-14` §3）。
2. **console 的 token。** `frontend/src/stores/auth.ts:20-21` 把 access／refresh token 放在 `localStorage`。被代理的應用必須位於**不同 origin**（決策 D1），否則它的任何一行 JS 都能讀走平台憑證。
3. **daemon 只出不進。** tech §3.2。資料面是 daemon 主動撥出的第二條 WebSocket，不是 Central 連進 node（決策 D5）。

成功的判準不是「畫面出來了」，而是這六項**可量測／可對抗**的條件：

1. 未帶授權 cookie 開啟 tunnel 網址 → **401**，且回應對「這個 slug 是否存在」保持一致（不可用回應差異列舉 tunnel）。
2. 深層路由（`/a/b/c?x=1`）、絕對路徑資產（`/assets/*`）、`POST` 表單、SSE 與 WebSocket 五種請求形態各有一個通過的自動測試，且**回應內容位元組不變**（無改寫）。
3. `port < 1024`、node 明確停用、非允許清單內的 port → 三種都被拒，且拒絕發生在 **Central 與 daemon 兩層**。
4. 一條隧道以 ≥8 MiB/s 傳輸時，同 node 上終端機按鍵往返 p95 退化 ≤10 ms（量測，1 分鐘取樣）。
5. 稽核與 log 中不存在請求路徑、query、header 值或 body（redaction 測試）。
6. 關閉 tunnel 後，進行中的 stream 在 1 秒內被中止，slug 立刻失效且永不重用。

## 2. 範圍

### 納入

- 契約 v1.6.0：控制面 `tunnel.open`／`tunnel.opened`／`tunnel.close`／`tunnel.closed`／`tunnel.list`／`tunnel.list_result`，資料面 `tunnel.request`／`tunnel.response`／`tunnel.body_end`／`tunnel.abort`／`tunnel.ws_open`／`tunnel.ws_opened`／`tunnel.ws_close`，binary kind **3**（HTTP body chunk）與 **4**（WebSocket message）（`TN-03`）。
- `node_tunnels` 資料表、`tunnel.view`／`tunnel.manage` 兩個 action、settings 與 error catalog（`TN-04`）。
- daemon：第二條 data-plane WSS 連線、`tunnel:` 設定區塊與 port 政策、tunnel_id→port 註冊表、HTTP／WS 中繼、有界佇列與逾時、metrics 與 `doctor` 檢查（`TN-05`、`TN-06`）。
- Central：tunnel registry 與 stream manager、host-based 分流、代理端點（HTTP 全動詞 + WS upgrade）、一次性 ticket → 短期 cookie 的授權交握、header 政策（`TN-07`、`TN-08`）。
- Edge：兩份 nginx 的 wildcard server block 與 CSP `frame-src` 同步、Railway wildcard 自訂網域、parity gate（`TN-09`）。
- REST API（建立／清單／關閉／鑄 access ticket）與稽核（`TN-10`）。
- 前端：Node 詳情 Tunnels 區塊、Session Workspace `WEB` tab（`TN-11`）。
- traceability、安全審查、NFR 量測、evidence／CI／runbook／exit gate（`TN-12`–`TN-15`）。

### 不納入（本期）

- **匿名／公開分享的 URL。** 決策 D10，並以 `SCOPE-013` 寫進 PRD 成為受守門的非目標。這是本功能與 ngrok 的根本差異：URL 不是憑證。
- **自訂網域與使用者自選 slug。** slug 由系統產生（D12）。自選 slug 會讓「slug 永不重用」與「不可枚舉」兩條性質同時失效。
- **非 HTTP 協定（raw TCP／UDP／gRPC over HTTP/2 明文）。** 決策 D4。gRPC-web 與 HTTP/1.1 上的一切都可用；HTTP/2 專屬功能（server push、明文 h2c）不支援。
- **node 端主動偵測「哪些 port 有服務在跑」的掃描清單。** 只在 `tunnel.open` 時對指定 port 做一次連線探測回報「目前沒有服務在聽」，不做全埠掃描——那是把 daemon 變成埠掃描器。
- **回應內容改寫（HTML base 注入、URL 重寫、腳本注入、CSP 注入）。** 決策 D14，且列為 PR 阻擋規則。
- **檔案上傳／下載加速、快取層、壓縮再壓縮。** 直通即可；`Content-Encoding` 原樣轉發，Central 不解壓也不重壓。
- **Session-scoped 隧道。** tunnel 是 node-scoped（D11）。
- **多 replica 的分散式 stream 表。** 沿用 ADR 0020 §2 的單 replica 約束。

## 3. 固定基線決策

這些是本目錄後續所有 ticket 的前提。改動任一項要回來改這張表，不要在 ticket 內就地改主意。

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D1 | URL 形式 | **子網域**：`https://<slug>.<tunnel-zone>/…`。**路徑前綴模式為永久非目標** | 兩個獨立的致命理由。(a) **絕對路徑**：`/assets/index-abc.js`、`/@vite/client`、`/socket.io/` 在路徑模式下全部指向 console 而非 app，除非改寫 HTML／CSS／JS／`fetch` 的每一處 URL——那條路沒有終點（sourcemap、CSS `url()`、動態 import、Worker、WS 位址各有一套規則）。(b) **origin 隔離**：token 在 `localStorage`（`stores/auth.ts:20-21`），同 origin 等於把平台憑證交給 node 上任何一個 dev server 與它引入的每一個 npm 套件 |
| D2 | tunnel zone 從哪裡來 | 新設定 `CLIORA_TUNNEL_BASE_DOMAIN`（例：`t.cliora.example.com`），tunnel host 為 `<slug>.<zone>`。**未設定 → 整個功能關閉**：API 回 404、UI 不顯示入口、daemon 不建立 data-plane 連線 | 沒有 wildcard 網域就沒有這個功能的安全形狀（D1）。「先用路徑模式上線，網域之後補」會讓不安全的形狀變成既成事實。關閉比降級誠實 |
| D3 | zone 與 console 的關係 | **由 `TN-02` #2b 的憑證結論決定**，兩個候選都不改程式（只換設定值）：(a) console 網域下的專用子 zone `t.<console-domain>`；(b) 獨立 apex（`*.cliora-preview.dev`） | (a) 是 cross-origin 但 same-site，授權 cookie 不落入第三方 cookie 封鎖／分割的路徑，少一類瀏覽器政策風險；代價是理論上的 cookie tossing（由 `__Host-` 擋掉，D6）。**但憑證這一層可能讓 (b) 反而更便宜**：wildcard 只能走 DNS-01，且 Cloudflare 的 Universal SSL 只涵蓋深度 1 的 `*.<domain>`，(a) 的 `*.t.<domain>` 需要 ACM。(b) 讓 wildcard 回到深度 1，順便把隔離升級成 cross-site —— 代價是 cookie 成為真正的第三方 cookie，而 D6 的 `SameSite=None; Partitioned` 本來就是為這一天寫的 |
| D4 | 資料面語意 | **HTTP 語意中繼 + WebSocket 訊息中繼**，不做 raw TCP | 三個理由。(a) **零新依賴**：瀏覽器側的 HTTP 由 uvicorn 解析完才進 ASGI，node 側由 Go `net/http` 產生與解析，Central 從頭到尾不碰 HTTP 語法；WS 用既有的 `gorilla/websocket`（`daemon/go.mod:8`）。(b) **不提供任意位元組通道**：raw TCP 隧道等於讓遠端把任意 bytes 寫進 node 的 loopback，而 loopback 上常有不做認證的 Postgres／Redis。(c) **政策可施加在語意層**：header 白名單、body 上限、方法政策都能在 schema 驗證得到的欄位上執行，而不是在位元組流裡猜 |
| D5 | 傳輸通道 | **獨立的 data-plane WebSocket**：`/ws/nodes/{node_id}/tunnel`。stream 的 open／data／close 全在此；tunnel 的**生命週期**（open/close/list）走既有控制面 socket | 既有 socket 的寫入是單一 mutex（`connection.go:137-160`）且終端機輸出與控制回應共用它。一個 3 MB 的 source map 排在前面就是一次可見的終端機停頓，而終端機延遲是 `NFR-001` 的承諾。分開之後兩者的佇列、限額、metrics 與重連都獨立。**stream 的所有訊息在同一條 socket 上，所以順序保證不跨 socket** |
| D6 | 瀏覽器如何被授權 | console 端 `POST /api/tunnels/{id}/access` 鑄一次性 ticket → 302 到 `https://<slug>.<zone>/__cliora/session?ticket=…` → 該 host 設 **`__Host-cliora_tunnel`** cookie（`Secure; HttpOnly; SameSite=None; Partitioned; Path=/`）→ 302 到目標路徑 | 瀏覽器導覽送不出 `Authorization` header，所以必須用 cookie；把 JWT 放在 query 每次請求會進 Referer、瀏覽器歷史與 app 自己的 access log。cookie 值是**獨立簽發、只綁 (user, tunnel_id) 的短期 token**，對 `/api` 完全無效（D8）。`__Host-` 前綴禁止 `Domain` 屬性，因此 zone 內任一 app 無法覆寫別人的 cookie |
| D7 | cookie 有效期與撤銷延遲 | cookie TTL 30 分鐘；tunnel 關閉／node 離線 → **立即**失效（走 process-local 活躍表）；使用者停用或降權 → **最多延遲一個 cookie TTL**，且每次 stream open 以 10 秒正向快取回查一次 | 一個頁面載入是數十個請求，每請求查 DB 是把預覽變成資料庫壓力測試。快取窗與 cookie TTL 就是誠實寫下來的撤銷延遲；`dashboard_cache_ttl_seconds` 已是同一種取捨（`settings.py`） |
| D8 | tunnel host 上不得存在 console 表面 | tunnel host 只服務 `/__cliora/*`（授權與錯誤頁）與代理流量。`/api/*`、`/ws/sessions/*`、console 靜態資產在 tunnel host 上一律 **404**；反之 console host 上不服務代理流量 | 沒有這條 host gate，一個被 XSS 的 app 頁面就能對同一 host 的 `/api` 發請求；即使它沒有 Bearer token，也不該有這個表面存在。兩個方向都要擋，且各有一個測試 |
| D9 | RBAC | 新增 `tunnel.manage`（建立／關閉／鑄 access ticket）與 `tunnel.view`（列出、開啟網址），**兩者皆 Admin + Developer；Viewer 一律無** | Viewer 的語意是唯讀，而一個 web app 的唯讀性不由平台決定（app 自己有寫入端點）。給 Viewer `tunnel.view` 等於把「唯讀」的承諾外包給被代理的應用。`tunnel.manage` 的資源邊界由 ownership 承擔：只能關自己建的，Admin（`node.manage`）可關任何人的 |
| D10 | 是否提供匿名 URL | **不提供。** 每一個請求都必須帶有效 cookie，並以 `SCOPE-013` 寫進 PRD §4 成為受守門測試保護的非目標 | URL 若是憑證，那麼「貼到 Slack」等於「公開部署」，而 node 上的 dev server 通常沒有任何認證。以 requirement 形式釘住，才不會在下一期被順手放寬 |
| D11 | tunnel 的歸屬層級 | **node-scoped**（`node_tunnels`），不綁 session。可選記錄一個 `created_by`，UI 上可從 workspace 進入 | 使用者的需求原話是「在平台設定 node 要轉出的 port」。dev server 的生命週期由使用者在 node 上決定，往往比任何一個 CLI session 長；綁 session 會讓預覽在 session 結束時無理由消失 |
| D12 | slug | 26 字元 Crockford base32（重用 `security/node_keys.py:_new_ulid_like`），全小寫輸出以符合 DNS label；**永不重用**，關閉後仍佔用 | 不可枚舉（但不作為授權，D10）。永不重用是為了「舊書籤打到新應用」這個很難察覺的錯誤：同一個網址在不同時間指到不同 app 是最糟的形狀 |
| D13 | 生命週期 | 明確關閉 ∪ TTL 到期（預設 8 小時，最長 24 小時，可延長）∪ node 離線（標記 `unavailable`，不刪除，重連即恢復且 slug 不變）。**不做閒置回收** | dev server 閒著是正常狀態，用閒置回收會在使用者離開午餐回來時關掉他的預覽。TTL 才是對「忘記關」的正確答案。node 離線不刪 row，因為 daemon 重啟是常態（`connection.go:105` 的重連迴圈） |
| D14 | 回應與請求的改寫政策 | **不改寫內容**。header 走白名單＋hop-by-hop 移除；回應 header 原樣通過，但移除 `Set-Cookie` 的 `Domain` 屬性、移除 `Strict-Transport-Security`；不注入 CSP、不注入 script、不改任何 body 位元組 | 子網域方案的全部價值就是不需要改寫（D1）。移除 `Set-Cookie` 的 `Domain` 是擋 cookie tossing（app 不得替整個 zone 設 cookie）；移除 HSTS 是因為那是 zone 的決定不是 app 的。**若 app 自己送 `X-Frame-Options: DENY`，iframe 就會失敗——這時 UI 提供「新視窗開啟」，而不是把該 header 拿掉** |
| D15 | Backpressure 與中止政策 | 每 stream 有界佇列（預設 2 MiB）；per-node 單一寫入 task；某 stream 超出份額 → **只中止該 stream**（`TUNNEL_BACKPRESSURE`），永不阻塞共用 socket | 沿用 `services/terminal_queue.py:22` 的紀律：不要讓一個慢的消費者拖住共用路徑，寧可明確關掉它並計數。阻塞 socket 會讓一個慢客戶端變成同 node 上所有預覽的故障 |
| D16 | 逾時 | 連線建立 5s；請求 header→首位元組 30s；**閒置 60s**（任一方向有位元組即重設）；HTTP stream 總時長 300s；WebSocket 不設總時長，只有閒置 300s + ping | SSE／長輪詢靠「閒置」而非「總時長」判定才不會被誤殺（每個 heartbeat 都重設閒置計時）。HTTP 有總時長上限是為了讓一個被遺忘的下載不會永久佔用 stream 額度 |
| D17 | 稽核與 log | 稽核只有三個 action：`tunnel.create`、`tunnel.close`、`tunnel.access_denied`。**請求路徑、query、header 值、body、回應狀態逐筆一律不記錄**；流量只進 metrics 計數器（label 僅 `node_id`／`result`） | 與 ADR 0004／`TECH-SEC-08` 同一條線。URL 的 query 經常帶 token；逐筆記錄等於把資料面內容搬進 DB。「誰在哪個 node 開過哪個 port」是可稽核的問題，「他載入了哪些頁面」不是本平台要回答的問題 |
| D18 | 契約版本 | **v1.6.0（compatible）**。新增訊息型別與兩個 binary kind，`version` 整數仍為 `1` | 沿用 1.1.0–1.5.0 的加法式演進。binary kind 白名單要同時放寬 `protocol/codec.py:100`（`Literal[1, 2]`）與 `daemon/internal/protocol/codec.go:395-396` |
| D19 | 前端呈現 | Session Workspace 新增 `WEB` tab（沿用 `WorkspaceTabs.vue:12-20` 的既有 tab 契約）；iframe **不加 `sandbox`**，改以 origin 隔離為邊界，並加 `referrerpolicy="no-referrer"`、最小化 `allow` | `sandbox` 會擋掉多數真實 app（同 origin 存取自己的 `localStorage`、彈窗、表單、Worker），加了就要一個一個開回來，最後等於沒加還多了假的安全感。真正的邊界是 D1 的 origin 隔離 |
| D20 | CSP | console 的 CSP 加 `frame-src 'self' https://*.<zone>`；tunnel host 的回應**不套** console 的 CSP／HSTS／`frame-ancestors` header | CSP 字串在四個地方各出現一次（`deploy/nginx/nginx.conf:134,221,236`、`deploy/railway/nginx.conf.template:114,203,216`），已有 parity gate（`scripts/railway/check-edge-parity.sh`）在防漂移。`frame-ancestors 'none'` 目前禁止一切 framing——**這是本期必須改的既有值**，且只放寬到 zone 這一個來源 |

## 4. 目標拓撲與資料流

```text
                console origin: https://cliora.example.com
                ┌──────────────────────────────────────────┐
瀏覽器 ─────────▶│ nginx（console 靜態 + /api + /ws 反代）   │──▶ Central
                └──────────────────────────────────────────┘
                tunnel zone:    https://<slug>.t.cliora.example.com
                ┌──────────────────────────────────────────┐
  iframe ──────▶│ nginx（wildcard server block，全部反代）  │──▶ Central（host gate）
                └──────────────────────────────────────────┘
                                                                │
   控制面（既有 socket）  tunnel.open / close / list ────────────┤
   資料面（新 socket）    tunnel.request / response / ws_* ──────┤
                                                                ▼
                                          daemon（node 上，只出不進）
                                                                │  net/http · gorilla dialer
                                                                ▼
                                                    127.0.0.1:<port>（dev server）
```

一次頁面載入的完整路徑（HTTP）：

| # | 位置 | 動作 |
|---|---|---|
| 1 | 瀏覽器 | `GET https://<slug>.<zone>/settings` 帶 `__Host-cliora_tunnel` cookie |
| 2 | edge nginx | wildcard server block → 全部反代到 Central，保留 `Host` |
| 3 | Central host gate | 由 `Host` 解出 slug → 查活躍表（無則 404）→ 驗 cookie（無效則 401 `/__cliora/expired`） |
| 4 | Central stream manager | 配一個 stream id，檢查 per-tunnel／per-node 併發額度，送 `tunnel.request`（method／path＋query／白名單 header） |
| 5 | daemon | 由 `tunnel_id` 查出 port（**請求裡沒有 port，也沒有 host**）→ `net/http` 對 `127.0.0.1:<port>` 發同樣的請求 |
| 6 | daemon | 回 `tunnel.response`（status＋header）→ kind 3 body chunks → `tunnel.body_end` |
| 7 | Central | 以 ASGI streaming response 邊收邊送；超出佇列份額 → `tunnel.abort` 只殺這個 stream |

WebSocket 的差別只在 4–6：`tunnel.ws_open` → daemon 用 gorilla dialer 連 `ws://127.0.0.1:<port><path>` → `tunnel.ws_opened` → 雙向 kind 4 frame（首位元組為 WS opcode）→ `tunnel.ws_close`。

## 5. 執行波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門，必須先關）** | `TN-01` | ADR 0022、PRD 新增 FR-TUNNEL-001/002/003 與 SCOPE-013、tech 修訂 | — |
| | `TN-02` | 網域與平台事實實測（wildcard DNS／TLS 可行性） | — |
| **1（契約與資料，需 TN-01 核准）** | `TN-03` | 契約 v1.6.0：訊息型別、binary kind 3／4、錯誤碼 | TN-01 |
| | `TN-04` | migration 0014／0015、`tunnel.*` action、settings、error catalog | TN-01 |
| **2（資料面）** | `TN-05` | daemon data-plane 連線、`tunnel:` 設定與 port 政策、tunnel 註冊表 | TN-03 |
| | `TN-06` | daemon HTTP／WS 中繼、有界佇列、逾時、metrics、doctor | TN-05 |
| | `TN-07` | Central tunnel registry 與 stream manager | TN-03、TN-04 |
| | `TN-08` | Central host gate、代理端點、cookie 授權交握、header 政策 | TN-07 |
| **3（邊緣與介面）** | `TN-09` | 兩份 nginx、CSP `frame-src`、Railway wildcard、parity gate | TN-02、TN-08 |
| | `TN-10` | REST API 與稽核 | TN-04、TN-07 |
| | `TN-11` | Node 詳情 Tunnels 區塊、Workspace `WEB` tab | TN-09、TN-10 |
| **4（驗證與退出）** | `TN-12` | traceability 註冊與影響分析 | TN-11（selector 必須與測試同一個 PR） |
| | `TN-13` | 安全審查（13 項對抗） | TN-11 |
| | `TN-14` | NFR 量測（延遲、吞吐、終端機不退化） | TN-11 |
| | `TN-15` | evidence、CI、runbook、release note、exit gate | 全部 |

`TN-05`／`TN-06`（daemon）與 `TN-07`／`TN-08`（Central）可並行開發，但**必須在同一輪整合驗證內收斂**：兩邊各自對契約寫的測試會同時綠，卻可能在對接時發現對 `tunnel.body_end` 的期待不同。`TN-03` 的 golden fixture 是唯一的仲裁者。

## 6. 每張 ticket 的完成格式

1. **產物清單**：新增／修改的檔案逐一列出，含理由。
2. **測試**：新增的自動測試與其斷言對象。「可手動展示」不能替代自動測試；**「單元測試通過」不能替代跨語言 fixture 與端到端實跑**。
3. **規格同步**：本 ticket 動到的 PRD／tech／style／ADR／traceability 條目。
4. **證據**：可重跑的指令與其輸出位置。
5. **未關項**：本機關不掉的（WebKit E2E、真實平台網域）明確標為 CI-gated／staging-gated，不含糊帶過。

## 7. 阻擋規則

### PR 階段

- 出現任何回應內容改寫（HTML／CSS／JS 的 URL 重寫、base 標籤注入、script 注入、CSP 注入）→ 退回（D14）。
- 出現路徑前綴模式的代理端點（`/t/<slug>/…` 或等價形狀）→ 退回（D1，永久非目標）。
- 隧道流量出現在既有 node 控制面 socket 上（`registry.send_binary`／`send_text_frame` 被用來送 stream 資料）→ 退回（D5）。
- 資料面訊息中出現 `host`、`port`、`url`、`scheme` 或任何目標位址欄位 → 退回。目標位址只能由 `tunnel_id` 在 daemon 端查表得到（D4、§4 第 5 步），schema 的 `additionalProperties:false` 是這條規則的機械化守門。
- 新增 Python 執行期依賴（`backend/pyproject.toml` 的 `dependencies`）→ 退回（使用規則 5）。
- 稽核或 log 中出現請求路徑、query、header 值或 body → 退回（D17）。redaction 測試會擋，但 review 也要擋。
- 改了 CSP 卻只改一份 nginx → `make railway-check` 的 parity gate 會失敗；四處字串必須一起改（D20）。
- 新增 action key 而未同步 `services/rbac.py`、seed migration、`frontend/src/api/dto.ts` 三處 → `backend/tests/db/test_permission_matrix.py` 會擋，不得以 skip 繞過。
- 契約 PR 未同步 schema、`contracts/v1/fixtures/`、`fixtures/manifest.json`、`contracts/CHANGELOG.md` 與 Python／Go／TypeScript 三個 consumer → 退回。

### 上線階段

- **`TN-01` 未核准，`TN-03` 起的程式不得合併**，即使已經寫好。
- **`TN-02` 未通過（wildcard 網域或憑證在目標平台上不可得）→ 不得部署**。`CLIORA_TUNNEL_BASE_DOMAIN` 留空即為關閉，這是可接受的上線狀態；把功能改成路徑模式上線不是。
- **`TN-13` 安全審查完成前不得部署到正式環境。** D9 給了 Developer 完整的建立權，補償控制集中在「ownership、port 政策、authenticated-only、TTL、稽核」五項，未經對抗測試之前不能上線。
- **部署前必須確認 daemon 的執行身分不是 root。** 與 ADR 0021 同一條理由：隧道不提升任何權限，它把 daemon 能連到的 loopback 服務暴露成可從瀏覽器互動的介面，所以 daemon 的身分就是這個功能的權限上界。
- **既有 node 升級前必須先發 release note。** daemon 升級後即具備此能力（見 `03-…md` §1.3 的預設值決定），這是能力變更而非修補。

## 8. 完成定義

`make check`、`make traceability`、`make railway-check` 全綠；`scripts/trace coverage --scope all --strict` 退出 0（本期三個新 requirement 的每個 criterion 都備齊 planned_by／specified_by／implemented_by／verified_by 四類 primary link）；`make contract` 在 Python／Go／TypeScript 三處對新 fixture 行為一致，含四筆必須被拒的 invalid fixture；`TN-13` 十三項對抗全部有通過的證據且無未處理 Critical／High；`TN-14` 的三項量測（延遲、吞吐、終端機不退化）達標且數字寫進 `07-implementation-status.md`（**量測值**，不是本文件的推估）；`docs/adr/0022-…md`、`docs/security-review-p10.md`、`docs/tn-report.md`、`docs/runbooks/tunnel.md`、release note 五份文件齊備。
