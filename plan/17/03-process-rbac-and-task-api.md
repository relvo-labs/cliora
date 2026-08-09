# 03 — 流程定義、RBAC 與 Task API（`TK-03`、`TK-04`、`TK-05`）

## 1. `TK-03` — 內化流程定義

把 Monstrare 的流程從檔案變成 `process_definitions` 的一列種子資料。
**出處要標註**：種子資料的 `source` 欄與 ADR 0028 都寫明流程定義源自 Monstrare（MIT）。

### 1.1 六車道（D3）

wire 值用 Monstrare 的 `stage`，UI 顯示中文標籤：

| stage | 中文標籤 | WIP 建議值 |
|---|---|---|
| `backlog` | 待辦 | — |
| `blocked` | 阻塞 | — |
| `ready` | 就緒 | 8 |
| `implementing` | 進行中 | 3 |
| `verify` | 驗證中 | 3 |
| `done` | 完成 | — |

WIP **顯示超標，不阻擋**（Monstrare 的既有語意）。

### 1.2 DoR 七項與 Review Gates 六項

readiness 七項來自 `ai/process/definition-of-ready.md`，gates 六項來自 `review-gates.md`。
每一項的 `key` 是穩定識別碼、`label_zh` 是顯示文字、`hint` 是表單上的提示。

**gates 的每一項都帶 `requires_human: true`**（`02-…md` §1.1），
而 `ui` 那一項另帶 `depends_on_integration: "tunnel"`。

### 1.3 `ui` gate 的衍生停用（D31、`00-…md` D10）

讀取流程定義時套用：

```text
tunnel_integration.enabled == false  ⇒  gates['ui'].enabled = false
                                         gates['ui'].disabled_reason = 'tunnel_integration_disabled'
```

三條規則：

1. **在讀取時套用，不是在種子資料裡。** Admin 可能在任何時候開關 tunnel 整合，
   而一個要靠 Admin 記得同步的關卡就是一個會忘的關卡。
2. **停用的 gate 不算在「未完成的關卡」裡**，否則涉及畫面的卡片會卡在一個
   永遠無法滿足的關卡上——那是死鎖不是嚴謹。
3. **要看得見。** Project Settings 顯示：
   「UI Mockup 關卡：**停用** —— 未啟用 tunnel 整合。[前往設定]」
   （`research/02/09` §6 的原文）。一個悄悄不存在的關卡比一個說明自己為什麼不存在的關卡糟。

### 1.4 模板

`templates` JSONB 承載 Task 建立表單與規格表單的欄位與提示文字
（來自 `ai/templates/task-card.md`、`feature-spec.md`）。
**它是表單的內容不是表單的結構**——結構在前端，內容在這裡，
因為 V2.4 的可覆寫版本要改的是內容。

## 2. `TK-04` — RBAC

三個動作，Viewer 一個都不拿（唯讀角色的既有定義）：

| 動作 | Viewer | Developer | Admin | 強制點 |
|---|---|---|---|---|
| `task.create` | ❌ | ✅ | ✅ | `POST` epics／user-stories／tasks／requirements |
| `task.update` | ❌ | ✅ | ✅ | `PATCH /api/tasks/{id}`、相依關係、規格版本 |
| `task.approve` | ❌ | ✅ | ✅ | `POST /api/tasks/{id}/gates/{gate}`、規格核准、提案接受 |

`task.approve` 與 `task.update` 的**持有者集合刻意相同**（D13 例外 3）：
拆開不是為了角色分離，是為了讓「Agent 憑證拿不到核准權」成為一個可以寫死在 scope 裡的東西。
這句話要同時出現在 `rbac.py` 的註解、ADR 0028 與 `docs/permission-matrix.md` 的對照表。

**`TK-04` 是一個 PR**（D6）：詞彙、seed、端點、`dto.ts` 的 `ACTION_*`、
`render_permission_matrix.py --write` 一次到位。

## 3. `TK-04` — Task API

十四條端點。全部掛在既有的 `require_projects_enabled` 之下（旗標關閉一律 404），
路由無條件掛載（`PJ-04` 的 D1，不重新論證）。

```text
GET    /api/projects/{id}/board                看板（依 stage 分組）      project.view
GET    /api/projects/{id}/roadmap              Epic → US → Task 進度      project.view
GET    /api/projects/{id}/process              生效中的流程定義           project.view
POST   /api/projects/{id}/epics                                          task.create
POST   /api/projects/{id}/user-stories                                   task.create
POST   /api/projects/{id}/tasks                                          task.create
GET    /api/projects/{id}/tasks?ref=TASK-12&stage=…                      project.view
GET    /api/tasks/{id}                                                   project.view
PATCH  /api/tasks/{id}                         帶 version                task.update
POST   /api/tasks/{id}/dependencies                                      task.update
DELETE /api/tasks/{id}/dependencies/{dep_id}                             task.update
POST   /api/tasks/{id}/gates/{gate}            勾選 Review Gate           task.approve
PATCH  /api/epics/{id}                                                   task.update
PATCH  /api/user-stories/{id}                                            task.update
```

