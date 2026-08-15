# 04 — 拆解與提案（`RQ-06`／`RQ-07`）

## 1. `RQ-06` — 提案提交路由

### 1.1 形狀

```text
POST /api/cli/runs/proposal
  scope: task.update（run 憑證有）
  body:  { tree: {...} }
  → 201 TaskProposalDTO
```

`run_router` 的**第八條**路由。守衛三道，前兩道與規格提交同構：

```python
task = await _run_task(session, principal)          # principal.task_id 相符
if task.card_kind != "decomposition":  → 409 TASK_KIND_MISMATCH
if task.requirement_id is None:        → 409 TASK_KIND_NEEDS_REQUIREMENT
requirement = await service.require(task.requirement_id)
# 第三道由 RequirementService.propose() 既有的檢查提供：
#   requirement.status != APPROVED → 409 REQUIREMENT_NOT_APPROVED
```

第三道**已經存在**（`requirements.py:279-284`），不重寫。
但它在 dispatch 就先擋過一次（`03-…md` §1.2 的 3b）——**兩道都要**：
dispatch 那道省一整個 run，這一道守「dispatch 之後有人把需求退回未核准」。

寫入時 `run_id=principal.run_id`、`status='pending'`、`spec_id` 由
`propose()` 既有的邏輯填成最新一版。

### 1.2 為什麼不是放寬 `POST /api/requirements/{id}/proposals`（D2 全文）

那條路由要 `task.create`。三條路，兩條被否決：

| 路 | 結果 |
|---|---|
| **給 run 憑證 `task.create`** | `RUN_TOKEN_SCOPES` 加一個動作，而那個動作同時開啟 `POST /api/projects/{id}/tasks`——**Agent 可以直接建立正式卡片**。這正是 D28 §2 要防的整件事 |
| **把那條路由降到 `task.update`** | run 憑證就過得了。但那條路由的 `requirement_id` 來自 **URL**，沒有任何東西把它綁回呼叫者——**任何一枚 run 憑證可以對這個專案的任何需求提案**，包括一個被 prompt injection 的實作 run |
| **開一條新路由**（採用） | 資源邊界是 `principal.task_id → tasks.requirement_id`，**由憑證決定而不是由 URL 決定**。與 `run_router` 既有六條完全同構 |

**這條論證要進 ADR 0034 §2**，因為它是本期唯一一次「看起來像是可以重用既有路由、
而重用會開一個洞」的地方，而下一個人會很自然地想重用。

### 1.3 `GATE-RQ-NO-CARD-FROM-RUN`

一條 gate 斷言：`POST /api/cli/runs/proposal` 的呼叫圖上不出現
`TaskService.create_task`。

**為什麼需要 gate 而不是測試**：一個「不小心也建立了卡片」的實作**會通過所有測試**
——提案存在、卡片存在、兩者都對得起來。壞掉的是「人有沒有看過」，
而那件事沒有斷言得到的形狀，除非直接對程式碼斷言。

## 2. 提案樹的形狀

### 2.1 為什麼要在計畫裡把它定死

`task_proposals.tree` 是 JSONB，V2.1 沒有定義它的形狀——
`accept()` 只讀 `tree["tasks"]`（`requirements.py:335`）。
**這對人工流程夠用**（人在前端填一個表單），
**對 Agent 不夠**：Agent 要自己產生這棵樹，而沒有規格的話它會每次產生不同的形狀。

所以本期把它定死，**而且是在伺服器端驗證**，不只寫在情境包。

### 2.2 形狀

