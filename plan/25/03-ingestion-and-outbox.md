# 03 — Outbox 與 ingestion worker（`KN-03`）

> **這一張 ticket 的正確性等級與 `CV-05` 相同。** `CV-05` 的問題是
> 「一句話會不會被做兩次」；這裡的問題是「一個事實會不會**沒有**進索引，
> 而且沒有任何地方會說」。第二種比第一種難發現——它的症狀是「搜不到」，
> 而搜不到永遠可以被解釋成「本來就沒有」。

## 1. 四條不可協商的性質

上游 §4 列的四條，逐條對到本期的落點：

| # | 性質 | 落在哪 | 怎麼證明 |
|---|---|---|---|
| 1 | 每個 ingest job 冪等 | §4 的 upsert；唯一鍵 ＋ `source_updated_at` 比較 | 同一 job 連跑三次 → 一列 source、chunk 數不變、`ingested_at` 更新 |
| 2 | Outbox 是事件的真實來源，不是記憶體佇列 | `knowledge_jobs` 表；worker 重啟不遺失 | 入列 20 筆 → 殺 Central → 起來 → 全部處理完 |
| 3 | 失敗有 dead-letter 與可觀測的 age | §5；`KNOWLEDGE_DEAD_LETTER_AGE_SECONDS` gauge | 造一個永遠失敗的 job → 五次 attempt → `state='dead'` → gauge 有值 |
| 4 | 來源被刪除、權限變更或 force-push 時 chunk 可撤銷或重建 | §6 tombstone；全量 manifest 比對 | J12 |

## 2. 入列（D80）

### 2.1 唯一的入列點

```python
# app/services/activity.py
async def record(self, kind, *, project_id, ...) -> None:
    ...
    self._session.add(ActivityEvent(...))
    # V2-K1：同一個交易，同一個決定。一列 activity 是「發生了什麼」，
    # 一列 job 是「所以有東西要重讀」。分兩個交易寫會讓後者在前者 rollback 時倖存。
    await KnowledgeOutbox(self._session).note(
        kind, project_id=project_id, task_id=task_id, payload=body
    )
```

**為什麼在這裡而不是八個服務各自呼叫**：`record()` 已經在 27 處被呼叫、
已經在同一個交易裡（它的 docstring 明寫 "Does **not** commit"）、
而 `kind` 是封閉詞彙表所以覆蓋率可以被測試斷言。八個呼叫點的問題不是麻煩，
是**漏掉一個是靜默的**。

### 2.2 映射表

```python
# app/services/knowledge/outbox.py
_INGEST_MAP: dict[str, tuple[str, _EntityKey]] = {
    activity.TASK_CREATED:            ("ticket",       _task),
    activity.TASK_UPDATED:            ("ticket",       _task),
    activity.TASK_STAGE_CHANGED:      ("ticket",       _task),
    activity.TASK_MESSAGE_POSTED:     ("conversation", _task),
    activity.PROPOSAL_ACCEPTED:       ("decision",     _requirement),
    activity.PROPOSAL_REJECTED:       ("decision",     _requirement),
    activity.REQUIREMENT_APPROVED:    ("decision",     _requirement),
    activity.REQUIREMENT_SPEC_ADDED:  ("decision",     _requirement),
    activity.PATCH_PROPOSAL_DECIDED:  ("decision",     _requirement),
    activity.ARTIFACT_ATTACHED:       ("artifact",     _task),
    activity.VERIFICATION_REPORTED:   ("verification", _task),
    activity.TASK_GATE_APPROVED:      ("activity",     _task),
    activity.TASK_FORCED_DONE:        ("activity",     _task),
    activity.RUN_FINISHED:            ("activity",     _task),
    activity.PROJECT_UPDATED:         ("policy",       _project),
}
```

三件事：

1. **`source_type` 是實體的種類，不是事件的種類。** 五個 requirement 相關的事件都映到
   `decision`，因為 worker 要做的事一樣：重讀那個 requirement 的現況。
2. **`conversation` 的 external_id 是 task id，不是 message id。** worker 重讀該卡
   `conversation_seq` 之後的新訊息並補上 source 列。這讓「一秒內五則訊息」變成一個 job。
3. **`repo_doc` 不在表裡。** 它的入列點是 `KN-06` 的 sync endpoint，不是 activity
   ——repo 的變更不是 Cliora 的事件。

**覆蓋率是測試不是清單**：

```python
def test_every_ingestable_source_type_has_at_least_one_activity_kind():
    mapped = {source_type for source_type, _ in _INGEST_MAP.values()}
    assert SOURCE_TYPES - {"repo_doc"} <= mapped
```

### 2.3 `knowledge_enabled` 的快取

