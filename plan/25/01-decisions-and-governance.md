# 01 — 決策全文與治理（D77–D90）

> [`00`](./00-execution-plan.md) §0 說的是**要不要**與**不同意的話會怎樣**。
> 這裡說的是**決定之後程式碼變成什麼樣子**，以及每一項落在哪一份 ADR。

## 0. 治理

三條規則，沿用前兩期：

1. **A 類未裁決前，相關 ticket 不開工。** 不是流程潔癖：D78 決定 `KN-08` 的交付物是
   一個 renderer 還是一個 endpoint，猜錯要重做兩張 ticket 的測試。
2. **裁決要留原文，包含當時放棄了什麼。** 三個月後沒有人會想知道選了什麼，
   但每個人都會想知道當時放棄了什麼（`plan/23/00` §0.1 的原話）。
3. **實作與決策不一致時，改決策或寫 waiver，不默默實作。**
   不一致寫進 [`11`](./11-implementation-status.md) §2 並回寫這裡。

ADR 對應：

| ADR | 標題 | 承載的決策 | ticket |
|---|---|---|---|
| **0038** | Project Knowledge 的來源、權威層級、project isolation 與保留 | D40、D45、D58、**D77**、**D79**、**D80**、**D81**、D85、D86、D88、D89、D90 | `KN-01` |
| **0039** | Context Builder：instruction／evidence 分層與 budget policy | D47、**D78**、D84 | `KN-08` |
| 0041（既有） | Conversation 的保留、附件與大小 | **只加一行交叉引用**，內容不動（D81） | `KN-01` |

`0040` 保留給 `beta.1` 的 work lifecycle（`research/03` §5 的清單），本期不用。

---

## 1. A 類全文

> **五項全部於 2026-08-22 裁決，全部採納計畫的答案。**
> 內文保留當時的論證與放棄的選項。

### ☑ D77 — repo 內容從 run 裡面推上來（2026-08-22 裁決：採納）

**決定**：`alpha.3` 的 repo knowledge 由 run 內的 `cliora knowledge sync` 推送。
Central **沒有**任何主動取得 repo 內容的路徑。

**程式碼後果**：

```text
新增   backend/app/services/knowledge/repo.py      manifest 比對、exclude 規則、tombstone
新增   POST /api/cli/runs/knowledge/repo-manifest  run token；回傳「我要哪些 path」
新增   POST /api/cli/runs/knowledge/repo-content   run token；上傳缺的檔案內容
新增   daemon/internal/cli/knowledge.go            走檔案樹、算 sha256、兩次呼叫
不動   backend/app/services/files.py               relay 的授權路徑一行都不改
不動   daemon/internal/runner/                     工作目錄的建立與 git fetch
不動   contracts/                                  零 diff
```

**權限與範圍**：run token 的 `project.view` 只允許它同步**自己 task 所屬 project**
的 repo，而 `source_external_id` 是 `<repository_id>:<path>`、`source_version` 是 commit SHA。
一個 run 不能替別的 project 同步——`_own_task()` 已經在做這件事，新端點沿用。

**三個要在 `KN-06` 處理的邊界**：

1. **同一個 commit 被兩個 run 同步。** 唯一鍵 `(project, source_type, external_id, version)`
   讓第二次是 no-op；`ON CONFLICT DO UPDATE WHERE excluded.source_updated_at > current`
   讓比較舊的 commit 不會覆蓋比較新的。
2. **檔案在新 commit 消失。** manifest 是**全量**的（不是 diff），
   所以 Central 可以算出「上次有、這次沒有」→ tombstone。這是 J12 的一半。
3. **force-push 讓 commit 不再是祖先。** 不特別處理：manifest 全量比對本來就不依賴
   commit 的祖先關係。這一句要寫進 ADR，因為它是「為什麼不需要處理 force-push」的答案。

**已知取捨（進 known limitations）**：沒跑過 Agent 的 Project 沒有 repo knowledge；
repo 新鮮度的上限是最近一次 run 的 commit。Source health 面板必須顯示這件事。

---

### ☑ D78 — context pack 走 HTTPS 拉，不走 offer（2026-08-22 裁決：採納）

**決定**：`run.offer.context` 只增加一個 **policy digest**（≤ 1.5 KiB，永不裁切）
與一行取用指引。完整五層 pack 由 `GET /api/cli/runs/context-pack` 提供。

**程式碼後果**：

