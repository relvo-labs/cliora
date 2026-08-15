# Cliora V2.5 — 需求釐清與任務拆解

> **狀態：`RQ-00`…`RQ-12` 已實作完成（2026-08-14）。**
> `make check` 全綠、十二個 gate 全 PASS、Central 1727 條測試、前端 673 條。
> **實作與計畫的十三處差異、三條部分達成的出口條件，記在
> [`11-implementation-status.md`](./11-implementation-status.md)。**
> `RQ-11b`（mockup 預覽）依 D5 本期不做。
> 前置條件是 V2.3（[`plan/20/`](../20/README.md)）與 V2.4（[`plan/21/`](../21/README.md)）。
> V2.4 的 `09-implementation-status.md` 仍有兩處未結清（§6.3 的 ADR 0033 範圍裁決、
> §6.5 的 Traqora CI）——**兩處都不擋本期開工**，理由在 §「與 V2.4 未結項的關係」。
> 合併規則不變：**`v2` → `dev` 一律由人決定**，出口條件全綠只是取得提案資格。

本目錄是 [`research/02/`](../../research/02/README.md) 規劃的**第七個、也是最後一個階段**的執行計畫，
ticket 統一使用 `RQ-` 前綴（**R**equirements and **Q**uestions）。

規劃層（[`research/02/07-phase-v25-requirements-and-decomposition.md`](../../research/02/07-phase-v25-requirements-and-decomposition.md)）
回答「V2.5 要做什麼、為什麼」；本目錄回答「在**這個 repo 的現況**上怎麼做得出來、做完怎麼證明」。

## 這一期真正的形狀

> V2.4 的 run 是「照卡片宣告的方式交付，並且憑證據判斷憑什麼算做完」。
> 這一期回答的是**更前面的一個問題**：**卡片本身是怎麼來的。**

而它跟前六期有一個結構性的差別，值得寫在最前面：

```text
                       V2.0–V2.4                      V2.5
 新的對外副作用          有（git push、provider API）    **零**
 新的執行能力            有（run、驗證命令）             **零**
 新的憑證                有（run token、provider token） **零**
 contract               v1.10→v1.13                   **不動**
 daemon 的節點半邊       每期都動                       只動 CLI 子命令
 主要工作落在哪           daemon ＋ Central             **Central ＋ 前端**
 風險的形狀              「平台做了不該做的事」          **「平台讓 Agent 的話變成事實」**
```

**本期唯一的新風險是語意的，不是機制的。** 沒有一個新的東西會離開沙箱；
會出事的方式是**一份 Agent 寫的規格被當成人核准過的規格**，
或**一棵 Agent 拆的樹直接變成 `ready` 的卡片**。
所以本期的閘門幾乎全部長成同一個形狀：**Agent 寫的東西一律是「提案」欄位，
而「已核准」欄位只有帶人類 actor 的路徑寫得到。**

## 一個已經做完一半的階段

這是本期與其他六期最不一樣的地方，**而它決定了工作量的分佈**：

`version2.md` §17 要求「先建立可靠的資料結構與人工操作流程，再讓 Agent 使用相同 API」，
V2.1 照做了。**所以三張表、五個 refusal、七條 API 路由、一個詳情頁都已經在庫裡：**

| 東西 | 現況 | 位置 |
|---|---|---|
| `requirements`／`feature_specs`／`task_proposals` | **已存在**（migration `0023`） | `backend/app/db/models.py:577-670` |
| 「未解決的 open questions 不得核准」 | **已實作**，API 層 | `services/requirements.py:241-252` |
| 「未核准的規格不得拆解」 | **已實作**，API 層 | `services/requirements.py:279-284` |
| 「缺 DoR 的提案卡落 `backlog`」 | **已實作** | `services/requirements.py:368` |
| 部分接受 ＋ 冪等 | **已實作** | `services/requirements.py:341-352` |
| 卡片回溯到需求／提案 | **欄位已存在**（`tasks.requirement_id`／`proposal_id`） | `models.py:756-761` |
| 七條人工路由 | **已存在** | `api/http/requirements.py` |
| 需求詳情頁 | **已存在**（361 行） | `frontend/src/views/RequirementDetailView.vue` |
| `ui` gate 在 tunnel 整合未啟用時自動停用 | **已實作** | `services/process.py:162-208` |
| `waiting_for_input` 24h 逾時退 `blocked` | **已實作** | `services/run_reaper.py:122-168` |
| 卡片訊息串（`say`／`ask`／`messages`） | **已實作** | `api/http/agents.py` 的 `run_router` |

