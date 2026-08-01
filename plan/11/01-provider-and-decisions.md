# 01 — Provider 實測與決策閘門（PG-01、PG-02）

## PG-01：Pinggy 行為實測與 host key 取得

> **狀態：✅ 已於 2026-08-01 完成。** 十二項全數對真實服務執行、全數通過；證據見
> `artifacts/pg/local/provider-verify.json`，腳本 `scripts/tunnel/verify-provider.sh`（可重跑），
> host key 已寫入 `deploy/pinggy_known_hosts`。**三項假設被實測推翻**（PTY 會得到 TUI、無效憑證
> 靜默降級、`Host` 是隧道網域），已回頭修正 `00-…md` D8b／D9b 與 `03-…md` §2.1／§2.3／§2.4。
> 逐項結果見 `07-implementation-status.md` 的 provider 事實表。仍未關：Pro 專屬三項（staging-gated）。

> 產出是**一份輸出檔**，不是一段判斷。文件說什麼不算證據 —— 這條紀律在整合第三方時比自建時更重要，因為對方的行為我們既不能讀原始碼也不能改。

### 1.1 十項必須實測

| # | 要確認的事 | 怎麼測 | 若與假設不同 |
|---|---|---|---|
| 1 | **非互動式啟動可行** | `ssh -p443 -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=<file> -R0:localhost:8000 http@free.pinggy.io` 能建立隧道 | 文件說「若被要求密碼，直接按 enter」。若 `BatchMode=yes` 因此失敗，依序試：(a) 提供一組 daemon 專屬的 SSH keypair；(b) `-o PreferredAuthentications=none`；(c) **改用 `golang.org/x/crypto/ssh` 自建 client**（`00-…md` D1 的重開條件），屆時認證由我們的程式決定 |
| 2 | **URL 的印出格式與時機** | 擷取 stdout／stderr 完整原文，記錄前 20 行 | 解析規則（§`03-…md` §2.3）依此撰寫。若 URL 只在 PTY 下印出（不是純 pipe），`PG-06` 要改用 `creack/pty`（`daemon/go.mod` 已有） |
| 3 | **host key 指紋** | `ssh-keyscan -p 443 free.pinggy.io pro.pinggy.io a.pinggy.io` 並記錄全部 key 型別的指紋 | 這是 D7 的輸入。**同時記錄取得日期與方式**：這是一組會過期、會輪替的第三方資料，runbook 要寫怎麼更新 |
| 4 | **basic auth 是否需要 Pro** | 免費 token 加 `b:u:p` 是否生效 | 若需 Pro：免費模式下唯一可用的保護是 `w:`（IP allowlist）或 `public`。這會改變 `PG-08` 的欄位驗證（免費 + `basic` 要在 API 層直接拒絕，而不是建立後才失敗），也會改變 `PG-10` 整合設定頁上「預設保護模式」的可選值 |
| 4b | **token 的實際字元集** | 取一組真實 token，確認是否符合 `^[A-Za-z0-9]{8,128}$` | 若含 `-`／`_` 等字元，pattern 要放寬到**仍然排除 `+`、`@`、空白與 `:`** 的最小集合。**不可為了讓真 token 通過而放寬到允許 `+`／`@`** —— 那正是注入面（`02-…md` §1.2） |
| 5 | **免費版時限的實際行為** | 跑滿 60 分鐘以上，記錄：`ssh` 是被關閉還是隧道停止服務、退出碼、stderr 訊息 | `PG-06` 的重連判定依此。若 `ssh` 不退出而只是隧道失效，就需要主動健康檢查而不是等 process 退出 —— 這是兩種完全不同的實作 |
| 6 | **重連後 URL 是否必然改變** | 連續三次重連，比對 URL | D9 的敘述依此。Pro + persistent subdomain 要另測一次，確認 URL 穩定 |
| 7 | **Pro persistent subdomain 的完整 hostname 形狀** | 用 Pro token 起一條，記錄 URL | `PG-12`（選用）的 CSP 需要確切網域；官方文件在這一點上不明確，必須實測 |
| 8 | **`+force` 的語意** | 同一 token 起第二條隧道時的行為（是否踢掉前一條） | 若同 token 不能並存多條，`tunnels_per_node_max`（`02-…md` §2.3）就必須是 **1**，而不是設定值。這會直接改變產品行為，必須在 `PG-02` 寫清楚 |
| 9 | **`x:https` 與 `x:xff` 的實際效果** | 對 http URL 發請求應被拒／app 收到的 `X-Forwarded-For` 內容 | 若 `x:https` 不生效，明文入口就存在，要在 UI 明說 |
| 10 | **服務端不可用時的表現** | 斷開 egress、用錯 token、用過期 token 各一次，記錄退出碼與 stderr | `PG-06` 的錯誤映射（`TUNNEL_PROVIDER_UNAVAILABLE`／`_UNAUTHORIZED`／`_UNTRUSTED`）依此。**不可用與認證失敗必須能分辨**，否則使用者拿到的永遠是「連不上」 |
| 11 | **app 收到的 `Host` 與 header 原貌** | 在 node 上跑一個回顯全部 header 的服務，經隧道請求一次，記錄原文 | plan/10 的自建代理由我們決定 `Host`；**這裡由 Pinggy 決定，我們無從控制**。若 app 收到的是隧道網域，Vite 的 `server.allowedHosts`／Next.js 的 host 檢查會 404，這要寫進 runbook 與 UI 提示。同時確認 `Cookie`／`Authorization` 是否原樣通過（**若是，這是整合方案相對 plan/10 的一個優勢**：需要登入的 app 可以維持自己的 session） |
| 12 | **免費版的其他限制** | 記錄文件與實測到的頻寬、請求數、並發連線限制 | 若有頻寬上限，UI 的免費模式說明要寫；若有並發連線上限，`concurrent_budget` 以外還要考慮單條隧道的併發 |

