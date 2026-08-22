# 11 — 實作進度與證據

> **本檔在實作期間逐步回填。與計畫不同時以這裡為準，並回寫計畫。**
> 目前狀態（2026-08-22）：**`KN-00`…`KN-13` 全部實作完成，五個波次走完。**
> `make check` **全綠**（exit 0）；`scripts/kn/gates.sh` **12 個 gate 全 PASS**；
> 五條旅程 **J11–J15 全 PASS**，在真的 daemon 上跑出來的。
> 尚未簽核、尚未打 tag——出口條件 **26／28**，缺的兩項在 §8。

## 0. 要回寫上游的六處

寫這份計畫時核對程式碼發現 `research/03/` 有六處已經過期或不精確。
**`KN-00` 負責回寫**，因為一份被下一個讀者當成事實的規劃文件，
它的錯誤會被繼承。

| # | 文件 | 原本 | 應為 |
|---:|---|---|---|
| 1 | `research/03/README.md` 規劃基準表 | `agentd` **0.12.0** | **0.13.1**（`daemon/VERSION`；`alpha.2` 升過） |
| 2 | 同上 | RBAC **24** 個動作 | **27**（`plan/23/10` §9.4 已更正過一次，上游還沒同步） |
| 3 | 同上 | migration head **0039** | **0040** |
| 4 | 同上 | `v2` HEAD `f91d9c4`，ahead 60／behind 6 | `45a3143`；兩個 tag 已建立 |
| 4b | `research/03/README.md` 末尾的執行計畫表 | `K1 \| plan/25/ \| 未建立` | **已建立**（本目錄，2026-08-22）；同時把 `plan/24` 那一列從「可開工」改成「已完成，兩個 tag 已建立」 |
| 5 | `research/03/03` §2 Activity 那一列 | authority 寫 `platform fact` | D45 的十級裡沒有這一級。本期存成 `verified`（[`04`](./04-sources-and-authority.md) §1 的 ★） |
| 6 | `research/03/08` §3.2 `knowledge_sources` 的 DDL | 沒有 `source_updated_at` | 冪等 upsert 的比較欄，**必須有**（§4 的敘述已經在用這個名字） |

還有兩處是**規劃層的缺口而不是錯誤**，已在本目錄補上並要回寫：

| # | 缺口 | 補在哪 |
|---:|---|---|
| 7 | 上游沒有提到 `run.offer.context` 的 32 KiB 硬上限，而五層 pack 的設計直接受它決定 | D78、[`06`](./06-context-builder.md) §1 |
| 8 | 上游沒有提到 PostgreSQL 對中文沒有分詞器，而「full-text 擅長一般語句」因此不成立 | D79、[`05`](./05-retrieval-and-search.md) §1 |

## 1. 開工前的裁決單

### A 類 — 擋開工

| # | 決定 | 狀態 | 裁決日 |
|---|---|---|---|
| D77 | repo 內容從 run 裡面推上來 | ☑ **採納** | 2026-08-22 |
| D78 | context pack 走 HTTPS 拉，不走 offer | ☑ **採納** | 2026-08-22 |
| D79 | tokenizer 是純函式，index 與 query 共用 | ☑ **採納** | 2026-08-22 |
| D80 | job 是實體鍵，入列點只有一個 | ☑ **採納** | 2026-08-22 |
| D81 | knowledge 的保留寫進 ADR 0038 §6 | ☑ **採納** | 2026-08-22 |

**五項全綠**，波次 1 至 3 沒有裁決性阻礙。

### B 類 — 實作時依計畫的答案執行

`D82`…`D90`：☐ 未裁決（依計畫執行，有異議時記在 §2）。

### 從上游繼承、仍未關閉

| # | 決定 | 狀態 | 影響 |
|---|---|---|---|
| ★ D46 | provider 同步落在哪一版 | ☐ 未裁決 | 本計畫假設 `beta.2`。擋 `KN-13` 的 SR-2 範圍定義，不擋波次 1–4 |
| ☑ D51 | 保留、匯出與刪除政策 | ☑ **隨 D81 關閉**（2026-08-22） | `research/03/01` §3 的 ★ 要一併撤掉（`KN-00`） |