```jsonc
{
  "epics": [
    { "id": "e1", "title": "報表匯出", "description": "…" }
  ],
  "user_stories": [
    { "id": "u1", "epic_id": "e1", "title": "…", "narrative": "身為…我想要…以便…" }
  ],
  "tasks": [
    {
      "id": "t1",
      "epic_id": "e1",
      "user_story_id": "u1",
      "title": "…",
      "track": "backend",            // frontend | backend | integration | n/a
      "objective": "…",
      "scope": "…",
      "non_goals": "…",
      "description": "…",
      "risk": "medium",
      "acceptance_criteria": [{ "text": "…" }],
      "readiness": {                  // 鍵來自 process.effective()，不是寫死
        "problem_stated": true, "acceptance_criteria": true,
        "scope_bounded": true, "dependencies_known": true,
        "verification_defined": true, "risk_assessed": true,
        "context_pointers": true
      },
      "links": { "refs": ["backend/app/services/reports.py"] },
      "source": "repo",
      "delivery": "pull_request",
      "target_branch": "main",
      "required_labels": ["python"],
      "depends_on": ["t0"]            // 樹內的 id，不是卡片 id
    }
  ]
}
```

四個形狀上的決定：

| 決定 | 理由 |
|---|---|
| **三層是三個平坦陣列 ＋ 外鍵，不是巢狀** | `accept()` 已經只讀 `tree["tasks"]`。巢狀會讓「只勾一張 Task 不勾它的 Epic」在資料上變成一個要重組的問題 |
| **`depends_on` 是樹內 id** | 提案還不是卡片，沒有卡片 id。接受時再翻譯成 `task_dependencies`（§4.3） |
| **`readiness` 的鍵不寫死** | `03-…md` §2.4 的理由：專案可以停用項目 |
| **沒有 `required_secrets`** | 拆解不得決定一張卡要哪些機密。`accept()` 建立卡片時一律給 `[]`，人自己補。**這一條要在提案提交時驗**：出現這個鍵就 `422` |

### 2.3 提交時的六道驗證

| # | 條件 | code |
|---|---|---|
| 1 | `tasks` 為空 | `PROPOSAL_EMPTY` |
| 2 | `tasks` 超過 40 張（C 類預設） | `PROPOSAL_TOO_LARGE` |
| 3 | id 重複，或 `epic_id`／`user_story_id`／`depends_on` 指向不存在的 id | `PROPOSAL_TREE_INVALID`（`details` 指名哪一個） |
| 4 | `depends_on` 形成環 | `PROPOSAL_TREE_CYCLE`（訊息要**列出環的路徑**，與 `task_dependencies` 的既有做法一致，`models.py:779`） |
| 5 | 任一節點出現 `required_secrets` | `PROPOSAL_FIELD_FORBIDDEN` |
| 6 | 高風險關鍵詞命中但 `risk != 'high'` | `PROPOSAL_RISK_UNDERSTATED`（§2.4） |

**第 3、4 道在提交時驗而不是在接受時驗**，因為接受時只勾了三張的話，
第四張的環永遠不會被發現——**而它會在下一次部分接受時才炸開**。

### 2.4 停止條件第四條的強制（`02-…md` §5）

```python
HIGH_RISK_TERMS = (
    "密鑰", "金鑰", "secret", "credential", "token",
    "認證", "登入", "auth", "權限", "rbac",
    "金流", "付款", "payment", "billing",
    "遷移", "migration", "schema",
    "基礎設施", "infra", "deploy", "部署",
)
```

命中（在 `title`／`objective`／`scope` 任一）而 `risk != 'high'` → `422`。

**這個比對是刻意的粗糙，而粗糙的方向是刻意選的**：
一張「移除舊的認證說明文件」的卡會被誤標高風險（代價：多一個徽章、人取消勾選），
而漏報的代價是一張碰金流的卡以 `low` 進 `ready`。兩者不對稱。

**它不是安全機制。** 一個想繞過的 Agent 換個詞就繞過了。
它是**給誠實但粗心的 Agent 的護欄**，這一句要寫進 ADR 0034 §4，
否則安全審查會把它當成一道控制。

## 3. 顆粒度：情境包管，伺服器不管

`workflow.md` Phase 5 的五種卡片大小、`implementation-plan.md` 的全端三分法與
Epic 架構優先、MECE 兩條——**全部只在情境包裡**（`03-…md` §2.4 第 6、7 段）。

**伺服器不驗顆粒度**，只驗 40 張的上限。理由：
「這張卡是不是太大」沒有伺服器判定得了的形式，
而一個猜的判定（字數？AC 條數？）會拒絕正確的卡並放過錯誤的卡。

