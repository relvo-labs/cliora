# 02 — 資料層（`TK-02`）

三支 migration。沿用 `PJ-02` 的紀律：**沒有任何既有欄位被改變型別、可空性或預設值**，
新增的欄一律 nullable 或帶 server default。

| Migration | 內容 |
|---|---|
| `0023_task_board` | 六張新表 ＋ 三個既有表的新增欄 |
| `0024_session_tokens` | `session_tokens` 一張表 |
| `0025_seed_task_actions` | `task.create`／`task.update`／`task.approve` 的角色種子 |

**seed 獨立一支**，沿用 `0022_seed_project_actions` 的既有慣例：schema 遷移與資料遷移
分開，回滾時可以只退一邊。

## 1. `0023` 的新表

### 1.1 `process_definitions`

```text
id            UUID PK
key           VARCHAR(64)   ← 'default'，UNIQUE
version       VARCHAR(32)   ← 內容版本號，例如 '2026.08-1'
source        VARCHAR(64)   ← 'monstrare'（出處標註，MIT）
lanes         JSONB         ← 六車道：{stage, label_zh, wip_suggested, order}
readiness     JSONB         ← DoR 七項：{key, label_zh, hint}
gates         JSONB         ← 六關卡：{key, label_zh, requires_human: true, depends_on_integration?}
templates     JSONB         ← Task／規格建立表單的欄位與提示文字
created_at
```

三個設計說明：

- **`version` 是內容版本號，不是流水號。** 它會變成投影目錄的名字
  （`.cliora/process/<version>/`），所以它必須在內容改變時改變、在內容相同時穩定
  （`05-…md` §4.2）。
- **`key` 現在只會有一列 `default`。** D15 裁決 V2.1 全域寫死不可覆寫。
  建 `key` 這一欄而不是直接假設單列，是因為 V2.4 的最小可覆寫版本要用它，
  而那時加一欄要回頭改所有讀取點。
- **`gates` 的每一項都有 `requires_human: true`。** 它現在是常數，但寫成資料是刻意的：
  它是「Agent 輸出不等於核准」在資料層的形式，而一個常數沒有地方可以被指著看。

### 1.2 `epics` 與 `user_stories`

```text
epics:         id / project_id FK / card_ref / title / description / order_index
               / status(active|done|archived) / created_by / created_at / updated_at
user_stories:  id / project_id FK / epic_id FK NULL / card_ref / title / narrative
               / order_index / status / created_by / created_at / updated_at
```

- `user_stories.epic_id` **nullable**：一個還沒歸到 Epic 的 US 是合法的中間狀態。
- `UNIQUE (project_id, card_ref)` 各一條。
- `ON DELETE`：`epics.project_id` CASCADE（Project 沒有刪除端點，這是安全網）；
  `user_stories.epic_id` **SET NULL**——Epic 被封存或誤刪時 US 落回未分類，不消失。

### 1.3 `tasks`

欄位取自 `research/02/08` §2 的清單，逐欄的本地決定如下：

```text
id                  UUID PK
project_id          FK projects(id) ON DELETE CASCADE
epic_id             FK epics(id) ON DELETE SET NULL          NULL
user_story_id       FK user_stories(id) ON DELETE SET NULL   NULL  ← 未分類桶（D4）
card_ref            VARCHAR(32)   ← 'TASK-12'，UNIQUE(project_id, card_ref)
title               VARCHAR(200)
description         TEXT NULL
objective           TEXT NULL
scope               TEXT NULL
non_goals           TEXT NULL
stage               VARCHAR(16)   ← 六值，CHECK 約束
risk                VARCHAR(16)   ← low|medium|high|critical
priority            VARCHAR(16)   ← low|normal|high
owner_user_id       FK users(id) ON DELETE SET NULL NULL
assigned_runner_id  UUID NULL     ← V2.2 才有 agent_runners 表，本期**無 FK**
required_labels     JSONB default '[]'
readiness           JSONB default '{}'   ← 七項 boolean
gates               JSONB default '{}'   ← 六項 {approved_by, approved_at}
acceptance_criteria JSONB default '[]'   ← [{id, text, result}]
links               JSONB default '{}'
version             INTEGER NOT NULL default 1   ← 樂觀鎖
-- 執行設定（D11：建欄不接行為）
source              VARCHAR(16) NOT NULL default 'repo'    ← none|repo|existing_branch
repository_id       UUID NULL     ← V2.3 的 project_repositories，本期**無 FK**
base_branch         VARCHAR(255) NULL
delivery            VARCHAR(16) NOT NULL default 'pull_request'
target_branch       VARCHAR(255) NULL
existing_pr_ref     VARCHAR(255) NULL
required_secrets    JSONB default '[]'
-- 來源可追溯（TK-05）
requirement_id      UUID NULL FK requirements(id) ON DELETE SET NULL
proposal_id         UUID NULL FK task_proposals(id) ON DELETE SET NULL
created_by / created_at / updated_at
```

