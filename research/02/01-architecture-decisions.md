# 01 — 開工前必須定案的決策

> **2026-08-08 的兩次裁決已寫入本文件**：
> 1. 任務卡要能拖曳（原 D6）。
> 2. **Monstrare 以「功能內化」方式導入，不複製檔案進使用者專案**（D2）。
>
> 第二次裁決讓 D1 翻面，並連帶取消了 D5、D6 的整套設計。這不是壞事——它移除的複雜度比它帶來的多。代價轉移到別的地方，D11 與新增的 D14 記錄那些代價。

每一條的格式：**問題 → 選項 → 決定 → 理由 → 影響到誰 → 事後翻案的代價**。

---

## ⚠️ D2 — Monstrare 怎麼進到系統（**先讀這條，其餘決策都由它推導**）

**問題**：一個 workspace 要成為「Cliora 管得動的專案」，需要先有 `ai/`、`tools/kanban/`、`.claude/skills/` 這一整套檔案嗎？

**已裁決：不需要。把 Monstrare 的能力內化成平台功能，不把它的檔案複製進使用者專案。**

### 決定性的事實：Monstrare 的東西不是同一種材料

能不能內化，取決於**誰在讀它**。這條分界不是偏好，是 Claude Code 與 Codex 的載入機制決定的：

| Monstrare 資產 | 誰讀 | 能內化嗎 | 內化後的形式 |
|---|---|---|---|
| `ai/process/kanban.md` 六車道與欄位規則 | 人／平台 | ✅ | 平台的看板欄位與狀態機 |
| `ai/process/definition-of-ready.md` 七項 | 人／平台 | ✅ | Task 上的 readiness 欄位 ＋ 進站檢核 |
| `ai/process/definition-of-done.md` | 人／平台 | ✅ | Done Gate 的**實際拒絕邏輯** |
| `ai/process/review-gates.md` 六個關卡 | 人／平台 | ✅ | Task 上的 gates ＋ 必帶人類 actor 的核准 |
| `ai/process/workflow.md` 九階段 | 人／平台 | ✅ | 平台的階段定義與 Activity 事件類型 |
| `ai/templates/*.md` | 人／Agent | ✅ | 平台的表單 schema ＋ 產出物產生器 |
| `tools/kanban/`（server + cards） | 人 | ✅ **整個取代** | 平台的 Board 與 Roadmap 畫面 |
| `epics.json` 的 Epic／User Story | 人／平台 | ✅ | 平台實體（有 CRUD 了，見 D4） |
| `ai/context/project-map.md` 等 | Agent | ⚠️ 半 | 平台存內容，**執行時要投影成檔案** |
| **`.claude/skills/*/SKILL.md`** | **Agent（CLI 從磁碟載入）** | ❌ | 只能投影成檔案，見下 |
| **`.claude/agents/*.md`** | **Agent（CLI 從磁碟載入）** | ❌ | 同上 |
| **`AGENTS.md` / `CLAUDE.md`** | **Agent（CLI 從磁碟載入）** | ❌ | 同上 |

**最後三列是硬邊界。** `claude` 與 `codex` 讀的是工作目錄裡的檔案；一個只存在 PostgreSQL 裡的 skill，CLI 永遠看不到。平台無法用 API 讓 Agent「知道」一條規則。

### 橋接方式：平台擁有定義，Session 啟動時投影成檔案

```text
平台 DB（單一事實來源）
  流程定義 / 模板 / 任務 / 計畫 / 驗證 / 專案情境
        │
        │  Session 建立時，平台產生並寫入（既有 filesystem.store）
        ▼
  <workspace>/.cliora/            ← 平台擁有的目錄，有保留期，可整個刪掉重生
    context/<session_id>.md       ← 本次任務的情境包（D7／D8）
    process/<version>/*.md        ← 這個專案適用的流程與檢核規則
    reference/*.md                ← design-system、project-map 等 Agent 要讀的參考
```

使用者的 repo **不需要** `ai/`、不需要 `tools/kanban/`、不需要 `.claude/skills/`。`.cliora/` 是產生物，可以 gitignore，刪掉下次開 Session 會重生。

### 一個真正的取捨：投影出來的 skill 不會被自動載入

`.claude/skills/` 底下的檔案會被 Claude Code 自動掛載；`.cliora/process/` 底下的不會。差別是「Agent 自動知道」與「Agent 被情境包告知去讀」。

三個選項：

| | A：只放 `.cliora/`，情境包指路 | B：平台寫進 `.claude/skills/` | C：寫到 node 的 `~/.claude/` |
|---|---|---|---|
| 自動載入 | ❌ 靠情境包一句話 | ✅ | ✅ |
| 污染使用者 repo | 否（單一目錄，可 gitignore） | **是**（且與既有檔案衝突時要覆寫） | 否 |
| 踩到寫入姿態 | 否 | **是**（覆寫既有 `CLAUDE.md`） | **是**（寫到 allowed root 之外） |
| 專案間隔離 | ✅ | ✅ | ❌ node 層全域 |

**決定 A。** 理由不只是安全：**當平台能真的拒絕時，需要靠 prompt 說服 Agent 的部分就變少了。** Monstrare 必須把規則寫成 skill，因為它只有檔案、沒有執行引擎——它唯一能做的就是說服。Cliora 有 API，Done Gate 可以直接回 409。規則從「請 Agent 遵守」變成「不遵守就寫不進去」，skill 的角色也就從**強制**降級為**說明**。說明放在情境包指路的檔案裡，夠用。

想要自動載入的團隊，仍可自己把 `.cliora/process/` 複製一份到 `.claude/skills/`。那是他們的 repo、他們的決定，平台不代勞。

### 保留 Monstrare 的出處

流程定義的措辭與結構源自 Monstrare（MIT）。內化時在 ADR 0027 與平台的流程定義種子資料中標註出處，不假裝是原創。

**翻案代價**：極高。這條決定了 D1、D4、D5、D6、D9、D11 的答案。V2.1 之後翻回「複製檔案」，等於把整個任務層從 DB 搬回檔案。**現在決定，而它已經決定了。**

---

## ⚠️ D1 — 任務資料的真實來源

**已裁決（隨 D2）：平台 DB。**

原本的建議是「repo 檔案為 writer of record，DB 投影」。D2 內化之後那個前提消失了——使用者的 repo 裡不再有卡片檔案，也就沒有東西可以當 writer of record。

| | 原方案 B：repo 為主 | **現行：DB 為主** |
|---|---|---|
| Agent 怎麼更新 | 原生檔案工具寫檔 | **必須呼叫 CLI／MCP**（代價轉移到 D11） |
| 版本與歷史 | git 免費提供 | 平台自建（`activity_events` ＋ 版本列） |
| 併發衝突 | git merge | DB 樂觀鎖，**比 git 簡單** |
| 平台要不要覆寫工作區檔案 | 要（`filesystem.replace`） | **完全不用**（D6 取消） |
| 沒有平台時還能用嗎 | ✅ | ❌ **（D14 處理）** |
| 跨專案查詢 | 要先索引 | 直接查 |

**這次翻面移除的東西**（不是延後，是消失）：

- ADR 0028（免 Session 唯讀讀取面）與 `project.*` 三組訊息 —— 不需要了，任務不在檔案裡。
- ADR 0029、`filesystem.replace`、`expected_sha256`、路徑樣式白名單 —— 不需要了，拖曳是一次 `UPDATE`。
- 索引服務、`project_index_runs`、`source_sha256`、「資料截至」語意、卡片 JSON 解析失敗處理、截斷提示 —— 全部消失。
- **紅線 3（ADR 0024／0026 的寫入姿態）完全不被觸碰。** 上一版為了拖曳開的那道窄縫，現在不需要開了。

**它新增的東西**（代價轉移，不是消失）：

- Agent 必須透過工具才能記錄工作 → D11 從後期的便利品變成 **V2.1 的前提**。
- 離線與平台不可用時無法記錄 → D14。
- 任務資料的歷史要自己做 → 版本列 ＋ `activity_events`（本來就要做）。

---

## D3 — 看板欄位用誰的詞彙

**不變。** wire 值採 Monstrare 的六個 `stage`（`backlog`/`blocked`/`ready`/`implementing`/`verify`/`done`），UI 顯示 `version2.md` §7.3 的標籤（`implementing` → 「進行中」）。

兩者本來就是同一組六個狀態，只差命名。內化之後這組值成為平台的**種子流程定義**，不是從檔案讀來的。

`ai/process/kanban.md` 的完整 12 關卡是政策，六欄是簡化實作。平台跟隨六欄，12 關卡的細節由 Task 上的 readiness／gates 呈現。WIP 上限**顯示超標，不阻擋**（沿用 Monstrare 的既有語意）。

---

## D4 — Epic / User Story

**升級為平台實體（原本只是索引維度）。**

D2 之前，Epic 來自 `epics.json`，平台只能 group by。內化之後它們是 DB 裡的表，所以：

- 有真正的 CRUD 與排序。
- Task 用外鍵指向 User Story（不再是字串比對）。
- 「指定 Epic 但沒指定 User Story」的未分類桶仍要保留——這是 Monstrare 明確定義過的語意，卡片不該憑空消失。
- Roadmap 的完成度是 join，不是掃描。

