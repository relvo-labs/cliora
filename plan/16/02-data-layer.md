# 02 — 資料層（`PJ-02`）

Migration `0021_projects`，`down_revision = "0020_node_file_upload"`。
**一支 migration 建三張表 ＋ 一個 `ALTER`**，seed 另計（`0022`，見 `03-…md` §1）。

慣例沿用 `0014_node_tunnels.py`：`postgresql.UUID(as_uuid=True)`、`postgresql.JSONB()`、
`sa.DateTime(timezone=True)` ＋ `server_default=sa.func.now()`、
索引用 `op.execute("CREATE INDEX IF NOT EXISTS …")`（可重跑）。

## 1. 為什麼是三張表而不是一張、也不是五張

判準沿用 `research/02/08` §2 的那一句：**沒有獨立查詢需求、隨父物件一起讀寫的東西用 JSONB；
有關聯查詢需求的才建表。** 加上這個 repo 自己的一條先例——
`FR-WORKSPACE-004`（最近使用的 workspace）**刻意沒有表**，因為它可以從
`terminal_sessions` 推導，而「第二個儲存同一組事實的地方，只會有機會和第一個不一致」
（`0011_workspace_favorites.py` 的註解）。

| 候選 | 建表？ | 理由 |
|---|---|---|
| `projects` | ✅ | 有獨立生命週期與 CRUD |
| `project_workspaces` | ✅ | 多對多（一個 Project 多個 workspace、一個 workspace 可屬多個 Project），需要唯一鍵與 join |
| `activity_events` | ✅ | 需要 `(project_id, occurred_at)` 的分頁查詢；而且它與 `audit_logs` 的**保留期不同**（`00-…md` D6） |
| 「Project 的進行中 Session 數」 | ❌ | 從 `terminal_sessions` where `project_id = ? and status in ACTIVE_STATES` 直接算。存一份計數就是第二個真實來源 |
| 「Project 的最後活動時間」 | ❌ | `max(activity_events.occurred_at)`。同上 |
| `project_members` | ❌ | `00-…md` D8 |

## 2. `projects`

```python
op.create_table(
    "projects",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column("name", sa.String(length=128), nullable=False),
    sa.Column("slug", sa.String(length=64), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    sa.Column(
        "owner_user_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.UniqueConstraint("slug", name="uq_projects_slug"),
)
```

| 欄位 | 決定 | 理由 |
|---|---|---|
| `slug` | **有**，全域唯一，`^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$`，建立時由 `name` 產生但可覆寫，**建立後不可改** | 它是給 V2.1 的 `card_ref`（`TASK-123` 前面的專案識別）與 V2.3 的機密命名空間用的。可改的 slug 會讓那兩個東西的歷史值失去意義。`name` 可以隨便改，slug 不行——這個分工要寫在 model 的 docstring 上 |
| `status` | `active`／`paused`／`archived`，**沒有 `deleted`** | `00-…md` D9。`paused` 與 `archived` 的差別在 `03-…md` §2.3 |
| `owner_user_id` | `NOT NULL`，`ON DELETE RESTRICT` | 與 `workspace_favorites` 的 `CASCADE` 不同，**刻意的**：一個使用者離職不該讓他的專案連同時間軸消失。`RESTRICT` 會讓刪除使用者失敗——而目前**沒有任何刪除使用者的端點**，所以這條約束今天不會擋到任何人，它是留給那個端點被寫出來的那一天的一句話 |
| `default_node_id`／`default_runtime` | **不建** | 本期沒有任何程式碼會讀它們。Session 表單的預填來自 `is_primary` 綁定（有 node 也有 path，比一個孤立的 `default_node_id` 更有用）。需要時是一次 `ALTER TABLE ADD COLUMN NULL`，零風險。**偏離 `research/02/02` §PJ-02，理由在此** |
| 沒有 `deleted_at` | — | 沒有刪除就不需要 soft delete 的欄位。**不要照抄 `nodes` 的形狀** |

**不建索引。** `slug` 的唯一約束自帶索引；`owner_user_id` 的查詢（「我擁有的專案」）
在專案數量到達需要索引的量級之前，seq scan 便宜得多。這一句要寫進 migration 的 docstring，
否則下一個人會「順手」補三個索引。

## 3. `project_workspaces`

```python
op.create_table(
    "project_workspaces",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "project_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "node_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("path", sa.String(length=4096), nullable=False),
    sa.Column("label", sa.String(length=128), nullable=True),
    sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.UniqueConstraint("project_id", "node_id", "path", name="uq_project_workspaces_project_node_path"),
)
op.execute(
    "CREATE INDEX IF NOT EXISTS ix_project_workspaces_project "
    "ON project_workspaces (project_id);"
)
op.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_project_workspaces_one_primary "
    "ON project_workspaces (project_id) WHERE is_primary;"
)
```

