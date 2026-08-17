# 01 — 決策與治理

決策編號沿用全域序列。[`research/03`](../../research/03/01-architecture-decisions.md) 用到 **D58**，本目錄從 **D59** 開始。

## 1. 從規劃層繼承的六項

這六項在 `research/03` 已有全文，這裡只記**落到 repo 之後多知道的事**。

### D37 — Ticket 是持久對話；Run 與 Turn 是可替換的執行

讀完程式碼之後，這條的可測形式更具體了：

```text
run_logs 有 logs_expire_at（成功 3 天、失敗 14 天），retention sweep 會刪
task_messages 沒有到期欄位，也不會被任何 sweep 碰
```

兩者的差別已經寫在資料庫裡了，本期只是讓行為跟上：
**清掉某張卡全部 `run_logs` 之後，conversation、question 與 proposal 仍完整。**

### D38 — `conversation_seq` 是 `tasks` 上的計數器欄

落地時多一個好處：`tasks.conversation_seq` 讓 `CV-13` 的
`conversation_last_seq` 投影**不必 join `task_messages`**。
那個 join 在 200 張卡的看板上會很貴（`beta.1` 的 work-items 要用到它）。

取號語句：

```sql
UPDATE tasks SET conversation_seq = conversation_seq + 1
WHERE id = :task_id RETURNING conversation_seq;
```

鎖的是卡片列。**那一列本來就要更新**——`tasks.updated_at` 有 `onupdate=func.now()`
（`models.py:834-836`），所以任何訊息寫入本來就會碰它。沒有多出一次鎖競爭。

### D39 — Continuation turn 建模成 child run

落地細節見 [`04`](./04-answer-resume-and-turns.md)。這裡只記一條**規劃層沒說的**：

continuation run **不走 `dispatch()`**，走一個新的 `enqueue_continuation()`。
理由是 `dispatch()` 的前兩個檢查會擋住它：

```python
if task.stage != "ready":            # 卡片可能在 implementing
    raise ApiError("TASK_NOT_READY", ...)
if await self.active_for_task(task.id) is not None:
    raise ApiError("RUN_ALREADY_ACTIVE", ...)
```

**但 `dispatch()` 的其餘檢查必須重跑**（D62）。

### ☑ D42 — 維持單一未答問題（**2026-08-16 已裁決：不放寬**）

### ☑ D44 — `alpha.2` 不動 contract（**2026-08-16 已裁決：不動**）

`GATE-CV-CONTRACT-FROZEN` 沿用 `plan/22` 已經寫好的那一條
（`contracts/` 全樹 sha256 與基線相同），不必新寫。

### D43 — Message 不可覆寫

本期落地為：`task_messages` **沒有任何 `UPDATE` 路徑**，
由 `GATE-CV-APPEND-ONLY` 斷言（形狀沿用 `plan/22` 的 `GATE-RQ-APPEND-ONLY`，
白名單只有 `task_questions.state` 與 `task_questions.answered_*`）。

人類編輯本期**不提供**。Agent 訊息**永不提供**編輯——錯了追加一則更正。

---

## 2. 本期新增的決策

### ☑ D59 — Agent process 結束時，Central 推導 `awaiting_input`（**2026-08-16 已裁決：採用**）

**要點頭什麼**：`finish()` 在 `run.complete` 且該 run 有 open question 時，
不把卡片當成交付完成，而是 `status='succeeded'`、`result='awaiting_input'`。

**為什麼在 Central 推導而不是讓 daemon 說**：讓 daemon 說有兩條路，兩條都貴。
一是新增訊息型別（D44 的代價）；二是在 `run.complete` 的 `result` 塞新值——
而 `result` 是 node→central 的欄位，Central 會拿 contract schema 驗它，
新的列舉值就是 contract 變更。**Central 這邊已經知道有沒有 open question**，
它是唯一一個不必問任何人就能回答這個問題的地方。

**這不是「猜」**：open question 是這個 run 自己透過 `POST /api/cli/runs/messages`
（`kind='question'`）建立的，run token 綁 run id，來源明確。

