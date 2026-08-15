# 02 — 資料層（`RQ-02`）

一支 migration：**`0039_requirements_agent_driven`**（`down_revision = "0038_runner_features"`）。

四項 `ALTER`、一張新表、兩個索引。**沒有任何一項會改寫既有資料**，
所以它與 V2.3 的 `0033`（那一支會收緊既有列）不同類，降級是乾淨的。

## 0. 先對齊：上游寫的資料模型有一半已經不存在了

`research/02/07` RQ-02 給了一份 migration `0030` 的草圖。**逐欄核對之後，
那份草圖有九處與現況不符**，而其中五處照做會讓 `alembic upgrade head` 當場失敗。

| 上游寫的 | 實際 | 處置 |
|---|---|---|
| migration `0030` | head 是 `0038` | 本期是 **`0039`** |
| 建 `requirements` 表 | **`0023_task_board` 已建** | 不建 |
| 建 `feature_specs` 表 | **已建** | 不建 |
| 建 `task_proposals` 表 | **已建** | 不建 |
| `requirements.title` / `body` | 實際是單一欄位 **`raw_text`** | 不改（單欄是刻意的：intake 只接受一句話） |
| `requirements.status: draft\|...` | 實際首值是 **`intake`** | 不改 |
| `requirements.epic_id` | **不存在** | **不加**（`00-…md` §4 的理由） |
| `feature_specs.risk` / `affected_areas` | **不存在** | 併進新的 `sections`（§1.3） |
| `feature_specs.approved_by` / `approved_at` | 不在這張表，在 **`requirements`** 上 | 不改。核准的對象是需求不是某一版規格，而那是對的：規格是版本列 |
| `task_proposals.spec_seq` | 實際是 **`spec_id`**（外鍵） | 不改 |
| `task_proposals.created_task_ids` | 不存在，改由 **`tasks.proposal_id` 反查** | 不加（反查已經有索引需求，§3） |

**這張表要進 `01-…md` §4.3 的回寫清單**，否則下一個讀 `research/02/07` 的人會再踩一次。

## 1. 四項 `ALTER`

### 1.1 `tasks.card_kind` — D1

```sql
ALTER TABLE tasks ADD COLUMN card_kind VARCHAR(16)
  NOT NULL DEFAULT 'implementation';
```

四值：`implementation`｜`clarification`｜`decomposition`｜`mockup`。

**用 `VARCHAR` ＋ 服務層封閉集合，不用 PostgreSQL `ENUM`**，
與 `tasks.stage`、`tasks.delivery`、`tasks.source` 三個既有欄位一致
（`models.py:715-733` 全是 `String(16)`）。理由與那三個相同：
一個 `ENUM` 要加值需要 `ALTER TYPE`，而它在交易裡的行為與 `ALTER TABLE` 不同，
遷移演練會多一種要驗的東西。

**`server_default` 是 `'implementation'` 而不是 NULL**，
所以既有的每一張卡都在遷移當下取得一個明確的種類——
`03-…md` §1 的四道 dispatch 拒絕全部讀這個欄位，
一個 NULL 會讓那四道 `if` 各自要處理「不知道」。

#### 1.1.1 它有 run 跑過之後不可改

```text
PATCH /api/tasks/{id}  changes 含 card_kind
  → 該卡存在任何一列 task_runs  → 409 TASK_KIND_LOCKED
```

**為什麼是「有 run 跑過」而不是「有進行中的 run」**：
一張釐清卡跑完之後改成實作卡，它的訊息串、規格版本與 run log 就掛在一張說自己是實作卡的卡上。
稽核時那看起來像「一張實作卡不知為何產出了規格」。
**歷史不可改，所以種類也不可改。**

`card_kind` 進 `EDITABLE_FIELDS`（否則連建立後第一次修正都不行），
但**不進** `AGENT_FORBIDDEN_FIELDS` 之外的任何放寬——
它要**加進** `AGENT_FORBIDDEN_FIELDS`：

```python
AGENT_FORBIDDEN_FIELDS = frozenset(
    {"gates", "owner_user_id", "assigned_runner_id", "required_secrets", "card_kind"}
)
```