**所以本期不是「做一個新功能」，是「把 Agent 接到一條已經在跑的路上」。**
這句話有兩個後果，兩個都影響計畫的形狀：

1. **工作量比 research/02/07 的字面篇幅小得多**，但**授權邊界的工作比它寫的多**——
   因為那條路現在只有人在走，而人持有 `task.create` 與 `task.approve`，
   run 憑證兩個都沒有，**也不能有**。
2. **最大的一塊是前端**，而不是後端。規格審閱、提案樹的勾選介面、來源可追溯
   ——`RequirementDetailView.vue` 目前只到「列出來」，離「可以在上面做決定」還有距離。

## 六個必須先裁決的東西

完整表格在 [`00-execution-plan.md`](./00-execution-plan.md) §0。這裡只列出**選錯會讓某一節整段作廢**的六個：

| # | 問題 | 計畫的答案 | 選錯的代價 |
|---|---|---|---|
| **D0** | `feature_specs` 要不要補上 Monstrare 規格書缺的那幾節 | **加一個 `sections JSONB`**，既有五欄不動 | 不加 → 拆解 run 沒有 User Stories 可讀，Epic→US→Task 的中間層變成 Agent 憑空生成（易錯 7） |
| **D1** | 平台怎麼分辨「這是一張釐清卡」 | **新欄位 `tasks.card_kind`**（四值） | 用 tag 或 `delivery` 推斷 → 出口條件 7／11 都變成「靠約定」，而約定沒有 refusal |
| **D2** | Agent 怎麼提交規格與提案 | **run 憑證專用的兩條新路由**，不放寬既有的七條 | 放寬 `POST /requirements/{id}/proposals` 的權限 → 任何 run 憑證可對**任何**需求提案 |
| **D3** | 「一次一個問題」在哪裡強制 | **伺服器端**，`kind=question` 且有未答問題時拒絕 | 只寫在情境包 ＋ CLI → Agent 直接打 HTTP 就繞過了，而那是它最容易做的事 |
| **D4** | 逾時的釐清 run 怎麼「不整批丟棄」 | **情境包要求每輪送一版草稿** ＋ 訊息串本來就永久 | 靠平台在逾時當下「把對話整理成規格」→ 那是平台在替 Agent 寫規格 |
| **D5** | RQ-07（UI Mockup）本期做不做 | **拆兩半：未啟用時的正確性必做，啟用時的預覽延後** | 整包延後 → 出口條件 11 沒人驗；整包做 → 本期唯一的新對外面，而它換不到本期的目標 |

## 上游的另一半：`../Monstrare`

`research/02/07` 說本期對應 Monstrare 的 `spec-interrogation`、`project-kickoff`、
`implementation-plan` 三個 skill 與 `workflow.md` 的 Phase 0–5。
**本計畫把那四份文件逐段讀過**，結論是三件事，三件都影響資料層：

**一、內化其實已經完成了十分之八，而缺的兩格正是本期。**

| Monstrare `kanban.md` 的 12 個治理欄位 | 平台的落點 | 誰交付 |
|---|---|---|
| 收件匣（Inbox） | `requirements.status = 'intake'` | V2.1 ✅ |
| **待釐清** | `'clarifying'` ＋ 釐清 run 在 `waiting_for_input` | **V2.5（本期）** |
| 待產品核准 | `'specified'` → `approve` | V2.1 ✅ |
| 待 UI Mockup | `tasks.gates.ui`（tunnel 整合未啟用時自動停用） | V2.1 ✅／RQ-11b 未做 |
| 待架構規劃 | `tasks.gates.architecture` | V2.1 ✅ |
| **待任務卡** | `task_proposals.status = 'pending'` | **V2.5（本期）** |
| AI 就緒 | `tasks.stage = 'ready'` ＋ DoR 七項 | V2.1 ✅ |
| Agent 執行中 | `implementing` ＋ `task_runs` | V2.2 ✅ |
| 待驗證 | `verify` ＋ `verification_reports` | V2.4 ✅ |
| 待審查 | `tasks.gates.*` | V2.1 ✅ |
| 待人工驗收 | Done Gate 六條 | V2.4 ✅ |
| 完成 | `done` | V2.1 ✅ |

