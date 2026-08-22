
# 03 — Conversation API（`CV-04`）

## 1. 現況與改動範圍

四條既有路由，兩條人類的、兩條 run token 的：

```text
GET  /api/tasks/{id}/messages?since=&limit=      agents.py:511   project.view
POST /api/tasks/{id}/messages                    agents.py:526   task.update
GET  /api/cli/runs/messages?since=               agents.py:769   run token
POST /api/cli/runs/messages                      agents.py:786   run token
```

四條都保留、都擴充，**沒有一條被取代**。新增五條，全部與 question／turn 有關
（其中三條在 [`04`](./04-answer-resume-and-turns.md)）。

服務層：`MessageService`（`services/runs.py:1270-1394`）擴充；
新增 `ConversationService`（`services/conversation.py`），承載取號、冪等、
question 狀態與投影維護。

> **為什麼不把 `MessageService` 整個搬走**：它現在的四個方法有三個
> （`post_event`、`pending_question`、`_require_no_pending_question`）
> 被 `RunService` 與 reaper 直接呼叫。搬家會讓這一期的 diff 裡混進一堆與
> conversation 無關的 import 變動，而 review 這一期最需要看清楚的是**新增的那些**。
> `ConversationService` 只承載新東西，`MessageService` 保留並瘦身。

## 2. 六種 kind

| 值 | 誰能寫 | 續跑 | 核准 | 資料庫存什麼 |
|---|---|---:|---:|---|
| `comment` | human ＋ runner | 否 | 否 | `comment`（新寫入）／`message`（既有列） |
| `question` | human ＋ runner | 依 target | 否 | `question` |
| `answer` | human ＋ runner | **是**（`resume=true` 且該 question open） | 否 | `answer` |
| `proposal` | **runner only** | 否 | 否 | `proposal` |
| `decision` | **human only**，需 `task.approve` | **否**（見下） | 僅對該 proposal | `decision` |
| `system` | 系統 only | 否 | 否 | `system`（新寫入）／`event`（既有列） |

> **`decision` 的續跑欄原本寫「依 decision」，那是錯的**（2026-08-21，`CE-18`）。
> 實作裡 `decision` 只有兩個出現點——常數與權限檢查——**沒有任何路徑替它建 continuation**，
> 只有 `answer` 會。ADR 0035 的狀態機畫了 `SpecProposed → Clarifying: 人類要求修改` 那條邊，
> 而今天那條邊由**人重新派工**走完；`plan/24` 的 J1a 就是這樣寫的，因為那是唯一走得通的路。
> 要不要自動續跑是一個產品決定（理由還沒寫完就開始跑？`input_from_seq` 從哪算？），
> 記在 `alpha.2` 的 known limitations 與 `beta.1` 的計畫裡。

讀取映射（D63）在 DTO 組裝的**一處**：

```python
_KIND_READ = {"message": "comment", "event": "system"}
def _read_kind(stored: str) -> str: return _KIND_READ.get(stored, stored)
```

寫入驗證取代 `runs.py:1299` 現行的那個集合：

```python
_WRITABLE_HUMAN  = {"comment", "question", "answer", "decision"}
_WRITABLE_RUNNER = {"comment", "question", "answer", "proposal"}
# system 兩邊都不在：只有 post_event() 寫得到
```

**`decision` 由 run token 寫入 → `403 AGENT_CANNOT_DECIDE` ＋ audit。**
不是 400，因為那是授權問題不是格式問題；不是靜默忽略，因為要留下痕跡。

## 3. Cursor 分頁

```text
GET /api/tasks/{id}/messages?after_seq=<int>&limit=<1..500>
GET /api/tasks/{id}/messages?before_seq=<int>&limit=<1..500>   往回讀（UI 的向上捲動）
GET /api/tasks/{id}/messages?since=<ts>                        deprecated（D64）
```

三條規則：

1. **`after_seq` 與 `since` 同時給 → `400 INVALID_ARGUMENT`。** 不猜。
2. **`after_seq > tasks.conversation_seq` → `409 CONVERSATION_CURSOR_AHEAD`。**
   呼叫端的狀態壞了（例如換了資料庫、或 client 存了別張卡的 cursor），
   回空陣列會讓它永遠停在那裡而不知道為什麼。
3. 回應帶 `next_after_seq`（本頁最後一則的 seq）與 `has_more`。
   **`has_more` 從第一版就在**，與 `BoardDTO.has_more` 同一個理由：
   之後加東西不必讓每個既有 client 處理它的缺席。

