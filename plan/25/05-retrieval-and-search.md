# 05 — 檢索（`KN-07`）

> **這一章的核心不是 SQL，是那個 tokenizer。** 沒有它，本產品的主要語言
> （繁體中文）在 full-text 通道上完全搜不到，而**搜不到不會報錯**。

## 1. Tokenizer（D79）

### 1.1 問題

PostgreSQL 沒有 CJK parser。`postgres:16-alpine` 只有內建設定，
而 `simple`／`english` 的 parser 以非字元邊界切詞：

```text
to_tsvector('simple', '租約過期時要怎麼處理')
  →  '租約過期時要怎麼處理':1          ← 一個 lexeme
to_tsquery('simple', '租約')
  →  '租約'                            ← 永遠不會命中上面那一個
```

於是「full-text 擅長一般語句」這句話對本產品不成立。
**這不是效能問題，是零召回。**

### 1.2 解法

```python
# app/services/knowledge/tokenize.py     純函式，零 I/O，唯一的分詞來源（D79）

_CJK = r"㐀-䶿一-鿿豈-﫿぀-ヿ"

def lexemes(text: str) -> list[str]:
    """索引與查詢共用。三類輸出：

    CJK bigram      「租約過期」→ ['租約', '約過', '過期']
    ASCII 詞         小寫、長度 ≥ 2、保留數字與底線／點／連字號的原形
    identifier 切分  lease_expires_at → ['lease_expires_at','lease','expires','at']
                     LeaseExpiresAt   → ['leaseexpiresat','lease','expires','at']
                     CV-05            → ['cv-05','cv','05']
    """
```

四個性質，每一個都有測試：

| 性質 | 測試 |
|---|---|
| 純函式、可重入 | 同輸入同輸出，無 I/O |
| index 與 query 同一個來源 | `GATE-KN-ONE-TOKENIZER` |
| CJK 與 ASCII 混排正確切開 | `'處理 lease_expires_at 逾時'` → 兩組都出現 |
| **單字 CJK 查詢有定義的行為** | 「期」只有一個字，沒有 bigram → 退回 trigram 通道，且**回應要說它退回了** |

最後一項是本節唯一一個對使用者可見的行為：一個單字中文查詢在 bigram 索引上
沒有 lexeme 可比，於是它只走 trigram。回應帶
`"channels": ["trigram"]`，UI 顯示「單字查詢：只做模糊比對」。
**不靜默降級**——靜默降級的結果是使用者以為系統沒有那份資料。

### 1.3 寫入

```python
doc = sa.func.setweight(sa.func.to_tsvector("simple", " ".join(lexemes(title))), "A").op("||")(
      sa.func.setweight(sa.func.to_tsvector("simple", " ".join(lexemes(body))),  "B"))
```

`'simple'` 而不是 `'english'`：english 會做 stemming 與 stop word 移除，
而我們送進去的已經是自己切好的 token——再 stem 一次會把 `expires` 變 `expir`，
而查詢端如果 stem 不一致就又是零召回。**`simple` 只做小寫化，那正是我們要的。**

### 1.4 查詢

```text
CJK bigram   b1 <-> b2 <-> b3            相鄰（phrase）
             或 b1 & b2 & b3             全含
ASCII 詞      w1 & w2
兩者之間      &
```

`phrase` 對長句準（「租約過期時要怎麼處理」的 bigram 序列相鄰才是那句話），
`&` 對短句與混合句準。**兩種都實作、都有測試，預設用 `&`**，
理由：`alpha.3` 的資料量下召回比精確重要，而 rerank 會把真正相關的推上來。
`KN-13` 的 relevance eval 會給出換不換的依據，換的話寫進 [`11`](./11-implementation-status.md)。

## 2. 三個通道 ＋ rerank

```text
score = w_fts  × ts_rank_cd(search_document, query)
      + w_trgm × similarity(content, raw_query)
      + w_graph × graph_boost(source)
      ────────────────────────────────
      × authority_weight(authority)
      × freshness_decay(occurred_at, source_type)
      + pin_bonus
```

### 2.1 通道

| 通道 | SQL | 擅長 | 權重 |
|---|---|---|---|
| Full-text | `search_document @@ query`，`ts_rank_cd` | 一般語句（中文靠 §1 的 bigram） | `w_fts = 1.0` |
| Trigram | `content % :q`，`similarity()` | `CV-05`、function name、commit SHA、error code、typo | `w_trgm = 0.8` |
| Graph | `knowledge_links` ＋ 同 Epic ＋ dependency | 「跟這張卡有關的東西」 | `w_graph = 0.6` |

**兩個通道各自取 top-K（K=50）再 union**，不是一個 SQL 把兩個條件 OR 起來。
理由：OR 起來 PostgreSQL 只會用一個索引，而兩個 GIN 各自掃自己的 top-K
再合併是兩次索引掃描 ＋ 一次小集合的合併。

`similarity()` 需要 `pg_trgm`；`%` 運算子的門檻用
`set_limit(0.25)`（**per-connection**，所以要在同一個 session 內設，
或改用 `similarity(content, :q) > 0.25` 顯式比較——後者不吃 GIN 索引，
所以**用 `%` 並在連線上設門檻**，並寫一個測試斷言門檻真的生效）。