**這張表就是「V2 有沒有真的內化 Monstrare」的答案**，而本期填的是中間那兩格。
它要進 ADR 0034，因為它是本期唯一一次可以把這句話說完的機會。

**二、`feature_specs` 只有 Monstrare 規格書的五分之二，而缺的那格是拆解要吃的。**
見下方易錯 7——這是本計畫在資料層上最大的一次偏離。

**三、Monstrare 有四樣東西平台沒有內化，本期也不內化，但要寫下來。**

| 沒內化的 | Monstrare 的位置 | 對本期的影響 | 處置 |
|---|---|---|---|
| **Security Gate** | `review-gates.md` 六個關卡之一 | 停止條件第四條（涉及密鑰／認證／金流／遷移／基礎設施）**在平台上沒有對應的關卡可以落地**——`process_definitions` 的六個 gate 是 `requirements`／`architecture`／`ui`／`implementation`／`verification`／`release`，沒有 `security` | **本期不加**（改動的是每個專案的共用詞彙，比 V2.5 大）。改為：命中第四條的提案卡強制 `risk: high` ＋ 問題留在 `open_questions`，接受介面顯示高風險徽章。追蹤項在 `10-…md` §4 |
| **`design-system.md`** | `ai/context/design-system.md`，是 `ui-mockup-gate` 的強制前置 | Monstrare 的 mockup 關卡要求「變體必須用已定案的 token 與元件拼出來」，而平台**沒有這份文件的等價物** | **這是 D5 把 RQ-11b 延後的第三個理由**，寫進 `08-…md` §3.0 |
| **條件式 DoR** | `definition-of-ready.md`：十項必要條件之外，UI 工作 8 項、後端／資料 6 項、高風險 4 項的**額外要求** | 平台的 `readiness` 是一張平坦的七項清單，沒有「依卡片性質變動」的概念。拆解出來的 UI 卡與後端卡用同一把尺 | **不改資料模型**。最小的補法是在拆解情境包裡依 `track` 給不同的補充清單（`10-…md` §4 第 5 項） |
| **Epic 0「專案設置」** | `project-kickoff.md` 步驟 2，含 `dependsOn` 全部設置卡的強制規則 | 它假設一個**全新專案**，而平台上的需求是往一個已經存在的專案丟的 | 整段跳過，寫進 ADR 0034 的 Alternatives rejected（`03-…md` §2.4 末段） |

## 七個容易踩的地方

寫計畫的過程中實際讀了程式碼與 `../Monstrare`，這七個是「照 `research/02/07` 的字面做會出事」的地方。

### 易錯 1 — `research/02/07` 的 migration 編號與表名都過期了

上游寫「migration `0030`」、`feature_specs.run_id`、`task_proposals.spec_seq`、
`requirements.epic_id`。**實際上**：head 是 `0038`（本期是 **`0039`**）、
三張表在 `0023` 就建好了、欄位名是 `spec_id` 不是 `spec_seq`、`requirements` **沒有** `epic_id`。

照字面做會得到一份跑不起來的 migration，而且是在 `alembic upgrade head` 那一刻才發現。
**`02-data-layer.md` §1 逐欄列出實際的現況與差額。**

### 易錯 2 — 「Agent 產出提案」需要的權限，現在在人身上

`POST /api/requirements/{id}/proposals` 要 `task.create`。
`RUN_TOKEN_SCOPES = {project.view, task.update}`（`agent_auth.py:70`），**而且那個模組的註解白紙黑字寫著
`task.create` 被排除的理由是「an agent proposes, a human creates — D28」**。

