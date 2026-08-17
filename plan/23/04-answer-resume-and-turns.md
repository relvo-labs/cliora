# 04 — Answer、Resume 與 Turn（`CV-05`、`CV-06`、`CV-07`、`CV-13`）

**本期的核心。** 前三節是三個獨立但互相咬合的改動，第四節之後是它們的後果。

## 1. Answer ＋ resume 的單一交易（`CV-05`）

```text
POST /api/tasks/{taskId}/questions/{questionId}/answer
{ "body": "用 SAML 2.0，IdP 是 Okta", "resume": true, "idempotency_key": "..." }
```

`task.update`。一個交易，五個步驟，**順序固定**：

```python
async def answer(self, *, task, question_id, body, resume, actor, idempotency_key):
    # ① CAS —— 單列，影響 0 列就是衝突
    updated = await session.execute(
        update(TaskQuestion)
        .where(TaskQuestion.id == question_id,
               TaskQuestion.task_id == task.id,
               TaskQuestion.state == "open")
        .values(state="answered", answered_at=now_utc())
        .returning(TaskQuestion.run_id))
    row = updated.first()
    if row is None:
        raise self._explain_cas_failure(question_id)   # 409，見 §1.2

    # ② 訊息（走 CV-04 的冪等路徑，同一交易）
    message = await self._messages.post(
        task=task, body=body, kind="answer", author_kind=ACTOR_USER,
        author_user_id=actor.id, question_id=question_id,
        reply_to_message_id=question.asked_message_id,
        idempotency_key=idempotency_key)
    await session.execute(update(TaskQuestion)
        .where(TaskQuestion.id == question_id)
        .values(answered_message_id=message.id))

    # ③ 續跑（三條分支，見 §1.3）
    outcome = await self._resume(task, question, message) if resume else _NO_RESUME

    # ④ 投影
    await self._reproject(task)

    # ⑤ audit（metadata only）
    await self._audit.record(CONVERSATION_ANSWERED, ...)
    return AnswerResult(message=message, **outcome)
```

**為什麼一個交易而不是兩個 endpoint**：拆了就存在「answer 已保存但 continuation 沒建立」
這個狀態，而它在 UI 上長得跟「Agent 還沒回」一模一樣。
使用者會等，然後再送一次，然後有兩個 turn。

### 1.1 為什麼 CAS 在最前面

`UPDATE … WHERE state='open'` 是整個併發正確性的**全部**。
它與 `claim()`（`runs.py:1396-1430`）是同一個形狀，而 `claim()` 的 docstring
已經把理由寫得很好：「競態在單一敘述之內解決，所以窗口不是被縮小而是被關閉」。

把它放在最前面，是因為後面每一步都要花錢（寫訊息、建 run、寫 audit），
而輸掉競態的那個請求應該在花錢之前就知道。

### 1.2 CAS 失敗的三種原因要分開回

`rowcount == 0` 有三種可能，**回同一個錯誤是不夠的**：

```python
def _explain_cas_failure(question_id):
    q = load(question_id)
    if q is None:            → 404 QUESTION_NOT_FOUND
    if q.task_id != task.id: → 404 QUESTION_NOT_FOUND   # 不洩漏它屬於哪張卡
    if q.state == "answered":→ 409 QUESTION_ALREADY_ANSWERED
                                  details: answered_by, answered_at, answered_message_id
    else:                    → 409 QUESTION_NOT_OPEN     details: state
```

`QUESTION_ALREADY_ANSWERED` 的 details 要夠讓 UI 說出
「這題已經被陳小美在 14:32 回答了」並提供「查看那則回覆」——
E2E-J8（兩個人同時回答）的驗收標準是**輸的那一方拿到可恢復的衝突**，
不是「操作失敗」。

### 1.3 Resume 的三條分支

這是 D66 的落地：**兩種等待，同一個入口**。

