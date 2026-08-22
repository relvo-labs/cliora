# 02 — 資料層（`KN-02`：migration `0041`、`0042`）

> 上游 DDL：[`research/03/08`](../../research/03/08-data-model-and-contract.md) §3。
> 本文件的差異都標了 **★**——那是讀完既有 40 個 migration 與 models.py 之後的修正。

## 1. 為什麼是兩個 migration 而不是一個

```text
0041_knowledge_extension   CREATE EXTENSION pg_trgm  +  projects.knowledge_{enabled,settings}
0042_knowledge_tables      六張表 + 索引
```

**這是本輪唯一一個不是純 additive 的資料庫變更**，而它只有一行。
把它單獨關在一個 migration 裡有三個具體的好處：

1. **失敗訊息指得準。** `CREATE EXTENSION` 需要資料庫的 superuser 或 extension allowlist。
   一個在 migration 中間失敗的 `CREATE EXTENSION` 會讓部署停在半路，
   而如果它跟六張表在同一個檔案裡，錯誤訊息會是「`0042` 失敗」——
   一個要讀 300 行才知道是哪一行的訊息。
2. **downgrade 的順序有意義。** extension 的 drop 需要沒有依賴物件，
   所以 downgrade 一定是先 `0042`（丟掉用 `gin_trgm_ops` 的索引）再 `0041`。
   兩個檔案讓這個順序由 alembic 的 revision 鏈保證，而不是由一個人記得。
3. **`0041` 可以先上。** 兩欄 ＋ 一個 extension 是可以在波次 1 一開始就上線的，
   而六張表要等 ADR 0038 定稿。

### 1.1 `0041`

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE projects ADD COLUMN knowledge_enabled  BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE projects ADD COLUMN knowledge_settings JSONB   NOT NULL DEFAULT '{}'::jsonb;
```

`knowledge_settings` 的形狀（**JSONB 而不是表**，沿用 `projects.process_overrides` 的判斷：
「與 project 一起讀寫、沒有獨立查詢」）：

```jsonc
{
  "exclude_globs": ["vendor/**", "**/*.min.js"],   // 使用者加的，與 .clioraignore 疊加
  "repo_sync": { "enabled": true, "max_files": 800 },
  "sources": { "diagnostic": false }               // 是否收人選的 log excerpt
}
```

**★ 修正**：上游只寫「exclude rules、repo sync 範圍、retention 覆寫」。
retention 覆寫拿掉了——D81 決定 knowledge 沒有自己的時鐘，一個沒有 sweep 的
retention 欄位是一個會誤導人的欄位。

### 1.2 兩條部署路徑各驗一次（`KN-02` 的出口條件）

| 路徑 | 怎麼驗 | 失敗時要看到什麼 |
|---|---|---|
| `deploy/compose` | `postgres:16-alpine` 的預設 superuser 就是 migration 用的角色，預期直接成功 | — |
| Railway | Railway 的 PostgreSQL 通常給非 superuser。**必須實測** | migration 失敗訊息要明確指向 `pg_trgm`，並在 `docs/deployment-railway.md` 加一節說明怎麼手動建 |

**★ 補上一個 preflight**：`0041` 在 `CREATE EXTENSION` 之前先查
`SELECT 1 FROM pg_available_extensions WHERE name='pg_trgm'`，
沒有就 raise 一個帶操作指引的錯誤。理由：`IF NOT EXISTS` 對「權限不足」沒有幫助，
它只對「已經裝了」有幫助，而後者不是會出問題的那種情況。

## 2. `0042` — 六張表

DDL 以上游 [`research/03/08`](../../research/03/08-data-model-and-contract.md) §3.2 為準。
以下只列**差異與必須寫進 docstring 的理由**。

### 2.1 `knowledge_sources`

★ 三處修正：

| 修正 | 原本 | 改成 | 理由 |
|---|---|---|---|
| 新增 `source_updated_at TIMESTAMPTZ NOT NULL` | 沒有 | 有 | 冪等 upsert 的比較欄（`WHERE excluded.source_updated_at > current`）。上游在 §4 的敘述裡用了這個欄位名，但 DDL 裡沒有它 |
| 新增 `chunk_count INTEGER NOT NULL DEFAULT 0` | 沒有 | 有 | Source health 面板要顯示每種來源的筆數，而 `count(*)` on `knowledge_chunks` 在 Sources 頁的五個區塊各跑一次是五次全表掃 |
| `authority` 長度 | `VARCHAR(16)` | **`VARCHAR(16)`** ✔ | 最長是 `authoritative`（13）。確認過，不改 |

`source_type` 的封閉值域（本期八種，**用 CHECK 約束而不是註解**）：

```sql
CHECK (source_type IN ('policy','ticket','conversation','decision',
                       'artifact','verification','repo_doc','activity'))
