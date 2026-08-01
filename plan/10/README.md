> # ⚠️ 本計畫已作廢（2026-08-01）
>
> **決定：不在平台自建反向代理，改以整合第三方隧道服務（Pinggy）交付同一個使用者需求。**
> 接續計畫見 **[plan/11](../11/)**（ticket 前綴 `PG-`）。
>
> 作廢理由不是設計有錯，而是**成本與收益不成比例**：本計畫的重量幾乎都不在功能本身，而在
> wildcard 網域、DNS-01 wildcard 憑證、Central 端代理與 stream manager、第二條 data-plane
> socket 與 CSP 放寬這五件事上（見 `00-execution-plan.md` §5 的 15 張票）。現階段以整合為主。
>
> **本目錄不刪除，因為它是 plan/11 的「被否決的替代方案」一節的完整論證**，也是日後真的要
> 自建時的現成規格。特別是這幾項結論在 plan/11 仍然成立並被沿用：
>
> | 沿用到 plan/11 的結論 | 位置 |
> |---|---|
> | port 政策（`<1024` 一律拒、node 端允許清單、node veto） | `00-…md` D8、`03-…md` §1.2 |
> | 目標位址固定 loopback，且不可由線上訊息指定 | `00-…md` D4、`02-…md` §1.2 |
> | 稽核只記生命週期，不記逐筆流量 | `00-…md` D17 |
> | `node_tunnels` 的資料形狀（無 `status` 欄位、部分唯一索引、slug 不重用） | `02-…md` §2.1 |
> | RBAC 兩個 action 與 Viewer 排除的理由 | `00-…md` D9 |
>
> 而以下結論在 plan/11 **反轉**了，原因是流量離開了組織邊界：預設啟用 → **預設停用**；
> 「URL 不是憑證」→ 第三方 URL **本質上是公開的**，改以保護模式（basic auth／IP allowlist）補償。

# Cliora 埠轉發隧道與反向代理 可實作規劃

本目錄把「在平台上指定 node 要轉出的 port，平台生成一個網址，任何 web 應用都能直接在平台內查看」從一句需求，變成可建立 ticket、撰寫程式與驗收的執行規格。ticket 統一使用 `TN-` 前綴。

這一期是**新增產品能力**，而且是本專案第一次讓瀏覽器的請求**流向 node 上的網路服務**——在此之前所有資料面都只有兩種形狀：終端機位元組（PTY）與唯讀檔案中繼（P3）。因此它同時需要契約變更、資料表、RBAC action、新的網域拓撲、新的 CSP 條目與一份 ADR。

## 為何需要這一期

在 node 上開發 web 應用時，目前的動線是斷的：

| 使用者要做的事 | 現在會發生什麼 |
|---|---|
| `npm run dev` 起 Vite 在 `127.0.0.1:5173`，想看看畫面 | 沒有任何路徑能看。CLI 面板看得到 log，`FR-FILE-002` 的 Monaco 看得到原始碼，但**跑起來的樣子看不到** |
| 改一行 CSS 想確認 | 只能靠 CLI 內的文字輸出推測，或自己在 node 上另外架 ngrok／SSH 反向隧道 |
| 請同事看一下這個頁面 | 只能截圖 |

而「自己在 node 上架 ngrok」正是這個平台存在的理由要否定的事：它是一條**平台看不到、不受 RBAC 管、不進稽核、憑證由第三方持有**的對外通道。`docs/adr/0020` 花了整節論證「單一 origin 不是偏好而是架構前提」，同一份紀律不能在 web 預覽這件事上外包給一個平台管不到的隧道服務。

所以這一期的問題不是「能不能看到畫面」，而是：**把已經有人在用的旁路，收回成平台的一等公民能力，並且讓它從第一天就帶著授權、稽核、限額與可撤銷性。**

### 三件現有架構已經替我們決定好的事

1. **daemon 只出不進。** `daemon/internal/connection/connection.go:105-135` 的 `Run` 是 daemon 主動 dial Central（tech §3.2）。隧道不得改變這一點——node 上不會多開任何對外監聽埠，資料面仍然是 daemon 撥出去的 WebSocket。
2. **Central 是單一 replica，而且是刻意的。** `app/services/registry.py` 與 `app/services/terminal_relay.py` 的狀態都是 process-local（ADR 0020 §2）。隧道的 stream 表同樣是 process-local，這**不是**新增的技術債，是沿用同一條既有約束。
3. **瀏覽器端的 token 在 `localStorage`。** `frontend/src/stores/auth.ts:20-21`。這一條直接決定了 §D1：被代理的 web 應用**絕對不能與 console 同 origin**，否則 node 上任何一個 dev server（或它引入的任何一個 npm 套件）都能讀走平台的 access／refresh token。這不是「加強防護」的選項，是這個功能唯一可接受的形狀。

### 這一期最容易做錯的三件事

