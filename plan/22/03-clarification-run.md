# 03 — 釐清 run（`RQ-03`／`RQ-04`／`RQ-05`）

三張 ticket，一條路徑：**卡片被拒絕得夠早 → Agent 拿到夠小的情境 → 它一次只能問一個問題 → 每輪送一版規格。**

## 1. `RQ-03` — 卡片種類與 dispatch 的四道新拒絕

### 1.1 放在哪一段

`services/runs.py::dispatch` 的檢查順序是固定的，而且**是為了拒絕訊息的可讀性固定的**
（`runs.py:307-314` 的 docstring）。四道新拒絕全部插在 **② 的最前面**
（「這張卡的宣告要能被滿足」），在既有的 `required_secrets` 檢查之前。

**為什麼在機密檢查之前**：一張釐清卡宣告了機密時，
「釐清 run 不得帶機密」比「那個名稱不在專案 allowlist 上」更接近真正的錯誤。
先報後者會讓人跑去 Project Settings 把名稱加進 allowlist，然後再被拒一次。

### 1.2 四道拒絕

```python
KIND_NO_SECRETS = {"clarification", "decomposition"}
KIND_DELIVERIES = {
    "clarification": {"none", "artifact"},
    "decomposition": {"none", "artifact"},
    "mockup":        {"none", "artifact"},
}
```

| # | 條件 | error code | 訊息要說什麼 |
|---|---|---|---|
| 1 | `card_kind ∈ KIND_NO_SECRETS` 且 `required_secrets` 非空 | `TASK_KIND_FORBIDS_SECRETS` | 「釐清與拆解不需要機密」＋列出宣告了哪幾個＋**改法是清空那個欄位，不是加進 allowlist** |
| 2 | `card_kind ∈ KIND_DELIVERIES` 且 `delivery` 不在對應集合 | `TASK_KIND_DELIVERY_NOT_ALLOWED` | 「這種卡只能交付 `none` 或 `artifact`」＋目前宣告的值 |
| 3 | `card_kind ∈ {clarification, decomposition}` 且 `requirement_id IS NULL` | `TASK_KIND_NEEDS_REQUIREMENT` | 「這張卡沒有連到任何需求，Agent 不知道要釐清什麼」＋指向 Requirements 分頁 |
| 4 | `card_kind = 'mockup'` 且 tunnel 整合未啟用 | `TASK_MOCKUP_INTEGRATION_DISABLED` | 「這個部署沒有啟用 tunnel 整合，所以平台無法提供 mockup 預覽」＋**明說一般 UI 實作卡不受影響**＋指向整合設定 |

再加一道**在拆解卡上**的前置檢查，它不是 dispatch 的第五道而是第三道的延伸：

| 3b | `card_kind = 'decomposition'` 且該需求 `status ≠ 'approved'` | `REQUIREMENT_NOT_APPROVED` | 重用既有 code（`requirements.py:280`）。**在 dispatch 就拒**，而不是等 run 跑完才在提交提案時拒——一整個 run 的成本 |

### 1.3 第四道為什麼不是「照常執行但關掉關卡」

D31 明寫要分兩種卡：**產出 mockup 變體是交付物的卡 → dispatch 當下拒絕；
一般 UI 實作卡 → 照常執行，只解除 `links.mockupDecision` 的要求。**

`card_kind` 讓這兩者變成兩個值：`mockup` 與 `implementation`。
**沒有 `card_kind` 的話這一條做不出來**——這是 D1 第三個、也是最難用其他方式取代的理由。

「一般 UI 卡照常執行」在程式碼上是**什麼都不做**：
`gates.ui` 已經被 `process.effective()` 停用（`process.py:189-191`），
而 gate 停用時 Done Gate 不會要求它。**這一條是出口條件 11 第四項，
而它的驗收方式是「跑一張 UI 實作卡，它進得了 `done`」**——不是讀程式碼。

## 2. `RQ-04` — 釐清情境包

### 2.1 一個新函式，不改既有那個

