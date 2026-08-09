# 00 — 執行總控（V2.0 專案基座）

Ticket 前綴 `PJ-`。上游規劃：[`research/02/02-phase-v20-project-foundation.md`](../../research/02/02-phase-v20-project-foundation.md)。

## 1. 成功定義

**要交付的：** 一個 Admin 可以在平台上建立一個 Project，把散落在**兩台不同 Node** 上的
workspace 綁上去，從 Project 頁面看到那兩台機器現在是不是在線，從那裡開一個 Session，
然後在這個 Project 的時間軸上看到剛才發生的事。

**其餘一律不做。** 任務、看板、Agent、機密、交付——那是 V2.1 之後的事（§2）。

**不得弄壞的六件事：**

1. **旗標關閉時，系統與升級前逐位元組一致。** 不是「差不多一樣」：OpenAPI schema 只允許
   新增路徑與既有回應的**可選新增欄位**，`pg_dump --schema-only` 的既有表逐欄無變化，
   導覽截圖比對相同（`06-…md` §3）。
2. **`authorize_workspace()` 只有一份實作。** 綁定用它、建立 Session 用它，
   `services/favorites.py` 已經是這個模式的第一個實例，本期是第二個。不得複製一份路徑檢查。
3. **既有 16 個 RBAC 動作的角色歸屬不變。** 只新增兩個，不改任何一個既有動作屬於誰。
4. **Viewer 仍然是唯讀角色。** 它拿到 `project.view`，不拿 `project.manage`。
5. **`audit.view` 守住的東西不因為 V2.0 而外流。** Project 時間軸上的 actor 依同一個動作遮蔽
   （D5）。
6. **Ad-hoc Session 仍然是產品的一部分。** `terminal_sessions.project_id` 永遠 nullable，
   沒有任何路徑會替一個沒有指定 Project 的 Session 推論出一個（D10）。

成功的判準是以下八項，每一項都要有可貼上的輸出（`06-…md` §3）：

1. 建立一個 Project（**驗收素材：`run-stack.sh` 的合成 workspace，不是 Traqora**——見下），綁定**兩個不同 Node** 上的 workspace，
   Project 頁面顯示兩者的 node 線上狀態，而且**兩種不可用分得出來**：node 離線、root 已停用。
   （第三種「路徑已不存在」本期偵測不到——那需要一次 `filesystem.*` 往返而本期不動 protocol。
   這是**被切開的一半**不是漏掉的一項，見 `06-…md` §5 出口條件 1 的但書與 `08-…md` M-PJ-04。）
2. 從 Project 建立的 Session 出現在該 Project 的時間軸；同時間建立的 Ad-hoc Session
   **不出現在任何 Project 的時間軸**。
3. 解綁一個 workspace，正在跑的 Session **不受任何影響**（狀態、terminal、檔案面都不變）。
4. Node 被移除（soft delete）後，Project 頁面的綁定列消失，Project 本身存活；
   **DB 裡那一列仍在**，而且重新啟用該 node 後它會回來（D4）。