```python
async def _resume(self, task, question, answer_message):
    parent = await session.get(TaskRun, question.run_id) if question.run_id else None

    # (a) 沒有 run —— 例如人主動在卡片上開的問題
    if parent is None:
        return {"mode": "no_run", "continuation_run_id": None}

    # (b) 那個 run 還活著（process 沒結束，仍在輪詢）
    if parent.status == "waiting_for_input":
        parent.status = "running"
        parent.waiting_since = None
        return {"mode": "live_run", "continuation_run_id": parent.id}

    # (c) 那個 run 已終結 —— 建 continuation
    if parent.status in ("succeeded", "failed", "cancelled"):
        child = await self._runs.enqueue_continuation(
            task=task, parent=parent,
            input_from_seq=parent.input_to_seq or _first_seq_of(parent),
            input_to_seq=answer_message.conversation_seq)
        return {"mode": "new_turn", "continuation_run_id": child.id}

    # (d) 其餘（queued/claimed/running）—— 不該發生
    raise ApiError("RUN_NOT_WAITING_FOR_INPUT", ..., 409)
```

| mode | 什麼時候 | Agent 怎麼拿到答案 | UI 顯示 |
|---|---|---|---|
| `live_run` | Agent 問完繼續輪詢（現行行為） | 它自己的 `cliora task messages --after` | 「Agent 正在讀取」 |
| `new_turn` | Agent 問完就 exit（D59 之後的建議行為） | 新 run 的情境包 ＋ CLI 拉取 | 「已排入新的一輪」 |
| `no_run` | 人對人的問題 | — | 「已回覆」 |

**(d) 是一個真的不該發生的狀態**：一個 `running` 的 run 有 open question，
表示它問完之後 Central 沒有把它轉成 `waiting_for_input`。
回 409 而不是靜默處理，因為那是我們自己的 bug，要看得見。

### 1.4 冪等

同一個 `idempotency_key` 重送：

- CAS 已經在第一次成功時把 question 關掉了，第二次會走進 `QUESTION_ALREADY_ANSWERED`。
- **但那不是我們要的**——重送應該回原結果，不是衝突。

所以 CAS 之前**先查冪等鍵**：

```python
existing = await self._messages.by_idempotency_key(task.id, idempotency_key)
if existing is not None and existing.question_id == question_id:
    return AnswerResult(message=existing, mode=_mode_of(existing), replayed=True)  # 200
```

**這是全期唯一一處「先查再寫」是對的地方**，因為衝突的處理是「回傳既有結果」
而不是「拒絕」——查漏了最壞的結果是走到 CAS 然後拿到 409，
而 409 的 details 裡有那則答案，client 仍然恢復得了。
其餘每一處（訊息寫入、continuation 建立）都靠唯一索引。

`TURN_ALREADY_QUEUED`：`task_runs` 加部分唯一索引，讓「同一個 question 建兩個 continuation」
在資料庫層不可能：

```sql
CREATE UNIQUE INDEX uq_task_runs_continuation
  ON task_runs(parent_run_id, resumed_question_id)
  WHERE parent_run_id IS NOT NULL;
```

（`resumed_question_id` 是 `task_runs` 的第 6 個新欄位——[`02`](./02-data-layer.md) §2.3 的五欄要加上它，
共 **14 欄**。這是寫 §1.4 時才發現需要的，記在這裡而不是回頭改成好像一開始就想到。）

## 2. `finish()` 推導 `awaiting_input`（`CV-07`，D59）

### 2.1 改動

`services/runs.py:1003-1046`，在 `run.status = "succeeded"` 那一行之後插入：

```python
awaiting = succeeded and await self._has_open_question(run.id)
if awaiting:
    run.result = "awaiting_input"
    # status 仍是 succeeded：這個 run 確實正常結束了。等待的是卡片，不是 run。
```

**`status` 不改成新值。** 三個理由：

1. `ACTIVE_STATUSES`、`LEASED_STATUSES`、reaper 的三個掃描、
   `active_for_task()`、前端的狀態徽章——**六處要同時懂新值**，漏一處就是一個
   「卡在某個狀態不動」的 bug。
2. 這個 run **真的**正常結束了：它做完了它那一輪，沒有失敗。
   把它標成非終結狀態是在說一件不真的事。
3. `result` 已經有 Central 端產生的值的先例（`delivery_incomplete`，`runs.py:1136`）。

### 2.2 這改變了什麼

| | 之前 | 之後 |
|---|---|---|
| Agent 問完 exit | run `succeeded`／`result='succeeded'`，對話結束 | run `succeeded`／`result='awaiting_input'`，**question 仍 open** |
| `active_for_task()` | 回 None（run 終結） | 回 None（**不變**） |
| 再次 `dispatch()` | 允許——會開一個全新的 run，情境包從頭 | 允許，但**不該這樣做**。UI 提供的是「回覆並繼續」 |
| 卡片顯示 | 「已完成」 | **「等待你的回覆」**（來自 `waiting_for_actor`） |
| 租約與 compute | 已釋放 | 已釋放（不變） |
| run token | 已撤銷（`runs.py:1031`） | 已撤銷（不變）。continuation 拿新的 |