**收斂點是接受介面**：底部顯示「將建立 N 張卡片」，
以及**分開的一行「其中 M 張會開 PR」**（`README` §5.1 的第一條處置）。
人看到「將建立 38 張卡片、其中 22 張會開 PR」就會停下來——
而那正是不要求一次產生完整 Roadmap 的執行方式。

## 4. `RQ-07` — 三個人工關卡的收口

V2.1 交付了三個關卡的**前兩個**，而且做得相當完整。本期補的是四個缺口。

### 4.1 缺口一：被拒絕的提案沒有理由欄位

`DELETE /api/proposals/{id}`（`requirements.py:244-264`）把 `status` 設成 `rejected`、
填 `decided_by`／`decided_at`，**但沒有讀 body，所以沒有 `decision_note`**。

而 `research/02/07` RQ-05 明寫：**「被拒絕的提案要保留，附理由。
下次拆解時把它放進情境包當作負面情境——這是這條路徑上唯一會累積的學習訊號，丟掉很可惜。」**

修法（三處）：

1. `DELETE` 改成接受一個 optional body `{ note }`，或**改用 `POST /api/proposals/{id}/reject`**。
   **選後者**：一個帶 body 的 `DELETE` 在 HTTP 語意上是可以的但在客戶端很常被丟掉
   （`fetch` 的 `DELETE` 帶 body 在部分環境會被剝除），
   而理由被靜默丟掉正是這個缺口本身。舊的 `DELETE` 保留並標為 deprecated。
2. `reject` 要求 `note` 非空。**「拒絕但不說為什麼」不是一個該被允許的動作**——
   它產生的資料在三個月後與「沒有這筆」等價。
3. 拒絕寫一筆 audit（`PROPOSAL_REJECT`，新常數）與 activity。

### 4.2 缺口二：被拒絕的提案沒有進到下一次的情境包

有了 `decision_note` 之後，`render_decomposition_context()` 多一段：

```text
## 上一次拆解被拒絕的內容（不要再提一次）
- 提案 #1（2026-08-10）：理由「這批卡太細，一個 endpoint 拆成三張」
```

**只取最近 3 筆、只取 `decision_note`、不取樹的內容**——
樹會把預算吃光，而理由才是訊號。

### 4.3 缺口三：部分接受之後「還剩哪幾張」沒有人說得出來

`accept()` 把 `status` 設成 `partially_accepted`（`requirements.py:395-399`），
而剩下哪幾張要從 `tree["tasks"]` 減去 `tasks.links.proposal_item_id` 算出來
——**這段計算目前只在 `accept()` 內部存在，沒有任何讀取路徑**。

修法：`TaskProposalDTO` 多兩個計算欄位：

```python
accepted_item_ids: list[str]     # 已產出卡片的節點
remaining_item_ids: list[str]    # tree 裡還沒被接受的
```

**`remaining` 而不是 `rejected`**：部分接受剩下的東西是**還可以接受的**
（`research/02/10` §2.7 條件 5 明寫「其餘保留」），不是被拒的。
兩者在 UI 上必須長得不一樣，否則人會以為已經決定過了。

`ix_tasks_proposal_item`（`02-…md` §3）是這個查詢的索引。

### 4.4 缺口四：`depends_on` 沒有被翻譯成 `task_dependencies`

`accept()` 現在完全不看 `depends_on`（`requirements.py:358-385` 的 `fields` 沒有它）。
於是拆解出來的相依關係在接受的那一刻消失，
**而 `dependencies_known` 那個 readiness 項目仍然是 true**——
卡片說「相依已辨識」，而資料庫裡沒有相依。

修法（順序很重要）：

```text
1. 先建立這一批被勾選的所有卡片（既有邏輯）
2. 建立 item_id → task_id 的對照
3. 逐張翻譯 depends_on：
     指向這一批裡的 → 建 task_dependencies
     指向沒被勾選的 → **不建，並回報**
4. 回傳 AcceptResult 多一個 unresolved_dependencies: dict[card_ref, list[item_id]]
```