`since` 的回應加 header：

```text
Deprecation: true
Sunset: <alpha.3 的預定日期>
Link: </api/tasks/{id}/messages?after_seq=0>; rel="successor-version"
```

## 4. 冪等寫入

```text
POST /api/tasks/{id}/messages
{ "body": "...", "kind": "comment", "reply_to_message_id": "...", "idempotency_key": "..." }
```

`idempotency_key` **選填**。給了就走冪等路徑：

| 情況 | 回應 |
|---|---|
| key 未用過 | `201` ＋ 新訊息 |
| key 用過，`body` ＋ `kind` ＋ `reply_to` 完全相同 | **`200`** ＋ **原訊息**（不是 201） |
| key 用過，內容不同 | `409 MESSAGE_IDEMPOTENCY_CONFLICT`，details 帶原訊息的 `conversation_seq` |

實作**靠唯一索引，不靠先查再寫**：

```python
try:
    async with session.begin_nested():
        message = await self._insert(...)
except IntegrityError as exc:
    if not _is_unique_violation(exc, "uq_task_messages_idem"):
        raise
    existing = await self._by_idempotency_key(task_id, key)
    if _same_content(existing, body, kind, reply_to):
        return existing, 200
    raise ApiError("MESSAGE_IDEMPOTENCY_CONFLICT", ..., status.HTTP_409_CONFLICT)
```

**先查再寫在兩個請求同時到達時會雙寫。** 這與 kintra 的
`search_documents` 選擇 `INSERT … ON CONFLICT` 而不是「先查再決定」是同一條理由，
[`research/03/01`](../../research/03/01-architecture-decisions.md) §1.9 已經記過。

`_same_content` **不比對 `idempotency_key` 以外的 metadata**（actor、時間）：
同一個 client 重送同一件事，actor 一定一樣；比對它只會製造假衝突。

## 5. 取號（D38）

```python
async def _next_seq(self, task_id: uuid.UUID) -> int:
    row = await self._session.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(conversation_seq=Task.conversation_seq + 1)
        .returning(Task.conversation_seq)
    )
    return int(row.scalar_one())
```

**在同一個交易裡取號並 INSERT。** 這條 `UPDATE` 取得卡片列的行鎖，
於是同一張卡的兩個併發寫入被序列化，而不同卡片互不影響。

`uq_task_messages_seq` 是**最後一道防線**而不是機制：
如果哪天有人在別的地方自己 `INSERT`，撞唯一鍵會失敗，而不是靜默產生重號。
`CV-12` 有一條 20 併發寫同一張卡的測試，斷言 seq 是 1..20 恰好一次。

## 6. `reply_to_message_id`

- 必須指向**同一張卡**的訊息 → 否則 `400 INVALID_ARGUMENT`。
  跨卡片引用會讓對話樹跨出 Ticket 邊界，而權限是以 Ticket 為單位判的。
- **不檢查深度、不禁止環**：`A reply_to B` 且 `B reply_to A` 在寫入順序上不可能
  （B 寫入時 A 還不存在）。
- UI 只渲染一層引用（引用的那一則的前 N 字），不做樹狀。

## 7. Question 的建立

`kind='question'` 的寫入在同一交易裡多做兩件事：

```text
INSERT task_questions (state='open', asked_message_id=<新訊息>, run_id=<若有>)
_reproject(task)        → open_question_count += 1, waiting_for_actor = 'human'
```

「一個 run 一個未答問題」（D42）的檢查從
`_require_no_pending_question`（掃訊息）改成**查 `task_questions`**：

```python
existing = await session.scalar(
    select(TaskQuestion.id).where(
        TaskQuestion.run_id == run_id, TaskQuestion.state == "open").limit(1))
if existing: raise ApiError("QUESTION_ALREADY_PENDING", ...)
```

錯誤碼、訊息與 `details` **一字不改**（`runs.py:1373-1384`）——
CLI 的本地提示（`cli.go:540-557`）比對的是那段文字的行為，
而使用者看到的字沒有理由因為底層換了查詢就變。

> **`pending_question()` 這個方法保留但改實作**：它同時被 CLI 的
> `PendingQuestion()` 走的路由用到。回傳型別從 `TaskMessage | None` 改成
> `TaskQuestion | None` 會讓 `cli.go` 也要改——所以**回傳 `TaskMessage`**
> （question 的 asked message），介面不變。

