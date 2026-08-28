# 01 — 架構決策

決策編號沿用全域序列，`plan/19` 用到 **D36**，本目錄從 **D37** 開始。
ADR 編號沿用 `docs/adr/`，目前到 **0034**，本目錄提案 **0035–0043**。

**這一份是開工前唯一必讀的文件。** §1 是本規劃與體驗重設提案不一致的地方；
§2 是 `alpha.1` 已知但未修的缺口；§3 是沒有預設值、必須有人決定的四項（D40 已於 2026-08-16 裁決）。

---

## 1. 與體驗重設提案不同的八處

提案是在**沒有讀程式碼**的前提下寫的產品構想，本規劃在寫的時候逐項核對了 repo。
以下八處是核對後認為應該偏離的地方。**每一處都寫了「提案怎麼說、實際狀況是什麼、
所以改成什麼」，可以只看這一節做決定。**

### 1.1 `plan/19` 已經實作完了，`PX-2 Design Foundation` 幾乎不存在

**提案怎麼說**（§1.2、§13.1）：保留 `plan/19` 的 token、guardrail、PageHeader、Panel 與
V1 pixel-stability 工作，並列為 `PX-2` 一整個 phase（`PX-14`–`PX-20`，7 張 ticket）。

**實際狀況**：`plan/19/09-implementation-status.md` 第一行寫「**狀態：實作完成**」；
`frontend/src/theme/tokens.css` 有 **58 個 custom property**，含 `--stage-backlog`…`--stage-done`、
`--run-queued`…`--run-lost`、risk 三級；`frontend/src/theme/checkTokens.test.ts` 與
`staticGuards.test.ts` 存在，`make check` 有 `tokens` target；`scripts/ui/evidence.sh` 存在。
`plan/19/README.md` 開頭那句「計畫已定稿，尚未開工」是 **2026-08-12 寫下後沒有更新的過期字串**。

**所以改成**：`PX-2` 從一個 phase 降為 `beta.1` 內的**兩張 additive ticket**：

| 原 ticket | 處置 |
|---|---|
| `PX-14` 合併 `plan/19` token 定稿 | **已完成**，刪除 |
| `PX-15` CSS token resolver gate | **已完成**（`checkTokens.test.ts` ＋ `make check` 的 `tokens`），刪除 |
| `PX-16` PageHeader／Panel／Drawer primitives | **PageHeader／Panel 已完成**；只留 **Drawer primitive**（併入 `PX-38`） |
| `PX-17` lifecycle／attention／execution tokens | **保留但縮小**：`--stage-*`／`--run-*` 已有，只缺 `--attention-*` 五個與 `--work-*` 五個的別名 → `PX-17` |
| `PX-18` WorkItemCard／WorkItemRow | 保留 → `PX-18` |
| `PX-19` Toolbar／Filter／Display options primitives | 保留，併入 `PX-31`／`PX-32` |
| `PX-20` visual regression 與 V1 pixel guard | 保留，但改為**沿用** `plan/19` 已建立的 baseline 機制，只補新畫面 → 併入 `HD-05` |

**淨效果：提案的 7 張 ticket 變成 2 張，`beta.1` 少掉約一個工作波次。**
連帶要做的一件小事：修正 `plan/19/README.md` 的狀態句（`CV-00`）。

### 1.2 Continuation turn 走既有的 offer／poll 路徑，`alpha.2` 不動 contract

**提案怎麼說**（§10A.5）：在既有 WSS 上加兩個輕量通知 `task.message_available` 與
`run.input_available`；並在 §14.6 要求 P95 < 2 秒讓 supervisor 得知。

**實際狀況**：三件事讓「加新訊息型別」比看起來貴很多。

1. **daemon 以 `DisallowUnknownFields` 嚴格解碼，且 Go 遞迴套用。** `contracts/CHANGELOG.md`
   1.13.0 已經把代價寫得很清楚：一個被拒的 `run.offer`「**產生不了任何回覆**——卡片被認領、
   offer 消失、租約過期、卡片重試到耗盡然後 blocked，而任何地方都不會提到相容性」。
   新的 central→node 訊息型別對 `agentd` 0.12.0 是未知型別，會走進 `codec.go` 的 `default:` 分支。
2. **因此 1.13.0 立下的規則是：`spec` 的新內容必須先有 `runner.register.features` 宣告。**
   新訊息型別要遵守同一條規則，等於要做「宣告 → 分版 → 兩邊都升」三件事。
3. **而這件事在正確性上不是必要的。** runner 已經有 `runner.poll`，預設 **5 秒**一次
   （`DefaultRunnerPollInterval = 5`）。continuation turn 如果**建模成一個 child run**，
   它就是一個普通的可認領工作，走的是已經存在、已經測過、已經有租約與重排的那條路。
   新訊息的價值只有延遲，不是能力。

**所以改成**：

