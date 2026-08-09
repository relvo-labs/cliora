# 06 — 驗證、證據與出口（`PJ-07`、`PJ-08`）

## 1. 共通完成定義（每張 ticket）

沿用既有紀律（`research/02/10` §1，對應本 repo 的工具）：

- 變更檔案清單與行為變更摘要。
- `make check` 通過（format、lint／vet、typecheck、unit、contract、build、
  traceability-validate、railway-check）。
- 涉及 DB 的：`make test-db` ＋ migration 上下行演練。
- 涉及畫面的：`make e2e` ＋ 截圖。
- 涉及 RBAC 的：`backend/tests/db/test_permission_matrix.py` 三條全綠。
- 已知限制與後續任務寫下來。

**不涉及的（本期一次都不會用到）**：`make integration`（daemon／tmux）。
它仍然要在旗標關閉的回歸套組裡跑一次（§3），但那是**回歸**不是**驗證**——
本期沒有任何 daemon 行為需要被驗證，因為本期沒有動 daemon。

**不算完成**（照既有紀律）：跳過測試沒說明理由、驗證只是「看起來沒問題」、
UI 改了沒截圖、AC 沒逐項檢查、動了不相關的檔案。

## 2. 測試清單

### 2.1 Central 單元（`pytest`）

| 檔案 | 覆蓋 |
|---|---|
| `backend/tests/test_authz.py` | 七條新路由在 `ROUTE_ACTIONS`（既有測試自動涵蓋）；`UNENFORCED_ACTIONS` 仍為空 |
| `backend/tests/test_activity_vocabulary.py` | `kind` 詞彙封閉性、`payload` 的禁用鍵、每個 kind 都有寫入點 |
| `backend/tests/db/test_projects_data_layer.py` | slug 產生與格式、狀態／唯一鍵／primary constraint、超過 1000 個 Project 時 detail summary 仍正確 |
| `backend/tests/db/test_projects_api.py`、`test_sessions_project_link.py` | **旗標開關下 route set 相同**、`features` 兩種值、旗標關閉七條 404、Session 的 project exact match／Ad-hoc／實際終止 actor |
| `backend/tests/test_audit_redaction.py` | 既有的兩條自動涵蓋五個新動作 |

### 2.2 Central DB（`make test-db`）

| 檔案 | 覆蓋 |
|---|---|
| `backend/tests/db/test_projects_api.py`、`test_projects_data_layer.py` | 綁定冪等、`is_primary` partial unique、node soft-delete 後消失／保留／重新啟用回來、解綁不影響 Session、activity keyset 分頁 |
| `backend/tests/db/test_permission_matrix.py` | 三角色 × 七條端點；**Viewer 的每一次寫入嘗試都斷言「什麼都沒留下」**（沿用 `RecordingRegistry`） |
| `backend/tests/db/test_migrations.py`（或既有等價處） | `0021`／`0022` 上下行；下行後 `pg_dump` 與 `PJ-00` 的 B2 基線逐位元組相同 |

### 2.3 前端單元（`vitest`）

| 檔案 | 覆蓋 |
|---|---|
| `AppLayout.test.ts` | 導覽不搬家（六個 href 在兩種旗標狀態下相同）、旗標關閉退回**原順序**、單一分組標題、`features` × `permissions` 四種組合 |
| `ProjectsView.test.ts` | optional slug／description 建立、404 intentional empty、request ID 與 retry |
| `ProjectDetailView.test.ts` | 9 條：usability 文字、Session 可用性、封存／權限／actor／kind label，加上 edit-pause 與 UI bind |
| `NewSessionDialog.test.ts` | 20 條：既有 14 條 Ad-hoc 行為全綠；另驗欄位顯示條件、封存過濾、無 Project 說明、project-page prefill 鎖定與可用綁定 |

**既有 14 條 Ad-hoc 案例仍全綠**是本期在這個檔案裡最重要的一行證據：
它證明加上 Project 欄位沒有改到 Ad-hoc 路徑。

### 2.4 契約（`make contract`）

**零變更。** 這是本期的一條斷言而不是一個步驟：
`git diff --name-only` 不得出現 `contracts/` 底下任何檔案（§4 的 `GATE-PJ-NO-WIRE`）。

### 2.5 E2E（`frontend/tests/e2e/projects.spec.ts`）

**已實作，五條，全綠。** 需要 `E2E_PROJECTS=1` ＋
`CLIORA_PROJECTS_ENABLED=true`；跨 node 那條另需 `E2E_SECOND_NODE=1`，
缺少時**跳過而不是假裝**——「一個專案跨兩台機器」用一台機器證不出來。

