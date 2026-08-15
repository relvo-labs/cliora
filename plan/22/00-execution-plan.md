# 00 — 執行總控（V2.5 需求釐清與任務拆解）

Ticket 前綴 `RQ-`。上游規劃：[`research/02/07-phase-v25-requirements-and-decomposition.md`](../../research/02/07-phase-v25-requirements-and-decomposition.md)。

> **本期是「Agent 的話怎麼變成平台的事實」這個問題的落地階段。**
> 而「不會變成事實」的驗收方式是**「那個欄位只有帶人類 actor 的路徑寫得到」**，
> 不是「Agent 被擋住」——對 `requirements.approved_by`、`task_proposals.decided_by`、
> `document_patch_proposals.decided_by` 各斷言一次（`09-…md` §3）。

## 0. 待裁決項目

**這一節是開工前唯一要讀的東西。** 每一項都寫了「不同意的話會怎樣」。

### 0.1 A 類 — 擋開工（6 項）

---

**☐ D0 — `feature_specs` 要不要補上 Monstrare 規格書缺的那幾節**

> **計畫的答案：加一個 `sections JSONB`，預設 `{}`；既有五個欄位一個都不動。**

`../Monstrare/ai/templates/feature-spec.md` 有十二節，這張表有五個欄位。
缺的七節裡三節是承重的（README 易錯 7）：**使用者故事**（拆解的輸入）、
**畫面**（`ui` gate 的上游）、**驗證計畫**（`verification_commands` 與 AC 的來源）。

**為什麼是一個 JSONB 而不是七個 column**：那七節的形狀是**文件**，
與 `task_proposals.tree` 同一個判準（ADR 0027 的規則：與本體一起讀寫、沒有獨立查詢）。
七個 `Text` column 會讓「Monstrare 之後多一節」變成一次 migration。

**`sections` 的鍵是封閉的**（`02-…md` §1.3 列出九個），
不是自由字典——否則第二個 Agent 會用 `user_stories` 而第一個用 `userStories`，
而前端要兩個都讀。

**不同意的話（不加）**：拆解 run 拿到的規格只有 `objective`／`scope`／`non_goals`／AC，
**Epic→US→Task 的中間那一層沒有來源**。Agent 只能自己生 User Story，
而那正是 `project-kickoff` 步驟 4 要人工勾選的東西——變成 Agent 自己勾了。

**要一起接受的代價**：規格審閱畫面要多渲染九節（`07-…md` §3），
而其中「使用者故事」那一節要能逐條勾選——那是本期前端第二重的一塊。

---

**☐ D1 — 平台用什麼分辨「這是一張釐清卡」**

> **計畫的答案：新增 `tasks.card_kind`，四值 `implementation`｜`clarification`｜`decomposition`｜`mockup`，預設 `implementation`。**

三條出口條件需要伺服器端能回答這個問題，而現在它答不出來：

| 出口條件 | 需要的判定 |
|---|---|
| 7 — 釐清 run 帶機密 → dispatch 當下被拒 | 「這是釐清卡」 |
| 11 第三項 — 產出 mockup 變體的卡在整合未啟用時 dispatch 被拒 | 「這是 mockup 卡」 |
| 9 — Agent 提交提案只能提給自己這張拆解卡的需求 | 「這是拆解卡」 |

**三個 alternatives，三個都被否決**：

| 方案 | 為什麼不行 |
|---|---|
| 用 `required_labels` 裡的約定字串（`clarify`） | tag 從 V2.3 起**真的參與派工比對**（D18）。同一個欄位同時決定「給哪台機器」與「這是什麼卡」，一次改 tag 會同時改掉兩件事。而且 tag 是自由文字，**打錯字會靜默降級成一般卡**——那正是出口條件 7 要擋的東西 |
| 用 `requirement_id is not null` | RQ-07 接受提案時建立的**實作卡也帶 `requirement_id`**（`requirements.py:388`）。這個判定會把整批實作卡誤判成釐清卡 |
| 用 `delivery in (none, artifact)` | 一張正常的「寫一份調查報告」卡也是 `artifact`。而且 `delivery` 是拆解的**產出**，拿它當卡片種類會讓兩個概念互相綁死 |

**不同意的話**：三條出口條件都退化成「靠情境包裡的一句話」，
而情境包是給 Agent 讀的文字，不是 refusal。第 7 條會變成「Agent 自願不帶機密」。

**要一起接受的代價**：`tasks` 多一個欄位、`EDITABLE_FIELDS` 多一個值、
前端卡片多三種外觀。**而 `card_kind` 一旦有 run 跑過就不可改**（`02-…md` §1.2）——
否則一張釐清卡可以在 dispatch 之後變成實作卡。