### 1.2 產物

- `scripts/tunnel/verify-provider.sh`：十項各一個 assertion，任一失敗整支非零，輸出實際取得的值（URL、指紋、退出碼、stderr 原文）。沿用 `scripts/railway/verify-deployment.sh` 的形狀。
- `artifacts/pg/local/provider-verify.json` 與 `provider-transcript.txt`（stdout／stderr 原文，**遮蔽 token**）。
- `deploy/pinggy_known_hosts`（隨 installer 佈署到 `/etc/agentd/pinggy_known_hosts`），檔頭註明取得日期、方式與更新程序。

### 1.3 驗收

十項全部有輸出；第 1、3、4、5、8 項的結果直接寫進 `07-implementation-status.md` 的「provider 事實」表，因為它們會改變後續票的形狀。

---

## PG-02：ADR 0022、PRD 修訂與 `SCOPE-013`

> **這張票的產出是一份書面決定。** `PG-03` 起的程式在它合併之前不得合併。

### 2.1 為什麼這需要產品層級的核准

不是因為它改了架構 —— 恰恰相反，它幾乎沒改架構。需要核准是因為它**改變了資料的邊界**：

| 變更 | 現況 | 之後 |
|---|---|---|
| 誰能看到 workspace 內的應用內容 | 只有持有平台憑證的使用者，且流量只走自有基礎設施 | **Pinggy 的伺服器會處理未加密的 HTTP 內容**（其 `http` 隧道型別本來就會解析流量以提供 header 改寫與 debugging），TLS 在其終結 |
| 誰決定一個 port 是否對外 | 不存在這個能力 | **三方**：平台管理員（啟用整合並提供憑證）＋ 持有 `tunnel.manage` 的使用者（該 node 的設定與建立）＋ node 擁有者（本機一票否決） |
| 誰保管第三方憑證 | 不存在 | **平台**（加密儲存，隨 `tunnel.open` 下發，node 不落地）。這是 2026-08-01 需求變更的結果，也是本 ADR 最需要論證的一條 |
| 平台能否回答「誰存取了這個預覽」 | — | **不能。** 流量不經過 Central |
| 新增的外部依賴 | 無 | Pinggy 的可用性、定價與 token 保管 |

第三列是能力缺口而不是隱私設計，ADR 必須這樣寫。第四列是營運責任，runbook 必須指名負責人。

### 2.2 ADR 0022 必須記錄什麼

檔名 `docs/adr/0022-third-party-tunnel-integration.md`（現有最新 `0021`）。七項缺一不可：

**(1) 決定與取捨**：以整合交付，理由是成本與收益（README 的成本對照表）。

**(2) 信任邊界的變化**：§2.1 的表，逐列寫明。特別是「Pinggy 可見未加密 HTTP 內容」這一句，要寫成一個獨立段落，因為它是這個決定唯一無法用工程手段消除的後果。