---

## ~~D5 — 沒有 Session 的時候怎麼讀專案檔案~~ 【已取消】

D2 內化之後**不再需要**。任務資料在 DB，平台不必為了讀看板而掃描 repo。

Workspace 檔案存取維持 V1 現狀**完全不變**：session-scoped、`authz.may_browse_files`、既有路徑安全鏈，一行都不動。

> 這條的取消是 D2 最大的單筆收益：它原本要替換一個授權輸入、要寫 ADR 0028、要新增三組 protocol 訊息、要做有界索引與截斷語意，而且是整份規劃裡風險最高的一項。

**唯一殘留的需求**：V2.4 的證據採集仍要在 run 的隔離目錄內執行 git 查詢（D10），那是另一條路徑，與本條無關。

---

## ~~D6 — 平台可不可以改任務卡~~ 【已取消】

D2 內化之後**不再是問題**。拖曳一張卡是對 `tasks` 表的一次 `UPDATE`，不碰任何檔案。

- 不需要 `filesystem.replace`、不需要 `expected_sha256`、不需要路徑樣式白名單。
- 不需要修訂 ADR 0024 的措辭。
- `plan/14` 那張「不覆寫、不刪除，機制就整批消失了」的表**一行都不用拿回來**。
- 併發衝突改用 DB 樂觀鎖（`tasks.version` 整數，不符回 409）。整數版本號在這裡可行，正是因為平台是唯一寫入者——這也是原方案不能用整數而要用 `expected_sha256` 的理由，現在那個理由消失了。

---

## ⚠️ D7 — Task 情境怎麼交到 Agent 手上

**不變**：檔案為預設，「代打第一行指令」為 opt-in 且預設關，env 注入否決（紅線 1，SEC-002）。

D2 之後唯一的變化是**情境包的內容從 DB 產生**，不是從 repo 檔案彙整。寫入機制仍是既有的 `filesystem.store` 寫到 `.cliora/context/<session_id>.md`——檔名帶 session id，`O_EXCL` 天然不撞名。

代打的完整語意（未變）：

- 只在 Session 剛建立、建立者本人是 writer、CLI 已就緒時送出**一次**；不重試、不排隊。
- 需要 `terminal.operate` ＋ writer 身分。
- audit 寫成 `actor = 建立者、on_behalf = platform`——既有 `session_connections` 只記 writer 是誰，這是新的稽核語意。
- 送出前 UI 明示內容，送出後 Terminal 上方顯示「平台已代為輸入」橫幅。
- 排在 V2.4（與 Plan 面板一起），因為那一行送進去之後要看得到 Agent 做了什麼。**Agent Run 路徑不需要它**——平台本來就是那次執行的啟動者，情境直接進工作目錄。

`.cliora/` 是**平台擁有的目的地**，依 ADR 0024 的 W2 要有保留期：預設 30 天，由 daemon 清理，Project 設定可見。

---

## D8 — 情境包的內容與大小預算

**不變。** 採 Monstrare `ai/process/context-protocol.md` 的情境包格式與 Always／On-demand 二分。

Always Included（平台從 DB 產生，目標 **≤ 4 KB**）：

```text
任務：TASK-123 標題
目標／範圍／非目標
驗收標準（逐項，含目前結果）
允許變更的檔案 / 不得觸碰
驗證指令
風險等級
相依任務與其狀態
```

On-demand：**只給路徑，讓 Agent 自己用原生工具讀**。內化之後這些路徑指向 `.cliora/reference/`（平台投影的 design-system、project-map）與使用者 repo 內的真實檔案。

理由不變：平台把大文件塞進情境是最容易做錯的一件事——Agent 有 `Read` 與 `rg`，給路徑比給內容更省也更準。

---

## D9 — Agent 的執行計畫用什麼形狀儲存

**改為 DB 表，但保留 append-only 語意。**

原方案是 `plans/<id>/001.json` 編號快照，那是為了繞開「不能覆寫」而設計的。D6 取消後不需要繞了，但**append-only 這個性質要留著**，理由與檔案無關：

- `version2.md` §7.5 要的「發現 Agent 是否偏離 Task」需要歷史，不是現值。
- 中斷後恢復要知道上一次做到哪。
- 改計畫要留下理由（`note`），那是一筆一筆的事件，不是一個可覆寫的欄位。

所以 `execution_plans` 是 `(task_id, seq)` 的版本列，只 INSERT 不 UPDATE，畫面顯示 `seq` 最大的那一列。上限與清理策略先量測再定（`09` §5 M4）。

---

## ⚠️ D10 — 證據可信度分級（**內化之後更重要**）

**不變的部分**：三級 `source`（`agent_reported` / `platform_observed` / `machine_verified`），Agent 自填高級別一律降級並記錄；「平台代跑驗證命令」**否決**。

**變重要的部分**：DB 成為單一事實來源之後，「誰寫的」是唯一的完整性錨點。原方案至少還有 git 可以事後對照 —— 現在沒有了。所以：

- 每一列 `verification_reports`、`evidence_items`、`execution_plans` 都要記錄**寫入者身分**（人類 user_id、或哪一枚 Session token）。
- Agent 憑證寫入的資料，`source` 由**伺服器端**決定為 `agent_reported`，不看 payload 裡寫什麼。
- Review Gate 的勾選必帶人類 actor；Agent token 嘗試勾選一律拒絕。這是 `review-gates.md` 的「agent 輸出不是核准」在平台上的具體形式。

能拿到的證據仍是三種，誠實排序不變：

| 來源 | 拿得到什麼 | 可信度 |
|---|---|---|
| Agent 自述（經 CLI 寫入） | 命令、輸出摘要、AC 結果、殘留風險 | 中 |
| 平台自身動作 | Session 起訖、writer 接手、檔案寫入、狀態轉換 | 高 |
| run 內的 git 查詢與驗證命令（V2.4） | branch、commit、變更檔案、diff 摘要、**真實 exit code** | 高 |

**「平台代跑驗證命令」的否決理由**（要寫進 ADR）：那需要一條通用的「在 node 上執行一條命令」路徑。即使命令來自白名單，白名單本身是使用者可寫的，等於間接取得任意執行——SEC-002 的整個設計就是為了讓這件事不可能。要自動跑測試該用 CI。

---

## ⚠️ D11 — Agent Tool Interface（**從 V2.3 提前到 V2.1，且變成前提**）

**這是 D2／D1 翻面的主要代價。**

原方案裡 Agent 用原生檔案工具就能記錄工作，CLI 只是方便。現在**任務資料在 DB，Agent 沒有工具就完全無法記錄任何東西**——它甚至不知道自己在做哪張卡（除了情境包那份唯讀快照）。

**決定：CLI 優先，MCP 為同源第二外殼。CLI 的最小集合必須在 V2.1 交付。**

CLI 為什麼優先：Claude Code 與 Codex 都會跑 shell，不需要各自的設定；MCP 在 Codex 側設定成本較高。

交付順序：

| 階段 | CLI 子命令 | 為什麼是這個階段 |
|---|---|---|
| **V2.1（必要）** | `cliora task list/get/update`、`cliora context show` | 沒有它，Agent 無法把卡片推進，看板只能靠人拖 |
| V2.2 | `cliora task say`／`ask`／`messages` | 看板作為溝通管道（D24）；沒有它 Agent 無法提問 |
| V2.4 | `cliora plan snapshot`／`verify submit`／`evidence add`、MCP 外殼 | 計畫與驗證上線 |

**憑證**：每個 Session 一枚、只含該 Project 範圍、可撤銷、Session 結束即失效的 token，隨情境包投影到 `.cliora/context/<session_id>.token`（同樣受保留期管轄）。**不是使用者的 JWT。**

**權限硬邊界**（`version2.md` §8，API 側強制，不靠 CLI 自律）：不能刪 Project、不能改權限與 Node 設定、不能繞過 workspace 限制、不能碰 DB、**不能勾 Review Gate**。

---

## D12 — 向下相容的機制

**不變。**

- 單一 feature flag `CLIORA_PROJECTS_ENABLED`（預設 `false` 直到 V2.1 出口通過）。
- `terminal_sessions.project_id` / `task_id` **nullable，且永遠 nullable**——Ad-hoc Session 是產品的一部分（`version2.md` §15）。
- 新增欄位不改任何既有欄位的可空性、型別或預設值；舊 API 回應不新增必填欄位。
- 每階段驗收包含「旗標關閉，跑完整 V1 回歸」（`09` §3）。

**D2 讓這條變容易了**：V2 現在幾乎不碰既有的 protocol 與檔案面，回歸風險集中在前端導覽與 Session 建立表單。

> 實作細節：`version2.md` §10 寫的 `sessions` 表在本 repo 實際叫 **`terminal_sessions`**。

---

## D13 — 新的 RBAC 動作與角色歸屬

D2 之後調整（`task.*` 不再是檔案寫入，歸類理由跟著變）：

