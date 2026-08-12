# 04 — `UI-06`／`UI-07`／`UI-08`：看板契約、D24、拖曳反饋

## 1. `UI-06` — 把 `AR-10` §3.3 做完

### 1.1 這不是新規格

`plan/18/07-frontend.md` §3.3 已經逐欄指定過看板要多哪三個欄位、
每一種狀態顯示什麼徽章，並把「第二列與第三列的文案**逐字不同**」
列為 V2.2 的出口條件 4／5。

**實作時那三個欄位一個都沒進去**（2026-08-12 實測）：

| `plan/18` §3.3 指定 | 現況 |
|---|---|
| `active_run_status` | 全 repo 不存在 |
| `active_run_runner_name` | 全 repo 不存在 |
| `waiting_reason` | 只存在於 `DispatchResponseDTO`（`schemas.py:1449`）——**看板拿不到** |

具體後果：**派工之後只要離開那一頁，看板就再也不會告訴你那張卡在等什麼。**
`resolve_waiting_reason()`（`backend/app/services/runs.py:331`）把兩種文案算得好好的，
只是沒有任何畫面在讀它。

**所以 D24 目前不是「沒做樣式」，是看板的資料契約無法表達它。**

### 1.2 三個欄位

```python
# backend/app/api/http/schemas.py — BoardCardDTO
active_run_status: RunStatus | None       # None = 這張卡沒有 active run
active_run_runner_name: str | None        # running 時顯示；None 時前端顯示「任一 Agent」
waiting_reason: str | None                # 前端不重算——那個判斷要跑資格查詢
```

**不加**：`attempt`、`seq`、時間戳、`run_id`。那些是 Run 詳情頁的內容。
連到 Run 詳情用既有的 `task_id` 路由即可，不必為此多一個 UUID 欄位。

**「active run」的定義要寫死**：狀態在 `queued`／`claimed`／`running`／`waiting_for_input`
的那一筆。同一張卡同時只會有一筆（既有的原子認領保證）。
已終結的 run（`succeeded`／`failed`／`lost`／`cancelled`）**不算 active**——
最近一次失敗要不要顯示在卡片上是 `UI-07` 的顯示層決定，不是契約層的。

### 1.3 查詢：第三個 grouped 查詢，不得 N+1

`board_cards()`（`backend/app/repositories/tasks.py:82`）目前是兩個查詢：

1. `select(Task, User.display_name)` — 卡片 ＋ owner
2. `blocking_counts()` — 一個 grouped 查詢

run 投影**必須是第三個 grouped 查詢**，形狀比照 `blocking_counts()`：

```python
async def active_runs(self, project_id) -> dict[uuid.UUID, ActiveRunProjection]:
    """每張卡的 active run，一個查詢。

    per-card 版本就是把 200 張卡的看板從一次往返變成兩百零一次
    ——與 blocking_counts 完全相同的理由。
    """
```

`tasks.py` 已經為此留下明確註解（「The per-card version is the N+1 that turns a
200-card board from one round trip into two hundred and one」）。**照著做。**

### 1.3b ⚠️ `waiting_reason` 是這張 ticket 真正的難點

`active_run_status` 與 `active_run_runner_name` 是單純的 join，**`waiting_reason` 不是。**

`resolve_waiting_reason()`（`runs.py:331`）為了算出那三個值，會呼叫
`_eligible_runner_count()`，而後者**每次都 `select(AgentRunner)` 跑一次資格比對**。
它目前只在 dispatch 的單一 run 上被呼叫過一次——**在看板上逐卡呼叫就是標準的 N+1**，
而且是比 blocking count 更貴的那種（它還要查 registry 的線上狀態）。

**做法**：把它改成一次算完整個專案的批次版本。

```python
async def waiting_reasons(self, runs: list[TaskRun], *, is_online) -> dict[UUID, str]:
    """整批 queued run 的 waiting_reason，一次算完。

    關鍵：enabled runner 清單與線上判定 **只取一次**，
    然後在記憶體裡對每個 run 做資格比對。
    逐 run 呼叫 resolve_waiting_reason() 是 N+1，而且比 blocking_counts 更貴。
    """
```

**只對 `queued` 狀態的 run 算**——其他狀態不需要這個欄位，
送 `null` 即可，順便省掉大部分工作量。

若這一段做起來比預期複雜，**`waiting_reason` 是本 ticket 唯一可以先砍的欄位**
（M1 超標時的退路也是砍它，§1.4）。另外兩個欄位就足以讓 D24 成立——
D24 要的是「等待你的回覆」（`waiting_for_input`），那是 `active_run_status` 的值，
不依賴 `waiting_reason`。**兩者不要綁在一起。**

