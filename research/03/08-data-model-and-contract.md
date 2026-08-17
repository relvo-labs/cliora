# 08 — 資料模型、Contract、RBAC 與憑證

## 1. 全域概觀

現況：migration head **0039**、`models.py` **1695 行 / 40 張表**、contract **1.13.0**、
RBAC **24 個動作**、`agentd` **0.12.0**。

本規劃新增：

| 里程碑 | Migration | 新表 | 既有表新欄位 | RBAC | Contract |
|---|---|---:|---:|---|---|
| `alpha.2` | `0040` | 2 | 3 張表共 **14** 欄 | **0 個新動作** | **不動**（D44 已裁決） |
| `alpha.3` | `0041`、`0042` | 6 | 1 張表共 2 欄 | **0 個新動作** | 不動 |
| `beta.1` | `0043` | 1 | 1 張表共 5 欄 | **0 個新動作** | 不動 |
| `beta.2` | `0044`、`0045` | 3 | — | 待 ADR 0043 | 可能 1.14.0 |

**三個里程碑都不新增 RBAC 動作**，是刻意的（[D53](./01-architecture-decisions.md)）。
每多一個動作就多一件要在測試裡證明「它不在 `RUN_TOKEN_SCOPES` 裡」的事，
而現有 `project.view` / `project.manage` / `task.update` / `task.approve` 的持有者集合
正好對應到需要的四種權限。**因此也不需要 seed migration。**

## 2. `alpha.2`：Conversation（migration `0040`）

### 2.1 既有表的 additive 欄位

```sql
-- tasks：三個投影欄，讓看板讀模型免掉對 task_messages 的 join
ALTER TABLE tasks ADD COLUMN conversation_seq   INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN open_question_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN waiting_for_actor  VARCHAR(16);   -- human | agent | NULL

-- task_messages
ALTER TABLE task_messages ADD COLUMN conversation_seq    INTEGER;
ALTER TABLE task_messages ADD COLUMN reply_to_message_id UUID REFERENCES task_messages(id) ON DELETE SET NULL;
ALTER TABLE task_messages ADD COLUMN question_id         UUID;   -- FK 在 task_questions 建立後補
ALTER TABLE task_messages ADD COLUMN idempotency_key     VARCHAR(128);
ALTER TABLE task_messages ADD COLUMN turn_run_id         UUID REFERENCES task_runs(id) ON DELETE SET NULL;

-- task_runs：continuation turn
ALTER TABLE task_runs ADD COLUMN parent_run_id  UUID REFERENCES task_runs(id) ON DELETE SET NULL;
ALTER TABLE task_runs ADD COLUMN turn_seq       INTEGER NOT NULL DEFAULT 1;
ALTER TABLE task_runs ADD COLUMN input_from_seq INTEGER;
ALTER TABLE task_runs ADD COLUMN input_to_seq   INTEGER;
```

**Backfill**：既有訊息依 `(task_id, created_at, id)` 排序填 `conversation_seq`（1 起算），
`tasks.conversation_seq` 設為該卡的最大值。`created_at` 相同時以 `id` 決勝——
**這正是目前 `--since <timestamp>` 分頁不可靠的原因**，backfill 必須明確處理它。

Backfill 之後才加約束：

```sql
ALTER TABLE task_messages ALTER COLUMN conversation_seq SET NOT NULL;
CREATE UNIQUE INDEX uq_task_messages_seq ON task_messages(task_id, conversation_seq);
CREATE UNIQUE INDEX uq_task_messages_idem ON task_messages(task_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_task_messages_task_seq ON task_messages(task_id, conversation_seq DESC);
CREATE INDEX ix_task_runs_parent ON task_runs(parent_run_id) WHERE parent_run_id IS NOT NULL;
```

`kind` 的值域擴充（`comment`／`system` 是 `message`／`event` 的新名字，**舊值保留可讀**）：