`record()` 是 repo 裡最熱的服務之一，而 `note()` 需要知道
「這個 project 有沒有開 knowledge」。每次去 DB 查等於替每一列 activity 加一次查詢。

```python
# 60 秒 TTL 的 project_id → bool。開關是 project.manage 的動作且寫 audit，
# 所以「剛開啟的 project 最多 60 秒之後才開始 ingest」是可接受的；
# 「剛關閉的 project 最多 60 秒之內還在 ingest」也是——關閉的語意是
# active=false，不是「立刻停止寫入」（D81）。
_ENABLED_CACHE: dict[uuid.UUID, tuple[bool, float]] = {}
```

★ **開關的那個動作本身要主動失效快取**（同一個行程內）＋ 寫一列 activity，
於是多副本部署下最壞情況仍是 60 秒。這一句要進 ADR 0038，
因為「為什麼開了 knowledge 之後畫面上還是空的」會是第一個支援問題。

## 3. Worker 的形狀

沿用 `RunReaper`（`app/services/run_reaper.py`）的三個性質——它們是本 repo
對背景迴圈已經付過學費的結論：

```text
1. start() 先 reconcile 一次，再進迴圈
   「whatever expired while this process was not running is still expired」
2. 一輪多個交易，不是一個
   第三件事失敗不得 rollback 前兩件
3. 每輪有上限
   一個停機兩天的 Central 回來不得在一個交易裡改幾千列
```

```python
# app/services/knowledge/worker.py
BATCH = 32                     # 一輪領幾個 job（RunReaper 的 BATCH 是 200；
                               # 這裡小得多，因為一個 job 要讀實體、算 chunk、寫索引）
INTERVAL = 3.0                 # 秒。freshness 目標是 P95 < 10s，見 §7
RECONCILE_EVERY = 300          # 秒
MAX_ATTEMPTS = 5
```

`main.py` 的 `lifespan` 加一段，形狀與 `_start_run_reaper()` 逐字對應
（含那個「啟動失敗不得讓 Central 起不來」的 try/except 與 warning log）。

### 3.1 領取

```sql
UPDATE knowledge_jobs SET state='running', attempts=attempts+1,
       started_at=now(), updated_at=now()
WHERE id IN (
  SELECT id FROM knowledge_jobs
   WHERE state='pending'
     AND (next_attempt_at IS NULL OR next_attempt_at <= now())
   ORDER BY created_at
   LIMIT 32
   FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

`SKIP LOCKED` 讓多副本併行是安全的（D86），而**沒有游標**是這個設計最重要的性質：
`activity_events.id` 是 uuid4、`occurred_at` 是交易開始時間，
任何基於順序的追蹤都會漏掉「先開始、後提交」的那一列。

### 3.2 卡死的 running job

```text
running 且 started_at < now() - 10 分鐘  →  回到 pending（attempts 不再加）
```

這是 Central 在處理途中被 kill 的唯一恢復路徑。**`attempts` 不加**，
因為那不是一次失敗的嘗試，是一次沒有結論的嘗試——加了會讓一個被重啟三次的 Central
把好的 job 送進 dead letter。

### 3.3 一個 job 的處理

```text
1. 讀 project.knowledge_enabled；false → state='done'，不做事（開關可能在入列後被關）
2. 依 source_type 分派到 sources.py 的 handler（04 章）
3. handler 回傳 [(source_key, title, authority, occurred_at, text)]
4. redact（§8）→ chunk（§9）→ upsert（§4）
5. tombstone 這次沒出現、上次有的（§6）
6. state='done'
```

**分派表是一個 dict，不是 if/elif**——與 `_context_for()` 的判斷相反。
那裡的 branch 是「哪一種情境包」，錯了會給出一句謊；這裡的分派是純資料查表，
漏掉一種的症狀是 `KeyError`，而那會被測試抓到。

## 4. 冪等 upsert（從 kintra 移植的模式）

```sql
INSERT INTO knowledge_sources
  (id, project_id, source_type, source_external_id, source_version, authority,
   checksum, title, occurred_at, source_updated_at, ingested_at, active, chunk_count, …)
VALUES (…)
ON CONFLICT (project_id, source_type, source_external_id, source_version)
DO UPDATE SET
   authority         = excluded.authority,
   title             = excluded.title,
   checksum          = excluded.checksum,
   source_updated_at = excluded.source_updated_at,
   ingested_at       = now(),
   chunk_count       = excluded.chunk_count,
   active            = true,
   deleted_at        = NULL
