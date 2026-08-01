# 01 — 決策閘門與平台事實（TN-01、TN-02）

## TN-01：ADR 0022、PRD 與 tech 修訂

> **這張票的產出不是程式，是一份書面決定。** `TN-03` 起的程式在它合併之前不得合併。

### 1.1 為什麼這不是一張功能票

本專案至今的資料面只有兩種形狀，兩者都是**由 Central 發起、內容受平台語意約束**的：

| 既有資料面 | 內容 | 誰決定內容 |
|---|---|---|
| 終端機（P2） | PTY 位元組 | node 上的 CLI 程序 |
| 檔案中繼（P3） | 唯讀的目錄／檔案內容 | daemon，且受 allowed root、敏感檔案政策、大小上限三重約束 |

隧道新增第三種：**由瀏覽器發起、內容由瀏覽器決定、目的地是 node 上的網路服務**。這件事沒有任何既有 requirement 描述過，PRD §4 的十二條非目標也沒有一條涵蓋它（`research/prd.md:73-116`）——它既沒被允許，也沒被禁止。這正是必須由人明確決定的情形。

同時它會**放寬一個目前實際存在的限制**：CSP 的 `frame-ancestors 'none'`（四處，見 D20）目前禁止一切 framing。放寬它是安全政策變更，不能夾在功能 PR 裡默默完成。

### 1.2 ADR 0022 必須記錄什麼

檔名 `docs/adr/0022-tunnel-and-reverse-proxy.md`（現有最新為 `0021`）。除了決策本身，以下六項缺一不可：

**(1) 它把什麼暴露出來了。** 逐條列出，不含糊：

| 項目 | 事實 |
|---|---|
| 暴露對象 | node 的 **loopback 網路命名空間**上，指定 port 的那一個服務 |
| 權限上界 | daemon 的執行身分能連到的 loopback socket。**隧道不提升任何權限**，它把「能連到」變成「能從瀏覽器互動」 |
| 既有的 allowed workspace root（`services/sessions.py:63`） | **與此無關**。隧道不是檔案系統存取，root 前綴授權對它不成立也不適用 |
| 敏感檔案政策（`TECH-SEC-09`／`FILE_DENIED`） | **對隧道無效**。app 若有一個 `/download?path=/etc/passwd` 的端點，隧道會忠實地把它轉出來。這是 app 的行為，不是平台繞過了政策——但 ADR 必須明說，否則下一個人會以為 P3 的政策也在保護這條路 |
| `SEC-002`（前端不得指定命令） | **仍有效**。資料面沒有任何命令／argv／binary 欄位，目標位址由 `tunnel_id` 查表得到 |
| `TECH-SEC-08`（資料面內容不進 log／DB） | **仍有效**，且本期不得為了「稽核使用者看了哪些頁面」而破壞它（D17） |
| daemon 只出不進（tech §3.2） | **仍有效**。data-plane 是 daemon 撥出去的第二條 WSS |

**(2) 補償控制，逐項寫明各自擋住什麼。**

| 控制 | 擋住什麼 |
|---|---|
| **Authenticated-only（D10、`SCOPE-013`）** | URL 洩漏等於公開部署。這是與 ngrok 的根本差異，也是本設計最重要的一條 |
| **Origin 隔離（D1）** | 被代理的 app 讀走 console 的 `localStorage` token |
| **Port 政策：`<1024` 一律拒、node 端允許清單、node veto（D8）** | 把隧道當成通用 loopback 打洞工具（`22`／`5432`／`6379`） |
| **HTTP／WS 語意限定（D4）** | 任意位元組寫進不做認證的 loopback 服務 |
| **`tunnel_id` → port 在 daemon 端查表** | 資料面訊息被改寫成指向別的 port／別的 host |
| **TTL + 明確關閉 + slug 永不重用（D13、D12）** | 被遺忘的長效暴露；舊書籤指到新 app |
| **稽核 create／close／access_denied（D17）** | 事後追溯「誰在哪個 node 開過哪個 port」 |
| **daemon 非 root** | 權限上界。**這一項失守，整個設計的風險等級改變** |

**(3) 為什麼子網域是唯一可接受的形狀**，以及路徑模式被拒的兩個理由（D1）。這一段要寫得足以讓半年後有人提出「加一個路徑模式當 fallback」時，能直接被這份 ADR 否決。

**(4) 為什麼資料面要與控制面分家**（D5），含「終端機延遲是承諾」這個因果，並指向 `TN-14` §3 的量測作為驗收。

**(5) CSP `frame-ancestors` 放寬的範圍與理由**（D20）：從 `'none'` 改為只允許 zone 一個來源，且 tunnel host 的回應不套 console 的 header 集合。

**(6) 被否決的替代方案與理由：**