### 2.3 一個必須跳過的既有檢查

`_record_run_outcome()`（`runs.py:1122-1140`）：

```python
if succeeded and task.delivery == "artifact":
    attached = count(artifacts of this run)
    if attached == 0:
        run.status = "failed"; run.result = "delivery_incomplete"
```

一個問完問題就 exit 的 run **當然沒有附產物**。不跳過的話，
每一輪釐清都會被標成 `delivery_incomplete` 並在卡片上留一則
「這張卡宣告以產物交付，但這次執行沒有附上任何產物」——**而那句話是錯的**，
它還沒交付是因為它在等人回答。

```python
if succeeded and not awaiting and task.delivery == "artifact":
```

`CV-12` 有一條測試：`delivery='artifact'` 的卡，run 問了問題就結束，
斷言 `result == 'awaiting_input'` 且卡片上**沒有** `run.delivery_incomplete` 事件。

### 2.4 `_record_run_outcome` 的其餘部分照跑

verification、evidence、git_state 在 `awaiting_input` 的 run 上通常是空的，
但**不特別跳過**：一個做了一半工作、附了證據、然後問問題的 run 是合法的，
它的證據應該留下。

`wants_pull_request()` 那一段會跳過，因為 `run.pushed_branch` 是空的
（沒 push 就沒 PR）。這是既有邏輯自然的結果，不必加條件。

## 3. 兩種等待，一個投影（`CV-13`，D66）

```text
情境 A：process 還活著     task_runs.status = 'waiting_for_input'
情境 B：process 已結束     task_runs.result = 'awaiting_input'（status='succeeded'）
情境 C：人對人的問題        沒有 run
```

三種情境，**同一個投影**：

```python
async def _reproject(self, task: Task) -> None:
    open_count = await count(TaskQuestion, task_id=task.id, state="open")
    task.open_question_count = open_count
    if open_count > 0:
        task.waiting_for_actor = "human"
    elif await self._has_pending_turn(task.id):     # queued/claimed/running 的 run
        task.waiting_for_actor = "agent"
    else:
        task.waiting_for_actor = None
```

**`GATE-CV-PROJECTION-ONE-WRITER`**：`waiting_for_actor` 與 `open_question_count`
的賦值點只在 `_reproject` 內。第二個寫入點的第一個漏掉的分支，
會讓看板上出現一張永遠寫著「等你回覆」但其實答完的卡，**而它不會有任何錯誤**。

`_reproject` 的呼叫點（全部在同一交易內）：

```text
question 建立      → open_count +1
answer CAS 成功    → open_count -1
question 逾期       → open_count -1（reaper）
question 取消       → open_count -1
continuation 建立   → 可能轉 'agent'
run 終結            → 可能轉 NULL
```

## 4. Reaper：從掃 run 改成掃 question（`CV-07`）

> **實作修訂（2026-08-16）**：是**兩段**掃描，不是一段。`run.progress` 的
> `waiting_for_input` 旗標可以在沒有任何 question 的情況下把 run 停在那個狀態，
> 而那種 run 沒有 question 列可掃——它會永遠佔住租約。所以
> `_expire_waiting`（掃 question）之外還有 `_expire_parked_runs`（掃沒有 question 的
> parked run）。分開而不是合併，因為它們回答的是不同問題，而一個同時做兩件事的查詢
> 會讓「是哪一種情況觸發的」看不出來。

`services/run_reaper.py:120-170` 的 `_expire_waiting()` 目前掃
`status='waiting_for_input' AND waiting_since < cutoff`。
D59 之後，情境 B 的 run 已經終結，這個掃描看不到它——**逾時就不會發生**。

改成掃 question：

