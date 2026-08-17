# 04 — `beta.1` 第一段：View 系統與讀模型

> **ticket 前綴 `PX-`。前置條件：`alpha.2` 與 `alpha.3` 出口條件通過。**
> 這一段是 `beta.1` 其餘三段（Board／Drawer／My Work）的地基：
> **它們全部只是這個讀模型的不同渲染。**

## 1. 為什麼先做讀模型

目前 Board、Roadmap、Task list、Requirement 各自有自己的查詢與 DTO，
`ProjectDetailView.vue` 有 **1515 行**在協調它們。
若先做 UI 再抽讀模型，就會做出第五個各自查詢的畫面。

一句話定義這一段的成果：

> **Board、List、My Work 與 Project Overview 對「這張卡現在怎麼樣」給出的答案，
> 由 backend 的同一個函式產生，前端只負責畫。**

## 2. 四個正交狀態面

不再用單一 `stage` 同時表達進度、阻塞、Agent 執行與人工決策。

### A. Work lifecycle — 「工作進展到哪裡？」

```text
backlog → ready → in_progress → review → done
```

**這是投影，不是新欄位。** `tasks.stage` 的六個值不動（[D49](./01-architecture-decisions.md)）：

| `tasks.stage` | 投影 `lifecycle` | 投影 `is_blocked` |
|---|---|---|
| `backlog` | `backlog` | 依 `is_blocked` 欄 |
| `blocked` | **`ready`** | **`true`**，`blocking_reason` 若無法推導則 `unknown` |
| `ready` | `ready` | 依欄位 |
| `implementing` | `in_progress` | 依欄位 |
| `verify` | `review` | 依欄位 |
| `done` | `done` | `false` |

DTO 同時帶 `legacy_stage`，讓「這張卡在舊看板長什麼樣」查得到。

### B. Readiness — 「這張卡能被執行了嗎？」

```text
draft → needs_clarification → ready
```

由既有 `tasks.readiness` JSONB ＋ Definition of Ready 檢查推導，**不新增欄位**。

### C. Execution — 「Agent 執行目前如何？」

```text
not_queued | queued | claimed | running | waiting_for_input
          | succeeded | failed | cancelled
```

直接來自 `task_runs.status`（既有值），`not_queued` 表示沒有 active run。

### D. Human decision — 「是否等待人類正式決定？」

```text
not_required | pending | approved | changes_requested
```

由 `tasks.gates`、delivery 狀態與 verification 推導。

## 3. Filter 語言

[D54](./01-architecture-decisions.md)：allowlist 結構，不做自由 DSL。

```json
{
  "and": [
    { "field": "lifecycle", "op": "in", "value": ["ready", "in_progress"] },
    { "field": "attention", "op": "eq", "value": "waiting_for_your_input" },
    { "field": "risk", "op": "neq", "value": "low" }
  ]
}
```

### 允許的欄位（15 個）

| field | 型別 | 來源 | 索引需求 |
|---|---|---|---|
| `lifecycle` | enum | 投影自 `stage` | `tasks(project_id, stage)` |
| `readiness` | enum | 投影 | — |
| `attention` | enum | 投影（[D55](./01-architecture-decisions.md)） | 物化，見 §5 |
| `execution_status` | enum | active run | `task_runs(task_id, status)` 部分索引 |
| `is_blocked` | bool | 新欄位 | `tasks(project_id, is_blocked)` |
| `blocking_reason` | enum | 新欄位 | — |
| `owner` | uuid \| `@me` \| null | `owner_user_id` | `tasks(project_id, owner_user_id)` |
| `assigned_runner` | uuid \| null | 既有 | — |
| `required_labels` | string[] | JSONB | GIN |
| `risk` | enum | 既有 | — |
| `priority` | enum | 既有 | — |
| `delivery` | enum | 既有 | — |
| `requirement` / `epic` / `user_story` | uuid | 既有 FK | 既有 |
| `card_kind` | enum | 既有 | — |
| `updated_at` / `created_at` | timestamp | 既有 | `tasks(project_id, updated_at DESC)` |

### 運算子（8 個）

`eq`、`neq`、`in`、`not_in`、`gt`、`lt`、`is_null`、`contains`（僅 `required_labels`）。

### 限制