## 8. 九個 machine code

| code | HTTP | 什麼時候 | 訊息要包含 |
|---|---:|---|---|
| `QUESTION_ALREADY_PENDING` | 409 | 這個 run 已有未答問題（既有） | 待答問題的本文與提問時間 |
| `QUESTION_ALREADY_ANSWERED` | 409 | 回答一個已答的 question | 誰在什麼時候答的 |
| `QUESTION_NOT_OPEN` | 409 | 回答 cancelled／expired 的 question | 目前狀態 |
| `RUN_NOT_WAITING_FOR_INPUT` | 409 | 對沒有在等的 run 要求 resume | run 目前狀態 |
| `CONVERSATION_CURSOR_AHEAD` | 409 | cursor > 目前 seq | 目前 seq |
| `MESSAGE_IDEMPOTENCY_CONFLICT` | 409 | 同 key 不同內容 | 原訊息的 seq |
| `TURN_ALREADY_QUEUED` | 409 | 該 question 已建立過 continuation | 那個 run 的 id |
| `MESSAGE_TOO_LARGE` | 400 | body > 20000 | 上限與實際長度 |
| `AGENT_CANNOT_DECIDE` | 403 | run token 寫 `decision` | 「decision 是人類動作」 |

全部註冊到 `api/error_catalog.py`。`MESSAGE_TOO_LARGE` 取代目前 Pydantic
`max_length=20000` 產生的 422——**422 沒有 machine code，前端無法分辨它與其他驗證錯誤**。
做法：Pydantic 的上限放寬到 24000（留餘裕），服務層在 20000 處明確拒絕。

## 9. DTO

```python
class TaskMessageDTO(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    run_id: uuid.UUID | None
    conversation_seq: int                    # 🆕
    author_kind: str
    author_user_id: uuid.UUID | None
    author_name: str | None
    author_runner_id: uuid.UUID | None
    author_runner_name: str | None           # 🆕 UI 要顯示「runner-03」而不是 uuid
    body: str
    kind: str                                # 讀取映射後的值
    event_kind: str | None
    reply_to_message_id: uuid.UUID | None    # 🆕
    question_id: uuid.UUID | None            # 🆕
    question_state: str | None               # 🆕 冗餘，省一次查詢
    created_at: datetime

class TaskQuestionDTO(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    run_id: uuid.UUID | None
    asked_message_id: uuid.UUID
    state: str
    answered_message_id: uuid.UUID | None
    created_at: datetime
    answered_at: datetime | None
    expired_at: datetime | None

class MessagePageDTO(BaseModel):
    items: list[TaskMessageDTO]
    next_after_seq: int | None
    has_more: bool
```

**`GET /messages` 的回應型別從 `list[TaskMessageDTO]` 改成 `MessagePageDTO`
是一個破壞性變更。** 兩個既有消費者：`frontend/src/api/client.ts:1110` 與
`daemon/internal/cli/cli.go:561`。兩邊都在本期改（`CV-08`／`CV-10`），
而**沒有第三個消費者**——`GATE-CV-NO-THIRD-CONSUMER` 用 grep 斷言。

> 這是本期唯一一個 API 破壞性變更，所以它值得一句解釋：
> 加一個 `?paged=true` 旗標可以避免它，但那會讓兩種回應形狀永久並存，
> 而這條路由的消費者恰好只有兩個、兩個都在這個 repo 裡、兩個都在本期要改。
> **能一次改乾淨的破壞性變更，比一個永久的相容旗標便宜。**

## 10. Central 端的 secret redaction（[`01`](./01-decisions-and-governance.md) §3.5）

`cliora task say` 走 HTTPS，**不經過 daemon 的 redactor**
（`run_handlers.go:218-229` 那個只包 protocol 的 `send`）。
所以 run token 寫入的 message body 要在 Central 端跑一次比對：

```python
if principal.kind == KIND_RUN and principal.run_id:
    body = await SecretService(...).redact_for_run(principal.run_id, body)
```

用該 run 已下放的機密值集合做字面比對，命中就換成 `[redacted:<NAME>]`。
**在寫入前做，不是在讀出時做**——寫進去就等於存下來了。

`CV-12` 有一條測試：下放一個機密給 run，run 用 `say` 把值送上來，
斷言資料庫裡那一列不含該值、且含 `[redacted:`。
