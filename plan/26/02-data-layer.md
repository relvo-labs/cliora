# 02 — 資料層（Migration `0043`）

> **ticket：`PX-22`（migration ＋ model ＋ backfill ＋ seed），依賴 `PX-61`（D98）。**

## 1. 一個 migration，不是兩個

`alpha.3` 用了兩個（`0041` extension、`0042` 表），理由是
`CREATE EXTENSION` 有自己的失敗模式與 downgrade 順序。**本期沒有那個問題**：
`0043` 全部是 additive DDL ＋ 資料 backfill，一個交易能完成，
拆兩個只會多一個要記住順序的東西。

```text
revision       0043_work_views_and_rank
down_revision  0042_knowledge_tables
```

## 2. `work_views`

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
  deleted_at TIMESTAMPTZ,            -- 只有 scope='project' 會被設；personal 是硬刪除（D112）
  CONSTRAINT ck_work_views_scope CHECK (
    (scope = 'personal' AND owner_user_id IS NOT NULL) OR
    (scope = 'project'  AND owner_user_id IS NULL AND project_id IS NOT NULL)
  ),
  CONSTRAINT ck_work_views_layout  CHECK (layout  IN ('board','list','roadmap')),
  CONSTRAINT ck_work_views_density CHECK (density IN ('compact','comfortable'))
);

CREATE UNIQUE INDEX uq_work_views_name
  ON work_views(COALESCE(project_id,    '00000000-0000-0000-0000-000000000000'::uuid),
                COALESCE(owner_user_id, '00000000-0000-0000-0000-000000000000'::uuid),
                name)
  WHERE deleted_at IS NULL;          -- 部分索引：刪除後名稱可重用（kintra 的形狀，D112）

-- 一個 project 至多一個預設 view。部分唯一索引，因為 is_default=false 的列有很多。
CREATE UNIQUE INDEX uq_work_views_default
  ON work_views(project_id) WHERE is_default AND scope = 'project';