## 2. 與計畫的差異（五處）

### 2.1 tokenizer 提前到 `KN-03` 落地，測試留在 `KN-07`

計畫把 `tokenize.py` 放在 `KN-07`。實際上 `knowledge_chunks.search_document` 是
`NOT NULL`，所以 `KN-03` 的 store 一寫 chunk 就需要它。

**處置**：`services/knowledge/tokenize.py` 隨 `KN-03` 實作（含 `lexemes`／`document`／
`has_cjk`），**七條 tokenizer 單元測試仍記在 `KN-07` 名下**，與 `GATE-KN-ONE-TOKENIZER`
一起交付。現在只有 smoke 級別的驗證。

### 2.2 `redact_for_index` 是自己的模組，不是 store 的一部分

計畫的 [`03`](./03-ingestion-and-outbox.md) §8 把 redaction 描述成 store 的一步。
實作拆成 `services/knowledge/secrets_filter.py`，理由是它有兩層而不是一層：
專案宣告的機密名（走既有 `SecretService.redact`）與**憑證樣式清單**，
而後者還要被 `KN-06` 的檔名排除（`is_sensitive_path`）重複使用。

呼叫點仍然只有一個（`sources.ingest`），這是原本的重點。

### 2.3 chunker 需要兩條句子切分規則，不是一條

計畫寫「切點優先序：段落 > 句末 > 換行 > 硬切」。第一版用
`(?<=[。！？!?.])\s+`，而**中文句號後面沒有空白**——一段兩千字的中文於是完全不切，
成為一個 1700 token 的 chunk。

**處置**：CJK 標點不要求後隨空白，ASCII 標點要求（否則 `v1.13.0` 會被切開）。
另加一道字元數硬上限，處理「一整行 minified、沒有任何標點」的情況——
計畫的「硬切」原本只是一個詞，實作時它必須是一段程式碼。

### 2.4 ★ `VerificationReport.result` 的值是 `passed` 不是 `pass`

`_artifact` handler 原本用 `result == "pass"` 判斷 artifact 該不該是 `verified`。
`0035` 的 CHECK 允許的是 `not_started/running/passed/failed/partial`。
**這是一個實作缺陷，由 `test_an_artifact_from_a_passing_run_is_verified` 抓到**——
它不會報錯，只會讓每一個 artifact 都降級成 `generated`。

### 2.11 ★ **標題根本沒有進索引**——`KN-13` 的量測抓到的

計畫（D79、ADR 0038 §4）寫「title 權重 A／body 權重 B」。第一版只寫了 body：

```python
search_document=sa.func.to_tsvector("simple", document(piece.content))
```

**所有單元測試都是綠的**，因為每一條都剛好把查詢詞也放在 body 裡。
`KN-13` 的固定查詢集在接近真實的語料上跑，八條裡兩條回 0 筆——那才看得出來。

一併踩到兩個 PostgreSQL 細節，都值得記下來：

1. `setweight` 的第二個參數是 `"char"`，**沒有 `varchar` 的多載**。
   bound parameter 會以 `varchar` 送出，錯誤訊息是
   `function setweight(tsvector, character varying) does not exist`。
   用 `literal_column("'A'")` 讓字母以無型別字面量送出，由伺服器決定。
2. SQLAlchemy 對 `to_tsvector` 有專用建構，`import sqlalchemy.dialects.postgresql`
   之前呼叫 `sa.func.to_tsvector` 會在 compile 時炸掉。

**這一處是整期最有價值的一個發現**：它證明了固定查詢集不是儀式。

### 2.12 ★ `CROSS_PROJECT_DENIED` 沒有安全的 raise 點——已移除

計畫的 machine code 表列了六個。五個有 raise 點；第六個**每一個候選位置都不能用**：
run token 指到別的專案的 repository、source 或 card，全部必須回 404，
因為 403 等於確認那個 id 是真的。唯一不洩漏的形狀是「呼叫端指名自己專案的邊界」，
而**沒有任何端點讓 run token 指名一個專案**——專案是從 token 來的。