### 2.2 Authority 權重

| authority | 權重 |
|---|---|
| `authoritative` | 1.60 |
| `accepted` | 1.45 |
| `canonical` | 1.35 |
| `verified` | 1.25 |
| `reviewed` | 1.15 |
| `generated` | 0.85 |
| `discussion` | 0.75 |
| `diagnostic` | 0.60 |
| `superseded` | **排除** |
| `retracted` | **排除** |

**排除不是權重 0。** 權重 0 的列仍然會被算、會佔 top-K 的名額、
會在某個 join 之後意外出現。排除寫在 `WHERE` 裡：

```sql
WHERE s.active AND s.deleted_at IS NULL
  AND s.authority NOT IN ('superseded','retracted')   -- 除非 include_history
```

### 2.3 Freshness

```python
half_life = {"conversation": 30, "ticket": 60, "activity": 30,
             "repo_doc": 180, "verification": 90,
             "decision": 365, "policy": 3650}   # 天
decay = 0.5 ** (age_days / half_life[source_type])
weight = 0.5 + 0.5 * decay        # 下界 0.5：舊不等於錯
```

★ 下界是本期加的。純指數衰減會讓一份三年前的 charter 的權重趨近 0，
而 charter 正是最不該衰減的東西——所以 `policy` 的半衰期是十年，
而**所有來源都有 0.5 的地板**。一個沒有地板的衰減函式等於「舊資料會消失」，
而那不是產品要的行為。

### 2.4 Graph boost 與 pin

| 條件 | 加分 |
|---|---|
| 同一個 Epic 底下的卡 | +0.20 |
| `task_dependencies` 的直接鄰居 | +0.30 |
| `knowledge_links` 有 `references`／`verifies`／`delivers` 指向查詢卡的來源 | +0.25 |
| **人工 pin**（`task_knowledge_pins.mode='pin'`） | **+2.00** |
| **人工 exclude** | **排除** |

pin 的加分刻意大到「一定進 top-N」。理由：pin 是人在說
「不管你的分數怎麼算，這張卡要看這個」，而一個可以被分數推掉的 pin 不是 pin。
D40 的取捨（沒有向量檢索、語意相近但用詞不同的查詢第一版找不到）
就是靠 pin 與 `knowledge_links` 補的——所以它必須真的有效。

## 3. `include_history`

```text
GET /api/projects/{id}/knowledge/search?q=…&include_history=true
```

只有這個旗標會讓 `superseded`／`retracted` 出現，而它們在回應裡**帶明確標記**
（`"historical": true` ＋ authority 徽章變灰）。
**Context Builder 永遠不設這個旗標**——一個 turn 讀到已被取代的規格是
本期最需要避免的失敗，而它比「找不到」難發現得多。

`GATE-KN-*` 之外的一個 pytest 斷言：
`test_context_builder_never_requests_history`。

## 4. Isolation predicate

**每一個查詢的第一個條件。** 不是最後一個過濾，不是 UI 層的過濾。

```python
def _scope(stmt, project_id: uuid.UUID):
    """所有 knowledge 查詢的唯一入口。GATE-KN-PROJECT-SCOPED 斷言
    knowledge_* 的每一個 select 都經過它。"""
    return stmt.where(KnowledgeChunk.project_id == project_id)
```

四個必須帶同一個 predicate 的地方（上游 §9 第 8 條的「search、count、citation、
context pack、cache」）：

| 面 | 帶了嗎 | 測試 |
|---|---|---|
| search 的 items | ✔ | 8 條 isolation 之一 |
| search 的 **count** | ✔ | **無權查詢 count 是 0，不是 403**——不揭露存在 |
| citation 展開（`GET /knowledge/sources/{id}`） | ✔ | 跨 project 的 id → **404** |
| context pack | ✔ | run token 的 project 不符 → `CROSS_PROJECT_DENIED` |
| 快取 | ✔ | 快取 key 含 `project_id`；**沒有跨 project 的共用快取** |

★ **本期不加任何檢索結果快取。** 上游把 cache 列進 isolation 測試的範圍，
但一個還沒被量測過的查詢先加快取是在猜。P95 < 1s 的目標先用索引達成
（[`09`](./09-verification-and-exit.md) §5），若量測顯示需要快取，
它是 `beta.1` 的工作並且要自己帶一組 isolation 測試。
**「快取無跨 project 洩漏」在本期的證明形式是「沒有快取」，並且寫下來。**

## 5. API

### 5.1 人的介面（session token，`project.view`）

```text
GET /api/projects/{project_id}/knowledge/search
    ?q=<string>                     必填，1..256
    &source_type=<csv>              可選，allowlist
    &authority=<csv>                可選，allowlist
    &task_id=<uuid>                 可選，開啟 graph boost
    &include_history=false
    &limit=20&cursor=<opaque>
→ { "items": [ { "source_id", "source_type", "title", "authority", "version",
                 "occurred_at", "uri", "excerpt", "score", "why": [...] } ],
    "total": 42, "channels": ["fts","trigram"], "took_ms": 87 }
```

