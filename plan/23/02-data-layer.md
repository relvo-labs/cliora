# 02 — 資料層（`CV-03`）

Migration `0040_ticket_conversation`，`Revises: 0039_requirements_agent_driven`。

**全部 additive。沒有一行改寫既有資料的欄位值**——backfill 只填新欄位，
這是 downgrade 乾淨的原因，也是它與 `0033`／`0036` 不同的地方。

## 1. 一張圖

```text
tasks ──────────────┬── conversation_seq      取號用的計數器（D38）
  （+3 欄）          ├── open_question_count   投影，看板用
                    └── waiting_for_actor     投影，看板用

task_messages ──────┬── conversation_seq      單調、無洞、每卡獨立
  （+5 欄）          ├── reply_to_message_id   → task_messages
                    ├── question_id           → task_questions
                    ├── idempotency_key       冪等
                    └── turn_run_id           → task_runs（哪個 turn 寫的）

task_runs ──────────┬── parent_run_id         → task_runs（上一輪）
  （+6 欄）          ├── root_run_id           → task_runs（第一輪，D60）
                    ├── turn_seq              對話內的第幾輪
                    ├── input_from_seq        這一輪讀了哪一段對話
                    ├── input_to_seq
                    └── resumed_question_id  → task_questions（哪個回答喚醒了它）

task_questions          新表：一個問題的一生
conversation_consumers  新表：誰讀到哪裡了
```

三張表共 **14 個欄位**。規劃層（[`research/03/08`](../../research/03/08-data-model-and-contract.md) §1）
寫的是 12——差的兩個是 `root_run_id`（來自 D60，讀 `run_branch()` 之後才發現）
與 `resumed_question_id`（來自 [`04`](./04-answer-resume-and-turns.md) §1.4）。

## 2. 既有表的新欄位

### 2.1 `tasks`

```python
conversation_seq: Mapped[int] = mapped_column(
    Integer, nullable=False, default=0, server_default=text("0")
)
open_question_count: Mapped[int] = mapped_column(
    Integer, nullable=False, default=0, server_default=text("0")
)
waiting_for_actor: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

`waiting_for_actor ∈ {human, agent, NULL}`。三個值的意思：

| 值 | 什麼時候 |
|---|---|
| `human` | 有 open question 在等人回答 |
| `agent` | 有 continuation turn 排隊或執行中，人已經回答完了 |
| `NULL` | 兩者皆非 |

**這兩個投影欄的維護點只有一處**（`ConversationService._reproject`），
由 `GATE-CV-PROJECTION-ONE-WRITER` 斷言。第二個寫入點的第一個漏掉的分支
會讓看板上出現一張永遠顯示「等你回覆」但其實已經答完的卡，
**而那張卡不會有任何錯誤**。

### 2.2 `task_messages`

```python
conversation_seq: Mapped[int] = mapped_column(Integer, nullable=False)   # backfill 後才 NOT NULL
reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("task_messages.id", ondelete="SET NULL"), nullable=True
)
question_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("task_questions.id", ondelete="SET NULL"), nullable=True, use_alter=True
)
idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
turn_run_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True
)
```

三件事值得寫在這裡而不是註解裡：

**`question_id` 需要 `use_alter=True`。** 它讓外鍵圖多一個環：
`task_messages` → `task_questions` → `task_messages`（`asked_message_id`）。
`0039` 已經處理過同一件事（`feature_specs` → `task_runs` → `tasks` → `task_proposals` →
`feature_specs`），做法一樣：具名 ＋ `use_alter`，讓 SQLAlchemy 把成環的那條邊分開發。
PostgreSQL 兩種寫法都收，這只是 `create_all` 的事。

**`turn_run_id` 與既有的 `run_id` 不是同一件事。** `run_id` 是「這則訊息是哪個 run 寫的」
（人類寫的訊息它是 NULL）；`turn_run_id` 是「這則訊息被哪個 turn 讀進去了」
（人類寫的 answer 會有值）。兩個都保留，因為 `CV-06` 的 catch-up 需要後者，
而 audit 需要前者。

**三個 FK 全部 `SET NULL`，沒有一個 `CASCADE`。** 與 `task_messages.run_id` 同一個理由，
`0039` 的 docstring 已經寫過：run 的紀錄照 retention 排程回收，訊息不是。
**一則訊息不該因為寫它的 run 老化了就消失。**

### 2.3 `task_runs`

```python
parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True, use_alter=True
)
root_run_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("task_runs.id", ondelete="SET NULL"), nullable=True, use_alter=True
)
turn_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
input_from_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
input_to_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
resumed_question_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("task_questions.id", ondelete="SET NULL"), nullable=True, use_alter=True
)
```

```sql
-- 「同一個 question 只能建立一個 continuation」，在資料庫層而不是在程式裡
CREATE UNIQUE INDEX uq_task_runs_continuation
  ON task_runs(parent_run_id, resumed_question_id)
  WHERE parent_run_id IS NOT NULL;