- *在 node 上跑 ngrok／cloudflared，平台只存 URL*：憑證與流量由第三方持有，RBAC 與稽核全部失效，且違反 ADR 0020 對單一 origin 的整套論證。這正是本期要收回的旁路。
- *raw TCP 隧道*：見 D4 (b)。多換到的是非 HTTP 協定支援，多付出的是一條通用 loopback 打洞通道。
- *Central 端主動連 node（把 node 變成有對外監聽埠的伺服器）*：違反 tech §3.2，且 node 通常在 NAT 後面——這條路一開始就是這個架構否決過的。
- *把隧道流量塞進既有 socket*：見 D5。
- *路徑前綴 + 內容改寫*：見 D1、D14。
- *iframe 加 `sandbox` 取代 origin 隔離*：見 D19。

### 1.3 PRD 修訂內容

**(a) 新增 `# 8.10 埠轉發與預覽`**（置於 `# 8.9 Daemon 與中央通訊` 之後，`research/prd.md:1192` 附近），三個 requirement。格式必須與既有 FR 完全一致：`## FR-XXX-NNN 標題` + 每個 criterion 一個 `<a id="fr-xxx-nnn-ac-0N"></a>`（對照 `research/prd.md:751-782` 的 `FR-SHELL-001` 寫法）。

`FR-TUNNEL-001 埠轉發隧道`：

| ID | 內容 |
|---|---|
| AC-01 | 持有 `tunnel.manage` 的使用者可為一個 online node 指定一個 port，系統回傳一個唯一網址 |
| AC-02 | 目標位址固定為該 node 的 loopback；請求不得指定主機、協定或其他 port |
| AC-03 | `port < 1024` 一律拒絕；Node 可設定允許的 port 範圍，亦可整體停用埠轉發 |
| AC-04 | 隧道不在 Node 上開啟任何對外監聽埠；資料面由 Daemon 主動連線 |
| AC-05 | 隧道有存活上限，可明確關閉；關閉或到期後網址立即失效且不再重用 |
| AC-06 | Node 離線時隧道標記為不可用；Node 重新連線後同一網址恢復可用 |
| AC-07 | 每個 Node 與每位使用者的隧道數量、併發連線數與請求主體大小均有上限 |
| AC-08 | 隧道的建立與關閉須留下稽核紀錄；請求路徑、查詢字串、標頭與內容不得寫入資料庫或 Log |

`FR-TUNNEL-002 隧道存取授權`：

| ID | 內容 |
|---|---|
| AC-01 | 隧道網址不構成授權；未經認證的請求一律拒絕 |
| AC-02 | 僅持有 `tunnel.view` 的使用者可開啟隧道網址；Viewer 不得開啟 |
| AC-03 | 授權憑證只對單一隧道有效，且不得用於平台 API |
| AC-04 | 隧道網址所在網域不得提供平台 API、平台 WebSocket 或 Console 靜態資源 |
| AC-05 | 隧道回應不得與 Console 同源 |
| AC-06 | 隧道被關閉、Node 離線或授權到期時，進行中的連線立即中止 |

`FR-TUNNEL-003 平台內 Web 預覽`：

| ID | 內容 |
|---|---|
| AC-01 | 使用者可在 Session 工作區內以內嵌畫面檢視隧道，亦可於新視窗開啟 |
| AC-02 | 支援 HTTP 全部常用方法、串流回應與 WebSocket |
| AC-03 | 平台不改寫應用的回應內容 |
| AC-04 | 應用拒絕被內嵌時，介面明確說明並提供新視窗開啟 |
| AC-05 | 隧道不可用時，介面顯示可行動的原因（Node 離線／已關閉／已到期／目標無服務） |

**(b) 新增 PRD §4 非目標第 13 條**（`research/prd.md:73-116` 之後追加，保留既有十二條的編號與 anchor）：

```
<a id="scope-013"></a>
<a id="scope-013-ac-01"></a>
13. 不提供匿名或公開存取的隧道網址。隧道網址不是憑證；每一個請求都必須通過平台認證與授權。
    （範圍新增 2026-08-01，ADR 0022。）
```

這一條要有守門測試（`TN-13` 第 1 項與 `backend/tests/test_scope_guards.py` 新增一例），理由與 `SCOPE-011` 完全相同：**最容易被順手放寬的性質，必須有機械化的守門**。

**(c) §7 系統架構**（`:223`）的圖與說明補上 data-plane socket 與 tunnel zone；**§10.6 Session 工作區**（`:1493`）補第四個 tab；**§11 後端 API**（`:1543`）新增 `11.8 Tunnels`；**§15 安全需求**新增 `SEC-008 隧道存取邊界`（authenticated-only、origin 隔離、port 政策、無內容改寫四項），並在 `SEC-005` 註明隧道流量同樣只走 TLS。

