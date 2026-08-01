# 03 — Daemon 端隧道代理（TN-05、TN-06）

## TN-05：data-plane 連線、`tunnel:` 設定與 port 政策

### 1.1 第二條連線

新增 `daemon/internal/tunnel/` 套件與一條獨立的 data-plane 連線，端點 `/ws/nodes/{node_id}/tunnel`。

| 性質 | 決定 | 理由 |
|---|---|---|
| 誰撥出 | daemon（同 `connection.go:105-135` 的 `Run` 迴圈形狀） | tech §3.2。node 上不新增任何監聽埠（`FR-TUNNEL-001.AC-04`） |
| 何時撥出 | `tunnel_base_domain` 有設定且該 node 未停用 tunnel 時，於控制面認證成功後撥出 | 沒有 zone 就沒有功能（D2）。**Central 在 `node.registered` 回應中帶 `tunnel_data_plane: true/false`**，daemon 據此決定要不要撥第二條——避免每個 node 都對一個不存在的端點重試 |
| 認證 | 同一組 Ed25519 credential、同一組 `node.challenge`／`node.auth` frame，但**簽章前綴改為 `cliora-node-tunnel-v1\n`** | nonce 本來就是一次性的，所以重放不成立；換前綴是為了讓「控制面簽章」與「資料面簽章」在密碼學上不可互換，這是零成本的域分離。實作上把 `security/node_keys.py:13` 的 `DOMAIN` 參數化，Go 端同樣參數化 `connection.go:231` 的字串 |
| 重連 | 獨立的 backoff（沿用 `connection.go:35-37` 的 `backoff` 表與 jitter），與控制面互不影響 | 資料面斷線不該讓終端機重連，反之亦然 |
| 斷線的語意 | 資料面斷 → 所有進行中的 stream 立即中止（兩端各自清理）；tunnel **不關閉**，Central 標記 `unavailable` | `FR-TUNNEL-001.AC-06`。daemon 重啟是常態，不該讓使用者的 URL 消失 |
| 寫入序 | 自己的 mutex 與自己的送出 queue，**絕不與 `connection.go` 的 `writeMu` 共用** | 這就是 D5 的全部意義。若有人為了少寫一個 mutex 而共用，`TN-14` §3 的量測會抓到，但 review 也要抓 |

### 1.2 `tunnel:` 設定區塊

`daemon/internal/config/config.go` 新增（沿用既有 `FilesystemConfig`／`SearchConfig` 的形狀與註解密度）：

```go
// TunnelConfig bounds the reverse-proxy relay (P10, ADR 0022). The daemon never
// listens on an external port; it dials 127.0.0.1:<port> on demand. Absent
// section → enabled with the default port policy.
type TunnelConfig struct {
    Enabled      bool     `yaml:"enabled"`
    AllowedPorts []string `yaml:"allowed_ports"`  // "3000-3999", "5173", …
    MaxStreams   int      `yaml:"max_streams"`
    // EnabledFromDefault reports that the section was absent and defaulted to
    // enabled, rather than being written by an operator. Never serialised.
    EnabledFromDefault bool `yaml:"-"`
}
```

| 決定 | 選擇 | 理由 |
|---|---|---|
| 預設值 | **設定缺項即視為啟用**（`applyTunnelDefaults()`，與 `applyRuntimeDefaults()` 同一手法） | 沿用 ADR 0021 D6 的結論：需求是「可以在平台看到 web 應用」，逐台改檔重啟的門檻與之不符。node 擁有者仍保有否決權（明確 `enabled: false`）。**代價是既有 node 升級後即取得此能力**，必須在 release note 與 runbook 明講（`06-…md` `TN-15`） |
| 預設 port 政策 | `allowed_ports` 缺項 → 允許 **1024–65535**；`<1024` **無論設定為何一律拒絕** | 一個 dev server 可能在任何高位 port，預設收窄成某個範圍只會讓功能在一半的情境下不能用而使用者不知道為什麼。真正該擋的是特權 port——那裡是系統服務，而且 daemon 非 root 本來也不該去碰。**`<1024` 不可由設定放寬**，這是硬編碼的下界 |
| 明確停用不得被覆寫 | `enabled: false` 必須在 `applyTunnelDefaults()` 之後仍為 false | plan/08 踩過同一顆釘子（`WT-06` 的 Go 測試）。這裡要有同型別的測試 |
| 產生的 `config.yaml` 要自我解釋 | `MarshalConfig` 在 `tunnel` 區塊上方掛註解：這是什麼、預設啟用（含既有 node）、如何停用、為何 daemon 不能是 root | 沿用 plan/08 補齊的教訓：node 擁有者是唯一的否決者，否決權必須寫在他會打開的那個檔案裡 |

