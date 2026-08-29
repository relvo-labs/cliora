# 06 — 規模與可觀測性（`HD-10`）

> 上游：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §6 的 `HD-10`
> 「大 Project 的 indexing、retention、queue、cost 與 observability（**新增**）」——一行。
> 決策：[D127](./01-decisions-and-governance.md#d127)（2000 卡新 seed 檔）、
> [D133](./01-decisions-and-governance.md#d133)（只加 metric 與 EXPLAIN）。

## 1. 這一期在回答什麼問題

三期的量測全部在 **200 卡**上做的（`scripts/cv/seed-dataset.py:59` `TASKS = 200`）。
於是每一個效能數字後面都有一句沒說出來的話：「在 200 卡上」。

本期要做的不是把系統調快，是**知道它在哪裡開始不行**。
`plan/26/11` §10 已經把這一項排到這裡：

> 造一個 2000 卡的 fixture 只會量到 PostgreSQL 的效能，量不到真實的 filter 分布。

**那句話是對的，而它不是不量的理由。** 量到 PostgreSQL 的效能就是量到一件事：
在 2000 卡上，`work-items` 的成本是查詢還是推導。這兩個答案指向不同的修法。

## 2. 2000 卡的固定資料集

**新檔** `scripts/hd/seed-large.py`，**不改** `scripts/cv/seed-dataset.py`
（[D127](./01-decisions-and-governance.md#d127)：200 卡那組是三期的對照組）。

| 維度 | 200 卡（既有） | 2000 卡（本期） | 為什麼是這個數 |
|---|---:|---:|---|
| tasks | 200 | **2000** | 十倍。一個真的忙的團隊一年的量 |
| 分佈 | 80／40／20／20／40 | 同比例 | 保持可比 |
| 等待卡 | 20 | **200** | attention 最高一級的密度不變 |
| conversation message | 500 | **5000** | 深卡仍然是一張，其餘攤開 |
| knowledge source | — | **5000** | `alpha.3` 沒有量過規模 |
| knowledge chunk | — | **20000** | 每 source 四個 chunk。**這個比例是選的不是量的**——`chunking.py:29` 的 `DEFAULT_CHUNK_TOKENS = 800`，四個 chunk 約等於一份 3200 token 的文件。seed 腳本的第一個動作是**印出實際比例**，不符就調 |
| repository | 1 | **50** | provider reconcile 的每輪成本 = repository 數 × 3 個 GET |
| 相依鏈深度 | 1 條短鏈 | **1 條 200 節點的鏈** | `blocking_counts()` 的成本來自鏈深，不是卡數 |

**相依鏈那一列是本節唯一一個非等比放大的維度**，而它是刻意的：
`blocking_counts()`（`repositories/tasks.py`）對每張卡問「有幾張擋著你」，
而一條 200 節點的鏈是那個查詢的最壞情況。等比放大不會產生它。

## 3. 六個熱查詢的 `EXPLAIN`

| # | 查詢 | 現有索引 | 擔心什麼 |
|---:|---|---|---|
| 1 | `work-items`（無 filter，第一頁） | `ix_tasks_project_rank`（`0043:199`） | rank 是 `VARCHAR(64)`，2000 卡的 B-tree 深度 |
| 2 | `work-items`（三層 filter） | filter compiler 動態產生 | 有沒有走到索引，或是全表 |
| 3 | `work-counts`（八級 attention） | `ix_tasks_project_blocked`（partial，`0043:201`） | **最熱的端點**（D95 每 20 秒輪詢），P95 < 200ms 是硬預算 |
| 4 | `blocking_counts()` | `ix_tasks_project_story` | 200 節點的鏈 |
| 5 | knowledge search（FTS ＋ trigram 雙通道） | GIN（`0042`） | 20000 chunk 上 trigram 的成本 |
| 6 | `knowledge_jobs` 的 `FOR UPDATE SKIP LOCKED` claim | `uq_knowledge_jobs_pending`（partial unique） | queue 深度大時的 claim 延遲 |

**輸出形式**：`artifacts/hd/local/w5/explain/*.txt`，
每份含 `EXPLAIN (ANALYZE, BUFFERS)` 的完整輸出 ＋ 一行結論
（「走了哪個索引」或「seq scan，因為 X」）。

**一行結論是必要的**，因為一份 `EXPLAIN` 輸出在三個月後沒有人會重讀。

## 4. 五個新 metric（原計畫六個，`legacy_route_hit_total` 做不出來）

沿用 `metrics.py` 的既有形狀：in-process、counter 與 histogram、
**label key 走封閉 allowlist**、gauge 刻意不存（`metrics.py:1`）。

| Metric | 型別 | label | 為什麼需要 |
|---|---|---|---|
| `provider_read_total` | counter | `host`、`outcome`（ok／refused／unreachable） | pull 模型下唯一能看出「同步還活著嗎」的東西 |
| `provider_reconcile_lag_seconds` | histogram | — | live cursor 後真正變更的 provider entity，其 `updated_at` 到 ingest 的距離；首次 backfill 不計。**300 秒的承諾就是靠它證明的** |
| `knowledge_queue_depth_total` | counter | `state`（pending／failed） | queue 積起來的表現是「knowledge 有點舊」，而那在畫面上看不出來 |
| `context_citation_total` | counter | `authority`（十級） | [D134](./01-decisions-and-governance.md#d134) 的量測。**只記 metadata** |
| ~~`legacy_route_hit_total`~~ | — | — | **☒ 不做**（`HD-07`，2026-08-28）：redirect 在 vue-router 裡、SPA 由 nginx 送，FastAPI 看不到 `?tab=`。一個永遠是 0 的指標會被讀成「沒人在用」。改為宣告式日落，見 ADR 0044 §4 |
| `work_counts_duration_seconds` | histogram | — | 最熱端點的 P95，本來只有離線量測 |

**label 全部低基數**，沒有一個是 id、path 或關鍵字——
`metrics.py:14` 已經寫過原因：「metrics 是唯一沒有 redaction 的 sink」。

**`provider_reconcile_lag_seconds` 是六個裡最重要的一個**：
它是 pull 模型的那個 300 秒承諾唯一的證據。不可用剛寫回的
`provider_synced_at` 算 `now - provider_synced_at`；那只會量出接近零的同步執行時間。
沒有它，「一個 PR 合掉之後最多 300 秒出現」就是一句話而不是一個事實。

## 5. Retention 與體積

| 資料 | 現有保留政策 | 2000 卡下的實測要記什麼 |
|---|---|---|
| `knowledge_chunks` | **無保留**（ADR 0038 §6） | 20000 chunk 的表大小 ＋ GIN 索引大小 |
| `task_messages` | **無保留**（產品資料，ADR 0041） | 5000 則的表大小 |
| `task_run_log_lines` | 有——`TaskRun.logs_expire_at` 驅動的 sweep | sweep 一輪在 2000 卡的量下要多久 |
| `activity_events` | 無保留 | 表大小成長率（每張卡的 activity 數 × 2000） |
| provider source | **無保留**（[D132](./01-decisions-and-governance.md#d132) 沿用 knowledge） | 50 個 repository × PR 與 release 的量 |

**要寫進 release note 的是一句話**：
「在 2000 卡／20000 chunk 時，資料庫是 X GB；三個無保留的表各佔 Y／Z／W。
超過這個量沒有量過。」

`plan/26` 的 known limitations 沒有這一句，而它是一個要部署這個系統的人
**第一個會問**的問題。

## 6. Cost 一頁

**不是財務估算**，是一張「這個系統的成本從哪來」的表：

| 成本項 | 隨什麼成長 | 2000 卡時的量 | 有沒有上限機制 |
|---|---|---|---|
| PostgreSQL 儲存 | chunk 數 × chunk 大小 | 待量 | **沒有**（無保留） |
| GIN 索引重建 | chunk 數 | 待量 | 沒有 |
| knowledge worker CPU | job 數 × chunk 切分 | 待量 | `BATCH=32`、`INTERVAL=3s` |
| provider API 配額 | repository 數 × 12 輪／小時 × 3 GET | **50 × 36 = 1800 GET／小時** | [D128](./01-decisions-and-governance.md#d128) 的 ≤36／repository／小時 |
| Central 記憶體 | metrics series 數 ＋ `NodeConnectionRegistry` | 待量 | label allowlist |

**provider 那一列是唯一算得出來的**，而 1800 GET／小時
對 GitHub 的 5000／小時 authenticated 配額是 36%。
**這個數字要寫進 release note**——一個部署 50 個 repository 的人需要知道它。

## 7. 不做的四件事（[D133](./01-decisions-and-governance.md#d133)）

| 不做 | 為什麼 |
|---|---|
| 分割 `knowledge_chunks` | 需要知道真實的查詢分布才知道按什麼分割。在 fixture 上選的分割鍵會量到 PostgreSQL |
| 改 `BATCH=32` / `INTERVAL=3.0` | 這兩個數字的依據是「freshness 目標 P95 < 10s」（`worker.py:48`）。改它們要先有一個新的 freshness 目標，而那要真實使用資料 |
| virtualization | `plan/26` 說「200 張是第一個 gate，1000 張才評估」。**本期是評估，不是實作**——量完之後決定 |
| 第二種 worker | 一個迴圈跑兩件事的成本是一個 `if`；兩個迴圈的成本是兩組 advisory lock、兩組 metric 與兩個可以各自壞掉的東西 |

## 8. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☐ | `scripts/hd/seed-large.py` 可重跑、產出 2000／5000／20000／50／200-鏈 | 一次跑完的輸出 |
| ☐ | `scripts/cv/seed-dataset.py` **一行未改** | diff |
| ☐ | 六個 `EXPLAIN (ANALYZE, BUFFERS)` ＋ 每份一行結論 | `artifacts/hd/local/w5/explain/` |
| ☐ | **五個** metric 在 `/metrics` 上，label 全部在 allowlist 內（第六個 `legacy_route_hit_total` 已裁定不做，理由在 §4） | 截圖 ＋ `metrics.py` 的 allowlist diff |
| ☑ | `provider_reconcile_lag_seconds` 的 P95 ≤ 300 秒 | `provider-lag-hour.json`：production worker 300 秒 cadence、12 輪／24 event、3613.071 秒，P95 **291.013 秒** |
| ☐ | retention 與體積的五列全部有實測值 | 表 ＋ release note |
| ☐ | provider API 配額佔比（50 repository = 36%）進 release note | release note |
| ☐ | virtualization 的**決定**（做或不做 ＋ 理由）已寫下 | [`11`](./11-implementation-status.md) |