```text
services/runs.py::_context_for()   在既有 renderer 的回傳值後 append 一段
                                   → 不新增 renderer、不加 flag、gate 形狀不變
services/knowledge/context.py      ContextBuilder：五層、budget、manifest
GET /api/cli/runs/context-pack      run token；回 markdown ＋ manifest；寫 context_packs
```

**為什麼 `_context_for()` 這一行不觸發 `GATE-RQ-CONTEXT-DISPATCH`**：
那個 gate 斷言的是「三個（現在四個）renderer 的呼叫者只有 `_context_for`」。
append 一段字串既不是新 renderer 也不是新呼叫者。`CV-09` 當時必須加第四個 renderer，
是因為 continuation 要**改寫整個包的結構**；policy digest 只是接在後面。
`KN-08` 的測試要包含「四個 renderer 的輸出各自 append 之後都仍 < 8 KiB」。

**`context_packs` 在拉取時寫入，不在 offer 時寫入。** 兩個理由：
① 它要記錄的是「Agent 實際讀到什麼」，而 offer 時還不知道 Agent 會不會來拉；
② 一個 run 可能拉多次（retry、續跑），每次的 `built_at` 與 manifest 都是不同的事實。
唯一鍵是 `(run_id, turn_seq, built_at)`——**刻意不做 upsert**，因為兩次拉取讀到不同內容
正是要被看見的事情。

**Budget 上限**：pack 本體 64 KiB（HTTP 回應，不受 wire 限制），
分層預算與裁切順序寫死在程式碼裡並有測試（[`06`](./06-context-builder.md) §3）。

---

### ☑ D79 — tokenizer 是純函式，index 與 query 共用（2026-08-22 裁決：採納）

**決定**：新增 `services/knowledge/tokenize.py`，一個純函式：

```python
def lexemes(text: str) -> list[str]:
    """索引與查詢的唯一分詞來源（D79）。

    輸出三類 token：
      * CJK bigram        「租約過期」→ 租約 約過 過期
      * ASCII 詞          小寫化、長度 ≥ 2
      * identifier 切分   lease_expires_at → lease expires at（原詞也保留）
    """
```

`search_document` 由 `to_tsvector('simple', ' '.join(lexemes(title)))` 加權 A
與 `to_tsvector('simple', ' '.join(lexemes(body)))` 加權 B 串接而成，
**在 Python 端組好 SQL 表達式送出**（不是觸發器、不是 GENERATED 欄——
`to_tsvector` 是 STABLE，PostgreSQL 會拒絕）。

查詢端用同一個函式的輸出組 `tsquery`：CJK bigram 之間用 `<->`（phrase，相鄰）
或 `&`（全含），ASCII 詞用 `&`。**兩種都要有測試**，因為 phrase 對長句準、
`&` 對短句與混合句準，而哪一種當預設是 `KN-13` 的 relevance eval 要回答的。

**`GATE-KN-ONE-TOKENIZER`**：AST 斷言 `to_tsvector`／`plainto_tsquery`／`to_tsquery`
這幾個名字在 `backend/app/` 只出現在 `services/knowledge/search.py`，
且該模組取得 lexeme 的唯一來源是 `tokenize.lexemes`。
違反它的症狀是**永遠查不到而且不報錯**——這個 repo 已經付過一次同類的學費
（`plan/23/10` §9.1：daemon 寫 `run.token`、CLI 讀 `<id>.token`，兩邊單測都綠）。

**bigram 而不是 trigram 或 unigram**：unigram 對中文的精確度太低（「期」會命中一切），
trigram 讓「租約」這種兩字詞查不到。bigram 是中文檢索的既有共識，
而 `pg_trgm` 那條通道仍然獨立存在，負責 SHA、function name、typo。

---

### ☑ D80 — job 是實體鍵，入列點只有一個（2026-08-22 裁決：採納）

**決定**：

```python
# services/activity.py::ActivityService.record()  末尾
await KnowledgeOutbox(self._session).note(
    project_id=project_id, kind=kind, task_id=task_id, payload=body
)
```

`note()` 內部：

```text
1. kind 不在 _INGEST_MAP → return（O(1) dict 查表）
2. project 的 knowledge_enabled 為 false → return（快取 60 秒，見 03 §2.3）
3. 算出 (source_type, external_id)，INSERT knowledge_jobs … ON CONFLICT
   (project_id, source_type, external_id) WHERE state='pending' DO NOTHING
```