`daemon/internal/install/plan.go` 產生的初始設定要寫出 `tunnel: {enabled: true}` 並帶上述註解。

### 1.3 tunnel 註冊表與 port 解析

`tunnel.Registry`（daemon 端，process-local）：`tunnel_id → port`。

- 只有 `tunnel.open` 能寫入，`tunnel.close` 移除，斷線清空。
- **資料面訊息只帶 `tunnel_id`**，port 一律由這張表查。查不到 → `tunnel.abort{code: TUNNEL_NOT_FOUND}`，不猜、不 fallback。
- `tunnel.open` 時驗 port：不在允許範圍 → `TUNNEL_PORT_NOT_ALLOWED`；`tunnel.Enabled == false` → `TUNNEL_DISABLED`。**Central 也擋同樣兩件事**（`04-…md` §1.2），兩層獨立成立，理由與 P3 的路徑檢查一樣（`services/files.py:49` 的註解：defence in depth）。
- 上限：`MaxStreams`（預設 128）為 node 端的併發 stream 上界，獨立於 Central 的 `tunnel_streams_per_node_max`。兩邊都有上限是因為兩邊的失敗模式不同：Central 擋的是「一個使用者吃掉整個 node 的額度」，daemon 擋的是「Central 出錯或被冒充時，node 上的 fd 不會被打爆」。

### 1.4 連線探測

`tunnel.open` 回應中的 `target_reachable`：對 `127.0.0.1:<port>` 做一次 `net.DialTimeout("tcp", …, 300ms)`，立刻關閉，回傳成功與否。

- **只探測這一個 port**，不掃描、不記錄、不重試。
- `false` 不是錯誤：dev server 還沒起來是最常見的情況，隧道照建，UI 顯示「目前沒有服務在聽」（`FR-TUNNEL-003.AC-05`）。
- 探測結果不進 metrics 的高基數 label（不以 port 為 label）。

### 1.5 驗收

- Go 單元測試：port 政策 6 例（範圍內、範圍外、`<1024` 即使被列入允許清單也拒、缺項預設、明確停用不被覆寫、`max_streams` 上限）。
- `tunnel_id` 查不到時回 `TUNNEL_NOT_FOUND` 且**不嘗試任何連線**（以 fake dialer 斷言 dial 次數為 0）。
- `agentd doctor` 新增三項檢查：`tunnel.enabled` 來源（設定檔／預設）、data-plane 連線狀態、目前活躍 tunnel 數。`doctor` 的輸出不得含 port 清單以外的內容（不列出 slug——slug 是 Central 的識別碼，node 上不需要知道）。
- `go test -race ./...` 全綠。

---

## TN-06：HTTP／WebSocket 中繼、佇列與逾時

### 2.1 HTTP 中繼

收到 `tunnel.request` 後：

