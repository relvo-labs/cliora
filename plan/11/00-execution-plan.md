# 00 — 執行總控（以 Pinggy 整合交付埠轉發）

## 1. 成功定義

**要交付的：** Admin 在系統整合設定啟用 Pinggy 並提供自己的 token；此後任一台 online node 都有一個埠轉發設定頁，可設定該節點的允許範圍並建立隧道；平台在數秒內回一個可從外部開啟的網址，並在網址變更、隧道結束或失敗時顯示準確狀態。流量不經過 Central。

**不得弄壞的三件事：**

1. **第三方憑證的保管。** token 由平台保管（需求變更後的形狀，D4），因此它必須加密儲存、永不回傳、只記指紋，且其字元集被嚴格限制 —— 它會被組進 `ssh` 的 `user@host` 欄位（D18、D19）。
2. **node 擁有者的否決權。** 設定搬到 UI 不等於 node 失去發言權。`tunnel.enabled: false` 一票否決，平台無任何路徑可覆寫（D3、D17）。
3. **既有資料面完全不動。** 不新增 socket、不新增 binary frame、不動 edge、不動 CSP（D6、D10）。這一期若動到 `deploy/nginx/nginx.conf` 或 `protocol/codec.py` 的 binary 部分，就是走錯路了。

成功的判準是這八項：

1. 整合未啟用時，Tunnels API 回 404、node 頁不顯示埠轉發入口；啟用但某 node 否決時，該 node 的設定頁顯示「此 Node 已在本機停用」與原因 —— **不是**一個看起來像故障的 500。
2. `CLIORA_SECRET_ENCRYPTION_KEY` 未設定時，啟用整合的 API 直接回錯並說明原因（無法安全保存憑證），**不是**存明文。
3. token 在 DB 為 ciphertext；`GET` 整合設定的回應含 `configured: true` 與指紋，**不含 token 的任何字元**。
4. 含 `+`／`@`／空白的 token 值在 API、schema、daemon 三處皆被拒（防注入 SSH 目的地與隧道型別）。
5. 建立後 10 秒內取得 https 網址；`curl` 該網址（帶 basic auth）能取到該 port 上應用的回應。
6. 免費版 60 分鐘後：`ssh` 自行重連，daemon 回報**新網址**，UI 在一個輪詢週期內更新。
7. host key 被釘住：以假的 host key 啟動時 `ssh` 拒絕連線，平台顯示 `TUNNEL_PROVIDER_UNTRUSTED`，**不是**默默連上。
8. 關閉隧道或 daemon 重啟後，node 上**沒有殘留的 `ssh` 行程**（孤兒回收，`03-…md` §2.5）。

## 2. 範圍

### 納入

- `PG-01` Pinggy 行為實測（含 host key 取得）、`PG-02` ADR 0022 與 PRD 修訂。
- 契約 v1.6.0：`tunnel.open`／`tunnel.opened`／`tunnel.close`／`tunnel.closed`／`tunnel.status`，**只有控制面**；`tunnel.open` 攜帶 provider 憑證（`PG-03`）。
- 三張表：`node_tunnels`、`tunnel_integration`（單列）、`node_tunnel_settings`；`tunnel.view`／`tunnel.manage`／`integration.manage` 三個 action；settings 與 error catalog（`PG-04`）。
- daemon：node 本機否決設定、host key 釘選、`doctor` 四項（`PG-05`）；`ssh` 子行程監管、憑證只在記憶體、URL 解析、重連與 TTL、孤兒回收、metrics（`PG-06`）。
- Central：tunnel service 與 URL 變更傳播（`PG-07`）；Tunnels API 與稽核（`PG-08`）；**整合設定服務、憑證加解密與 API**（`PG-09`）。
- 前端：**系統整合設定頁**（`PG-10`）、**每個 node 的埠轉發設定頁**（`PG-11`）。
- traceability、安全審查、evidence／CI／runbook／release note／exit gate（`PG-13`、`PG-14`）。