---

**☐ D2 — Agent 提交規格與提案走哪條路**

> **計畫的答案：兩條 run 憑證專用的新路由，既有七條人工路由的權限一個字不改。**

```text
POST /api/cli/runs/spec        需要 task.update，寫入 feature_specs（authored_by_kind='runner'）
POST /api/cli/runs/proposal    需要 task.update，寫入 task_proposals（status 恆為 pending）
```

兩條都**額外**檢查 `principal.task_id → tasks.requirement_id`：這張卡屬於哪個需求，
就只能寫那個需求。這與 `run_router` 既有六條路由的形狀完全一致
（`agents.py:742` 的 `_own_task`）。

**不同意的話（放寬 `POST /api/requirements/{id}/proposals` 到 `task.update`）**：
`RUN_TOKEN_SCOPES` 含 `task.update`，所以**任何一枚 run 憑證都能對這個專案的任何需求提案**
——包括一個被 prompt injection 的實作 run。而那條路由的 `requirement_id` 來自 URL，
沒有任何東西把它綁回呼叫者。

**另一個不同意的方向（給 run 憑證 `task.create`）**：
`agent_auth.py:56` 的註解寫著它被排除的理由就是 D28。加回去會讓 run 憑證同時能
`POST /api/projects/{id}/tasks` ——**Agent 直接建立正式卡片，繞過整個提案機制**。

---

**☐ D3 — 「一次一個問題」在哪一層強制**

> **計畫的答案：伺服器端。`POST /api/cli/runs/messages` 當 `kind='question'` 且該 run 已有一則未被回答的 question 時，回 `409 QUESTION_ALREADY_PENDING`。**

「已被回答」的判定：該 question 之後存在一則 `author_kind='user'` 的訊息（同一張卡）。
不需要新欄位——`task_messages` 有 `created_at` 與 `author_kind`，一條 `EXISTS` 就夠。

**不同意的話（只寫進情境包 ＋ CLI 端限制）**：上游 `research/02/07` 就是這樣寫的
（「情境包明寫『一次一個』＋ CLI 端限制 `task ask` 頻率」）。
但 CLI 端的限制是 `daemon/internal/cli/` 裡的 Go 程式碼，**而 Agent 手上有 shell 與 `curl`，
`.cliora/context/run.token` 是一個它讀得到的檔案**。CLI 端的限制對「Agent 不小心」有效，
對「Agent 想快一點」無效——而後者正是這條規則要防的行為。

**要一起接受的代價**：Agent 想一次問兩個**相關**的問題會被擋。
所以拒絕訊息要給出路：「把它們寫成一個問題，或等這一題有答案」。
CLI 端也要**同時**做（`06-…md` §2），因為一個在本機就能看到的錯誤比一趟 HTTP 便宜。

---

**☐ D4 — 逾時的釐清 run 怎麼「不整批丟棄」**

> **計畫的答案：情境包要求每答完一輪就送一版 `feature_specs` 草稿；平台不在逾時當下做任何整理。**

出口條件 10 的驗收方式因此變成一條可查的斷言：**逾時之後 `feature_specs` 的列數 > 0**，
而不是「訊息串還在」（訊息串本來就永久，那不需要驗）。

**不同意的話（平台在逾時當下把對話整理成規格草稿）**：那是**平台在替 Agent 寫規格**。
它需要一個「把 Q&A 變成 objective／scope／AC」的東西，而平台裡沒有那種東西——
真要做只有一條路：再開一個 run。**一個為了保存資料而自動開的 run，
是本期最不該長出來的東西。**

**要一起接受的代價**：如果 Agent 一版草稿都沒送就逾時，**就是什麼都沒有**。
所以情境包把「每輪送一版」寫在**第一段**（與 `render_run_context` 把「怎麼回報」放第一段同一個理由），
而出口條件 10 用「列數 > 0」把它變成可驗的。

---

**☐ D5 — RQ-11（UI Mockup 關卡）本期做到哪裡**

> **計畫的答案：切成兩半。RQ-11a（整合未啟用時的正確性）**必做**；RQ-11b（啟用時的預覽）**本期不做**。**

| | RQ-11a（本期做） | RQ-11b（本期不做） |
|---|---|---|
| 內容 | `ui` gate 停用原因在 Project Settings 可見；`card_kind='mockup'` 的卡在整合未啟用時 dispatch 被拒並說明；一般 UI 卡照常 | 從 `artifacts/preview/` 開 tunnel、保護策略詢問流程、六件要設計的事 |
| 出口條件 | **11（四子項全驗）** | 12（本期不驗，隨 RQ-11b） |
| 新的對外面 | **零** | **有**——本期唯一的 |
| 現況 | 三分之一已實作（`process.py:189-191`） | 零 |