```

`resumed_question_id` 與那個部分唯一索引是寫 [`04`](./04-answer-resume-and-turns.md) §1.4
時才發現需要的：`TURN_ALREADY_QUEUED` 若只靠程式判斷，兩個併發的 resume 會各自
看到「還沒有 continuation」然後各建一個。**這是本期最貴的一種失效**
（Agent 回覆兩次、可能 push 兩次），所以它由資料庫擋。

**`root_run_id` 是為了不做 recursive CTE。** D60 要求 continuation 沿用 root 的分支名，
而沿 `parent_run_id` 往上走需要遞迴查詢。多存一欄，建立時從 parent 抄
（parent 自己是 root 時就填 parent 的 id），查詢變成一次 `get()`。

**兩個自我參照的 FK 也成環**（自己指自己），同樣 `use_alter`。

## 3. 兩張新表

### 3.1 `task_questions`

```sql
CREATE TABLE task_questions (
  id                  UUID PRIMARY KEY,
  task_id             UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  run_id              UUID REFERENCES task_runs(id) ON DELETE SET NULL,
  asked_message_id    UUID NOT NULL REFERENCES task_messages(id) ON DELETE CASCADE,
  state               VARCHAR(16) NOT NULL,
  answered_message_id UUID REFERENCES task_messages(id) ON DELETE SET NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  answered_at         TIMESTAMPTZ,
  expired_at          TIMESTAMPTZ,
  CONSTRAINT ck_task_questions_state
    CHECK (state IN ('open','answered','cancelled','expired'))
);
CREATE INDEX ix_task_questions_open ON task_questions(task_id) WHERE state = 'open';
CREATE INDEX ix_task_questions_expiry ON task_questions(created_at) WHERE state = 'open';
```

**`asked_message_id` 是 `CASCADE`，`answered_message_id` 是 `SET NULL`。**
不對稱是刻意的：一個沒有問題本文的 question 列沒有意義（所以跟著走），
一個「答案訊息不在了但問題答過」是有意義的狀態（所以留著）。
實務上兩者都不會發生——`task_messages` 沒有刪除路徑——但約束要說得出自己的意思。

**兩個部分索引**。一張卡一生可能有幾十個問題，同時 open 的最多一個（D42）。
全索引會索引到用不上的列。第二個是給 reaper 掃逾時用的，
`WHERE state='open'` 讓它掃的是個位數而不是全表。

**`state` 用 CHECK 而不是 enum type**：與 `verification_reports.result` 同一個判準，
這是 API 契約的一部分（會出現在 DTO），不是內部狀態機。

### 3.2 `conversation_consumers`

```sql
CREATE TABLE conversation_consumers (
  task_id            UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  consumer_type      VARCHAR(16) NOT NULL,          -- run | runner
  consumer_id        UUID NOT NULL,
  last_delivered_seq INTEGER NOT NULL DEFAULT 0,
  last_acked_seq     INTEGER NOT NULL DEFAULT 0,
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, consumer_type, consumer_id),
  CONSTRAINT ck_conversation_consumers_order CHECK (last_acked_seq <= last_delivered_seq)
);
```

**`consumer_id` 沒有 FK。** 與 `tasks.assigned_runner_id` 同一個先例
（`models.py:780-782`）：consumer 可能是一個已經被 retention 清掉的 run，
而 cursor 的意義不會因此消失。**一個指向不存在 run 的 cursor 是無害的；
一個因為 run 被刪而消失的 cursor 會讓重連補拉從頭開始。**

`ck_conversation_consumers_order` 讓「acked 超前 delivered」這個無意義狀態
在資料庫層不存在。`CONVERSATION_CURSOR_AHEAD` 這個 machine code 守的是
**呼叫端送來的** cursor 超前，這條 CHECK 守的是**我們自己寫壞**。

## 4. Backfill

### 4.1 `conversation_seq`

```sql
WITH ordered AS (
  SELECT id, task_id,
         ROW_NUMBER() OVER (PARTITION BY task_id ORDER BY created_at, id) AS seq
  FROM task_messages
)
UPDATE task_messages m SET conversation_seq = ordered.seq
FROM ordered WHERE m.id = ordered.id;

UPDATE tasks t SET conversation_seq = COALESCE(
  (SELECT MAX(conversation_seq) FROM task_messages WHERE task_id = t.id), 0);