- continuation turn = **同一張卡的 child run**，`parent_run_id` 指回上一個 run，
  透過既有 `runner.poll` → `run.offer` → `run.accept` 認領。**contract 維持 1.13.0。**
- 新的對話內容不上 wire：agent 用 `cliora task messages --after <seq>`（run token，HTTPS）拉。
  **這條路已經存在**，只是把 `--since <timestamp>` 換成 `--after <seq>`。
- 延遲目標從 P95 < 2s 改為 **P95 < 10s**（poll 5s ＋ 認領 ＋ 啟動）。
- `task.input_available` 這類通知列為 **`beta.2` 的選配最佳化**（`HD-09`），
  上線時 feature-gated，且**關掉它系統仍然正確**。

**代價**：使用者按下「回覆並繼續」到 Agent 開始回應，中位數約 3–8 秒而不是 2 秒。
**換到的**：`alpha.2` 不需要升級任何一個節點，未升級的 `agentd` 0.12.0 行為完全不變。

### 1.3 `alpha.3` 的 knowledge 檢索**不含向量**

**提案怎麼說**（§10B.7）：第一版採 hybrid retrieval，PostgreSQL full-text／trigram
**加上** vector search，並警告「不要只做 vector search」。

**實際狀況**：

- `deploy/compose/compose.yaml` 用 `postgres:16-alpine`，**沒有 pgvector**。加它要改 image、
  改 migration（`CREATE EXTENSION`）、改 Railway 的資料庫方案，並且**沒有 downgrade 路徑**
  ——一個裝了 extension 的資料庫回不去 stock image。
- embedding 要嘛呼叫外部 API，要嘛在本機跑模型。前者讓 Central 多一條對外連線：
  目前 `backend/pyproject.toml` 只有 `httpx` 一個對外用的套件。~~`SCOPE-013` 明文限定它~~
  「只從一個模組（`services/providers.py`）可達」。多一個 embedding provider 等於多一個
  金鑰、多一個 egress 目的地、多一份把 Project 內容送出去的資料流——**而 Project 內容
  正是這個系統最敏感的東西**。後者則多一個 GPU／記憶體需求與模型版本治理問題。
- 提案自己在 §10B.7 已經說了最關鍵的那句：「專案知識常包含 `PX-C05`、function name、
  commit SHA、error code 等精確 token，**純向量檢索會漏掉最關鍵的來源**」。
  換句話說，**lexical 那一半才是不可或缺的那一半**。

**所以改成**：`alpha.3` 的 retrieval 是 **lexical hybrid**：

```text
PostgreSQL full-text（tsvector，title 權重 A／body 權重 B）
＋ trigram（pg_trgm，精確 ref／symbol／SHA 的模糊比對）
＋ explicit graph boost（同 Epic、dependency、linked PR、supersedes）
＋ authority × freshness rerank
```

`knowledge_chunks.embedding_ref` **欄位從第一版就留**（nullable），
`KnowledgeRetriever` 的介面設計成可插入第二個 candidate source，
但 `alpha.3` 的實作只有一個 lexical source。**D40 已於 2026-08-16 裁決：不做向量檢索**；
日後要加，進 Horizon 2 並需要獨立 ADR（egress、金鑰、成本、刪除保證）。

> `pg_trgm` 是 PostgreSQL contrib，`postgres:16-alpine` **內建**，
> `CREATE EXTENSION pg_trgm` 不需要換 image。這是它與 pgvector 的關鍵差別。

### 1.4 Provider（PR／MR／Release）同步移到 `beta.2`

**提案怎麼說**：`PX-K11` 在 `PX-K` phase 內，而 `PX-K` 對應 `alpha.3`。

**實際狀況**：本輪其他所有工作——conversation、knowledge ingestion（來源全是自家 DB）、
views、board、drawer——**新增的對外副作用是零**。provider webhook 與 API 同步則同時新增：
inbound webhook endpoint（新的未認證入口，要做 signature 驗證與 delivery 去重）、
outbound API 呼叫（新的 egress 與速率限制）、以及 provider token 的保存與輪替。

把它和「零對外副作用」的工作放在同一個 tag，等於讓那個 tag 的安全審查範圍
被單一功能拉高一個等級。

**所以改成**：`KN-11`（provider sync）整段移到 `beta.2`，改編號 `HD-01`–`HD-03`。
`alpha.3` 的 knowledge 來源**全部來自 Cliora 自己的資料庫與已經授權的 repo 內容**
（repo 檔案由既有的 run 工作目錄或既有 `project_repositories` 憑證取得，不新增 provider API 面）。

### 1.5 `BoardCardDTO` 不擴充，改開 `WorkItemCardDTO` 與新 endpoint

**提案怎麼說**（§14.1）：「現有 BoardCardDTO 需擴充或改為 WorkItemCardDTO」，並列了 13 個新欄位。