- **用路徑前綴（`/t/<slug>/…`）省掉 wildcard 網域。** 省下的是 DNS 設定，付出的是：(a) 絕對路徑資產（`/assets/index.js`）全部 404，除非改寫 HTML／CSS／JS——一條沒有終點的路；(b) 與 console 同 origin，等於把 §3 的 token 交出去。**本期明確拒絕**（決策 D1）。
- **把隧道流量塞進既有的 node WebSocket。** 那條 socket 的寫入端是單一 mutex（`connection.go:137-160` 的 `writeMu`），一個 3 MB 的 source map 會排在終端機輸出前面。終端機延遲是 `NFR-001` 的承諾，不能被預覽功能借用。本期走**獨立的 data-plane socket**（決策 D5），並且用量測證明終端機延遲沒有退化（`TN-14`）。
- **做成 raw TCP 隧道。** 看起來更通用，實際上是把「任意位元組寫進 node 的 loopback socket」這個能力交給遠端。node 的 loopback 上通常還有 Postgres、Redis 與各種不做認證的內部服務。本期只做 **HTTP 語意中繼 + WebSocket 訊息中繼**（決策 D4），代價是不支援非 HTTP 協定，換到的是「這條通道無法被當成通用的 loopback 打洞工具」。

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍與非目標、20 項固定基線決策、目標拓撲與資料流、ticket 波次、共同 DoD、阻擋規則 |
| [01-decisions-and-spec-change.md](./01-decisions-and-spec-change.md) | `TN-01`（ADR 0022、PRD 新增 FR-TUNNEL-001/002/003 與 SCOPE-013、tech 修訂）、`TN-02`（網域與平台事實實測：wildcard DNS／TLS 可行性閘門） |
| [02-contract-and-data-model.md](./02-contract-and-data-model.md) | `TN-03`（契約 v1.6.0：控制／資料面訊息、binary kind 3／4、錯誤碼）、`TN-04`（migration 0014／0015、`tunnel.*` action、settings、error catalog） |
| [03-daemon-tunnel-agent.md](./03-daemon-tunnel-agent.md) | `TN-05`（data-plane 連線、`tunnel:` 設定、port 政策、tunnel 註冊表）、`TN-06`（HTTP／WS 中繼、有界佇列、逾時、metrics、doctor） |
| [04-central-proxy-and-access.md](./04-central-proxy-and-access.md) | `TN-07`（tunnel registry 與 stream manager、backpressure 與中止政策）、`TN-08`（host gate、代理端點、cookie 授權交握、header 政策） |
| [05-edge-api-and-frontend.md](./05-edge-api-and-frontend.md) | `TN-09`（兩份 nginx、CSP `frame-src`、Railway wildcard 網域、parity gate）、`TN-10`（REST API 與稽核）、`TN-11`（Node 詳情 Tunnels 區塊、Workspace `WEB` tab） |
| [06-verification-and-exit.md](./06-verification-and-exit.md) | `TN-12`（traceability 註冊與影響分析）、`TN-13`（安全審查 13 項對抗）、`TN-14`（NFR 量測，含終端機不退化）、`TN-15`（evidence、CI、runbook、exit gate） |
| [07-implementation-status.md](./07-implementation-status.md) | 各 ticket 實作狀態與實際證據；初始均未開工 |

## 使用規則

1. **先關 `TN-02`。** wildcard 網域與 wildcard TLS 在兩個部署目標（`deploy/compose/` 與 Railway）上是否真的可得，決定 D1／D2 是否成立。這一項若不成立，整個 URL 方案要重新選，而不是把功能降級成路徑模式偷偷上線——`00-…md` §2 已把路徑模式列為**永久非目標**。
2. **`TN-01` 未核准，`TN-03` 起的程式不得合併。** 這是 plan/08 `WT-04` 的同一條紀律：新增一條「瀏覽器→node 網路服務」的資料面是規格層級的變更，決定本身不能取代把決定寫下來。
3. **不得為了讓 app 正常顯示而改寫回應內容。** 不注入 script、不改寫 HTML／CSS 的 URL、不注入 CSP、不做 base 標籤重寫（決策 D14）。子網域方案的全部價值就在於「不需要改寫」；一旦開始改寫，就是在承認 D1 沒做對。
4. **不得記錄請求路徑、query、header 值或 body。** 稽核只記 tunnel 的建立／關閉／存取被拒（決策 D17），流量只進 metrics 計數器。這是 `TECH-SEC-08` 與 ADR 0004 的同一條線：資料面內容不進 DB 也不進 log。
5. **不得新增 Python 執行期依賴。** HTTP 由 uvicorn（瀏覽器側）與 Go `net/http`（node 側）各自處理，Central 不自己解析 HTTP（決策 D4）。任何 PR 想加 `httpx`／`aiohttp` 到 `backend/pyproject.toml` 的 runtime dependencies → 退回，並回到 D4 重新論證。
6. **平台聲明不算證據。** 沿用 plan/07 使用規則 3：「Railway 支援 wildcard 網域與憑證」要由 `TN-02` 對真實網域跑出來的輸出證明，不是引用文件。

## 完成結果

本期通過時：一位持有 `tunnel.manage` 的使用者可以在 Node 詳情頁指定一個 port（例如 5173），平台立即回一個 `https://<slug>.<tunnel-zone>` 網址；在 Session Workspace 的 `WEB` tab 內，該應用以 iframe 呈現、可互動、Vite HMR 的 WebSocket 正常連通，重新整理與深層路由（`/settings/profile`）都可用；同一個網址在未登入的瀏覽器上得到 401 而不是頁面，也不洩漏該 tunnel 是否存在；node 端沒有多開任何對外監聽埠；`<1024` 的 port 與 node 明確停用的情況一律拒絕；tunnel 有 TTL、可即時關閉，關閉後 slug 永不重用；建立／關閉／存取被拒有稽核紀錄，而請求路徑與內容不在任何紀錄裡；一條隧道以 8 MiB/s 傳輸時，同一 node 上終端機按鍵的 p95 延遲退化不超過 10 ms（**量測值**，不是推論）。