```

**`ORDER BY created_at, id` 的第二個鍵不是裝飾。** 現行的
`list_for()`（`runs.py:1278-1285`）就是 `order_by(created_at, id)`——
backfill 用同一個順序，升級前後的閱讀順序才一致。
而**同一個 `created_at` 有兩則訊息時要用 id 決勝**，正是現行 `--since` 分頁
不可靠的原因（[`README`](./README.md) 缺口 1）。這一句 SQL 是那個缺口的收尾。

Backfill 之後才加約束：

```sql
ALTER TABLE task_messages ALTER COLUMN conversation_seq SET NOT NULL;
CREATE UNIQUE INDEX uq_task_messages_seq ON task_messages(task_id, conversation_seq);
CREATE UNIQUE INDEX uq_task_messages_idem ON task_messages(task_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_task_messages_task_seq ON task_messages(task_id, conversation_seq DESC);
```

`ix_task_messages_task_seq` 是**降序**：讀對話最常見的查詢是「最後 50 則」，
而 cursor 分頁的 `WHERE conversation_seq > ?` 用升序掃同一棵樹一樣快。

### 4.2 `task_questions`（D61，2026-08-16 已裁決）

對每一則 `kind='question'` 的歷史訊息建一列。是否已答，用**現行規則**判定
——那條規則在 `runs.py:1331-1365` 的 docstring 裡有三段說明，這裡照抄它的判準：

```sql
INSERT INTO task_questions (id, task_id, run_id, asked_message_id, state,
                            answered_message_id, created_at, answered_at)
SELECT gen_random_uuid(), q.task_id, q.run_id, q.id,
       CASE WHEN a.id IS NULL THEN 'open' ELSE 'answered' END,
       a.id, q.created_at, a.created_at
FROM task_messages q
LEFT JOIN LATERAL (
  SELECT m.id, m.created_at FROM task_messages m
  WHERE m.task_id = q.task_id
    AND m.author_kind = 'user'          -- 「任何使用者訊息都算」
    AND m.created_at > q.created_at     -- 「時間在問題之後」
  ORDER BY m.created_at, m.id LIMIT 1
) a ON TRUE
WHERE q.kind = 'question';
```

三個要注意的地方：

1. **`author_kind = 'user'`，不是 `kind = 'answer'`。** 現行規則的第二段明說：
   「人是用打字回覆的，不是用按一個有標籤的按鈕」。換規則會讓一張卡在升級前後
   對「這題答了沒」給出不同答案。
2. **系統訊息不算。** 現行規則的第三段：否則 24 小時逾時通知本身就會解鎖提問，
   而那正好是反的。上面的 `author_kind = 'user'` 已經排除它。
3. **一則使用者訊息可以同時答掉兩個歷史問題。** `answered_message_id` **沒有唯一約束**，
   這是允許的。

Backfill 完之後回填 `task_messages.question_id`（answer 那一側）與
`tasks.open_question_count`／`waiting_for_actor`：

```sql
UPDATE task_messages m SET question_id = q.id
FROM task_questions q WHERE q.answered_message_id = m.id;

UPDATE tasks t SET
  open_question_count = COALESCE((SELECT COUNT(*) FROM task_questions
                                  WHERE task_id = t.id AND state = 'open'), 0),
  waiting_for_actor = CASE WHEN EXISTS (SELECT 1 FROM task_questions
                                        WHERE task_id = t.id AND state = 'open')
                           THEN 'human' ELSE NULL END;
```

### 4.3 `task_runs.root_run_id`

既有 run 全部是 root：`UPDATE task_runs SET root_run_id = id;`
（`turn_seq` 的 `server_default` 已經是 1，不必動。）

## 5. Downgrade

```text
drop conversation_consumers
drop task_questions            （task_messages.question_id 的 FK 先 drop）
drop task_runs 的 5 欄
drop task_messages 的 5 欄與 3 個索引
drop tasks 的 3 欄
```

**backfill 出來的 `conversation_seq` 不可還原**——但它是新欄位，
drop 掉就沒有了，所以 downgrade 仍然是乾淨的。
`GATE-CV-MIGRATION-ROUNDTRIP` 斷言降回 `0039` 之後 schema 與基線逐位元組相同
（沿用 `plan/22` 的實作，只換降級目標）。

## 6. 索引清單與它們各自要服務的查詢

| 索引 | 服務的查詢 | 出現在 |
|---|---|---|
| `uq_task_messages_seq` | 取號正確性的最後一道防線 | 併發測試 |
| `uq_task_messages_idem` | 冪等：同 key 第二次寫入撞唯一鍵 | `CV-04` |
| `ix_task_messages_task_seq` | `?after_seq=` 的 cursor 分頁、最後 N 則 | `CV-04`、`CV-06` |
| `ix_task_questions_open` | 「這張卡有沒有未決問題」、投影維護 | `CV-05`、`CV-13` |
| `ix_task_questions_expiry` | reaper 的逾時掃描 | `CV-07` |
| `ix_task_runs_parent`（部分） | 「這條對話有哪些 turn」 | `CV-06`、UI |

```sql
CREATE INDEX ix_task_runs_parent ON task_runs(parent_run_id) WHERE parent_run_id IS NOT NULL;
```

## 7. 這個 migration 不做的事

| 不做 | 為什麼 |
|---|---|
| 不 `UPDATE task_messages.kind` 的既有值 | D63：讀取映射永遠正確，而全表 UPDATE 會跟 `GATE-CV-APPEND-ONLY` 打架 |
| 不加 `task_messages.deleted_at` | 訊息沒有刪除路徑（D43）。加一個沒有寫入者的欄位是在邀請第一個寫入者 |
| 不加 `task_messages.edited_at` | 本期不提供編輯。`beta.1` 若提供，走 revision 表而不是就地欄位 |
| 不加 attachment 相關欄位 | D51：沿用既有 `task_artifacts.message_id` |
| 不加 `tasks.attention_*` | 那是 `beta.1`（`0043`）的事 |
| 不動 `run_logs` 與 `logs_expire_at` | 本期的整個重點就是這兩者與 conversation 無關 |