| 動作 | 意思 | Viewer | Developer | Admin |
|---|---|---|---|---|
| `project.view` | 看 Project、看板、任務詳情 | ✅ | ✅ | ✅ |
| `project.manage` | 建立／改名／封存 Project、綁定與解除 Workspace | ❌ | ❌ | ✅ |
| `task.create` | 建立 Epic／User Story／Task | ❌ | ✅ | ✅ |
| `task.update` | 改 stage、readiness、指派 | ❌ | ✅ | ✅ |
| `task.approve` | **勾選 Review Gate** | ❌ | ✅ | ✅ |
| `process.manage` | 改專案適用的流程定義（車道、gates、模板） | ❌ | ❌ | ✅ |

四點理由：

- `project.manage` 與 `process.manage` 歸 Admin，與 `node.manage`／`enrollment.manage` 同層：那是組織層決定。
- `task.approve` **獨立於 `task.update`**，因為核准與編輯是不同的權力。Agent token 永遠拿不到這一個，這是 D10 完整性錨點的一部分。
- `task.*` 不再需要與 `file.upload` 同層論證（它們不再寫檔案）。Viewer 仍然不持有任何 `task.*`，理由回到最基本的：Viewer 是唯讀角色。
- 沒有把它們併進既有動作：稽核上「改了任務狀態」與「上傳了檔案」必須可區分。

**實作約束**：每個新動作在**同一張 ticket** 內接上強制點（`backend/tests/db/test_permission_matrix.py` 的 `test_every_action_is_enforced_somewhere` 兩個方向都會失敗），`UNENFORCED_ACTIONS` 目前是空集合，不要為了先 merge 而往裡面加東西。同步更新 `frontend/src/api/dto.ts` 的 `ACTION_*` 與 `docs/permission-matrix.md`。

---

## 🆕 D14 — 平台不可用時，Agent 怎麼辦

**問題**：D1 翻面新產生的問題——任務資料在 DB，Agent 沒有連線就記錄不了任何東西。原方案（repo 為真實來源）沒有這個問題，因為檔案在本機。

**適用範圍很窄**：只影響**使用者自己開的互動式 Session 裡的 Agent**。Agent Run 是平台派出去的，**平台不在就不會有 run**，所以完全不受這條影響。

**已裁決（2026-08-08）：直接失敗，不做離線佇列。**

| | **A：直接失敗（已裁決）** | B：本機佇列補送 | C：本機檔案 fallback |
|---|---|---|---|
| Agent 體感 | 工具回報錯誤 | 無感 | 無感 |
| 資料一致性 | **完好** | 補送順序與衝突要處理 | **兩個真實來源** |
| 實作成本 | **無** | 中（`.cliora/queue/` ＋ 補送 ＋ 衝突清單） | 高 |
| 新增的失敗模式 | **無** | 補送本身會失敗、會亂序、會撞版本 | 匯入衝突 |

### 為什麼是 A 而不是 B

B 不是「多做一點就好」，它會引入**一整類新的失敗模式**：補送順序、補送時目標卡已被改（版本衝突）、佇列本身寫壞、佇列在 run 目錄被清掉時消失。這些都要設計、要測、要在 UI 上呈現——**為了一個本來就該很罕見的情況**。

Central 長時間不可用是一個運維問題，該用運維手段解（監控、HA、部署視窗），不該在每個 Agent 的工具鏈裡放一套最終一致性機制去繞過它。

C 早已否決：一旦本機檔案能被匯入為權威資料，就有兩個真實來源與衝突語意，等於把 D1／D2 的內化裁決白做一次。

### A 的關鍵不是「失敗」，是那句訊息

```text
無法連線到 Cliora（Session 可繼續工作）。
你的變更未被記錄，恢復連線後請重新執行。
```

**第二句是整條決策的重點**：平台掛掉**不影響 CLI Agent 本身的工作**——那是 V1 的既有性質，不能因為 V2 而改變。Agent 照樣讀檔、改檔、跑測試，只是這次的進度沒被記到看板上。

沒有這句話，Agent 很可能會判斷「我沒辦法繼續」而停下來——**那才是真正的損失**，比沒記錄到看板嚴重得多。所以：

1. 訊息由 CLI 產生，不是把 HTTP 錯誤原樣吐出來。
2. **`cliora context show` 讀本機檔案，不需要連線**——即使平台掛了，Agent 仍然知道自己在做什麼。
3. CLI 的離線失敗**回傳非零 exit code 但不中斷 Agent 的工作流程**；情境包裡要明寫這一點。

### 重新評估的觸發條件

`10` §5 的 **M9**（平台不可用的實際頻率與時長）。若真實數據顯示不可用頻繁到讓使用者困擾，再回頭評估 B——**但那時要先問「為什麼平台這麼常掛」，而不是直接做佇列**。

這個觸發條件要寫進 ADR，否則日後有人提 B 時會變成沒有依據的爭論。

---

## 🆕 D15 — 流程定義可不可以被專案改

**問題**：內化之後，六車道、七項 readiness、六個 gates 是平台寫死的，還是每個專案可調？

**選項**：
- A：全域寫死（Monstrare 的定義即平台的定義）。
- B：平台內建為**種子**，Project 可覆寫（改車道名稱、增減 gates、關掉某些 readiness 項）。
- C：完整的流程編輯器。

**建議：V2.1 用 A，V2.4 視需求做 B 的最小版本（只允許啟用／停用既有項目，不允許新增自訂項目）。C 明確不做**——`00` §9 已經把「視覺化 Workflow Designer」列為不做。

理由：A 的好處是跨專案可比較（`version2.md` §16 的品質指標要跨專案聚合，欄位不同就無法比）。真正的需求出現前不要先做可設定性——可設定性是最容易在沒有使用者的情況下被過度設計的東西。

---

---

# 第三次裁決衍生的決策（Agent Runner 模型）

> 2026-08-08 裁決：平台作為使用者與 Agent 的橋樑；Agent 像 GitHub Runner 一樣自行認領任務卡、在隔離目錄拉 git、依卡片交付模式產出結果；Project × Agent 多對多；原有 Session 保留給使用者。
>
> 以下 D16–D27 是這個裁決推導出來的設計問題。**D19、D20、D22、D23、D25、D27 標 ⚠️**，它們改變安全姿態或新增儲存面。

---

## D16 — Agent 是什麼實體

**問題**：Runner 是新的 binary、新的註冊流程，還是既有 `agentd` 的一個模式？

**建議：`agentd` 的一個模式（`agentd serve --runner`），不是新 binary、不是新的信任建立。**

理由：Node 的 enrollment token、Ed25519 credential、outbound WSS、heartbeat、doctor、release／update 全部可以直接重用。做第二套等於把 `plan/02` 的整個信任鏈重寫一次，而那條鏈是目前系統裡最不該重做的東西。

**資料模型**：`agent_runners` 綁在 `node_id` 上。一個 node 可以有多個 runner（不同 runtime、不同並行度），但都共用該 node 的一條 WSS 連線與一份憑證。

**一個推論**：runner 的線上狀態就是 node 的線上狀態，不必新做一套 heartbeat。

---

## ⚠️ D17 — 認領模型：拉取還是推送

**問題**：任務怎麼到 Agent 手上？

| | A：**拉取**（Agent 主動要工作） | B：推送（平台指派） |
|---|---|---|
| 誰決定誰做 | Agent 依自己的容量與資格 | 平台的排程器 |
| 平台要不要寫排程邏輯 | **不用** | 要（而且會一路長成負載平衡與優先權引擎） |
| 背壓 | 天然：runner 忙就不領 | 要自己做 |
| 與紅線 4 的關係 | 「認領」在範圍內 | 「自動指派」仍不在範圍 |
| GitHub Actions | 就是這個 | — |

**建議：A。** 這也是裁決的字面要求（「agent 有能力自行認領任務卡」）。

**協定形狀**（走既有 WSS 控制通道，D16 之後不需要新連線）：

```text
runner.register    { runner_id, runtime, labels, max_concurrent }
runner.poll        { runner_id, capacity }          ← runner 說「我還能吃 N 個」
run.offer          { run_id, task_id, project_id, spec }
run.accept | run.decline
run.lease_renew    { run_id }                       ← 每 30s
run.progress       { run_id, phase, message }
run.log_chunk      { run_id, seq, data }            ← 有界、已去識別
run.complete       { run_id, result, delivery, evidence }
run.failed         { run_id, error_code, message }
```

**原子性**：`UPDATE task_runs SET runner_id=?, claimed_at=now() WHERE id=? AND runner_id IS NULL`。平台是唯一的 offer 來源，所以競爭窗口很小，但這條 WHERE 仍然要在——它是「雙重領取」不可能發生的唯一保證。

**租約**：`lease_expires_at`，runner 每 30 秒續租；逾時（建議 3 分鐘）平台把 run 標為 `lost` 並把任務重排。重排有 `attempt` 上限（建議 3），用完進 `blocked` 並在卡片上說明原因。

**資格判定**（五個條件全滿足才會被 offer）：

1. 任務在 `ready`
2. `dependsOn` 全滿足
3. **runner 綁了這個 Project**（授權，D18）
4. runner 的 runtime 與 labels 符合卡片要求（能力，D18）
5. 卡片的 `assigned_runner_id` 為 null，**或**正好是這個 runner（指定，D17b）