### 不納入

- **iframe 內嵌**（`PG-12` 選用票，可整票不做）。預設呈現是新視窗開啟，因此本期**不動 CSP**（D6）。
- **平台自建反向代理。** 就是 plan/10；要做要重新核准（D15）。
- **代管 Pinggy 帳號、代購訂閱、呼叫其計費或管理 API。** 訂閱由使用者自行處理；平台只使用一個 Admin 貼進來的 token（D20）。
- **per-user 或 per-node 各自的 token。** 平台一組（D18 的「單一憑證」）。若 `PG-01` #8 證明方案的併發數少於 `concurrent_budget`（預設 8），處理方式是**把預算調降到符合方案並在 UI 說明**，不是引入多 token 管理。
- **多 provider。** daemon 內有一層 interface，但只有一個實作，設定只接受 `pinggy`（D2）。
- **TCP／TLS 隧道型別**（D8）。TCP 會讓「轉出一個資料庫 port」變成一次設定的事。
- **Pinggy 的 header 改寫（`a:`／`r:`／`u:`）與 key auth（`k:`）。**
- **平台端的流量統計、存取記錄、頻寬計量。** 流量不經過 Central，做不到。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D1 | 整合方式 | daemon 以 **`exec.CommandContext` 監管 OpenSSH client 子行程** | 與既有慣例一致：tmux（`internal/tmux/client.go:96`）與 systemctl（`internal/update/systemd.go:64`）都是外部 binary + `doctor` 檢查。**被否決**：引入 `golang.org/x/crypto/ssh`（`daemon/go.mod` 目前沒有 x/crypto）。**重開條件**：若 `PG-01` 證明非互動式認證無法在 `BatchMode` 下穩定成立，就改用它 |
| D2 | provider 抽象 | daemon 內一層 `Provider` interface，**只有 Pinggy 一個實作**；設定的 `provider` 只接受 `pinggy` | 介面的目的不是支援多家，是把「換 provider」或「回到自建」的成本關在 daemon 內。多一個 enum 值卻沒有第二個實作，是替不存在的需求付維護費 |
| D3 | 誰決定一個 node 能不能轉出 | **三層，每一層只能收窄**（見 D17）：平台整合設定（Admin，總開關＋全域上限）→ 平台的 per-node 設定（該 node 是否參與、port 範圍）→ **node 本機否決**（`tunnel.enabled: false`，預設不否決） | 需求是「在平台設定」，所以主閘門必須在平台。node 本機預設不否決的理由是**它已經授予平台 shell 能力**（ADR 0021 的 `shell` runtime 預設啟用）：一個已經能執行 `bash` 的平台再要求逐台編輯設定檔才能轉發 port，是形式上的安全而非實質的。但否決權必須存在，給有合規要求的機器 |
| D4 | 第三方憑證由誰保管 | **平台保管**（`tunnel_integration` 表，AES-GCM 加密），隨 `tunnel.open` 下發給 node。**這一條反轉了 plan/11 初版的「只存在 node 上」** | 需求要求「在系統整合設定啟用」，而啟用的實質內容就是提供 token；把 token 留在 node 端會讓 UI 上的「啟用」變成一個做不到的承諾（平台無從知道每台 node 有沒有填、填了什麼）。代價與補償控制見 D18／D19 與 `01-…md` §2.2 |
| D5 | 保護模式 | 三種，建立時必選：**`basic`（預設）**＝`b:user:pass`，密碼由 Central 產生且**只顯示一次**（存 Argon2 hash）；**`ipallow`**＝`w:IP,…`；**`public`**＝無保護，需一次明確確認並記入稽核 | 第三方 URL 本質公開，保護必須加在 provider 的選項上。預設值由整合設定決定（`default_protection`），但建立時仍必須是一個明示的選擇 |
| D6 | 呈現方式 | **新視窗開啟為唯一預設，本期不動 CSP。** iframe 是選用票 `PG-12`，且只在 `ipallow`／`public` 模式下提供 | Chrome 不在 cross-origin iframe 顯示 basic auth 對話框，所以預設保護模式與 iframe 天生互斥；而 iframe 要動四處 CSP 字串並把 provider 網域寫進安全政策 |
| D7 | SSH host key | **釘選**：`-o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/agentd/pinggy_known_hosts`，內容由 `PG-01` 取得並隨 installer 佈署。`StrictHostKeyChecking=no` 一律禁止（grep gate） | 沒有釘選，node egress 上任何 MITM 都能取得全部預覽流量，而症狀是「一切正常」。這是本期唯一一個**平台可以自己做對**的傳輸安全控制 |
| D8 | 隧道型別與目標 | 只 `http`；`-R0:localhost:<port>`，port ≥1024 且在三層設定的交集內；固定附加 `x:https` 與 `x:xff` | 沿用 plan/10 D8 的 port 政策。**實測（`PG-01` #9）**：`x:https` 讓明文請求被 **301 導向** https（不是拒絕）；`x:xff` 讓 app 收到呼叫者的公網 IP |
| D8b | **選用的 Host 改寫**（2026-08-01 依實測新增） | 建立隧道時可勾選「改寫 Host 為本機位址」，對應 remote option `u:Host:localhost:<port>`；**預設關閉** | **實測（`PG-01` #11）**：app 收到的 `Host` 是隧道網域，因此 Vite（`server.allowedHosts`）與 Next 的 host 檢查會直接拒絕請求 —— 這是使用者第一次用就會撞到的牆。這**不違反 D14 的「不改寫內容」**：改的是一個 header 而不是 body，而且是使用者為了讓自己的 dev server 能收請求而明確選擇的。預設關閉，因為改寫 Host 會讓 app 產生的絕對 URL（redirect、cookie domain）指向 loopback |
| D9 | URL 生命週期 | URL 由 provider 決定，**可能變更**（實測：每次連線都是新的隨機 slug）。daemon 以 `tunnel.status` 主動回報；Central 更新 `url`／`url_updated_at`；UI 顯示「網址可能變更」與 provider 時限 | 整合方案最顯著的行為差異，必須是一等公民。使用者若把免費版網址貼進文件，一小時後它會失效 —— UI 要先講 |
| D9b | **免費版網址會洩漏 node 的公網 IP** | 免費模式的 UI 必須明文顯示這件事；`plan_tier=free` 時在建立表單與清單各出現一次 | **實測（`PG-01` #2c）**：免費版 hostname 形如 `xxxxx-114-32-49-189.run.pinggy-free.link` —— 中間那段就是該 node 的公網 IP。這在任何文件裡都沒寫，只有跑過才會看到，而它是一個使用者有權在建立前知道的揭露 |
| D10 | 契約 | **v1.6.0（compatible）**，5 個控制訊息 + 6 個錯誤碼。**不新增 binary kind、不新增 socket** | 資料面不存在於平台，這是本期成本低的根本原因 |
| D11 | 稽核 | 隧道：`tunnel.create`／`tunnel.close`／`tunnel.public_acknowledged`。整合：`integration.enable`／`integration.disable`／`integration.credential_set`（**只記指紋**）。per-node 設定：`integration.node_settings_updated` | 「誰在什麼時候把整合打開、換了憑證、改了哪台 node 的允許範圍」全都是必須可回溯的操作。流量天然無法記錄，這一點是能力缺口而非隱私設計 |
| D12 | 資料表 | 三張：`node_tunnels`（沿用 plan/10 §2.1 形狀）、`tunnel_integration`（單列，含加密憑證）、`node_tunnel_settings`（per-node 平台側設定） | 狀態一律推導不存。分三張而非塞進 `nodes`：整合設定是平台級的單列，per-node 設定有自己的變更者與時間，混進 `nodes` 會讓一張已經很寬的表再寬四欄 |
| D13 | `SCOPE-013` 的內容 | **「不由平台自建對外反向代理；埠轉發以第三方服務整合交付，該路徑的流量不經過平台，平台因此不提供存取記錄、內容政策與頻寬計量。訂閱與帳號由使用者自行持有。」** | 誠實的非目標比好聽的非目標有用。這一條同時把「不要偷偷長回一個自建代理」與「不要開始代管第三方帳號」兩件事釘住 |
| D14 | 資料外流的告知 | 兩處：**整合設定頁啟用時**（一次，Admin 必須勾選確認）＋ **每個 node 第一次建立隧道時**（一次，建立者確認）。兩者都記稽核 | 兩個不同的人在做兩個不同的決定：Admin 決定「本組織使用這個服務」，建立者決定「這台機器的這個 port 現在對外」。只問一次會漏掉其中一個 |
| D15 | provider 不可用時 | 顯示明確狀態（`TUNNEL_PROVIDER_UNAVAILABLE`），**不做任何 fallback** | fallback 到自建就是 plan/10（要重新核准）；靜默降級成無保護的公開 URL 更糟 |
| D16 | 相依檢查 | `agentd doctor` 四項：`ssh` 存在、egress 到 provider host:443 可達、`known_hosts` 存在且可解析、本機是否否決（**不回報憑證，因為 node 不再持有**） | 這個功能的失敗集中在環境。沒有 `doctor`，每次都要讀 daemon log 才能分辨四種 |
| D17 | 三層設定的合成規則 | **交集，只能收窄。** 有效 `allowed_ports` = 平台全域 ∩ per-node ∩ node 本機；**每台 node 的上限** = `min(tunnels_per_node_max, per-node 設定, node 本機)`；任一層 `enabled: false` 即整體停用 | 只有一條規則、沒有例外，才能在四個地方（API、UI 提示、daemon、稽核）給出一致的答案。**「平台可覆寫 node」是明確被拒絕的選項**：那會讓 node 擁有者的否決權變成建議 |
| D17b | **併發預算是車隊級的，不進 per-node 的 `min()`** | `concurrent_budget`（預設 **8**）是**整個車隊同時存活的隧道數上限**，以「全域 live tunnel 計數」單獨檢查；per-node 上限是另一條獨立的檢查 | 兩者限制的是不同的東西：預算來自 **provider 方案能同時開幾條**（一個 token 的併發數），per-node 上限來自「不要讓一台機器吃掉整個預算」。把它們放進同一個 `min()` 會得到荒謬的結果 —— 預算 8、per-node 3 時，`min()` 會讓每台 node 只能開 3 條卻**永遠檢查不到第 8 條**，車隊實際可開 3×N 條，直接超過方案 |
| D18 | 憑證如何到 node | **隨每一次 `tunnel.open` 下發**（payload 的 `credential` 欄位），node **只放在記憶體與子行程 argv，永不寫入磁碟** | 不需要額外的下發／輪替協定；換 token 只影響之後新建的隧道（既有的 `ssh` 連線持有舊憑證直到關閉，這一點要在 UI 說明）。**代價**：token 出現在 node 的 `ssh` argv，同 uid 的行程讀得到 —— 已列入安全審查的紀錄項，且 daemon 非 root 是這裡的邊界 |
| D19 | 憑證的儲存與顯示 | AES-GCM（`cryptography` 已是既有依賴），金鑰來自新設定 `CLIORA_SECRET_ENCRYPTION_KEY`（32 bytes base64）；DB 存 ciphertext + nonce + **sha256 指紋前 8 hex**；API **永不回傳 token**，只回 `configured` 與指紋 | 指紋讓人能回答「現在裝的是不是我上週換的那一把」而不洩漏任何字元。金鑰未設定時**拒絕啟用整合**（判準 2）—— 這比「先存明文，日後再加密」誠實得多 |
| D20 | 訂閱與帳號 | **使用者自行處理。** 平台不代購、不代管帳號、不呼叫 Pinggy 的計費／管理 API；`plan_tier`（`free`／`pro`）只是 Admin 在整合設定裡告知平台的一個值，用來決定 UI 文案與併發預算的預設 | 一旦平台開始呼叫對方的管理 API，就要保管一組權限更大的憑證、處理它的錯誤與版本變更，而收益只是少讓 Admin 填一個欄位 |