從 catalog 移除，理由寫在原地。`test_the_catalog_documents_nothing_fictional` 是對的：
一個沒有 raise 點的 code，遲早會被人在錯的地方 raise。

### 2.13 ★ `runner.register.features` 的 enum 是封閉的——CLI 提示改看版本號

見 [`07`](./07-cli-and-agent-contract.md) §5 的 ★ 段。計畫假設那個欄位可以免費多帶一個值；
它不行，而且後果比「動 contract」更糟：**沒升級的 Central 會直接拒絕新 daemon 的註冊**。
改看 `nodes.daemon_version`，以整數 tuple 比較。J15 是證據。

### 2.14 專案只有一個 repository 時，不必指名

`repo-manifest` 原本要求 card 指名 repository。J12 寫到一半才看清楚：
`source: none` 的卡沒有 `repository_id`，而 `source: repo` 的卡會讓 runner 去 clone
一個不存在的遠端。

**處置**：專案剛好有一個已註冊 repository 時由 Central 解析。
零個或兩個以上仍然拒絕——猜錯會把文件歸到錯的 repository 上，而且是靜默的。
這同時讓「agent 不必知道平台 uuid」這件事真的成立。

### 2.15 `include_history` 與「supersede 時關掉 chunk」互斥

實作 repo sync 時為了讓「目前索引了什麼」只有一個答案，在 supersede 時把舊 chunk
的 `valid_to` 關掉。三條測試同時紅：`include_history=true` 從此回不出任何東西，
而那是 superseded 這一級存在的唯一理由。

**處置**：不關。`valid_to` 答的是「這個 chunk 還是它那個版本的現行文字嗎」，
而被取代的版本的 chunk 仍然是；「這個 source 還是現行的嗎」是另一個問題，由 `active` 回答。

### 2.6 `RETURNING` 混用 ORM 屬性與 `sa.text()` 會產生一個讀不到的欄位

改用 mapped class 之後，`.returning(KnowledgeSource.id, sa.text("xmax = 0 AS inserted"))`
的結果**沒有 `inserted` 這個名字**——三條測試同時紅，訊息是 `KeyError: 'inserted'`。

`xmax = 0` 是 PostgreSQL 判斷「這一列是新插入的而不是被更新的」的方法
（系統欄位只有全新 tuple 才是零），而 metric 需要它來區分「新增」與「更新」，
Recently learned 那一區也需要。**處置**：改成
`sa.literal_column("xmax = 0").label("inserted")` ＋ `.mappings()`。

這一處值得寫下來，因為它是「型別修正引入行為改變」的實例——
mypy 綠了、測試紅了，而如果那三條測試不存在，紅的會是三個月後的一個 metric。

### 2.5 reconciliation watermark 有兩種形狀，不是一種

計畫的 [`03`](./03-ingestion-and-outbox.md) §7 假設每種 source type 都能用
「實體的 `updated_at` 比 source 的 `source_updated_at` 新」比對。
`conversation`／`artifact`／`verification` 不行——它們一個實體產生**多筆** source
（每則訊息一筆），沒有「該卡的 source 版本」可比。

**處置**：兩個 helper。`_stale_entity`（A：實體自己有 `updated_at`）與
`_stale_children`（B：卡片的子列裡有還沒變成 source 的）。
`_stale_children` 用 `GROUP BY` 而不是 `SELECT DISTINCT`，因為 PostgreSQL 不接受
不在 distinct 清單裡的 `ORDER BY`。

## 3. Ticket 狀態