### 1.4 M1 重量：補做 `plan/18` 沒做的那次

`plan/18` §3.3 自己寫過：

> 這三個欄位每張卡約 80 bytes，200 張卡是 16 KB——可接受，
> 但要在 `AR-10` 量一次並記進 `10-…md`，不是假設。

**那次量測沒有發生。** 本期補做。

| 項目 | 值 |
|---|---|
| 基線（M1，`plan/17/10` §1） | 200 張卡 = **74 KB** |
| `plan/18` 估值 | ＋16 KB |
| **預算** | **≤ 90 KB** |
| 超過怎麼辦 | **先砍 `waiting_reason`**（它也是查詢成本最高的一個，§1.3b）。仍超標再砍 `active_run_runner_name`。`active_run_status` 是 D24 的必要條件，最後才動 |

**先量再決定，不預先妥協。** 結果寫進 `10-open-measurements.md`。

`tasks.py` 的 docstring 明寫「Widening this type is how that decision gets undone」——
所以 `UI-06` 要**同時**更新那段 docstring，把新的量測值寫進去，
讓下一個想加欄位的人看到的是最新的預算而不是 74 KB。

### 1.5 OpenAPI 快照（D33）

純新增欄位，走既有的 `scripts/pj/openapi_diff.py` 機制，
更新 `artifacts/*/baseline/openapi*.json`。**`contracts/` 一個字不改。**

`contracts/CHANGELOG.md` 加一行說明為什麼 board 的變更不在那裡（`01` §8）。

### 1.6 RBAC

沿用既有的 `project.view`，**不新增動作**。
三個欄位都不含機密、不含路徑、不含使用者可控自由文字（`01` §7）。

---

## 2. `UI-07` — 看板重繪

### 2.1 現況

`TaskBoard.vue` 的卡片上是：

```
[risk 原文]  [delivery 原文]  [阻塞 N]  [owner]
```

四顆**外觀完全相同**的灰色藥丸，其中兩顆印的是英文 enum（`low`、`pull_request`）。
六個車道沒有任何顏色區分。

### 2.2 改成

```
┌──────────────────────────────┐
│ ● 等待你的回覆                │  ← 滿版色條，--run-waiting，脈動點
├──────────────────────────────┤
│ TASK-105                      │  ← mono, --font-xs, muted
│ Runner 註冊與認領協定          │
│ [高風險] [PR] [⛒ 待 TASK-107] │  ← RiskBadge / DeliveryBadge / 阻塞
│ 指定 build-vm-02              │  ← --font-xs muted
└──────────────────────────────┘
```

- 車道標頭加 `--stage-*` 色條（prototype `.lane .bar`，3px 寬）；
- WIP 超標**只變色不阻擋**（既有語意，不改）；
- 卡片改用 `UI-04` 的徽章族。

### 2.3 D24：等待你的回覆

**唯一有滿版色條的狀態。** 規則寫死：

| 條件 | 表現 |
|---|---|
| `active_run_status === 'waiting_for_input'` | 滿版 `--run-waiting` 色條 ＋ 脈動 ＋ 卡片外框同色 ＋ `box-shadow` |
| 其他任何狀態 | 一般 `RunBadge`，**沒有色條** |

**不得**為了「一致性」把色條給別的狀態。它之所以有效，是因為它是唯一的。
`02-…md` §2.1 的 token 註解已經把這件事寫在 `--run-waiting` 旁邊。

### 2.4 兩種等待文案（`plan/18` 出口條件 4／5 的回歸）

由 `waiting_reason` 驅動，**前端不重算**。
後端 `resolve_waiting_reason()` 回傳**三個值**（2026-08-12 實測 `runs.py:331`）：

| `waiting_reason` | 卡片顯示 | 使用者該做什麼 |
|---|---|---|
| `no_eligible_runner` | **等待可用的 Agent** | 這個部署沒有能做這件事的機器 → 去設定 |
| `assigned_offline` | **等待指定的 Agent：dev-vm-01（目前離線）** | 那台機器等一下就回來 → 等，或改成不指定 |
| `any` | 排隊中 | 正常排隊，不需要動作 |

前兩則**逐字不同**（`plan/18` 出口條件 4／5），因為它們回答的是不同問題。