1. 查表得 port（§1.3）。
2. 用 `net/http` 組請求：`http://127.0.0.1:<port><target>`。**`target` 已經被 schema 限定為 `/` 開頭**（`02-…md` §1.2），Go 端再驗一次（`strings.HasPrefix(target, "/")` 且 `url.Parse` 後 `Host == ""`）。
3. Header：白名單複製（§2.3），加 `X-Forwarded-For`（Central 傳來的 client IP，一個值）、`X-Forwarded-Proto: https`、`X-Forwarded-Host: <slug>.<zone>`。**`Host` 設為 `127.0.0.1:<port>`**——不轉發 tunnel host，因為 dev server 對 Host 做虛擬主機判斷時，收到一個它不認識的網域通常會 404（Vite 的 `server.allowedHosts` 就是這個坑）。這一項要寫進 runbook：若 app 需要看到原始 Host，用 `X-Forwarded-Host`。
4. `has_body` 為真 → 以 `io.Pipe` 當 request body，kind 3 frame 寫入，`tunnel.body_end` 關閉寫端。
5. 回應 header 齊全時送 `tunnel.response`，body 邊讀邊切成 ≤64 KiB 的 kind 3 frame，結束送 `tunnel.body_end`。
6. 任一步失敗 → `tunnel.abort`，`code` 依錯誤映射（連不上 → `TUNNEL_TARGET_UNREACHABLE`、逾時 → `REQUEST_TIMEOUT`、其他 → `INTERNAL_ERROR`）。**daemon 的原始錯誤字串不上線**，只有碼；字串進本地 log 帶 stream id（沿用 `error_catalog.py` 檔頭的規則）。

`http.Transport` 的設定必須明寫，不能用 `DefaultTransport`：

| 設定 | 值 | 理由 |
|---|---|---|
| `DialContext` | 固定 `127.0.0.1:<port>`，忽略 URL 中的任何 host | 最後一道 SSRF 防線：即使前面所有檢查都被繞過，連線目標仍然只能是 loopback |
| `Proxy` | `nil` | 否則 node 上的 `HTTP_PROXY` 環境變數會讓 loopback 請求被送出去 |
| `DisableCompression` | `true` | Central 原樣轉發 `Content-Encoding`（D14）；讓 Go 自動解壓會與轉發的 header 不一致 |
| `ForceAttemptHTTP2` | `false` | 目標是 loopback 的 HTTP/1.1 dev server；h2c 不在範圍內（`00-…md` §2） |
| `MaxIdleConnsPerHost` | 32 | 連線重用；一個頁面載入是數十個請求 |
| `ResponseHeaderTimeout` | 30s（`tunnel_first_byte_timeout_seconds` 的 node 端對應值） | |

### 2.2 WebSocket 中繼

`tunnel.ws_open` → 用既有的 `gorilla/websocket` Dialer（`daemon/go.mod:8`）連 `ws://127.0.0.1:<port><target>`，帶上白名單 header 與 `subprotocols`。

- 成功 → `tunnel.ws_opened{subprotocol}`，之後雙向以 kind 4 frame 中繼，**opcode byte 原樣保留**（text 與 binary 不可互換，否則瀏覽器端 `event.data` 的型別會變）。
- 訊息 >64 KiB → 切分？**不切**：WS 訊息沒有分片重組的中繼語意（分片是傳輸層的事，訊息邊界是應用層的事）。超過上限 → `tunnel.ws_close{code: 1009}`（Message Too Big），並記一個 metric。這是誠實的限制，寫進 runbook。
- ping／pong 由兩端各自維護，不中繼。中繼 ping 會讓「連線活著」變成一個經過三跳的推論。
- 閒置 `tunnel_ws_idle_seconds`（300s）無任何訊息 → 關閉。HMR 的 Vite client 有自己的 ping，所以正常開發不會被誤殺。
- `permessage-deflate` 不協商（雙方各自不啟用），理由同 `DisableCompression`：多一層壓縮／解壓只會讓位元組不再原樣。

### 2.3 Header 政策（兩個方向）

**移除（hop-by-hop 與平台自有）：** `Connection`、`Keep-Alive`、`Proxy-Authenticate`、`Proxy-Authorization`、`TE`、`Trailer`、`Transfer-Encoding`、`Upgrade`。這一組不是「建議移除」，是 RFC 9110 的 hop-by-hop 定義；把它們轉出去就是請求走私的入口。