於是有一個看起來像矛盾的東西：**D28 說 Agent 要產出提案，而防止 Agent 產出東西的註解也引用 D28。**
兩句話都對，衝突在於「提案」被誤當成「建立」。
**解法不是放寬那條路由**（放寬等於讓任何 run 憑證對任何需求提案），
而是開一條 `POST /api/cli/runs/proposal`：只要 `task.update`，
但**資源邊界收在 `principal.task_id → tasks.requirement_id`**——這張卡屬於哪個需求，就只能對那個需求提案。
`05-…md` §2 是完整論證。

### 易錯 3 — 情境包的預算不是 4 KB，但也不是 32 KB

`research/02/01` D8 寫「≤4 KB 預算」；`run-spec.schema.json` 的 `context` 是 `maxLength: 32768`，
而它的 `$comment` 記著「a rendered context pack measures 1–2 KB」。

釐清的情境包要塞：原始需求原文 ＋ 既有規格草稿 ＋ 未解決問題 ＋ 五條停止條件 ＋ 提問規約。
**第二輪之後很容易破 4 KB**，而破了不會有錯誤——`maxLength` 是 32 KB，所以它會安靜地送出去，
然後佔掉 64 KiB 控制訊框裡不成比例的一塊。

本期給的是**分層預算與可驗證的截斷順序**（`03-…md` §2.3），並把它變成一項量測（M-RQ-1）。

### 易錯 4 — 「24h 未回覆不整批丟棄」目前是真的會丟

`run_reaper.py` 逾時的處置是 run 失敗 ＋ 卡片退 `blocked`。
**這是對的，而且不必改**——真正會丟掉東西的不是 reaper，是「Agent 問了五輪、一版草稿都沒送」。

出口條件 10 說「已問到的內容保留為規格草稿」。
訊息串本身永久（`TaskMessage` 的 `run_id` 是 `SET NULL`，模型註解已寫明「a card's conversation has no retention」），
但**訊息串不是規格草稿**。所以本期的做法是 D4：
情境包要求 Agent **每答完一輪就送一版 `feature_specs`**（未解決的留在 `open_questions`），
而出口條件 10 的驗收方式改成一條可查的斷言：**逾時之後 `feature_specs` 的列數 > 0**。

### 易錯 5 — `ui` gate 已經自動停用了，但 dispatch 還沒有那條拒絕

出口條件 11 有四個子項。**第一項（gate 自動停用）已經做完了**（`process.py:189-191`），
**第三項（產出 mockup 變體的卡片 dispatch 被拒）沒有任何程式碼**，
第二項（Project Settings 寫出停用原因）前端沒有那段文案。

所以 RQ-11a 不是「做一個新關卡」，是**把一個做了三分之一的關卡補成可驗的**。
這也是 D5 把它切成兩半的直接理由。

### 易錯 6 — 本期不動 contract，但**會動 `context` 的內容**

`research/02/08` §194 寫「V2.5：contract v1.13.0 不變、agentd 0.11.0 不變」。
前半正確：**沒有任何 schema 需要改**。後半不正確：CLI 要新增三個子命令
（`cliora spec submit`、`cliora proposal submit`、`cliora requirement show`），
那是 `daemon/` 的程式碼，**agentd 進 0.12.0**。

值得一起記的是為什麼這不觸發「舊 node 靜默丟 offer」那個老問題（V2.4 README 易錯 1）：
本期新增的東西**全部在 HTTP 那一側**（`/api/cli/runs/*`），
一個舊 node 收到的 `run.offer` 逐欄位與 V2.4 相同，只有 `spec.context` 的字串內容不同。
**字串內容不受 `DisallowUnknownFields` 管。** 舊 node 會正常執行，只是它的 CLI 沒有新子命令
——那時 Agent 呼叫 `cliora spec submit` 會得到 cobra 的 unknown command，
而**那個失敗是可見的**（非零 exit code ＋ 訊息），不是靜默丟棄。

### 易錯 7 — `feature_specs` 少了拆解要吃的那一格