CREATE INDEX ix_work_views_owner ON work_views(owner_user_id) WHERE owner_user_id IS NOT NULL;
```

`filter_json` 是 JSONB 而不是子表，理由逐字採用 kintra `p2_01_board_views` 的 docstring：

> 篩選條件是整體讀寫的值物件，沒有任何查詢需要「找出所有用到 `priority=urgent` 的檢視」。
> 拆子表只會讓一次讀取變成 join，且每加一種篩選維度就要改表結構。

這段話要抄進 `0043` 的 docstring——「為什麼不拆表」是每個讀到 JSONB 欄位的人都會問一次的問題。

三個約束各自擋掉一種無意義的狀態：

| 約束 | 擋掉什麼 | 為什麼要在資料庫層 |
|---|---|---|
| `ck_work_views_scope` | 「personal 但沒有 owner」與「project 但有 owner」 | 這兩種列會讓 `PX-26` 的權限判斷需要一個 `if` 而不是一個 join |
| `uq_work_views_default` | 一個 project 兩個 default | 上游只說「改 default 要 audit」，沒說**改 default 是把舊的關掉再開新的**。沒有這個索引，一次失敗的交易會留下兩個 default，而 UI 會隨機挑一個 |
| `uq_work_views_name` | 同一個擁有者的同名 view | 形狀移植自 kintra 的 `uq_board_views_board_user_name`——**包括它是部分索引這件事**（[D112](./01-decisions-and-governance.md)）。`COALESCE` 到全零 uuid 是因為 PostgreSQL 的 `UNIQUE` 不比較 `NULL` |

**`uq_work_views_default` 是上游沒有的。** 它讓「改 default」必須寫成
一個交易裡的兩個 `UPDATE`（先清舊、再設新），而那正是 audit 要記的那一對值
（[`01`](./01-decisions-and-governance.md) D105 的同一個原則）。

### `layout = 'roadmap'` 為什麼現在就在值域裡

`beta.1` 只實作 `board` 與 `list`。`roadmap` 現在就進 CHECK 約束，
理由與 `BoardDTO.has_more` 一樣（`schemas.py:1070`）：
**一個之後才加的值會逼每個既有客戶端處理它的缺席**，
而一個從第一版就在的值只是暫時沒有人寫入。

## 3. `tasks` 的四個新欄位

```sql
ALTER TABLE tasks ADD COLUMN rank             VARCHAR(64);
ALTER TABLE tasks ADD COLUMN is_blocked       BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE tasks ADD COLUMN blocking_reason  VARCHAR(32);
ALTER TABLE tasks ADD COLUMN blocking_message TEXT;
```

**四個，不是五個。** 上游 [`08`](../../research/03/08-data-model-and-contract.md) §4
列了第五個 `attention_primary`，並說「只有在 `PX-24` 量測後決定物化才建立」。
[D92](./01-decisions-and-governance.md) 把那個問題關掉了：
**八級裡有兩級不在資料庫裡，所以物化對它們無效，於是八級都不物化。**
這個欄位不會出現在 `0043`，也不會出現在 `0043b`。

`blocking_reason` 的值域（**應用層的常數，不是 CHECK 約束**）：

```text
dependency | human_input | no_eligible_runner | assigned_runner_offline
verification_failed | gate_unmet | unknown
```

**不加 CHECK 的理由**：`no_eligible_runner` 與 `assigned_runner_offline`
是相位 B 的產物（D92），寫入它們的路徑是 backfill 的一次性推導；
之後的日常寫入只會用前兩個與 `unknown`。一個 CHECK 會把
「這一欄記錄的是當時的推導」變成「這一欄是權威分類」，而它不是。
值域的斷言在 `services/work/projection.py` 的一個 `frozenset` 與一支測試上。

## 4. 四個索引

```sql
CREATE INDEX ix_tasks_project_rank    ON tasks(project_id, rank);
CREATE INDEX ix_tasks_project_blocked ON tasks(project_id) WHERE is_blocked;
CREATE INDEX ix_tasks_project_owner   ON tasks(project_id, owner_user_id);
CREATE INDEX ix_tasks_project_updated ON tasks(project_id, updated_at DESC);
```

第四個是 [D104](./01-decisions-and-governance.md)。

> ⚠️ **實作後更正**（[`12`](./12-implementation-status.md) §2.10）：原文說它是
> 「本期唯一一個會讓既有查詢變快的變更」。**實測顯示它對既有看板完全沒有效果**——
> `read_board` 回傳專案的全部卡片，而一個反正要讀完的表，索引贏不了循序掃描 ＋ 排序；
> 200 卡與 2000 卡的執行計畫都一個位元組沒變。
> 它真正服務的是**會提早停下來**的查詢，也就是 `PX-25` 的游標與 Done 欄的「近 7 天／近 N」：
> 在 2000 卡上 `LIMIT 50` 便宜 14 倍、快 6.7 倍。**決定不變，理由改寫。**


```python
# repositories/tasks.py:107 — 現行看板，今天沒有支援它的索引
return select(Task).where(Task.project_id == project_id).order_by(Task.updated_at.desc())
```

`0023_task_board.py` 只建了 `ix_tasks_project_stage` 與 `ix_tasks_project_story`；
`0039` 加了 `ix_tasks_proposal_item`。**`(project_id, updated_at)` 從來沒有存在過。**
`PX-22` 要在 200 卡與 2000 卡兩個規模上各量一次前後 `EXPLAIN ANALYZE`，
輸出進 `artifacts/px/local/`。

既有的 `ix_tasks_project_stage` 繼續服務 lifecycle filter（投影自 stage）。

### 已經有的、不要重複建

```text
ix_tasks_project_stage      (project_id, stage)         0023
ix_tasks_project_story      (project_id, user_story_id) 0023
ix_tasks_proposal_item      …                            0039
task_runs 的 (task_id, status) 相關索引                   0029 起
```

`required_labels` 的 GIN 索引**不建**：上游 [`04`](../../research/03/04-phase-p1-view-and-read-model.md) §3
把它列為 `contains` 運算子的索引需求，但一個專案的卡片是數百張、
`required_labels` 是短陣列，而 GIN 的維護成本落在每一次卡片更新上。
**先不建，`PX-24` 的量測若顯示 `contains` 是熱點再補一個 `0043b`。**
記在 [`11`](./11-open-measurements.md) 第 5 項。

## 5. Backfill：三段，順序固定

### 5.1 `rank`

```text
對每個 project：
  SELECT id FROM tasks WHERE project_id = ? ORDER BY updated_at DESC, id DESC
  ranks = rebalanced_ranks(len(rows))            -- PX-61 的純函式（D98）
  逐列 UPDATE tasks SET rank = ranks[i]