**代價**：
1. `run.result` 多一個 Central 端產生的值。既有的 `result` 有 payload 帶進來的
   （`succeeded`／`failed`）與 Central 產生的（`delivery_incomplete`，`runs.py:1136`）
   兩種——**後者已有先例**，`awaiting_input` 走同一條路。
2. `_record_run_outcome` 的 `delivery: artifact` 檢查會在 `awaiting_input` 時誤判
   （問了問題就 exit 的 run 當然沒附產物）。**必須跳過**——見 [`04`](./04-answer-resume-and-turns.md) §2.3。
3. 24 小時逾時的掃描對象要換。見 [`04`](./04-answer-resume-and-turns.md) §4。

**不同意的話**：出口條件「Agent process 結束或 daemon 重啟後，conversation 可從 DB 恢復」
做不到。剩下的替代只有 D44 改成動 contract。

### D60 — Continuation run 沿用 root run 的分支名

**要點頭什麼**：`run_branch()` 對 `parent_run_id is not null` 的 run，
用 root run 的 `seq` 而不是自己的。

**為什麼**：現行是 `f"cliora/{task.card_ref}-{run.seq}"`（`runs.py:1444`）。
一張 `pull_request` 卡在第一輪（seq=2）推了 `cliora/TK-142-2` 並開了 PR；
第二輪是新 run（seq=3），會推 `cliora/TK-142-3`。
**兩輪的成果分在兩條分支，PR 指著第一條，而沒有任何測試會紅。**

**「root run」怎麼找**：沿 `parent_run_id` 往上走到 `parent_run_id IS NULL` 的那一個。
鏈的長度就是對話輪數，實務上個位數；為了不做遞迴查詢，
**`task_runs` 多存一個 `root_run_id`**（continuation 建立時從 parent 抄，
parent 為 root 時就是 parent 自己的 id）。多一個欄位換掉一次 recursive CTE。

**代價**：`run_branch()` 從純函式變成需要 root run 的 seq。
簽章改成 `run_branch(task, run, root_seq)`，呼叫端（`poll()` 一處）帶進去。
**保持純函式**——這一點不放棄，它有自己的測試。

**不同意的話**：本期只允許 `delivery in ('none', 'artifact')` 的卡 continuation，
其餘 resume 回 `409 CONTINUATION_DELIVERY_UNSUPPORTED`，並寫進 known limitations。

### ☑ D61 — 歷史問題的 backfill 規則（**2026-08-16 已裁決：用現行規則**）

見 [`00`](./00-execution-plan.md) §0.1。實作在 [`02`](./02-data-layer.md) §4.2。

### D62 — Continuation 重跑 dispatch 的卡片檢查

**要點頭什麼**：`enqueue_continuation()` 跳過 `dispatch()` 的①（stage、依賴、active run），
但**重跑②a（card_kind 的三條）與②（機密允許清單與存在性）**。

**為什麼**：卡片在等待期間是可以編輯的。一張釐清卡在第一輪問完問題之後，
有人替它加了 `required_secrets`——如果 continuation 不重跑那個檢查，
第二輪的 offer 就會帶著機密出去，而 `TASK_KIND_FORBIDS_SECRETS` 那條 refusal
（`runs.py:356-372`）從來沒有被繞過的痕跡。

**這是本期唯一一個「新的執行路徑可能繞過既有 refusal」的地方**，
所以它有自己的 gate：`GATE-CV-CONTINUATION-REFUSALS`（[`08`](./08-verification-and-exit.md) §3）。

**實作形狀**：把 `dispatch()` 的②a＋②抽成 `_assert_card_dispatchable(task, project)`，
`dispatch()` 與 `enqueue_continuation()` 各呼叫一次。
**抽出來而不是複製**——複製的第二份會在第三次修改時分歧。

**檢查失敗時怎麼辦**：answer 已經寫入（它是使用者說的話，不能因為卡片設定錯了就丟掉），
但 continuation 不建立，並在卡片上留一則 `system` 訊息說明
「已收到你的回覆，但因為以下原因無法繼續：…」。**使用者的字不會不見**是這裡的紅線。