**為什麼不整包延後**：出口條件 11 的四個子項裡，第一項已經做完了，
第三、第四項各是一個 `if`。**延後它們等於留下一個「做了三分之一、沒人驗」的關卡**，
而那種東西下一期會被當成已完成。

**為什麼不整包做**：RQ-11b 是本期唯一會新增對外面的東西，
而它**換不到本期的目標**——一句模糊需求走到卡片，全程不需要 mockup。
做它會讓本期從「零新對外副作用」變成「有一個」，而安全審查的節數會從一節變成兩節。

**不同意的話（要做 RQ-11b）**：`08-…md` §3 已經寫完了完整設計，
照它做即可；但**要同時把 `09-…md` §6 的安全審查加第二節**，
並把出口條件從 24 條變成 28 條。

---

### 0.2 B 類 — 確認即可（4 項）

| ☐ | 項目 | 內容 | 不同意的話 |
|---|---|---|---|
| ☐ | **contract 不動** | 本期沒有任何 schema 變更，`v1.13.0` 原封不動 | 想在 `run.offer` 加一個 `requirement` 區塊 → `strictUnmarshal` 是 `DisallowUnknownFields` 且遞迴適用到 `spec`，**未升級的 node 會靜默丟掉整個 offer**（V2.4 README 易錯 1）。需求資料走 `spec.context` 的字串，那是既有欄位 |
| ☐ | **agentd 進 0.12.0** | 三個新 CLI 子命令，wire 零變更 | 若堅持 0.11.0 不變，就沒有 `cliora spec submit`——Agent 只能用 `curl`，而那需要它自己組 JSON 與讀 token 檔，**離線行為與錯誤訊息全部沒有**（`06-…md` §3） |
| ☐ | **不新增 RBAC 動作** | 27 個維持不變；新路由用既有的 `task.update`／`task.approve` | 新增 `spec.submit` 之類的動作 → `test_every_action_is_enforced_somewhere` 兩個方向都要顧，而它換到的邊界，`principal.task_id` 已經給了 |
| ☐ | **FR-SPEC-001 標為 V2.1 已交付** | 上游 `research/02/11` 列 FR-SPEC-001…008，但 -001（資料模型與人工表單）在 V2.1 是以 **FR-TASK-005** 交付的 | 重新編一組 FR-SPEC-001 → traceability 會有兩個 ID 指向同一批 AC，覆蓋率報表開始重複計算 |

### 0.3 C 類 — 開工時決定，計畫已給預設值（6 項）

| ☐ | 項目 | **計畫的預設** | 什麼情況要改 |
|---|---|---|---|
| ☐ | 釐清情境包的預算 | **6 KB**（分層，超出時依固定順序截斷） | **M-RQ-1** 量出第三輪之後仍超過 |
| ☐ | 一次拆解的提案卡上限 | **40 張**，超過在提交時拒絕 | M-RQ-3 量出真實需求常態超過 |
| ☐ | 一個需求的規格版本上限 | **20 版**，超過在提交時拒絕 | 釐清輪次的中位數（M-RQ-2）接近它 |
| ☐ | 釐清 run 允許的 `source` | **`repo` 與 `none` 兩者皆可**，預設 `repo` | 若組織不希望釐清 run 讀程式碼，改成只允許 `none` |
| ☐ | PRD patch 的 diff 大小上限 | **256 KiB** | 實際的 PRD patch 超過 |
| ☐ | 接受提案時是否自動建立「套用 patch」的卡 | **不自動**，接受畫面給一個帶入欄位的按鈕 | `05-…md` §4 有完整理由 |
| ☐ | 要不要補一個 `security` review gate | **本期不補。** `process_definitions` 的六個 gate 沒有它，而 Monstrare `review-gates.md` 有——但補它會改動每個專案的共用詞彙與 `process_definitions.version`，那比 V2.5 大。代償：命中停止條件第四條的提案卡強制 `risk: high` ＋ 問題留在 `open_questions` ＋ 接受介面顯示高風險徽章 | 組織真的要在平台上跑高風險工作的安全審查關卡時。追蹤項在 `10-…md` §4 |

## 1. 成功定義

