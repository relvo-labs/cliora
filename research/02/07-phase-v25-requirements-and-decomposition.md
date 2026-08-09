# V2.5 — 需求釐清與任務拆解（ticket 前綴 `RQ-`）

## 目標

把 Monstrare 最前段的能力內化進平台：**從一句模糊的需求，經過反覆提問，變成一份人工核准的規格，再拆成一批 AI-ready 的任務卡。**

對應 Monstrare 的 `spec-interrogation`、`project-kickoff`、`implementation-plan` 三個 skill，以及 `ai/process/workflow.md` 的 Phase 0–5。

## 一個關鍵發現：釐清不需要新機制

「Agent 反覆詢問使用者以理解需求」在這個架構裡**已經有現成的管道**——就是 D24 設計的看板溝通：

```text
Agent 用 cliora task ask 提問
  → run 進 waiting_for_input，租約續租但不計執行逾時
  → 卡片顯示「等待你的回覆」（看板上最醒目的狀態）
  → 使用者在卡片訊息串回答
  → Agent 下次拉取就看到，繼續問或收斂
  → 24h 未回覆自動退 blocked
```

**不要為了釐清另做一套聊天介面。** 兩套訊息管道會立刻分裂：使用者不知道該在哪裡回話、Agent 不知道該讀哪一邊、稽核要看兩個地方。這一條寫進 ADR 的 Alternatives rejected。

這也回頭證明 D24 的形狀是對的——它原本只是為了「執行中的 Agent 能提問」，結果整個釐清流程直接落在上面。

## 前置條件

- **V2.3 出口條件全數通過**（釐清需要讀 repo → 需要隔離目錄與 git）。
- **不依賴 V2.4**：釐清與拆解的 `delivery` 是 `none` 或 `artifact`，都不推 git（`artifact` 的機制在 V2.2 就有）。所以本階段可與 V2.4 並行，只要團隊有餘裕。
- V2.1 已交付規格與提案的**資料模型與人工表單**（見下方「為什麼分兩段」）。
- D28 已裁決；ADR 0034（需求釐清與拆解的形狀）已撰寫並接受。

### 為什麼分兩段：資料模型在 V2.1，Agent 驅動在 V2.5

這不是我的偏好，是 `version2.md` §17 自己寫的：

> 不要先做 Agent 自動生成 PRD。**先建立可靠的資料結構與人工操作流程，再讓 Agent 使用相同 API。**

所以 V2.1 就要有 `requirements` 與 `feature_specs` 的表與表單，讓人可以自己寫規格、自己拆卡。V2.5 只是讓 Agent 走**同一條 API**。如果 V2.1 的人工流程沒人用，那 V2.5 也不會有人用——這是一個免費的早期訊號。

## 工作包

### RQ-01 — ADR 0034：釐清與拆解的形狀

四段：

1. **釐清用既有管道**（上方那段），不新增聊天介面。
2. **Agent 的產出是提案，不是正式資料。** 拆解 run 產生 `task_proposals`，人接受之後才建立真正的 Epic／User Story／Task。這是 `review-gates.md`「agent 輸出不等於核准」在這條路徑上的形式。
3. **三個人工關卡**：規格核准（product gate）、提案接受、UI 變體選定（若涉及畫面）。每個關卡都必帶人類 actor 與 audit，**Agent 憑證的 scope 永遠不含它們**。
4. **停止條件**（直接內化 `ai/process/context-protocol.md` 的那五條）：搜尋發現多種做法且各有取捨、需求與既有架構衝突、缺少必要檔案、任務涉及密鑰／認證／金流／遷移／基礎設施、預估範圍超出卡片——**遇到任一條就停下來問，不要自己選**。這五條寫進釐清 run 的情境包。

**Alternatives rejected**：Agent 直接建立正式卡片（繞過 DoR 與人工核准）、平台自動接受低風險提案（「低風險」的判定本身就是 Agent 說的）、獨立的釐清聊天介面（管道分裂）、一次要求產生完整 Roadmap（`version2.md` §7.7 明文不要求）。

### RQ-02 — 資料模型

migration `0030`：