- 巢狀深度 ≤ 3、條件總數 ≤ 20。
- 每個 (field, op) 有明確的編譯路徑；**沒有動態 SQL 字串拼接**。
- 違規回 `400 FILTER_FIELD_NOT_ALLOWED` / `FILTER_OP_NOT_ALLOWED` / `FILTER_TOO_COMPLEX`，
  **回應要指名是哪一個 field 或 op**。

## 4. View schema

```text
work_views
  id
  project_id       nullable    -- null = 跨專案的個人 view（My Work 用）
  owner_user_id    nullable    -- null = project 共用 view
  name
  layout           board | list | roadmap
  scope            personal | project
  filter_json
  group_by         nullable
  subgroup_by      nullable
  order_by_json
  visible_fields_json
  density          compact | comfortable
  show_subtasks    bool
  is_default       bool
  position         bigint
  version          int
  created_at, updated_at, created_by, updated_by
  UNIQUE (project_id, owner_user_id, name)
```

**名稱是 `work_views` 不是 `project_views`**，因為 `project_id` 可以是 null
（跨專案的個人 view），叫 `project_views` 會讓那一列自相矛盾。

`(project_id, owner_user_id, name)` 的唯一鍵形狀移植自 kintra 的 `uq_board_views_board_user_name`。

### 權限（[D53](./01-architecture-decisions.md)，不新增 RBAC 動作）

| 操作 | 需要 |
|---|---|
| 讀 project view | `project.view` |
| 建／改／刪自己的 personal view | `project.view` ＋ owner 比對 |
| 建／改／刪 project view | `project.manage` |
| 改 project default view | `project.manage` ＋ **audit** |
| 複製 project view → personal | `project.view` |

**View 不影響 Task 權限。** 無權查看的 Task 在 query boundary 排除，
且 **counts 與 items 用同一個 predicate**——否則 count 會洩漏存在性。

## 5. Attention projection

[D55](./01-architecture-decisions.md)：backend 單一函式，固定優先序。

```python
def derive_attention(task, active_run, gates, verification, blocking) -> AttentionDTO:
    """回傳 primary（最高優先的一個）與 signals（全部）。"""
```

| 優先 | attention | 觸發條件 |
|---:|---|---|
| 1 | `waiting_for_your_input` | active run 為 `waiting_for_input` 且有 open question |
| 2 | `pending_human_approval` | 有 gate 待人工核准，或 delivery 待審 |
| 3 | `verification_failed` | 最新 verification report 不合格 |
| 4 | `run_failed` | 最新 run `failed` 且未重排 |
| 5 | `no_eligible_runner` | dispatch 找不到符合 tag／runtime 的 runner |
| 6 | `assigned_runner_offline` | 指定的 runner 離線 |
| 7 | `dependency_blocked` | `blocking_count > 0` |
| 8 | `over_wip_or_stale` | 超過建議 WIP，或 `updated_at` 超過門檻 |

卡片只顯示 **primary**；其餘顯示數量，詳情在 Drawer 完整列出。
**前端不得重建這個順序**——`PX-24` 的測試在 backend；前端測試只驗證「照著渲染」。

### 要不要物化？

`attention` 要能被 filter 與 group，所以它必須進得了 `WHERE`。兩條路：

| 做法 | 代價 |
|---|---|
| 每次查詢即時計算（LATERAL join active run／gates／verification） | 200 張卡實測前先不下結論；風險是三個 join 都在熱路徑 |
| **物化成 `tasks.attention_primary` ＋ `attention_signals`，由寫入路徑維護** | 需要在 run 狀態變化、gate 變化、verification 寫入、dependency 變化四處更新 |

**建議先做第一種並量測**（`PX-24` 的量測項），200 張卡若 P95 > 1 秒再改物化。
決定寫進 `plan/25/` 的 implementation status，不在這裡預先猜。

## 6. API

```text
GET   /api/projects/{id}/work-items      filter/group/order/cursor/per-group cursor
GET   /api/projects/{id}/work-counts     與 work-items 同一 predicate
GET   /api/projects/{id}/views
POST  /api/projects/{id}/views
PATCH /api/work-views/{viewId}
DELETE /api/work-views/{viewId}
POST  /api/work-views/{viewId}/duplicate
GET   /api/me/work-items                 跨專案（見 07）
GET   /api/me/attention-counts
POST  /api/tasks/bulk-update
POST  /api/tasks/{id}/rank
```