第 3 步的 `ON CONFLICT DO NOTHING` 讓「一秒內同一張卡被改五次」只留一列 pending job，
而 worker 領到時讀的是**最後的狀態**。這是「job 是提示」這個決定的直接紅利。

**worker 的一輪**（沿用 `RunReaper` 的形狀：先 reconcile 一次再進迴圈、一輪多個交易、每輪有上限）：

```sql
UPDATE knowledge_jobs SET state='running', attempts=attempts+1, updated_at=now()
WHERE id IN (
  SELECT id FROM knowledge_jobs
  WHERE state='pending' AND (next_attempt_at IS NULL OR next_attempt_at <= now())
  ORDER BY created_at LIMIT 32
  FOR UPDATE SKIP LOCKED
) RETURNING *;
```

**沒有游標，所以沒有「先開始後提交」的漏行問題**（`activity_events.id` 是 uuid4、
`occurred_at` 是交易開始時間——見 [`00`](./00-execution-plan.md) §0.1 D80 的表）。

**`_INGEST_MAP` 的覆蓋率是一個測試而不是一份清單**：
`test_every_ingestable_source_type_has_at_least_one_activity_kind` 對
`SOURCE_TYPES`（本期八種）逐一斷言映射表裡有它。新增一種 source 卻忘記映射 → 測試紅。

---

### ☑ D81 — knowledge 的保留寫進 ADR 0038 §6（2026-08-22 裁決：採納）

**決定**：見 [`00`](./00-execution-plan.md) §0.1。這裡只補三個實作細節：

1. **`active` 與 `deleted_at` 是兩件事。** `active=false` 是「不進預設 retrieval」
   （`knowledge_enabled` 關閉、來源被 exclude、被 supersede）；
   `deleted_at` 是「這個來源已經不存在」（repo 檔案消失、artifact 被刪）。
   兩者都不刪列——**刪列會讓舊 context manifest 的引用變成懸空**，
   而 manifest 存的是 ID ＋ metadata，正是為了在這種時候還能說出「這個來源已被刪除」。
2. **cascade 的測試對象是約束不是行為。** `projects` 現在只有 archived、沒有 delete，
   所以測試直接 `DELETE FROM projects WHERE id=…` 並斷言六張表都空了。
   ADR 要寫明「這是為了未來有 delete 的那一天預先成立」。
3. **匯出延到 `beta.2`**，並且要在 known limitations 寫一句
   「knowledge 目前沒有匯出路徑」——空的限制清單需要解釋，不是好消息。

---

## 2. B 類全文

### D82 — Knowledge UI 落在新的 `modules/knowledge/`

`research/03/09` 的目標結構把 `ProjectKnowledgeView.vue` 放在 `modules/project/views/`，
而模組化重構本身是 `beta.1` 的 `PX-64`。兩者不衝突，因為：

> **`PX-64` 的困難是「既有頁要在旗標兩種狀態下都能用」。新頁沒有舊版對照，
> 所以它不需要雙路徑，可以直接生在新結構裡。**

本期建立：

```text
frontend/src/modules/knowledge/
  views/ProjectKnowledgeView.vue
  components/KnowledgeSearch.vue  SourceList.vue  SourceHealth.vue
             DecisionColumns.vue  RecentlyLearned.vue  CitationLink.vue
             RelatedKnowledgePanel.vue
  queries.ts        useAsyncResource 的薄封裝（不是新的 query 層）
```

**`queries.ts` 不是 `PX-27` 的 query 層。** 那 300 行是 `beta.1` 的工作。
本期只有五個唯讀資源 ＋ 三個 mutation，用既有 `useAsyncResource` 直接寫，
`modules/knowledge/queries.ts` 只是把 key 與失效集中在一個檔案，方便 `beta.1` 接管。
**若這個檔案開始長出 retry policy 或快取層，那是提前做 `PX-27`，要停下來。**

路由：`/projects/:id/knowledge`（新的 top-level route，不是 `ProjectDetailView` 的頁籤）。
理由：`ProjectDetailView.vue` 已經 1515 行同時管 12 件事，再加一個頁籤會讓
`beta.1` 的拆分更貴。

### D83 — Related knowledge 掛在 `TaskDetailView.vue`