`knowledge_enabled=false` → **404**（不是 403：不揭露設定狀態，D58）。
無 `project.view` → 404（既有 project 路由的一致行為）。

`excerpt` 用 `ts_headline`（fts 命中）或命中位置前後 120 字（trigram 命中）。
**`ts_headline` 對我們自製的 tsvector 沒用**（它重新分析原文），
所以 excerpt 一律用 Python 端的命中定位——又一個「index 與 query 同源」的後果。

### 5.2 Agent 的介面（run token）

```text
GET  /api/cli/runs/knowledge/search?q=…&limit=8        project 由 run 決定，不可指定
GET  /api/cli/runs/knowledge/sources/{id}              只能是自己 project 的
GET  /api/cli/runs/context-pack                        06 章
```

`limit` 上限 8（人的介面是 50）。理由：Agent 拉的東西要進它的上下文，
而一個回 50 筆的端點會讓 Agent 把 50 筆都讀進去。**限制在伺服器端，不在提示裡。**

### 5.3 其他端點（`KN-10` 用）

```text
GET  /api/projects/{id}/knowledge/sources?source_type=&state=      Sources 頁
GET  /api/projects/{id}/knowledge/sources/{sid}/versions           版本比較
GET  /api/projects/{id}/knowledge/health                           Source health
GET  /api/projects/{id}/knowledge/recent                           Recently learned
POST /api/projects/{id}/knowledge/sources/{sid}/authority          標為正式決策 / 撤回
POST /api/projects/{id}/knowledge/resync                           project.manage
POST /api/tasks/{tid}/knowledge/pins                               pin / exclude
DELETE /api/tasks/{tid}/knowledge/pins/{sid}
PATCH /api/projects/{id}                                           knowledge_enabled（既有端點加兩欄）
```

## 6. 效能

目標 **P95 < 1s**（index warm），資料集見 [`09`](./09-verification-and-exit.md) §5。

三個已知的成本點與對策：

| 成本 | 對策 |
|---|---|
| GIN 索引不含 `project_id`，所以要 heap 過濾 | `ix_knowledge_chunks_live(project_id, source_id) WHERE valid_to IS NULL`（[`02`](./02-data-layer.md) §2.2） |
| bigram 讓 `search_document` 大 1.6–2 倍 | 量它（[`10`](./10-open-measurements.md) 第 2 項）；必要時 title 用 bigram、body 用 unigram＋trigram |
| 兩個通道各取 top-50 再合併 | K 是常數，兩次索引掃描；**不要改成 OR**（§2.1） |

## 7. 測試（`KN-07`）

### 7.1 Tokenizer（純單元，最便宜也最重要）

| # | 輸入 | 斷言 |
|---|---|---|
| 1 | `'租約過期'` | `['租約','約過','過期']` |
| 2 | `'lease_expires_at'` | 含原詞與三個切分 |
| 3 | `'CV-05'` | 含 `'cv-05'` 與 `'cv'`、`'05'` |
| 4 | `'處理 lease 逾時'` | CJK bigram 與 ASCII 詞都出現，且不互相污染 |
| 5 | `'期'` | 空 bigram → 呼叫端要走 trigram |
| 6 | 全形標點、emoji、零寬字元 | 不 crash、不產生空 lexeme |
| 7 | 10 萬字 | 有界時間（線性），不遞迴 |

### 7.2 固定查詢集（relevance，`KN-13` 建立基準）

| # | 查詢 | 必須找到 | 為什麼 |
|---|---|---|---|
| 1 | `CV-05` | 提到它的 ticket 與對話 | 精確 ref（trigram） |
| 2 | `lease_expires_at` | migration 與 model | symbol |
| 3 | `139f143` | 那個 commit 的 repo_doc | SHA |
| 4 | `租約過期` | 討論逾時處理的對話 | 中文一般語句（bigram） |
| 5 | `怎麼處理逾時` | 同上 | **這一條預期會漏**——D40 的已知取捨，用 pin 補；列入基準 |
| 6 | `verification` | accepted spec 勝過 Agent proposal | authority rerank |
| 7 | `charter` | 三年前的 policy 仍在前三 | freshness 地板（§2.3） |
| 8 | `lese_expires`（typo） | 同 #2 | trigram 容錯 |

### 7.3 整合

| # | 測試 |
|---|---|
| 1 | `test_search_is_scoped_to_one_project`（×8 條 isolation，[`09`](./09-verification-and-exit.md) §4） |
| 2 | `test_count_is_zero_for_an_unauthorized_project` |
| 3 | `test_superseded_sources_are_absent_by_default_and_present_with_history` |
| 4 | `test_a_pinned_source_always_enters_the_top_n` |
| 5 | `test_an_excluded_source_never_appears_for_that_task_but_does_for_another` |
| 6 | `test_disabled_knowledge_returns_404` |
| 7 | `test_run_token_cannot_search_another_project` |
| 8 | `test_run_token_search_limit_is_capped_at_eight` |
| 9 | `test_single_character_cjk_query_reports_its_degraded_channel` |
| 10 | `test_trigram_threshold_is_actually_applied` |
