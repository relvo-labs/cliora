# V2.1 — 任務與 Session 整合（ticket 前綴 `TK-`）

> 本階段已依 **D2（功能內化）** 重寫。與上一版相比：
> **移除** ADR 0028／0029、`project.*` 與 `filesystem.replace` 四組 protocol 訊息、索引服務、投影表、卡片 JSON 解析、截斷語意。
> **新增** 內化的流程定義、Epic／User Story 實體、`.cliora/` 投影機制、**`cliora` CLI 首發**。
> 淨效果：daemon 與 contract **完全不動**，風險大幅下降；但 Agent 側從「零整合」變成「必須有工具」。
>
> **2026-08-09 修訂（不刪原文，加註記）：上一行「daemon 與 contract 完全不動」不成立。**
> 執行計畫（[`plan/17`](../../plan/17/README.md)）讀了程式碼之後發現 `.cliora/` 是 daemon
> 明文保留給平台的子樹、既有寫入 verb 對它一律拒絕，而且協定裡沒有 mkdir。所以 V2.1
> **會**動 contract（**v1.10.0**：一組 `context.project` 訊息）與 daemon（**`agentd` 0.8.0**：
> 一個新的寫入 verb ＋ `.cliora/` 清理迴圈）。連帶：V2.2–V2.4 的 contract／`agentd` 版本號
> 與 ADR 編號各順移一格（已回寫本目錄各處）。本階段的 ADR 是 **0028**。

## 目標

讓平台成為任務的所在地：Epic → User Story → Task 在平台上建立與推進，Session 有明確歸屬，Agent 拿得到情境也推得動卡片。

## 前置條件

- V2.0 出口條件全數通過。
- D3、D4、D7、D8、D11、D13、D14、D15 已裁決。
- ADR 0027 已涵蓋 D2／D1（V2.0 就寫了），並補上 `.cliora/` 投影的規則（`07` §4 的重生問題）。

## 工作包

### TK-01 — 內化流程定義

把 Monstrare 的流程從檔案變成平台的種子資料（`process_definitions`）：

| 來源 | 內化成 |
|---|---|
| `ai/process/kanban.md` 六車道 ＋ WIP 建議值 | 車道定義（顯示超標不阻擋） |
| `ai/process/definition-of-ready.md` 七項 | `readiness` 欄位定義與進站檢核 |
| `ai/process/review-gates.md` 六關卡 | `gates` 欄位定義與核准語意 |
| `ai/process/definition-of-done.md` | Done Gate 的拒絕條件（V2.1 只有 `dependsOn` 有資料可判，驗證那幾項在 V2.4 接上） |
| `ai/templates/task-card.md`、`feature-spec.md` | Task 與規格建立表單的欄位與提示文字（TK-01b） |
| `ai/process/context-protocol.md` | 情境包產生器的格式（TK-05） |

D15：V2.1 只有一筆全域種子，不可覆寫。`process.manage` 動作到 V2.4 才加。

**出處標註**：種子資料與 ADR 0027 要註明流程定義源自 Monstrare（MIT）。

### TK-01b — 需求與規格的資料模型（人工流程先行，D28 §4）

`version2.md` §17 明寫「先建立可靠的資料結構與人工操作流程，再讓 Agent 使用相同 API」。所以規格與拆解的**表與表單**在這裡就要有，Agent 驅動留到 V2.5。

- migration 併入 `0023`：`requirements`、`feature_specs`（版本列，只 INSERT）、`task_proposals`。欄位見 `07` RQ-02。
- 人工表單：提需求、寫規格（objective／scope／non-goals／AC／**open questions**）、手動拆卡。
- **`open_questions` 未解決時規格不得核准**——這個閘門在 V2.1 就要成立，V2.5 的 Agent 只是走同一條路。
- 每張卡可回溯來源需求（`activity_events` 記錄）。

若這個人工流程在 V2.1–V2.4 期間沒人用，那是 V2.5 值不值得做的**免費早期訊號**（`09` §5 的 M14）。

### TK-02 — 資料層