**要交付的：** 一個人在 Traqora 的 Requirements 分頁丟一句
「使用者反映報表匯出很慢，想辦法改善」，按「派給 Agent 釐清」；
平台建立一張 `card_kind: clarification`、`source: repo`、`delivery: artifact` 的卡並 dispatch；
runner 領走，在隔離目錄裡讀 repo，**在卡片訊息串上一次問一個問題**
（「慢是指哪一種匯出？」→ 等回答 → 「可接受的秒數是多少？」→ 等回答）；
每答完一輪 Agent 用 `cliora spec submit` 送一版 `feature_specs`；
第三輪之後 `open_questions` 清空，卡片訊息串上是一段完整的對話；
人在規格審閱畫面按**核准**（按鈕在 `open_questions` 清空前是停用的，
而且會列出是哪幾個問題）；
接著派一張 `card_kind: decomposition` 的卡，Agent 用 `cliora proposal submit`
送出一棵 Epic→US→Task 的樹，**每張 Task 自帶 DoR 七項與 `source`／`delivery`**；
人在提案樹上勾三張、就地把其中一張的 `delivery` 從 `pull_request` 改成 `artifact`、拒絕其餘的並寫理由；
**建立出來的三張卡在詳情頁顯示「來自需求 REQ-7 的提案 #1」**。

**同一天要驗的反面：**
規格還有一個未解決的 `open_questions` 時，`POST /requirements/{id}/approve` **回 409 並列出問題**
（不是按鈕停用而已）；
未核准的需求送 `POST /api/cli/runs/proposal` **被拒**；
釐清卡宣告 `required_secrets: ["DB_PASSWORD"]` **在 dispatch 當下被拒**；
Agent 用 run 憑證打 `POST /requirements/{id}/approve` **401**（那條路由不接受 agent principal）；
Agent 在上一個問題還沒有答案時再問一個 **409**；
拆解卡的 run 對**另一個**需求提案 **404**；
整個流程跑完，**Traqora 的遠端零變更**（`git ls-remote` 前後逐位元組相同）。

**其餘一律不做。** MCP 外殼、需求優先權排序、工時估算、Sprint 規劃、
自動核准、全自動鏈（需求→拆解→執行不經人）——`research/02/00` §9 的不做清單原封不動。

**不得弄壞的十二件事：**

1. **兩個旗標都關閉時，系統與 V2.4 逐位元組一致。** 本期新增端點全數 404。
2. **互動式 Session 的行為一個位元組都不變。** `daemon/internal/runtime/` 對 `RQ-00` 基線零 diff。
3. **contract 零變更。** `contracts/` 對基線逐位元組相同——**這是本期唯一一個「整個目錄不准動」的禁區**。
4. **既有七條人工路由的權限一個字不改。** `requirements.py` 的 `require_action(...)` 參數對基線零 diff。
5. **`RUN_TOKEN_SCOPES` 仍然是 `{project.view, task.update}`。** 一條測試斷言它的內容，
   而**不是**斷言「它不含 task.approve」——後者在有人加第三個動作時仍然會過。
6. **27 個 RBAC 動作的角色歸屬不變，且不新增第 28 個。**
7. **`requirements.approved_by`／`task_proposals.decided_by`／`document_patch_proposals.decided_by`
   永遠是人。** 三個欄位各一條測試：agent principal 走遍所有可達路由，三個欄位都寫不到。
8. **`feature_specs` 與 `task_proposals` 仍然只 INSERT。** 沿用 `GATE-DV-APPEND-ONLY` 的形狀。
9. **一次拆解不會建立任何卡片。** `POST /api/cli/runs/proposal` 的路徑上不得出現
   `TaskService.create_task`——一條 gate。
10. **釐清與拆解 run 產生零個遠端副作用。** 用遠端狀態驗，不用 log 驗。
11. **卡片產物與 run log 的兩種保留期不變。**
12. **`ui` gate 的自動停用邏輯不被改成「Admin 可以手動開」。** `process.py:189-191` 是禁區。

## 2. 十三張 ticket

