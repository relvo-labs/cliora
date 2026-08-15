# 01 — 基線、決策文件與治理（`RQ-00`／`RQ-01`）

本檔是本期「寫下來的東西」：基線、一份新 ADR、兩則增補、PRD 的一節、traceability，
以及**一張要一起帶著問的清單**——V2.4 留下的一個範圍問題，本期不解它，但本期會放大它，
所以要在這裡寫明白，而不是等它自己在第三次拆解時炸開。

## 1. `RQ-00` — 基線擷取

沿用前三期的做法：**`scripts/rq/capture-baseline.sh` 是
`scripts/ar/capture-baseline.sh` 的一層 `BASELINE_OUT` 覆寫**，不複製那 60 行。
（`plan/20/08` §3 第 2 條記了為什麼：兩份會在其中一份被修好的第一時間開始分歧。）

```bash
AR_BASELINE_ALLOW_DIRTY=1 \
CLIORA_DATABASE_URL=postgresql+asyncpg://cliora:cliora@127.0.0.1:5432/cliora_rq_baseline \
  scripts/rq/capture-baseline.sh
```

| 檔案 | 內容 | 預期（2026-08-14 實測） |
|---|---|---|
| `COMMIT` | commit ＋ 時間 ＋ 未提交路徑清單 | 未提交的應只有 `research/02/`、`plan/22/`、`scripts/rq/` |
| `openapi-flags-off.json` / `-on.json` | 旗標關閉／開啟的 OpenAPI | **兩份逐位元組相同** |
| `schema.txt` | 表清單 ＋ 目前 revision | **40 行**（39 個 `__tablename__` ＋ `alembic_version`）、`0038_runner_features` |
| `contract-fixtures.txt` | fixture 清單 | **184 行** ＝ 183 個檔（76 valid ＋ 107 invalid）＋ `manifest.json` |
| `frontend-routes.txt` | 路由清單 | **19 條** |
| `terminal-latency.json` | 終端延遲 | 三次連續量測取 p50 的中位數（沿用 `plan/21/01` §1 的修訂） |
| 🆕 `contract-tree.sha256` | `contracts/` 全樹的雜湊 | **本期唯一一個「整個目錄不准動」的禁區**（§5 gate） |

> ⚠️ **閘門一**：基線完成前不得動任何程式碼。
> 例外與前三期一致：擷取器本身（`scripts/rq/`）。

### 1.1 為什麼多一個 `contract-tree.sha256`

前三期的 `GATE-*-CONTRACT-ADDITIVE` 比對的是 **fixture 清單**，
它守的是「既有 fixture 沒被改」，而**允許新增**。

本期的承諾更強：**contract 一個位元組都不動**（§0 B 類第一項）。
一個「只比對清單」的 gate 會讓「新增一個 schema 欄位並補一個 valid fixture」完全合法通過
——而那正是本期最需要擋的動作（V2.4 README 易錯 1 的那條路）。
所以本期在既有 gate 之外**多一個全樹雜湊**，兩個一起跑。

## 2. `RQ-01` — ADR 0034

檔名：`docs/adr/0034-v25-clarification-decomposition-and-the-three-human-gates.md`

- **Status**: `proposed`，等第二道閘門（人的接受）。
  在被接受之前，`RQ-02` 起不得動 `backend/`、`frontend/`、`daemon/`。
  **一份自己標成 accepted 的文件會讓那道閘門失去意義**（沿用 ADR 0033 的做法）。
- **Amends**: ADR 0028（任務層）**增補 A**、ADR 0029（run 模型）**增補 D**。
- **Related**: ADR 0022（tunnel 的範圍宣告——**本期不增補它**，理由在 §2.5）、
  ADR 0027（JSONB 的判準——`feature_specs.sections` 與 `task_proposals.tree` 用同一條）、
  ADR 0030（產物是交付物）、ADR 0032（機密；本期新增一條「釐清 run 一律零機密」的收窄）、
  ADR 0033（五種 delivery——拆解決定用哪一種，本期不新增第六種）。
