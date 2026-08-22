# 08 — 前端（`KN-10`／`KN-11`）

> **這一塊是提案裡最重要卻最容易被砍掉的功能。** 理由（上游 §8 原話）：
> **retrieval 若是不可見的黑盒，「Agent 為什麼這樣做」就永遠無法回答。**
> 它同時是 debug 工具與信任機制。

## 1. 落點（D82／D83）

```text
frontend/src/modules/knowledge/            ← 新目錄，本 repo 第一個 modules/
  views/ProjectKnowledgeView.vue
  components/
    KnowledgeSearch.vue        查詢框 ＋ 結果清單 ＋ authority 徽章
    SourceList.vue             五類來源的同步狀態與筆數
    DecisionColumns.vue        accepted / superseded / conflicting 三欄
    RecentlyLearned.vue        最近 ingest／更新
    SourceHealth.vue           last sync / job lag / failed / dead letter age
    CitationLink.vue           一個引用 → 一個可點的去處（或不可點的 repo:// 文字）
    RelatedKnowledgePanel.vue  KN-11，宿主是 TaskDetailView
    SourceVersionDiff.vue      版本比較
  queries.ts
```

路由：`/projects/:id/knowledge`（top-level，不是 `ProjectDetailView` 的頁籤）。
`ProjectDetailView.vue` 已經 1515 行同時管 12 件事，再加一個頁籤會讓 `beta.1` 的拆分更貴。

**`queries.ts` 不是 `PX-27` 的 query 層。** 本期只有五個唯讀資源 ＋ 三個 mutation，
用既有 `useAsyncResource` 直接寫，這個檔案只集中 key 與失效。
**若它開始長出 retry policy 或快取層，那是提前做 `PX-27`，要停下來**（D82）。

## 2. Knowledge 頁的五個區塊

### 2.1 Search

```text
[ 查詢框                                    ] [搜尋]
篩選：來源類型 ▾   可信層級 ▾   □ 含已被取代的版本

[S1] accepted    ADR 0029 §5 租約與重排                      2026-07-02
     …命中片段（高亮）…
     為什麼：全文命中「租約」「重排」· accepted 加權 · 同 Epic
     ↳ 開啟來源 · 標為正式決策 · 從這張卡排除

12 筆結果 · 87 ms · 通道：全文 ＋ 模糊
```

三個必須有的元素：

| 元素 | 為什麼 |
|---|---|
| **authority 徽章**（含顏色與文字） | 「accepted 勝過 generated」是本期的核心承諾之一，而使用者要看得出來 |
| **版本** | 一個沒有版本的引用回答不了「這是不是最新的」 |
| **「為什麼」一行** | `manifest.why` 的渲染。**這是把黑盒打開的那一行**，不是裝飾 |

`include_history` 是一個 checkbox 而不是預設：歷史版本會讓結果數倍增，
而 `superseded` 的內容看起來與 accepted 一樣可信。勾選時該列的徽章變灰 ＋ 加「已被取代」。

### 2.2 Sources

五列（ticket／conversation／decision／artifact＋verification／repo_doc），
每列：筆數、最後 ingest 時間、狀態。**筆數來自 `knowledge_sources.chunk_count` 的聚合**
（[`02`](./02-data-layer.md) §2.1 加那一欄的理由）。

repo_doc 那一列特別：顯示 **`最後同步：139f143（3 天前，來自 TK-142 的 run）`**。
D77 的已知取捨（沒跑過 Agent 的 project 沒有 repo knowledge）必須在這裡看得出來：

```text
repo 文件    0 筆    ⚠ 從未同步
             repo 內容由 Agent 在 run 裡推送。這個專案還沒有跑過 run，
             或 run 裡沒有執行 `cliora knowledge sync`。
```

★ **一個看不出自己是空的知識庫比沒有知識庫更糟。** 這段文字是 D77 的驗收條件之一。

### 2.3 Decisions

三欄：`accepted`／`superseded`／`conflicting`。

`conflicting` 的定義（**本期唯一一個需要定義的衍生概念**）：
同一個 `external_id` 家族下有兩個都是 `accepted`／`authoritative`
且沒有 supersede 關係的來源。**不自動解決**——沿用 `EvidenceItem` 的
「Contradictions are stored, not resolved」：顯示兩者、標出來、讓人決定。

★ 若本期的資料模型下 `conflicting` 恆為空（因為 supersede 是自動的），
**這一欄要顯示「目前沒有偵測到衝突」而不是被移除**，
並在 [`11`](./11-implementation-status.md) 記錄它是否真的出現過。
一個永遠是空的欄位是一個要在 `beta.1` 決定去留的東西，不是一個 bug。

### 2.4 Recently learned

最近 20 筆 ingest／更新，含「新增」與「更新」的區別
（[`03`](./03-ingestion-and-outbox.md) §4 的 `xmax = 0` 就是為了這個）。

用途不是好看：它是使用者判斷「我剛剛接受的那份規格進去了沒」的地方，
而那正是 ingest freshness（P95 < 10s）在畫面上的樣子。

### 2.5 Source health

| 指標 | 來源 | 什麼時候要紅 |
|---|---|---|
| pending job 數 | `KNOWLEDGE_PENDING_JOBS` | > 1000 |
| ingest lag P95 | `KNOWLEDGE_INGEST_LAG_SECONDS` | > 60s |
| failed job 數 | `knowledge_jobs.state='failed'` | > 0（黃） |
| **dead letter age** | `KNOWLEDGE_DEAD_LETTER_AGE_SECONDS` | > 1 小時（紅） |
| repo 最後同步 | `knowledge_sources` 的 max | > 14 天（黃） |
| 初次建索引進度 | pending 與 watermark 的差 | — |