```python
def render_clarification_context(
    task: Task, requirement: Requirement, latest: FeatureSpec | None,
    readiness_keys: list[str], repo_hint: str | None,
) -> str: ...
```

`render_run_context()`（`runs.py:1297`）一個字不改。
**兩個函式而不是一個帶旗標的**，理由與 `run_router` 是獨立 router 同一條：
一個帶 `if kind == ...` 的渲染函式，第一個忘記加分支的人就會把機密提示送進釐清情境包
——而釐清 run 沒有機密，那段文字會是一個謊。

`poll()`（`runs.py:751`）依 `task.card_kind` 選函式，
**選擇在一個地方**，而 `GATE-RQ-CONTEXT-DISPATCH` 斷言那裡只有一個 `match`。

### 2.2 內容：十一段，順序是刻意的

沿用 `render_run_context` 的決定——**第一段是怎麼回報**，
因為最可能出錯的不是 Agent 誤解任務，是它從不說話。
本期在那之上多一條：**第二段是「每輪送一版草稿」**，
因為本期最可能出錯的是它問了五輪、一版都沒送（D4）。

```text
1  # REQ-7 釐清：<需求標題>
2  你正在把一句模糊的需求問成一份規格。沒有人在終端前面。
3
4  ## 你必須做的兩件事
5    cliora task ask "..."      一次一個問題，問完就等
6    cliora spec submit x.json  **每得到一個答案就送一版**，未解決的留在 open_questions
7    ← 沒有第二件事的話，24 小時後這次釐清會整批消失
8
9  ## 原始需求（原文照錄）
10 ## 目前的規格草稿（第 N 版）與它的未解決問題      ← 第二輪起才有
11 ## 這個專案已知的非目標                          ← 從 project + 既有需求彙整
12 ## 規格書要有哪幾節（九節，見 sections）
13 ## 你不知道就不要填：五條停止條件
14 ## 提問的規約：一次一個
15 ## 情境指路：conventions 與 architecture 的路徑（不是內容）
16 ## 這次執行的邊界：不改 repo、不推分支、沒有機密
```

三段值得單獨說：

**第 12 段（九節）**直接來自 `../Monstrare/ai/templates/feature-spec.md`，
但**只給節名與一句話說明，不貼範本全文**——範本 2.5 KB，
貼進去會一個人吃掉半個預算（§2.3）。CLI 端提供 `cliora spec template` 印出完整範本
（`06-…md` §2.4），**要用的時候在本機取，不佔情境**。

**第 13 段（五條停止條件）**逐字內化 `../Monstrare/ai/process/context-protocol.md`
的「停止條件」，MIT，ADR 標註出處。五條原文：

```text
- 搜尋發現多種可能的實作方式、各有不同取捨。
- 需求跟既有架構衝突。
- 缺少必要檔案。
- 任務涉及密鑰、身分驗證、金流、遷移或基礎設施。
- 預估範圍超出已核准的任務卡。
```

後面接一句本計畫加的：**「遇到任一條，把它寫進 `open_questions`，
不要自己選一個然後在規格裡寫得像已經決定了。」**
——因為 `open_questions` 是核准閘門的輸入，而「自己填答案」是它唯一的繞法。

**第 15 段（情境指路）給路徑不給內容**，這是 `context-protocol.md`
「摘要或符號搜尋就夠用時，不要把大檔案整份貼進情境」的直譯。
Agent 有 repo（`source: repo`），它自己讀得到。

### 2.3 預算：6 KB，分層，截斷順序固定

wire 上的上限是 32768（`run-spec.schema.json` 的 `context`），
而既有的實作測到 1–2 KB。**釐清情境包會比它大，而大多少取決於輪數**——
第 10 段（既有草稿與未解決問題）會隨輪次成長。