四個要點：

- **`assigned_runner_id` 與 `repository_id` 本期沒有外鍵。** 目標表要到 V2.2／V2.3 才存在，
  而 `activity_events.task_id` 已經替這個做法留了前例（`0021` 的註解：
  「`task_id` points at a table V2.1 creates」）。V2.2／V2.3 各補一次 `ADD CONSTRAINT`。
- **`stage` 用 CHECK 而不是 enum type。** 沿用既有表的做法（`terminal_sessions.status`
  也是 `String` ＋ 服務層狀態機）；PostgreSQL enum 的 `ALTER TYPE` 在 V2.4 要調整車道時
  會是一次不可回滾的遷移。
- **`acceptance_criteria` 用 JSONB 不獨立建表**（`research/02/08` §2 的判準）：
  隨 Task 一起讀寫、沒有獨立查詢需求。獨立表會讓「改一行 AC」變成多列 upsert 與孤兒清理。
- **`gates` 的每一格是 `{approved_by, approved_at}` 而不是 boolean。**
  這是 D10 的完整性錨點在資料層的形式：那一格永遠有一個人類 `user_id`。

索引：

```sql
CREATE INDEX ix_tasks_project_stage ON tasks (project_id, stage, updated_at DESC);
CREATE INDEX ix_tasks_project_story ON tasks (project_id, user_story_id);
-- 看板與藍圖各一條；沒有第三條，因為本期沒有第三種查詢形狀。
```

### 1.4 `task_dependencies`

```text
task_id            FK tasks(id) ON DELETE CASCADE
depends_on_task_id FK tasks(id) ON DELETE CASCADE
created_by / created_at
PRIMARY KEY (task_id, depends_on_task_id)
CHECK (task_id <> depends_on_task_id)
```

**循環偵測在服務層，用一次遞迴 CTE**（`03-…md` §3.4）。不做觸發器：
一條 `WITH RECURSIVE` 走訪在專案內卡數量級是百的規模下是微秒級的，
而觸發器會讓「為什麼這次 INSERT 失敗」的錯誤訊息離呼叫端很遠。

### 1.5 `requirements`／`feature_specs`／`task_proposals`（`TK-05` 用）

```text
requirements:    id / project_id FK / card_ref / raw_text(TEXT) ← 就是那一句模糊的話
                 / status(intake|clarifying|specified|approved|rejected)
                 / created_by / created_at / updated_at

feature_specs:   id / requirement_id FK / seq INTEGER          ← 版本列，只 INSERT
                 / objective / scope / non_goals / acceptance_criteria JSONB
                 / open_questions JSONB   ← [{id, question, answer, resolved_as}]
                 / authored_by_kind(user|agent) / authored_by / created_at
                 UNIQUE (requirement_id, seq)

task_proposals:  id / requirement_id FK / spec_id FK / seq
                 / tree JSONB              ← Epic/US/Task 三層提案
                 / status(pending|partially_accepted|accepted|rejected)
                 / decided_by / decided_at / decision_note
                 / created_at
```

- **`feature_specs` 只 INSERT 不 UPDATE**，與 D9 對執行計畫的處置同一個形狀：
  「第 N 版 vs 第 N-1 版」的比較需要歷史，而規格被改過是最需要留痕的事。