`../Monstrare/ai/templates/feature-spec.md` 的規格書有十二節。
`feature_specs` 這張表有**五個欄位**（`objective`／`scope`／`non_goals`／
`acceptance_criteria`／`open_questions`）。缺的七節裡，**有三節不是裝飾**：

| Monstrare 的節 | 為什麼缺了會出事 |
|---|---|
| **使用者故事（User Stories）** | `spec-interrogation` 的輸出裡，這一節**就是拆解的輸入**——`project-kickoff` 步驟 4 明寫「規格書裡的『User Stories』章節就對應這裡勾選出的清單」。少了它，拆解 run 拿到的規格**沒有 Epic→US→Task 中間那一層的來源**，只能自己憑 `objective` 猜 |
| **畫面（Screens）** | 決定一張卡要不要走 `ui` gate 的依據。少了它，`card_kind: mockup` 與 `gates.ui` 都沒有上游 |
| **驗證計畫** | V2.4 的 `verification_commands` 與 `acceptance_criteria` 的來源。少了它，拆解出來的卡片 DoR 的「驗證方式已定義」永遠是 Agent 自由發揮 |

**處置：`feature_specs` 加一個 `sections JSONB` 欄位**（`02-…md` §1.3），
而不是加七個 column——那七節的形狀是文件，不是查詢對象，
與 `task_proposals.tree` 用 JSONB 的理由完全相同。
既有五個欄位**一個都不動**，V2.1 寫的規格照樣讀得出來（`sections` 預設 `{}`）。

## 裁決紀錄

本目錄的形狀被以下裁決決定。**這張表是唯一的索引**，各處 inline 註記都指回這裡。

| 日期 | 裁決 | 對本期的意義 |
|---|---|---|
| 2026-08-08 | **D28：釐清用既有管道；Agent 產出是提案；三個人工關卡；資料模型 V2.1／Agent 驅動 V2.5** | 整期的骨架。ADR 0034 是它的落地 |
| 2026-08-08 | **D24：`task ask` → `waiting_for_input` → 卡片顯示等待回覆** | 釐清**沒有新介面**的原因。D3 在這條路上加一道伺服器端閘門 |
| 2026-08-08 | **D31：Mockup 走既有 tunnel；未啟用整合就沒有 mockup** | RQ-11 的前提。D5 把它切成 a／b 兩半 |
| 2026-08-08 | **D29：卡片產物是最安全的一種出口**；HTML 產物不得在應用 origin 渲染 | RQ-11b 若要做，這一條是它的邊界；RQ-11a 不碰它 |
| 2026-08-12 | **不做 `project_agents`；授權邊界永久是 enrollment** | 本期同樣不新增任何授權表。兩條新路由的邊界是 `principal.task_id`，不是一張表 |
| 2026-08-14 | **卡片宣告驗證命令要 `task.approve`；`RUN_TOKEN_SCOPES` 永不含它** | **本期最重要的既有結論**：D2 的兩條新路由必須維持這條邊界，而不是在旁邊開一個洞 |
| **本計畫** | **D1：新增 `tasks.card_kind`（四值）** | dispatch 的三道新拒絕、兩條新路由的守衛、前端的三種卡片外觀，都讀這一個欄位 |
| **本計畫** | **D2：兩條 run 憑證專用路由，不放寬既有七條** | `05-…md` §2 |
| **本計畫** | **D3：「一次一個問題」在伺服器端強制** | `03-…md` §3 |
| **本計畫** | **D5：RQ-11 切成 a（必做）／b（延後）** | `08-…md` |

## 與 V2.4 未結項的關係

V2.4 的 `09-implementation-status.md` 留了兩項，**本計畫確認兩項都不擋本期開工**：