| ID | 狀態 | 證據 |
|---|---|---|
| `KN-00` | ☑ | `research/03/{README,01,03,08}` 已回寫（§0 的八處）；`scripts/kn/capture-baseline.sh` ＋ `artifacts/kn/local/baseline/`（COMMIT `45a3143`、contract sha256、7 個依賴、833 行 schema） |
| `KN-01` | ☑ | `docs/adr/0038-…md`（352 行）；`research/prd.md` §8.18（11 節、44 個 AC anchor）；`traceability/requirements.json` **178 → 189**；`make traceability-validate` 綠；ADR 0041 加一行交叉引用 |
| `KN-02` | ☑ | migration `0041`＋`0042`；六個 model；**upgrade → downgrade → `schema unchanged` → upgrade 實測**；`tests/db/test_knowledge_schema.py` 15 條 |
| `KN-03` | ☑ | `services/knowledge/{outbox,worker,store,chunking,tokenize,secrets_filter}.py`；`ActivityService.record()` 單一入列點；三個 metric ＋ 兩個 gauge ＋ **三條告警** ＋ runbook；`main.py` lifespan；`tests/db/test_knowledge_ingestion.py` 16 條 |
| `KN-04` | ☑ | `sources.py` 的 `policy`／`ticket`／`conversation`／`decision` handler ＋ redaction ＋ citation anchor；`tests/db/test_knowledge_sources.py` 15 條 |
| `KN-05` | ☑ | 同檔的 `artifact`／`verification`／`activity` handler；authority 對應含 §2.4 的修正 |
| `KN-06` | ☑ | `services/knowledge/repo.py`、兩個 run-token 端點、`daemon/internal/cli/knowledge.go`；`tests/db/test_knowledge_repo_sync.py` 15 條 ＋ Go 8 條；J12 |
| `KN-07` | ☑ | `tokenize.py` ＋ `search.py`（雙通道、rerank、freshness 地板、isolation predicate）；tokenizer 單元 16 條、整合 22 條 |
| `KN-08` | ☑ | **ADR 0039**；`context.py`（五層、budget、instruction／evidence）；`_context_for` append；`GET /api/cli/runs/knowledge/context-pack`；17 條 |
| `KN-09` | ☑ | `cliora knowledge {sync,context,search,cite}`；`agentd` 0.13.1 → **0.14.0**；Go 13 條 |
| `KN-10` | ☑ | `modules/knowledge/`（view ＋ 6 元件 ＋ queries）；11 個 HTTP 端點；4 個 token；13 條前端測試 |
| `KN-11` | ☑ | `RelatedKnowledgePanel`，宿主 `TaskDetailView`（D83）；樂觀更新 ＋ 失敗回滾 |
| `KN-12` | ☑ | `scripts/kn/gate_knowledge_invariants.py`（5 個 AST gate）＋ `scripts/kn/gates.sh`（另 4 個 ＋ 4 個 re-run），**全 PASS** |
| `KN-13` | ☑ | 五條旅程、三項量測、relevance 基準、SR-2、release note。**兩項出口條件未達成**，見 §8 |

## 4. Gate 結果

`scripts/kn/gates.sh`（2026-08-22，工作樹）：

```text
  PASS  GATE-KN-{ONE-TOKENIZER,PROJECT-SCOPED,INSTRUCTION-LAYER,AUTHORITY-SERVER-SIDE,NO-RAW-LOG-INDEX}
        fleet-wide (allowed): api/http/metrics.py::knowledge_queue
        fleet-wide (allowed): services/knowledge/worker.py::_recover_stuck
  PASS  GATE-KN-NO-NEW-EGRESS (dependencies)
  PASS  GATE-KN-NO-NEW-EGRESS (httpx)
  PASS  GATE-KN-CONTRACT-FROZEN
  PASS  GATE-KN-TOUCH-LIST
  PASS  GATE-KN-MIGRATION-ROUNDTRIP
  PASS  GATE-KN-JOURNEY-COVERAGE
  PASS  GATE-RQ-CONTEXT-DISPATCH (re-run)
  PASS  GATE-SC-SINGLE-DECRYPT (re-run)
  PASS  GATE-CV-* (re-run)
all V2-K1 gates passed
```

**兩個 fleet-wide 例外每次都會被印出來。** 一個看不見的例外，就是一條悄悄失效的規則。

`make check`：**exit 0**（format-check、lint、typecheck 156 檔、tokens 62、
unit backend 1919 ＋ frontend 699、contract 192、build、traceability、railway-check）。