**理由**：一個釐清 run 若能把自己的卡改成 `implementation`，
它就繞過了「釐清卡不得帶機密」——下一次 dispatch 那張卡就可以帶了。

### 1.2 `feature_specs.run_id` 與 `task_proposals.run_id`

```sql
ALTER TABLE feature_specs  ADD COLUMN run_id UUID
  REFERENCES task_runs(id) ON DELETE SET NULL;
ALTER TABLE task_proposals ADD COLUMN run_id UUID
  REFERENCES task_runs(id) ON DELETE SET NULL;
```

**`SET NULL` 而不是 `CASCADE`**，與 `task_messages.run_id` 完全相同的理由
（`models.py:1134`）：run 的紀錄有保留期，**而規格與提案沒有**。
一份規格不該因為產出它的 run 被回收而消失。

**兩欄都可為 NULL**，因為人寫的規格與人拆的提案沒有 run——
V2.1 的路徑一個位元組都不改。

用途只有一個，但那一個是本期的核心：**規格審閱畫面上要能說
「這一版是 REQ-7 的釐清 run #2 寫的」並連過去看 log**。
沒有這個欄位，`authored_by_kind='runner'` 只能說「某個機器」。

### 1.3 `feature_specs.sections` — D0

```sql
ALTER TABLE feature_specs ADD COLUMN sections JSONB
  NOT NULL DEFAULT '{}'::jsonb;
```

**九個封閉的鍵**，逐一對應 `../Monstrare/ai/templates/feature-spec.md`
的節（MIT，ADR 要標註出處）：

| 鍵 | 型別 | Monstrare 的節 | 誰吃它 |
|---|---|---|---|
| `problem` | `str` | 問題 | 規格審閱；`objective` 是「要做什麼」，這是「要解決什麼」 |
| `users` | `str` | 使用者 | 規格審閱 |
| `user_stories` | `list[{title, narrative, acceptance}]` | 使用者故事 | **拆解 run**——Epic→US→Task 的中間層 |
| `journeys` | `str` | 使用者旅程 | 規格審閱 |
| `functional_requirements` | `list[str]`（`WHEN … THE SYSTEM SHALL …`） | 功能需求 | 拆解 run 產生 AC 的來源 |
| `screens` | `list[{name, states, note}]` | 畫面 | `card_kind: mockup` 與 `gates.ui` 的上游 |
| `data_and_api` | `{inputs, outputs, validation, errors}` | 資料與 API | 拆解 run 的後端卡 |
| `security_privacy` | `{authn, authz, sensitive_data, abuse}` | 安全性與隱私 | **停止條件第四條的落點**（§5） |
| `verification_plan` | `{unit, integration, e2e, visual, manual}` | 驗證計畫 | 拆解 run 填 DoR 的「驗證方式已定義」 |

**封閉的意思是伺服器端驗證**：`POST /api/cli/runs/spec` 與人工的
`POST /requirements/{id}/specs` 都對 `sections` 的**頂層鍵**做白名單，
未知鍵回 `422 SPEC_SECTION_UNKNOWN` 並列出它。
**節的內容不驗**（那是文件），只驗鍵。

**不驗內容的代價要寫進 ADR**：一份 `sections` 全空的規格是合法的。
擋它的不是 schema，是**規格核准那道人工關卡**——
而那正是 D28 §3 說的「每個關卡都必帶人類 actor」。

#### 1.3.1 `sections` 不影響 `open_questions` 的閘門

`_open_questions()`（`requirements.py:65-75`）只讀 `open_questions`，本期不改它。
**這一句要寫下來**，因為很容易想「`sections` 裡也可能有問題」——
不要。**未解決的問題只有一個地方**，那是 `open_questions` 成為一等欄位的全部意義。

### 1.4 `tasks.links` 的兩個新約定鍵（無 schema 變更）

`links` 是既有的 JSONB。本期約定兩個鍵，**不改欄位**：