## 4. 三層設定與資料流

```text
① 平台整合設定（tunnel_integration，單列）
   enabled / provider=pinggy / plan_tier / token(ciphertext) / concurrent_budget
   default_protection / default_ttl / allowed_ports(全域上限)
                    │
② 平台 per-node 設定（node_tunnel_settings）
   enabled / allowed_ports / max_tunnels                     ← PG-11 的頁面
                    │
③ node 本機否決（/etc/agentd/config.yaml）
   tunnel.enabled: false（一票否決）/ allowed_ports（只能更窄）
                    │
                    ▼  有效設定 = ①∩②∩③（D17）

建立
  瀏覽器 ──POST /api/tunnels──▶ Central ──tunnel.open{credential, port, protection…}──▶ daemon
                                （token 由 ① 解密後放入 payload）              │
                    ssh -p443 -R0:localhost:5173 <token>@pro.pinggy.io  b:u:p  x:https  x:xff
                                                                              ▼
  Central ◀──tunnel.opened{url, upstream_expires_at}── daemon ◀── stdout    Pinggy

使用
  外部瀏覽器 ──https://xxx.run.pinggy-free.link──▶ Pinggy ──SSH 反向通道──▶ daemon ──▶ 127.0.0.1:5173
                                                （平台完全不在這條路徑上）

網址變更（免費版 60 分鐘）
  daemon（ssh 退出 → 重連 → 新 URL）──tunnel.status{url}──▶ Central ──▶ UI（輪詢 15s）
```