三個設計說明：

**一、唯一鍵讓綁定變成冪等的。** 同一組 `(project, node, path)` 第二次 POST 回既有的列，
不是 409——**沿用 `workspace_favorites` 的既有裁決**（「favouriting the same path twice is
the same intent expressed twice」）。差別在這裡回 200 而不是 201。

**二、`is_primary` 用 partial unique index，不用應用層檢查。** 一個 Project 最多一個主要
workspace，這是 DB 能保證而應用層在併發下保證不了的東西。
`0013_shell_session_parent`（WT-07／ADR 0021）已經用過同一個手法
（一個 CLI session 最多一個 live shell），而且它的註解寫明了為什麼那半條要在 DB：
「a user who clicked twice would produce two live shells」——同一個按兩下的情境在這裡是
兩個「主要」。差別是我們的條件更單純（不必跟 `ACTIVE_STATES` 綁在一起），
所以 partial index 的 `WHERE is_primary` 不需要一條 `test_..._states_match_...` 去釘住它。

**三、`path` 是 `String(4096)` 而不是 `Text`。** 與 `terminal_sessions.workspace` 和
`workspace_favorites.path` 一致。三個地方存同一種東西，型別不一致會在 join 與比較時
變成一個沒有人預期的隱式轉換。

**`ON DELETE CASCADE` 是安全網不是正常路徑。** Node 的移除是 soft delete（ADR 0011），
所以正常情況下這個 CASCADE 永遠不會觸發——服務層以 `nodes.deleted_at IS NULL` 過濾
（`00-…md` D4）。這一段要**逐字**寫進 migration 的 docstring，因為
`0011_workspace_favorites.py` 已經因為同一件事寫過一次，而下一個人仍然會踩到。

## 4. `activity_events`

```python
op.create_table(
    "activity_events",
    sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "project_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),      # V2.1 才有值
    sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),  # 系統事件為 null
    sa.Column("kind", sa.String(length=64), nullable=False),
    sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)
op.execute(
    "CREATE INDEX IF NOT EXISTS ix_activity_events_project_occurred_at "
    "ON activity_events (project_id, occurred_at DESC, id DESC);"
)
```

| 決定 | 理由 |
|---|---|
| `task_id`／`session_id` **沒有外鍵** | `task_id` 指向一張 V2.1 才存在的表，所以本期不可能有 FK。`session_id` 則是刻意的：**時間軸是歷史**，一個被硬刪的 session 不該讓它的那一列消失或變 null。與 `audit_logs` 的既有做法一致（那三個 UUID 欄位也都沒有 FK） |
| `actor_user_id` **有** FK 嗎 | **沒有**，同上，且與 `audit_logs.user_id` 一致 |
| `payload` `NOT NULL DEFAULT '{}'` | 與 `audit_logs.metadata` 一致（`default=dict`）。null 與 `{}` 的差別在讀取端沒有任何意義，而多一個 null 分支就是多一個 `if` |
| 索引含 `id DESC` | 分頁的 tiebreaker。`(occurred_at DESC)` 單獨用在同毫秒的兩列上會給出不穩定的順序，而 keyset 分頁會因此漏列或重複。`_recent_activity_block` 的 `order_by(AuditLog.created_at.desc(), AuditLog.id.desc())` 是同一個理由 |
| **沒有保留期、沒有清理任務** | `00-…md` D6。它是產品內容不是診斷紀錄。ADR 0024 W2 的問題「誰清這個」的答案是：**Project 被刪除時 CASCADE**——而 Project 沒有刪除，所以答案實際上是「不清」。這是一個要寫下來的答案，不是一個漏掉的問題。成長速率是 M-PJ-02（`08-…md`） |

### 4.1 `kind` 的封閉詞彙（V2.0 六個）

```python
PROJECT_CREATED       = "project.created"
PROJECT_UPDATED       = "project.updated"      # 含狀態轉換，payload 帶 from/to
WORKSPACE_BOUND       = "workspace.bound"
WORKSPACE_UNBOUND     = "workspace.unbound"
SESSION_STARTED       = "session.started"
SESSION_ENDED         = "session.ended"        # payload 帶 status 與 exit_code
```

