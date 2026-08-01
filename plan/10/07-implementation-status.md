# 07 — 實作進度與證據

本檔隨實作更新；每一列的「證據」欄只填**實際跑過的指令與其輸出位置**，不填計畫中的測試。「量測」欄只填量到的數字，不填 `00-…md` 或 `06-…md` 的目標值。

最後更新 2026-08-01（建立）：**TN-01 – TN-15 全部未開工。**

## 決策紀錄

| # | 決策 | 狀態 | 決定者／日期 | 備註 |
|---|---|---|---|---|
| D-1 | `TN-01`：新增「瀏覽器→node 網路服務」資料面（ADR 0022） | ⬜ 未決定 | — | `01-…md` §1.2 的六項必記內容尚未撰寫。**未核准前 `TN-03` 起的程式不得合併** |
| D-2 | URL 形式：子網域（D1），路徑模式為永久非目標 | ⬜ 未確認 | — | 需 `TN-02` #1／#2 的實測支撐；不成立則整個 URL 方案要重選 |
| D-3 | zone 網域的實際值（`t.<console-domain>` 或獨立網域，D3） | ⬜ 未決定 | — | 只換設定值，不改程式；但一旦有人開始使用就難以更改（同 plan/07 使用規則 1 對 `public_base_url` 的判斷） |
| D-4 | node 端預設啟用 + node veto（`03-…md` §1.2） | ⬜ 未決定 | — | 沿用 ADR 0021 D6 的結論形狀。若改為預設停用，release note 與 runbook 的內容會反過來 |
| D-5 | RBAC：`tunnel.view` / `tunnel.manage` 皆 Admin + Developer，Viewer 無（D9） | ⬜ 未決定 | — | 若日後要給 Viewer `tunnel.view`，前提是先回答「唯讀在被代理的 app 內如何成立」 |
| D-6 | CSP `frame-ancestors` 由 `'none'` 放寬到 `'self'` + `frame-src` 限 zone（D20） | ⬜ 未決定 | — | 這是安全政策變更，屬於 `TN-01` 的核准範圍，不得夾在功能 PR 內 |

## 波次 0：閘門

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| TN-01 | ADR 0022、PRD FR-TUNNEL-001/002/003 與 SCOPE-013、tech 修訂 | ⬜ 未開工 | — | 產出是書面決定，不是程式 |
| TN-02 | 網域與平台事實實測（wildcard DNS／TLS／WS upgrade） | ⬜ 未開工 | — | 六項全部需要對真實網域跑出輸出；**沒有程式相依，可立即開始** |

## 波次 1：契約與資料

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| TN-03 | 契約 v1.6.0：13 個訊息型別、binary kind 3／4、9 個錯誤碼 | ⬜ 未開工 | — | 四筆 invalid fixture 是安全性質的機械化守門，不可省 |
| TN-04 | migration 0014／0015、`tunnel.*` action、settings、error catalog | ⬜ 未開工 | — | `port` 的 CHECK 約束需要一例直接 INSERT 的負向測試 |

## 波次 2：資料面

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| TN-05 | daemon data-plane 連線、`tunnel:` 設定與 port 政策、tunnel 註冊表 | ⬜ 未開工 | — | 簽章前綴的域分離需同時改 `security/node_keys.py` 與 daemon 兩端 |
| TN-06 | daemon HTTP／WS 中繼、有界佇列、逾時、metrics、doctor | ⬜ 未開工 | — | `http.Transport` 的六項設定必須明寫，不得用 `DefaultTransport` |
| TN-07 | Central tunnel registry 與 stream manager | ⬜ 未開工 | — | 代理熱路徑不得查 DB |
| TN-08 | host gate、代理端點、cookie 授權交握、header 政策 | ⬜ 未開工 | — | host gate 的兩個方向各需測試；不得信任 `X-Forwarded-Host` |

## 波次 3：邊緣與介面

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| TN-09 | 兩份 nginx、CSP `frame-src`、Railway wildcard、parity gate | ⬜ 未開工 | — | 四處 CSP 字串必須一起改，parity gate 會擋 |
| TN-10 | REST API 與稽核（三個 action + 節流） | ⬜ 未開工 | — | `tunnel.access_denied` 的節流需要測試證明「第二次不落列但計數器增加」 |
| TN-11 | Node 詳情 Tunnels 區塊、Workspace `WEB` tab | ⬜ 未開工 | — | 「複製 URL」必須複製不帶 ticket 的網址——這是安全相關的斷言 |

## 波次 4：驗證與退出

| Ticket | 標題 | 狀態 | 證據 | 備註 |
|---|---|---|---|---|
| TN-12 | traceability 註冊與影響分析（19 criterion × 4 = 76 條連結） | ⬜ 未開工 | — | selector 必須與測試同一個 PR 落地 |
| TN-13 | 安全審查 13 項對抗 → `docs/security-review-p10.md` | ⬜ 未開工 | — | 第 1、4 項是整個功能的安全論證核心 |
| TN-14 | NFR 量測（延遲、吞吐、終端機不退化 + 反例） | ⬜ 未開工 | — | 沒有反例的效能斷言不算量測 |
| TN-15 | evidence、CI、五份文件、exit gate | ⬜ 未開工 | — | Zone 驗證是唯一 staging-gated 的 gate，不得寫成無條件 skip |

## 量測值（`TN-14`）

| 指標 | 目標 | 量測值 | 環境 |
|---|---|---|---|
| 4 KiB GET 端到端 p95 | ≤ 120 ms | — | — |
| 額外延遲 p95（對照直打 app） | ≤ 80 ms | — | — |
| WS 往返 p95 | ≤ 60 ms | — | — |
| 單 stream 下載 | ≥ 8 MiB/s | — | — |
| 8 並行合計 | ≥ 16 MiB/s | — | — |
| 終端機 p95 退化（隧道滿載時） | ≤ 10 ms | — | — |
| 反例（隧道走控制面 socket 時的終端機 p95 退化） | 應明顯 > 10 ms | — | — |

## 已知會在實作中遇到的事（先寫下來，避免被當成漏掉）

1. **`Host` 被改寫成 `127.0.0.1:<port>`**（`03-…md` §2.1）會踩到 Vite 的 `server.allowedHosts`／Next.js 的 host 檢查。這是刻意的取捨，解法是 app 端讀 `X-Forwarded-Host`。第一個用它的人一定會遇到，所以 runbook 要寫在前面。
2. **回應沒有 `content-length`**（`04-…md` §2.4），所以瀏覽器的下載進度條沒有百分比。
3. **不轉發 `Cookie`／`Authorization`**（`03-…md` §2.3），所以需要登入的 app 在隧道後面無法維持自己的 session。這是本期最大的功能缺口，且它的解法（重寫 cookie 命名空間）與 D14 的「不改寫」直接衝突——要解就要先改 D14，不是繞過它。
4. **位址列只能顯示「導覽到」的路徑**（`05-…md` §3.2），因為跨 origin 的 iframe 讀不到真實 URL。做不到就要在 UI 上誠實。
5. **WS 訊息 >64 KiB 會被關閉（1009）**（`03-…md` §2.2）。不做分片重組是刻意的：訊息邊界是應用層語意。
6. **`tunnel_access_cache_ttl_seconds`（10s）與 cookie TTL（30 分）就是撤銷延遲**（D7）。這不是 bug，是寫下來的數字；若哪天要求「降權立即生效」，代價是每個請求一次 DB 查詢。