第 5 條讓「指定」在拉取模型裡不需要任何新機制——它只是 poll 查詢的一個 `WHERE` 條件：

```sql
WHERE (assigned_runner_id IS NULL OR assigned_runner_id = :runner_id)
```

平台仍然不推送、不排程、不決定誰做什麼。**指定是卡片的意圖，不是平台的調度。**

---

## 🆕 D17b — 指定 Agent 的語意

**已裁決：任務卡可以指定 agent，也可以不指定。**

不指定（`assigned_runner_id = null`，**預設**）：任一符合資格的 runner 都能領。

指定：只有那一個 runner 能領。三個必須先定清楚的邊界：

### 1. 指定**不能繞過綁定授權**（安全相關）

指定一個沒綁這個 Project 的 runner，**不會讓它取得該專案的任務或機密**。第 3 條資格判定永遠先成立。

否則「指定」就變成一條授權旁路：任何持有 `run.dispatch` 的 Developer 都能把任務指給任意 runner，等於繞過 Admin 才有的 `agent.manage` 綁定。**這一條要有測試。**

### 2. 資格衝突要在 **dispatch 當下**就拒絕，不是排隊到天荒地老

指定的 runner 不符合資格時（沒綁 Project、runtime 不符、labels 缺、已停用），`POST /dispatch` 直接回 409 並**指名是哪一個條件不滿足**。

這與「指定的 runner 只是暫時離線或忙碌」不同——那是合法的等待，卡片顯示「等待指定的 Agent：dev-vm-01（目前離線）」。**兩種情況的訊息必須不一樣**，否則使用者分不出「我設定錯了」跟「再等一下就好」。

### 3. 指定就是指定，**預設不做逾時退回任一 agent**

| | A：嚴格（**建議**） | B：逾時後開放給任一 agent |
|---|---|---|
| 指定的意義 | 確定 | 建議 |
| 卡在離線 agent 上 | 一直等，但**看得見原因** | 自動被別人領走 |
| 風險 | 需要人來看一眼 | **在錯的機器上執行** |

**建議 A。** 會指定 agent 的理由，通常正是「只有那台機器有需要的東西」——特定的環境、特定的網路位置、特定的資料。悄悄退回任一 agent 等於在錯的地方執行，那比多等一會兒糟得多。

真的需要退回時，做成**卡片上明確的 opt-in 欄位**（`fallback_after_minutes`），不做成全域預設。V2.2 不實作，等有真實需求再說。

### 重排時維持指定

被指定的 run 逾時變成 `lost` 之後，重排**仍然只給原本指定的 runner**。attempt 用完進 `blocked`，原因寫明「指定的 Agent 連續 3 次未能完成」。

---

## D18 — Project × Agent 多對多怎麼綁

**建議：明確綁定表 ＋ labels 過濾，兩層。**

- `project_agents(project_id, runner_id, enabled)`：**授權**層。沒綁就永遠拿不到這個專案的任務，也拿不到它的機密。
- `tasks.required_labels` vs `agent_runners.labels`：**能力**層。例如卡片要 `docker`、`node20`，runner 沒有就不會被 offer。

為什麼不只用 labels：labels 是能力宣告，不是授權。一個 runner 宣稱自己有 `backend` 標籤，不該因此就能拿到別的專案的機密。授權必須是顯式的一列資料。

**三層要分清楚**，它們回答三個不同的問題：

| 層 | 問題 | 誰設定 |
|---|---|---|
| `project_agents` 綁定 | 這個 runner **可不可以**碰這個專案 | Admin（`agent.manage`） |
| `labels` × `required_labels` | 這個 runner **做不做得了**這張卡 | runner 自報能力、卡片宣告需求 |
| `assigned_runner_id` | 這張卡**想不想**給特定的它做（D17b） | 建卡或 dispatch 的人 |

第三層永遠不能覆蓋第一層。

---

## ⚠️ D19 — 隔離工作目錄

**問題**：Agent 在哪裡工作？

**建議：daemon 擁有的 per-run 目錄，`<agentd_state_dir>/runs/<run_id>/`，不在任何 allowed root 內。**

```text
<state>/runs/<run_id>/
  repo/               git clone + checkout（若卡片需要程式碼）
  .cliora/
    context.md        情境包
    process/          內化流程的投影
    reference/        design-system 等
    token             Session token（D11）
  artifacts/          run 產生的檔案（測試報告等），有大小上限
```

六條規則：

1. **不在 allowed root 內**，也不得被既有的檔案瀏覽 API 觸及。使用者要看 Agent 做了什麼，看的是 run log 與 PR diff，不是這個目錄。
2. **每次執行新建，結束後依保留期清理**（建議成功 3 天、失敗 14 天——失敗的要留久一點，因為那才是需要人來看的）。
3. **配額**：單一 run 目錄大小上限、node 上所有 run 的總量上限。超過就拒絕領新工作，並回報給平台顯示。
4. **repo 快取**：同一個 repository 在同一個 node 上共用一份 bare mirror，run 目錄用 `git worktree` 或淺 clone 掛出來。否則每次執行都完整 clone 一個大 repo 是不可接受的。
5. **誰清這個**：daemon 的既有清理迴圈（`shell_reaper` 已有同類型的東西可以參考）。這是 ADR 0024 W2 那個問題的答案，要寫進 ADR。
6. **不可瀏覽的例外**：`artifacts/` 可以透過 run 詳情頁下載，但那是**明確列舉的檔案**，不是目錄瀏覽器。

**Agent Run 不能讀寫使用者的 allowed root。** 這一條要有測試：runner 程序的工作目錄與可及路徑都收斂在 run 目錄內。

---

## ⚠️ D20 — Git 存取

**問題**：怎麼拿到程式碼、怎麼把結果送回去。

**已裁決（2026-08-08）：同時支援 fine-grained PAT 與 SSH key。**

**取得**：卡片宣告 `source`（D21），daemon 從 node 上的 bare mirror `git worktree add`，再 `git checkout -b cliora/<card_ref>-<run_seq> origin/<base_branch>`。

**送回**：只有 `git push origin cliora/<card_ref>-<run_seq>`。

### 五條硬約束（寫死在 daemon，不是設定值，各配一條測試）

1. 只能推 `cliora/` 前綴的分支。
2. 永不推 base／target 分支——`target_branch` 是「PR 合併回哪裡」，不是推送目標。
3. 永不 force push、不刪遠端分支、不動 tag。
4. remote allowlist：只能推到該 Project 登記的 repository host。
5. commit trailer 帶 run id，作者是 bot identity，不冒充人類。

### 兩種認證的落地方式

**兩者都不得把 token 或私鑰寫進檔案**（D22 的「不落檔」）：

| | Fine-grained PAT | SSH key |
|---|---|---|
| 傳輸 | HTTPS | SSH |
| 交給 git 的方式 | `GIT_ASKPASS` 指向一支**本身不含機密**的小 helper，helper 從環境變數讀值 | **`ssh-agent` ＋ `ssh-add -`（從 stdin 讀入）**，私鑰永不落檔 |
| 為什麼不用別的 | **不得把 token 塞進 remote URL**——它會出現在 `git remote -v`、reflog 與錯誤訊息。也不用 `-c http.extraHeader`，那會出現在 `ps` | **不得寫一個 0600 私鑰檔再刪掉**——那違反不落檔規則，而且刪除失敗就留在磁碟上 |
| 收尾 | 程序結束即消失 | run 結束 kill agent；socket 在 run 目錄內、權限 0700 |
| host 驗證 | host allowlist | host allowlist ＋ **known_hosts pinning**（`StrictHostKeyChecking=yes`） |

`ssh-agent` 那一格是對 D22「機密不落檔」的**重要細化**：**socket 不是金鑰**。這條要明寫進 ADR，否則實作時很容易退回「寫個 0600 檔案就好」。

known_hosts 這條有既有的前例可循（`fix/update-healthcheck-known-hosts`），沿用同一套做法。

### 一個必須先講清楚的後果：SSH 開不了 PR

**SSH 只有 git 傳輸，沒有 API。** 所以一個用 SSH 認證的 repo，若卡片的 `delivery` 是 `pull_request`，它**還需要第二個機密**來開 PR。

| repo 認證 | push | 開 PR |
|---|---|---|
| PAT（含 `Pull requests: write`） | ✅ 同一枚 | ✅ 同一枚 |
| PAT（只有 `Contents: write`） | ✅ | ❌ 需另一枚 `provider_token` |
| **SSH key** | ✅ | ❌ **必定**需要另一枚 `provider_token` |

**UI 在設定 repository 時就要檢查並提示**，不要等 run 跑到最後一步才失敗——那時候分支已經推上去了，使用者只會看到一個沒頭沒尾的錯誤。

### Fine-grained PAT 的最小權限（寫進文件並在 UI 提示）

- `Contents: Read and write`
- `Pull requests: Read and write`（若同一枚要開 PR）
- **指定 repository，不要 all repositories**
- **設定到期日**——fine-grained PAT 強制要求，這正是選它而不選 classic PAT 的理由

### 不做

fetch 以外的任何遠端寫入、merge、rebase 到共用分支、release、tag。

---