- **Requirements**: `FR-SPEC-002`…`-008`（`-001` 已由 V2.1 的 `FR-TASK-005` 交付，§4）。
- **Contract**: **v1.13.0，零變更。** 這一行要寫在 ADR 的抬頭，因為它是本期最容易被推翻的承諾。
- **Ships in**: Central（minor）、`agentd` **0.12.0**、frontend（minor）。

### 2.1 七節

**§1 — 釐清用既有管道，不新增介面。**
D28 的第一條，加上一段本計畫的發現：**這條路已經完整存在了**
（`run_router` 的 `GET/POST /messages`、`waiting_for_input`、24h reaper），
本期在它上面只加**一道伺服器端閘門**（一次一個問題，D3）。
**Alternatives rejected**：獨立的釐清聊天介面（管道分裂——使用者不知道在哪回話、
Agent 不知道讀哪邊、稽核要看兩個地方）；用 WebSocket 推送問題給使用者
（那是 Terminal relay 的語意，D24 已經否決過一次）。

**§2 — Agent 的產出是提案，不是正式資料。**
落地成一句可驗證的話：**Agent 寫得到的欄位與人寫得到的欄位，在資料庫上是不同的欄位。**

| Agent 寫得到 | 人才寫得到 |
|---|---|
| `feature_specs`（整列，`authored_by_kind='runner'`） | `requirements.status='approved'`、`approved_by`、`approved_at` |
| `task_proposals`（整列，`status` 恆為 `'pending'`） | `task_proposals.status ∈ {accepted, partially_accepted, rejected}`、`decided_by`、`decided_at` |
| `document_patch_proposals`（整列，`status='pending'`） | `document_patch_proposals.status`、`decided_by` |
| `task_messages`（`author_kind='agent'`） | — |
| `tasks` 的 `EDITABLE_FIELDS` 減去 `AGENT_FORBIDDEN_FIELDS` | `gates`、`verification_commands`、`card_kind`（§2.3） |

這張表就是 `09-…md` §3 的 `GATE-RQ-HUMAN-ACTOR` 與「授權」那一層測試的規格。

**§3 — 三個人工關卡。**
規格核准（`task.approve`）、提案接受（`task.approve`）、UI 變體選定（`task.approve`，RQ-11b）。
三個都必帶人類 actor 與 audit。
**而「Agent 憑證的 scope 永遠不含它們」不是一行 if**——是 `RUN_TOKEN_SCOPES` 這個常數，
以及 `get_agent_principal` 與 `get_current_user` 是兩條互相 401 的依賴（`agent_auth.py` 模組註解）。
本期照抄 V2.4 對 `tasks.verification_commands` 用過的同一段論證。

**§4 — 停止條件五條，內化進釐清情境包。**
搜尋發現多種做法且各有取捨／需求與既有架構衝突／缺少必要檔案／
任務涉及密鑰、認證、金流、遷移或基礎設施／預估範圍超出卡片。
**遇到任一條就停下來問，不要自己選。**
出處 `../Monstrare/ai/process/context-protocol.md`（MIT），ADR 要標註。

**§5 — 卡片種類（D1）。**
`tasks.card_kind` 四值、預設 `implementation`、**有 run 跑過之後不可改**。
它服務三條 dispatch 拒絕與兩條路由守衛，**而不服務任何顯示邏輯以外的東西**——
特別是**它不參與派工比對**（那是 tag，D18），這一句要明寫，
否則下一個人會很自然地想「釐清卡是不是該只給某些 runner」。

**§6 — 平台不套用 PRD patch。**
只渲染與記錄決定；接受之後走一張正常的 `delivery: pull_request` 卡片。
**理由不只是安全**：套用一份 markdown patch 是通用檔案編輯（`plan/14` 被撤銷的東西），
而讓它走一張正常的卡，PRD 的修改就跟程式碼一樣有 PR 可審。

