# 10 — 本期知道自己沒量的東西

> 一份沒有這一節的計畫，是一份把未知假裝成已知的計畫。
> 每一項要寫：**為什麼現在不量**、**不量的風險**、**什麼時候會知道**。

| # | 項目 | 為什麼現在不量 | 風險 | 什麼時候知道 |
|---:|---|---|---|---|
| 1 | **沒有向量檢索的召回率損失** | D40 已裁決不做，所以這不是「還沒決定」而是「已知的取捨」。需要真實查詢紀錄才有對照組，而 D90 決定不存查詢紀錄 | 語意相近但用詞不同的查詢（「怎麼處理逾時」vs 文件寫 `lease expiry`）找不到。用 pin ＋ `knowledge_links` 補 | `KN-13` 的固定查詢集建立**基準值**（含第 5 條那個預期會漏的）。日後若重啟向量，那組數字就是對照組 |
| 2 | **CJK bigram 讓 `search_document` 大多少** | 沒有真實資料量。估 1.6–2 倍，但那是估的 | GIN 索引體積與寫入成本被低估。最壞情況是 `alpha.3` 的資料集下 search P95 超過 1s | `KN-13` 記錄 `pg_column_size(search_document)` 的平均與 `content` 的比值。**不設門檻，只記數字** |
| 3 | **chunk 800／100 是不是對的** | 需要 relevance eval 的基準才有比較的對象（上游未量測項第 3 項的同一句話） | 太大 → 一個 chunk 命中就佔掉整個 retrieved 預算；太小 → 上下文被切斷，excerpt 讀不懂 | `KN-13` 之後。調整只需要重跑 ingestion（chunk_key 穩定，是 upsert），不需要 migration |
| 4 | **十級 authority 是否過細** | 需要真實使用。本期只有八級有寫入者（D85） | 若只用到四級，排序邏輯多了六個沒用的分支 | `beta.1` 的真實使用。**合併容易、拆開難**，所以先留 |
| 5 | **repo sync 在大型 monorepo（>50k 檔）的表現** | 手上沒有這種 repo。`KN-06` 只在中型 repo（~2000 tracked／300 doc）上量 | D88 的 800 檔上限在大 repo 上會直接擋住，而使用者只會看到 `KNOWLEDGE_SYNC_TOO_LARGE` | 有這種 repo 的使用者出現時。上限是設定（`knowledge_settings.repo_sync.max_files`），不是常數 |
| 6 | **`FR-CONV` ＋ `FR-KNOW` 21 條翻成 `active` 的成本** | 兩個 family 共 21 條需求、約 80 個 AC 要各自有 `implemented_by` 與 `verified_by` link，而 `make traceability-coverage --strict` 會逐條檢查 | `rc.1` 之前才發現要補 160 條 link | **`rc.1` 的一張獨立 ticket。** 本期在 `KN-13` 先補 FR-KNOW 的 link，不翻 lifecycle（[`09`](./09-verification-and-exit.md) §8） |
| 7 | **`conflicting decisions` 那一欄會不會恆為空** | supersede 是自動的，所以「兩個都 accepted 且無 supersede 關係」在本期的資料模型下可能不會發生 | 一個永遠是空的 UI 區塊 | `beta.1`。`KN-13` 要記錄它在測試資料與真實使用中是否出現過（[`08`](./08-frontend.md) §2.3） |
| 8 | **`tsquery` 用 phrase 還是 AND** | 兩種都實作、都有測試，但哪一種當預設要 relevance eval 才知道 | 預設選錯 → 中文長句查詢的精確度或召回率之一被犧牲 | `KN-13`。換的話寫進 [`11`](./11-implementation-status.md) |
| 9 | **多副本 Central 下的 ingest 吞吐量** | 開發與 staging 都是單副本 | `SKIP LOCKED` 的爭用在高副本數下可能讓每輪的有效 batch 遠小於 32 | 有多副本部署時。`KNOWLEDGE_JOBS_TOTAL` 的 label 已經足以看出來 |
| 10 | **Agent 到底會不會去拉 context pack** | D78 把完整 pack 放在一個 CLI 呼叫後面，而這是 M2 假設的一次新賭注 | 賭錯的話 knowledge 對 Agent 等於不存在，而畫面上一切正常 | **J11 的第 3 項斷言就是在量這個**（`context_packs` 有沒有列）。但那是「腳本會不會拉」；真實 Agent 會不會拉要 `beta.1` 的使用資料 |
| 11 | **symbol map 的價值** | 本期不做（[`04`](./04-sources-and-authority.md) §5.2），因為它需要語言感知的解析器 | function name 只靠 trigram，於是「這個函式在哪被呼叫」查不到 | `beta.1` 之後。若固定查詢集的 #2（`lease_expires_at`）在真實 repo 上召回不足，那就是它的入場證據 |
| 12 | **freshness 的 0.5 地板是否正確** | 半衰期與地板都是猜的（[`05`](./05-retrieval-and-search.md) §2.3） | 地板太高 → 舊資料一直浮上來；太低 → charter 沉下去 | relevance eval 的第 7 條（三年前的 charter 是否仍在前三）是唯一的訊號 |

## 兩個刻意不列進來的

**「快取的 isolation」不在這裡**，因為本期的答案是「沒有快取」，
而那是一個決定不是一個未知（[`05`](./05-retrieval-and-search.md) §4 的 ★）。
它被寫成一條測試（[`09`](./09-verification-and-exit.md) §4 #8），
所以下一期有人加快取時會被提醒。

**「Ask Project（自然語言問答）」不在這裡**，因為它不是未量測，是未在範圍內：
它需要一次 LLM 呼叫，而 Central 目前不呼叫任何 LLM。上游已把它列入 Horizon 2。