```text
requirements              使用者丟進來的原始需求（Intake）
  id / project_id / title / body / submitted_by / created_at
  status  draft | clarifying | specified | approved | rejected
  epic_id nullable        ← 核准後歸屬到哪個 Epic

feature_specs             規格（版本列，只 INSERT）
  id / requirement_id / seq / run_id nullable
  objective / scope / non_goals
  acceptance_criteria JSONB
  open_questions     JSONB   ← 未解決的問題，不得被靜默省略
  risk / affected_areas JSONB
  authored_by  人類 user_id 或 runner
  approved_by / approved_at  ← 人類，null = 未核准
  UNIQUE (requirement_id, seq)

task_proposals            拆解提案（一次拆解一列，內含整棵樹）
  id / requirement_id / spec_seq / run_id
  tree JSONB              ← [{kind: epic|user_story|task, ...卡片欄位}]
  status pending | partially_accepted | accepted | rejected
  decided_by / decided_at / decision_note
  created_task_ids JSONB  ← 接受後真正建立了哪些卡
```

三個設計說明：

- **`feature_specs` 是版本列，只 INSERT**（與 `execution_plans` 同樣的理由，D9）：規格改過什麼、為什麼改，比現值更有價值。
- **`open_questions` 是一等欄位，不是備註。** 規格裡沒解決的問題必須看得見；`version2.md` §7.6 的 PRD Patch 也列了同一個欄位。**帶著未回答問題的規格不得被核准**——這是 RQ-05 的閘門之一。
- **`task_proposals.tree` 用 JSONB 存整棵樹**，因為它在被接受之前不是實體，沒有獨立查詢需求。接受之後才變成真正的 `epics`／`user_stories`／`tasks` 列。

### RQ-03 — 釐清 run

卡片的執行設定：`source: repo`（要讀程式碼才問得出好問題）、`delivery: artifact`（規格本身可以附成一份可下載的文件）或 `none`、`required_secrets: []`（釐清不需要機密——**這一條要在 dispatch 時強制**，不是建議）。

情境包（沿用 D8 的 ≤4 KB 預算）給的是：

```text
原始需求（使用者寫的那段話，原文照錄）
既有規格草稿與其 open questions（若是第二輪）
專案 conventions 與 architecture 摘要的路徑
本專案已知的非目標
停止條件五條（RQ-01 §4）
提問方式：cliora task ask，一次一個問題
```

**一次一個問題。** 一口氣丟五個問題給使用者，實務上會得到三個答案與兩個被忽略的問題，而 Agent 無法分辨哪個被忽略了。這一條寫進情境包，並在 CLI 端限制 `task ask` 的頻率。

產出：一列 `feature_specs`（狀態未核准）＋ `open_questions`。**Agent 不得把未解決的問題自己填答案**——不知道就留在 `open_questions` 裡，那正是它存在的理由。

### RQ-04 — 拆解 run

輸入：一份**已核准**的 `feature_specs`。未核准的規格不得被拆解（閘門在 API，不是靠 Agent 自律）。

產出：一列 `task_proposals`，樹的每個節點是 Epic／User Story／Task。**每張提案的 Task 必須自帶完整的 DoR 七項**，否則不能被接受為 `ready`：

```text
目標明確具體 / 行為清楚 / 範圍有界 / 相關檔案或搜尋入口
驗收標準可測試 / 非目標明確 / 風險等級 / 驗證方法
```

外加 V2 執行模型需要的欄位：`source`、`delivery`、`target_branch`、`required_labels`、`required_secrets`、`dependsOn`。

**`delivery` 由拆解決定，這是它最有價值的判斷之一**：哪些卡要出 PR、哪些只交付一份報告（`artifact`）、哪些純執行不留東西（`none`）。拆解時就分清楚，比事後補救便宜得多。

不要求一次產生完整 Roadmap（`version2.md` §7.7 明文）。拆到「一個畫面狀態／一個 API endpoint／一個元件行為／一個 bug 的重現與修復／一個測試缺口」這個顆粒度就停（Monstrare 的建議卡片大小）。

### RQ-05 — 人工關卡

三個，各自獨立、各自必帶人類 actor：

| 關卡 | 進站條件 | 誰核准 | 動作 |
|---|---|---|---|
| 規格核准 | **`open_questions` 全部已解決或明確標為「已知未知」** | `task.approve` | `requirements` 進 `approved` |
| 提案接受 | 規格已核准 | `task.create` | 全部接受／部分接受／編輯後建立／拒絕（`version2.md` §7.7） |
| UI 變體選定 | 卡片 `kind=ui`（RQ-07，可延後） | `task.approve` | 決定記錄在卡片 |