migration `0023`（`process_definitions`、`epics`、`user_stories`、`tasks`、`task_dependencies`、`task_sessions`、`terminal_sessions.task_id`）與 `0024`（`session_tokens`）。欄位見 `07` §2。

三個要點：

- `tasks.card_ref`（如 `TASK-123`）在專案內唯一，由平台配號。它是給人看的，不是主鍵。
- `tasks.version` 樂觀鎖：`PATCH` 帶 `version`，不符回 409。
- `task_dependencies` 建立時做循環偵測（專案內卡數量級是百，一次圖走訪即可，不需要排程引擎）。

### TK-03 — RBAC

新增 `task.create`、`task.update`、`task.approve`（`01` D13），seed migration，同 ticket 接上強制點。

`task.approve` 獨立於 `task.update` 是刻意的：核准與編輯是不同的權力，而且 Session token 的 scope **在發行時就寫死不含它**（`07` §6）。

### TK-04 — Task API

```text
GET    /api/projects/{id}/board                看板（依 stage 分組）        project.view
GET    /api/projects/{id}/roadmap              Epic → US → Task 進度        project.view
POST   /api/projects/{id}/epics                                            task.create
POST   /api/projects/{id}/user-stories                                     task.create
POST   /api/projects/{id}/tasks                                            task.create
GET    /api/tasks/{id}                                                     project.view
PATCH  /api/tasks/{id}          stage／readiness／指派／欄位（帶 version） task.update
POST   /api/tasks/{id}/gates/{gate}   勾選 Review Gate                     task.approve
POST   /api/tasks/{id}/dependencies                                        task.update
```

**進站與出站檢核**（內化 DoR／DoD）：

- 進 `ready` 之後的車道：`dependsOn` 全部 `done`，否則 409 並**指名是哪幾張卡**。
- 進 `ready`：readiness 七項齊備（V2.1 為警告，不阻擋——因為使用者剛開始用，全部強制會讓人放棄）。
- 進 `done`：V2.1 只檢查 `dependsOn`；驗證與交付那幾項在 V2.4 接到同一條路徑上（`06` DV-05）。
- 每次成功寫入產生 `activity_events`；`gates` 的核准另記 actor 與時間。

### TK-05 — `.cliora/` 投影與情境包（D7／D8）

Session 建立成功後，平台請 daemon 投影（**修訂：不是既有的 `filesystem.store`**，見下方註記）：

```text
.cliora/context/<session_id>.md      情境包，≤4 KB，內容格式見 01 D8
.cliora/context/<session_id>.token   Session token（D11）
.cliora/process/<version>/*.md       流程與檢核說明（同版本已存在則跳過）
.cliora/reference/*.md               Agent 要讀的參考（design-system 等，若專案有）
```

四條規則：

1. **寫入失敗不讓 Session 建立失敗。** 情境是加值，不是前提。失敗記 activity ＋ audit，UI 顯示「情境未送達，可手動重試」。
2. 流程檔以**內容版本號當目錄名**，收到 `FILE_EXISTS` 視為成功（`07` §4）。不得因此想加 `overwrite`。
3. `.cliora/` 是平台擁有的目的地，保留期 30 天由 daemon 清理（ADR 0024 W2）。
4. token 檔權限與情境包相同；Session 結束即失效，即使檔案還在。

> **2026-08-09 修訂：寫入機制改為新的 protocol 訊息 ＋ 新的 daemon 寫入 verb。**
> 既有的 `filesystem.store` 做不到這件事，兩個各自獨立的原因都在程式碼裡：
> ① `store_policy.go:83` 對使用者的寫入 verb 在 `.cliora/` 下一律回 `platform_owned`；
> ② `store.go` 步驟 6 要求目的地目錄事先存在，而協定裡沒有任何 mkdir。
> **不放寬既有 verb**——那會讓任何持有 `file.upload` 的使用者覆寫平台的情境包與 token 檔。
> daemon 的 `Verb` 型別註解本來就寫著「`.cliora/` 的規則是 per-verb 的」，這正是它預留的擴充點。
> 設計見 `plan/17/05-contract-and-daemon-projection.md`。