**不轉發給 app（請求方向）：** `Cookie`（tunnel host 上的 cookie 只有平台的授權 cookie，app 不該看到它）、`Authorization`（同理）。**這是一個功能取捨**：需要 cookie／登入的 app 在隧道後面無法保持自己的 session。寫進 runbook 與 `docs/tn-report.md`，並列為「未來擴充」的候選（做法是給 app 一個獨立的 cookie 命名空間，但那需要重寫 cookie name 與 path，屬於 D14 禁止的改寫，因此本期不做）。

**回應方向的三個修改（D14 允許的全部）：**

| 動作 | 對象 | 理由 |
|---|---|---|
| 移除 `Domain` 屬性 | `Set-Cookie` | 擋 cookie tossing：app 不得替整個 zone 設 cookie。cookie 仍會作用在自己的 host 上，功能不受影響 |
| 移除整個 header | `Strict-Transport-Security` | HSTS 是 zone 的決定，不是某個 dev server 的 |
| 保留但由 UI 處理 | `X-Frame-Options`／`Content-Security-Policy` | **不移除**。app 拒絕被內嵌是它的權利；平台的答案是「新視窗開啟」（`FR-TUNNEL-003.AC-04`），不是把它的安全 header 拿掉 |

### 2.4 佇列與 backpressure（node 端）

- 每個 stream 一個有界的送出佇列（byte-aware，預設 2 MiB），紀律沿用 `backend/app/services/terminal_queue.py:22` 的 `BrowserChannel`：**滿了就中止這一個 stream，不阻塞共用 socket**（D15）。
- 從本地 socket 讀取的迴圈在佇列接近上限時暫停讀取（讓 TCP 對 dev server 施加背壓），只有在「暫停後仍持續超限」時才中止 stream。
- per-node 單一寫入 goroutine 消費所有 stream 的佇列，round-robin，避免一個大回應餓死其他 stream。
- 請求 body 累計超過 `tunnel_request_body_max_bytes` → `TUNNEL_BODY_TOO_LARGE`（Central 端也擋，見 `04-…md` §2.4）。

### 2.5 Metrics（`daemon/internal/metrics`）

| 名稱 | 型別 | label |
|---|---|---|
| `daemon_tunnel_dial_total` | counter | `result`（`ok`／`refused`／`timeout`） |
| `daemon_tunnel_requests_total` | counter | `result`（`ok`／`aborted`／`unreachable`） |
| `daemon_tunnel_bytes_total` | counter | `direction`（`in`／`out`） |
| `daemon_tunnel_streams_active` | gauge | — |
| `daemon_tunnel_queue_bytes` | histogram | — |
| `daemon_tunnel_ws_active` | gauge | — |

**label 一律不含 port、path、slug 或任何識別碼**（D17，且高基數 label 會把本地 metrics 撐爆）。沿用 `connection.go` 內既有的「本地也記一份，因為 `agentd metrics` 必須在連不上 Central 時仍可回答」的理由。

### 2.6 驗收

- Go 單元測試（以本地 `httptest.Server` 為目標）：GET／POST with body／串流回應（chunked）／SSE（保持連線 3 秒不被閒置逾時殺掉）／404／502（app 掛掉）／header 白名單雙向／`Set-Cookie` 的 `Domain` 被移除／`X-Frame-Options` 被保留。
- WS 測試：text 與 binary 各一往返（opcode 保留）、>64 KiB 訊息得到 1009、閒置逾時。
- 對抗測試：`target` 為絕對 URL、`target` 不以 `/` 開頭、header value 含 CRLF、`Transfer-Encoding: chunked` 被塞進 header 清單 → 四者全部在 daemon 端也被拒（schema 已擋，但 daemon 不得依賴上游驗證）。
- backpressure：一個永不讀取的 client + 一個持續輸出的 app → 只有該 stream 被中止，同一 node 上另一條 stream 完好（斷言另一條的位元組數持續增加）。
- `make integration` 新增 `./internal/tunnel`，`go test -race ./...` 全綠。