- **`open_questions` 是 JSONB 不是表**：它隨規格版本一起讀寫，改一個答案就是新的一版。
- `authored_by_kind` 從第一天就有。V2.1 只會寫 `user`，但欄位存在意味著 V2.5 的
  Agent 版本不需要遷移——而且它讓「這份規格是誰寫的」在 V2.5 之前就是一個可查詢的事實。

## 2. `0023` 對既有表的新增欄

三個，全部 nullable 或帶 default：

### 2.1 `terminal_sessions.task_id`

```sql
ALTER TABLE terminal_sessions ADD COLUMN task_id UUID NULL
  REFERENCES tasks(id) ON DELETE SET NULL;
CREATE INDEX ix_terminal_sessions_task ON terminal_sessions (task_id)
  WHERE task_id IS NOT NULL;
```

`0021` 的註解已經預告了這一步（「waits for V2.1's `0023`, when `tasks` exists and it can be
a real foreign key」）。**永遠 nullable**，與 `project_id` 同一條理由。
`SET NULL` 而不是 CASCADE：Task 被封存或誤刪不該連帶抹掉一個真的跑過的 Session。

> **不建 `task_sessions` 關聯表**（偏離 `research/02/08` §2 的表列）。
> 規劃列它是為了「一張卡的歷史 Session」，但那是 `terminal_sessions.task_id` 的
> 一次索引查詢就能回答的問題。多對多在這裡沒有語意：一個 Session 只可能屬於一張卡。
> 需要時它是一張新表，不會回頭改本期任何欄位。

### 2.2 `projects.next_card_seq`

```sql
ALTER TABLE projects ADD COLUMN next_card_seq INTEGER NOT NULL DEFAULT 1;
```

配號（D5）：

```sql
UPDATE projects SET next_card_seq = next_card_seq + 1
WHERE id = :project_id RETURNING next_card_seq - 1 AS seq;
```

在同一個交易裡拿號、建卡。**行鎖是這裡唯一需要的併發控制**——
兩個同時建卡的請求會排隊，而排隊的代價是微秒。

`EPIC-`／`US-`／`TASK-` 共用同一個池，所以編號會跳號。ADR 要寫一句：
**跳號是刻意的，`card_ref` 是識別碼不是計數器。**

### 2.3 `activity_events.actor_kind`

```sql
ALTER TABLE activity_events ADD COLUMN actor_kind VARCHAR(16) NOT NULL DEFAULT 'user';
```

**這是規劃沒有的一欄**（README 差異 #7）。沒有它，時間軸上三種東西長得一模一樣：

| 情況 | `actor_user_id` | 沒有這一欄時讀者看到 |
|---|---|---|
| 人做的 | 一個 UUID | 名字 |
| 人做的、讀者沒有 `audit.view` | **被 `redact_actors` 清成 null** | 空白 |
| 系統事件 | null | 空白 |
| **Agent 做的（本期新增）** | null（不冒充人類） | **空白——與上面兩種無法區分** |

有了 `actor_kind` 之後：`user` ＋ null ＝「你需要 `audit.view`」，
`system` ＝系統，`agent` ＝ Session 的 Agent。
`redact_actors` **只清 `actor_id`／`actor_name`，不動 `actor_kind`**——
「這是 Agent 做的」不是操作者身分，它是事件的性質。

`DEFAULT 'user'` 讓既有的列不必回填：V2.0 寫進去的每一列本來就都是人做的。

### 2.4 `services/activity.py` 的新 kind

`ALL_KINDS` 是封閉詞彙，而 `test_every_activity_kind_has_a_write_site` 會對沒有寫入點的
kind 失敗。本期新增七個，每一個都要在同一張票裡接上寫入點：

```text
task.created / task.updated / task.stage_changed / task.gate_approved
epic.created / user_story.created / requirement.created
```

`task.updated` 與 `task.stage_changed` 分開，是因為看板上的讀者在掃一整欄的
「這張卡動到哪了」，而改標題與換車道對他是兩件事。

## 3. `0024` — `session_tokens`