**被拒絕的提案要保留，附理由。** 下次拆解時把它放進情境包當作負面情境——這是這條路徑上唯一會累積的學習訊號，丟掉很可惜。

接受時建立真正的卡片，`activity_events` 記錄「由提案 #N 建立」，讓每張卡都追得回它的來源需求。

### RQ-06 — PRD Patch 提案

（從 V2.4 移來——它屬於這裡，它是釐清的產物之一。）

照 `version2.md` §7.6 的四步，但**平台不套用**：

```text
使用者提需求 → Agent 分析受影響的文件 → Agent 寫 patch 提案
            → 平台渲染 diff 與理由 → 人接受／拒絕
            → 接受後由 Agent（或人）在後續 run 中自己套用（走 delivery: pull_request）
```

平台只做「渲染 ＋ 記錄決定」。理由：套用一份 markdown patch 是通用檔案編輯，那是 `plan/14` 被撤銷的東西；而讓它走一張正常的 `delivery: pull_request` 卡片，PRD 的修改就跟程式碼一樣有 PR 可審——**這比平台代為套用好，不只是比較安全**。

提案內容照 `version2.md` §7.6：Added／Modified／Removed Sections、Reason、Related Tasks、Open Questions。

### RQ-07 — UI Mockup 關卡（**有條件，且可延後**）

Monstrare 的 `ui-mockup-gate`：涉及畫面的卡片在 `ready` 之前要有 2–3 個變體與人工選定。

#### 前置條件：tunnel 整合必須已啟用（D31）

**沒有啟用 tunnel 整合（目前唯一供應商是 Pinggy），系統就不做 mockup。** 這不是降級模式，是整個關卡不存在：

| | 未啟用 | 已啟用 |
|---|---|---|
| UI Mockup 關卡（變體、選定、`links.mockupDecision`） | **不存在** | 存在 |
| `process_definitions` 的 `ui` gate | **自動停用** | 可用 |
| Agent 附截圖為卡片產物 | **照常**（D29 的通用能力） | 照常 |

**`ui` gate 必須由系統自動停用，不能只是「Admin 可以關掉」**——否則涉及畫面的卡片會卡在一個永遠無法滿足的關卡上，那是死鎖不是嚴謹。

#### 落地方式（整合已啟用時）

mockup 變體同時是**卡片產物**（截圖，永久）與 **Pinggy 預覽**（互動，暫時）。人檢視後選一個，決定記錄在卡片的 `links.mockupDecision`。

流程完全複用既有機制，沒有新元件：

```text
Agent 用 cliora task ask 問「這份 mockup 要用哪種保護？密碼／限制 IP／不保護」
  → 卡片顯示「等待你的回覆」（D24）
  → 人選擇 → 平台以那個策略開 tunnel → Agent 只被告知 URL
```

**開 tunnel 的是人，不是 Agent**——`tunnel.manage` 永不在 Agent 憑證的 scope 內。這是紅線 5 得以成立的關鍵（D31）。

#### 為什麼是 tunnel 而不是平台自己渲染

Cliora 是**單一 origin 部署**（ADR 0020）。在應用 origin 裡渲染 Agent 產生的 HTML，那份 HTML 就能讀 `localStorage`（裡面有 JWT）、以使用者身分打同源 API、改寫整個頁面。**「是我們自己的 Agent 做的」不是信任邊界**——Agent 讀過 repo 內容、可能被 prompt injection。

Pinggy 的 URL 是**完全不同的 origin**，同源政策自己就擋住了——沒有 sandbox flag 要調，沒有 CSP 要對。而且 mockup 沒有真實資料，正好落在 ADR 0022 的範圍宣告內（「用於預覽開發中的應用，不適用於任何持有真實資料的環境」），比它原本的使用情境更貼合。

#### dispatch 行為分兩種卡

| 卡片性質 | 未啟用整合時 |
|---|---|
| **產出 mockup 變體**是這張卡的交付物 | **dispatch 當下拒絕**，理由寫明整合未啟用 |
| 一般 UI 實作卡 | **照常執行**，`links.mockupDecision` 的要求解除 |