**(3) 補償控制，逐項寫明擋住什麼：**

| 控制 | 擋住什麼 | 不擋什麼 |
|---|---|---|
| **整合預設停用，須由 Admin（`integration.manage`）明確啟用並確認**（D3、D14） | 平台在管理員不知情的情況下具備對外轉發能力 | 啟用後，任何持 `tunnel.manage` 的人都能在允許的 node 上建立 |
| **node 本機一票否決，平台不得覆寫**（D3、D17） | 平台替一台有合規要求的機器做外流決定 | 未否決的機器（預設）——理由是它已授予平台 `shell` runtime |
| **憑證加密儲存、永不回傳、只顯示指紋**（D19） | 憑證從介面、DB dump、稽核或 log 外流 | 平台本身被入侵（處置：在 Pinggy 端撤換，寫進 runbook） |
| **憑證字元集限 `[A-Za-z0-9]`**（D18） | 以憑證值注入 `+tcp`（改隧道型別）或 `@evil.host`（改 SSH 目的地） | — |
| **provider host 由 daemon 的常數決定，不由 Central 指定** | 協定長出「叫 node 連到任意主機」的能力 | — |
| **保護模式預設 `basic`**（D5） | 隨機掃到 URL 的外人 | Pinggy 自己（它在 TLS 終結點之後） |
| **`x:https`**（D8） | 明文入口 | 同上 |
| **host key 釘選**（D7） | node egress 路徑上的 MITM | Pinggy 伺服器本身 |
| **port ≥1024 + node 允許清單**（D8） | 把系統服務或資料庫轉出去 | app 自己的行為 |
| **TTL + 明確關閉 + 孤兒回收**（D9、`03-…md` §2.5） | 被遺忘的長效外流；daemon 重啟後殘留的 `ssh` | — |
| **首次使用的明確確認 + 稽核**（D14、D11） | 「我不知道流量會經過第三方」 | — |
| **daemon 非 root** | 權限上界 | — |

「不擋什麼」這一欄是這張表的重點：三項補償控制都擋不住 Pinggy 本身，所以**這個功能只適用於預覽開發中的應用，不適用於任何帶有真實資料的環境**。這句話要進 ADR、runbook 與 UI。

**(4) 為什麼 plan/10（自建）被否決**：引用 README 的成本對照表，並註明 plan/10 未刪除、可作為自建的現成規格；重開條件（若第三方不可接受、或需要平台端的存取記錄與內容政策）。

**(5) 為什麼用 `exec ssh` 而非自建 SSH client**（D1，含重開條件）。

**(6) 能力缺口的完整清單**：無存取記錄、無內容政策、無頻寬計量、免費版 URL 會變、Pinggy 中斷即不可用、iframe 與 basic auth 互斥。

**(7) 被否決的其他替代方案**：Cloudflare Tunnel／ngrok／tailscale funnel（若評估過，寫下選 Pinggy 的理由與其它選項的差異；若沒評估，就誠實寫「未做橫向比較，選擇依據是使用者指定」—— 後者比編造一份比較表好）。

### 2.3 PRD 修訂

**(a) 新增 `# 8.10 埠轉發預覽`**（置於 `# 8.9 Daemon 與中央通訊` 之後，`research/prd.md:1192` 附近），格式對照 `FR-SHELL-001`（`research/prd.md:751-782`）。

`FR-TUNNEL-001 埠轉發隧道（第三方整合）`：

| ID | 內容 |
|---|---|
| AC-01 | 埠轉發整合須由平台管理員啟用；Node 得於本機停用該功能，且該停用不得被平台覆寫 |
| AC-02 | 持有 `tunnel.manage` 的使用者可為已啟用的 Node 指定一個 port，平台顯示服務商回傳的網址 |
| AC-03 | 目標位址固定為該 Node 的 loopback；`port` 須大於等於 1024 且在該 Node 的允許範圍內 |
| AC-04 | 隧道不得在 Node 上開啟任何對外監聽埠；對外連線一律由 Daemon 主動建立 |
| AC-05 | 隧道有存活上限，可明確關閉；關閉後平台不再顯示該網址 |
| AC-06 | 網址由服務商決定且可能變更；變更後平台須在介面上更新 |
| AC-07 | 建立與關閉須留下稽核紀錄；流量內容不經過平台，平台亦不記錄 |
| AC-08 | Node 上不得殘留已關閉隧道的行程 |

