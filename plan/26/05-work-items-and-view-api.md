# 05 — `work-items`、view CRUD、bulk 與 rank 的 API

> **ticket：`PX-25`（items／counts／bulk）、`PX-26`（view CRUD）、
> `PX-47`（`/api/me/*`）、`PX-61`（rank）。**

## 1. 端點總表

```text
GET    /api/projects/{id}/work-items       filter / group / order / cursor / per-group cursor
GET    /api/projects/{id}/work-counts      與 work-items 同一個 predicate 與同一個 ProjectScope
GET    /api/projects/{id}/views
POST   /api/projects/{id}/views
PATCH  /api/work-views/{viewId}
DELETE /api/work-views/{viewId}
POST   /api/work-views/{viewId}/duplicate
GET    /api/me/work-items                  跨專案
GET    /api/me/attention-counts
POST   /api/tasks/bulk-update
POST   /api/tasks/{id}/rank
```

全部落在**新檔** `backend/app/api/http/work.py` 與 `me.py`，
除了 `POST /api/tasks/{id}/rank`（放在既有 `tasks.py`，因為它的 authorization
與其餘 task 寫入路徑相同）。

`api/http/tasks.py` 的 `read_board` 與 `BoardCardDTO` **一個位元組都不動**（D48）。

## 2. `GET /work-items`

### 查詢參數

```text
view       uuid          可選。取 work_views 的定義當基底
filter     base64url     可選。覆蓋／合併 view 的 filter（quick filter，D103）
group      enum          可選。lifecycle | owner | epic | risk | requirement | execution_status | attention | blocking_reason
order      string        可選。`rank:asc` / `updated_at:desc`，最多兩層
cursor     base64url     單一 group 時使用
cursors    base64url     per-group：{group_key: cursor} 的 map
limit      int           每 group 上限，預設 50，最大 100
```

`group` 的八個值域。**`attention` 可以分組但不能排序**（[`04`](./04-filter-and-query-compiler.md) §4）——
分組是在頁面內做的，排序是在 SQL 裡做的。

### 回應

```json
{
  "groups": [
    { "key": "ready", "label": "Ready", "count": 348,
      "items": [ …WorkItemCardDTO… ], "next_cursor": "eyJyYW5rIjoi…" }
  ],
  "runtime_signals_available": true
}
```

**`count` 是 server total，不是 `len(items)`。** 這是 `PX-36` 的釘死測試：
載入 20 張、`count` 顯示 348。上游把這件事叫做「這類看板最常見的謊」，
本計畫同意，並且把它放在**後端**的測試而不只是前端。

**`runtime_signals_available`** 是本計畫加的欄位。它在 `false` 時表示
相位 B 沒有跑（沒有 registry，或 registry 剛啟動還沒有任何節點連上）。
理由是 [`03`](./03-read-model-and-attention.md) §2 的那句 docstring：
「we did not look」與「we looked and there is a runner」是不同的事實。
前端在 `false` 時把 `no_eligible_runner` 的 quick filter chip 標成
「暫時不可用」，而不是回 0 筆讓人以為問題解決了。

### 游標（[D109](./01-decisions-and-governance.md)）

```text
cursor = base64url(json({"rank": "a3f", "id": "…uuid…"}))
WHERE (rank, id) > (:rank, :id)   -- 依 order 方向調整
```

**不是 offset**（會在插入時漏卡），**不是純 `updated_at`**
（使用者看的時候它會變）。`id` 是 tie-breaker，因為再平衡期間 rank 可能短暫重複。

`order` 不是 `rank` 時，cursor 帶的是那個排序鍵 ＋ `id`，
規則相同。排序鍵可為 null（例如 `owner`）時，cursor 用
`(coalesce(key, sentinel), id)`，sentinel 依方向是最大或最小值。

### 大小預算（[D94](./01-decisions-and-governance.md)）

`PX-25` 的**第一個** commit 是量測，不是 endpoint：

```python
# backend/tests/db/test_work_items_size.py
async def test_the_work_item_card_stays_within_its_measured_budget(...):
    """D94's pin. Measured <BYTES> on <DATE> against the fixed dataset (seed 20260819).

    The threshold is the measurement plus 15 %, not a number from a planning document:
    the upstream 160 KB was derived from a 74 KB figure that `plan/19` already made
    stale — the same 200-card fixture is 89,251 bytes today, 99.2 % of the board
    card's own 90,000-byte budget.

    Top five fields by bytes: <…>
    """
```