**實際狀況**：`backend/tests/db/test_tasks_api.py::test_the_board_card_stays_a_summary`
是一個**刻意釘死的測試**，它的 docstring 寫著：74 KB／200 張 vs 439 KB／200 張的實測
「就是取代分頁的那個決定」。加 13 個欄位會讓那張卡從摘要變成別的東西，而那正是
這個測試存在的理由。

**所以改成**：

- `GET /api/projects/{id}/board` 與 `BoardCardDTO` **一個位元組都不動**。舊看板繼續用它。
- 新開 `GET /api/projects/{id}/work-items`，回 `WorkItemCardDTO`。
  ~~由 `CLIORA_PROJECT_EXPERIENCE_V2` 控制~~ ——**該旗標不建立**
  （`plan/26` [D117](../../plan/26/01-decisions-and-governance.md#d117)，2026-08-23 人工確認）。
- **新 DTO 有自己的大小預算與自己的釘死測試**（`PX-25`）：**先量再釘**
  （`plan/26` [D94](../../plan/26/01-decisions-and-governance.md)），
  門檻 = 量測值 × 1.15，並在測試 docstring 記錄逐欄 bytes 前五名。
  ~~200 張卡 ≤ 160 KB。這個數字是 74 KB 的兩倍多一點~~

  **原推導的兩個數字都不能用**（`plan/26` 的 `PX-00` 於 2026-08-23 重量）：

  | 數字 | 它其實是什麼 |
  |---|---|
  | 74 KB | `plan/17` 的 M1，之後 `plan/19` 加了三欄 |
  | 89,251 bytes | **不是 `BoardCardDTO`**，是 `scripts/tk/measure_board_payload.py` 的
    **合成**產生器與一份手寫 summary dict，早於這個 DTO 存在 |
  | **75,952 bytes** | 真正的 `BoardCardDTO` × 200，跑在固定資料集（seed 20260819）上 |

  一個從過期數字推出來的預算，若低於實測就從第一天起不守任何東西，
  若高於實測則會在欄位已經被用起來之後才變紅。
- ~~旗標關閉、或 `beta.1` rollback 時，`work-items` 不被呼叫，`board` 完全不受影響。~~
  沒有旗標（D117）。回滾路徑是「回上一個 image ＋ downgrade `0043`」，
  而 `/board` 保留一版（`plan/26` D118）。

### 1.6 維持「一個 run 同時只有一個未答問題」

**提案怎麼說**（§10A.9）：「多個 open questions 時逐題回答或一次回答全部，但每個 answer 都保留關聯」。

**實際狀況**：ADR 0034 §4 已經定了「一次一個問題」，`cliora task ask` 在 CLI 端先擋
（`client.PendingQuestion()`），server 端以 409 為真正的閘門，`runs.py` 有對應的
「這個 run 有沒有未答問題」查詢。

**所以改成**：`alpha.2` **維持單一未答問題**。理由不是省事，是**它讓 answer→resume 的
CAS 條件是單一列**：`UPDATE task_questions SET state='answered' WHERE id=? AND state='open'`
影響 0 列就是 409，影響 1 列就建立 continuation turn。多問題會讓「回答了三題中的兩題，
要不要續跑」變成一個產品問題，而那個問題現在沒有使用者資料可以回答。

放寬與否是 **D42，2026-08-16 已裁決：不放寬**；`beta.1` 依真實對話資料再議。

### 1.7 Stage 第一版只做 projection，`blocked` 車道保留

**提案怎麼說**（§6.2、§16.2）：`blocked` 從車道改成 constraint，並給了兩條路
（完整 migration，或「第一版只在 view layer 抽成 attention projection」）。

**所以改成**：**明確選第二條**，並補上提案沒寫的那一半——`blocked` **仍然是合法 stage 值**。

| | |
|---|---|
| 資料庫 | `tasks.stage` 的六個值全部不動；**新增** `is_blocked`／`blocking_reason`／`blocking_message` 三欄（additive） |
| 舊看板 | 行為完全不變 |
| 新 work-items | `blocked` 的卡投影成 `lifecycle = ready` ＋ `is_blocked = true`，並在 DTO 帶 `legacy_stage: "blocked"` |
| 寫入 | 新 UI **不再把卡片寫成 `stage='blocked'`**，改寫 `is_blocked`；舊 UI 仍可寫 |
| 何時真正 migrate | `beta.2`，且必須先產出 ambiguous report（見 [`12`](./12-migration-and-rollout.md) §3） |

**這是過渡設計，而且記在這裡就是為了它不會被忘記。**
`HD-06` 是「把過渡拆掉」那張 ticket，它的存在本身就是這個決定的還款計畫。

### 1.8 Rank：`tasks` 沒有排序欄位，Backlog 要新增一個

**提案怎麼說**（§9.1）：Backlog 有 rank handle、drag rank；§8.6 說「不得因 grouping
建立第二份 Task 排序真實來源；rank 必須有明確 scope」。

**實際狀況**：`repositories/tasks.py` 的看板查詢是 `ORDER BY Task.updated_at DESC`。
**`tasks` 表沒有 rank、沒有 position、沒有 order_index**（`epics` 與 `user_stories` 有
`order_index`，`tasks` 沒有）。所以「拖曳排序」目前在任務層**根本不存在**，
提案把它當成既有能力的改良，其實是新能力。

**所以改成**：新增 `tasks.rank`（`String(64)`，lexicographic），並**從 `../kintra`
移植 `backend/app/modules/board/ranking.py` 的純函式**（見 §1.9）。scope 明確定義為
**每個 project 一個序列**（不是每欄一個）——因為 Backlog 與 Board 是同一批卡的兩個投影，
兩份 rank 會立刻分歧。

### 1.9 從 `../kintra` 移植什麼、不移植什麼

提案 §13.4 說「可以移植模式與測試案例，但不直接 copy」。核對 kintra 之後，
具體到三樣東西可以**逐字移植**，其餘只移植模式：

| kintra 的東西 | 處置 | 理由 |
|---|---|---|
| `backend/app/modules/board/ranking.py` | **逐字移植純函式 ＋ 測試** | 它是無 I/O 純函式，不含 kintra 的 domain。已解決的三個不變式（非空、不以 `'0'` 結尾、全小寫 base36 避開 collation）是踩過坑才寫得出來的，重寫只會重踩 |
| `board_views` 的 schema 形狀 | **移植欄位設計**（`criteria` JSONB ＋ `is_default` ＋ `position` ＋ `(board,user,name)` 唯一鍵） | 形狀對；但 Cliora 要多一個 `scope`（personal／project），因為 kintra 的 view 全是個人的 |
| `search_documents` 的冪等寫入 | **移植模式**：唯一鍵 ＋ `source_updated_at` 比較，用 `INSERT … ON CONFLICT`，**不是**「先查再決定寫不寫」 | 後者在兩個 worker 同時處理同一資源時會雙寫。這正是 `KN-03` 要面對的問題 |
| `TicketDetailDrawer.vue`（1394 行） | **只移植互動規格與測試案例**，不移植程式碼 | 它綁 Naive UI 的 drawer、kintra 的 custom field 與 i18n；Cliora 的 Drawer 要放 conversation、run、gate、evidence，主體結構不同 |
| `BoardCardVisibilityPopover.vue` | 移植**「卡片欄位可配置」是看板層設定而非個人設定**這個決定 | kintra 把 `card_fields` 放在 `boards` 上（migration `p11_01`）。Cliora 放在 view 上，因為 Cliora 的 view 是第一級物件 |
| Naive UI 元件 | **不移植** | `plan/19` D35 已裁決「不擴大 naive-ui 的使用面」 |
| 自動化規則、custom field、worklog | **不移植** | 提案 §3.2 非目標：不做通用 no-code automation、不自訂任意 schema |

---

## 2. `alpha.1` 的已知缺口（進 release note 的 known limitations）

這六條是核對程式碼之後確認**存在、但 `alpha.1` 不修**的缺口。
它們也是 `alpha.2`／`alpha.3` 的存在理由。

| # | 缺口 | 現況證據 | 修在哪 |
|---|---|---|---|
| 1 | 對話分頁用時間戳，不是單調序號 | `cliora task messages --since <timestamp>`；`task_messages` 無 seq 欄 | `CV-03` |
| 2 | 訊息 POST 無 idempotency key，重送會產生重複訊息 | `task_messages` 無 `idempotency_key` 欄 | `CV-04` |
| 3 | run 結束後對話沒有 continuation 模型；`waiting_for_input` 佔住 lease 與 compute 最長 24 小時 | `runs.py` `ACTIVE_STATUSES` 含 `waiting_for_input`，租約 sweep 刻意跳過它 | `CV-05`、`CV-07` |
| 4 | 一般留言與「回答問題」在 API 上都是 `POST /messages`，差別只有 `kind` 字串，沒有「要不要續跑」的語意 | `agents.py:806` 只在 `kind == "question"` 時改 run 狀態 | `CV-05` |
| 5 | 沒有 project-scoped 知識層；每次 run 的情境包從零組裝，Agent 無法引用先前決策 | `services/context_projection.py` 只投影卡片與流程 | `KN-*` |
| 6 | 看板卡片沒有統一的 attention 投影，「現在輪到誰」由前端各自拼湊 | `BoardCardDTO` 有 `active_run_status`／`waiting_reason`／`blocking_count` 三個平行欄位，沒有優先序 | `PX-24` |

---

## 3. ~~仍需你裁決（原四項，**現只剩 D46**）~~ → **四項全部已裁決**

> **☑ D46 於 2026-08-25 由 `plan/27` 的 ★ D120 一併關閉**：
> provider 同步落在 `beta.2`，**形狀是 pull 而不是 webhook**。
> 這一節至此清空，而每一項的原文都保留在下面——那是被放棄的選項的紀錄。

每一項都沒有安全的預設值。**未裁決前，相關 ticket 不開工。**

### ☑ D40 — `alpha.3` 不做向量檢索（**2026-08-16 已裁決：採納建議**）

| | |
|---|---|
| **裁決** | **不做。`alpha.3` 只做 lexical hybrid。** |
| **接受的代價** | 語意相近但用詞不同的查詢（「怎麼處理逾時」vs 文件寫 `lease expiry`）第一版找不到。以 explicit graph boost、`knowledge_links` 與人工 pin 補 |
| **換到的** | 不換 PostgreSQL image（`pg_trgm` 是 `postgres:16-alpine` 內建的 contrib）、**Central 不新增任何 egress**、`alpha.3` 少 3 張 ticket 與一次安全審查範圍的擴大 |
| **保留的退路** | `knowledge_chunks.embedding_ref` 欄位第一版就留（永遠 `NULL`）、`KnowledgeRetriever` 介面預留第二個 candidate source。**架構不擋，這一版不實作。** |

**這個裁決連帶固定了三件事**：

1. `KN-02` 的 migration **不含 `CREATE EXTENSION vector`**，只有 `pg_trgm`。
   於是 `alpha.3` 唯一一個非純 additive 的資料庫變更變成一行 contrib extension，
   而它在 compose 與 Railway 兩條路徑都要驗（`KN-02` 的出口條件）。
2. ~~`SCOPE-013`~~ **`GATE-KN-NO-NEW-EGRESS (httpx)`**（Central 對外連線只有 `services/providers.py` 一個模組）——**引用錯了三處，2026-08-28 由 `plan/27` 的 `HD-00` 更正**：SCOPE-013 的實際文字是「不由平台自建對外反向代理；埠轉發以第三方整合交付」，與模組數無關。單模組是一個 **gate**，而 gate 可以被一個決定改寫（`beta.2` 的 D119 就把它改成明列的兩個）；一條需求不行。把 gate 當需求引用，會讓一個本來可以討論的限制看起來不能討論
   **在 `alpha.3` 維持不變**，SR-2 的「Central 未新增對外連線」那一項成為可過的條件。
3. [`10`](./10-verification-and-exit.md) §10 第 1 項（「沒有向量檢索的召回率損失」）
   從「D40 裁決後量」改為 **`KN-12` 的 relevance eval 建立基準值**——
   之後若要重啟向量，那組基準就是對照組。

若日後要加，進 Horizon 2 並需獨立 ADR，範圍至少涵蓋：
embedding provider 的 egress 目的地、金鑰治理、成本模型、
以及**刪除保證**（一個 source 被 tombstone 之後，它的 embedding 也必須消失）。

### ☑ D42 — 維持「一個 run 一個未答問題」（**2026-08-16 已裁決：不放寬**）

| | |
|---|---|
| **裁決** | `alpha.2` **不放寬**；`beta.1` 依真實對話資料再議 |
| **不同意的話** | `CV-05` 的 CAS 從單列變成多列，需要定義「答了 2/3 題要不要續跑」的產品規則。**這條規則現在沒有資料可以回答**，猜錯的成本是每次續跑都在半個上下文上做決定 |

### ☑ D44 — `alpha.2` 不動 contract（**2026-08-16 已裁決：不動**）

| | |
|---|---|
| **裁決** | **不動**（維持 1.13.0）。continuation turn 走既有 offer／poll，延遲目標 P95 < 10s |
| **不同意的話** | contract 升 1.14.0、新增兩個訊息型別、`runner.register.features` 加宣告、`agentd` 升 0.13.0，並且**所有未升級節點必須驗證「收到未知型別不會壞」**——而 1.13.0 的 changelog 已經記錄過一次「未升級節點靜默丟棄 offer」的缺陷 |
| **注意** | 這一項與 §1.2 是同一個決定的兩面。裁決 D44 = 裁決 §1.2 |

### ☑ ★ D46 — provider（PR／MR／Release）同步落在哪一版（**2026-08-25 已裁決**）

| | |
|---|---|
| **裁決** | **`beta.2`，且只做 pull**（`plan/27` 的 ★ D120）。理由是它是本輪唯一新增對外副作用的工作，而 pull 連那個副作用都只剩唯讀 GET |
| **建議**（原文） | `beta.2`。理由是它是本輪唯一新增對外副作用的工作 |
| **不同意的話** | `alpha.3` 的安全審查範圍要涵蓋 inbound webhook、signature 驗證、delivery 去重、provider token 保存與輪替，時程約多兩個工作波次 |

### ☑ D51 — conversation 與 knowledge 的保留、匯出與刪除政策（**2026-08-22 已裁決**）

| | |
|---|---|
| **要決定什麼** | ① message body 保留多久（現有 run log 有 `logs_expire_at`，message 沒有）② 附件是否允許、上限、型別 ③ Project 刪除時 knowledge 的 tombstone 範圍 ④ 是否提供使用者匯出 |
| **建議** | message **永久保留**（它是產品資料不是診斷資料，run log 才是後者）；附件沿用既有 artifact 的配額與型別檢查，**不另開一條上傳路徑**；Project 刪除 cascade 到 chunks／index／cache，並有測試；匯出延後到 `beta.2` |
| **不決定的話** | `CV-03` 的 schema 少一欄就得再 migrate，`KN-02` 的 cascade 測試寫不出來 |

---

## 4. 決策全文

### D37 — Ticket 是持久對話；Run 與 Turn 是可替換的執行

**模型**：

```text
Ticket   = 持久工作項目 ＋ 持久 conversation      （平台 DB 的事實）
Run      = 一次受控執行                          （可失敗、可取消、可被替換）
Turn     = Agent 對一批 conversation input 的一次回應
```

一張 Ticket 跨越多個 run／turn。run 結束、lost、retry、daemon 重啟或更換 runner，
**都不得讓 conversation 消失**。Run log 是**診斷資料**，有保留期；
conversation message 是**產品資料**，不從 log 解析產生。

這條的可測形式是 [`10`](./10-verification-and-exit.md) 的出口條件：
清掉某張卡所有 run log 之後，conversation、question 與 spec proposal 仍完整。

→ ADR 0035

### D38 — `conversation_seq` 是 `tasks` 上的計數器欄，不是全域 sequence

每張 Ticket 需要一個**單調遞增、無洞、每卡獨立**的序號。三個候選：

| 做法 | 問題 |
|---|---|
| PostgreSQL `SEQUENCE` | 全域單調但**每卡有洞**；且 rollback 會消耗號碼，cursor 語意變模糊 |
| `SELECT max(seq)+1` | 併發下重複；加 `FOR UPDATE` 就是下一個做法但鎖的是訊息表 |
| **`tasks.conversation_seq` 計數器 ＋ 同交易 `UPDATE … RETURNING`** | ✅ 鎖的是卡片列（本來就要更新 `updated_at`），無洞，且**看板讀模型免費得到 `conversation_last_seq`** |

採第三種。附帶好處是 §1.5 的 `WorkItemCardDTO` 不必為了顯示「有幾則新訊息」去 join
`task_messages`——那個 join 在 200 張卡的看板上會很貴。

### D39 — Continuation turn 建模成 child run

見 §1.2。具體：

```text
task_runs 新增 parent_run_id (nullable, FK → task_runs.id)
task_runs 新增 turn_seq      (int, 同一條 conversation 內遞增)
task_runs 新增 input_from_seq / input_to_seq
```

**不新增 `run_turns` 表**（提案 §10A.7 建議的）。理由：`task_runs` 已經有完整的
狀態機、租約、重排、log、取消與 audit；再開一張表等於維護兩套生命週期，
而 UI 無論如何都要把它們聚合成一條對話。

UI 把 `parent_run_id` 鏈聚合為同一個 conversation，**不要求使用者理解底層 attempt**。

→ ADR 0035

### ☑ D40 — `alpha.3` 的檢索不含向量（**2026-08-16 已裁決**）

見 §1.3 與 §3。→ ADR 0038

### D41 — Answer ＋ resume 是單一 transaction endpoint

```text
POST /api/tasks/{id}/questions/{questionId}/answer
```

一個交易內做完四件事：

1. `UPDATE task_questions SET state='answered', answered_at=now() WHERE id=? AND state='open'`
   ——影響 0 列 → `409 QUESTION_ALREADY_ANSWERED`
2. `INSERT task_messages`（`kind='answer'`、`question_id`、`reply_to_message_id`、`conversation_seq`）
3. 若 `resume=true`：建立 child run（`parent_run_id`、`input_from_seq`、`input_to_seq`）
4. 寫 activity 與 audit（**只記 metadata，不複製 message body**）

**不拆成兩個 endpoint。** 拆了就有「answer 已保存但 continuation 沒建立」這個狀態，
而那個狀態在 UI 上長得跟「Agent 還沒回」一模一樣。

### ☑ D42 — 維持單一未答問題（**2026-08-16 已裁決**）

見 §1.6 與 §3。

### D43 — Message 不可覆寫；人類編輯走 revision，Agent 只能追加更正

`actor`、`kind`、`reply relation`、`conversation_seq` 與原文**建立後不可改**。

- 人類編輯：`alpha.2` **不提供**（`beta.1` 再評估）。若提供，採 revision history，
  且**修改事件本身進下一個 turn 的 input**——否則 Agent 讀到的是被改過的歷史。
- Agent 訊息：**永不提供編輯**。錯了就追加一則更正。

理由與 `task_artifacts` 沒有 update path 是同一條：可以被單獨抹掉的紀錄不是紀錄。

### ☑ D44 — `alpha.2` 不動 contract（**2026-08-16 已裁決**）

見 §1.2 與 §3。

### D45 — Knowledge 的 authority 是欄位，不是推導

```text
authoritative  人類正式決策、policy、accepted ADR
accepted       accepted spec、approved requirement
canonical      merged code、目前分支文件、Release
verified       通過 verification 的 evidence／artifact
reviewed       已審 PR／MR 或人類確認的摘要
generated      Agent proposal、turn summary、未核准分析
discussion     Ticket 對話、PR 討論
diagnostic     failure、人類選定的 log excerpt
superseded     已被新版本取代，只供歷史查詢
retracted      已撤回，不進預設 retrieval
```

**存成 `knowledge_sources.authority` 欄位而不是在檢索時推導。** 三個理由：

1. 推導需要 join 到來源表，而來源有八種，檢索路徑會變成八個 join。
2. authority 會**隨事件變化**（PR merge → `reviewed` 升 `canonical`），變化本身要可稽核。
3. 「這段內容當時是什麼權威等級」是歷史事實。推導只能回答「現在是什麼」。

寫入 authority 的權力**只在 ingestion pipeline 手上**，API 不接受呼叫端指定
——與 `FR-VERIFY-002`「三級 `source` 由伺服器端判定，忽略 payload」同一條原則。

→ ADR 0038

### ★ D46 — Provider 同步移到 `beta.2`

見 §1.4 與 §3。

### D47 — Instruction 與 evidence 分層；來源文字永遠先是 data

Context pack 有兩個結構上分開的區塊：

```text
[ instruction layer ]   只有 accepted Project policy 與平台自己的規則可以進
[ evidence layer   ]    其餘全部——repo 文件、PR 討論、Ticket 對話、Agent proposal
```

evidence layer 的內容在 render 時**明確標示為引用資料**，且：

- repo 文件裡寫「忽略上述規則」不會因此成為指令。
- 未核准的 Agent proposal **永不**進 instruction layer。
- context budget 不足時，**先砍 evidence，不砍 instruction**。

可測形式：`KN-12` 的 prompt injection 測試——一份含注入字串的 repo 文件進 index 之後，
產出的 context pack 中該字串必須出現在 evidence 區塊且帶 citation，
**不得出現在 instruction 區塊**。

→ ADR 0039

### D48 — 新 `WorkItemCardDTO` 與新 endpoint，`BoardCardDTO` 不動

見 §1.5。

### D49 — Stage 第一版只做 projection

見 §1.7。→ ADR 0040

### D50 — Rank 用 lexicographic 字串，從 kintra 移植純函式

見 §1.8、§1.9。`tasks.rank VARCHAR(64) NOT NULL`，backfill 依現有
`ORDER BY updated_at DESC` 的順序產生初始值。scope = project。
再平衡門檻沿用 kintra 的 24／48（背景／同步保險閥）。

### ☑ D51 — 保留、匯出與刪除政策（**2026-08-22 已裁決**）

見 §3。前兩問由 ADR 0041（`alpha.2`）回答，後兩問由 **ADR 0038 §6**（`alpha.3`，`plan/25` D81）回答。

### D52 — 不替 Conversation 與 Knowledge 開部署旗標

現有兩個旗標（`CLIORA_PROJECTS_ENABLED`、`CLIORA_AGENT_RUNS_ENABLED`）刻意分開，
因為看板與自主執行的**風險等級**不同。Conversation 與 Knowledge 不適用同一個理由：

- **Conversation 是既有 `task_messages` 的修復。** 用旗標關掉它，等於讓同一張表
  在兩種語意間漂移：關閉時寫入的訊息沒有 seq，開啟後 cursor 就有洞。
- **Knowledge 的成本與風險是逐專案的**，不是逐部署的。一個 500 檔的專案與一個
  50000 檔的 monorepo 需要不同答案，而部署旗標給不出不同答案。

所以：Conversation **沒有旗標**（additive、預設啟用）；
Knowledge 用 **per-project 的 ingestion 設定**（見 D58）；
只有 `CLIORA_PROJECT_EXPERIENCE_V2` 是新的部署旗標。

### D53 — View 有 personal／project 兩種 scope，**不新增 RBAC 動作**

| 操作 | 需要什麼 |
|---|---|
| 讀 project view | `project.view` |
| 建立／改／刪 **自己的** personal view | `project.view`（擁有者比對，非 RBAC 動作） |
| 建立／改／刪 project view | **`project.manage`** |
| 改 project default view | `project.manage` ＋ **audit** |
| 複製 project view 成 personal view | `project.view` |

**不新增 `project.view.manage`**（提案 §7.4 提過）。RBAC 動作是 seed migration
與角色矩陣的一部分，加一個就要動 `rbac.py`、seed、以及三個角色的權限表；
而 `project.manage` 的持有者集合正好就是應該能改共用 view 的人。
**每多一個動作，`RUN_TOKEN_SCOPES` 就多一個要證明「不在裡面」的東西。**

View 不影響 Task 權限：無權查看的 Task 在 **query boundary** 排除，
不是在序列化時過濾——counts 與 items 用同一個 predicate（`PX-25`）。

### D54 — Filter 是 allowlist 結構，不做自由 DSL

API 接受的結構：

```json
{ "and": [ { "field": "stage", "op": "in", "value": ["ready", "in_progress"] } ] }
```

- **欄位 allowlist**（15 個，見 [`04`](./04-phase-p1-view-and-read-model.md) §3）。
- **運算子 allowlist**（`eq`／`neq`／`in`／`not_in`／`gt`／`lt`／`is_null`／`contains`）。
- 巢狀深度上限 3、條件數上限 20。
- 每個 (field, op) 組合有明確的 SQL 編譯路徑與索引；**沒有動態 SQL 字串拼接**。
- 不合法的 field／op 回 `400 FILTER_FIELD_NOT_ALLOWED`／`FILTER_OP_NOT_ALLOWED`，
  **回應要指名是哪一個**。

第一版 UI 不做自由文字編輯器，但 API 從第一版就用這個結構，
所以之後加 UI 不必改 API。

### D55 — Attention 由 backend 單一函式推導

```python
derive_attention(task, active_run, gates, verification, blocking) -> AttentionDTO
```

固定優先序（提案 §6.3，採納不改）：

```text
1 waiting_for_your_input     2 pending_human_approval
3 verification_failed        4 run_failed
5 no_eligible_runner         6 assigned_runner_offline
7 dependency_blocked         8 over_wip_or_stale
```

同一個函式服務 work-items、My Work、Project Overview 與 Drawer。
卡片只顯示 **primary attention**，其餘只顯示數量。
**前端不得各自重建優先序**——`PX-24` 的測試在 backend，前端的測試只驗證「照著渲染」。

### D56 — 前端不引入 query cache 套件，擴充既有 `useAsyncResource`

`frontend/package.json` 目前沒有任何 server-state 套件；資料層是
`composables/useAsyncResource.ts` ＋ Pinia store 手寫。引入 TanStack Query 會：
新增一個 runtime 依賴、與既有 12 個 store 產生兩套模式、並讓 `plan/19` 建立的
測試慣例（`@vue/test-utils` ＋ vitest）多一層 mock 面。

**改成**：擴充 `useAsyncResource` 成有 key、有 invalidation、有 optimistic snapshot／rollback
的最小 query 層（`PX-27`），約 200–300 行，並要求：

- query key 由 `(project, view, filter, group, sort)` 組成。
- optimistic mutation 一定有 snapshot 與 rollback。
- task update invalidate card、drawer、counts 與相關 group。
- **打開 Drawer 不 reload 整個 Board。**

這是一個**有明確反悔點**的決定：若 `beta.1` 期間這 300 行開始長成第二個框架，
就在 `beta.2` 改用套件，並把它記進 [`10`](./10-verification-and-exit.md) 的未量測項。

### D57 — 不直接複製 kintra 元件

見 §1.9 的表。追加一條紅線：**不建立跨 repo 的共用 package**。
兩邊的版本治理成本高於重寫成本，而且 Cliora 有 feature flag、runner tag、
secret name 與 delivery policy，kintra 一個都沒有。

### D58 — Knowledge 是 per-project opt-in

`projects` 新增 `knowledge_enabled BOOLEAN NOT NULL DEFAULT false` 與
`knowledge_settings JSONB`（exclude rules、repo sync 範圍、retention 覆寫）。

- 關閉時：不 ingest、不建 index、search API 回 `404`（不是 403——不揭露設定狀態）。
- 開啟需 `project.manage`，並寫 audit。
- 關閉後既有 sources 標為 inactive，**不立即刪除**；刪除是獨立動作，要求二次確認並寫 audit。

→ ADR 0038

---

## 5. ADR 清單

| ADR | 標題 | 對應決策 | 里程碑 |
|---|---|---|---|
| 0035 | Ticket conversation、run turn 與 continuation 模型 | D37、D39、D41 | `alpha.2` |
| 0036 | Conversation 的傳遞語意：cursor、idempotency、at-least-once | D38、D43 | `alpha.2` |
| 0037 | Conversation 的權限與 actor 邊界 | D43、D52 | `alpha.2` |
| 0038 | Project Knowledge 的來源、權威層級與 project isolation | D40、D45、D58 | `alpha.3` |
| 0039 | Context Builder：instruction／evidence 分層與 budget policy | D47 | `alpha.3` |
| 0040 | Work lifecycle、attention projection 與 stage 相容策略 | D49、D55 | `beta.1` |
| 0041 | Conversation 與 knowledge 的保留、匯出與刪除 | D51 | `alpha.2`／`alpha.3` |
| 0042 | View schema、scope、權限與 rank | D50、D53、D54 | `beta.1` |
| 0043 | Provider ingestion：webhook 信任邊界與 reconciliation | D46 | `beta.2` |