**第 3 步的第二種情況是本期最容易做錯的一格。**
直覺會想「那就把它也建起來」——不行，那張卡不存在。
另一個直覺是「那就靜默略過」——不行，卡片會宣稱相依已辨識而實際上沒有。

**正確的處置是回報，並且讓那張卡落 `backlog`**：
在 `missing` 的計算裡把 `dependencies_known` 加進去。
`AcceptResult.incomplete` 已經是這個形狀（`requirements.py:62`），
所以這是**在既有機制裡多一個 missing 值**，不是新機制。

### 4.5 三個關卡的最終形狀

| 關卡 | 進站條件 | 動作 | 誰 | 本期改了什麼 |
|---|---|---|---|---|
| 規格核准 | `open_questions` 全部有 `answer` 或 `resolved_as`（不得兩者皆有，`03-…md` §4.3） | `requirements.status → approved` | `task.approve` | 只加第三道拒絕 |
| 提案接受 | 需求已核准 | 全部／部分／編輯後建立／拒絕 | `task.approve` | §4.1、§4.3、§4.4 |
| UI 變體選定 | `card_kind='mockup'` ＋ tunnel 整合已啟用 | 決定寫進 `links.mockupDecision` | `task.approve` | **本期不做**（RQ-11b） |

**三個關卡的共同斷言**（`09-…md` §3 的 `GATE-RQ-HUMAN-ACTOR`）：
`requirements.approved_by`、`task_proposals.decided_by`、
`document_patch_proposals.decided_by` 三個欄位的**每一個寫入點**
都在一個 `require_action(TASK_APPROVE)` 的路由裡，
而那個依賴**不接受 agent principal**。

## 5. 接受時「編輯後建立」怎麼運作

`research/02/07` RQ-05 列了四種決定：全部接受／部分接受／**編輯後建立**／拒絕。
V2.1 實作了三種——編輯那一種沒有。

**本期的做法：`AcceptProposalRequest` 多一個 `overrides`。**

```jsonc
{
  "accept_ids": ["t1", "t3", "t7"],
  "overrides": {
    "t3": { "delivery": "artifact", "risk": "high", "target_branch": null }
  },
  "note": "t3 只要一份調查報告，不需要 PR"
}
```

三條規則：

1. **`overrides` 的鍵必須是 `accept_ids` 的子集。** 編輯一張沒被勾的卡沒有意義，
   而它會在下一次接受時被靜默套用——那是一個沒有人記得的決定。
2. **可覆寫的欄位是 `EDITABLE_FIELDS` 的子集，且不含 `readiness`。**
   人可以改 `delivery`、`risk`、`target_branch`、`required_labels`、`stage`；
   **不能改 `readiness`** ——那會讓「缺 DoR 落 backlog」變成一個勾一勾就消失的規則。
   要補 DoR 就在卡片建立之後改卡片，那時它是一次有 audit 的 `PATCH`。
3. **覆寫寫進 audit 的 metadata**，逐欄位。
   「這張卡跟 Agent 提的不一樣」是三個月後有人會問的問題。

**`proposal.tree` 不因覆寫而改寫**——它是 Agent 提的原文，只 INSERT 的姿態延伸到這裡。
差異只存在於「提案說什麼」與「卡片是什麼」之間，而兩邊都查得到。

## 6. 新增的 error code

| code | HTTP |
|---|---|
| `PROPOSAL_EMPTY` | 422 |
| `PROPOSAL_TOO_LARGE` | 422 |
| `PROPOSAL_TREE_INVALID` | 422 |
| `PROPOSAL_TREE_CYCLE` | 422 |
| `PROPOSAL_FIELD_FORBIDDEN` | 422 |
| `PROPOSAL_RISK_UNDERSTATED` | 422 |
| `PROPOSAL_REJECT_NEEDS_NOTE` | 422 |
| `PROPOSAL_OVERRIDE_NOT_ACCEPTED` | 422 |