**§7 — 內化總帳（Monstrare 對照）。**
README「上游的另一半」那張 12 列的表整段搬進來。
**這一節是 ADR 0034 唯一一個回頭看的部分**，也是唯一一次可以把
「V2 有沒有真的內化 Monstrare」這句話說完的機會——本期填的是
`kanban.md` 十二個治理欄位裡的第 2 格（待釐清）與第 6 格（待任務卡）。

同一節要誠實列出**沒有內化的四樣**，各附一句「為什麼不」：

| 沒內化 | 為什麼不 |
|---|---|
| `review-gates.md` 的 **Security Gate** | 改動的是每個專案的共用詞彙與 `process_definitions.version`，比 V2.5 大。代償見 `02-…md` §5 |
| `ui-mockup-gate.md` 依賴的 **`design-system.md`** | 平台沒有等價物，也沒有計畫要有。這是 RQ-11b 延後的第三個理由（`08-…md` §2） |
| `definition-of-ready.md` 的**條件式 DoR**（UI 8 項／後端 6 項／高風險 4 項的額外要求） | 平台的 `readiness` 是平坦七項。最小的補法在情境包而不是資料模型（`10-…md` §4 第 5 項） |
| `project-kickoff.md` 的 **Epic 0「專案設置」** | 它假設一個全新專案，而平台上的需求是往一個**已經存在的專案**丟的 |

### 2.2 授權標註（MIT）

本期有**四處**直接內化 `../Monstrare` 的內容，四處都要標註出處與 MIT：

| 內化到哪 | 來源 | 內容 |
|---|---|---|
| 釐清情境包第 13 段 | `ai/process/context-protocol.md` | 五條停止條件，逐字 |
| 拆解情境包第 6 段 | `ai/skills/implementation-plan.md` | 全端三分法、Epic 架構優先、MECE 兩條 |
| 拆解情境包第 7 段 | `ai/process/workflow.md` Phase 5 | 卡片大小五種 |
| `feature_specs.sections` 的九個鍵 ＋ `cliora spec template` | `ai/templates/feature-spec.md` | 規格書的節結構 |

第四處是**編譯進 binary** 的（`06-…md` §2.4），
所以授權標註要同時出現在 `daemon/internal/cli/` 的檔頭與 `NOTICE` 慣例所在之處
——與 migration `0026` 標 `source: 'monstrare'` 的做法一致。

### 2.3 ADR 0028 增補 A — `card_kind` 與「卡片種類不是 tag」

ADR 0028 定義了任務卡。本期給它多一個維度，而增補要回答的是
**「為什麼這不是 `required_labels` 的一個值」**——`00-…md` §0 D1 的三個 alternatives 全文搬進來。

還要補一句 ADR 0028 當時沒有的事實：**`tasks.requirement_id` 從 V2.1 就存在，
而它不足以判定卡片種類**——因為 RQ-07 建立的實作卡也帶它。

### 2.4 ADR 0029 增補 D — run 有了兩種它不產生程式碼的用途

ADR 0029 §1 描述的 run 是「在隔離目錄裡執行工作」。
本期加入兩種 run，它們**都不修改 repo**：

| | 釐清 run | 拆解 run |
|---|---|---|
| `card_kind` | `clarification` | `decomposition` |
| `source` | `repo`（預設）或 `none` | `repo` 或 `none` |
| `delivery` | **只允許 `none`／`artifact`** | **只允許 `none`／`artifact`** |
| `required_secrets` | **強制為空** | **強制為空** |
| 產出 | `feature_specs` 一到多列 ＋ 訊息串 | `task_proposals` 一列 |
| 對 repo 的影響 | 零 | 零 |

增補要寫清楚**這不擴大 run 的能力**：兩種 run 走的是完全相同的生命週期、
相同的租約、相同的 log 與產物路徑。**改變的只有情境包的內容與 dispatch 的四道拒絕。**