## 🆕 D21 — 任務卡的來源與交付模式（**不是每張卡都要 PR**）

**問題**：調查型、分析型、寫規格型的任務不產生程式碼變更，也不該被迫開 PR。

**建議：`source` 與 `delivery` 是兩個獨立欄位。**

### `source` — 這張卡要不要程式碼、要哪一份

| 值 | 意思 | 用在 |
|---|---|---|
| `none` | 不 clone 任何東西 | 寫規格、產生任務拆解、回答問題 |
| `repo` | clone 指定 repository 的 `base_branch` | 絕大多數 |
| `existing_branch` | checkout 一條既有分支（不新建） | 接續前一次 run、修 review 意見 |

### `delivery` — 做完之後成果怎麼離開

| 值 | 動作 | 完成條件 |
|---|---|---|
| `none` | **不推送任何東西** | 完成摘要 ＋ 驗證報告 ＋ 看板上的訊息就是產出 |
| `branch` | 推 `cliora/<card_ref>-<run_seq>`，不開 PR | 使用者自己決定要不要開 |
| `pull_request` | 推分支並開 PR／MR，target 為卡片的 `target_branch` | **預設值** |
| `existing_pr` | 推到既有 PR 的分支，追加 commit | 修 review 意見的迴圈 |

### 兩個誠實性規則

1. **`delivery: none` 但工作目錄有變更時，不得靜默丟棄。** run 結果要標示「本卡宣告不產出變更，但偵測到 N 個檔案變更」並附 `git diff --stat`，讓人決定。靜默丟棄會讓人在幾週後發現一份不見了的工作。
2. **`source: none` 但 Agent 想讀程式碼時，它讀不到——這是刻意的。** 需要讀就把卡片改成 `source: repo`，而那是一次卡片編輯，會留下紀錄。

### 對 Done Gate 的影響

`delivery: none` 的卡不能用「有沒有 PR」當完成證據，所以它的 Done Gate 是：完成摘要 ＋ 驗證報告 ＋ 每項 AC 有結果。這正好是 `version2.md` §7.8 的最低完成條件，不必為它另做一套。

---

## ⚠️ D22 — 機密管理

**問題**：裁決要求「系統紀錄環境變數，以安全的方式下放給 agent 執行」。這是 V2 最大的新安全面。

**已裁決（2026-08-08）：主金鑰放環境變數 `CLIORA_SECRET_MASTER_KEY`。**

| 面向 | 決定 |
|---|---|
| 儲存 | `project_secrets`，**信封加密**：每筆一把資料金鑰（DEK），DEK 以主金鑰包裝後與密文同列 |
| 主金鑰 | **環境變數**，與既有的 `CLIORA_JWT_SECRET`／`CLIORA_TOKEN_PEPPER` 同一種做法 |
| 讀取 | **寫入後永不可讀回。** 沒有任何 API 回傳值，UI 只顯示名稱、建立者、最後使用時間 |
| 下放 | 每次 run 隨 `run.offer` 送出**該卡片宣告需要的那幾個**，走既有已認證的 WSS。不是整包、不是常駐 |
| 落地 | runner 只放在記憶體，以環境變數傳給 CLI 程序，**不寫進任何檔案**（例外見 D20 的 `ssh-agent`） |
| 去識別 | runner 在送 `run.log_chunk` 前對已知值比對替換為 `***`。**在 runner 端做**——值不該離開 node |
| 名稱 allowlist | Project 宣告可用名稱；卡片只能從中挑 |
| node 可拒絕 | `accept_secrets: false` 的 node 只領 `required_secrets` 為空的卡片 |
| 稽核 | 每次下放一筆 audit（誰的 run、哪個 project、哪幾個名稱——**不含值**） |
| 輪替與撤銷 | 可覆寫、可刪除；進行中的 run 不受影響，下一次生效 |

### 主金鑰放環境變數：買到什麼、付出什麼

買到的：**與本 repo 的既有做法完全一致**——不只是 JWT secret 與 token pepper，ADR 0022 的 tunnel 供應商憑證就是用 `CLIORA_SECRET_ENCRYPTION_KEY`（環境變數、32 bytes base64、AES-GCM、每次寫入換 nonce、無金鑰即拒絕啟用該功能）加密的。**這不是新發明的模式，是照抄一個已經通過安全審查的模式。**

> 一個實作細節：`project_secrets` 建議用**自己的** `CLIORA_SECRET_MASTER_KEY`，不要共用 `CLIORA_SECRET_ENCRYPTION_KEY`。兩者的輪替時機不同（tunnel token 換供應商時換；專案機密可能因人員異動而換），共用會讓其中一個的輪替被另一個綁住。

還買到：沒有新的雲端依賴、離線與自架部署都能用、實作最小。

**付出的代價要誠實寫進 ADR，不能只寫好處**：

| | 環境變數（已裁決） | KMS |
|---|---|---|
| **金鑰與密文的信任邊界** | **同一個**——能讀 env 的人通常也能讀 DB | 分開 |
| 解密稽核 | **沒有**（不知道誰在何時解了什麼） | 有 |
| 輪替 | 部署 ＋ 重新包裝 DEK | 一次 API 呼叫 |
| 金鑰遺失 | **所有機密不可復原** | 可控 |

第一列是最重要的一列：**這個方案沒有把金鑰與資料分開**。不是致命，但它意味著「DB 備份外洩」的防護仰賴攻擊者拿不到 env，而不是兩道獨立的防線。ADR 要把這句寫出來。

### 讓這個選擇不變成死路的四件事

1. **信封加密仍然要做。** 輪替主金鑰時只需重新包裝 DEK，不必重新加密所有密文。沒有信封，輪替就是一次全表重寫。
2. **`key_version` 從第一天就有**，不是「日後再加」。
3. **啟動時驗證**：金鑰缺少、長度不足、或等於 dev 預設值 → **拒絕啟動並指名是哪一個**。這是 `.env.example` 對 JWT secret 與 token pepper 的既有處置，照抄即可。
4. **把升級到 KMS 的路徑寫進 ADR**：有了信封加密與 `key_version`，改用 KMS 只是換掉「解開 DEK」那一個函式。這句話要寫，否則半年後會有人以為當初選錯而想整批重做。

### 一個運維上的硬事實

**DB 備份本身無法還原機密**——金鑰在 env，不在備份裡。所以：

- `docs/runbooks/backup-restore.md` 要增訂：金鑰另外保管，且必須與該次備份的 `key_version` 相符。
- **金鑰遺失＝所有機密不可復原**，只能全部重建（每個 repo 的 token 都要重發）。這一句要在機密設定頁上直接寫出來，不要只躺在 runbook 裡。

### 與既有 `tunnel_integration` 的關係

不混用。那張表是「組織給第三方 tunnel 供應商的憑證」，單一用途、Admin 專屬。專案機密是多值、多專案、會被下放到 node 的，風險等級不同，混在一起會讓兩者的規則互相污染。

**這一條必然觸發安全審查**（`10` §6）。

---

## ⚠️ D23 — SEC-002 要修訂到什麼程度

**問題**：機密下放就是環境變數注入，而 SEC-002 明文禁止呼叫端指定環境變數。

**建議：精確地只撤銷一句，其餘全部保留。**

| SEC-002 的內容 | 處置 |
|---|---|
| 呼叫端不得指定 command／binary／shell string | **完全保留**。argv 仍由 daemon 從 allowlist 組出 |
| 呼叫端不得指定環境變數 | **修訂為**：請求 payload 不得攜帶環境變數的**值**；值只能來自平台 secret store，名稱只能來自專案 allowlist |
| 互動式 Session | **完全不變**，一個位元組都不動 |

修訂後的不變式，一句話：

> **沒有任何請求 payload 能命名一個命令、或攜帶一個機密的值。**

這句話同時擋掉了「從 UI 傳一個 env 給 run」與「從卡片描述注入 shell」兩種攻擊，而它比原本的措辭更精確——原本的措辭把「不能有 env」與「不能有任意執行」綁在一起，其實那是兩件事。

ADR 0027 要記錄這次修訂，並在 `Alternatives rejected` 明列：讓卡片直接寫 env 值（會讓機密進資料庫的明文欄位與 UI）、讓 runner 從 node 本機的 `.env` 讀（平台無法稽核也無法撤銷）。

---

## D24 — 看板作為溝通管道

**問題**：裁決要求「使用者可以直接透過任務看板跟 agent 溝通」。

**建議：`task_messages` ＋ 一個 run 狀態。**

- 訊息模型：`task_messages(task_id, run_id, author_kind[user|agent|system], author_id, body, created_at)`。使用者在卡片上留言；Agent 用 `cliora task say` 回覆。
- **Agent 怎麼收到訊息**：它在自然的停頓點主動拉（`cliora task messages --since`）。**不做中斷式推送**——推送需要在 CLI 執行中打斷它，那是 Terminal relay 的語意，會把兩條執行路徑混在一起。
- **Agent 提問時**：run 進入 `waiting_for_input`，租約續租但不計入執行逾時，卡片顯示「等待你的回覆」並在看板上標記。使用者回覆後 Agent 下次拉取就看到。
- **逾時**：`waiting_for_input` 超過可設定時間（建議 24h）自動結束 run 並把卡片退回 `blocked`，原因寫明。否則會有 run 永遠掛著佔著容量。