之後：ALTER TABLE tasks ALTER COLUMN rank SET NOT NULL;
```

`ORDER BY updated_at DESC, id DESC` 與 `board_cards()` 的排序**逐字相同**
（`repositories/tasks.py:126`）。這一條要有一個測試：
**backfill 之後，依 `rank` 排序的結果與 backfill 之前依 `updated_at DESC, id DESC`
排序的結果完全相同。** 否則使用者升級之後會看到卡片重新洗牌。

`rebalanced_ranks(count)` 保證等距、保序、去重、滿足 I2（不以 `'0'` 結尾），
且 `width=3` 支援到 23327 張，超過自動加寬——所以呼叫端不需要判斷。

### 5.2 `is_blocked` 與 `blocking_reason`

`stage = 'blocked'` 的卡設 `is_blocked = true`，`blocking_reason` 依下列順序推導，
**都推不出來就是 `unknown`**：

| 序 | 條件 | 查哪裡 |
|---:|---|---|
| 1 | 有未完成的 `task_dependencies` | `TaskRepository.unfinished_dependencies()` |
| 2 | active run 為 `waiting_for_input` | `TaskRepository.active_runs()` |
| 3 | 最近一次 dispatch 失敗於資格判定 | `task_runs` 最新一列 ＋ `waiting_reason` 的歷史（**若查不到就跳過**） |
| 4 | 指定的 runner 離線 | **跳過**——見下 |
| 5 | 最近 verification 不合格 | `verification_reports` 最新一列 `result IN ('failed','partial')` |
| 6 | 有未通過的 gate | `tasks.gates` |
| 7 | 以上皆非 | **`unknown`，列入 ambiguous report** |

**第 3 與第 4 條在 migration 裡不可用。** 這是上游 [`12`](../../research/03/12-migration-and-rollout.md) §3.2
沒有看到的：兩者都需要 `NodeConnectionRegistry`（D92 的相位 B），
而 **migration 跑在一個沒有 registry 的行程裡**——`alembic upgrade` 不是 FastAPI app。
所以 backfill 只實作 1／2／5／6，其餘一律 `unknown`。

`blocking_message` 一律 `NULL`。**不猜測 previous stage**，
而且「留在 `ready`」這件事本身要出現在 report 上（上游 §3.2 的補充，本計畫採納）。

### 5.3 Ambiguous report

`PX-22` 的產物之一，落在 `artifacts/px/local/blocked-ambiguous.{json,csv}`：

```text
card_ref, title, project_name, updated_at, derived_reason, last_5_activity_kinds
```

**條件是「人工檢查完才能繼續」**——但「繼續」指的是 `beta.2` 的 `HD-06`（最終遷移），
不是 `beta.1` 的部署。`beta.1` 帶著 `unknown` 上線是可以的，
因為讀模型對 `unknown` 的呈現是「已阻塞（原因未知）」而不是假裝知道。

### 5.4 預設 view seed

`0043` 對**既有**專案呼叫 `seed_default_views(project_id)`；
`ProjectService.create()` 對**新**專案呼叫同一個函式（[D101](./01-decisions-and-governance.md)）。

| name | layout | filter | group_by | order_by | is_default |
|---|---|---|---|---|---|
| `Active Work` | board | `lifecycle in (ready, in_progress, review, done)` | `lifecycle` | `rank asc` | **✅** |
| `Backlog` | list | `lifecycle eq backlog` | — | `rank asc` | |
| `Waiting for Me` | list | `attention eq waiting_for_your_input` | — | `updated_at desc` | |
| `Blocked` | list | `is_blocked eq true` | `blocking_reason` | `updated_at desc` | |
| `Verification` | list | `lifecycle eq review` | — | `updated_at desc` | |

全部 `scope = 'project'`、`owner_user_id = NULL`、`created_by = NULL`（系統建立）。
`seed_default_views` 冪等（`ON CONFLICT (…name) DO NOTHING`），
因為 migration 與 `create()` 都可能對同一個 project 跑到。

## 6. Downgrade

```sql
DROP INDEX ix_tasks_project_updated;
DROP INDEX ix_tasks_project_owner;
DROP INDEX ix_tasks_project_blocked;
DROP INDEX ix_tasks_project_rank;
ALTER TABLE tasks DROP COLUMN blocking_message;
ALTER TABLE tasks DROP COLUMN blocking_reason;
ALTER TABLE tasks DROP COLUMN is_blocked;
ALTER TABLE tasks DROP COLUMN rank;
DROP TABLE work_views;
```

**完全可逆，但不是無損**：

| 失去什麼 | 嚴重性 |
|---|---|
| 使用者的 saved view | **這是產品資料，而 ☑ [D117](./01-decisions-and-governance.md#d117) 之後 downgrade 是唯一的回滾路徑**——沒有旗標可關。所以 `PX-66` 的回滾演練要先**匯出 `work_views` 成 JSON** 再 downgrade，並在演練報告記錄「回滾會失去 saved view，除非先匯出」 |
| rank | 無害。重新 upgrade 會依 `updated_at DESC` 重新 backfill，順序回到升級前的樣子 |
| `is_blocked` | 無害。`stage='blocked'` 仍在，舊看板照常 |

`GATE-PX-MIGRATION-ROUNDTRIP` 沿用 `scripts/ar/gate-migration-roundtrip.sh`，
target revision `0042_knowledge_tables`（形狀照抄 `scripts/kn/gates.sh:136`）。

## 7. Model 變更

```python
# db/models.py — Task 新增四欄
rank: Mapped[str | None] = mapped_column(String(64), nullable=True)
is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
blocking_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
blocking_message: Mapped[str | None] = mapped_column(Text, nullable=True)
```

`rank` 在 model 上是 `nullable=True` 而資料庫是 `NOT NULL`：
**這是刻意的不一致**，因為 `Task()` 建構時還不知道 rank
（要先知道要插在哪兩張卡之間）。`TaskService.create()` 在 flush 之前
呼叫 `rank_between(None, first_rank)` 填它，而一支測試斷言
「新建的卡一定有 rank」。

`WorkView` 是新的 model class，落在 `db/models.py` 尾端
（沿用既有的「一個檔案」慣例——`models.py` 已經 2170 行，
拆檔是另一題，本期不動）。

## 8. 與 `EDITABLE_FIELDS` 的關係

```python
# services/tasks.py
EDITABLE_FIELDS |= {"is_blocked", "blocking_reason", "blocking_message", "rank"}

# services/agent_auth.py — 擴大禁區（00 §3 的例外 1 與 4）
AGENT_FORBIDDEN_FIELDS |= {"is_blocked", "blocking_reason", "rank"}
```

三個新的禁止欄位各有理由：

| 欄位 | 為什麼 Agent 不能改 |
|---|---|
| `is_blocked` | 能把自己標成「非阻塞」的 Agent 等於能繞過 dependency gate（上游 §6.2） |
| `blocking_reason` | 同上的第二半：能改原因就能把 `dependency` 改成 `unknown`，讓報表看不到 |
| `rank` | **上游沒有寫。** 能改自己排序的 Agent 可以把自己的卡插到 Backlog 最前面，而 rank 沒有樂觀鎖以外的保護 |

`blocking_message` **不在禁區**：它是給人看的一句話，
Agent 寫「等待 SSO 供應商回覆」是有用的，而它不影響任何判斷。