上游規劃寫「Task Drawer 另加 Related knowledge 區塊」。**Drawer 不存在**——
`beta.1` 的 `PX-*` 才建它。現在的宿主是 `views/TaskDetailView.vue`（145 行），
它已經內嵌 `ConversationPanel`，位置在它下方。

`beta.1` 的 `PX-62` 把同一個元件搬進 Drawer。**元件的 props 只有 `taskId`**，
所以搬家是一行 import——這正是為什麼它是元件而不是寫在頁面裡。

### D84 — chunk 800／100，token 用字元近似

```python
def approx_tokens(text: str) -> int:
    """CJK 一字≈一 token，ASCII 四字元≈一 token。"""
```

**不引入 tokenizer 套件**：`backend/pyproject.toml` 不新增依賴是 SR-2 的可過條件之一
（「Central 未新增對外連線」的證據是「無新依賴」），而一個 tokenizer 套件雖然不連外，
會讓那條證據需要解釋。近似值的誤差對 800/100 的分塊決策無關緊要——
它決定的是「切在哪」，不是「送多少給誰」。

真正的預算（[`06`](./06-context-builder.md) §3）用**位元組**計算，
因為 wire 與 HTTP 的限制都是位元組。

列入 [`10`](./10-open-measurements.md) 第 3 項。

### D85 — 十級 authority 全建，八級有寫入者

| authority | 本期有寫入者？ | 誰寫 |
|---|---|---|
| `authoritative` | ✅ | 人工標記為正式決策（`project.manage`）、Project charter |
| `accepted` | ✅ | accepted spec、approved requirement（`requirements.py` 既有路徑） |
| `canonical` | ✅ | repo 檔案 at commit（D77） |
| `verified` | ✅ | `verification_reports.result='pass'`、`evidence_items` 的機器來源 |
| `reviewed` | ❌ | **等 `beta.2`**：已審 PR／MR |
| `generated` | ✅ | Agent proposal、turn summary |
| `discussion` | ✅ | Ticket 對話 |
| `diagnostic` | ✅ | 人類選定的 log excerpt（**只有人選的**） |
| `superseded` | ✅ | supersede 時由 pipeline 改寫 |
| `retracted` | ✅ | 人工撤回（`project.manage`） |

**不刪級。** 上游的未量測項第 4 條（「十級是否過細」）要真實使用才知道，
而合併容易、拆開難：一個曾經寫成 `discussion` 的列，事後拆不回
「這其實是 accepted」。ADR 0038 要有這張表，並註明兩個空級的填補時機。

### D86 — worker 併行，reconciler 單飛

ingestion worker 的一輪本來就靠 `SKIP LOCKED` 安全，多副本併行**是想要的**
（吞吐量隨副本數線性）。reconciliation 不同：它是「掃每張來源表找漏掉的」，
N 個副本各掃一次是 N 倍的成本、零倍的收益。

```python
if not await conn.scalar(sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": _RECONCILE_LOCK}):
    return   # 另一個副本正在做
```

`_RECONCILE_LOCK` 是一個寫死的常數。這是本 repo 第一次用 advisory lock，
所以 ADR 要記一句「為什麼不用一張 leader 表」：advisory lock 隨連線自動釋放，
一個被 kill -9 的 Central 不會留下一個永久的 leader 列。

### D87 — `agentd` 0.14.0，節點半邊零 diff

`daemon/VERSION` 0.13.1 → 0.14.0，只動 `internal/cli/`。
`GATE-KN-CONTRACT-FROZEN` 對 `contracts/v1/` 取全樹 sha256（沿用
`GATE-CV-CONTRACT-FROZEN` 的實作，只換基線目錄）；
`GATE-KN-TOUCH-LIST` 對 `daemon/internal/{protocol,runner,connection,workspace,gitfetch}` 斷言零 diff，
並且**同時問 `git status --porcelain --untracked-files=all`**——
`plan/23/10` §9.1 記錄過只問 `git diff` 的洞（從沒被 add 過的新檔案不在 diff 裡）。

`contracts/CHANGELOG.md` 要有一段「本期不動及理由」，
而它**不在 sha256 的範圍內**（範圍是 `contracts/v1/`）——
一個會被解釋文字弄紅的 gate，會用刪掉解釋來變綠。

### D88 — repo sync 的四個上限