**「代打第一行指令」**：V2.1 只做 Project 設定欄位與 UI，**不接上實作**——留到 V2.4 與 Plan 面板一起做。注意這只影響**互動式 Session**；Agent Run 路徑不需要它（平台本來就是啟動者）。

### TK-06 — `cliora` CLI 首發（**本階段的關鍵路徑**）

D11：內化之後 Agent 沒有工具就完全無法記錄工作。V2.1 的最小集合：

```text
cliora context show          讀 .cliora/context/<id>.md（本機檔案，不需連線）
cliora task list             本 Project 的任務
cliora task get <ref>        單一任務詳情
cliora task update <ref> --stage implementing --note "…"
```

四個性質：

1. 憑證從 `.cliora/context/<session_id>.token` 讀，不是使用者的 JWT。
2. `context show` **不需要連線**（讀本機檔案），所以平台掛掉時 Agent 至少還知道自己在做什麼。
3. `task update` 需要連線；連不上時依 **D14 直接失敗，不進佇列**。訊息由 CLI 產生（不是把 HTTP 錯誤原樣吐出）：

   ```text
   無法連線到 Cliora（Session 可繼續工作）。
   你的變更未被記錄，恢復連線後請重新執行。
   ```

   **第二句是重點**：平台掛掉不影響 CLI Agent 本身工作，那是 V1 的既有性質。回傳非零 exit code 但**不應讓 Agent 判斷「我沒辦法繼續」**——情境包要明寫這一點。
4. 嘗試勾 gate 一律被 API 拒絕（scope 不含）。

~~發行方式：**V2.1 用投影**（`.cliora/bin/`），因為本階段不升級 daemon；**V2.2 起改為隨 `agentd` 附帶**。~~

**2026-08-09 修訂：V2.1 就隨 `agentd` 附帶，而且 `cliora` 就是 `agentd` 那支二進位**
（argv[0] 分派 ＋ 安裝時的 symlink）。投影一支二進位做不到：單檔上限 4 MiB
（`daemon/internal/config/config.go:205`）、`.cliora/` 對使用者寫入 verb 是禁區、
而 update 的解壓器**只取單一成員 `agentd`**（`update/files.go`，那是刻意最小化的解壓面）。
附帶好處：D11 要的「MCP 設定要指向一個穩定可執行路徑」在 V2.1 就成立，V2.4 不必再搬一次。

理由與 D11 的 stdio 裁決一致：MCP 設定要指向一個**穩定的可執行路徑**，隨 daemon 附帶才有固定路徑與跟著 daemon 走的版本。這個轉換要寫進 ADR 0028，否則 V2.4 做 MCP 時會發現路徑不固定。

### TK-07 — 前端：看板、藍圖、任務詳情

見 `08` §4。要點：

- 六車道，Monstrare 的 `stage` 值 ＋ 中文標籤（D3）。
- **卡片可拖曳**。互動契約：樂觀更新 → `PATCH`（帶 `version`）→ 失敗一律**彈回原位並重新載入該卡**，訊息要具體（`409 version 衝突` 是「這張卡剛被別人改過」、被 `dependsOn` 擋是「TASK-101 尚未完成」）。
- WIP 超標時車道計數變色，不阻擋。
- 藍圖分頁：Epic → User Story → Task，完成度 = `done` 卡數／總卡數；未指定 User Story 的卡落在「（未分類任務）」桶（D4，沿用 Monstrare 的語意）。
- Readiness 七項與 Gates 六項可勾選；**勾 gate 的 UI 要顯示核准者與時間**，因為那一格永遠是一個人。
- Task Detail 兩欄版面見 `08` §4.5。

### TK-08 — Task ↔ Session

- `POST /api/sessions` 接受 optional `task_id`（需同時有 `project_id`）。
- 從 Task Detail 的「開始工作」帶入 Project／Workspace／Runtime 預設值進入既有 Session 建立流程——**是預填，不是新流程**。Node／Runtime／Workspace 的選擇與驗證一步都不能省。
- Session 詳情顯示所屬 Task；Task 詳情顯示歷史 Session（含已結束的）。

## 這一階段明確不做