這正好把 `version2.md` §5 的「目前阻塞原因」變成一個真的機制，而不是一個要 Agent 自覺填寫的欄位。

---

## ⚠️ D25 — 自主執行的收斂點

**問題**：沒有人在終端前面看著，Agent 做錯事怎麼辦？

**建議：不試圖限制 Agent 在沙箱裡能做什麼，改為限制它的產出能怎麼離開沙箱。**

這是 §7 紅線 5：出口只有 PR／分支／無交付三種。推論：

- 沙箱內：Agent 有完整的檔案與 shell 能力（那是 `claude`／`codex` 的原生能力，ADR 0023 的「node 是可拋棄的隔離 VM」姿態已經涵蓋）。
- 沙箱外：只有 `git push` 到 `cliora/` 分支這一個副作用，且不自動合併。
- 網路：node 層面的事，平台不宣稱能控制。**這一點要誠實寫進 ADR**——如果組織需要限制 Agent 的對外網路，那是 node 的部署姿態（防火牆、egress proxy），不是平台功能。

**為什麼不做「Agent 動作審批」**：那會讓自主執行退化成互動式 Session，而互動式 Session 已經存在。要人審就用 Session，要自動就接受沙箱模型 —— 中間態兩邊的缺點都有。

---

## D26 — 互動 Session 與 Agent Run 的關係

**建議：並存、不互相取代、V2 期間不做互轉。**

- 從卡片可以做兩件事：「派給 Agent」（建立 run）或「我自己來」（開互動 Session，V2.1 已有）。
- 一張卡在同一時間只能有一個進行中的 run，但可以同時有人開著 Session 看。
- **不做「把 run 升級成互動 Session 接管」**：run 的工作目錄是隔離的、會被清掉，把它變成一個持久 tmux session 需要重新設計生命週期。想接管就用 run 產出的分支，在自己的 workspace 開 Session。

這一條列在這裡是為了擋掉一個很誘人但代價很大的功能。真的需要時再開 ADR。

---

## ⚠️ D27 — Run log 與「terminal bytes 從不儲存」的既有承諾

**問題**：V1 明文承諾終端位元組從不儲存（PRD、ADR 0013）。Agent Run 的輸出就是終端輸出。存它算不算違反承諾？

**建議：不算，但必須把界線寫清楚，否則它會變成侵蝕那條承諾的先例。**

| | 互動式 Session | Agent Run |
|---|---|---|
| 終端另一端是誰 | **一個人**，他的鍵盤輸入與螢幕內容 | 一個自動程序 |
| 那些位元組是什麼 | 操作者的隱私 | **這次執行的產出紀錄** |
| 不存的話會怎樣 | 沒事，人自己看得到 | 沒有人看得到，run 完全不可稽核 |
| 決定 | **繼續不存，一個位元組都不存** | 存，但有界、去識別、有保留期 |

Run log 的四條約束：

1. **有界**：單次 run 的 log 上限（建議 5 MB），超過從中間截斷並明示「已截斷 N bytes」。
2. **去識別在 runner 端做**（D22）：機密值在離開 node 之前就被替換掉。
3. **保留期**：與 run 目錄一致（成功 3 天、失敗 14 天可設定），到期刪除。
4. **不是 Terminal relay**：`run.log_chunk` 是單向、批次、可丟棄的；它不走 `terminal.*` 的任何一條路徑，也沒有 writer／viewer 語意。

ADR 要明寫：**這不構成「平台現在會存終端內容」的先例。** 互動式 Session 的承諾未變，而且兩條路徑在程式碼上是分開的。

---

## 🆕 D28 — 需求釐清與任務拆解的形狀

**問題**：Monstrare 的 `spec-interrogation`（把模糊需求問成規格）與 `project-kickoff`／`implementation-plan`（拆成 Epic→US→Task）要怎麼內化？

### 一、釐清用既有管道，不新增介面

「Agent 反覆詢問使用者」已經有現成的落點——D24 的看板溝通：`cliora task ask` → `waiting_for_input` → 卡片顯示「等待你的回覆」→ 使用者在訊息串回答 → Agent 下次拉取看到。

**否決獨立的釐清聊天介面。** 兩套訊息管道會立刻分裂：使用者不知道在哪回話、Agent 不知道讀哪邊、稽核要看兩個地方。

這回頭證明 D24 的形狀是對的——它原本只為「執行中的 Agent 能提問」而設計，整個釐清流程直接落在上面。

### 二、Agent 的產出是**提案**，不是正式資料

拆解 run 產生 `task_proposals`（一列 JSONB 樹），人接受之後才建立真正的 Epic／User Story／Task。

這是 `review-gates.md`「agent 輸出不等於核准」在這條路徑上的形式，也讓 DoR 有地方可以擋——**缺 DoR 欄位的提案卡被接受後直接落 `backlog` 而非 `ready`**。

### 三、三個人工關卡，各自獨立

| 關卡 | 進站條件 | 動作 |
|---|---|---|
| 規格核准 | **`open_questions` 全部已解決或明確標為「已知未知」** | 需求進 `approved` |
| 提案接受 | 規格已核准 | 全部／部分／編輯後建立／拒絕 |
| UI 變體選定 | 卡片涉及畫面（可延後） | 決定記錄在卡片 |

三個關卡都必帶人類 actor 與 audit；**Agent 憑證的 scope 永遠不含它們**。

### 四、分兩段交付，而這是原文的要求

`version2.md` §17 明寫：

> 不要先做 Agent 自動生成 PRD。**先建立可靠的資料結構與人工操作流程，再讓 Agent 使用相同 API。**

所以 **V2.1 交付資料模型與人工表單**（人可以自己寫規格、自己拆卡），**V2.5 才讓 Agent 走同一條 API**。若 V2.1 的人工流程沒人用，V2.5 也不會有人用——這是一個免費的早期訊號。

### 五、停止條件直接內化

`ai/process/context-protocol.md` 的五條停止條件寫進釐清 run 的情境包：搜尋發現多種做法且各有取捨、需求與既有架構衝突、缺少必要檔案、涉及密鑰／認證／金流／遷移／基礎設施、預估範圍超出卡片。**遇到任一條就停下來問，不要自己選。**

### 六、一次一個問題

一口氣丟五個問題，實務上會得到三個答案與兩個被忽略的問題，而 Agent 分辨不出哪個被忽略。寫進情境包，並在 CLI 端限制 `task ask` 頻率。

**Alternatives rejected**：Agent 直接建立正式卡片（繞過 DoR 與人工核准）、平台自動接受低風險提案（「低風險」本身就是 Agent 說的）、獨立聊天介面（管道分裂）、要求一次產生完整 Roadmap（`version2.md` §7.7 明文不要求）。

---

## ⚠️ D29 — 任務卡產物（Artifacts）

**已裁決：Agent 可以把產物交付到任務卡上，執行中也可以用留言附檔的方式。**

### 一、它不是紅線 5 的例外，是紅線 5 漏掉的一種形式

紅線 5 的原則是「每一種出口都必須落在人看過才生效的地方」。卡片產物是**惰性資料**——不碰 repo、不碰分支、不觸發任何東西，人打開才看得到。**它是四種出口裡最安全的一種。**

第一版把紅線 5 寫成「只有三種」是把清單當成定義；現在改成陳述原則，清單變成推論（`00` §7）。

### 二、能力與宣告要分開

| | 意思 |
|---|---|
| **附加產物的能力** | **每個 run 隨時都可以做**，就像發訊息一樣。不需要卡片事先宣告 |
| **`delivery: artifact`** | 「這張卡的完成證據**就是**產物」——Done Gate 要求至少一件 |

分開之後，一張 `delivery: pull_request` 的卡也可以在執行中附上測試報告與截圖，而它的完成證據仍然是 PR。這是對的：附件是過程證據，delivery 是成果形式。

### 三、產物必須存在平台，不能留在 node

run 目錄有保留期（成功 3 天、失敗 14 天，D19），**但卡片是永久的**。產物留在 node 上，三天後卡片上就會是一堆死連結。

所以：runner 在附加時**上傳到平台**，平台durable 儲存，與 run 的清理週期無關。

**這是 ADR 0024 W2 那個問題的兩個不同答案，要寫清楚**：

| | run log | 卡片產物 |
|---|---|---|
| 是什麼 | **診斷**紀錄 | **交付物** |
| 誰清、何時 | 保留期到期自動刪 | **跟著卡片走**；卡片在就在 |
| 上限 | 單 run 5 MB，超過截斷 | 單件 10 MB、單 run 件數、**專案總配額** |

### 四、提供時的安全問題（本條真正的風險）

產物是 Agent 產生的檔案，平台要把它送回瀏覽器。這是一條「不受信任內容 → 使用者瀏覽器」的路徑，**而 Cliora 是單一 origin 部署**（ADR 0020）。

規則：