| # | 測試 | 守什麼 |
|---|---|---|
| 1 | 建專案 → 綁定 → 時間軸 | 導覽出現 `Projects` ＋ 一個分組標題；時間軸顯示**中文標籤而非 `workspace.bound`** |
| 2 | Project Session → timeline → 解綁 | prefill 鎖定；真 terminal／files；Ad-hoc 不入 timeline；解綁後仍運作 |
| 3 | Viewer 讀得到、寫入被拒且 actor 隱藏 | 精確 `POST /api/projects` 403、`authz.denied/project.manage` 一筆、actor 是 `—` |
| 4 | root 撤銷 | 畫面顯示 distinct `root_disabled`，直接建立 Session 回既有精確錯誤碼 |
| 5 | 一個專案跨兩台 node | 兩列綁定各自依自己的機器判定，列表計數是 `2 directories · 2 nodes` |

> **`run-stack.sh` 目前只 enroll 一台 node**（`e2e-node`，第 116–133 行），
> 而出口條件 1 與 4 都需要**兩台不同的 Node**。這是本期唯一一項對共用 e2e 基礎設施的改動，
> 要當成 `PJ-07` 的一個子項而不是臨場處理。
>
> **已實作（PJ-09）：opt-in 的 `E2E_SECOND_NODE=1`，預設關。**
>
> ```bash
> E2E_SECOND_NODE=1 scripts/e2e/run-stack.sh bash -c 'cd frontend && npm run test:e2e'
> ```
>
> 第二個 enrollment token ＋ 第二個 `agentd` 程序（`e2e-node-2`，不同的 `--name`、
> **不同的 state 目錄、不同的 workspace root**）。
> **一台機器上跑兩個 node 是合法的**——node 是一個 `agentd` 實例不是一台實體機器，
> 而這正好也驗到「跨 node 綁定」不依賴機器邊界。
>
> **為什麼是 opt-in 而不是預設**：一般 P2／P3 stack 維持原本單 Node 的形狀；
> V2 雙旗標完整套組才明確打開第二台。檔案 E2E 會依名稱選擇有完整 fixtures 的
> `e2e-node`，所以兩台的上線順序不再讓既有回歸變得不確定。
>
> **兩台的 workspace root 要刻意不同**（例如 `/tmp/e2e-ws-a` 與 `/tmp/e2e-ws-b`），
> 這樣「跨 node 綁定」驗到的是真的跨機器語意，不是同一份內容的兩個掛載點。

一條主線，刻意包含一次拒絕與一次「不受影響」：

```text
登入(Admin) → /projects 空狀態 → 建立 Project "demo"
  → 綁定 e2e-node:/tmp/e2e-ws-a（主要）
  → 綁定 e2e-node-2:/tmp/e2e-ws-b        ← E2E_SECOND_NODE=1，內容刻意與 a 不同
  → Overview 顯示兩列，兩台機器的線上狀態正確
  → 從第一列〔開 Session〕→ 對話框預填 → 建立
  → Activity 出現 session.started
  → 另開一個 Ad-hoc Session（不選 Project）
  → Activity 仍然只有一筆（Ad-hoc 不入任何 Project）
  → 停用 e2e-node 的 root → 重整 → 該列變 root_disabled 且〔開 Session〕停用
  → 直接 POST 建立 Session（繞過 UI）→ WORKSPACE_OUTSIDE_ALLOWED_ROOT
  → 解綁 e2e-node-2 → 第一個 Session 仍在跑、terminal 仍可輸入
  → 登出 → 以 Viewer 登入 → /projects 看得到 → Activity 的 actor 是「—」
```

Viewer 那一段是**必要**的，不是加分項：它是 `00-…md` D5 唯一的端到端證據。

## 3. 旗標關閉回歸套組（`PJ-07` 的核心）

這是「既有功能都要保留」這句話的可執行形式。
`CLIORA_PROJECTS_ENABLED=false`（**預設值**）時：