**注意「使用」那一段：平台不在資料路徑上。** 這決定了本期的能力邊界（無內容政策、無存取記錄、無延遲量測）與成本優勢（無代理、無佇列、無 backpressure）。兩者是同一件事的兩面，ADR 要一起寫。

## 5. 執行波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `PG-01` | Pinggy 行為實測與 host key 取得 | — |
| | `PG-02` | ADR 0022、PRD 修訂與 `SCOPE-013` | PG-01 |
| **1（契約與資料）** | `PG-03` | 契約 v1.6.0：5 個控制訊息、6 個錯誤碼、憑證欄位 | PG-02 核准 |
| | `PG-04` | migration 0014–0016、三個 action、settings、error catalog | PG-02 核准 |
| **2（daemon）** | `PG-05` | node 本機否決設定、host key 釘選、`doctor` | PG-03 |
| | `PG-06` | `ssh` 子行程監管、憑證只在記憶體、URL 解析、重連、孤兒回收 | PG-05 |
| **3（Central）** | `PG-09` | **整合設定服務、憑證加解密與 API** | PG-04 |
| | `PG-07` | tunnel service、三層設定合成、URL 變更傳播 | PG-03、PG-09 |
| | `PG-08` | Tunnels API、稽核 | PG-07 |
| **4（介面）** | `PG-10` | **系統整合設定頁** | PG-09 |
| | `PG-11` | **每個 node 的埠轉發設定頁** | PG-08、PG-10 |
| **5（選用）** | `PG-12` | iframe 內嵌與 CSP（**可整票不做**） | PG-11 |
| **6（驗證與退出）** | `PG-13` | traceability 與安全審查 13 項 | PG-11 |
| | `PG-14` | evidence、CI、runbook、release note、exit gate | 全部 |