`assigned_offline` 那則要**帶 runner 名稱**——所以 `active_run_runner_name`
在 `queued` 狀態下也要送，不能只在 `running` 時送。

> 後端 docstring 自己註明了：這是 **hint 不是 gate**——
> runner 可能三秒後就註冊上來，而 run 不會因此改變任何狀態。
> UI 的文案不要寫成「無法執行」，要寫成「在等什麼」。

### 2.5 指定 agent 的顯示

| 情況 | 顯示 |
|---|---|
| `active_run_runner_name` 有值且 `running` | 「執行中 · build-vm-02」 |
| 卡片指定了 agent 但還沒跑 | 「指定 <名稱>」 |
| 沒指定 | 「任一 Agent」 |

最後一列是 `research/02/09` §4.3 明確要求的——不寫，使用者會以為漏填了什麼。

---

## 3. `UI-08` — 拖曳反饋

### 3.1 現況：文案對了，傳達方式錯了

先把話說清楚，免得冤枉既有實作：

`TaskBoard.vue` 的 `explain()` **已經正確處理了到期的兩種拒絕**，
而且相依那一則會**指名是哪幾張卡**（`blocking_refs.join("、")`）。
prototype 示範的第二種（Done Gate）屬於 **V2.4 的 `DV-05`，本期不到期**——
`DONE_GATE_UNMET` 在 backend／frontend／`docs/error-catalog.md` 三處都不存在，這是正確的。

**要修的是傳達方式**：

| 問題 | 為什麼是問題 |
|---|---|
| 訊息渲染成看板頂端一行 `<p class="board-message">` | 在一面六車道的看板上，**使用者的視線在卡片上，不在頁首**。被拒的那張卡可能在最右邊 |
| 卡片被拒後沒有任何動作 | 樂觀更新已經把它移過去、再默默移回來。**看起來像什麼都沒發生** |
| 三則訊息共用同一個灰框 | 視覺上分不出嚴重程度 |

### 3.2 改成

1. **Toast**（`UI-05` 的 `ToastHost`）：右下角，標題 ＋ 內文兩層，
   左側 3px 色條標示嚴重度。**錯誤類不自動消失。**
2. **卡片彈回動畫**：prototype 的 `bounce`（0.32s，左右各 5px）。
   這是「它真的沒有移動」的體感證據。
3. **`prefers-reduced-motion` 要處理**：偏好減少動態時，
   改成短暫的外框閃爍而不是位移。動畫是輔助線索，不是唯一線索。

### 3.3 訊息（沿用既有文案，不改）

| 錯誤碼 | 訊息 |
|---|---|
| `TASK_VERSION_CONFLICT` | 「這張卡剛被別人改過，已重新載入。」 |
| `TASK_DEPENDENCY_UNSATISFIED` | 「TASK-105、TASK-107 尚未完成。」**指名** |
| `PROJECT_ARCHIVED` | 「這個專案已封存，卡片不能再變更。」 |
| 其他 | `error.message` |

Done Gate 到 V2.4 只要多一個 `case`——**先把 toast 機制做好，正是為了那時候。**

### 3.4 兩種移動路徑都要接

`TaskBoard.vue` 的檔頭寫得很清楚：**「移動到…」選單是主要路徑，拖曳是便利層**，
理由是 HTML5 DnD 對鍵盤不可用、在 Playwright 下不穩。

**這個決定不翻案。** toast 與彈回要**同時接在兩條路徑上**：
選單移動失敗也要有 toast（彈回動畫對選單路徑沒有意義，改成卡片外框閃一下）。

e2e 斷言走選單路徑（既有做法），**不改成拖曳**。

### 3.5 測試

| case | 斷言 |
|---|---|
| 相依未滿足 | toast 出現；文案含被擋的 `card_ref`；卡片回到原車道 |
| 樂觀鎖 409 | toast 出現；文案不同於上一則；卡片回到原車道 |
| 成功移動 | 綠色 toast；卡片留在新車道 |
| `prefers-reduced-motion` | 不套用位移動畫（單元測試查 class） |

## 4. 完成定義

- [ ] `UI-06`：三欄位、grouped 查詢、OpenAPI 快照、**M1 ≤ 90 KB 寫進 `10-…md`**、`tasks.py` docstring 更新
- [ ] `UI-07`：車道著色、D24 唯一性（有測試斷言只有一個狀態有色條）、兩種文案逐字不同
- [ ] `UI-08`：toast ＋ 彈回；兩條移動路徑都接；`prefers-reduced-motion`
- [ ] `make tokens` 綠