**mypy 的 14 個錯誤全部來自本期**，都是同一個原因：`Model.__table__` 的型別是
`FromClause`，而 `sa.update()`／`pg_insert()` 的簽章不收它。改成傳 mapped class
之後歸零。一個連帶的收穫記在 §2.6。

## 5. 測試計數

| 層 | 計畫 | 實際 |
|---|---:|---:|
| Unit（tokenizer 等） | ~95 | 16 ＋ 既有 |
| Backend integration | ~70 | **93**（schema 15、ingestion 16、sources 15、repo 15、search 22、context 17）＋ authz／catalog／matrix 的擴充 |
| Frontend component | ~26 | 13 |
| Go（`internal/cli`） | 9 | **13**（總計 41 個 PASS） |
| E2E 旅程 | 4 | **5**（多一條 J15，理由見 §2.13） |
| **backend 全套** | — | **1919 passed**（開工前 1805，＋114） |
| **frontend 全套** | — | **699 passed** |

## 6. 效能量測

證據：`artifacts/kn/local/measurements.json`、`artifacts/kn/local/journeys/`。
環境：本機 PostgreSQL 16.14，資料集 200 卡／500 訊息／300 repo 文件＝1000 chunks。

| 項目 | 目標 | 實測 |
|---|---|---|
| ingest freshness（決策 → 搜得到）P95 | < 10s | **1.5s**（J11，實際 run） |
| knowledge search P95 | < 1s | **0.11s** |
| context pack build P95 | < 2s | **0.079s** |
| offer context vs wire 32 KiB | 必須放得下 | **~0.7 KiB** 實測；最壞情況由測試斷言 < 8 KiB |
| `search_document` 體積倍率 | 記錄基準，**不設門檻** | **3.54×** |
| relevance 固定查詢集 | 8 條逐條人工判定 | **8／8 符合預期**（含 1 條「預期會漏」） |

那條預期會漏的查詢（`how do we handle timeouts` 對 `lease expiry`）是 D40 的取捨
**被量出來**而不是被假設。日後要重啟向量檢索，這就是對照組。

倍率沒有門檻是刻意的：沒有人知道合理值是多少，
而**一個第一次紅就被調高的門檻，是形式而不是標準**。

## 7. 出口條件（26／28）

| ☑ | # | 條件 | 證據 |
|---|---:|---|---|
| ☑ | 1 | ingest freshness P95 < 10s | 1.5s（J11） |
| ☑ | 2 | search P95 < 1s | 0.11s |
| ☑ | 3 | context pack build P95 < 2s | 0.079s |
| ☑ | 4 | citation 可回到原來源 | `_source_row.uri` ＋ `CitationLink`；`repo://` 刻意不可點 |
| ☑ | 5 | manifest 說得出來源／版本／authority／token／**why** | `test_the_manifest_carries_provenance_and_no_content` |
| ☑ | 6 | 更新／刪除／supersede 後舊內容不進預設 retrieval | 三條測試 ＋ J12 |
| ☑ | 7 | 精確 ref／symbol／SHA／中文語句都找得到 | relevance 8／8 |
| ☑ | 8 | 未核准 proposal 不以 authoritative 提供 | `test_only_policy_reaches_the_instruction_block` |
| ☑ | 9 | prompt injection 不提升為 instruction，**且卡片狀態未變** | J13 四條 |
| ☑ | 10 | 無跨 Project 洩漏 | 8 條 isolation ＋ J14 七條 |
| ☑ | 11 | `knowledge_enabled=false` 不 ingest、search 回 404 | 兩條測試 ＋ J14 |
| ☑ | 12 | Project 刪除後全部消失 | cascade 測試 |
| ☑ | 13 | Central 未新增對外連線 | `GATE-KN-NO-NEW-EGRESS` |
| ☑ | 14 | `contracts/v1/` 逐位元組不變 | `GATE-KN-CONTRACT-FROZEN` |
| ☑ | 15 | offer context 最壞情況 < 32768 bytes | `test_the_offer_digest_stays_far_under_the_wire_ceiling` ＋ J15 |
| ☑ | 16 | 未升級節點（0.13.1）行為不變 | **J15 實測**，不是論證 |
| ◑ | 17 | `pg_trgm` 在 compose ＋ Railway 各成功一次 | **compose ✅／Railway 未驗** |
| ☑ | 18 | migration downgrade 回到基線 | `GATE-KN-MIGRATION-ROUNDTRIP`：`schema unchanged` |
| ☑ | 19 | 八個新 gate ＋ re-run 全 PASS | §4 |
| ☑ | 20 | 旅程各執行一次、無 skip、各留證據 | `GATE-KN-JOURNEY-COVERAGE`，5／5 |
| ☑ | 21 | 三條告警規則在 `alerts.yml` | `test_alerts_and_runbooks.py` 全過 |
| ☑ | 22 | dead letter age 有 gauge 且面板顯示 | `knowledge_dead_letter_age_seconds` ＋ `SourceHealth` |
| ☑ | 23 | Related knowledge 顯示的與 Agent 讀到的同一份 | 同一個 `KnowledgeSearch`，同一個 `task_id` |
| ☑ | 24 | 從未同步 repo 的 project 看得出來 | `repo_never_synced` ＋ 前端測試 |
| ☑ | 25 | relevance 基準已記錄 | `artifacts/kn/local/measurements.json` |
| ☐ | 26 | **SR-2 已簽核** | 文件齊備、**未簽核** |
| ☑ | 27 | 九項 release 產物齊備 | `docs/release-note-project-memory.md` |
| ☑ | 28 | `make check` 全綠 | exit 0 |