| 上限 | 值 | 逾限行為 |
|---|---|---|
| 候選檔數 | 800 | `KNOWLEDGE_SYNC_TOO_LARGE`，`details.limit="files"`、`details.count=N` |
| 單檔大小 | 256 KiB | 該檔跳過並列入回應的 `skipped[]`，**不失敗整次 sync** |
| 單次上傳總量 | 8 MiB | `KNOWLEDGE_SYNC_TOO_LARGE`，`details.limit="bytes"` |
| 每 project 每小時 sync 次數 | 12 | `429`，`Retry-After` |

**單檔逾限只跳過、總量逾限才失敗**，這個不對稱是刻意的：
一個 repo 裡有一個 5 MB 的 CHANGELOG 不該讓整個專案沒有 knowledge，
但一次 sync 想傳 200 MB 是設定錯誤，而靜默截斷會讓它看起來像成功。

### D89 — `context_packs` 隨 run CASCADE

`context_packs.run_id` 是 `ON DELETE CASCADE`。理由與 ADR 0041 的分類一致：

```text
run log          診斷資料，有保留期
context pack     「這個 turn 讀了什麼」— 診斷資料，與 run 同生命週期
conversation     產品資料，永久
knowledge source 產品資料的衍生，與來源同生命週期
```

**代價**：一個很舊的 turn 的 manifest 會隨 run 的 retention 消失，
於是「三個月前那次 Agent 為什麼這樣做」在 log 被清掉之後也答不出來。
接受它的理由是：那個問題的答案在 conversation 裡（Agent 說了什麼、引用了什麼），
而引用是訊息內容的一部分，訊息永久保留。**manifest 是 debug 工具，引用才是紀錄。**

### D90 — 查詢字串不留痕

| 面 | 記什麼 |
|---|---|
| audit | **不記**（`research/03/08` §7 的「不記」清單已列入） |
| metric label | **不記**。`app/metrics.py` 的 module docstring：metric 是唯一沒有 redaction 的 sink |
| log | `_keyword_digest(query)`（沿用 `services/files.py:162`）＋ 長度 ＋ 結果數 |
| DB | **不存查詢歷史。** 沒有 `knowledge_queries` 表 |

一個查詢字串會包含使用者正在想什麼，而它沒有稽核價值——
`services/files.py` 已經替 `filesystem.search` 做過同一個判斷，本期沿用同一個函式。

### D91 — 0.14.0 沒發出去過，於是它變成 0.14.1

D87 為 `knowledge` 子命令切了 0.14.0，而它**從未 tag、從未建出 artifact**
（`docs/release-note-project-memory.md` 的 `Status: not tagged`、
`.goreleaser.yaml` 的 `release.disable: true`）。在它出去之前，
同一個 `internal/cli/` 又收了第二個改動：CLI 現在能分辨裸 404 與「被拒絕」，
不再對兩者都印 `請求被拒絕（HTTP 404）`。

於是**沒有任何一個 artifact 只帶第一個改動**。
把兩者一起叫 0.14.0，等於讓版本號描述一個沒人拿得到的 binary；
`daemon/VERSION` 因此走到 `0.14.1`。

| 面 | 影響 |
|---|---|
| `GATE-KN-TOUCH-LIST` | **不受影響**。禁區是 `daemon/internal/{protocol,runner,connection,workspace,gitfetch}`，`internal/cli/` 不在其中 |
| D87 的「節點半邊零 diff」 | **仍然成立**，兩個改動都只在 `internal/cli/` |
| Central 能力判斷 | `RunService._daemon_has_knowledge_cli()` 比的是 `node.daemon_version >= 0.14.0`，`0.14.1` 通過。**版本以整數 tuple 比較**（見 [`07`](./07-cli-and-agent-contract.md) §5），這裡正是那個判斷要付出代價的地方 |
| 要改的地方 | `daemon/VERSION` 與 `cmd/agentd/main.go` 的 `version` 兩處，由 `TestVersionMatchesTheVersionFile` 綁住（`plan/23/10` §2.12） |

**代價**：`plan/25` 全篇寫的是 0.14.0，而發出去的是 0.14.1。
這份決策就是那個落差的紀錄——**沒有回頭改 `plan/25` 的其他文件**，
因為那些是當期的計畫，不是發版事實；發版事實在 release note。

但 ADR 0038／0039 的 `Ships in:` **是**發版事實，不是計畫，
所以那兩行改成 0.14.1——否則它們指著一個永遠不會存在的版本。
同理，`backend/` 那邊寫的 `>= 0.14.0` **一個都不動**：
那是門檻不是版本，而 0.14.1 過得去。