`PG-09` 先於 `PG-07`：三層設定的合成與憑證解密都在 tunnel service 的建立路徑上，先有整合設定才有東西可合成。`PG-05`／`PG-06`（daemon）可與波次 3 並行，但整合驗證要在同一輪收斂 —— 兩邊各自對契約寫的測試會同時綠，卻可能對 `tunnel.open` 是否帶憑證有不同期待。`PG-03` 的 golden fixture 是唯一仲裁者。

## 6. 每張 ticket 的完成格式

1. **產物清單**：新增／修改的檔案逐一列出，含理由。
2. **測試**：新增的自動測試與其斷言對象。**與第三方互動的部分一律以 fake provider 測**（`03-…md` §2.6）；真實 Pinggy 只出現在 `PG-01` 與 `PG-14` 的 staging leg。
3. **規格同步**：本 ticket 動到的 PRD／tech／ADR／traceability 條目。
4. **證據**：可重跑的指令與其輸出位置。
5. **未關項**：需要真實帳號／Pro 訂閱者明確標為 staging-gated。

## 7. 阻擋規則

### PR 階段

- **token 出現在任何 API 回應中**（含前綴、後綴、長度以外的任何資訊）→ 退回（D19）。
- token 以明文存入 DB、寫入 node 磁碟、出現在 log／稽核 metadata／metrics label／`doctor` 輸出 → 退回（D18、D19）。
- token 的字元集未驗證（未拒絕 `+`／`@`／空白／非 `[A-Za-z0-9]`）→ 退回。這是注入 SSH 目的地與隧道型別的入口（D18）。
- 出現 `StrictHostKeyChecking=no`、`UserKnownHostsFile=/dev/null` 或任何略過 host key 驗證的寫法 → 退回（D7，grep gate）。
- 任何讓平台設定**放寬** node 本機設定的程式（覆寫否決、擴大 port 範圍、提高上限）→ 退回（D17）。
- 出現 Central 端的代理／轉發程式碼 → 退回（D15，`SCOPE-013` 的 grep gate）。
- 動到 `deploy/nginx/*`、CSP 字串或 `protocol/codec.py` 的 binary 部分 → 退回，除非是 `PG-12`（選用票，需獨立核准）。
- 呼叫 Pinggy 的計費／管理 API，或新增任何代管帳號的欄位 → 退回（D20）。
- 新增 action key 未同步 `services/rbac.py`、seed migration、`frontend/src/api/dto.ts` 三處 → `test_permission_matrix.py` 會擋，不得 skip。

