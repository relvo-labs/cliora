# Cliora 埠轉發：以 Pinggy 整合交付 可實作規劃

本目錄把「在平台上啟用 Pinggy 整合，然後在每個 node 的設定頁把該節點上的 port 轉出去」交付為**對第三方隧道服務的整合**，而不是平台自建反向代理。ticket 統一使用 `PG-` 前綴。

**取代 [plan/10](../10/)**（2026-08-01 決定）。plan/10 的設計沒有錯，是成本與收益不成比例：它的重量幾乎全在 wildcard 網域、DNS-01 wildcard 憑證、Central 端代理與 stream manager、第二條 data-plane socket、CSP 放寬這五件事上。本期把這五件事全部換成「daemon 監管一個 `ssh` 子行程」。

## 使用者動線（2026-08-01 需求確認後的形狀）

```
① Admin：系統整合設定 → 啟用 Pinggy → 貼上自己的 token（訂閱由使用者自行處理）
                                 ↓（平台加密保存，永不回傳）
② 任一 node 的「埠轉發」設定頁 → 選 port → 建立 → 取得網址（＋一次性密碼）
                                 ↓（token 隨 tunnel.open 下發，node 不落地）
③ daemon 起 ssh 反向隧道 → 回報網址 → UI 顯示、可新視窗開啟
```

三層設定，規則是**每一層只能收窄，不能放寬**（決策 D17）：

| 層 | 誰設定 | 內容 |
|---|---|---|
| 平台整合設定 | Admin（UI） | 啟用／停用、token、方案別（free／pro）、併發預算、預設保護模式與 TTL、全域 port 上限 |
| 平台的 per-node 設定 | Admin／Developer（UI，`PG-11` 的頁面） | 該 node 是否參與、該 node 的 port 允許範圍、隧道數上限 |
| node 本機否決 | node 擁有者（`/etc/agentd/config.yaml`） | `tunnel.enabled: false` 一票否決；`allowed_ports` 只能比平台更窄 |

## 兩個方案的成本對照

| 需要做的事 | plan/10（自建） | plan/11（整合 Pinggy） |
|---|---|---|
| Wildcard 網域 + DNS-01 wildcard 憑證 | ✅ 必要（且是唯一可行形狀） | — |
| Central 端 HTTP／WS 代理、stream manager、backpressure | ✅ 約 1000 行新程式 | — |
| 第二條 data-plane WebSocket（含獨立認證與重連） | ✅ | — |
| 契約 | 13 個訊息 + binary kind 3／4 | **5 個控制訊息，無 binary frame** |
| Edge nginx 改動、CSP 放寬 | ✅ 四處字串 + parity gate | **不改**（D6：只做新視窗開啟） |
| host gate、cookie 授權交握 | ✅ | — |
| daemon 端 | data-plane 連線 + HTTP／WS 中繼 + 佇列 | **監管一個 `ssh` 子行程 + 解析它印出的 URL** |
| 平台端新增的設定面 | 環境變數一個 | **系統整合設定頁 + per-node 設定頁 + 加密保存的第三方憑證** |
| 票數 | 15（`TN-01`–`TN-15`） | 14（`PG-01`–`PG-14`），無一張需要動 edge |
| 新增的信任對象 | 無（流量不離開自有基礎設施） | **Pinggy** |

倒數第三列是這次需求確認新增的成本：把啟用與 port 設定搬到 UI 之後，**平台必須保管使用者的第三方憑證**，而 plan/11 的初版刻意不這麼做。這一條的代價與補償控制寫在 `01-…md` §2.2 與 `00-…md` D4／D18。

## 這一期最容易做錯的四件事

1. **把 token 存明文，或在 API 回應中回傳它。** token 只能加密保存、只能寫入不能讀出，UI 只顯示「已設定 · 指紋 ab12…」（D19）。
2. **token 的字元集不驗。** 它會被組進 `ssh` 的 `user@host` 欄位，而 Pinggy 用 `+` 串接修飾詞、`@` 分隔主機。一個含 `+tcp` 或 `@attacker.host` 的 token 值能改變隧道型別或連線目的地 —— 所以 token 只接受 `[A-Za-z0-9]`（D18，有 invalid fixture）。
3. **忘記 node 的否決權。** 設定搬到 UI 不代表 node 失去發言權；`tunnel.enabled: false` 必須一票否決，而且平台不得有任何路徑覆寫它（D3、D17）。
4. **`StrictHostKeyChecking=no`。** 沒有釘住 host key，node egress 上一個 MITM 就能讀走全部預覽流量，症狀是「一切正常」（D7，有 grep gate）。

## Pinggy 的事實（文件版 ＋ **實測修正**）

下表是**文件說的**。`PG-01` 已於 2026-08-01 對真實服務跑完十二項，其中**三項與文件不同**，
以實測為準 —— 逐項結果見 [07-implementation-status.md](./07-implementation-status.md) 的 provider 事實表：

| 實測推翻的假設 | 實際行為 |
|---|---|
| URL 可以在 PTY 下取得 | **加 `-t` 會得到全螢幕 ANSI TUI**，URL 無法解析；無 PTY 時 stdout 是四行乾淨文字 |
| 無效憑證會被拒絕 | **不會**：服務靜默降級為匿名免費隧道並照樣給網址 → 只能靠 stdout 橫幅判定，且必須主動中止 |
| app 會收到 loopback 作為 `Host` | 收到的是**隧道網域**，Vite／Next 的 host allowlist 會擋 → 新增選用的 Host 改寫（D8b） |