```python
async def _expire_questions(self) -> None:
    cutoff = now_utc() - timedelta(hours=settings.run_waiting_timeout_hours)
    questions = select(TaskQuestion).where(
        TaskQuestion.state == "open", TaskQuestion.created_at < cutoff).limit(BATCH)
    for q in questions:
        q.state = "expired"; q.expired_at = now_utc()
        task = get(Task, q.task_id)
        # 情境 A：那個 run 還活著，照舊把它收掉
        run = get(TaskRun, q.run_id) if q.run_id else None
        if run is not None and run.status == "waiting_for_input":
            run.status = "failed"; run.result = "failed"
            run.error_code = "RUN_WAITING_TIMEOUT"
            run.finished_at = now_utc()
            run.logs_expire_at = now_utc() + timedelta(days=14)
        task.stage = "blocked"
        await messages.post_event(task=task, body=..., event_kind="run.waiting_timeout")
        await conversation._reproject(task)
        await activity.record(RUN_FINISHED if run else QUESTION_EXPIRED, ...)
```

四個保留與一個新增：

- **保留** 24 小時（`settings.run_waiting_timeout_hours`，`settings.py:193`）。
- **保留** `task.stage = "blocked"`。`beta.1` 的 D49 才處理 stage 語意，本期不動。
- **保留** 卡片上那則說明文字（使用者看到的字不變）。
- **保留** 情境 A 的 run 收尾行為（`RUN_WAITING_TIMEOUT`、14 天 log 保留）。
- **新增** question 進 `expired`，且**不刪除**——
  [`research/03/02`](../../research/03/02-phase-c1-ticket-conversation.md) §2 要求
  「過期不刪除 question，人類事後回覆仍可續跑」。

**事後回覆一個 expired question**：`state != 'open'` → `409 QUESTION_NOT_OPEN`。
UI 在這種情況提供的動作是「重新派工」而不是「回覆並繼續」——
因為那張卡已經在 `blocked`，而 continuation 需要它不在 blocked。
這是一個**已知的粗糙邊緣**，記在 [`09`](./09-open-measurements.md) 第 5 項。

## 5. `enqueue_continuation`（`CV-07`）

```python
async def enqueue_continuation(self, *, task, parent, question,
                               input_from_seq, input_to_seq) -> TaskRun:
    project = await self._session.get(Project, task.project_id)
    # D62：重跑卡片層的 refusal —— 卡片在等待期間可能被改過
    await self._assert_card_dispatchable(task, project)

    run = TaskRun(
        id=uuid.uuid4(), task_id=task.id, project_id=task.project_id,
        seq=await self._next_seq(task.id),          # 既有的 UNIQUE(task_id, seq)
        status="queued", attempt=1,
        assigned_runner_id=task.assigned_runner_id,  # 指定沿用；不創造資格
        repository_id=parent.repository_id,
        source_kind=parent.source_kind, source_ref=parent.source_ref,
        parent_run_id=parent.id,
        root_run_id=parent.root_run_id or parent.id,
        resumed_question_id=question.id,
        turn_seq=(parent.turn_seq or 1) + 1,
        input_from_seq=input_from_seq, input_to_seq=input_to_seq,
        created_by=None,                             # 系統建立，不是某個人 dispatch 的
    )
```

### 5.1 `_assert_card_dispatchable` 抽取（D62）

從 `dispatch()`（`runs.py:312-470`）抽出**②a 與 ②** 兩段：

```text
②a  card_kind 的三條：釐清／拆解卡不得帶機密、必須有 requirement、
     非 implementation 卡的 delivery 限制、mockup 卡需要 tunnel 整合
②   機密允許清單 ＋ 機密存在性
```

**不抽 ①**（stage、依賴、active run）：那三條是「現在能不能開始一輪新的工作」，
而 continuation 不是新工作。

**抽出來而不是複製。** `GATE-CV-CONTINUATION-REFUSALS` 用 AST 斷言
`dispatch()` 與 `enqueue_continuation()` 都呼叫它，且那些 refusal 的
`raise` 只出現在它裡面。複製的第二份會在第三次修改時分歧，
而分歧的方向一定是 continuation 那一份比較舊。

失敗時的處理見 [`01`](./01-decisions-and-governance.md) D62：
**answer 已寫入、不回滾**，continuation 不建立，回 409 ＋ 在卡片上留一則
`system` 訊息說明。使用者打的字不會不見。

### 5.2 分支繼承（D60）

```python
def run_branch(task: Task, run: TaskRun, root_seq: int) -> str:
    ...
    return f"cliora/{task.card_ref}-{root_seq}"
```

呼叫點只有 `poll()` 一處（`runs.py:825`），改成：

```python
root_seq = run.seq if run.root_run_id in (None, run.id) else (await root_of(run)).seq
branch=run_branch(task, run, root_seq)
```