> **實作修訂（2026-08-16）**：原本寫「回 `409`」。實作時改成 **HTTP 201 ＋
> `mode="refused"` ＋ `refusal_code`**。兩個理由：一是「先 commit 再 raise」的交易狀態
> 很脆弱；二是**回應碼會說謊**——answer 確實建立了，回 409 說的是「你的請求失敗了」，
> 而 body 還要接一句「不過我們存下來了」。201 是誠實的那個碼，
> 拒絕的資訊放在 `mode` 裡。

### D63 — `kind` 的值域擴充採讀取相容映射，不做 `UPDATE`

**要點頭什麼**：`message` → 讀成 `comment`、`event` → 讀成 `system`，
新程式只寫新值，**不對既有列做 `UPDATE`**。

**為什麼**：那張表被 `activity_events` 與 audit 間接引用，
一次全表 `UPDATE` 會改掉 `updated_at`-like 的推導基準，也會讓 backfill 與
`GATE-CV-APPEND-ONLY` 打架（gate 說這張表沒有 UPDATE 路徑，migration 卻做了一次）。
**兩行讀取映射永遠正確，而且成本是零。**

映射寫在**一處**：`schemas.py` 的 DTO 組裝。服務層與資料庫保持原值。

### D64 — `--since` 保留一版並標 deprecated

**要點頭什麼**：`GET /api/tasks/{id}/messages?since=` 與
`GET /api/cli/runs/messages?since=` 保留，回應 header 加
`Deprecation: true` 與 `Sunset`；CLI 的 `--since` 印一行 stderr 提示。
`alpha.3` 移除。

**為什麼不立刻移除**：`cliora task messages --since` 可能已經寫進某些 Agent 的
prompt 或 wrapper script 裡；而 `render_run_context`（`runs.py:1490-1500`）
印給 Agent 看的那段說明**只列了 `say`／`ask`／`attach`**，沒有 `messages`
——所以風險低但不是零。一版的窗口是便宜的保險。

**要一起接受的**：兩條查詢路徑要並存一版，
且 `since` 與 `after_seq` 同時給 → `400 INVALID_ARGUMENT`（不猜使用者要哪個）。

### ☑ D67 — 一般留言在「提問的 run 還活著」時關閉問題（**實作時發現，2026-08-16**）

**要點頭什麼**：一則人類的 `comment` 在提問的 run 仍是 `waiting_for_input` 時
關閉那個 question（但**不建立 turn**）；run 已終結時則不關閉。

**為什麼**：D42 與本節其餘部分寫的是「只有 `answer` 關閉 question」。
實作時既有測試立刻紅了，而它紅得有道理——V2.5 的規則是「任何使用者訊息都算答了」，
它存在的理由是**一個還活著的 Agent 不會因為有人沒按某個按鈕而永久失語**。

拿掉那條規則，就出現這個情境：Agent 問、人打字回、Agent 再問被 409 擋住、
沒有任何東西顯示為什麼。所以規則保留，但只保留在它原本涵蓋的情境裡。

**run 已終結時為什麼不關閉**：關了之後卡片會顯示「沒有人在等」，
而其實沒有人在做事——沒有 turn 被建立。**一張看起來閒置的卡比一張說還在等的卡更糟。**

兩條承諾都還成立：`comment` 不建立 turn（`test_a_comment_does_not_wake_an_agent`
送 20 則留言後 run 數不變），`answer` 不核准任何東西。

實作在 `ConversationService._close_questions_a_live_run_is_waiting_on`。

### ★ D65 — 第四個 renderer，gate 的形狀不變（**待裁決，B 類**）

見 [`00`](./00-execution-plan.md) §0.2 與 [`05`](./05-context-pack-and-runner.md) §2。

### ★ D66 — 兩種等待都保留，但只有一個投影（**待裁決，B 類**）

見 [`00`](./00-execution-plan.md) §0.2 與 [`04`](./04-answer-resume-and-turns.md) §3。

---

## 3. 治理

### 3.1 紅線（本期一條都不動）