同一支測試順便重量 `BoardCardDTO`，斷言 **89,251 ± 2%**。
理由：新讀模型與舊看板共用 `active_runs()` 與 `blocking_counts()`，
有人為了新卡讓那兩個查詢多回一欄，舊卡會跟著變大而 OpenAPI diff 是空的。

## 3. `GET /work-counts`

**一個 `GROUP BY`，不是跑一次 items 再數**（[D110](./01-decisions-and-governance.md)）。

```sql
SELECT <group_key>, count(*) FROM <同一個 work_rows CTE> WHERE <同一份 filter> GROUP BY 1
```

**唯一的第二個查詢**是 attention 的兩個 runtime 級：
先取 queued 候選集（一個小查詢），相位 B 解析，回傳兩個純量。

```json
{
  "by_lifecycle":  { "backlog": 80, "ready": 40, "in_progress": 20, "review": 12, "done": 48 },
  "by_attention":  { "waiting_for_your_input": 3, "no_eligible_runner": 2, … },
  "total": 200,
  "runtime_signals_available": true
}
```

這是 [D95](./01-decisions-and-governance.md) 下**最熱的 endpoint**——
每個開著看板的分頁每 20 秒打一次。P95 預算 **< 200ms**。

**counts 與 items 用同一個 `ProjectScope` 實例與同一份 filter 編譯結果。**
不是「同樣的邏輯」，是同一個物件：

```python
async def work_counts(session, *, scope: ProjectScope, compiled: CompiledFilter, group: str): ...
async def work_items (session, *, scope: ProjectScope, compiled: CompiledFilter, …): ...
```

`PX-28` 有一支測試對同一個 fixture 打兩個 endpoint，
斷言 `sum(counts.by_lifecycle.values()) == counts.total ==` items 全部 group 的 count 總和。

## 4. View CRUD（`PX-26`）

### 權限（[D53](../../research/03/08-data-model-and-contract.md)，不新增 RBAC 動作）

| 操作 | 需要 |
|---|---|
| 讀 project view | `project.view` |
| 建／改／刪自己的 personal view | `project.view` ＋ `owner_user_id == actor.id` |
| 建／改／刪 project view | `project.manage` |
| 改 project default view | `project.manage` ＋ **audit** |
| 複製 project view → personal | `project.view` |

`VIEW_NOT_OWNED`（403）用在「改別人的 personal view」。
**不是 404**——一個 personal view 的存在不是機密（它在 `/api/projects/{id}/views`
的列表裡不會出現，因為那個列表只回自己的與 project 的），
而 403 讓「這是別人的」與「這不存在」在客戶端可以分開處理。

`VIEW_NAME_CONFLICT`（409）用在 `uq_work_views_name`。
`details` 帶 `{"name": …, "scope": …}`。

### 改 default 是一對 UPDATE

```sql
BEGIN;
  UPDATE work_views SET is_default = false WHERE project_id = ? AND is_default AND scope = 'project';
  UPDATE work_views SET is_default = true  WHERE id = ?;
COMMIT;
```

`uq_work_views_default`（[`02`](./02-data-layer.md) §2）讓中途失敗不會留下兩個 default。
audit 記 `{old_view_id, new_view_id, actor}`。

**不記 audit 的**：personal density、personal visible fields、暫時 filter、
Drawer 開關。`PX-28` 有兩支測試——一支斷言 default 變更寫了 audit，
一支斷言改 density 沒寫。

### `visible_fields` 不影響授權

一支測試：一個 `visible_fields` 不含 `owner_name` 的 view，
回應不含該欄，但同一個 filter 的 items 集合與 counts **完全不變**。

### View 不改變 Task 權限

一支測試：一個 project view 的 filter 涵蓋某張卡，
而呼叫者無權看該卡（今天只能用「無 `project.view`」構造）→ 該卡不出現。
這一條的誠實版本見 [D93](./01-decisions-and-governance.md)。

## 5. `POST /api/tasks/bulk-update`（`PX-25`）

```json
{ "task_ids": ["…"], "patch": { "owner_user_id": "…", "risk": "high" }, "idempotency_key": "…" }
```