```text
id            UUID PK
session_id    FK terminal_sessions(id) ON DELETE CASCADE
project_id    FK projects(id) ON DELETE CASCADE
token_hash    VARCHAR(128)   ← HMAC-SHA256(token_pepper, token)，UNIQUE
scopes        JSONB          ← 寫死的清單，發行時快照
issued_by     FK users(id) ON DELETE RESTRICT   ← 建立 Session 的人
issued_at / expires_at / revoked_at NULL / last_used_at NULL
```

四個要點：

- **只存 HMAC，不存值。** 沿用 enrollment token 與 node secret 的既有做法
  （`token_pepper`，ADR 0008）。查詢時對輸入算一次 HMAC 再比對，
  所以 `token_hash` 上的 UNIQUE 索引就是查詢索引。
- **`scopes` 在發行時快照。** 不是每次請求去讀一份全域設定——
  那會讓一次設定變更把已發出去的 token 的權力改掉，而 token 的整個意義是它是一枚固定的憑證。
- **`expires_at` 上限由 `CLIORA_SESSION_TOKEN_TTL_H`（預設 24）決定**，
  但**失效的第一條件是 Session 結束**（`04-…md` §3）。
- **`revoked_at` 的列保留 90 天**（D9）：稽核要能回答「那次是哪一枚 token 做的」，
  而 audit 只記 `token_id`。清理沿用 `app/retention.py` 的既有迴圈。

索引：`ix_session_tokens_session (session_id)`，用於 Session 結束時的批次撤銷。

## 4. `0025` — seed

`task.create`／`task.update`／`task.approve` 三個動作加進 Developer 與 Admin
（Viewer 一個都不拿），沿用 `0022_seed_project_actions.py` 的 JSONB 陣列更新寫法。

**同一張票（`TK-04`）內接上強制點**，`UNENFORCED_ACTIONS` 保持空集合（D6）。

## 5. 上下行演練

沿用 `scripts/pj/gate-migration-roundtrip.sh` 的既有做法（重用，不複製）：

```text
0022（V2.0 終點）→ upgrade head → pg_dump → downgrade 0022 → pg_dump
                 → 與 TK-00 的基線逐位元組比對（只允許 alembic revision 那一行不同）
```

`downgrade()` 要**逐一寫出來**，不用 `op.drop_all`：

- `0025`：把三個動作從三個角色的 JSONB 陣列裡移除（不是整列重寫）。
- `0024`：`drop_table(session_tokens)`。
- `0023`：先 drop 三個新增欄與其索引（`terminal_sessions.task_id` 的 FK 要先 drop constraint，
  沿用 `0021` 的寫法），再 drop 八張表，順序與外鍵相反。

**一條容易忘的**：`activity_events.actor_kind` 是 `NOT NULL DEFAULT`，
downgrade 時直接 drop column 即可，但 `ALL_KINDS` 新增的七個 kind 在 downgrade 之後
會變成資料庫裡存在、程式碼不認得的值——所以 downgrade 演練要在**空的 activity 表**上跑，
而演練腳本要說明這一點（既有的 roundtrip 腳本已經是在乾淨資料庫上跑的，這裡只是把理由寫下來）。

## 6. 測試

| 層 | 覆蓋 |
|---|---|
| `backend/tests/db/` | 八張表的建立與外鍵行為；`ON DELETE SET NULL` 的四個路徑各一條 |
| | **併發配號**：兩個 async 交易同時建卡 → 兩個不同的 `card_ref`，沒有 UNIQUE 違反 |
| | **樂觀鎖**：兩個交易同時 PATCH 同一張卡 → 一個成功、一個 409，且失敗那個**沒有寫入任何一半** |
| | `activity_events.actor_kind` 的三種值 ＋ `redact_actors` 不動它 |
| | `session_tokens`：同一個值算兩次 HMAC 相同；Session 刪除連帶刪 token 列 |
| Migration | 上下行 roundtrip；`pg_dump` diff 只有宣告的那些 |
| Schema gate | `GATE-TK-SCHEMA-ADDITIVE`：既有表逐欄無變化（`08-…md` §4） |
