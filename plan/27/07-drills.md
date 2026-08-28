# 07 — 演練（`HD-08`／`HD-09`）

> 上游：[`research/03/12`](../../research/03/12-migration-and-rollout.md) §2（「每一個 migration 都要有一次演練」）與 §5。
> 決策：[D123](./01-decisions-and-governance.md#d123)（`0046` 不可逆）、
> [D127](./01-decisions-and-governance.md#d127)（並發那一項走 HTTP）。

## 1. 為什麼演練是自己的兩張 ticket

`plan/26` 有一個 `scripts/px/rollback-drill.sh`，四步全綠。
本期不同的地方是**有一個不可逆的 revision**。

一個可逆的 migration 的演練回答「退得回去嗎」。
一個不可逆的 migration 的演練回答**「退不回去的是什麼」**——
而第二個問題的答案要寫進 release note，因為它是使用者要承擔的東西。

## 2. `HD-08` — Migration rehearsal

**範圍**：`0040` → `0046`（七個 revision，跨 `alpha.2`／`alpha.3`／`beta.1`／`beta.2`）。

**兩條部署路徑各一次**：`deploy/compose` 與 Railway
（`deploy/railway`、`deploy/migrate.sh`）。

```text
每條路徑：
  1  在 alpha.1 的資料快照上起一個乾淨環境
  2  alembic upgrade head          → 驗證（見 §4 的驗證清單）
  3  alembic downgrade 0043        → 驗證
  4  alembic upgrade head          → 驗證資料未損
  5  pg_dump → drop → restore      → 驗證
```

**逐 revision 的可逆性表**（要進 release note）：

| Revision | 內容 | 可逆？ | 退回去失去什麼 |
|---|---|---|---|
| `0040` | conversation seq／questions／turns | ✅ | backfill 的 seq 不可還原（無害） |
| `0041` | `pg_trgm` ＋ `projects.knowledge_*` | ⚠️ | extension 的 drop 需要沒有依賴物件——**downgrade 順序是先 `0042` 再 `0041`** |
| `0042` | knowledge 六張表 | ✅ | 全部 index 與 chunk，要重新 ingest |
| `0043` | `work_views` ＋ `tasks` 五欄 ＋ 索引 ＋ rank backfill | ✅ | rank 的值（重跑 backfill 會給不同的字串但同樣的順序） |
| `0044` | provider 兩個 source type ＋ 四欄 | ✅ | provider source 與其 chunk（要重新 reconcile） |
| `0045` | stage 資料 ＋ `legacy_blocked_at` | ✅ | 什麼都不失去——`legacy_blocked_at` 就是為此存在 |
| **`0046`** | `ck_tasks_stage` 收成五值 | ❌ **值域可還原，資料不可** | `0046` 之後被阻塞的卡沒有 `legacy_blocked_at`，退版後它們是 `is_blocked` 而不是 `stage='blocked'`（[`03`](./03-stage-final-migration.md) §3） |

**`0041` 那一列是既有的坑，不是本期新增的**——
但它在一個七個 revision 的 downgrade 裡是**第一個會炸的**，
所以演練腳本要把順序寫死並在失敗時說出原因。

## 3. `HD-09` — Rollback drill

```text
在 beta.1 的資料上：
  1  CLIORA_PROJECTS_ENABLED=false 重啟   → 驗證 V1 路徑完整可用（J16 的一半）
  2  重新開旗                             → 驗證資料未損
  3  downgrade 0045                       → 驗證 legacy_blocked_at 的卡全部還原成 stage='blocked'
  4  downgrade 0043                       → 驗證 provider source 已消失、work_views 保留
  5  upgrade head                         → 驗證資料未損
  6  匯出 work_views                      → 因為 D117 說「沒有 kill switch，回滾前要先匯出」
```

**第 6 步是 `plan/26` D117 留下的義務**：
`CLIORA_PROJECT_EXPERIENCE_V2` 這個旗標**沒有被建立**，
所以新 UI 沒有 kill switch，而回滾前要先把使用者存的 view 匯出。
`plan/26` 的 `rollback-drill.sh` 已經有 `work-views-after.tsv`，本期沿用並擴充。

**五個保證**（沿用 `research/03/12` §5，加一條）：

| 保證 | 怎麼達成 |
|---|---|
| 新 schema 除 `0046` 外全部可 drop | §2 的表 |
| rollback 不刪除使用者 saved views | 表保留，只是不被讀取 ＋ 匯出 |
| rollback 不刪除 conversation | `alpha.2` 的資料是產品資料 |
| knowledge 可整組停用 | `knowledge_enabled=false`，資料保留 |
| **provider 同步可整組停用** | `provider_sync_enabled=false`，資料保留（[D132](./01-decisions-and-governance.md#d132)） |

## 4. 每次演練的驗證清單

**一個「upgrade 成功」的訊息不是驗證。** 每一步之後要問七件事：

```text
☐ alembic current == 預期的 revision
☐ 卡數、message 數、source 數、chunk 數與前一步一致（或按預期變化）
☐ 六個熱查詢各跑一次，沒有錯誤
☐ 一張已知的等待卡的 attention 仍然是 waiting_for_input
☐ 一個已知的 knowledge citation 仍然指得到它的 source
☐ 前端首頁與一個 Project 的 work 頁打得開（HTTP 200 ＋ 沒有 console error）
☐ /metrics 回得出來
```

**第 4、5 項是刻意的**：它們檢查的不是「表還在」，
而是**跨表的一致性在遷移之後仍然成立**。
一個 downgrade 可以讓每張表各自完好而讓它們之間的關係壞掉，
而那種壞法在 `SELECT count(*)` 上看不出來。

## 5. 效能與負載（`HD-09` 的第二半）

**十三項效能預算在 2000 卡上重量一次**
（`research/03/10` §5 的表）。形狀沿用 service-level 量測
（[D127](./01-decisions-and-governance.md#d127)）。

**並發那一項走 HTTP**，因為要量的是連線池與 worker 的競爭：

| 場景 | 併發數 | 預算 | 為什麼 |
|---|---:|---|---|
| `work-counts` | 10 | P95 < 200ms | D95 的硬預算，2000 卡上重驗 |
| `work-counts` | 50 | P95 < 500ms | 一個 50 人團隊每人開一個看板分頁 |
| `work-counts` | 100 | **只記數字，不設預算** | 想知道它在哪裡開始不行，而不是它應該多快 |

**第三列刻意沒有預算。** 一個猜出來的預算被超過時，
唯一能做的事是把它調高——而那不是量測，是記帳。

**輸出**：`artifacts/hd/local/w6/perf-2000.json`，
每一項含 200 卡的舊值與 2000 卡的新值，**並列**。
一個孤立的數字說不出「變慢了幾倍」。

## 6. 出口條件（本節）

| ☐ | 條件 | 證據 |
|---|---|---|
| ☐ | `HD-08` 兩條部署路徑各完成一次五步演練 | `artifacts/hd/local/w6/rehearsal-compose.log`、`-railway.log` |
| ☐ | 七個 revision 的可逆性表完整，`0046` 那一列的「失去什麼」進 release note | 表 ＋ release note |
| ☐ | `0041` 的 downgrade 順序在腳本裡寫死，失敗時說出原因 | 腳本 ＋ 一次故意錯序的輸出 |
| ☐ | 每一步都跑了七項驗證清單 | 逐步輸出 |
| ☐ | `HD-09` 六步全綠，`work_views` 已匯出 | `artifacts/hd/local/w6/rollback/` |
| ☐ | 十三項效能預算在 2000 卡上重量，**與 200 卡並列** | `perf-2000.json` |
| ☐ | 三個並發場景各跑一次；100 併發的數字**只記錄** | 同上 |
| ☐ | 超出預算的項目逐項有處置（修、調、或列入 known limitations） | [`11`](./11-implementation-status.md) |
