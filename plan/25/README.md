# Cliora `v2.0.0-alpha.3` — V2-K1 Project Memory

> **狀態：`KN-00`…`KN-13` 全部實作完成（2026-08-22）。**
> `make check` 全綠、`scripts/kn/gates.sh` 12 個 gate 全 PASS、五條旅程在真 daemon 上全過。
> **出口條件 26／28**——缺 Railway 的 `pg_trgm` 驗證與 SR-2 的具名簽核，兩者都不是實作者能自己關的。
> **未打 tag。** 實作紀錄與八處與計畫的差異在 [`11`](./11-implementation-status.md)。
> [`00`](./00-execution-plan.md) §0 保留原文——其中三項是讀完程式碼才看得見的，
> 而每一項的錯誤答案都會讓後面兩個波次白做。仍未裁決的只剩繼承自上游的 **★ D46**
> （provider 同步落點），它只擋 `KN-13` 的 SR-2 範圍定義。
> 上游規劃：[`research/03/03-phase-k1-project-knowledge.md`](../../research/03/03-phase-k1-project-knowledge.md)。
> 前一期：[`plan/23`](../23/README.md)（C1 實作）＋ [`plan/24`](../24/README.md)（C1 封版，`v2.0.0-alpha.2` 已 tag）。
> **合併規則不變**：`v2` → `dev` 一律由人決定，出口條件全綠只是取得提案資格。

Ticket 前綴 `KN-`。

---

## 這一期要交付什麼

一句話：

> **每個 Project 一層可追溯的記憶**——自動從「已經存在的事實」收集來源，
> 保留 provenance／版本／時效／信任層級，以受控 retrieval 提供給 Agent 並附引用，
> 且**人看得見 Agent 會讀到什麼**。

Ticket 是局部工作記憶（`alpha.2` 交付的），Knowledge Hub 是跨 Ticket 的長期記憶。
`alpha.1` 的已知缺口第 5 條——「沒有 project-scoped 知識層；每次 run 的情境包從零組裝，
Agent 無法引用先前決策」——就是本期存在的理由。

`alpha.2` 的形狀是「一句話怎麼保證只被做一次」。
**本期的形狀是「Agent 讀到的每一句話，說得出它從哪裡來、是誰說的、有多可信、以及為什麼是它而不是別的」。**

---

## 五個真正的缺口（讀完程式碼才看得到的那種）

上游規劃寫的是「要做什麼」。以下五條是把它對到這個 repo 的現況之後，
**規劃層沒有寫、但會決定實作形狀**的事實。每一條都在 [`01`](./01-decisions-and-governance.md) 有對應的裁決。

| # | 缺口 | 證據 | 決策 |
|---:|---|---|---|
| 1 | **`run.offer` 的 `context` 有 32 KiB 硬上限，超過就解碼失敗——而解碼失敗在這條線上是靜默的。** 五層 context pack 塞不進去，塞進去也會在某一張卡上突然壞掉，而症狀是「卡片被認領、offer 消失、租約過期、重試到耗盡然後 blocked」 | `daemon/internal/protocol/codec.go:962`；contract 1.13.0 changelog 記錄過這個失敗長什麼樣 | **D78**：offer 只帶 layer-1 policy digest；完整 pack 由 run token 走 HTTPS 拉 |
| 2 | **Central 讀不到 repo。** 沒有 git、沒有 egress（`SCOPE-013`），而唯一存在的檔案通道 `filesystem.read` 綁 `terminal_sessions` ＋ 需要 `User` actor，背景 worker 兩個都沒有 | `backend/app/services/files.py:182` `_resolve()`；`app/services/providers.py` 是唯一對外模組 | **D77**：repo 內容從 run **裡面**推上來（`cliora knowledge sync`），不是 Central 去拉 |
| 3 | **`to_tsvector` 對中文等於沒有分詞。** 產品內容（卡片、對話、決策）幾乎全是繁體中文，而一整串 CJK 在 `simple`／`english` 設定下是**一個 lexeme**。full-text 那一半在中文上形同不存在 | PostgreSQL 無中文 parser；`postgres:16-alpine` 只有內建設定 | **D79**：Python 端自製 tokenizer（ASCII 詞 ＋ CJK bigram），index 與 query 同一個純函式 |
| 4 | **`activity_events.id` 是 uuid4，`occurred_at` 是交易開始時間。** 任何「用游標追 activity 當 outbox」的設計都會漏行——不是理論上會，是兩個交易交錯提交時一定會 | `app/db/models.py:462`；`occurred_at` 用 `server_default=func.now()` | **D80**：job 是 **entity key（提示）不是內容**，用 `FOR UPDATE SKIP LOCKED` 領取，不用游標；入列點只有 `ActivityService.record` 一個 |
| 5 | **`ADR 0041` 已經 accepted，而它只答了 conversation 那一半。** D51 的四個問題裡「Project 刪除時 knowledge 的 tombstone 範圍」與「匯出」在 `alpha.2` 沒有落點，而 `KN-12` 的 cascade 測試需要它 | `docs/adr/0041-…md` §1–§2 全篇只談 message | **D81**：knowledge 的保留寫進 **ADR 0038 新的一節**，0041 只加一行交叉引用，**不改已 accepted 的內容** |

第 1、2、3 條合起來說明一件事：**上游規劃把 `alpha.3` 描述成一個「加表 ＋ 加查詢」的期，
它實際上是一個「加一條資料通道 ＋ 加一個分詞器 ＋ 改一個交付邊界」的期。**
三項都不難，但三項都不在原本的 ticket 描述裡。