| 層 | 預算 | 超出時 |
|---|---|---|
| 1–8 段（固定文字 ＋ 原始需求） | 2.0 KB | **原始需求超過 1.5 KB 時截斷並註明「完整內容在卡片上」** |
| 第 10 段（草稿 ＋ 未解決問題） | 2.5 KB | **只送最新一版**；仍超出時只送 `open_questions` ＋ 各節的節名與字數 |
| 第 11 段（已知非目標） | 0.5 KB | 取最近 5 條 |
| 12–16 段（規約與邊界） | 1.0 KB | **不截斷**——它們是規則，截一半的規則比沒有規則糟 |
| 合計硬上限 | **6 KB** | 超過就是實作有 bug，記一筆 `activity_events` 並照上表截 |

**「不截斷」的那一層要放在最後渲染並且先算長度**，
否則截斷順序在程式碼上會變成「誰先寫誰活下來」。

這個上限是 **M-RQ-1** 的量測對象（`10-…md` §1）。

### 2.4 拆解情境包：同一個函式的第二種

`render_decomposition_context()`，八段，
差別是它拿到的是**一份已核准的規格**而不是一句話：

```text
1  # REQ-7 拆解：<需求標題>
2  你要把一份已核准的規格拆成一棵 Epic → User Story → Task 的樹。
3  ## 這棵樹不會直接變成卡片。人會逐張勾選，缺 DoR 的會落 backlog。
4  ## 已核准的規格（九節全文，或截斷後的節）
5  ## 每張 Task 必須帶的 DoR 七項          ← **從 process.effective() 讀，不寫死**
6  ## 拆分規則四條                          ← Monstrare implementation-plan.md
7  ## 卡片大小五種                          ← Monstrare workflow.md Phase 5
8  ## 每張 Task 還要帶的執行設定：source / delivery / target_branch /
      required_labels / dependsOn；required_secrets 一律留空由人補
```

**第 5 段從 `process.effective(project=…)` 讀**，不是常數。
理由是 V2.4 給了專案停用 readiness 項目的能力（`process.py:225`），
而一個硬寫七項的情境包會讓 Agent 填一個這個專案已經關掉的欄位——
它填的值會被 `accept()` 忽略，看起來像 Agent 亂填。
**目前的七個鍵**（migration `0026`）：

```text
problem_stated / acceptance_criteria / scope_bounded / dependencies_known
verification_defined / risk_assessed / context_pointers
```

⚠️ **這七個鍵與 `research/02/07` RQ-04 寫的「DoR 七項」文字不一樣**
（上游寫的是「目標明確具體／行為清楚／範圍有界／相關檔案或搜尋入口／
驗收標準可測試／非目標明確／風險等級／驗證方法」，數起來是八條）。
**以 `process_definitions` 為準**——那是唯一會被 `accept()` 讀的東西。
回寫進 `01-…md` §4.3。

**第 6 段的四條**逐條來自 `../Monstrare/ai/skills/implementation-plan.md`：

| 規則 | 內容 |
|---|---|
| 全端三分法 | 一個 User Story 同時碰前後端時，**預設拆成前端／後端／串接三張卡**，不是一張大卡 |
| Epic 架構優先 | 同 Epic 底下多個 US 共用畫面框架、路由保護或資料模型時，先拆一張「{Epic} 架構基礎」卡，其餘卡 `dependsOn` 它 |
| MECE — 完全窮盡 | 所有卡合起來要覆蓋規格的完整驗收標準；規格提到卻沒有卡負責的，是缺口 |
| MECE — 相互排斥 | 兩張卡不得都要改同一支 API 或同一個元件的核心邏輯 |

**第 7 段的五種**來自 `workflow.md` Phase 5：
一個畫面狀態／一個 API endpoint／一個元件行為／一個 bug 的重現與修復／一個測試缺口。

**不內化 `project-kickoff` 的 Epic 0「專案設置」規則。**
它假設一個全新專案，而平台上的需求是往一個**已經存在的專案**丟的。
寫進 ADR 0034 的 Alternatives rejected，因為它是三個 skill 裡唯一被整段跳過的。

## 3. `RQ-04` — 一次一個問題（D3）

### 3.1 兩層，而只有下面那層是閘門