| 檢查 | 方法 | 基線 |
|---|---|---|
| API 表面 | `scripts/pj/openapi_diff.py` 對 B1 | 只允許：新增路徑（全部 404）、既有回應的**可選**新增欄位、既有請求的**可選**新增欄位。不允許欄位移除／改名／型別變更／必填性變更（`04-…md` §2.3） |
| 路由集合 | 旗標開／關下 `mounted_routes()` 相同 | B5 |
| 新路徑全 404 | 七條各一次 | — |
| Protocol | `make contract` 全綠且 `contracts/` 無 diff | — |
| Daemon | `make integration` | — |
| 六個既有路由可直達 | e2e 逐一造訪 | — |
| 導覽外觀 | 截圖 × 三角色 | B3 |
| Session 全生命週期 | 建立 → 操作 → 重整重連 → 接手 writer → 終止 | — |
| 檔案面 | 瀏覽、搜尋、預覽、圖片投放、一般上傳（含 `FILE_EXISTS` 拒絕） | — |
| System terminal | 開啟、sudo 姿態、單一 live shell 限制 | — |
| Tunnel | 開啟、狀態、關閉 | — |
| RBAC | 三角色 × 既有 16 動作 | B4 |
| DB schema | `pg_dump --schema-only` 既有表逐欄比對 | B2 |

**在 CI 裡跑兩次**：一次 `CLIORA_PROJECTS_ENABLED=true`（功能測試），
一次 `false`（回歸套組）。不是抽樣，是整套。

> **兩個旗標各自獨立**的驗證（`PROJECTS_ENABLED=true` ＋ `AGENT_RUNS_ENABLED=false`）
> 在 V2.2 才有意義——本期沒有 `agent_runs_enabled` 這個設定（`04-…md` §2.1）。
> 這一條要寫在 `07-…md` 的移交欄，否則 V2.2 開工時會以為它已經被驗過。

## 4. 兩個 gate

放在 `scripts/pj/`，形狀照 `scripts/fu/evidence.sh`。

| Gate | 守什麼 | 怎麼守 |
|---|---|---|
| `GATE-PJ-NO-WIRE` | 本期不碰 daemon、contract、ws、檔案面、terminal、deploy | `git diff --name-only origin/v2...HEAD` 不得命中 `^daemon/`、`^contracts/`、`^backend/app/api/ws/`、`^backend/app/services/(files\|terminal_relay\|terminal_queue\|tunnels\|integrations\|node_update)\.py$`、`^deploy/`、`^frontend/src/(protocol\|monaco)/` |
| `GATE-PJ-FLAG-OFF` | 旗標關閉時新路徑全 404、`features` 為空 | 起一個 `projects_enabled=false` 的 app，對七條路徑各發一次請求斷言 404，並斷言 `/api/auth/me` 的 `features == []` |

`scripts/pj/evidence.sh` 把兩個 gate ＋ §2 的每一組測試串成一次可貼上的輸出，
末尾印「N 道通過、M 失敗、K 筆 skip（附理由）」。**skip 必須帶理由**，
沿用 `plan/15` 的既有做法：一筆誠實的 skip 比一個假裝跑過的綠燈有用。

## 5. 出口條件

**七條，全部通過才取得合併提案資格。**
（源自 `research/02/10` §2.1，其中第 1 與第 4 條依程式碼事實改寫，見 `README.md` 的差異表。）

1. 建立一個 Project（驗收素材：`run-stack.sh` 的合成 workspace，**不是 Traqora**，`00-…md` D13），
   綁定**兩個不同 Node** 上的 workspace，
   Project 頁面正確顯示兩者的 node 線上狀態，**且 `node_offline` 與 `root_disabled`
   兩種不可用在畫面上分得出來**。
   > **已知缺口**：第三種（路徑已不存在）本期偵測不到，因為那需要問 node 而本期不動
   > protocol。使用者會在建立 Session 時拿到 daemon 的既有錯誤——與今天手動輸入一個
   > 不存在的路徑的行為完全一樣。這是**被切開的一半**，不是漏掉的一項（`08-…md` M-PJ-04）。
2. 從 Project 建立的 Session 出現在該 Project 時間軸；同時建立的 Ad-hoc Session
   **不出現在任何 Project 的時間軸**。
3. 解綁 workspace 不影響進行中的 Session（狀態、terminal、檔案面都不變）。
4. 移除 Node（soft delete）→ Project 頁面的綁定列消失、Project 存活、
   **`project_workspaces` 那一列仍在**；重新啟用該 node 後它回來。