---

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | **開工前唯一必讀**：五項 A 類裁決、九項 B 類、五個波次、14 張 ticket、禁區清單、版本節奏 |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | **D77–D90** 全文，每一項含「不同意的話會怎樣」 |
| [02-data-layer.md](./02-data-layer.md) | Migration `0041`／`0042`、六張表、model、索引、`pg_trgm` 的兩條部署路徑、downgrade 順序 |
| [03-ingestion-and-outbox.md](./03-ingestion-and-outbox.md) | 入列點、job 語意、worker、冪等 upsert、dead-letter、reconciliation、redaction |
| [04-sources-and-authority.md](./04-sources-and-authority.md) | 八種 source 的逐一對應、chunking、authority 寫入規則、supersede、tombstone、repo sync 協定 |
| [05-retrieval-and-search.md](./05-retrieval-and-search.md) | tokenizer、tsvector／trigram／graph boost／rerank、search API、isolation predicate |
| [06-context-builder.md](./06-context-builder.md) | 五層、budget、instruction／evidence 分層、context-pack endpoint、與 `_context_for` 的接法 |
| [07-cli-and-agent-contract.md](./07-cli-and-agent-contract.md) | 四個 `cliora knowledge` 子命令、citation 格式、missing source 行為、`agentd` 0.14.0 |
| [08-frontend.md](./08-frontend.md) | `modules/knowledge/`、五個區塊、Related knowledge、狀態與 token |
| [09-verification-and-exit.md](./09-verification-and-exit.md) | 八個新 gate、測試矩陣、四條旅程、SR-2、效能預算、**26 項出口條件** |
| [10-open-measurements.md](./10-open-measurements.md) | 本期知道自己沒量的東西與理由 |
| [11-implementation-status.md](./11-implementation-status.md) | 實作後回填；**與計畫不同時以這裡為準並回寫計畫** |

## 建議使用方式

1. 先讀 [`00`](./00-execution-plan.md) §0 的 **A 類五項**。D77／D78／D79 是上表的第 1–3 條，
   **它們決定波次 2 與波次 3 的形狀**。**五項已於 2026-08-22 全部裁決**，所以這一步是讀而不是決定。
2. 波次順序照 [`00`](./00-execution-plan.md) §1。波次 1（`KN-00`…`KN-03`）是地基：
   沒有 outbox，波次 2 的三張 ticket 都沒有入口。
3. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
4. **出口條件未通過，不建立 `v2.0.0-alpha.3` tag。** 上一期學到的：
   證據是自己的一期（[`plan/24`](../24/README.md)），所以本期把它排成 `KN-13` 而不是 `KN-12` 的尾巴。
5. 需求變更先更新 `research/prd.md` 與 `traceability/requirements.json`，再同步
   [`research/03/11`](../../research/03/11-requirement-traceability.md)。

## 規劃基準（2026-08-22 實際讀過程式碼確認）

| 項目 | 現況 | 讀哪裡 |
|---|---|---|
| `v2` HEAD | `45a3143`（`Merge branch 'master' into v2`） | `git rev-parse HEAD` |
| tag | `v2.0.0-alpha.1`、`v2.0.0-alpha.2` **已建立且留在本機** | `git tag` |
| contract | **1.13.0**，`run.offer.context` 上限 **32768 bytes** | `daemon/internal/protocol/codec.go:962` |
| `agentd` | **0.13.1** | `daemon/VERSION` |
| migration head | **0040**`_ticket_conversation` | `backend/app/db/migrations/versions/` |
| RBAC 動作 | **27**（`ALL_ACTIONS`；「24」是舊文件的錯，見 `plan/23/10` §9.4） | `backend/app/services/rbac.py` |
| run token scope | `{project.view, task.update}` | `agent_auth.py:70` |
| ADR | 37 份，最新 `0037`／`0041`；**`0038`／`0039`／`0040` 是空號，本期用掉前兩個** | `docs/adr/` |
| requirements | **178** 條、27 個 family（`FR-CONV` 十條已註冊，`lifecycle: proposed`） | `traceability/requirements.json` |
| 情境包預算 | 實作包 `CONTEXT_BUDGET_BYTES = 6 KiB`；continuation `16 KiB`；**wire 32 KiB** | `services/runs.py:1823,1942` |
| 唯一的情境包分派點 | `RunService._context_for()`，由 `GATE-RQ-CONTEXT-DISPATCH` 用 AST 守著 | `scripts/rq/gate_context_dispatch.py` |
| 對外連線 | 只有 `httpx`，只有 `services/providers.py` 一個模組可達（`SCOPE-013`） | `backend/pyproject.toml` |
| PostgreSQL | `postgres:16-alpine`，**無 pgvector**，`pg_trgm` 是內建 contrib | `deploy/compose/compose.yaml:18` |
| 背景迴圈的既有形狀 | `RunReaper`：先 reconcile 一次再進迴圈，一輪三個交易，每輪有上限 | `services/run_reaper.py` |
| 前端 | 無 query cache 套件；`useAsyncResource` ＋ 12 個 Pinia store；`tokens.css` 58 個 property | `frontend/src/` |
| Task 詳情頁 | `views/TaskDetailView.vue`（145 行）內嵌 `ConversationPanel`；**Drawer 是 `beta.1` 的東西，現在不存在** | `frontend/src/views/` |
| secret redaction | `SecretsService.redact(project_id, names, text)` 已存在（`GATE-SC-SINGLE-DECRYPT` 要求只有這一個模組解密） | `services/secrets.py:407` |

> 執行計畫與 `research/03/` 不一致時，**以本目錄為準並回寫上游**——
> 本目錄讀的是程式碼，上游讀的是構想。已知需要回寫的六處列在
> [`11`](./11-implementation-status.md) §0。