（`TK-05` 另有五條，見 §5。）

### 3.1 看板端點的形狀（M1 已量，2026-08-09）

**裁決：一次回全部，每張卡只帶摘要欄位，不分頁。**
數字與推導在 `10-…md` §1；`artifacts/tk/local/m1.json` 是可重跑的證據。

摘要欄位：`id`、`card_ref`、標題、`stage`、`risk`、`priority`、owner、
`delivery`、`blocking_count`、`gates_approved_count`、`version`、`updated_at`。

**摘要不得含 AC 全文與 gates 明細，而這是一條有測試的硬規則**（不是建議）：
量測顯示 full 形狀在 200 張卡是 439 KB、500 張破 1 MB，而 summary 在 500 張只有 180 KB。
分頁能買到的東西，把這兩塊移出摘要就已經買到了——所以本期不做游標、不做捲動載入。

`has_more` **仍然在 DTO 裡，值恆為 `false`**：一個之後才加的欄位會讓每個既有客戶端
都要處理「沒有這個欄位」的情況。

### 3.2 路徑參數一律 UUID，`card_ref` 走查詢（差異 #9）

`GET /api/tasks/{id}` 只收 UUID。CLI 的 `cliora task get TASK-12` 因此是兩次往返：
先 `GET /api/projects/{pid}/tasks?ref=TASK-12` 再取詳情。

**被否決**：讓 `{id}` 同時吃 UUID 與 `card_ref`。兩者的樣式雖然不相交，
但「一個欄位兩種意義」是這個 repo 一貫拒絕的形狀，而且它會讓
「`TASK-12` 在哪個專案」變成一個路由層要回答的問題——
`card_ref` 只在專案內唯一，路由上沒有專案。

### 3.3 進站檢核（內化 DoR／DoD）

`PATCH /api/tasks/{id}` 改 `stage` 時：

| 目標車道 | 檢查 | 不通過時 |
|---|---|---|
| `ready`／`implementing`／`verify`／`done` | `dependsOn` 全部 `done` | **409 `TASK_DEPENDENCY_UNSATISFIED`，`details.blocking_refs = ["TASK-3","TASK-7"]`** |
| `ready` | readiness 七項齊備 | **200 ＋ `warnings`**（不阻擋，D7） |
| 任一 | WIP 超標 | **200 ＋ `warnings`**（不阻擋） |
| `done` | 本期**只**檢查 `dependsOn` | 驗證與交付那幾項在 V2.4 接到同一條路徑上 |

**`blocking_refs` 是 `card_ref` 不是 UUID**：錯誤訊息是給人看的，
而人看得懂 `TASK-3`。這一條有測試（判準 2）。

### 3.4 相依關係與循環偵測

`POST /api/tasks/{id}/dependencies` 在同一個交易裡：

```sql
WITH RECURSIVE reach(id) AS (
  SELECT :depends_on
  UNION
  SELECT d.depends_on_task_id FROM task_dependencies d JOIN reach r ON d.task_id = r.id
)
SELECT 1 FROM reach WHERE id = :task_id;
```

有列 → 409 `TASK_DEPENDENCY_CYCLE`，`details.path` 給出環的 `card_ref` 序列。
專案內卡數量級是百，一次走訪即可，**不需要排程引擎**（`research/02/03` TK-02）。

### 3.5 樂觀鎖

`PATCH` 必帶 `version`：

```sql
UPDATE tasks SET …, version = version + 1
WHERE id = :id AND version = :expected
```

0 列 → 409 `TASK_VERSION_CONFLICT`，回應**附上該卡的現值**，
讓前端可以直接重新渲染而不必再發一次 GET（拖曳失敗時要立刻彈回並顯示新狀態，
`07-…md` §2.2）。

### 3.6 Gate 核准

`POST /api/tasks/{id}/gates/{gate}`：

1. `task.approve`（動作層）。
2. **actor 必須是人類**——Agent principal 走不到這條路徑，因為它不掛
   `require_action`（`04-…md` §2）。若真的收到一個非人類 principal（例如未來新增第三種），
   回 403 `GATE_REQUIRES_HUMAN_ACTOR`。
3. gate 必須存在於生效中的流程定義，且**未被衍生停用**（§1.3）→ 否則 409 `GATE_DISABLED`。
4. 寫入 `gates[key] = {approved_by, approved_at}`，`version + 1`，
   audit `task.gate_approve` ＋ activity `task.gate_approved`。

**取消核准**：`DELETE` 同一條路徑，同樣需要 `task.approve` 並記 audit。
不做「只能核准不能取消」——一個按錯就永久生效的核准會讓人不敢按。

### 3.7 錯誤碼

新增九個，全部進 `error_catalog.py` 並重新產生 `docs/error-catalog.md`：

