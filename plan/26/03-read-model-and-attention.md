# 03 — 讀模型與 attention

> **ticket：`PX-24`（投影 ＋ attention ＋ 量測）。依賴 `PX-22`。**
> 這一份定義的是**「這張卡現在怎麼樣」的唯一答案**。
> Board、Backlog、List、Drawer、My Work、Overview 六個畫面全部讀它。

## 1. 四個正交狀態面

不再用單一 `stage` 同時表達進度、阻塞、Agent 執行與人工決策。
四個面互相獨立，各自回答一個問題。

### A. Work lifecycle — 「工作進展到哪裡？」

```text
backlog → ready → in_progress → review → done
```

**這是投影，不是新欄位。** `tasks.stage` 的六個值一個都不動（D49）：

| `tasks.stage` | `lifecycle` | `is_blocked` |
|---|---|---|
| `backlog` | `backlog` | 依 `is_blocked` 欄 |
| `blocked` | **`ready`** | **一律 `true`**（見下） |
| `ready` | `ready` | 依欄位 |
| `implementing` | `in_progress` | 依欄位 |
| `verify` | `review` | 依欄位 |
| `done` | `done` | **一律 `false`** |

兩個「一律」是 [D102](./01-decisions-and-governance.md) 的 dual-write 規則：

- **`stage='blocked'` 一律投影成 `is_blocked=true`，即使欄位是 `false`。**
  **寫這一欄的不是舊 UI，是平台自己**——`run_reaper.py:176`（lease 過期）、
  `run_reaper.py:246`（重試耗盡）、`runs.py:1510`（24 小時無人回答）。
  所以 ☑ [D117](./01-decisions-and-governance.md#d117) 拿掉舊 UI 之後**這條規則不會消失**，
  它會持續到 `beta.2` 的 `HD-06` 改掉那三處為止。
- **`stage='done'` 一律投影成 `is_blocked=false`。**
  一張完成的卡不會「被阻塞」，而 backfill 之後可能留下這個組合。

DTO 同時帶 `legacy_stage`，讓「這張卡在舊看板長什麼樣」查得到。

### B. Readiness — 「這張卡能被執行了嗎？」

```text
draft → needs_clarification → ready
```

由既有 `tasks.readiness` JSONB ＋ `ProcessService.effective().readiness_keys()` 推導，
**不新增欄位**：

```python
missing = [k for k in process.readiness_keys() if not (task.readiness or {}).get(k)]
if not missing:            return "ready"
if len(missing) == len(keys): return "draft"
return "needs_clarification"
```

**注意 `readiness_keys()` 是 per-deployment 的一份定義，可被 project 關掉某幾項**
（`process.py:225`）。所以 readiness 的推導要吃 `EffectiveProcess`，
而 `EffectiveProcess` 是 per-project 的——**`derive_attention` 對每個 project
只取一次 process，不是每張卡一次**。這是 `PX-24` 的一個 N+1 陷阱。

### C. Execution — 「Agent 執行目前如何？」

```text
not_queued | queued | claimed | running | waiting_for_input
          | succeeded | failed | cancelled
```

直接來自 `task_runs.status`（既有值），`not_queued` 表示沒有 active run。
資料來源是既有的 `TaskRepository.active_runs()`——**複用，不重寫**
（它已經用 `row_number()` 處理了「一張卡多個 active run」的髒資料）。

### D. Human decision — 「是否等待人類正式決定？」

```text
not_required | pending | approved | changes_requested
```

由 `tasks.gates`、delivery 狀態與 verification 推導。
`gates` 的形狀是 `{gate_key: {approved_by, approved_at}}`，
而 `EffectiveProcess.gates` 給出這個部署有哪些 gate 可用——
**未定義的 gate key 不算數，derived-disabled 的 gate 也不算數**
（`process.py` 的 `Gate.enabled`）。

## 2. `derive_attention`：兩相位

[D92](./01-decisions-and-governance.md) 的實作規格。

```python
# services/work/attention.py

ATTENTION_ORDER = (
    "waiting_for_your_input",     # 1
    "pending_human_approval",     # 2
    "verification_failed",        # 3
    "run_failed",                 # 4
    "no_eligible_runner",         # 5  ← 相位 B
    "assigned_runner_offline",    # 6  ← 相位 B
    "dependency_blocked",         # 7
    "over_wip_or_stale",          # 8
)

def derive_attention(row: WorkRow, runtime: RuntimeSignals | None) -> AttentionDTO:
    """The single source of truth. Returns primary (highest) and the full signal set.

    `runtime` is None when the caller could not consult the node registry — a
    background job, a migration, a test without an app. In that case levels 5 and 6
    are **absent from the signal set**, not `false`: "we did not look" and "we looked
    and there is a runner" are different facts, and a caller that cannot tell them
    apart will eventually render the second when it means the first.
    """
```

### 相位 A（SQL，一個查詢）

六級的述詞全部由 `work_rows` 這個 CTE 產生，與 items 查詢**同一個 CTE**：

| 級 | 述詞 |
|---:|---|
| 1 | ~~`tasks.open_question_count > 0 AND active_run.status = 'waiting_for_input'`~~ → **`tasks.open_question_count > 0 AND tasks.waiting_for_actor = 'human'`**（見下方更正） |
| 2 | `human_decision = 'pending'`（gates 未齊 或 delivery 待審） |
| 3 | `latest_verification.result IN ('failed','partial')` 且無更新的 passed report |
| 4 | `latest_run.status = 'failed'` 且無更新的 run |
| 7 | `blocking_count > 0` |
| 8 | `updated_at < now() - :stale_after` 或 該 group 超過 `wip_suggested` |

`tasks.open_question_count` 是 `alpha.2` 的 `0040` 已經加好的投影欄——
**不要 join `task_questions`**，那一欄存在的理由就是這個。

> **更正（2026-08-24，`plan/26/12` §2.24）：第一級的述詞上面原本寫錯了，而實作照抄了。**
>
> 劃掉的版本讀 **run 狀態**。Agent 有兩種等法：問完繼續輪詢（run 停在
> `waiting_for_input`），和問完**直接結束**（run 是 `succeeded` / `awaiting_input`）——
> 而 `cliora task ask` 印出來的三個選項裡，第一個、被標為「建議」的就是「直接結束」。
> 所以照建議做的 Agent，它的卡片在看板上**完全沒有標記**：那個在等它的人看不出它在等自己。
>
> `tasks.waiting_for_actor`（ADR 0035 §8）存在的理由正是這個。它由 question 狀態寫入，
> `ConversationService._reproject` 是唯一的 writer，所以兩種等法給同一個答案。
> 這一級要讀它，而**不是**讀 run。
>
> 十五條單元測試沒抓到，因為它們全部照這張表的形狀佈景。J4 對真的 daemon 跑起來時
> 才發現——`plan/26/12` §2.24 記了為什麼一份寫錯的規格會連帶把測試一起寫錯。

同一個 CTE 額外輸出 `queued_task_ids`：`active_run.status = 'queued'` 的集合。

### 相位 B（Python，一次 snapshot）

```python
def resolve_runtime_signals(queued: list[ActiveRunProjection], *, is_online) -> dict[UUID, str]:
    """levels 5 and 6, for the queued set only.

    One runner query and one registry snapshot for the whole page — the same shape
    `TaskRepository.waiting_reasons()` already uses. Per-run resolution
    (`RunService.resolve_waiting_reason`) is the console path and stays as it is; this
    is the board path and it must not be N queries.
    """
```

**兩者必須給出相同答案。** `PX-24` 有一支測試：對同一個 run，
`resolve_runtime_signals()` 與 `RunService.resolve_waiting_reason()`
回傳的 kind 相同。**這是本期最重要的一致性測試**——
console 說「沒有符合的 runner」而看板說「等待中」，
是這一對函式存在時最容易出現的失敗。

複用既有述詞：`tag_match(runner, task)` 與 `accepts_secrets(runner, task)`
（`services/runs.py` 已有），**不重寫**。

### 為什麼順序是這八個

| 優先 | attention | 這個順序的理由 |
|---:|---|---|
| 1 | `waiting_for_your_input` | 有一個 Agent 停在那裡等一句話。**這是唯一一個「一個人可以在十秒內解除」的狀態**，而且它同時在燒 lease |
| 2 | `pending_human_approval` | 也是等人，但沒有東西停著 |
| 3 | `verification_failed` | 有結論了，是壞的。比 4 高，因為它說的是「做完了但不對」 |
| 4 | `run_failed` | 沒有結論。retry 可能就好了 |
| 5 | `no_eligible_runner` | 設定問題，人可以修，但不急——卡片沒有在退化 |
| 6 | `assigned_runner_offline` | 同 5，但更可能自己好 |
| 7 | `dependency_blocked` | 在等別的卡，而別的卡有自己的 attention |
| 8 | `over_wip_or_stale` | 這不是事件，是趨勢 |

**前端不得重建這個順序。** `ATTENTION_ORDER` 這個 tuple 是唯一的定義，
`PX-24` 的測試在 backend；`PX-18` 的前端測試只驗證「照著渲染」。

## 3. `WorkRow`：一次查詢的形狀

```python
@dataclass(frozen=True, slots=True)
class WorkRow:
    """One card as the read model sees it, before attention.

    Deliberately **not** BoardCard: that type is pinned at 89,251 bytes for 200 cards
    (repositories/tasks.py:44) and shares a query with the V1 board. Widening it is
    how that pin gets undone. This one has its own budget (D94) and its own query.
    """
    task: Task
    owner_name: str | None
    blocking_count: int
    blocking_refs: tuple[str, ...]      # 上限 3（D108）
    gates_approved_count: int
    gates_required_count: int
    active_run: ActiveRunProjection | None
    latest_run_status: str | None
    latest_verification_result: str | None
    readiness_missing: tuple[str, ...]
```

一個 `work-items` 請求的查詢數（`PX-24` 的預算）：

```text
1  work_rows CTE          （tasks + owner join + active run lateral + verification lateral）
1  blocking_counts        （既有 TaskRepository.blocking_counts，複用）
1  blocking_refs          （只對 blocking_count > 0 的卡，一個 IN 查詢）
1  runners                （相位 B，只在 queued 非空時）
── 上限 4 個查詢，與卡片數無關
```

**`blocking_refs` 是第三個查詢而不是 CTE 的一部分**：
它要對每張卡取最多三個 `card_ref`，而在 CTE 裡做 `array_agg` 加 `LIMIT`
需要一個 correlated subquery，那會讓計畫器對 200 張卡各跑一次。
一個 `IN` 查詢再在 Python 分組是四行程式碼。

## 4. `WorkItemCardDTO`

```text
身分       id, card_ref, title, card_kind
生命週期    lifecycle, legacy_stage, readiness, is_blocked
阻塞       blocking_reason, blocking_refs（≤3）, blocking_count
注意力      primary_attention, attention_count
執行       execution_status, active_run_id, active_run_runner_name, active_run_started_at
決策       pending_human_action, verification_state
歸屬       owner_user_id, owner_name, risk, priority, delivery
關聯       requirement_id, epic_id, user_story_id
其他       labels, comment_count, artifact_count
對話       conversation_last_seq, open_question_count, waiting_for_actor
排序       rank, version, updated_at
```

**33 欄。** 大小預算走 [D94](./01-decisions-and-governance.md)：先量再釘。

`attention_signals` 的**全文不在卡片上**（[D107](./01-decisions-and-governance.md)），
只有 `primary_attention` ＋ `attention_count`。完整清單在 Drawer 的 detail endpoint。

`visible_fields` **只影響 response shaping，不影響 authorization**。
這一條有測試：一個 `visible_fields` 不含 `owner_name` 的 view，
其回應不含該欄，但**授權判斷完全不變**。

### 若量測超過 200 KB，砍除順序

依「單位 bytes 換到的資訊量」由低到高：

| 序 | 砍什麼 | 為什麼它最先走 |
|---:|---|---|
| 1 | `active_run_started_at` | 卡片顯示的是「12m」，前端從 `updated_at` 也算得出近似值；精確值在 Drawer |
| 2 | `blocking_refs` | 留 `blocking_count`。卡片上「2 張卡阻塞中」與「TK-3、TK-7 阻塞中」的行為差別是一次點擊 |
| 3 | `comment_count` / `artifact_count` | 兩個整數，但 200 張 × 兩個 key 名 ≈ 6 KB，而它們不驅動任何決定 |
| 4 | `requirement_id` / `epic_id` / `user_story_id` | 只有 group-by 用得到，而 group-by 是 server-side 做的 |

**砍到第 4 還不夠就不是欄位問題，是 200 張卡不該一次回。**
那時的正確反應是把預設 per-column page size 從 50 降到 25，
而不是繼續砍——記在 [`12`](./12-implementation-status.md)。

## 5. 效能量測（`PX-24` 的產物）

在 `scripts/cv/seed-dataset.py` 的固定資料集上（200 卡 / 6 queued）：

| 量什麼 | 目標 | 為什麼量這個 |
|---|---|---|
| `work-items` 200 張 P95 | < 1s | 上游的預算 |
| `work-counts` P95 | < 200ms | D95 讓它每 20 秒被打一次 |
| 相位 B 在 6 queued 的耗時 | 記錄 | 基準 |
| 相位 B 在 **60 queued** 的耗時 | 記錄 | D92 說成本綁佇列長度，**這一格就是在證明或推翻它** |
| `derive_attention` 純函式 200 次 | < 10ms | 它不該是瓶頸；若是，表示它在裡面查東西 |
| `ix_tasks_project_updated` 前後 `EXPLAIN` | 記錄 | D104 |

**「60 queued」的 fixture 要新建**：`scripts/px/seed-queued.py`，
在既有資料集上把 60 張 ready 卡 dispatch 成 queued 且無合格 runner。
這是本期唯一新增的 fixture。

## 6. 什麼**不是**這一份的責任

| 不在這裡 | 在哪裡 |
|---|---|
| filter 的驗證與編譯 | [`04`](./04-filter-and-query-compiler.md) |
| 分頁、游標、bulk、view CRUD | [`05`](./05-work-items-and-view-api.md) |
| 卡片長什麼樣 | [`06`](./06-board-and-backlog.md) §3 |
| 跨專案 | [`08`](./08-my-work-and-navigation.md) §2——**但它呼叫的是這裡的同一個 `derive_attention`** |