WHERE excluded.source_updated_at > knowledge_sources.source_updated_at
RETURNING id, (xmax = 0) AS inserted;
```

**不是「先查再決定要不要寫」**（上游 §4 第 1 點、`research/03/01` §1.9）。
後者在兩個 worker 同時處理同一資源時會雙寫，而這是 `KN-03` 一定會遇到的情況：
`SKIP LOCKED` 讓兩個副本各領一個 job，兩個 job 指向同一張卡是完全正常的。

`RETURNING … (xmax = 0)` 讓 metric 能分「新增」與「更新」，
而那個分法是 Source health 面板上「Recently learned」的資料來源。

**★ `WHERE excluded.source_updated_at > …` 的一個陷阱**：當比較為假時
`ON CONFLICT DO UPDATE` **不回傳任何列**，於是 `RETURNING` 是空的，
呼叫端會以為插入失敗。要再一次 `SELECT id` 補齊。這一句要寫進程式碼註解——
它是一個會讓人以為自己寫錯 SQL 的行為。

### 4.1 chunk 的 upsert

```sql
INSERT INTO knowledge_chunks (…, content_hash, search_document, valid_from)
VALUES (…) ON CONFLICT (source_id, chunk_key)
DO UPDATE SET content=…, content_hash=…, search_document=…, token_count=…
WHERE knowledge_chunks.content_hash <> excluded.content_hash;
```

`content_hash` 的比較是效能決定：一張卡被改了 `stage` 而 description 沒動，
chunk 的內容一樣，**不該重算 GIN 索引**。

同一個 source 的 chunk 數變少時，多出來的要 `valid_to = now()`（軟刪），
不是 DELETE——`context_packs.source_manifest` 可能引用它，而懸空引用比
「這段內容已失效」難解釋。

## 5. 退避與 dead letter

| attempt | 下一次 |
|---|---|
| 1 | +5 秒 |
| 2 | +30 秒 |
| 3 | +2 分 |
| 4 | +10 分 |
| 5 | → `state='dead'`，`dead_lettered_at=now()` |

`last_error` 存**型別名稱與一行訊息**，不存 traceback，也不存實體內容
——一個 dead letter 的 `last_error` 會被顯示在 Source health 面板上，
而那個面板的讀者只需要 `project.view`。

五個 metric（label 都是低基數的封閉集合）：

```python
KNOWLEDGE_JOBS_TOTAL              = "knowledge_jobs_total"              # label: source_type, outcome
KNOWLEDGE_JOB_DURATION            = "knowledge_job_duration_seconds"    # label: source_type
KNOWLEDGE_INGEST_LAG_SECONDS      = "knowledge_ingest_lag_seconds"      # histogram: occurred_at → indexed
KNOWLEDGE_DEAD_LETTER_AGE_SECONDS = "knowledge_dead_letter_age_seconds" # gauge，scrape 時算
KNOWLEDGE_PENDING_JOBS            = "knowledge_pending_jobs"            # gauge，scrape 時算
```

後兩個是 gauge，所以**不進 `app/metrics.py` 的 registry**——
那個模組的 docstring 明寫「Gauges are deliberately *not* stored here」，
它們在 `api/http/metrics.py` 的 scrape 路徑上算。

告警（`deploy/prometheus/alerts.yml`）：

| 規則 | 門檻 | 為什麼 |
|---|---|---|
| `KnowledgeDeadLetterAging` | `> 3600` 持續 10 分 | 一小時沒人管的 dead letter 表示沒有人在看面板 |
| `KnowledgeIngestLagHigh` | P95 `> 60s` 持續 15 分 | freshness 目標是 10s；60s 是「壞了」而不是「慢」 |
| `KnowledgePendingBacklog` | `> 5000` 持續 30 分 | worker 追不上，或某個 job 在無限重試 |

★ `plan/24` 的 `CE-11` 學到的：**指標存在但沒有告警規則等於沒有指標**
（`CONVERSATION_DUPLICATE_TURN_TOTAL` 的門檻寫在 docstring 裡，`alerts.yml` 裡沒有它）。
所以這三條規則是 `KN-03` 的交付物，不是 `KN-13` 的。

## 6. Tombstone

三種觸發，一條程式碼：

| 觸發 | 怎麼偵測 |
|---|---|
| repo 檔案在新 commit 消失 | 全量 manifest 比對（`KN-06`） |
| artifact 被刪除 | `task_artifacts.deleted_at` 不為 NULL → handler 回傳空 |
| 來源被人工 exclude | `task_knowledge_pins.mode='exclude'`（**不動 source，只在檢索時排除**） |

```text
tombstone(source) = active=false, deleted_at=now(),
                    chunks 全部 valid_to=now()
```

**exclude 不是 tombstone**，這個區別要在 ADR 寫清楚：exclude 是「這張卡不要用它」
（per-task，可還原），tombstone 是「它不存在了」（per-project，不可還原）。
混在一起的第一個後果是：一個人在一張卡上 exclude 了一份文件，
其他四十張卡也搜不到它。

## 7. Reconciliation（正確性路徑）

事件是新鮮度路徑，排程是正確性路徑。**兩者都要有**（上游 §4 末句）。

```python
# 每 300 秒，pg_try_advisory_lock 單飛（D86）
for source_type, watermark_query in _WATERMARKS.items():
    # 找出「實體的 updated_at 比它的 source.source_updated_at 新」的前 200 個
    # → note() 入列（ON CONFLICT DO NOTHING，所以與事件路徑不衝突）