| 規則 | 實作 |
|---|---|
| 上限 100 | 超過回 `BULK_LIMIT_EXCEEDED`（400），`details.limit` ＋ `details.received` |
| **逐張走 `TaskService.update()`** | [D96](./01-decisions-and-governance.md)。不寫第二條 stage 寫入路徑 |
| 每張獨立 authorization | 不是「有 `project.manage` 就全過」 |
| all-or-nothing | 一個交易。第一個失敗回滾全部，回應指名**哪一張**與**為什麼** |
| 冪等 | 同 key 回原結果。沿用 `alpha.2` 的 `task_messages.idempotency_key` 形狀 |
| audit 一列 | `{actor, patch, item_refs: [card_ref…]}`（[D105](./01-decisions-and-governance.md)） |
| activity N 列 | 每張卡的時間軸要看得到自己那一次變更 |

**patch 的欄位受 `EDITABLE_FIELDS` 限制**，與單張 PATCH 同一套。
`version` **不在 patch 裡**：bulk 是「把這 100 張都改成這樣」，
逐張帶 version 會讓 UI 必須先讀取 100 張的當前版本。
所以 bulk 的樂觀鎖語意是**沒有**——這一點要在 API 文件與 UI 上明說，
而不是靜默地讓最後一個寫入者贏。

**交易成本**（D96）：100 張 ≈ 400 列寫入 ＋ 最多 100 次 Done Gate 評估。
`PX-25` 量 P95，超過 3 秒就把上限下修到量出來的值並記在
[`12`](./12-implementation-status.md)。

## 6. `POST /api/tasks/{id}/rank`（`PX-61`）

```json
{ "previous_task_id": "…", "next_task_id": "…", "column_id": null, "version": 7 }
```

命名逐字採用 kintra 的 `TicketMove`（[`13`](./13-kintra-port.md) §7）：
`previous_`／`next_` 而不是 `before_`／`after_`——後兩個字在時間與順序之間有歧義。
`column_id` 省略代表**同 group 重排**。

**送 neighbor IDs，不送 index。** 理由是上游 [`05`](../../research/03/05-phase-p2-board-and-backlog.md) §3.4
的那一條：篩選後的第 3 個位置不是資料裡的第 3 個位置。
`PX-34` 的請求 payload 有一個斷言測試。

```python
# 兩個鄰居的 rank —— **一次查詢**（kintra `_neighbour_ranks` 的形狀，13 §2）
previous_rank, next_rank = await repo.neighbour_ranks(task, previous_id, next_id)
new_rank = rank_between(previous_rank, next_rank)
await service.update(task, {"rank": new_rank, **group_change}, expected_version=version)
if len(new_rank) > INLINE_REBALANCE_THRESHOLD:      # 同步保險閥
    await service.rebalance_project(task.project_id)
```

`RANK_NEIGHBOR_STALE`（409）用在三種情況，`details.reason` 分別是：

| reason | 情況 |
|---|---|
| `neighbor_missing` | neighbor 已被刪除 |
| `neighbor_moved` | neighbor 的 rank 已經不在原本的相對位置（`before.rank >= after.rank`） |
| `cross_project` | neighbor 屬於別的 project |

第三種**不回 404**：兩張卡都在呼叫者可見的範圍內（今天全域可見），
所以 409 沒有洩漏任何存在性。**若未來加了 per-project membership，
這一行要改成 404**，而那件事記在 [`11`](./11-open-measurements.md) 第 1 項。

### 跨 group 拖曳是**一個**請求

上游 [`05`](../../research/03/05-phase-p2-board-and-backlog.md) §3.5：
「拖到另一個 group 時同時改 rank 與該欄位，且兩者在同一個請求裡」。
實作是 `PATCH /api/tasks/{id}` 的 body 同時含 `rank` 與 group 欄位——
**不是**先打 rank 再打 patch。`PX-34` 有一個 payload 斷言。

於是 `rank` 進 `EDITABLE_FIELDS`（[`02`](./02-data-layer.md) §8），
而 `POST /tasks/{id}/rank` 是「只改順序」的便捷路徑
（它內部呼叫同一個 `TaskService.update()`）。

**一次 move 只產生一個 `UPDATE tasks`。** 這條有一支**以 SQL 語句計數斷言**的測試
（移植自 kintra 的 `P2-T4`，[`13`](./13-kintra-port.md) §2）——
kintra 記錄的第一條階段風險就是「拖曳造成整欄 UPDATE」，
而一個「順手把整欄 rank 重算」的實作會回應正確、測試全綠。