```text
現有：message | question | answer | event
新增：comment | proposal | decision | system
讀取相容：message → 視為 comment；event → 視為 system
寫入：新程式只寫新值
```

**不做 rename migration。** 一次 `UPDATE` 全表在有 audit 依賴的資料上不值得，
而讀取端的兩行映射永遠正確。這個決定記在 ADR 0035。

### 2.2 新表

```sql
CREATE TABLE task_questions (
  id                 UUID PRIMARY KEY,
  task_id            UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  run_id             UUID REFERENCES task_runs(id) ON DELETE SET NULL,
  asked_message_id   UUID NOT NULL REFERENCES task_messages(id) ON DELETE CASCADE,
  state              VARCHAR(16) NOT NULL,   -- open|answered|cancelled|expired
  answered_message_id UUID REFERENCES task_messages(id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  answered_at        TIMESTAMPTZ,
  CONSTRAINT ck_task_questions_state CHECK (state IN ('open','answered','cancelled','expired'))
);
CREATE INDEX ix_task_questions_open ON task_questions(task_id) WHERE state = 'open';

CREATE TABLE conversation_consumers (
  task_id            UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  consumer_type      VARCHAR(16) NOT NULL,   -- run | runner
  consumer_id        UUID NOT NULL,
  last_delivered_seq INTEGER NOT NULL DEFAULT 0,
  last_acked_seq     INTEGER NOT NULL DEFAULT 0,
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, consumer_type, consumer_id)
);
```

`ix_task_questions_open` 是**部分索引**：一張卡的一生可能有幾十個問題，
但同時 open 的最多一個（[D42](./01-architecture-decisions.md)）。全索引會索引到用不上的列。

### 2.3 `conversation_seq` 的取號

```sql
UPDATE tasks SET conversation_seq = conversation_seq + 1
WHERE id = :task_id
RETURNING conversation_seq;
```

在同一個交易裡取號並 INSERT 訊息。鎖的是卡片列——**那一列本來就要更新
`updated_at`**，所以沒有多出一次鎖競爭。[D38](./01-architecture-decisions.md) 記錄了
為什麼不用 `SEQUENCE`（每卡有洞）與 `max(seq)+1`（併發重複）。

## 3. `alpha.3`：Knowledge（migration `0041`、`0042`）

### 3.1 `0041` — extension 與 project 設定

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- PostgreSQL contrib，postgres:16-alpine 內建

ALTER TABLE projects ADD COLUMN knowledge_enabled  BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN knowledge_settings JSONB   NOT NULL DEFAULT '{}'::jsonb;
```

> **`CREATE EXTENSION` 需要資料庫的 superuser 或 `pg_trgm` 已在 `shared_preload`／
> extension allowlist。** Railway 與 compose 兩條部署路徑都要在 `KN-02` 驗證，
> 失敗訊息要明確指向這一行——一個在 migration 中間失敗的 `CREATE EXTENSION`
> 會讓部署停在半路。這是本輪唯一一個**不是純 additive** 的資料庫變更。

### 3.2 `0042` — 六張表

```sql
CREATE TABLE knowledge_sources (
  id                  UUID PRIMARY KEY,
  project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_type         VARCHAR(32) NOT NULL,
  source_external_id  VARCHAR(255) NOT NULL,
  source_uri          TEXT,
  source_version      VARCHAR(128) NOT NULL,
  authority           VARCHAR(16) NOT NULL,
  visibility          VARCHAR(16) NOT NULL DEFAULT 'project',
  checksum            CHAR(64) NOT NULL,
  title               VARCHAR(500),
  authored_by_type    VARCHAR(16),          -- human | runner | system
  authored_by_id      UUID,
  occurred_at         TIMESTAMPTZ NOT NULL,
  ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  supersedes_source_id UUID REFERENCES knowledge_sources(id) ON DELETE SET NULL,
  active              BOOLEAN NOT NULL DEFAULT true,
  deleted_at          TIMESTAMPTZ,
  UNIQUE (project_id, source_type, source_external_id, source_version)
);
CREATE INDEX ix_knowledge_sources_project_active
  ON knowledge_sources(project_id, source_type) WHERE active AND deleted_at IS NULL;