```

`_WATERMARKS` 對每種 source_type 一條 SQL，形式都是
「LEFT JOIN knowledge_sources ON … WHERE s.id IS NULL OR e.updated_at > s.source_updated_at」。
它同時是「第一次替一個既有 project 開啟 knowledge」的 backfill 路徑
——**不需要另寫一支 backfill 腳本**，開開關之後 reconciler 會把它填滿。

★ 這一點是本章最有價值的設計後果：`KN-02` 沒有 backfill，
因為 `knowledge_enabled` 預設 false，而開啟時 reconciler 就是 backfill。
一個只有一條路徑的填充邏輯比兩條正確。

**進度要看得見**：開啟 knowledge 之後 Source health 面板顯示
「初次建立索引中：ticket 142/500」，資料來自 pending job 數與 watermark 的差。

## 8. Redaction（在寫入之前）

```python
text = await SecretsService(session).redact(project_id, names, text)
```

`names` 用 **project 的 `allowed_secret_names`**（不是單張卡的 `required_secrets`）
——一份 repo 文件不屬於任何一張卡，而它可能提到任何一個機密名。

三個補充規則（`KN-04`／`KN-06` 各自的測試）：

| 規則 | 形式 |
|---|---|
| 疑似憑證的字面樣式一律遮蔽 | `cliora_rt_`／`cliora_st_` 前綴、`-----BEGIN … PRIVATE KEY-----`、`AKIA[0-9A-Z]{16}` 等**固定樣式清單**（不是啟發式熵值判斷） |
| 敏感檔名不進 index | `.env*`、`*.pem`、`*.key`、`id_rsa*`、`*.p12`、`credentials*`、`.npmrc`、`.netrc` |
| raw run log 不進 index | **架構上不可能**：`_INGEST_MAP` 裡沒有任何映到 `run_logs` 的東西，且 `GATE-KN-NO-RAW-LOG-INDEX` 斷言 `services/knowledge/` 不 import `RunLog` |

★ 第三條寫成 gate 而不是測試，理由與 `GATE-CV-NO-LOG-IN-THREAD` 相同：
它守的是一個**不該存在的關聯**，而測試只能證明目前沒有。

## 9. Chunking

```text
800 approx_tokens 一塊、100 重疊（D84）
切點優先序：段落邊界 > 句末（。！？.!?） > 換行 > 硬切
chunk_key = f"{ordinal:04d}"    // 穩定：同樣的輸入產生同樣的 key
```

**`chunk_key` 穩定是冪等的前提**（唯一鍵是 `(source_id, chunk_key)`）。
用序號而不是內容 hash：內容 hash 當 key 會讓「文件開頭加一句話」變成
「全部 chunk 都是新的」，於是每次小改都重算整份 GIN 索引。

短來源不切：一則對話訊息、一個 evidence item 通常遠小於 800 token，
它們是**一個 chunk**，而 `chunk_key='0000'`。

## 10. 測試（`KN-03`）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `test_the_same_job_run_three_times_writes_one_source` | 冪等 |
| 2 | `test_two_workers_racing_on_one_entity_write_one_source` | 兩個 asyncio task 同時處理 → 一列 |
| 3 | `test_an_older_version_does_not_overwrite_a_newer_one` | `source_updated_at` 比較 |
| 4 | `test_a_failing_job_backs_off_then_dead_letters` | 五次 attempt 的時間表 |
| 5 | `test_a_stuck_running_job_returns_to_pending_without_counting_an_attempt` | §3.2 |
| 6 | `test_pending_jobs_survive_a_restart` | 入列 → 丟掉 worker 實例 → 新實例處理完 |
| 7 | `test_activity_rollback_rolls_back_the_job` | 同一交易的證明 |
| 8 | `test_disabled_project_records_activity_but_no_job` | §2.3 |
| 9 | `test_reconciler_finds_an_entity_the_event_path_missed` | 手動刪一列 job 之後 |
| 10 | `test_reconciler_is_single_flighted` | 兩個併發呼叫，一個立即返回 |
| 11 | `test_a_project_secret_value_never_reaches_a_chunk` | redaction fixture（沿用既有 runner 的） |
| 12 | `test_knowledge_module_does_not_import_run_log` | gate 的 pytest 版本 |
| 13 | `test_chunk_keys_are_stable_across_re_ingest` | §9 |
| 14 | `test_deleted_artifact_tombstones_its_chunks` | §6 |