| 層 | 位置 | 效果 |
|---|---|---|
| 情境包第 14 段 | 文字 | Agent 讀了會照做——**大多數時候** |
| CLI 端 | `daemon/internal/cli/` | 本機就報錯，省一趟 HTTP（`06-…md` §2.2） |
| **伺服器端** | `POST /api/cli/runs/messages` | **這一層才是閘門** |

Agent 手上有 shell、有 `curl`、`.cliora/context/run.token` 是它讀得到的檔案。
CLI 端的限制對「不小心」有效，對「想快一點」無效。

### 3.2 判定

```sql
-- 這個 run 有沒有一則還沒被回答的問題
SELECT EXISTS (
  SELECT 1 FROM task_messages q
  WHERE q.run_id = :run_id AND q.kind = 'question'
    AND NOT EXISTS (
      SELECT 1 FROM task_messages a
      WHERE a.task_id = q.task_id
        AND a.author_kind = 'user'
        AND a.created_at > q.created_at
    )
);
```

命中 → `409 QUESTION_ALREADY_PENDING`，`details` 帶那則問題的內文與時間。

**三個判定上的選擇，各有理由：**

| 選擇 | 為什麼 |
|---|---|
| 回答的 scope 是 `task_id` 不是 `run_id` | 使用者在卡片上留言時**不知道也不該知道**現在是第幾個 run。一則回覆是回給這張卡的 |
| 「回答」＝任何 `author_kind='user'` 的訊息，不要求它是 `kind='answer'` | 使用者會直接留言而不是按「回答」。要求特定 kind 會讓 Agent 永遠等一個永遠不來的東西 |
| 不看 `author_kind='system'` | 24h 逾時的系統訊息不算回答，否則逾時反而解鎖了提問 |

### 3.3 拒絕訊息要給出路

```text
409 QUESTION_ALREADY_PENDING
上一個問題還沒有答案：「報表匯出是指 CSV 還是 PDF？」（3 分鐘前）
要問新的：把兩個問題合併成一個，或等這一題有回覆。
```

**「合併成一個」是真的可行的建議**，不是安慰——
`task ask` 的 body 是自由文字，一則訊息裡寫兩個相關的子問題是允許的。
D3 擋的是**五個各自獨立的問題一次丟出**，那時使用者會回答三個。

### 3.4 這道閘門對實作 run 也生效

它加在 `POST /api/cli/runs/messages` 上，而那條路由服務所有 run。
**這是刻意的**：一個實作 run 一次丟五個問題，問題與釐清 run 完全相同。

**要一起接受的代價**：V2.2 起就存在的實作 run 行為變了。
所以它要進 release note 的「行為變更」段，而不只是「新增」段。

## 4. `RQ-05` — 規格提交路由

### 4.1 形狀

```text
POST /api/cli/runs/spec
  scope: task.update（run 憑證有）
  body:  { objective?, scope?, non_goals?, acceptance_criteria?,
           open_questions?, sections? }
  → 201 FeatureSpecDTO
```

**它是 `run_router` 的第七條路由**，與既有六條同構：
`_run_task()` 取得這張卡並確認 `principal.task_id` 相符，
然後**多一道本期特有的**：

```python
if task.card_kind != "clarification":
    raise ApiError("TASK_KIND_MISMATCH", ..., 409)
if task.requirement_id is None:
    raise ApiError("TASK_KIND_NEEDS_REQUIREMENT", ..., 409)
requirement = await service.require(task.requirement_id)
```

寫入時 `authored_by_kind='runner'`、`authored_by=None`、`run_id=principal.run_id`。

**`authored_by=None` 是重點。** 它是 `users.id` 的外鍵；
一個 run 沒有 user，而 `AgentPrincipal` **刻意不帶 `user_id`**
（`agent_auth.py` 模組註解：帶了就會開始冒充派工的人）。
`authored_by_kind` 這個欄位存在的理由就是讓 `NULL` 不必表示「系統」。

### 4.2 它重用 `RequirementService.add_spec()`，一個字不改

`add_spec` 已經有 `authored_by_kind` 參數（`requirements.py:184`），
已經有「需求已核准就拒絕新版本」（`:191`），
已經會依 `open_questions` 把 `requirement.status` 設成 `specified` 或 `clarifying`（`:218`）。