| 碼 | 狀態 | 意思 |
|---|---|---|
| `TASK_NOT_FOUND` | 404 | — |
| `TASK_VERSION_CONFLICT` | 409 | 這張卡剛被別人改過 |
| `TASK_DEPENDENCY_UNSATISFIED` | 409 | 帶 `blocking_refs` |
| `TASK_DEPENDENCY_CYCLE` | 409 | 帶 `path` |
| `TASK_STAGE_INVALID` | 422 | 不是六個值之一 |
| `GATE_UNKNOWN` | 404 | 流程定義裡沒有這個關卡 |
| `GATE_DISABLED` | 409 | 衍生停用（§1.3） |
| `GATE_REQUIRES_HUMAN_ACTOR` | 403 | — |
| `SPEC_HAS_OPEN_QUESTIONS` | 409 | 帶未解決的問題清單（§5） |

`PROJECT_ARCHIVED`（既有）沿用：封存的 Project 不得建立新卡片。

### 3.8 稽核與時間軸

每個寫入動作**兩邊都寫**（`PJ-04` 的既有形狀，D6 of `plan/16`）：

| 動作 | audit | activity |
|---|---|---|
| 建卡 | `task.create` | `task.created` |
| 改卡 | `task.update` | `task.updated` 或 `task.stage_changed` |
| 勾 gate | `task.gate_approve` | `task.gate_approved` |

Agent 寫入時 `audit_logs.user_id = NULL` ＋ metadata `{actor_kind, session_id, token_id}`，
`activity_events.actor_kind = 'agent'`（D4）。
**metadata 不含 token 值**——`FORBIDDEN_METADATA_KEYS` 已經套用在兩邊，
再加一條測試斷言 token 值不出現在任何一列。

## 4. 資源層級授權

沿用 `services/authz.py` 的既有兩層分工（動作層在 `deps.py`，資源層在 `authz.py`）：

| 資源 | 規則 |
|---|---|
| Task／Epic／US | 屬於一個可見的 Project 即可讀（`project.view` 的持有者看得到全部 Project，與 Node 一致） |
| 寫入 | 對應動作 ＋ **Project 不得為 `archived`** |
| Gate 核准 | `task.approve` ＋ actor 必須是人類 |
| Agent principal | **只能讀寫它自己那個 Project 的卡片**，且只有四條端點（`04-…md` §2.3） |

**新增一個 `authz.may_write_task(user, task)`**，不重用 `may_*_session` 的任何一個——
它們問的是不同的問題，而共用一個函式會讓「Session 的擁有者」與「卡片的擁有者」
在某次重構裡被當成同一件事。

## 5. `TK-05` — 需求與規格的人工流程

`research/02/03` TK-01b：`version2.md` §17 明寫「先建立可靠的資料結構與人工操作流程，
再讓 Agent 使用相同 API」。所以本期交付**表與人工表單**，V2.5 才讓 Agent 走同一條路。

```text
POST   /api/projects/{id}/requirements          Intake（一句模糊的話）  task.create
GET    /api/projects/{id}/requirements                                  project.view
GET    /api/requirements/{id}                   含所有規格版本          project.view
POST   /api/requirements/{id}/specs             新增一版規格            task.update
POST   /api/requirements/{id}/approve           核准                    task.approve
POST   /api/requirements/{id}/proposals          手動拆卡提案            task.create
POST   /api/proposals/{id}/accept               全部／部分接受          task.approve
```

三條硬規則，**本期就要成立**：

1. **`open_questions` 有未解決項時 `approve` 回 409 `SPEC_HAS_OPEN_QUESTIONS`**，
   `details.questions` 指名是哪幾個。V2.5 的 Agent 只是走同一條路——
   它現在就要是 API 層的拒絕，不是 UI 的停用按鈕。
2. **未核准的規格不能被拆解**（`POST /proposals` 回 409）。同上，API 層。
3. **接受提案時缺 DoR 的卡落 `backlog` 而非 `ready`**，並在回應裡說明是哪幾張、缺哪幾項。

每張由提案建立的卡帶 `requirement_id` 與 `proposal_id`，Task Detail 顯示
「來自需求 #12 的提案 #3」（`research/02/09` §4.5b 的來源可追溯）。

**M14 的訊號就是這幾條端點的使用次數**（`10-…md`）。若 V2.1–V2.4 期間沒人用，
那是 V2.5 值不值得做的免費早期訊號，不是一個要補救的問題。

## 6. 測試

| 層 | 覆蓋 |
|---|---|
| Central 單元 | 進站檢核四種結果；循環偵測（自環、兩點環、三點環）；樂觀鎖 409 附現值；gate 的四個拒絕理由 |
| Central DB | 併發 PATCH；併發建卡配號；archived Project 拒寫；`redact_actors` 不動 `actor_kind` |
| RBAC | `test_permission_matrix.py` 三條全綠；`UNENFORCED_ACTIONS` 仍為空 |
| 錯誤碼 | 九個新碼各一條；`render_error_catalog.py` 的輸出與 repo 內容一致 |
| 邊界 | Viewer 對七個寫入端點各拿一次 403，且 audit 有對應的 `authz.denied` |