```

★ 上游沒有這個約束。加它的理由與 `ActivityService.record()` 對 `kind` 做的一樣：
「A typo would otherwise create a row no filter can ever find」。

### 2.2 `knowledge_chunks`

```sql
CREATE INDEX ix_knowledge_chunks_fts  ON knowledge_chunks USING GIN(search_document);
CREATE INDEX ix_knowledge_chunks_trgm ON knowledge_chunks USING GIN(content gin_trgm_ops);
CREATE INDEX ix_knowledge_chunks_project ON knowledge_chunks(project_id) WHERE valid_to IS NULL;
```

★ **第四個索引，本期新增**：

```sql
CREATE INDEX ix_knowledge_chunks_live ON knowledge_chunks(project_id, source_id)
  WHERE valid_to IS NULL;
```

理由：每一次檢索都是 `WHERE project_id = ? AND valid_to IS NULL`（isolation predicate，
見 [`05`](./05-retrieval-and-search.md) §4），而 GIN 索引不含 `project_id`。
沒有這個複合索引，PostgreSQL 會對 GIN 的結果做一次 heap 過濾——
在單一 project 的資料佔全表 5% 時那是 20 倍的無效工作。

**`project_id` 的反正規化是刻意的**（上游已說明，這裡補一句可測形式）：
isolation 測試對**每一張表單獨**斷言「A 專案的查詢碰不到 B 專案的列」，
而 `GATE-KN-PROJECT-SCOPED` 用 AST 斷言「對 `knowledge_*` 的每一個 SELECT
都有 `project_id` 的 where 條件」。這個 gate 寫得出來，**只因為欄位在每一張表上**。

★ **`search_document NOT NULL` 的後果要寫進 docstring**：它由 Python 端算
（D79），所以任何繞過 `services/knowledge/` 直接 INSERT chunk 的路徑都會失敗——
這是想要的。

### 2.3 `knowledge_links`

`relation` 的封閉值域用 CHECK：
`supersedes | derived_from | references | verifies | delivers | blocks`。

★ 補一個索引：`CREATE INDEX ix_knowledge_links_to ON knowledge_links(to_source_id, relation);`
——graph boost 兩個方向都要走（「誰引用了我」與「我引用了誰」），
而 PK 只覆蓋 `from` 開頭的那個方向。

### 2.4 `knowledge_jobs`

★ 三處修正：

```sql
next_attempt_at TIMESTAMPTZ,        -- 指數退避的下一次時間（上游沒有這一欄）
started_at      TIMESTAMPTZ,        -- 用來偵測卡死的 running job
UNIQUE (project_id, source_type, external_id, state) WHERE state = 'pending'
```

最後一項是 D80 的 `ON CONFLICT DO NOTHING` 的目標。★ 但 PostgreSQL 的 partial
unique 要寫成 unique index：

```sql
CREATE UNIQUE INDEX uq_knowledge_jobs_pending
  ON knowledge_jobs(project_id, source_type, external_id) WHERE state = 'pending';
CREATE INDEX ix_knowledge_jobs_claimable
  ON knowledge_jobs(created_at) WHERE state = 'pending';
CREATE INDEX ix_knowledge_jobs_dead
  ON knowledge_jobs(dead_lettered_at) WHERE state = 'dead';