5. 綁定一條「曾經合法但 root 已停用」的路徑後，用它建 Session 被拒
   （**重驗證，不信任綁定表**），錯誤碼是既有的 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`。
6. 旗標關閉：§3 的完整回歸套組全綠，導覽退回 `PJ-00` 的 B3 基線，`/api/projects*` 404。
7. `pg_dump --schema-only` 的 diff 只有預期的三張表 ＋ 四個索引 ＋ 一個 `ALTER`；
   既有表逐欄比對無變化。

外加兩條本期新增的（它們是 `00-…md` §1 判準 6、7 的落點）：

8. 給了 `project_id` 但 workspace 不屬於該 Project 的建立請求回 **400 而不是靜默忽略**，
   且**沒有 session 列被建立**。
9. Viewer 看得到 `/projects` 與時間軸但看不到任何 actor 名字；
   `POST /api/projects` 得到 403 且 `authz.denied` 有一筆。

## 6. 安全審查：為什麼本期不觸發（而這句話本身要寫下來）

`research/02/10` §6 的四個觸發條件，逐條回答：

| 觸發條件 | 本期 | 說明 |
|---|---|---|
| 新增或改變**授權輸入** | ❌ | 新增兩個動作，但授權的**輸入**沒變：仍然是「使用者的角色」＋「`authorize_workspace()` 對 node 的 enabled roots」。沒有任何新的東西被信任 |
| 新增**寫入路徑或新的儲存面** | ⚠️ 部分 | 三張新表是 Central 自己的資料庫，**不是 node 上的儲存面**。對 workspace 的寫入路徑一條都沒新增（ADR 0024／0026 完全不被觸碰） |
| 新增在 node 上**執行程序**的能力 | ❌ | 一行都沒有 |
| 新增**憑證或機密流** | ❌ | 一個都沒有 |

**結論：本期不產出 `docs/security-review-*.md`。**

但有三件事要在 `PJ-08` 的 release note 裡明說，因為它們是「不觸發」的邊界：

1. **`project.view` 是三個角色都持有的新讀取面。** 它讓 Viewer 看得到專案名稱、
   描述、綁定的 node 名稱與**絕對路徑**。今天 Viewer 已經看得到 node 名稱
   （`node.view`）與 session 的 workspace 路徑（`session.view`），所以這不是新的資訊類別——
   **但它是一個新的聚合視角**，而聚合本身有時就是揭露。這句話要寫下來。
2. **時間軸的 actor 遮蔽是這一期唯一的授權設計**，而它是既有裁決的延伸（`00-…md` D5）。
   它的測試在 §2.1 與 §2.5，兩層都有。
3. **綁定表不是授權**（`00-…md` D3）。這是紅線 2 在新資料結構上的適用，
   `WorkspaceFavorite` 已經是同一個形狀的第一個實例。

> V2.1 的 Session token 會**必然**觸發第四條，V2.2 的無人值守執行會觸發第一、二、三條，
> V2.3 同時觸發三條——那是 V2 風險最高的一次。本期不觸發是因為本期刻意什麼都沒碰
> （`00-…md` D0），不是因為標準變寬了。

## 7. `PJ-08` — 收尾

1. `07-…md` 更新：實際跑過的指令、輸出位置、環境事實、**下一輪從哪裡接手**。
2. `docs/release-note-project-layer.md`：第一段就寫 §6 的第 1 點
   （`project.view` 的新聚合視角），不是附註。附上新環境變數
   `CLIORA_PROJECTS_ENABLED`（預設 `false`）與升級後的預設行為（什麼都不變）。
3. `traceability/requirements.json` 的五筆 `FR-PROJECT-*` 從 `proposed` 翻成 `active`，
   `links.json` 補齊 `verified_by`，`scripts/trace render --write`；
   `make traceability`（validate ＋ selectors ＋ coverage `--scope all --strict` ＋ baseline ＋ test）全綠。
   **順序理由見 `01-…md` §6.1**——在此之前翻成 active 會讓 coverage 直接紅。
4. **提出合併請求並停下來等人決定。**

## 8. 合併回 `dev`

> **一律由人工確認。** 自動化（含 CI 與 agent）**不得**發起或完成這個合併，
> 即使所有出口條件都是綠的（`research/02/10` §7）。

「客觀條件通過」與「可以合併了」是兩件事。前者是機器能回答的，後者不是——
它還包含時機、其他分支的狀態、要不要先等某個量測結果。
**條件全綠只是取得提案資格，不是核准。**

操作規則：

1. 階段工作以正常 PR 進 `v2`。
2. §5 的九條出口條件與 §3 的回歸套組全部通過 → **在 PR 或 issue 上提出合併請求**，附證據。
3. 由人審閱後決定合併時機。沒有自動合併、沒有排程合併、沒有「條件綠了就 merge」的 CI job。
4. 合併後在 `07-…md` 記錄合併的 commit 與日期。
</content>