| # | Ticket | 交付物 | 落在哪份文件 |
|---|---|---|---|
| `RQ-00` | 基線擷取 | `scripts/rq/capture-baseline.sh`（`scripts/ar/` 的 `BASELINE_OUT` 覆寫） | `01` §1 |
| `RQ-01` | ADR 0034 ＋ PRD §8.16 ＋ traceability ＋ 三則增補 | `docs/adr/0034-…md`、`research/prd.md`、`traceability/requirements.json` | `01` §2–§4 |
| `RQ-02` | 資料層 | migration `0039`：`tasks.card_kind`、**`feature_specs.sections`**、`feature_specs.run_id`、`task_proposals.run_id`、`document_patch_proposals`、`tasks.links.proposal_item_id` 索引 | `02` |
| `RQ-03` | 卡片種類與 dispatch 的四道新拒絕 | `services/runs.py::dispatch` 第 ②' 段、四個新 error code | `03` §1 |
| `RQ-04` | 釐清情境包與「一次一個問題」 | `render_clarification_context()`、`messages` 路由的閘門 | `03` §2–§3 |
| `RQ-05` | 規格提交路由 | `POST /api/cli/runs/spec` | `03` §4 |
| `RQ-06` | 拆解 run 與提案提交路由 | `POST /api/cli/runs/proposal` ＋ DoR 與顆粒度檢查 | `04` §1–§3 |
| `RQ-07` | 三個人工關卡的收口 | 提案拒絕帶理由、部分接受的剩餘可見、來源可追溯的寫入 | `04` §4 |
| `RQ-08` | PRD Patch 提案 | `document_patch_proposals` 的服務與四條路由 | `05` |
| `RQ-09` | CLI（agentd 0.12.0） | `cliora spec submit`／`proposal submit`／`requirement show` | `06` |
| `RQ-10` | 前端 | Requirements 分頁、規格審閱與版本比較、提案樹、來源徽章 | `07` |
| `RQ-11a` | UI Mockup 關卡：未啟用時的正確性 | dispatch 拒絕 ＋ Project Settings 文案 | `08` §1–§2 |
| `RQ-12` | 驗證與出口 | `scripts/rq/gates.sh`、24 條出口條件、安全審查、release note | `09` |

（`RQ-11b` 存在於 `08` §3 但**不在本期的 ticket 清單裡**——D5。）

## 3. 開工順序與相依

```text
RQ-00 基線 ──▶ 閘門一（基線未完成不得動程式碼）
                │
                ▼
RQ-01 ADR 0034 ──▶ 閘門二（ADR 未被人接受，RQ-02 起不得動 backend/frontend/daemon）
                │
                ▼
RQ-02 資料層 ─┬─▶ RQ-03 dispatch 拒絕 ─┬─▶ RQ-04 情境包與提問閘門
              │                        │
              │                        └─▶ RQ-11a（讀 card_kind）
              │
              ├─▶ RQ-05 規格提交 ──┐
              │                    ├─▶ RQ-09 CLI ──▶ RQ-12 E2E
              ├─▶ RQ-06 提案提交 ──┘
              │
              ├─▶ RQ-07 人工關卡收口 ──▶ RQ-10 前端
              │
              └─▶ RQ-08 PRD Patch ──────▶ RQ-10 前端
```

**兩個閘門與 V2.4 完全相同**，理由也相同：基線是「只有新增」的唯一參照物；
一份自己標成 accepted 的 ADR 會讓第二道閘門失去意義。

**可以並行的三組**：
`RQ-05`＋`RQ-06`（兩條路由互不相干）、
`RQ-08`（PRD Patch 只碰新表）、
`RQ-11a`（只讀 `card_kind`，不寫任何東西）。

**不可並行**：`RQ-10` 前端要等 `RQ-07`，因為提案樹的介面依賴「部分接受的剩餘怎麼呈現」
這個伺服器端決定——而那個決定 V2.1 只做了一半（狀態改成 `partially_accepted`，
但沒有任何地方說「還剩哪幾張」）。

## 4. 這一期明確不做

沿用 `research/02/07`「這一階段明確不做」，一字不改，並補三條本計畫發現的：

- 不做自動核准（任何一個關卡都不行）。
- 不做「Agent 自動把需求丟進佇列自己拆自己做」的全自動鏈。
- 不做需求的優先權排序、工時估算、Sprint 規劃。
- 不套用 PRD patch（只渲染與記錄決定）。
- 不新增訊息管道（釐清走既有的看板訊息串）。
- 不要求一次產生完整 Roadmap。
- 🆕 **不做 `requirements.epic_id`。** 上游 `research/02/07` 列了它（「核准後歸屬到哪個 Epic」），
  但接受提案時建立的 Epic 是**提案樹的一部分**，而樹是 JSONB。
  一個指回 `epics` 的外鍵需要「接受之後回頭 UPDATE 需求」，而 `requirements` 沒有那條路徑。
  **要看一個需求產出了什麼，走 `tasks.requirement_id` 的反查就夠了。**
- 🆕 **不做規格的 diff 渲染。** 版本比較是「並排顯示第 N 版與第 N-1 版的五個欄位」，
  不是字元級 diff。字元級 diff 需要一個 diff 元件，而那是 `plan/14` 被撤銷的東西的近親。
- 🆕 **不做 `card_kind` 之間的轉換。** 一張釐清卡不會變成實作卡；要實作就從提案建立新卡。