| 鍵 | 值 | 誰寫 |
|---|---|---|
| `proposal_item_id` | 提案樹裡那個節點的 id | **已存在**（`requirements.py:375`），本期只加索引（§3） |
| `patch_proposal_id` | 這張卡是為了套用哪一份 PRD patch 而建的 | RQ-08 的接受畫面（`05-…md` §4） |

`links.mockupDecision`（D31 與 Monstrare `mockup-decision.md` 都用這個名字）
**本期不寫入**——RQ-11b 才寫。約定先記在 ADR 0034，避免下一期換個拼法。

## 2. 一張新表：`document_patch_proposals`

```sql
CREATE TABLE document_patch_proposals (
  id             UUID PRIMARY KEY,
  project_id     UUID NOT NULL REFERENCES projects(id)     ON DELETE CASCADE,
  requirement_id UUID          REFERENCES requirements(id) ON DELETE SET NULL,
  run_id         UUID          REFERENCES task_runs(id)    ON DELETE SET NULL,
  seq            INTEGER NOT NULL,
  target_path    VARCHAR(512) NOT NULL,
  diff           TEXT NOT NULL,
  sections       JSONB NOT NULL DEFAULT '{}'::jsonb,
  reason         TEXT,
  related_task_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  open_questions   JSONB NOT NULL DEFAULT '[]'::jsonb,
  status         VARCHAR(16) NOT NULL DEFAULT 'pending',
  decided_by     UUID REFERENCES users(id) ON DELETE SET NULL,
  decided_at     TIMESTAMPTZ,
  decision_note  TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, seq)
);
```

五個設計說明：

1. **只 INSERT。** 與 `feature_specs`／`execution_plans` 同一條姿態（D9）。
   一份被就地改寫的 patch 提案，等於改寫了人當初看過的東西。
   `GATE-RQ-APPEND-ONLY` 對它斷言。
2. **`diff` 是 `TEXT` 不是 JSONB。** 它是一份 unified diff，
   平台**不解析它**——`00-…md` §0 C 類的 256 KiB 上限是唯一的處理。
   解析它就是往「平台套用 patch」那條路走了一半。
3. **`sections` 照 `version2.md` §7.6 的四項**：
   `added_sections`／`modified_sections`／`removed_sections`／`related_docs`。
   與 `feature_specs.sections` 一樣是封閉鍵。
4. **`seq` 的 scope 是 project 不是 requirement。** patch 提案可能來自一個沒有需求的 run
   （例如一張「把 ADR 0031 的增補補齊」的實作卡），所以 `requirement_id` 可為 NULL，
   而編號要在專案內唯一才有辨識度。
5. **`target_path` 是 repo 相對路徑，且在寫入時驗證**：
   不得為絕對路徑、不得含 `..`、不得以 `/` 開頭。
   **這不是路徑安全**（平台不會去讀那個檔案），**是可讀性**——
   一個 `../../etc/passwd` 的 `target_path` 會出現在人的審閱畫面上，
   而那時它已經是一個看起來像攻擊的東西了。

### 2.1 為什麼不重用 `task_artifacts`

一份 patch 提案「就是一個檔案」，很自然會想附成產物。**三個理由否決**：

| | 產物 | patch 提案 |
|---|---|---|
| 有沒有「決定」 | 沒有。附上去就是附上去了 | **有**：接受／拒絕 ＋ 理由 ＋ 誰 ＋ 何時 |
| 可不可變 | 不可變（D29 §6） | 也不可變，但**狀態會變**——而產物沒有狀態欄位 |
| 查詢 | 依 run／卡片列 | **依專案列「還沒決定的」**，那是一個 index 撐的清單 |

把「需要人決定的東西」塞進一張刻意設計成惰性資料的表，
會讓 D29「產物是最安全的一種出口，因為它不觸發任何東西」這句話立刻失效。

## 3. 兩個索引

```sql
CREATE INDEX ix_tasks_proposal_item
  ON tasks ((links ->> 'proposal_item_id')) WHERE proposal_id IS NOT NULL;
CREATE INDEX ix_document_patch_proposals_pending
  ON document_patch_proposals (project_id, created_at DESC) WHERE status = 'pending';
```