## 8. 未完成

### 8.1 兩項出口條件未達成——**都不是可以自己解決的**

| # | 缺什麼 | 為什麼不能自己補 |
|---:|---|---|
| 17 | `CREATE EXTENSION pg_trgm` 在 **Railway** 未驗 | 需要一個 Railway 專案與它的資料庫憑證。compose 那半已驗（PostgreSQL 16.14，migration 角色是 superuser） |
| 26 | **SR-2 未簽核** | 簽核要具名，而且**必須是沒有寫這段程式的人**。`docs/security-review-v2k1.md` 十三列逐項有證據，十二列通過、一列（第 17 項的另一半）待補。實作者簽自己的審查，等於沒有審查 |

`plan/23/10` §9.4 記過同一件事（SR-1 未簽核），`plan/24` 才關掉。形狀一樣。

**在這兩項關閉之前不建立 `v2.0.0-alpha.3` tag。**

### 8.2 一項先前就存在的失敗，已修，並記在這裡

`make format-check` 對 `backend/tests/db/test_auth_api.py` 報 "would reformat"，
而 `git status --porcelain` 對該檔為空——**它在 `45a3143` 就是這樣**，不是本期造成的
（它來自 `83d2146` 那個 refresh-token 的安全修正）。

一開始判斷「不順手修」，因為本期的禁區規則要求每一處改動都有理由。
**改判的理由**：出口條件 28 是「`make check` 全綠」，而只要這兩個換行還在，
那一項就永遠不會綠。所以它被 `ruff format` 一併修了，diff 是
**兩處純換行、零語意變更**（`+2 −6`），在這裡具名而不是讓它混在本期的 diff 裡。

### 8.3 尚未執行

- `pg_trgm` 只在本機 compose 路徑驗過（PostgreSQL 16.14，migration 角色是 superuser）。
  **Railway 路徑未驗**——這是 `KN-02` 出口條件的一半，記在這裡而不是打勾。
- ~~三條 Prometheus 告警規則尚未寫進 `alerts.yml`~~ → **已補**（同一輪）：
  三條規則 ＋ `docs/runbooks/knowledge-ingestion.md` ＋ 兩個 scrape-time gauge
  （`knowledge_pending_jobs`／`knowledge_dead_letter_age_seconds`，
  依 `metrics.py` 的規則放在 exporter 而不是 registry）。
  `tests/test_alerts_and_runbooks.py` 的四項檢查全過。