另外兩件文件沒寫的事：**免費版網址內嵌 node 的公網 IP**（D9b 的揭露義務）；**`Cookie`／`Authorization` 原樣通過**（plan/10 做不到的事）。

| 事實 | 內容 |
|---|---|
| 命令形狀 | `ssh -p443 -R0:<localhost>:<localport> [<token/keyword/tunneltype>@]free.pinggy.io <remote options>` |
| token 與修飾詞 | 放在 `@` 之前，以 `+` 串接：`tkn+force@pro.pinggy.io`；免費為 `http@free.pinggy.io` |
| remote options（附在命令最後） | `b:user:pass`（basic auth，帳密不得含 `:`）、`w:IP1,IP2`（IP allowlist）、`k:key`、`x:https`、`x:xff[:Header]`、`a:／r:／u:`（header 增改刪） |
| 取得的網址 | 連線後服務端印出 http 與 https 兩行，形如 `https://uljtt-30-47-152-61.run.pinggy-free.link` |
| 免費版 | 60 分鐘、隨機網址；**重連後網址會變** |
| Pro | 固定子網域（dashboard 指派給 token）、自訂網域、無 60 分鐘上限 |
| 長時間執行 | 官方建議 `-o ServerAliveInterval=60` 搭配重連迴圈 |

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 成功定義、範圍與非目標、19 項固定基線決策、三層設定與資料流、ticket 波次、共同 DoD、阻擋規則 |
| [01-provider-and-decisions.md](./01-provider-and-decisions.md) | `PG-01`（Pinggy 行為實測閘門，含 host key 取得）、`PG-02`（ADR 0022、PRD 修訂與 `SCOPE-013`） |
| [02-contract-and-data-model.md](./02-contract-and-data-model.md) | `PG-03`（契約 v1.6.0）、`PG-04`（migration 0014–0016：`node_tunnels`／`tunnel_integration`／`node_tunnel_settings`、action、settings、error catalog） |
| [03-daemon-supervisor.md](./03-daemon-supervisor.md) | `PG-05`（node 本機否決設定、host key 釘選、`doctor`）、`PG-06`（`ssh` 子行程監管、URL 解析、重連與 TTL、孤兒回收） |
| [04-central-and-api.md](./04-central-and-api.md) | `PG-07`（tunnel service、URL 變更傳播）、`PG-08`（Tunnels API、稽核）、`PG-09`（**整合設定服務、憑證加密與 API**） |
| [05-frontend.md](./05-frontend.md) | `PG-10`（**系統整合設定頁**）、`PG-11`（**每個 node 的埠轉發設定頁**）、`PG-12`（選用：iframe 內嵌與 CSP，可整票不做） |
| [06-verification-and-exit.md](./06-verification-and-exit.md) | `PG-13`（traceability、安全審查 13 項）、`PG-14`（evidence、CI、runbook、release note、exit gate） |
| [07-implementation-status.md](./07-implementation-status.md) | **各 ticket 狀態、已落地的產物清單、交棒說明與環境事實。`PG-01`–`PG-11`、`PG-13`、`PG-14` 完成；`PG-12` 依 D-5 不做；唯一未關的驗證缺口是 fake provider 的 E2E** |

## 使用規則

1. **先關 `PG-01`。** 非互動式認證、URL 印出格式、host key 指紋、basic auth 是否需要 Pro、同一 token 能否並存多條 —— 五項若與假設不同，`PG-05`／`PG-06`／`PG-09` 的形狀就要改。
2. **`PG-02` 未核准，`PG-03` 起的程式不得合併。** 「把使用者的 HTTP 流量交給第三方，並由平台保管其憑證」是產品層級的決定。
3. **token 只能寫入，不能讀出。** 加密保存、API 永不回傳、稽核與 log 只記指紋（D19）。任何回傳 token（含前綴片段）的 PR → 退回。
4. **絕不使用 `StrictHostKeyChecking=no`**（D7，grep gate）。
5. **三層設定只能收窄。** 任何讓平台設定覆寫 node 否決的程式 → 退回（D17）。
6. **不做 fallback 到自建代理**（D15）。要自建就是回到 plan/10，那是要重新核准的決定。
7. **訂閱由使用者自行處理。** 平台不代購、不代管帳號、不呼叫 Pinggy 的計費或管理 API；只使用一個由 Admin 貼進來的 token。

## 完成結果

本期通過時：Admin 在「系統整合設定」啟用 Pinggy 並貼上自己的 token（平台加密保存，之後只顯示指紋）；任一台 online node 的「埠轉發」設定頁可設定該節點的允許 port 範圍與隧道上限，並在該頁建立隧道；建立後數秒內顯示 Pinggy 回傳的 https 網址與一組**只顯示一次**的 basic auth 帳密，可新視窗開啟；免費版 60 分鐘後自動重連並把**新網址**更新到頁面；node 擁有者以 `tunnel.enabled: false` 可一票否決且平台無法覆寫；token 不以明文存在於 DB、log、稽核或任何 API 回應中，且其字元集被嚴格限制以防注入 SSH 目的地；建立、關閉、整合設定變更與憑證設定皆有稽核紀錄；`agentd doctor` 能回答「ssh 在不在、egress 通不通、host key 釘住了沒有、本機是否否決」。