1. **預設一律下載，不內嵌渲染**：`Content-Disposition: attachment`、`X-Content-Type-Options: nosniff`。
2. **只有小白名單可以內嵌預覽**：圖片、純文字、markdown（走既有的預覽政策，與 ADR 0015 同一套限制）。
3. **HTML 產物**（例如 RQ-07 的 mockup 變體）**不得在應用 origin 內直接渲染**。要預覽就放進 `sandbox` iframe 並配 CSP，或乾脆只提供下載。**這一條要在 V2.5 做 mockup 預覽之前定案，不能到時候便宜行事。**
4. 產物**繼承 Project 的存取控制**（`project.view`），沒有公開連結、沒有可猜的 URL。

### 五、內容不保證不含機密

runner 端的去識別（D22）只對 log 的文字串流有效。一個二進位產物裡面有什麼，平台不知道也無法保證。

**誠實寫進 ADR**：這與 log 去識別是同一種盡力而為，真正的保障來自「機密可撤銷」與存取控制。不要在 UI 上暗示產物是安全的。

### 六、產物不可變

已附加的產物**不可編輯、不可取代**（沿用平台一貫的「只新增」姿態）。要更新就附一個新的，時間軸自然呈現版本。

Admin 可以刪除（配額耗盡時的唯一出路），需理由並寫 audit。

### 七、把「不得靜默丟棄」變得更有用

D21 的誠實性規則原本是：`delivery: none` 但工作目錄有變更 → 顯示 `diff --stat` 讓人決定。

有了產物之後可以更好：**把 diff 直接附成一件產物**。那份工作就不會消失在被清掉的 run 目錄裡，而是變成卡片上一個可下載的 patch 檔。

**Alternatives rejected**：產物留在 node 由平台代理讀取（卡片比 run 長壽，會產生死連結）、允許編輯已附加的產物（違反只新增姿態，且破壞證據性）、在應用 origin 直接渲染 HTML 產物（stored XSS）、把產物當成 run log 的一部分（保留期語意衝突）。

---

## 🆕 D30 — 驗收素材用哪個專案

**已裁決（2026-08-08）：`git@github.com:Lei-k/Traqora.git`**，不是 Cliora 自己。

### 為什麼另一個 repo 比 dogfooding 自己好

1. **它真的驗到「跨專案」這個賣點。** Cliora 管 Cliora 只證明它管得動一個專案；Cliora 管 Traqora 才證明它管得動一個**跟自己無關**的專案。
2. **預設分支不同**（Traqora `main` vs Cliora `master`）。這會逼出「`base_branch` 真的是設定值，不是寫死的 `master`」——一個只在自己 repo 上測的實作很容易漏掉這點。
3. **分支命名慣例不同**（Traqora 用 `p4-`／`p5-1-` 這種階段前綴，沒有 `feat/`）。正好驗證 `cliora/<card_ref>-<run_seq>` 命名空間不會撞到別人的慣例。
4. **避免故障的循環依賴。** 這一條最重要：V2.2 的已知缺口是 run **還沒有隔離**，直接在使用者的 workspace 執行。拿正在被建造的平台本身當標的，一次壞掉的 run 可能弄壞你用來跑它的東西。

### 但有一條使用上的限制

Traqora 看起來是有 9 條功能分支的**活躍專案**。所以：

| 階段 | 標的 | 理由 |
|---|---|---|
| V2.0／V2.1 | **正式 repo 可以** | 只在 workspace 寫 `.cliora/`，不碰程式碼 |
| **V2.2** | **用 scratch clone 或 fork，不要用正式 repo** | run 尚未隔離，直接在 workspace 執行 |
| V2.3 起 | 正式 repo 可以 | 隔離目錄 ＋ 分支命名空間 ＋ 只出 PR |

這一條要寫進 V2.2 的工作包，否則「建議只在測試專案啟用」會被當成客套話。

### 各階段用 Traqora 驗什麼

- **V2.0**：把 Traqora 的多個目錄綁在**兩個不同 node** 上 → 驗跨 node 綁定與 root 停用時的狀態顯示。
- **V2.1**：用 Traqora 真實的待辦建看板 → 驗六車道與 DoR 在真實工作上撐不撐得住。
- **V2.2**：scratch clone 上跑第一次認領 → 驗雙重領取、租約重排。
- **V2.3**：`base_branch: main` → 驗設定值不是寫死的；PAT 與 SSH **各測一次**。
- **V2.4**：對 Traqora 開出第一個真的 PR → 這是整個 V2 的第一次真實交付。
- **V2.5**：拿 Traqora 一句真實的模糊需求走完釐清 → 拆解。

**Cliora 自己仍然不納入管理。** 平台管自己會讓「平台掛了」與「工作停了」變成同一件事，那在 V2 這種還在動安全姿態的階段不值得。

---

---

## 🆕 D31 — Mockup 預覽走既有的 Pinggy tunnel

**提案（2026-08-08）**：不要讓平台去渲染 Agent 產生的 HTML，改成**讓 mockup 從 run 所在的 node 經 Pinggy tunnel 對外提供**，並由 **Agent 在任務卡上詢問要用哪一種保護策略**（密碼／限制 IP／不保護）。

**這是目前最好的方案，而且它幾乎不用新做東西。**

### 為什麼它比前四個方案都好

**一、它從構造上消滅了 stored XSS，不是靠設定去繞過。**

前面的 B（sandbox iframe）是在同一個 origin 裡想辦法關住不受信任的內容——做對了安全，做錯一個 flag 就全開。Pinggy 的 URL 是**完全不同的 origin**，同源政策自己就把它擋在 `localStorage` 與同源 API 之外。**沒有 sandbox flag 要調，沒有 CSP 要對。**

**二、它不是新功能。** 既有的東西已經齊了：

| 需要的東西 | 現況 |
|---|---|
| tunnel 生命週期、授權、限額、稽核 | ADR 0022 已交付（`plan/11`） |
| protocol `tunnel.open` / `close` / `status` | 已存在 |
| `node_tunnels.protection` ＋ `basic_auth_user`／`basic_auth_hash`／`allowed_ips` | **三種策略的欄位已經在資料模型裡** |
| 供應商憑證（加密、write-only、fingerprint） | `tunnel_integration` 已存在 |
| 併發預算、TTL、port allowlist | `concurrent_budget: 8`、`default_ttl_seconds: 4h`、`allowed_ports` |
| RBAC | `tunnel.view` / `tunnel.manage` 已存在 |
| UI | `/nodes/:id/tunnels` 已存在 |

**三、mockup 正好是 ADR 0022 範圍宣告的理想使用情境。** 那份 ADR 明寫：

> This feature is for previewing applications under development. **It is not for any environment holding real data.**

它的兩個能力缺口——**流量經過供應商且 TLS 在對方終止**、**平台無法回答「誰看過這個預覽」**——對一個沒有任何真實資料的 mockup 來說，正好都不構成問題。這比它原本的使用情境（預覽開發中的應用，那多少會有測試資料）**更貼合**。

**四、詢問策略這件事不需要新機制。** `cliora task ask` → `waiting_for_input` → 卡片顯示「等待你的回覆」→ 人回答（D24）。整條流程已經設計好了。

**五、它順手解決的不只是 mockup。** 任何產出「跑得起來的東西」的 run——Storybook、報表網站、開發伺服器——都能用同一條路預覽。

### 紅線 5 有沒有被打破

沒有，但論證必須寫清楚，否則它看起來像第五種出口。

tunnel **不是產出離開沙箱**，位元組始終在 node 上；它是一扇看進沙箱的窗。但它確實製造了一個對外的面，而紅線 5 的實作規則寫了「不得執行任何上述四種以外的外部副作用」。

**保住紅線的關鍵是：開 tunnel 的不是 Agent，是人。**

```text
Agent 用 task ask 詢問要用哪種保護策略
  → 卡片顯示「等待你的回覆」
  → 人選擇（密碼／限制 IP／不保護）
  → 平台以那個策略開 tunnel
  → Agent 只被告知 URL
```

**Agent 憑證的 scope 永不含 `tunnel.manage`**——與 `task.approve`、`secret.manage`、`process.manage` 同一條規則。Agent 沒有任何單方面的對外副作用，紅線 5 成立。

### 必須設計的六件事

1. **只服務指定的子目錄**：`artifacts/preview/`，**不是 run 根目錄、不是 `repo/`**。靜態檔案、**不列目錄**、不執行。否則一次路徑穿越就把整份原始碼推上公網。
2. **預覽程序不繼承 run 的環境變數**。run 的 env 裡有機密（D22），預覽伺服器不該看得到。
3. **生命週期綁 run**：run 結束、取消、租約逾時 → tunnel 一律關閉。另加一個與 run 無關的最大 TTL（沿用 `default_ttl_seconds`）。
4. **預設是密碼保護**，且密碼**由平台產生**（不是 Agent，不是使用者自訂弱密碼），一次性顯示在卡片上。`tunnel_integration.default_protection` 本來就是 `basic`，沿用。
5. **「不保護」要多一道明確確認**，並寫進 audit。URL 雖然是隨機的，但它會進瀏覽器紀錄、進卡片、可能進日誌——**隨機不等於秘密**。
6. **每個 Project 一個預覽併發上限**，與既有的 `concurrent_budget` 一起算。否則一個失控的 run 會把整個組織的 tunnel 額度吃光。