放在 `app/services/activity.py`，形狀**照 `app/services/audit.py`**：常數 ＋ `ALL_KINDS`
＋ 一條 `test_every_activity_kind_has_a_write_site`（照
`test_audit_redaction.py:test_every_audit_action_has_a_write_site` 抄）。
一個沒有人寫的 kind 是一個永遠回空的篩選器。

### 4.2 `payload` 的內容約束

**套用 `audit.FORBIDDEN_METADATA_KEYS` 的同一份清單**（`content`、`keyword`、`rel_path`、
`password`、`token`、`private_key`、`bytes`），並配一條測試。

理由：`activity_events` 的可見性比 `audit_logs` **寬**（`project.view` vs `audit.view`），
所以對內容的約束只能更嚴不能更鬆。V2.2 之後會有 Agent 往這張表寫東西——
那時這條檢查已經在了。

V2.0 的 payload 只放這些：`{"name": …}`、`{"from": "active", "to": "paused"}`、
`{"node_name": …, "path": …}`、`{"runtime": …, "workspace": …}`。
**`path` 允許**（`audit_logs` 的 `file.upload` 已經放使用者選的相對路徑），
但 workspace 絕對路徑只給 `project.view` 持有者——而他們本來就看得到綁定列。

## 5. `terminal_sessions.project_id`

```sql
ALTER TABLE terminal_sessions ADD COLUMN project_id UUID NULL
  REFERENCES projects(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_terminal_sessions_project
  ON terminal_sessions (project_id) WHERE project_id IS NOT NULL;
```

- **nullable，而且永遠 nullable**（D12）。Ad-hoc Session 是產品的一部分。
- **不 backfill。** 升級後所有既有 session 的 `project_id` 都是 `NULL`，那是正確的——
  它們確實不屬於任何 Project。
- **partial index**：旗標關閉的部署裡這一欄全是 null，partial index 不佔空間也不拖寫入。
- `task_id` 留到 V2.1 的 `0023` 一起加（那時 `tasks` 表才存在，它會是真的外鍵）。
- `ON DELETE SET NULL` 是安全網：本期沒有任何 API 會刪除 Project（D9）。

## 6. SQLAlchemy 模型

加在 `backend/app/db/models.py`，位置放在 `WorkspaceFavorite` 之後、`NodeMetricSample` 之前
（讓 workspace 形狀的東西聚在一起）。

四個 docstring 各要回答一件事，照既有模型的密度：

| 模型 | docstring 要說的 |
|---|---|
| `Project` | slug 不可改而 name 可改，以及為什麼；沒有刪除只有封存 |
| `ProjectWorkspace` | **「A binding, never an authorization.」**——直接呼應 `WorkspaceFavorite` 的第一句；node soft delete 時服務層過濾而非 CASCADE |
| `ActivityEvent` | 與 `audit_logs` 的分工（誰看得到、誰清）；為什麼三個 UUID 欄位沒有 FK |
| `TerminalSession.project_id` | 一行註解：永遠 nullable，Ad-hoc 是產品的一部分，平台不推論（指向 ADR 0027） |

## 7. 驗收

| 檢查 | 方法 |
|---|---|
| Migration 上行 | `make migrate`；`alembic current` 顯示 `0021_projects` |
| Migration 下行 | `alembic downgrade 0020_node_file_upload` → `pg_dump --schema-only` 與 `PJ-00` 的 B2 基線**逐位元組相同** |
| 重跑 | `alembic upgrade head` 兩次（第二次無操作）；`0021` 的索引都是 `IF NOT EXISTS` |
| 既有表未變 | `pg_dump --schema-only` 與 B2 的 diff **只有** 三個 `CREATE TABLE`、四個 `CREATE INDEX`、一個 `ALTER TABLE … ADD COLUMN project_id`、以及 `terminal_sessions` 上多的那一個 FK 約束 |
| `is_primary` 唯一性 | `backend/tests/db/test_projects.py`：兩列同 `project_id` 都 `is_primary=true` → `IntegrityError` |
| 綁定冪等 | 同 `(project, node, path)` 插兩次 → `IntegrityError`（服務層據此回既有列） |
| 分頁穩定 | 同一毫秒插 200 筆 activity，keyset 分頁走完剛好 200 筆、無重複 |
| `kind` 詞彙 | `test_every_activity_kind_has_a_write_site` 通過（`PJ-04` 之後才會全綠——所以這條測試與 `PJ-04` 同 PR，同 D7 的理由） |

**`make test-db` 要同時設兩個變數**：`CLIORA_TEST_DATABASE_URL` 與 `CLIORA_DATABASE_URL`
（`plan/15/06` 記過的環境事實）。
</content>