一件要一起寫進增補的事：**「工作目錄若有變更則明示並附成產物」這條 V2.4 的誠實性規則
（DV-01）對這兩種 run 一樣適用。** 一個釐清 run 不該改 repo，
但它可能為了讀懂程式碼跑了 `npm install`——那時工作目錄是髒的，
而 `delivery: none` 的誠實性規則會把 `git status --porcelain` 的結果顯示出來。
**這是對的行為，不是誤報**，出口條件 8 用它。

### 2.5 為什麼**不**增補 ADR 0022

`research/02/11` 列了「修訂 ADR 0022：tunnel 也用於 run 的 mockup 預覽」。
**D5 把 RQ-11b 延後，所以這則增補跟著延後。**

寫進本計畫而不是默默略過的理由：一則描述「tunnel 現在也服務 mockup」的增補，
在 mockup 預覽還沒有任何程式碼的時候寫下去，就是一句**過期的承諾**
——而 `GATE-DV-NO-STALE-PROMISE` 存在的原因正是這種東西
（`plan/21/08` §3）。本期沿用那個 gate。

## 3. `RQ-01` — PRD §8.16

新增一節：**§8.16 需求釐清與任務拆解**，接在 §8.15（交付、驗證與完成判準，`research/prd.md:2348`）之後。

七個小節，對齊 ADR 0034 的七節（§7 的內化總帳併進 8.16.7）：

| 小節 | 內容 |
|---|---|
| 8.16.1 | 一句模糊需求到卡片的完整流程圖（Intake → 釐清 → 規格 → 核准 → 拆解 → 接受 → 卡片） |
| 8.16.2 | 三個人工關卡，各自的進站條件與所需動作 |
| 8.16.3 | 釐清 run 的執行設定與四道 dispatch 拒絕 |
| 8.16.4 | 提案的 DoR 七項與「缺項落 `backlog`」 |
| 8.16.5 | PRD Patch 提案：平台只渲染與記錄 |
| 8.16.6 | UI Mockup 關卡的**條件性**（未啟用整合時整個關卡不存在） |
| 8.16.7 | 這一階段不做的六件事 ＋ 沒有內化的四樣（§2.1 的 §7） |

**§8.16.6 要寫成「關卡不存在」而不是「關卡停用」**，並附那張「什麼消失、什麼還在」的表。
截圖不會消失（D29 的通用能力），消失的是治理關卡。

## 4. `RQ-01` — traceability

### 4.1 FR-SPEC 的七個新 ID（`-001` 不新增）

| ID | 標題 | Owner | 本期的關鍵 AC |
|---|---|---|---|
| ~~FR-SPEC-001~~ | ~~需求 Intake 與規格資料模型~~ | — | **不新增**：V2.1 已以 `FR-TASK-005` 交付。traceability 加一條 `supersedes` 註記指過去 |
| FR-SPEC-002 | 釐清 run | central | 提問走既有訊息串；**一次一個問題是伺服器端 409**；五條停止條件在情境包 |
| FR-SPEC-003 | Open questions 閘門 | central | 未解決時規格不得核准（**API 409，不是按鈕停用**）；Agent 不得自行填答 |
| FR-SPEC-004 | 拆解 run 與提案 | central | 產出是提案不是卡；每張 Task 提案自帶 DoR 七項與 `source`／`delivery`；**提交路徑上不得出現 `create_task`** |
| FR-SPEC-005 | 提案接受 | central | 全部／部分／編輯後建立／拒絕；缺 DoR 落 `backlog`；被拒提案保留理由 |
| FR-SPEC-006 | 來源可追溯 | frontend | 每張卡回溯到需求與提案編號 |
| FR-SPEC-007 | PRD Patch 提案 | central | 平台只渲染與記錄，**不套用** |
| FR-SPEC-008 | UI Mockup 關卡 | frontend | **本期只交付「未啟用時」那一半**（RQ-11a）；已啟用的四項 AC 標為 `deferred` 並指向 RQ-11b |