`FR-TUNNEL-002 隧道保護`：

| ID | 內容 |
|---|---|
| AC-01 | 建立隧道時必須選擇一種保護方式：密碼保護、來源 IP 限制或公開 |
| AC-02 | 密碼保護的密碼由平台產生，僅於建立時顯示一次，不以明文儲存 |
| AC-03 | 選擇「公開」須經一次明確確認並記錄 |
| AC-04 | 僅持有 `tunnel.view` 的使用者可在平台內看到隧道網址；Viewer 不得看到 |
| AC-05 | 使用者於首次為某 Node 建立隧道時，須確認已知悉流量將經由第三方服務轉送 |

`FR-TUNNEL-004 整合設定與憑證保管`（**2026-08-01 需求變更新增**）：

| ID | 內容 |
|---|---|
| AC-01 | 埠轉發整合由平台管理員在系統整合設定中啟用；未啟用時不得建立隧道 |
| AC-02 | 服務商憑證由使用者自行取得並提供；平台不代管其帳號，亦不呼叫其管理介面 |
| AC-03 | 服務商憑證須加密儲存，且不得由任何介面回傳；僅得顯示其指紋 |
| AC-04 | 環境未具備憑證加密能力時，不得啟用整合，亦不得以明文儲存憑證 |
| AC-05 | 每個 Node 有獨立的埠轉發設定；平台設定與 Node 本機設定只能取交集，Node 的停用不得被平台覆寫 |
| AC-06 | 整合的啟用、停用、憑證設定與 Node 設定變更均須留下稽核紀錄；憑證內容不得出現於紀錄中 |

`FR-TUNNEL-003 傳輸與依賴`：

| ID | 內容 |
|---|---|
| AC-01 | 與服務商的連線須驗證其主機金鑰，不得停用驗證 |
| AC-02 | 隧道僅接受加密的外部連入 |
| AC-03 | 服務商不可用、憑證無效與主機金鑰不符須顯示為可區分的狀態 |
| AC-04 | Node 可自我診斷埠轉發的先決條件（用戶端存在、對外連線可達、主機金鑰已佈署、憑證已設定） |

**(b) PRD §4 非目標新增第 13 條：**

```
<a id="scope-013"></a>
<a id="scope-013-ac-01"></a>
13. 不由平台自建對外反向代理。埠轉發以第三方隧道服務整合交付：平台不代管服務商憑證，
    該路徑的流量不經過平台，平台因此不提供存取記錄、內容政策與頻寬計量。
    （範圍新增 2026-08-01，ADR 0022；自建方案見 plan/10，已作廢。）
```

守門測試（`backend/tests/test_scope_guards.py`）：斷言 Central 沒有任何代理路由 —— 具體做法是掃 `app.routes`，確認不存在 catch-all 的 `{path:path}` 路由，且沒有任何 route 會把請求轉往 node 的 HTTP 服務。理由與 `SCOPE-011` 相同：**最容易被順手長回來的東西必須有機械化的守門**。

**(c) §7 系統架構**（`:223`）補一句「埠轉發預覽的資料路徑不經過 Central」；**§10 前端頁面規劃**新增「系統整合設定頁」與「Node 埠轉發設定頁」兩節；**§11 後端 API** 新增 `11.8 Tunnels` 與 `11.9 Integrations`；**§15 安全需求**新增 `SEC-008 第三方隧道邊界`（管理員明確啟用、**憑證加密保管且永不回傳**、host key 釘選、保護模式、三層設定只能收窄、僅適用開發預覽六項）。

**(d) tech.md**：§12.2 新增 `Tunnel` 控制訊息分節；§8 Daemon 設計新增一小節「埠轉發監管」（子行程、重連、URL 解析、孤兒回收）；§17 部署架構註明新增的 egress 需求（TCP 443 到 provider）。

### 2.4 驗收

- ADR 0022 已合併，§2.2 的七項齊備。
- PRD 修訂已合併，`scripts/trace validate --level static` 通過（新 anchor 存在，既有 anchor 未動）。
- 決定與日期記錄在 `07-implementation-status.md`。
- traceability 註冊留在 `PG-13`（selector 必須與測試同一個 PR 落地）。