5. 綁定一條「曾經合法但 root 已被停用」的路徑後，用它建立 Session **被拒**，
   錯誤碼是既有的 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`（不新增一個同義的新碼）。
6. 給了 `project_id` 但 workspace 不屬於該 Project 的建立請求回 **400 而不是靜默忽略**。
7. 一個 Viewer 看得到 `/projects` 與時間軸，看不到任何 actor 名字；
   直接呼叫 `POST /api/projects` 得到 403，且 `authz.denied` 有一筆。
8. `CLIORA_PROJECTS_ENABLED=false` 時：`/api/projects*` 全數 404、導覽退回升級前的樣子、
   完整 V1 回歸（`make check` ＋ `make test-db` ＋ `make integration` ＋ `make e2e`）全綠。

## 2. 範圍

### 納入

- `PJ-00` **基線擷取與 M8 量測**（閘門，動任何程式碼之前）。
- `PJ-01` 需求變更：ADR 0027、`research/prd.md` 的 Project 章節、
  `.agent/skills/cliora-project-context/SKILL.md` 範圍句修訂、`traceability/requirements.json` 註冊。
- `PJ-02` 資料層：migration `0021`（`projects`、`project_workspaces`、`activity_events`、
  `terminal_sessions.project_id`）。
- `PJ-03` RBAC：`project.view`／`project.manage`、seed migration `0022`、`dto.ts` 的 `ACTION_*`、
  `docs/permission-matrix.md` **重新產生**。
- `PJ-04` Project API：七條端點、五個新錯誤碼、五個新稽核動作、`ROUTE_ACTIONS` 七列。
- `PJ-05` Session 關聯：`POST /api/sessions` 的 optional `project_id`、`GET` 的篩選、
  `UserResponse.features`、旗標的三個強制點。
- `PJ-06` 前端：導覽分組、`/projects` 列表、`/projects/:id` 總覽、Session 建立表單的 Project 欄位。
- `PJ-07` 驗證與證據：新測試、旗標關閉回歸套組、`scripts/pj/evidence.sh`。
- `PJ-08` Exit gate：`07-…md` 更新、release note、合併提案（**停下來等人決定**）。

### 不納入

以下每一項都是**被上游規劃明確排除**或**被本期的形狀排除**，不是能力不足：

- **任務、Epic、User Story、看板、藍圖。** V2.1（`research/02/03-…md`）。
- **`.cliora/` 投影、情境包、`cliora` CLI、Session Token。** V2.1。它們需要動 daemon，本期不動。
- **Agent Runner、run、機密、隔離目錄、交付。** V2.2–V2.4。
- **`project_members`。** V2.0 用既有三角色 ＋ `owner_user_id` 就夠。專案級成員制在有第二個團隊
  真的需要時再做，屆時它是一張新表加一層授權，不會回頭改動本期任何東西。
- **Project 的刪除。** 只有 `archive`（D9）。
- **從 Project 頁面「一鍵開 Session」的完整流程。** 本期只做「Session 建立表單多一個 optional
  的 Project 下拉」＋「綁定列上的〔開 Session〕按鈕預填 node 與 path」。完整流程要等 V2.1
  有 Task 可以選。
- **`default_node_id`／`default_runtime` 欄位。** 見 `02-…md` §2.1。
- **任何 protocol 訊息、任何 daemon 變更、任何 contract 版本變更。**
- **任何對 allowed root 的讀寫。** 本期一行檔案存取都沒有。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **本期在 V2 的哪一格** | V2 的骨架階段：新增資料與畫面，**不觸碰 daemon、protocol、檔案面、terminal、tunnel**。三張新表、一個 nullable FK 欄、兩個動作、七條 API、兩個畫面 | 之後每個階段都會動一次安全姿態（V2.2 無人值守執行、V2.3 機密與 git 寫入、V2.4 對外副作用）。那些階段需要一個**已知良好且已經含有 V2 資料模型**的基準去回歸。把基座和第一次姿態變更綁在同一期，出問題時分不出是哪一個造成的 |
| D1 | **旗標擋在 handler，不是 mount** | router **無條件** `include_router`；每條 `/api/projects*` 掛一個 `require_projects_enabled` 依賴，旗標關閉時 `raise HTTPException(404)`。`ROUTE_ACTIONS` 無條件列出七條 | `tests/test_authz.py:mounted_routes()` 讀的是 `app.routes`，那是**匯入期**就固定的清單，而 `test_every_mounted_route_is_in_the_matrix` 雙向斷言。條件掛載會讓這條測試的結果取決於跑測試時的 `CLIORA_PROJECTS_ENABLED`——綠或紅由 `.env` 決定，那不叫 gate。**被否決**：條件掛載 ＋ 在測試裡強制開旗標（那等於承認矩陣只在一種設定下成立，而部署跑的是另一種）；用 `APIRouter(include_in_schema=False)`（藏起 OpenAPI 不等於路由不存在，反而讓 §1 判準 8 的 schema diff 變得無法驗證） |
| D2 | **前端怎麼知道旗標** | `UserResponse` 新增 `features: list[str]`，旗標開時含 `"projects"`，關時是空陣列。`/api/auth/me` 與登入回應同時攜帶 | 前端目前**完全沒有**得知伺服器旗標的管道：`/api/auth/me` 只回 `permissions`，而 `permissions` 無法承載這件事——seed migration 是無條件跑的，旗標關閉時 Admin 一樣持有 `project.manage`。形狀刻意與 `permissions` 一致（字串陣列），V2.2 加 `"agent_runs"` 時是一個字串而不是一次改版。**被否決**：新增 `GET /api/features`（多一條路徑、多一次啟動往返，而導覽要在它回來之前先渲染一次，就會閃一下）；`VITE_PROJECTS_ENABLED` 建置期變數（兩個真實來源，而且改旗標要重新 build 前端）；由 `/api/projects` 的 404 反推（導覽的第一次渲染早於任何 API 呼叫） |
| D3 | **綁定驗證重用 `sessions.authorize_workspace()`** | 綁定時呼叫它；**每一次以綁定路徑發起的操作再呼叫一次**。不新增任何路徑檢查邏輯 | `WorkspaceFavorite` 的 docstring 已經把這條寫死：「A shortcut, never an authorization. …a favorite that was legal when saved may not be now (SEC-001)。」`project_workspaces` 是同一種東西的第二個實例，措辭直接沿用。**兩份實作最後一定會分歧**，而分歧的那一天是安全事件而不是 bug |
| D4 | **Node 移除時綁定列怎麼消失** | 外鍵 `ON DELETE CASCADE`（安全網），但**正常路徑是服務層過濾 `nodes.deleted_at IS NULL`**。UI 上綁定列消失，DB 列仍在 | Node 的移除是 **soft delete**（ADR 0011）。`0011_workspace_favorites.py` 的註解已經記過這個教訓並選了同一個做法。上游規劃的出口條件 4 寫「綁定列一起消失」，若照字面實作成 CASCADE 會**驗不出來**（因為 CASCADE 根本不會觸發）。**附帶好處**：重新啟用一台被誤刪的 node，綁定會回來 |
| D5 | **Activity Timeline 的 actor 可見性** | 沒有 `audit.view` 的呼叫者拿到的每一列 `actor_id`／`actor_name` 為 `null`，並帶 `actors_hidden: true` | 這**不是新裁決，是既有裁決的適用**：`services/dashboard.py:project_for` 已經為 Dashboard 的近期活動做過同一件事，理由是「知道一台 node 被移除了是運維情境，知道**誰**移除它是稽核紀錄（FR-AUTH-002）」。Project 時間軸的守門動作是 `project.view`——**三個角色都持有**。照抄一個帶 actor 的時間軸等於把 P4 特意關上的門重新打開，而且是在一個沒人會去看的地方。**實作上直接呼叫同一個形狀的函式**，並在測試裡斷言 Viewer 拿到的是 `null` |
| D6 | **`activity_events` 與 `audit_logs` 是兩件事** | 都寫。`audit_logs`：誰做了什麼，全域、`audit.view` 才看得到 metadata、既有保留期。`activity_events`：**這個專案上發生了什麼**，`project.view` 可見、隨 Project 存活、無獨立保留期 | 判準是 ADR 0024 W2 的那個問題——**誰清這個、什麼時候清**。兩者的答案不同：audit 是合規紀錄有既有的保留期；activity 是產品內容，Project 在就在，Project 被封存也在（歷史不因為封存而消失）。**被否決**：只寫 audit 然後把時間軸做成 audit 查詢（那需要把 `audit.view` 下放給 Viewer，或做一個平行的去識別查詢層——前者是權限變更，後者就是這張表但少了 `project_id` 索引）；只寫 activity（稽核會缺一段） |
| D7 | **RBAC 詞彙與強制點同一個 PR** | `PJ-03` 與 `PJ-04` 合併為一次提交。`UNENFORCED_ACTIONS` 保持空集合 | `test_every_action_is_enforced_somewhere` 是**對 `backend/app/**/*.py` 的文字掃描**：`PROJECT_VIEW` 一寫進 `rbac.py` 而別處沒出現，測試立刻紅；反過來，先加進 `UNENFORCED_ACTIONS` 再移除，測試在第二步也會紅。`research/02/01` D13 明寫「不要為了先 merge 而往裡面加東西」。**這不是偏好，是這條測試的形狀決定的** |
| D8 | **不做 `project_members`** | V2.0 用既有三角色 ＋ `projects.owner_user_id`。`project.view` 的持有者看得到**所有** Project | 與 Node 的既有做法一致（`node.view` 的持有者看得到全部 node）。專案級成員制是一張新表加一層資源授權，**它不會回頭改動本期任何欄位或任何端點的形狀**——所以現在做只是提早付款。**代價要寫在 ADR**：多團隊共用一個 Cliora 時，A 團隊看得到 B 團隊的專案名稱與時間軸 |
| D9 | **Project 沒有刪除，只有封存** | `status` 三值 `active`／`paused`／`archived`。沒有 `DELETE /api/projects/{id}` | `activity_events` 是歷史，`terminal_sessions.project_id` 指向它。刪除要嘛留下孤兒、要嘛連帶刪掉一段真的發生過的歷史。封存的語意夠用：**封存後不得建立新 Session、不得新增綁定，既有的一律不動**。`ON DELETE SET NULL` 保留在 schema 裡當安全網，但沒有任何 API 會觸發它 |
| D10 | **`terminal_sessions.project_id` 由建立者指定，平台不推論** | 給了就驗（workspace 必須是該 Project 的綁定之一，不符回 400）；沒給就是 Ad-hoc，**永遠不從 workspace 反查 Project 幫他填** | 一個 workspace 綁到兩個 Project 是允許的，所以反查沒有唯一解。更重要的是：**Ad-hoc Session 是產品的一部分**（`version2.md` §15、D12），一個會自動歸屬的欄位會讓「這是不是 Ad-hoc」變成平台的判斷而不是使用者的意思。**被否決**：唯一綁定時自動填（那會讓行為取決於別人有沒有綁第二個專案） |
| D11 | **導覽是重新分組，不是搬家** | 三組 `Projects`／`Sessions`／`Infrastructure`；**既有路由路徑一律不變**；分組標題是**無縮排的分隔線 ＋ 小標籤，子項不縮排**；sidebar `--layout-sidebar: 208px` **不得加寬** | 路徑不變是為了書籤與既有的 e2e。**分隔線版本已於 2026-08-08 實測選定**：最寬 `Integrations` 147px、餘裕 61px，而縮排版本是 159px／49px——**兩者都通過**，選前者是因為側欄還會再長（V2.2 要加 `Agents`），縮排讓每個子項都付 12px（`05-…md` §1.3、`08-…md` §1）。不加寬是因為 `plan/09` 把 280→208 的整個理由就是「空間讓給中央區」，而 `plan/08`／`research/style.md` §12／§18 是同一個方向——加寬會一次推翻三份決定 |
| D12 | **這一期不碰的東西** | `daemon/`、`contracts/`、`backend/app/api/ws/`、`backend/app/services/{files,terminal_relay,terminal_queue,tunnels,integrations,node_update}.py`、`deploy/`、`frontend/src/{protocol,monaco,composables/useFileTree,composables/useTerminalSession}` | 判準寫死：若 diff 出現在上述任一處，就是走錯路了。`GATE-PJ-NO-WIRE`（`06-…md` §4）以 `git diff --name-only` 斷言它 |
| D13 | **驗收素材：本期不用 Traqora** | 用 `scripts/e2e/run-stack.sh` 的合成 workspace，兩台 node 各一個**內容不同**的 root（`E2E_SECOND_NODE=1`，`06-…md` §2.5） | D30 定 Traqora 為 V2 的驗收素材，但它的價值要更晚才兌現：真實待辦撐不撐得住六車道是 **V2.1**；`base_branch: main` 逼出「不是寫死的 `master`」與 `p4-` 分支慣例不撞 `cliora/` 命名空間是 **V2.3**；第一個真的 PR 是 **V2.4**。**V2.0 一行程式碼都不讀**，連 `.cliora/` 都不寫——在這裡用它，得到的只是一個叫 traqora 的目錄名稱。合成 workspace 反而更好：可重現、CI 跑同一份、而且兩台 node 的內容可以刻意不同，驗到的才是真的跨機器語意而不是同一份內容的兩個掛載點。**已回寫 `research/02/01` D30 的階段表** |

## 4. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `PJ-00` | 基線擷取（OpenAPI、`pg_dump`、導覽截圖）與 M8 量測 | — |
| | `PJ-01` | ADR 0027、PRD 增訂、skill 範圍句、traceability 註冊 | `PJ-00` 的 M8 |
| **1（資料層）** | `PJ-02` | migration `0021`、三張新表＋一個 ALTER、SQLAlchemy 模型、上下行演練 | `PJ-01` 核准 |
| **2（Central）** | `PJ-03`＋`PJ-04` | RBAC 詞彙 ＋ seed `0022` ＋ 七條 API ＋ 錯誤碼 ＋ 稽核（**同一個 PR**，D7） | `PJ-02` |
| | `PJ-05` | Session 的 optional `project_id`、`features` 欄位、旗標三個強制點 | `PJ-04` |
| **3（前端）** | `PJ-06` | 導覽分組、`/projects`、`/projects/:id`、Session 表單 | `PJ-05` |
| **4（收尾）** | `PJ-07` | 測試、旗標關閉回歸套組、`scripts/pj/evidence.sh` | `PJ-02`–`PJ-06` |
| | `PJ-08` | `07-…md` 更新、release note、**合併提案並停下來** | `PJ-07` |

**閘門一：`PJ-00` 完成前不得動任何程式碼。** 出口條件裡有三條是「與升級前 diff」，
而升級前的快照**改完就再也取不到**。這一條不是流程潔癖，是可驗證性的前提。

**閘門二：`PJ-01` 核准前不得動 `backend/` 與 `frontend/`。**
理由與前四期相同（`plan/12`–`plan/15` 的同一條）：
`.agent/skills/cliora-project-context/SKILL.md` 明文寫著「Do not introduce … Git automation,
**task routing**, or multi-agent orchestration without a requirements change」。
V2 兩者都碰。**需求變更是第一張票，不是事後補件**，否則後面每一張票都在違反這個 repo
自己的規則，而 `make check` 內的 traceability gate 也會擋下來。

**`PJ-06` 可以晚於 `PJ-05`。** 有能力但沒有入口是安全的方向，反過來不是。

## 5. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| **旗標關閉時的回歸沒有真的跑過** | 「我們有這個旗標」但沒人在關閉狀態下跑完整套組 | `06-…md` §3 的回歸套組是 `PJ-07` 的**必要**內容，而且它在 CI 裡是**第二次**跑測試（`CLIORA_PROJECTS_ENABLED=false`）。不是抽樣，是整套 |
| **導覽重整讓既有使用者找不到 Nodes** | 「Nodes 跑到哪去了」 | 路由不變；`Infrastructure` 群組**預設展開且不可收合**（本期不做收合狀態的持久化——那是一個 localStorage 的狀態機，為了一個八列的側欄不值得）；e2e 逐一造訪六個舊路由 |
| ~~**sidebar 208px 不夠**~~ | ~~標籤截斷或換行~~ | **已量掉（2026-08-08）**：採用的分隔線版本最寬 147px、餘裕 61px（`08-…md` §1）。V2.2 要加 `Agents` 時仍要重量一次——那是 `Infrastructure` 的第六個子項，而 `plan/09` 的高度規則也要跟著複驗 |
| **`activity_events` 無界成長** | 一個活躍專案跑一年之後時間軸查詢變慢 | 本期就建 `(project_id, occurred_at DESC)` 索引並**分頁**（預設 50、上限 200，沿用 `/api/sessions` 的形狀）。保留期**刻意不做**（D6）：它是產品內容不是診斷。成長速率是 M-PJ-02（`08-…md`），有數字之後再決定要不要封存策略 |
| **Project 與 workspace 多對多造成「這個 session 屬於哪個專案」歧義** | 同一個路徑綁在兩個專案上 | D10：由建立者明確指定，平台不推論。UI 上當一個 workspace 有多個 Project 綁定時，下拉列出全部並要求選一個 |
| **`project.manage` 只給 Admin，Developer 建不了專案** | 「為什麼我不能建專案」 | 這是 D13 的裁決，不是疏漏。處置是**文案**：`/projects` 的空狀態對非 Admin 顯示「還沒有專案。請 Admin 建立，或直接從 Sessions 建立 Ad-hoc Session」——這句話同時教了兩件事 |
| **有人把 `activity_events` 當成 audit 的替代品** | 之後的階段往 `payload` 裡塞 actor 細節或機密 | `audit.FORBIDDEN_METADATA_KEYS` 的同一份清單套用到 `activity_events.payload` 的寫入路徑，並配一條測試。D6 的兩欄表要寫進 ADR 0027 |
| **`features` 欄位被當成權限用** | 前端出現 `if (features.includes('projects'))` 去決定「可不可以」 | `features` 回答的是「這個部署有沒有這個功能」，`permissions` 回答「這個人可不可以」。兩者在 UI 上是 AND，而**伺服器兩個都會再檢查一次**。`04-…md` §3 的註解要把這句寫在型別定義上 |
</content>