#### 六件要設計的事（沿用 D31）

只服務 `artifacts/preview/`（不列目錄、不是 `repo/`）、預覽程序不繼承 run 的 env、生命週期綁 run、**預設密碼保護且密碼由平台產生**、「不保護」需額外確認並寫 audit、每個 Project 有併發上限。

**這一包可以延後，不影響其餘七包。** 若團隊目前沒有 UI 工作或沒啟用 tunnel 整合，先不做。

### RQ-08 — 前端

- **Intake 入口**：Project 下的 `Requirements` 分頁，或全域的「提個需求」按鈕。輸入框刻意簡單——**它接受的就是一句模糊的話**，那是整條流程的前提。
- **釐清中的對話**：**重用 V2.2 的卡片訊息串元件**，不新做。差別只在頁面位置。
- **規格審閱**：objective／scope／non-goals／AC 逐項、`open_questions` 置頂且未解決時核准按鈕停用、版本比較（第 N 版 vs 第 N-1 版）。
- **提案樹的接受介面**：樹狀勾選（Epic／US／Task 三層可獨立勾）、可就地編輯欄位、顯示每張卡的 DoR 缺項、底部顯示「將建立 N 張卡片」。
- **來源可追溯**：每張卡的詳情頁顯示「來自需求 #12 的提案 #3」。

## 這一階段明確不做

- 不做自動核准（任何一個關卡都不行）。
- 不做「Agent 自動把需求丟進佇列自己拆自己做」的全自動鏈——每個關卡都要人。
- 不做需求的優先權排序、工時估算、Sprint 規劃（`00` §9）。
- 不套用 PRD patch（只渲染與記錄決定）。
- 不新增訊息管道（釐清走既有的看板訊息串）。
- 不要求一次產生完整 Roadmap。

## 出口條件

1. 丟一句模糊需求 → 釐清 run 領走 → **在看板訊息串裡提問**（不是另一個介面）→ 使用者回答 → 產出規格草稿。
2. 規格帶未解決的 `open_questions` 時，**核准按鈕停用**，且說明是哪幾個問題。
3. 未核准的規格**不能**被拆解（API 層拒絕，不是 UI 隱藏）。
4. 拆解產出的每張 Task 提案都帶完整 DoR 七項與 `source`／`delivery`；缺項的卡在接受介面上標示，**接受後直接落在 `backlog` 而非 `ready`**。
5. 部分接受：勾 3 張建立 3 張，其餘保留在提案裡；被拒絕的提案保留理由。
6. 建立出來的卡片詳情頁顯示「來自需求 #N 的提案 #M」。
7. 釐清 run 嘗試帶機密 → **dispatch 當下被拒**（釐清不需要機密）。
8. 釐清 run 的 `delivery` 是 `none`／`artifact`，**執行後遠端沒有任何變更**；若工作目錄有變更則明示並附成產物（V2.4 DV-01 的誠實性規則）。
9. Agent 嘗試自己核准規格或接受提案 → 被拒（scope 不含 `task.approve`）。
10. 24h 未回覆的釐清 run 自動退 `blocked`，已問到的內容保留為規格草稿，**不整批丟棄**。
11. 旗標關閉：完整 V1 回歸全綠。

## 風險

| 風險 | 對策 |
|---|---|
| **Agent 一口氣問十個問題** | 情境包明寫「一次一個」＋ CLI 端限制 `task ask` 頻率；出口條件 1 檢查對話節奏 |
| Agent 自己編答案填掉 open questions | `open_questions` 是一等欄位；核准閘門檢查它；出口條件 2 |
| 拆出一堆不可執行的卡 | DoR 七項為接受條件；缺項的卡落 `backlog` 不落 `ready`（出口條件 4） |
| 拆解變成「一次產生 80 張卡」 | 顆粒度指引寫進情境包；接受介面顯示總數；不要求完整 Roadmap |
| 釐清與執行的對話混在一起 | 同一條訊息串但不同卡片；釐清卡與實作卡是不同的卡 |
| 兩套訊息管道 | ADR 明列為 rejected；前端重用同一個元件（RQ-08） |
| 人工關卡變成橡皮圖章 | 核准必帶人類 actor 與時間、永久可見；指標追蹤「核准到接受的中位時間」，太短是警訊 |