### 上線階段

- **`PG-02` 未核准，`PG-03` 起的程式不得合併。**
- **`PG-13` 安全審查完成前不得部署到正式環境。** 本期的核心風險從「隧道」移到了「平台保管第三方憑證」，未經對抗測試前不能上線。
- **`CLIORA_SECRET_ENCRYPTION_KEY` 的產生、保管與輪替程序必須寫進 runbook** 才算完成。金鑰遺失＝所有已存憑證無法解密（處置：重新輸入 token），這件事要先寫下來。
- **release note 必須先發。** 重點與 plan/08 相反：升級**不會**啟用任何東西；要用必須由 Admin 在整合設定啟用，並理解流量會經過 Pinggy。
- **必須確認 daemon 執行身分不是 root。** 第三次出現在第三個功能上（ADR 0021 的 shell、plan/10 的自建代理、本期）。

## 8. 完成定義

`make check`、`make traceability` 全綠；`scripts/trace coverage --scope all --strict` 退出 0；`make contract` 三語一致（含 4 筆 invalid fixture）；§1 的八項判準各有通過的證據；`PG-13` 十三項對抗全部有證據且無未處理 Critical／High；`docs/adr/0022-third-party-tunnel-integration.md`、`docs/security-review-p11.md`、`docs/pg-report.md`、`docs/runbooks/tunnel-pinggy.md`、`docs/release-note-tunnel.md` 五份文件齊備；`plan/10` 已標記作廢並在 ADR 0022 中作為被否決的替代方案完整記錄。