**FR-SPEC-008 標 `deferred` 而不是省略**，因為 traceability 的覆蓋率報表兩個方向都會叫
（`make traceability-coverage`）：一個不存在的 ID 與一個沒有實作的 ID，
在報表上要能分辨，而只有後者是本期的刻意決定。

### 4.2 SEC 的一條收窄

本期不新增 SEC 需求，但要在既有的 `SEC-00Y`（機密）下加一條**收窄**：

> **釐清與拆解 run 一律不得攜帶機密**，在 dispatch 當下拒絕。
> 這不是「建議不要」，是一條 refusal——`research/02/07` RQ-03 的原文就寫著
> 「這一條要在 dispatch 時強制，不是建議」。

### 4.3 三份要同步修訂的既有文件

| 文件 | 修訂 |
|---|---|
| `docs/permission-matrix.md` | 27 個動作不變，但要補一列說明：**`task.approve` 現在守三個關卡而不是一個** |
| `docs/error-catalog.md` | 本期新增的七個 error code（`03`／`04`／`05` 各節列出） |
| `research/02/07-phase-v25-…md` | 回寫易錯 1（migration 編號與欄位名）、易錯 2（提案的權限）、D5（RQ-07 切兩半）。**執行計畫與規劃不一致時以執行計畫為準並回寫** |

## 5. 要一起帶著問的事（本期不解）

### 5.1 拆解會放大 V2.4 §6.3 的那個範圍問題

V2.4 的 `09-implementation-status.md` §6.3 留了一個裁決：
**ADR 0033 的「平台永不合併」是否要改寫成「**平台**永不合併」並明說 runner 側不受此約束**
（因為 Agent 自己也能開 PR，那條路是被支援的）。

**本期不解它**，但要寫下來的是：**拆解會把它的曝光面乘上一個數量級。**

```text
V2.4：一個人建一張 delivery: pull_request 的卡         → 一次一個決定
V2.5：一次拆解產生十張卡，其中六張 delivery: pull_request → 一個決定，六個結果
```

而**拆解時 `delivery` 是 Agent 建議的**（RQ-04 明寫「`delivery` 由拆解決定，
這是它最有價值的判斷之一」）。接受介面上人可以改，但**預設值是 Agent 給的**。

所以本期的處置有三條，都不是解法而是**讓它可見**：

1. 提案接受介面上，`delivery: pull_request` 的卡**顯示為一個獨立的計數**
   （「將建立 6 張會開 PR 的卡」），不與其他混在總數裡（`07-…md` §4.3）。
2. ADR 0034 §2 的那張表明寫「`delivery` 是 Agent 寫得到的欄位」。
3. 在 `01` 這一節記下：**V2.4 §6.3 的裁決應在本期之後、下一次真的大量拆解之前完成。**

### 5.2 M14 的答案本期才會知道

`research/02/10` §M14：**「V2.1 的人工規格／拆解表單有沒有人用？」**
——D28 §4 把它定成「V2.5 值不值得做的早期訊號」。

**這個訊號到今天還沒有被讀過。** 本期開工前應該花十分鐘查一次：

```sql
SELECT count(*) FROM requirements;
SELECT count(*) FROM feature_specs WHERE authored_by_kind = 'user';
SELECT count(*) FROM task_proposals;
```

**三個都是 0 的話，本期的價值主張要重新問一次**——不是不能做，
而是「沒人用人工流程，Agent 版也不會有人用」這句話是 D28 自己寫的。
若真的是 0，建議的處置是：**先用人工流程在 Traqora 上跑完一個真實需求**
（那也正好是 `RQ-12` E2E 的前半段），再決定要不要接 Agent。

**這一條不擋開工**，因為它的成本是十分鐘，而它的答案會改變的是優先順序不是設計。