```

第三個索引是給 metric 用的：「最舊的失敗 job 幾歲」是 `KN-12` 的 metric 之一
（上游 §4 第 3 點），而它每 15 秒被 scrape 一次。

### 2.5 `task_knowledge_pins`

不變。`mode ∈ {pin, exclude}` 用 CHECK。
★ 補：`created_by` 是 `SET NULL`，所以一個離職者留下的 pin 仍然有效——
這是對的（pin 是專案的決定不是個人的偏好），但要在 docstring 說出來，
否則第一個讀到 NULL 的人會以為是資料壞了。

### 2.6 `context_packs`

★ 三處修正：

| 修正 | 理由 |
|---|---|
| 新增 `turn_seq INTEGER NOT NULL DEFAULT 1` | D78：一個 run 可能拉多次；`turn_seq` 讓 manifest 對得上 continuation 的第幾輪 |
| 新增 `total_bytes INTEGER NOT NULL` | 效能量測要的分子；也是「這個 pack 有多大」在 UI 上的唯一答案 |
| **不加**唯一鍵 | 刻意的。兩次拉取讀到不同內容正是要被看見的事情（D78） |

`source_manifest` 的形狀（**只有 ID 與 metadata，不存內容**）：

```jsonc
[{ "source_id": "…", "source_type": "conversation", "version": "seq:41",
   "authority": "discussion", "title": "…", "tokens": 214, "layer": 4,
   "score": 0.71, "why": ["trigram:CV-05", "graph:same_epic"] }]
```

★ `why` 是上游沒有的。它是 `KN-11`「為什麼被選中」那一欄的資料來源，
而它同時是 [`09`](./09-verification-and-exit.md) 的 relevance eval 唯一可自動比對的東西。
**沒有它，「retrieval 是不是黑盒」這個問題只能靠人讀。**

## 3. Model 層

六個 class 加進 `app/db/models.py`（**不新開檔案**——`models.py` 1873 行是本 repo 的既有慣例，
拆檔是一個獨立的決定，不該夾在功能期裡做）。

每個 class 的 docstring 要回答的問題，依本 repo 既有 model 的水準：

| Model | docstring 必須回答 |
|---|---|
| `KnowledgeSource` | 為什麼 authority 是欄位不是推導（D45）；為什麼唯一鍵是四欄；`active` 與 `deleted_at` 的差別（D81） |
| `KnowledgeChunk` | 為什麼 `project_id` 反正規化；為什麼 `search_document` 在 Python 端算（D79）；`embedding_ref` 為什麼永遠 NULL（D40） |
| `KnowledgeLink` | 為什麼是表不是 JSONB（graph boost 有自己的查詢，兩個方向都要索引） |
| `KnowledgeJob` | 為什麼 job 是提示不是內容（D80）；為什麼沒有游標 |
| `TaskKnowledgePin` | 為什麼 `created_by` SET NULL 之後 pin 仍有效 |
| `ContextPack` | 為什麼隨 run CASCADE（D89）；為什麼 manifest 只存 ID |

## 4. Downgrade

```text
0042 down:  DROP TABLE ×6（順序：pins → context_packs → links → chunks → jobs → sources）
0041 down:  ALTER TABLE projects DROP COLUMN ×2
            DROP EXTENSION IF EXISTS pg_trgm    ← 只有在沒有依賴物件時成功
```

★ **`DROP EXTENSION` 不用 `CASCADE`。** 用 CASCADE 會連帶丟掉別人建的、
剛好用到 `pg_trgm` 的索引，而那是一個 downgrade 不該做的事。
沒有依賴物件時它會成功；有的時候它會失敗，而**失敗是對的**——
訊息會指名還有誰在用。

`GATE-KN-MIGRATION-ROUNDTRIP` 沿用 `scripts/ar/gate-migration-roundtrip.sh`
（`GATE-CV-MIGRATION-ROUNDTRIP` 已經在用同一支），目標 revision 改成 `0040_ticket_conversation`。
**不 fork 那支腳本**：問題（「downgrade 之後 schema 是否逐位元組回到基線」）是同一個問題，
第二份拷貝會在任一份被修時與另一份不一致。

## 5. 測試（`KN-02`）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `test_pg_trgm_is_available` | `SELECT 'a' % 'ab'` 不報錯 |
| 2 | `test_source_unique_key_refuses_a_duplicate_version` | 四欄唯一鍵 |
| 3 | `test_source_type_check_refuses_a_typo` | CHECK 約束 |
| 4 | `test_pending_job_is_deduplicated` | 同一實體連續 note 五次 → 一列 pending |
| 5 | `test_deleting_a_project_removes_every_knowledge_row` | 六張表 cascade（D81） |
| 6 | `test_deleting_a_run_removes_its_context_packs_but_not_its_messages` | D89 的兩半 |
| 7 | `test_chunk_requires_a_search_document` | NOT NULL 擋掉繞過 pipeline 的 INSERT |
| 8 | `test_downgrade_restores_the_baseline_schema` | roundtrip gate 的 pytest 版本 |
| 9 | `test_knowledge_settings_defaults_to_an_empty_object` | server_default，不是 Python default |