| V2.4 未結項 | 為什麼不擋 V2.5 |
|---|---|
| §6.3 — ADR 0033「平台永不合併」的範圍要不要改寫（Agent 自己開 PR 那條路） | 本期產出的卡片**預設 `delivery` 由拆解決定**，而拆解出來的卡走的是 V2.4 已有的五條路。本期不新增第六條，也不改變那兩條路的任何一條。**但它會放大那個問題的曝光面**——拆解一次可能產生十張 `pull_request` 卡——所以 `01-…md` §5 把它列為**本期要一起帶著問的事**，不是本期要解的事 |
| §6.5 — Traqora CI 自 2026-08-10 起紅（與變更無關，缺 billing 權限無法確認） | 本期的 E2E 標的是**釐清與拆解，不是 PR**（出口條件 8 明寫遠端零變更）。Traqora 只用來提供「一句真實的模糊需求」與一份可讀的 repo。**CI 綠不綠不影響任何一條出口條件** |

## 文件導覽

| 文件 | 內容 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | **待裁決項目**、成功定義、不得弄壞的清單、13 張 ticket、開工順序與相依 |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | `RQ-00` 基線、`RQ-01` ADR 0034 ＋ PRD §8.16 ＋ traceability、三則增補、要一起帶著問的事 |
| [02-data-layer.md](./02-data-layer.md) | `RQ-02` migration `0039`：`card_kind`、兩個 `run_id`、`document_patch_proposals`、seed |
| [03-clarification-run.md](./03-clarification-run.md) | `RQ-03`／`RQ-04`／`RQ-05`：卡片種類與四道 dispatch 拒絕、情境包與預算、一次一個問題、規格提交 |
| [04-decomposition-and-proposals.md](./04-decomposition-and-proposals.md) | `RQ-06`／`RQ-07`：提案提交、DoR 七項、顆粒度、三個人工關卡的收口 |
| [05-prd-patch-proposals.md](./05-prd-patch-proposals.md) | `RQ-08`：`document_patch_proposals`、平台只渲染與記錄、接受後怎麼變成一張卡 |
| [06-cli-and-daemon.md](./06-cli-and-daemon.md) | `RQ-09`：agentd 0.12.0 的三個子命令、離線行為、為什麼 contract 不動 |
| [07-frontend.md](./07-frontend.md) | `RQ-10`：Requirements 分頁、規格審閱與版本比較、提案樹、來源可追溯 |
| [08-ui-mockup-gate.md](./08-ui-mockup-gate.md) | `RQ-11a`（必做）／`RQ-11b`（延後）：未啟用時的正確性、啟用時的六件事 |
| [09-verification-and-exit.md](./09-verification-and-exit.md) | `RQ-12`：測試矩陣、十個 gate、**24 條**出口條件、**一節**安全審查、旗標關閉回歸 |
| [10-open-measurements.md](./10-open-measurements.md) | M-RQ-1…5、繼承的未結量測、上線後要觀察的兩件事 |
| [11-implementation-status.md](./11-implementation-status.md) | **實作狀態**：完成度、與計畫不同的十處、24 條出口條件對照、合併前建議做的三件事 |

## 基線數字（2026-08-14 實測）

| 項目 | 值 | 取得方式 |
|---|---|---|
| migration head | `0038_runner_features` | `ls backend/app/db/migrations/versions/` |
| `__tablename__` 數 | **39** | `models.py` 正則盤點；`schema.txt` 應為 **40**（含 `alembic_version`） |
| RBAC 動作 | **27** | `rbac.py` 常數盤點 |
| contract fixtures | **76 valid ＋ 107 invalid**（`schema.txt` 對照 184 行含 `manifest.json`） | `ls contracts/v1/fixtures/*` |
| 前端路由 | **19** | `grep -c "path:" frontend/src/router/index.ts` |
| contract 版本 | **v1.13.0** | `contracts/CHANGELOG.md` |
| agentd 版本 | **0.11.0-dev** | `daemon/cmd/agentd/main.go:20` |
| ADR 最新編號 | **0033** | `ls docs/adr/` |
| PRD 最新節 | **§8.15 交付、驗證與完成判準** | `research/prd.md:2348` |

> **這些數字是 `RQ-00` 基線的預期值**，不是基線本身。對不上的時候以基線為準並回寫這裡。

## 執行慣例

沿用前六期：一個背景 tmux 承載長時間工作，不佔用互動視窗。

```bash
tmux new-session -d -s cliora-v25 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v25 'make check' C-m
tmux attach -t cliora-v25
```