| 紅線 | 本期的關係 |
|---|---|
| 互動式 Session 與 Agent Run 是兩條生命週期 | 不動。continuation 是 Agent Run 的第二個實例，不是 session |
| Agent 不冒充 human actor | **本期加強**：`decision` 這個 kind 由 run token 寫入 → `403` ＋ audit |
| Agent 不能自動核准、自動合併、自動部署 | 不動。`proposal` 不改 readiness、不動 gate |
| Agent Run 不接觸使用者 allowed workspace | 不動。本期不碰 `daemon/internal/workspace` |
| Agent 產出只落在人看過才生效的位置 | 不動。`proposal` 是提案欄位 |
| Project × Agent 不建立固定綁定 | 不動。continuation 走同一個 tag 比對，**可能被另一台機器接走**——這是刻意的 |
| `v2` → `dev` 由人工確認 | 不動 |

> **「continuation 可能被另一台機器接走」值得單獨說一句。** `_eligible()` 的註解
> 已經寫明沒有 `project_agents`、tag 決定機器、`ORDER BY queued_at` 是唯一排序。
> continuation 不打破它：第二輪可能落在不同 runner 上。
> **這正是「conversation 是持久的、execution 是可替換的」的具體樣子**，
> 而它能成立的前提是情境包帶得夠（[`05`](./05-context-pack-and-runner.md) §3）。

### 3.2 RBAC（不新增動作）

| 新能力 | 需要 |
|---|---|
| 讀 conversation、questions | `project.view` |
| 發 `comment`／`question`／`answer` | `task.update` |
| 觸發 resume | `task.update` |
| 寫 `decision`（接受／拒絕 proposal） | **`task.approve`** |

`task.approve` 從來不在 `RUN_TOKEN_SCOPES` 裡（`agent_auth.py:70`），
所以「Agent 不能 decide」在授權層就是真的，不必靠一條 `if`。
**但仍然加那條 `if`**，因為它能回一個看得懂的 `AGENT_CANNOT_DECIDE`
而不是一個泛用的 403，而且它有 audit。

### 3.3 `AGENT_FORBIDDEN_FIELDS` 的擴充

現況（`agent_auth.py:81-83`）：

```python
{"gates", "owner_user_id", "assigned_runner_id", "required_secrets", "card_kind"}
```

本期**不加**。`is_blocked`／`blocking_reason` 是 `beta.1` 才有的欄位，
到那時再加（`research/03` [`08`](../../research/03/08-data-model-and-contract.md) §6.2 已記）。

這一節保留在計畫裡，是為了讓「本期為什麼沒動這個集合」查得到出處。

### 3.4 Audit

| 事件 | 記 | 不記 |
|---|---|---|
| message 建立 | actor、kind、task、`conversation_seq` | **body** |
| answer ＋ resume | question id、continuation run id、mode（`new_turn`／`live_run`） | answer 內容 |
| `decision` | actor、proposal id、結果 | proposal 全文 |
| Agent 嘗試 `decision` 被拒 | actor、task、run id | — |
| question 逾時 | question id、等待時數 | question 內容 |

既有的 `TASK_MESSAGE_POSTED` activity（`runs.py:1324-1332`）payload 已經只有
`{card_ref, kind}`——**已經合規**，本期只加 `conversation_seq`。

### 3.5 保留、附件與大小（D51 的落地）

| 項目 | 決定 |
|---|---|
| message 保留期 | **永久**。它是產品資料；`run_logs` 才是有 `logs_expire_at` 的診斷資料 |
| body 上限 | 維持 **20000 字元**（`schemas.py:1809`），但改回 `400 MESSAGE_TOO_LARGE` 而不是 Pydantic 的 422 |
| 附件 | **本期不新增路徑**。既有 `POST /api/tasks/{id}/artifacts` 已經支援 `message`，並回填 `task_artifacts.message_id` |
| 匯出 | 延後到 `beta.2` |
| Project 刪除 | 既有 `ON DELETE CASCADE` 已經涵蓋（`task_messages.task_id` → `tasks` → `projects`） |
| Secret redaction | 沿用既有 runner 端 redaction；**Central 端在 message POST 也要跑一次**，因為 Agent 可以把機密值打進 `say` 的 body |

> 最後一列是本期新增的一條防線。既有的 redactor 包在 daemon 的 `send` 外面
> （`run_handlers.go:218-229`），管的是 `run.failed` 的 stderr 與 `run.complete` 的 summary。
> **`cliora task say` 走的是 HTTPS，不經過那個 redactor。**
> 所以 Central 端要對 message body 跑一次同樣的比對——用該 run 已下放的機密值集合。