### 再平衡

```text
背景門檻 24    專案內任一 rank 的**字串長度** > 24 → 排入背景再平衡
同步保險閥 48  rank_between 產出的**字串長度** > 48 → 當場對整個 project 重新平衡
```

**兩個門檻量的都是 rank 字串的長度**，不是相鄰 rank 的共同前綴長度——
本計畫第一版寫錯了，更正依據是 kintra `ticket_service.py:544`
（`if len(new_rank) > ranking.INLINE_REBALANCE_THRESHOLD`），見 [`13`](./13-kintra-port.md) §2。

門檻常數 `REBALANCE_THRESHOLD` / `INLINE_REBALANCE_THRESHOLD` 逐字移植自 kintra。
**再平衡不得改變相對順序**——這是移植過來的整合測試
（`../kintra/backend/tests/integration/test_rank_rebalance.py`）。

背景再平衡沿用 `RunReaper` 的形狀（`services/run_reaper.py`：
先 reconcile 一次再進迴圈，一輪三個交易，每輪有上限）。

## 7. `/api/me/*`（`PX-47`）

```text
GET /api/me/work-items         同樣的 filter / group / order / cursor
GET /api/me/attention-counts
```

**與 `/api/projects/{id}/work-items` 共用同一個 query compiler 與同一個
`derive_attention`**，只有 `ProjectScope` 不同（[D93](./01-decisions-and-governance.md)）。
這一條有一支測試：對同一張卡，兩個 endpoint 回的 `primary_attention` 相同。

**不在前端對每個專案各發一次請求再合併。** 三個理由（上游 §4.1）：
N 個專案就是 N 個請求；分頁無法跨專案正確排序；權限邊界會變成前端的責任。

`/api/me/*` 是新的路徑命名空間——**這個 repo 今天沒有任何 `/api/me/`**。
所以 `PX-47` 要同時決定：`/api/me/` 下未來還會有什麼（notification、preferences），
並在 `me.py` 的 module docstring 寫下這個命名空間的規則
（**只回「與這個呼叫者有關」的東西，永遠不接受 `user_id` 參數**）。
沒有這句話，第一個需要「看別人的 My Work」的需求會在這裡加一個 `?user_id=`。

## 8. OpenAPI 與相容（`PX-28`）

| 斷言 | 怎麼證明 |
|---|---|
| `BoardCardDTO` 與 `/board` 未變更 | OpenAPI diff 為空（沿用既有快照機制） |
| `BoardCardDTO` 的 **bytes** 未變 | 89,251 ± 2%（D94） |
| RBAC 27 個動作不變 | `test_permission_matrix.py` 既有斷言 ＋ `len(ALL_ACTIONS) == 27` |
| run token 拿不到新 endpoint | 對七個新 endpoint 各一條 403 測試 |
| `AGENT_FORBIDDEN_FIELDS` 含新三欄 | 三條負面測試：run token PATCH `is_blocked`／`blocking_reason`／`rank` → 422 |
| shared default 變更寫 audit；personal density 不寫 | 兩支測試 |

## 9. `GET /projects/{id}/board-attention`（`PX-24`，**暫時**）

[D115](./01-decisions-and-governance.md) 的波次 0 產物。

```json
{ "<task_id>": { "primary": "waiting_for_your_input", "count": 2 }, … }
```

既有的 `/board` 回應一個位元組都不動（D48）；前端把這個 map 合併上去，
就讓**既有看板**的卡片有了 attention 徽章——三個波次之前。

四條規則：

1. **它呼叫的是 `derive_attention`，不是第二份邏輯。** 波次 2 的 `work-items`
   用同一個函式，所以這裡不是原型。
2. 波次 0 時 `0043` 還沒上，所以相位 A 讀不到 `is_blocked`——
   `stage='blocked'` 直接投影（[D102](./01-decisions-and-governance.md) 本來就這樣規定）。
3. **不進 OpenAPI 的相容承諾。** module docstring 第一行寫
   `temporary; removed when /work-items lands in wave 2`。
4. **波次 2 的 `PX-25` 負責刪掉它**，而 `PX-28` 的 OpenAPI 快照斷言它不見了。
   一個「暫時」的 endpoint 若沒有人負責刪，它就是永久的。