**(d) tech.md**：§12.2 訊息類型新增 `Tunnel` 分節與兩個 binary kind；§10.2 Frame 設計補 kind 3／4；§4 整體架構圖補第二條 socket；新增 §11.9（或 §24）「隧道與反向代理設計」記錄 §4 的七步資料流、佇列與逾時常數來源；§17 部署架構補 wildcard zone 與 CSP。

### 1.4 驗收

- `docs/adr/0022-tunnel-and-reverse-proxy.md` 已合併，§1.2 的六項齊備。
- PRD 修訂已合併，`scripts/trace validate --level static` 通過（所有新 anchor 存在，既有 anchor 未被改動）。
- `TN-01` 的決定與日期記錄在 `07-implementation-status.md`。
- **traceability 註冊留在 `TN-12`**：`verified_by` 的 selector 必須與測試檔在同一個 PR 落地，否則中間每個 commit 的 `make traceability` 都是紅的（`scripts/traceability/validate.py` 會檢查 selector 路徑是否存在）。

---

## TN-02：網域與平台事實實測

> 這張票的產出是**一份輸出**，不是一段判斷。沿用 plan/07 使用規則 3：平台文件說支援，不算證據。

### 2.1 要證明的六件事

| # | 主張 | 怎麼證明 | 若不成立 |
|---|---|---|---|
| 1 | 目標網域可設定 wildcard DNS（`*.t.<domain>` → edge） | `dig +short <random>.t.<domain>` 對三個隨機 label 都回 edge 位址 | D2 不成立 → 功能關閉上線 |
| 2 | edge 能取得 wildcard TLS 憑證且對隨機 label 有效 | `openssl s_client -connect <random>.t.<domain>:443 -servername …` 檢查 SAN 含 `*.t.<domain>`，且 `curl` 無憑證錯誤 | 同上。**逐個 slug 申請憑證不是替代方案**：slug 是動態產生的，Let's Encrypt 的速率限制會在第一個下午就把功能鎖死 |
| 2b | **憑證的簽發路徑真的可用** | wildcard 只能走 **DNS-01**（HTTP-01 簽不出來），所以要有 DNS 服務商的 API token 並實際簽出一張。若網域走 Cloudflare 代理：Universal SSL 只涵蓋 apex 與**深度 1** 的 `*.<domain>`，`*.t.<domain>` 需 Advanced Certificate Manager | **這一項可能翻轉 D3**：改用獨立 apex（`*.cliora-preview.dev`）讓 wildcard 回到深度 1，憑證變便宜、隔離變更強（cross-site），且只是換一個設定值、不改程式。這個結論要寫回 `00-…md` D3 |
| 3 | Railway 的自訂網域支援 wildcard，且指到 console 服務 | 平台上設定後跑 #1、#2；輸出存檔 | 若 Railway 不支援 → 記 waiver，Railway 目標上功能關閉，compose 目標仍可啟用 |
| 4 | wildcard host 的 WebSocket upgrade 能通過 edge（含 Railway edge） | `scripts/tunnel/verify-zone.sh` 對一個 echo 端點做真實 WS 往返 | D4 的 WS 模式不可用 → HMR 不可用，功能價值大幅下降，必須回到 `TN-01` 重新評估是否值得交付 |
| 5 | edge 不會對 wildcard host 套用 console 的 header 集合 | 對 tunnel host 取 header，斷言無 `Content-Security-Policy`、無 `Strict-Transport-Security`（由 zone 決定）、無 `X-Frame-Options` | D20 未落實 → iframe 會被自己的 CSP 擋掉 |
| 6 | `<slug>.tunnel.localhost` 在開發環境可解析且可設 `Secure` cookie | 本機 Chromium 與 Firefox 各跑一次 `frontend/tests/e2e` 的 zone smoke | 本機開發需要改用 `/etc/hosts` 或本機 DNS，寫進 `docs/runbooks/tunnel.md` |

### 2.2 產物

- `scripts/tunnel/verify-zone.sh <zone> [slug]`：黑箱腳本，六項各一個 assertion，任一失敗整支非零，並印出實際取得的值（憑證 SAN、header 清單、WS 往返時間）。沿用 `scripts/railway/verify-deployment.sh` 與 `scripts/p4/verify-edge.sh` 的形狀與紀律。
- `docs/adr/0022-…md` 的「平台事實」一節填入實測輸出的摘要與日期。
- `artifacts/tn/<env>/zone-verify.json`。

### 2.3 驗收

- 六項全部有輸出，或不成立的項目有明確 waiver 與其後果（功能在該環境關閉）。
- 腳本可對 staging 與 production 兩個 zone 各跑一次，輸出可比對。
- **這張票沒有程式相依**，可與 `TN-01` 並行；但兩者都要關，波次 1 才能開工。