### `WorkItemCardDTO`

[D48](./01-architecture-decisions.md)：新 DTO，`BoardCardDTO` 不動。

```text
id, card_ref, title, card_kind
lifecycle, legacy_stage, readiness, is_blocked
blocking_reason, blocking_refs, blocking_count
primary_attention, attention_count
execution_status, active_run_id, active_run_runner_name, active_run_started_at
pending_human_action, verification_state
owner_user_id, owner_name, risk, priority, delivery
requirement_id, epic_id, user_story_id
labels, comment_count, artifact_count
conversation_last_seq, open_question_count, waiting_for_actor
rank, version, updated_at
```

**釘死的大小預算：200 張卡 ≤ 160 KB**（`PX-25` 的測試，形狀比照既有
`test_the_board_card_stays_a_summary`）。既有的 74 KB 是 15 個欄位；
這裡是 33 個，但多數是短 enum 與 uuid，160 KB 是有餘裕的上限而不是預期值。

`visible_fields` **只影響 response shaping，不影響 authorization**。

### Bulk update

```text
POST /api/tasks/bulk-update  { task_ids: [...], patch: {...}, idempotency_key }
```

- 上限 **100** 張。
- 每張**獨立** authorization——不是「有 project.manage 就全過」。
- **all-or-nothing**（第一版）。partial 需要一個「哪些成功哪些失敗」的 UI，那是另一題。
- audit：**一筆 batch 記錄 ＋ 完整 item refs**（不是 100 筆），並在 ADR 0042 寫明理由。
- 冪等：同 key 重送回原結果。

## 7. Tickets

| ID | 工作 | 交付物 | 來源 |
|---|---|---|---|
| `PX-17` | `--attention-*` 與 `--work-*` 語意 token | tokens.css additive、非僅顏色的徽章 | PX-17（縮小） |
| `PX-18` | `WorkItemCard`／`WorkItemRow` 元件 | 八種 attention 的變體、compact／comfortable | PX-18 |
| `PX-21` | **ADR 0040 ＋ 0042**：lifecycle 投影、attention、View schema、rank | 裁決全文 | PX-21 |
| `PX-22` | **Migration**：`work_views`、`tasks.rank`／`is_blocked`／`blocking_*`、索引 | additive、backfill rank、rollback | PX-22 |
| `PX-23` | Filter 驗證與 query compiler | allowlist、深度限制、三個 machine code、負面測試 | PX-23 |
| `PX-24` | **Attention projection 單一來源** ＋ 效能量測 | `derive_attention`、200 張卡 P95、物化與否的裁決 | PX-24 |
| `PX-25` | `work-items`／`work-counts` API | cursor、per-group cursor、160 KB 釘死測試、權限一致性 | PX-25 |
| `PX-26` | View CRUD API | personal／project scope、default 變更 audit、duplicate | PX-26 |
| `PX-27` | 前端最小 query 層（擴充 `useAsyncResource`） | query key、invalidation、optimistic snapshot／rollback | PX-27（[D56](./01-architecture-decisions.md)） |
| `PX-28` | Contract snapshot、RBAC 與 audit 測試 | OpenAPI 快照、權限矩陣、audit 斷言 | PX-28 |

## 8. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | Board 與 List 用同一個 query model | 兩者呼叫同一 endpoint，只有 `layout` 不同 |
| ☐ | attention 在 work-items、My Work、Overview 結果一致 | 同一張卡在三處的 `primary_attention` 相同（測試） |
| ☐ | 無權資源不因 count、group 或 filter 洩漏 | inference 測試：無權使用者的 count 與有權使用者不同且為 0 |
| ☐ | 200 張卡 query P95 通過預算 | 見 [`10`](./10-verification-and-exit.md) §6 |
| ☐ | `WorkItemCardDTO` 200 張 ≤ 160 KB | 釘死測試 |
| ☐ | 不合法 filter 回明確 machine code 並指名欄位 | 六個負面測試 |
| ☐ | shared default view 變更寫 audit；個人 density 不寫 | 兩個測試 |
| ☐ | `BoardCardDTO` 與 `/board` 未變更 | OpenAPI diff 為空 |
| ☐ | bulk update 逐張授權、all-or-nothing、冪等 | 三個測試 |