- ~~**不新增任何 protocol 訊息、不升級 `agentd`、不改 contract。**~~
  **2026-08-09 修訂**：改為「**只新增一組** protocol 訊息（`context.project`／`projected`）、
  `agentd` 升到 0.8.0、contract 升到 v1.10.0」。**既有訊息一個位元組不改**，
  既有 fixtures 逐檔 sha256 不變（`plan/17/08-…md` §4 的 `GATE-TK-CONTRACT-ADDITIVE`），
  daemon 的 terminal／tmux／tunnel／既有檔案路徑零 diff（同節的 `GATE-TK-TOUCH-LIST`）。
- **不做 Agent Runner 與任何自主執行**（V2.2）——本階段的 Agent 只在使用者開的互動式 Session 裡工作。
- 不做 Execution Plan 與 Verification（V2.4）。
- **不做離線佇列**（D14 已裁決：直接失敗）。
- 不做流程可設定性（D15，V2.4）。
- 不做 git、機密、Evidence、MCP。
- **不做 Agent 驅動的釐清與拆解**（V2.5）——V2.1 只有人工表單與資料模型。
- 不做 PRD patch 提案（V2.5）。
- 不把 Monstrare 的檔案複製進任何使用者專案。
- 不寫入 `.cliora/` 以外的任何工作區路徑。

## 出口條件

1. 在平台上建立 Epic → User Story → 3 張 Task，拖曳推進，Roadmap 完成度正確。
2. 從 Task Detail 開 Session → `.cliora/context/<session_id>.md` 與 `.token` 出現、情境包 ≤4 KB 且含驗收標準。
3. Agent 在 Session 中執行 `cliora task update TASK-123 --stage implementing` → 看板即時更新 → 時間軸出現一筆事件，actor 標示為「Session 的 agent」而非人類。
4. Agent 用其 token 嘗試 `POST /gates/architecture` → **被拒**（scope 不含 `task.approve`）。
5. 前置卡未完成的卡拖到 `implementing` → 被拒，訊息指名是哪幾張卡。
6. 兩個瀏覽器分頁同時拖同一張卡 → 後者 409、彈回、重新載入。
7. **Central 停機時**，Session 中的 CLI Agent 仍可正常工作；`cliora context show` 仍可讀；`cliora task update` 失敗且訊息符合 D14。
8. 同一個 workspace 開第二個 Session → 流程檔目錄已存在被跳過，不產生錯誤，情境包是新檔案。
9. **`git status --porcelain` 完全為空**（修訂：比原本寫的「只看到 `.cliora/`」更強——
   image drop 已經在 `.cliora/.gitignore` 寫入 `*`，整個子樹本來就被忽略），
   沒有任何其他檔案被平台建立或修改。
10. 旗標關閉時完整 V1 回歸全綠；**contract 的既有 fixtures 無任何變更**（新增檔案除外），
    且 `agentd` 0.8.0 在旗標關閉的部署上行為與 0.7.0 相同。

## 風險

| 風險 | 對策 |
|---|---|
| **Agent 不會用 CLI** | 情境包第一段就是「怎麼回報進度」的三行說明；`09` §5 的 M3 觀察前 10 個 Session 的實際使用率 |
| 平台掛掉導致工作無紀錄 | **這是 D14 接受的已知取捨，不做佇列。** 靠的是訊息要說出「Session 可繼續工作」＋ `context show` 免連線；出口條件 7 驗證 Session 本身不受影響。M9 是重新評估的觸發條件 |
| `.cliora/` 污染使用者 repo | 單一目錄、可 gitignore、有保留期；出口條件 9 用 `git status` 驗證 |
| 流程檔因 `O_EXCL` 寫不進去被誤判為錯誤 | 版本號目錄 ＋ `FILE_EXISTS` 視為成功；出口條件 8 |
| DoR 七項全部強制會讓人放棄使用 | V2.1 只警告不阻擋；`dependsOn` 是唯一硬阻擋 |
| 內化的流程與 Monstrare 日後分歧 | 種子資料標註來源版本；分歧是允許的，但要在 ADR 記錄，不要假裝同步 |