### 前置條件：沒有啟用 tunnel 整合，就沒有 mockup（已裁決）

**目前唯一的供應商是 Pinggy，而 tunnel 整合是 Admin 才能啟用的單例設定**（`tunnel_integration.enabled` ＋ 供應商憑證，ADR 0022）。**沒有啟用時，系統不做 mockup。**

寫成「**tunnel 整合**未啟用」而不是「Pinggy 未啟用」——`tunnel_integration.provider` 這個欄位本來就是為了日後可能有第二家供應商而存在的，措辭綁死在 Pinggy 上，日後換人就要改一輪引用。

### 未啟用時，什麼消失、什麼還在

| | 未啟用 tunnel 整合 | 已啟用 |
|---|---|---|
| **UI Mockup 關卡**（2–3 變體、人工選定、`links.mockupDecision`） | **整個不存在** | 存在 |
| `process_definitions` 的 `ui` gate | **自動停用** | 可用 |
| Agent 附截圖為卡片產物 | **照常**（那是 D29 的通用能力，與本條無關） | 照常 |
| 互動式預覽 | 不可用 | 可用 |

**截圖不會消失**，因為它從來不屬於這個關卡——任何 run 都能附產物（D29）。消失的是**治理關卡**：變體比較、人工選定、以及 DoR 上對 mockup 決策的要求。

### 三個必須一起定的後果

**一、`ui` gate 必須「自動停用」，不能只是「可以手動關掉」。**

若整合未啟用而 `ui` gate 仍是啟用狀態，涉及畫面的卡片會卡在一個**永遠無法滿足的關卡**上。這是死鎖，不是嚴謹。所以：整合未啟用 ⇒ `ui` gate 由系統停用，不由 Admin 記得去關。

**二、要看得見，不能靜默。**

一個悄悄不存在的關卡比一個說明自己為什麼不存在的關卡糟。Project Settings 要寫出來：

> UI Mockup 關卡：**停用** —— 未啟用 tunnel 整合。[前往設定]

**三、dispatch 的行為要分兩種卡，不能一刀切。**

| 卡片性質 | 未啟用整合時 |
|---|---|
| **產出 mockup 變體**本身就是這張卡的交付物 | **dispatch 當下拒絕**，理由寫明是整合未啟用（沿用 D17b「資格衝突在 dispatch 當下拒絕」的同一個原則） |
| 一般 UI 實作卡（原本需要先有 mockup 決策） | **照常執行**，只是 `links.mockupDecision` 的要求被解除 |

第二列很重要：實作工作本身是有效的，不該因為預覽機制沒開就整批擋下。

### 一個順帶的好處

ADR 0022 帶著一句硬性範圍宣告：「**這個功能用於預覽開發中的應用，不適用於任何持有真實資料的環境**」。把 mockup 關卡綁在這個整合上，等於讓組織**在同一個地方、只接受一次**那條宣告——而不是在 V2.5 又寫一份意思相同的警語。

### 與截圖（方案 D）的關係：不是二選一

| | 截圖（PNG 產物） | Pinggy 預覽 |
|---|---|---|
| 性質 | **永久的交付紀錄**（`task_artifacts`，跟著卡片走） | **暫時的即時預覽**（隨 run 結束消失） |
| 互動 | 沒有 | 有 |
| 成本 | 零 | 供應商額度 ＋ 一次人工決策 |
| 離線可看 | 是 | 否 |

**兩個都要**：截圖是留在卡片上的證據，tunnel 是需要點點看時才開。用 tunnel 取代截圖會讓三個月後回頭看卡片時什麼都不剩。

### 要同步修訂的東西

- **ADR 0022 加一節**：這條路徑現在也用於 run 的預覽，發起方式是「Agent 提議 → 人核准 → 平台執行」。它的範圍宣告（不得用於持有真實資料的環境）**不變且更強**。
- `node_tunnels` 需要一個 nullable 的 `run_id`，讓預覽 tunnel 能隨 run 一起關掉並在 Run 詳情頁顯示。

---

## 決策裁決表

### 已裁決

| 編號 | 主題 | 裁決 |
|---|---|---|
| D2 ⚠️ | Monstrare 導入方式 | ✅ 功能內化，不複製檔案；skill／subagent／`AGENTS.md` 為硬邊界，靠投影橋接 |
| D1 ⚠️ | 真實來源 | ✅ 平台 DB |
| D6 | 平台改卡片 | ✅ 可拖曳（內化後是 DB `UPDATE`，不碰檔案） |
| D5 | 免 Session 讀檔 | ❌ 取消（內化後不必要） |
| D21 🆕 | 交付模式 | ✅ **不是每張卡都要 PR**：`source` 與 `delivery` 兩個獨立欄位，各四個值 |
| — | Agent Runner 模型 | ✅ 自行認領、多對多、隔離目錄、機密下放、依卡片交付 |

### 建議採納（需你點頭）

| 編號 | 主題 | 建議 |
|---|---|---|
| D3 | 看板詞彙 | 用 Monstrare `stage`，UI 中文標籤 |
| D4 | Epic／User Story | 升級為平台實體 |
| D7 ⚠️ | 情境交付 | 檔案為預設；「代打第一行」在 Agent Run 路徑上不需要（平台本來就是啟動者） |
| D8 | 情境內容 | ≤4 KB，只給路徑 |
| D9 | 執行計畫形狀 | DB 版本列，保留 append-only 語意 |
| D10 ⚠️ | 證據可信度 | 三級 ＋ 伺服器端判定；「平台代跑驗證命令」在 Agent Run 路徑上**改為允許**，因為那本來就是 run 在做的事——但仍不開放「對任意 node 執行任意命令」的 API |
| D11 ⚠️ | 工具介面 | CLI 優先，V2.1 首發 |
| D12 | 相容機制 | 單一旗標 ＋ 永久 nullable |
| D31 🆕 | Mockup 預覽 | ✅ **已裁決：走既有 tunnel 整合（目前只有 Pinggy）**。Agent 在卡片上問策略、人決定、平台開。**未啟用整合時系統不做 mockup**：`ui` gate 自動停用、產出變體的卡在 dispatch 當下被拒、一般 UI 卡照常執行。截圖是 D29 的通用能力，不受影響 |
| D30 🆕 | 驗收素材 | ✅ **已裁決：用 Traqora**，不用 Cliora 自己。V2.2 期間限用 scratch clone（run 尚未隔離） |
| D14 🆕 | 平台不可用時 | ✅ **已裁決：直接失敗，不做離線佇列**。關鍵在訊息要說出「Session 可繼續工作」；M9 是重新評估的觸發條件 |
| D13 | RBAC | 新增動作（見 `07` §5，已因 Runner 擴充） |
| D15 | 流程可設定性 | V2.1 寫死，V2.4 最小可覆寫 |
| D16 | Agent 實體 | `agentd` 的一個模式，重用既有信任鏈 |
| D17 ⚠️ | 認領模型 | ✅ **已裁決：拉取式** ＋ 租約 ＋ 重排上限 |
| D17b 🆕 | 指定 Agent | ✅ **已裁決：可指定可不指定**（預設不指定）。指定不繞過綁定授權；資格衝突在 dispatch 當下拒絕；預設不逾時退回 |
| D28 🆕 | 需求釐清與拆解 | ✅ **已裁決：納入 V2**。釐清用既有看板管道；Agent 產出是提案；三個人工關卡；資料模型 V2.1、Agent 驅動 V2.5 |
| D29 🆕 ⚠️ | 任務卡產物 | ✅ **已裁決：Agent 可交付產物到卡片**，執行中亦可用留言附檔。能力與 `delivery: artifact` 宣告分開；存平台不存 node；**預設下載不渲染**；不可變 |
| D18 | 多對多綁定 | 顯式授權表 ＋ labels 能力過濾 ＋ 可選指定，三層 |
| D19 ⚠️ | 隔離工作目錄 | daemon 擁有、不在 allowed root、配額 ＋ 保留期 ＋ repo 快取 |
| D20 ⚠️ | Git 存取 | ✅ **已裁決：PAT ＋ SSH key 兩者都支援**。五條硬約束寫死在 daemon；PAT 走 `GIT_ASKPASS`、SSH 走 `ssh-agent` stdin，兩者都不落檔；**SSH 開不了 PR，需另一枚 provider_token** |
| D22 ⚠️ | 機密管理 | ✅ **已裁決：主金鑰放環境變數**。信封加密 ＋ `key_version` ＋ 啟動時驗證 ＋ KMS 升級路徑寫進 ADR；寫入後不可讀回、按需下放、runner 端去識別、node 可拒絕 |
| D23 ⚠️ | SEC-002 修訂 | 只撤銷 env 值那一句，argv 完全保留 |
| D24 | 看板溝通 | 訊息表 ＋ `waiting_for_input` ＋ 逾時退回 |
| D25 ⚠️ | 自主執行收斂 | 限制出口而非限制沙箱內行為 |
| D26 | Session 與 Run 的關係 | 並存，不做互轉 |
| D27 ⚠️ | Run log | 存，但與互動 Session 的承諾嚴格分開 |

### 仍需你裁決

| 編號 | 問題 |
|---|---|