`last_error` 顯示在 dead letter 展開後。它只有型別名稱與一行訊息
（[`03`](./03-ingestion-and-outbox.md) §5），因為這個面板的讀者只需要 `project.view`。

## 3. 六個操作

| 操作 | 權限 | 確認？ | audit |
|---|---|---|---|
| 開啟／關閉 `knowledge_enabled` | `project.manage` | 關閉時要 | ✔ |
| 標為正式決策（→ `authoritative`） | `project.manage` | — | ✔ |
| 撤回（→ `retracted`） | `project.manage` | ✔ | ✔ |
| 從某張卡排除 | `project.manage` | — | ✔ |
| 重新同步（resync） | `project.manage` | — | ✔ |
| 比較版本 | `project.view` | — | ✗ |

**不做「刪除來源」的 UI**：刪除是 D81 的獨立動作、要二次確認，
而它在本期沒有使用者需求（`knowledge_enabled=false` 已經處理了「我不要這個功能」）。
API 端也不做——沒有端點比有一個危險的端點好。

## 4. `KN-11`：Related knowledge（D83）

宿主：`views/TaskDetailView.vue`，位置在 `ConversationPanel` 之下。
`beta.1` 的 `PX-62` 把同一個元件搬進 Drawer——**props 只有 `taskId`**，所以搬家是一行 import。

```text
▾ 這張卡的專案記憶（Agent 目前會讀到的 8 個來源）

  📌 [S1] accepted   ADR 0029 §5 租約與重排        （已釘選）  移除釘選
     [S2] canonical  supervisor.go                為什麼：模糊命中「lease」 · canonical 加權
     [S3] discussion TK-140「這裡的 24 小時」      為什麼：dependency 鄰居
  …
  ＋ 釘選一個來源（搜尋）              最近一次組裝：2 分鐘前 · 41 KB · 省略 6 個（預算）
```

四個性質：

1. **顯示的就是 Agent 會讀到的**——資料來自最近一次 `context_packs` 的 manifest，
   沒有的話即時算一次（不寫列）。**不是另一組排序邏輯**：
   兩套排序會在某一天分歧，而分歧的那一天沒有人看得出來。
2. **「為什麼」一定要有**（`manifest.why`）。
3. **pin／exclude 立即生效於下一個 turn**，不影響已經組好的 pack。
4. **省略要說出來**：「省略 6 個（預算）」是 `omitted_json` 的渲染。

★ 上游把這一塊描述成「Task Drawer 的區塊」。Drawer 不存在（D83），
而**這個區塊比 Drawer 重要**——它是「Agent 為什麼這樣做」的唯一答案，
所以它不能等 `beta.1`。

## 5. 狀態

| 狀態 | 位置 | 理由 |
|---|---|---|
| 查詢字串 | **URL**（`?q=`） | 「你看一下這個查詢」是真實需求 |
| 篩選（type／authority／history） | **URL** | 同上 |
| 展開的來源 id | URL（`?source=`） | 可分享、可重整 |
| Related knowledge 的展開／收合 | local transient | 純視覺 |
| 查詢歷史 | **不存**（D90） | 查詢字串會包含使用者正在想什麼 |

## 6. Token（＋4）

`frontend/src/theme/tokens.css` 從 58 個加到 62：

```css
--authority-high:   /* authoritative / accepted / canonical */
--authority-mid:    /* verified / reviewed */
--authority-low:    /* generated / discussion / diagnostic */
--source-stale:     /* superseded / retracted / 過期未同步 */
```

**三階而不是十階。** 十個 authority 各一個顏色的結果是十個難以區分的顏色，
而使用者要區分的其實是「這是規則／這是觀察／這是有人說的」。
文字標籤帶精確等級，顏色只帶三階。
`checkTokens.test.ts` 會自動涵蓋新 token 的對比度。

## 7. 測試（`KN-10`／`KN-11`）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `ProjectKnowledgeView` 在 `knowledge_enabled=false` 時 | 顯示啟用引導，**不顯示空的搜尋框** |
| 2 | 搜尋結果每一列都有 authority 徽章與版本 | 結構斷言 |
| 3 | 「為什麼」那一行存在且來自 `why` | 不是前端重算 |
| 4 | `include_history` 勾選後歷史列有「已被取代」標記 | |
| 5 | repo 從未同步時顯示 D77 的說明文字 | §2.2 |
| 6 | dead letter age > 1h 時 Source health 是紅的 | |
| 7 | `RelatedKnowledgePanel` 的清單來自 manifest 而非自算 | mock 兩者不同 → 顯示 manifest 的 |
| 8 | pin 之後樂觀更新，失敗回滾 | `useAsyncResource` 的 mutate |
| 9 | 無 `project.manage` 時六個操作只剩「比較版本」 | 權限 |
| 10 | `repo://` 的引用是純文字 ＋ 複製按鈕，不是連結 | [`04`](./04-sources-and-authority.md) §4.1 |
| 11 | 查詢字串不進任何 localStorage／store | D90 |
| 12 | `?seq=18` 讓 `TaskDetailView` 滾到那一則訊息 | citation 的落點 |