**第一個是修一個既有的效能洞，不是新功能。**
`requirements.accept()`（`requirements.py:341-346`）為了冪等，
每次接受都要查「這個提案已經產出過哪些 item」——它現在是
`SELECT * FROM tasks WHERE proposal_id = ?` 然後在 Python 裡讀 JSONB。
卡片數少時無所謂；**一次拆解 40 張的情況下這是本期會第一個被看見的慢查詢**，
而症狀是「按下接受之後轉圈很久」，沒有人會把它連到 JSONB 上。

**第二個是部分索引**，因為 `pending` 是唯一會被列的狀態，
而已決定的提案只會被單筆讀取。

## 4. 不加的四個欄位

| 上游或直覺會想加的 | 為什麼不加 |
|---|---|
| `requirements.epic_id` | `00-…md` §4。接受提案時建立的 Epic 在 JSONB 樹裡，回填需要一條 `requirements` 沒有的 UPDATE 路徑；反查 `tasks.requirement_id` 就夠 |
| `task_proposals.created_task_ids` | 同一份資訊在 `tasks.proposal_id` 上，而那裡是有外鍵的一份。兩份會分歧 |
| `task_messages.answers_message_id` | D3 的「一次一個問題」用 `created_at` ＋ `author_kind` 的 `EXISTS` 判定就夠（`03-…md` §3.2）。加一個回覆指標會讓「使用者回了一句無關的話算不算回答」變成一個要判斷的問題——**而它應該算**，因為 Agent 該重問而不是永遠等著 |
| `feature_specs.approved_by` | 核准的對象是**需求**不是某一版規格（`requirements.approved_by` 已存在）。加在版本列上會產生「第 2 版被核准、第 3 版沒有」這種狀態，而 `add_spec` 在需求已核准時本來就拒絕（`requirements.py:191-196`） |

## 5. 停止條件第四條在資料層的落點

Monstrare `context-protocol.md` 的第四條停止條件是
「任務涉及密鑰、身分驗證、金流、遷移或基礎設施」。
平台**沒有 `security` review gate**（README「上游的另一半」§三）。

本期的代償是三個既有欄位的組合，**不加新欄位**：

```text
sections.security_privacy   ← 規格層：這個需求碰到什麼
open_questions              ← 命中第四條時問題留在這裡，Agent 不得自己選
tasks.risk = 'high'         ← 提案層：拆解時強制標高
```

而**強制的位置在提案提交**（`04-…md` §2.4）：
提案樹的節點若 `sections.security_privacy` 有非空內容、
或標題／目標命中一組關鍵詞，`risk` 不是 `high` 就回 `422`。

**關鍵詞比對是刻意的粗糙。** 它會誤報（一張「移除舊的認證說明文件」的卡被標高風險），
而誤報的代價是「多一個高風險徽章」，漏報的代價是「一張碰金流的卡以 `low` 進 `ready`」。
兩者不對稱，所以選會誤報的那一邊——**這一句要寫進 ADR 0034 §4**。

## 6. 遷移演練

| 檢查 | 方法 |
|---|---|
| 上行 | `alembic upgrade head`，schema 與基線比對只允許新增 |
| 下行 | `alembic downgrade 0038_runner_features`，**與基線 `schema.txt` 逐位元組相同** |
| 既有列不被改寫 | 遷移前後對 `tasks`／`feature_specs`／`task_proposals` 做 `md5(row::text)` 的集合比對，**只有新欄位造成的差異**（所以要比對舊欄位的投影，不是整列） |
| 預設值真的落在既有列 | `SELECT count(*) FROM tasks WHERE card_kind <> 'implementation'` ＝ 0 |
| V2.1 寫的規格照樣讀得出來 | 遷移後 `GET /api/requirements/{id}` 對一份 V2.1 的規格，`sections` 是 `{}`，其餘五欄不變 |

**下行的目標參數化**（沿用 `plan/20/08` §6 第 10 條修好的 `gate-migration-roundtrip.sh`）：
`scripts/rq/gates.sh` 傳 `0038_runner_features`。