`root_of()` 是一次 `session.get(TaskRun, run.root_run_id)`——
因為 `root_run_id` 是直接存的（[`02`](./02-data-layer.md) §2.3），不是遞迴查詢。

**`run_branch` 保持純函式**，它有自己的測試。新增兩條：
continuation 的分支等於 root 的分支；三輪之後仍然等於 root 的分支。

### 5.3 認領：完全走既有的路

continuation run 是一個普通的 `queued` run：

- `_eligible()`（`runs.py:890-956`）的五個條件照套，`ORDER BY queued_at` 不改。
- `claim()` 不改一個字（`GATE-AR-SINGLE-CLAIM` 的對象）。
- run token 在認領時發（`poll()` 裡），wall clock 重新計時。
- **可能被另一台 runner 接走**——這是刻意的（[`01`](./01-decisions-and-governance.md) §3.1）。

**不給 continuation 插隊。** 一個人在等自己的回覆被處理，而前面排著 50 張卡，
體感是差的；但改 `ORDER BY` 會打破「沒有優先權、沒有負載平衡」這個明確的姿態，
而那個姿態是 ADR 0029 寫下的。列入 [`09`](./09-open-measurements.md) 第 2 項：
**先量 P95，超過 10 秒再談。**

## 6. Cursor 與 consumer（`CV-06`）

```text
GET  /api/cli/runs/conversation/input?after_seq=      run token
POST /api/cli/runs/conversation/ack { "seq": N }      run token
```

`input` 回這一輪要讀的東西，`ack` 推進 `last_acked_seq`。

```python
# input
rows = messages where task_id = run.task_id and conversation_seq > after_seq
consumer.last_delivered_seq = max(consumer.last_delivered_seq, rows[-1].seq)
return { messages: rows, open_questions: [...], from_seq, to_seq, has_more }
```

三條語意：

1. **DB commit 是真實來源。** cursor 只是「讀到哪」的紀錄，不是佇列。
2. **at-least-once。** consumer 以 `conversation_seq` 去重——
   重複拉取同一段是安全的，因為 seq 是單調的。
3. **`last_acked_seq` 是診斷用的，不是流程控制。**
   它讓 UI 顯示 `agent_seen`，而 `agent_seen` 的 tooltip 明說
   「supervisor 已 ack，不代表模型同意內容」。
   **沒有任何流程等待 ack**——等待 ack 的流程會在 Agent 崩潰時卡住。

`CONVERSATION_CURSOR_AHEAD`：`after_seq > tasks.conversation_seq` → 409。

## 7. 失效模式對照表

寫這一節是因為這一期的錯誤幾乎都是「沒發生的事」，而那種錯誤不會有 stack trace。

| 失效 | 症狀 | 防線 |
|---|---|---|
| 同一 answer 建兩個 turn | Agent 回覆兩次、可能 push 兩次 | `uq_task_runs_continuation` ＋ CAS ＋ E2E-J8 |
| 重送產生兩則訊息 | 對話裡有兩句一樣的話 | `uq_task_messages_idem` ＋ `CV-12` 的重送 10 次測試 |
| seq 重號 | cursor 跳過一則訊息，Agent 沒讀到 | `uq_task_messages_seq` ＋ 20 併發測試 |
| answer 寫了但 turn 沒建 | 使用者等著，Agent 永遠不來 | 單一交易（§1） |
| turn 建了但 answer 沒寫 | Agent 讀不到任何新東西，空轉一輪 | 單一交易（§1） |
| `comment` 誤 resume | Agent 被無意義地叫醒 | `comment` 不經過 answer endpoint；`CV-12` 送 20 則 comment 斷言無新 turn |
| 逾時掃不到情境 B | 卡片永遠停在「等你回覆」 | §4 改掃 question ＋ `CV-12` 的逾時測試涵蓋兩種情境 |
| continuation 帶了機密 | 釐清卡拿到不該有的環境變數 | D62 ＋ `GATE-CV-CONTINUATION-REFUSALS` |
| 第二輪 push 到別的分支 | PR 指著只有一半成果的分支 | D60 ＋ `run_branch` 的兩條新測試 |
| 投影與實際不符 | 看板顯示「等你回覆」但已答完 | `GATE-CV-PROJECTION-ONE-WRITER` |
| `delivery_incomplete` 誤判 | 每輪釐清都留一則錯誤的抱怨 | §2.3 ＋ 對應測試 |