CREATE TABLE knowledge_chunks (
  id           UUID PRIMARY KEY,
  source_id    UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,  -- 反正規化，見下
  chunk_key    VARCHAR(128) NOT NULL,
  content      TEXT NOT NULL,
  content_hash CHAR(64) NOT NULL,
  token_count  INTEGER NOT NULL,
  embedding_ref VARCHAR(128),               -- 預留，alpha.3 永遠 NULL
  search_document TSVECTOR NOT NULL,
  valid_from   TIMESTAMPTZ NOT NULL,
  valid_to     TIMESTAMPTZ,
  UNIQUE (source_id, chunk_key)
);
CREATE INDEX ix_knowledge_chunks_fts  ON knowledge_chunks USING GIN(search_document);
CREATE INDEX ix_knowledge_chunks_trgm ON knowledge_chunks USING GIN(content gin_trgm_ops);
CREATE INDEX ix_knowledge_chunks_project ON knowledge_chunks(project_id) WHERE valid_to IS NULL;

CREATE TABLE knowledge_links (
  from_source_id UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  relation       VARCHAR(24) NOT NULL,
  to_source_id   UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  PRIMARY KEY (from_source_id, relation, to_source_id)
);

CREATE TABLE knowledge_jobs (
  id              UUID PRIMARY KEY,
  project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  source_type     VARCHAR(32) NOT NULL,
  external_id     VARCHAR(255) NOT NULL,
  payload         JSONB NOT NULL,
  state           VARCHAR(16) NOT NULL,     -- pending|running|done|failed|dead
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_error      TEXT,
  dead_lettered_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_knowledge_jobs_pending ON knowledge_jobs(created_at) WHERE state = 'pending';

CREATE TABLE task_knowledge_pins (
  task_id    UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  source_id  UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  mode       VARCHAR(8) NOT NULL,           -- pin | exclude
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (task_id, source_id)
);

CREATE TABLE context_packs (
  id              UUID PRIMARY KEY,
  run_id          UUID NOT NULL REFERENCES task_runs(id) ON DELETE CASCADE,
  task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  built_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_manifest JSONB NOT NULL,           -- [{source_id, version, authority, tokens}]
  budget_json     JSONB NOT NULL,
  omitted_json    JSONB NOT NULL
);
```

**`knowledge_chunks.project_id` 是刻意的反正規化。** 它可從 `source_id` join 出來，
但 isolation 測試要能對**每一張表單獨**斷言「A 專案的查詢碰不到 B 專案的列」；
多一個欄位換一個更短、更難寫錯的證明。同理 `context_packs.project_id`。

**`context_packs.source_manifest` 只存 ID 與 metadata，不存內容。**
存內容等於把敏感資料複製第二份，且會讓 retention 政策失效（[D51](./01-architecture-decisions.md)）。

## 4. `beta.1`：View、rank 與 blocked（migration `0043`）

```sql
CREATE TABLE work_views (
  id                  UUID PRIMARY KEY,
  project_id          UUID REFERENCES projects(id) ON DELETE CASCADE,   -- NULL = 跨專案個人 view
  owner_user_id       UUID REFERENCES users(id) ON DELETE CASCADE,      -- NULL = project 共用
  name                VARCHAR(64) NOT NULL,
  layout              VARCHAR(16) NOT NULL,     -- board|list|roadmap
  scope               VARCHAR(16) NOT NULL,     -- personal|project
  filter_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
  group_by            VARCHAR(32),
  subgroup_by         VARCHAR(32),
  order_by_json       JSONB NOT NULL DEFAULT '[]'::jsonb,
  visible_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  density             VARCHAR(16) NOT NULL DEFAULT 'comfortable',
  show_subtasks       BOOLEAN NOT NULL DEFAULT true,
  is_default          BOOLEAN NOT NULL DEFAULT false,
  position            BIGINT NOT NULL,
  version             INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT ck_work_views_scope CHECK (
    (scope = 'personal' AND owner_user_id IS NOT NULL) OR
    (scope = 'project'  AND owner_user_id IS NULL AND project_id IS NOT NULL)
  )
);
CREATE UNIQUE INDEX uq_work_views_name
  ON work_views(COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(owner_user_id, '00000000-0000-0000-0000-000000000000'::uuid),
                name);

ALTER TABLE tasks ADD COLUMN rank             VARCHAR(64);
ALTER TABLE tasks ADD COLUMN is_blocked       BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE tasks ADD COLUMN blocking_reason  VARCHAR(32);
ALTER TABLE tasks ADD COLUMN blocking_message TEXT;
ALTER TABLE tasks ADD COLUMN attention_primary VARCHAR(32);   -- 若 PX-24 決定物化才用

CREATE INDEX ix_tasks_project_rank    ON tasks(project_id, rank);
CREATE INDEX ix_tasks_project_blocked ON tasks(project_id) WHERE is_blocked;
CREATE INDEX ix_tasks_project_owner   ON tasks(project_id, owner_user_id);
```

`ck_work_views_scope` 是關鍵約束：它讓「personal 但沒有 owner」與
「project 但有 owner」這兩個無意義的狀態**在資料庫層不存在**。

**Backfill**：
- `rank`：依 `ORDER BY updated_at DESC` 對每個 project 產生初始 lexicographic 值，
  之後 `SET NOT NULL`。
- `is_blocked`：`stage = 'blocked'` 的卡設 `true`，`blocking_reason` 設 `'unknown'`
  並列入 ambiguous report（見 [`12`](./12-migration-and-rollout.md) §3）。**不猜測 previous stage。**
- 預設 view：每個 project seed 五個 project view（Active Work／Backlog／Waiting for Me／
  Blocked／Verification），`is_default` 給 Active Work。

`attention_primary` 欄位**只有在 `PX-24` 量測後決定物化才建立**。
migration 先不加；若量測結果需要，另開 `0043b`。**不預先建一個可能用不到的欄位。**

## 5. Contract

### `alpha.2` — 不動（[D44](./01-architecture-decisions.md)，2026-08-16 已裁決）

理由完整在 [`01`](./01-architecture-decisions.md) §1.2。摘要：

- continuation turn = child run，走既有 `runner.poll` → `run.offer` → `run.accept`。
- 對話內容不上 wire，agent 用 `cliora task messages --after <seq>`（run token、HTTPS）拉。
- `contracts/` 無 diff；`agentd` 0.12.0 未升級節點跑完整 E2E 是出口條件之一。

### 若 D44 改為採納通知路徑

則需要：contract **1.14.0**、兩個新的 central→node 訊息型別、
`runner.register.features` 新增 `conversation_notify` 宣告、`agentd` **0.13.0**，
以及**一組證明「未宣告 feature 的節點不會收到新訊息型別」的 fixture**。

```text
task.message_available { task_id, conversation_seq }
run.input_available    { run_id, question_id, conversation_seq }
```

通知只表示「有新資料」，**不攜帶內容**；daemon 仍以 HTTPS 依 cursor 拉取。
這一點無論 D44 怎麼裁決都不變。

### `beta.2` — provider ingestion

ADR 0043 決定是否需要 contract 變更。**傾向不需要**：webhook 是 Central 的
HTTP 入口，與 node protocol 無關。

## 6. RBAC 與兩種憑證

### 6.1 動作對應（不新增動作）

| 新能力 | 需要的既有動作 |
|---|---|
| 讀 conversation | `project.view` |
| 發 comment／question／answer | `task.update` |
| 寫 decision（接受／拒絕 spec proposal） | **`task.approve`** |
| 觸發 continuation resume | `task.update` |
| 讀 knowledge search／sources | `project.view` |
| pin／exclude source、標為正式決策、resync | `project.manage` |
| 開關 `knowledge_enabled` | `project.manage` |
| 讀 project view | `project.view` |
| 改 project view／default | `project.manage` |
| bulk update | 逐張以既有 task 權限判定 |

### 6.2 Run token（`RUN_TOKEN_SCOPES = {project.view, task.update}`，**不變**）

| 能做 | 不能做 |
|---|---|
| 讀本 task 的 conversation | 讀別的 task |
| 以 runner actor 發 `comment`／`question`／`answer`／`proposal` | 指定 actor |
| 讀本 run 的 turn input、推進 ack | 讀別的 run |
| 查詢本 project 的 knowledge、取得 context pack | 跨 project 查詢 |
| — | 寫 `decision` → `403 AGENT_CANNOT_DECIDE` ＋ audit |
| — | 改 `gates`、`owner_user_id`、`assigned_runner_id`、`required_secrets`、`card_kind`（既有 `AGENT_FORBIDDEN_FIELDS`） |
| — | 改 rank／view／knowledge 設定 |

`AGENT_FORBIDDEN_FIELDS` **新增 `is_blocked`／`blocking_reason`**：
一個能把自己標成「非阻塞」的 Agent 等於能繞過 dependency gate。

### 6.3 Session token（不變）

互動式 Session 的 token 不取得任何 conversation 或 knowledge 的寫入能力。
Agent Run 與 interactive Session 是兩條生命週期——這條紅線本輪完全不動。

## 7. Audit

| 事件 | 記 | 不記 |
|---|---|---|
| message 建立 | actor、kind、task、seq | **message body** |
| answer ＋ resume | question id、continuation run id | answer 內容 |
| decision（接受／拒絕 proposal） | actor、proposal id、結果 | proposal 全文 |
| knowledge source exclude／resync／標為決策 | actor、source id、動作 | source 內容 |
| `knowledge_enabled` 開關 | actor、project、新值 | — |
| shared view created／updated／deleted | actor、view id、diff 摘要 | — |
| project default view 變更 | actor、舊／新 view id | — |
| bulk task update | actor、patch、**完整 item refs**（一筆 batch） | — |
| Agent 嘗試 decision 被拒 | actor、task、拒絕原因 | — |
| workflow mapping migration | 執行者、影響筆數、ambiguous 清單位置 | — |

**不記**：personal density、personal visible fields、暫時 filter、Drawer 開關、
knowledge search 查詢字串（它會包含使用者正在想什麼，且沒有稽核價值）。

## 8. Machine codes 總表

```text
# alpha.2
QUESTION_ALREADY_ANSWERED  QUESTION_NOT_OPEN         RUN_NOT_WAITING_FOR_INPUT
CONVERSATION_CURSOR_AHEAD  MESSAGE_IDEMPOTENCY_CONFLICT
TURN_ALREADY_QUEUED        MESSAGE_TOO_LARGE         MESSAGE_ATTACHMENT_REJECTED
AGENT_CANNOT_DECIDE

# alpha.3
KNOWLEDGE_DISABLED         SOURCE_NOT_FOUND          SOURCE_EXCLUDED
CONTEXT_BUDGET_EXCEEDED    CROSS_PROJECT_DENIED

# beta.1
FILTER_FIELD_NOT_ALLOWED   FILTER_OP_NOT_ALLOWED     FILTER_TOO_COMPLEX
VIEW_NAME_CONFLICT         VIEW_NOT_OWNED            BULK_LIMIT_EXCEEDED
RANK_NEIGHBOR_STALE        STAGE_TRANSITION_REFUSED
```

每一個都要有：明確的 HTTP status、可行動的訊息、以及**指名是哪一個欄位／資源**。
`STAGE_TRANSITION_REFUSED` 的回應必須列出未滿足的 gate 項目——
提案 §6.4「拒絕必須回傳 machine code、可行動訊息與未滿足項目」是出口條件。