**V2.1 把這條路鋪好了，本期只是接上去。**
唯一要加的是 `sections` 的傳遞與白名單驗證（`02-…md` §1.3）。

### 4.3 三道 Agent 特有的拒絕

| # | 條件 | code | 為什麼 |
|---|---|---|---|
| 1 | `sections` 有未知的頂層鍵 | `SPEC_SECTION_UNKNOWN` | §1.3 的封閉鍵 |
| 2 | 這個需求的 `feature_specs` 已達 20 版 | `SPEC_VERSION_LIMIT` | C 類預設值。一個迴圈裡的 Agent 每秒送一版，沒有上限就是一張無限增長的表 |
| 3 | `open_questions` 裡某一條**同時**有 `answer` 與 `resolved_as` | `SPEC_QUESTION_AMBIGUOUS` | `_open_questions()` 兩個都認（`requirements.py:74`）。兩個都填看起來像「已解決」，但**它掩蓋了「答案是什麼」與「我們決定不解決」的差別**——那是核准者要看的差別 |

第 3 道是讀 `_open_questions()` 的實作才發現的：它用 `or`，
所以填任一個都算解決。**這不是 bug**（人工流程下兩個都填是不會發生的），
但 Agent 會——它會為了讓核准按鈕亮起來而兩個都填。

### 4.4 Agent **不能**做的三件事，各一條測試

```text
POST /api/requirements/{id}/approve   run 憑證 → 401（那條路由不接受 agent principal）
POST /api/proposals/{id}/accept       run 憑證 → 401
PATCH /api/cli/runs/…  想寫 approved_by → 沒有這個欄位可寫
```

前兩條的 401 不是本期寫的 `if`，是 `get_current_user` 對
`cliora_rt_` 前綴的無條件拒絕（`agent_auth.py:36-40` 的三個理由之一）。
**測試要斷言的是 401 而不是 403**，因為 403 意味著「認出你了但不准」，
而正確的行為是「這條路根本不認識你這種憑證」。

## 5. `RQ-05` — 24h 逾時之後（D4）

`run_reaper.py:122-168` 一個字不改。本期加的是**兩件小事**：

1. 逾時的系統訊息（`:154`）在 `card_kind='clarification'` 時多一句：
   「已送出 N 版規格草稿，最新一版在需求 REQ-7 上」——
   **N 從 `feature_specs` 數，不是從訊息串猜**。
2. 逾時事件（`run.waiting_timeout`）的 payload 多一個 `spec_count`。
   出口條件 10 用它。

**N = 0 時那句話要改成一句誠實的**：
「這次釐清沒有送出任何規格草稿，已問到的內容在卡片訊息串上。」
——不要在 N=0 的時候還說「草稿在需求上」，那會讓人去一個空的頁面找東西。

## 6. 新增的 error code（進 `docs/error-catalog.md`）

| code | HTTP | 誰回 |
|---|---|---|
| `TASK_KIND_FORBIDS_SECRETS` | 409 | dispatch |
| `TASK_KIND_DELIVERY_NOT_ALLOWED` | 409 | dispatch |
| `TASK_KIND_NEEDS_REQUIREMENT` | 409 | dispatch ＋ 兩條新路由 |
| `TASK_MOCKUP_INTEGRATION_DISABLED` | 409 | dispatch |
| `TASK_KIND_LOCKED` | 409 | `PATCH /api/tasks/{id}` |
| `TASK_KIND_MISMATCH` | 409 | 兩條新路由 |
| `QUESTION_ALREADY_PENDING` | 409 | `POST /api/cli/runs/messages` |
| `SPEC_SECTION_UNKNOWN` | 422 | 兩條規格路由 |
| `SPEC_VERSION_LIMIT` | 409 | 兩條規格路由 |
| `SPEC_QUESTION_AMBIGUOUS` | 422 | 兩條規格路由 |

（`04-…md` 與 `05-…md` 各自再加三個與兩個。）
