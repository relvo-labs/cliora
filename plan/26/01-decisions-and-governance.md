# 01 — 決策與治理（D92–D111）

決策編號沿用全域序列。`plan/19` 用到 D36，`research/03` 用到 D58，
`plan/23`–`plan/25` 用到 **D91**。本期從 **D92** 開始。

ADR 編號沿用 `docs/adr/`：0035–0039 與 0041 已用，**0040 與 0042 是空號**，
本期用掉這兩個。`0043` 已由 [`research/03/11`](../../research/03/11-requirement-traceability.md) §3
指派給 `beta.2` 的 provider ingestion，**不得在本期佔用**。

每一項的格式是：**裁決 → 證據 → 後果 → 不同意的話會怎樣**。
最後一段是重點——它記錄的是**當時放棄了什麼**，而那是三個月後唯一有人想知道的事。

---

## A 類（擋開工，八項）—— ☑ **2026-08-23 全部裁決，全部採納**

完整論證在 [`00`](./00-execution-plan.md) §0.1，裁決單在
[`12`](./12-implementation-status.md) §1。這裡留裁決、後果與反面。

**「反面」（不同意的話會怎樣）在裁決之後仍然保留**，而且比裁決之前更重要：
它是日後有人想推翻某一項時，唯一能告訴他「當年換掉的是什麼」的東西。

### ☑ D92 — attention 兩相位求值；`tasks.attention_primary` 永不建立

**裁決**：`derive_attention()` 分兩相位。相位 A 在 SQL 產生六級 ＋ queued 候選集；
相位 B 在 Python 用 `NodeConnectionRegistry` 解出 `no_eligible_runner` 與
`assigned_runner_offline`。**上游 [`04`](../../research/03/04-phase-p1-view-and-read-model.md) §5
提議的 `tasks.attention_primary` 欄位不進 `0043`，也不進 `0043b`。**

**證據**：`services/runners.py` module docstring 引 ADR 0029 §1
——「a stored copy would be a second answer that can go stale, and this module
deliberately does not create one」；`services/registry.py:80` 是行程內 dict。

**後果**：
- `order_by` allowlist 不含 attention 的這兩級（[`04`](./04-filter-and-query-compiler.md) §4）。
- 相位 B 的成本綁在**佇列長度**而不是卡片數，所以 `PX-24` 的 P95 量測要同時報告
  「200 張卡 / 6 queued」與「200 張卡 / 60 queued」兩組。
- 多 worker 部署下這兩級是 per-process 的 → [`11`](./11-open-measurements.md) 第 2 項。

**不同意的話**：見 [`00`](./00-execution-plan.md) §0.1 D92 末段。簡言之：
撤銷 ADR 0029 §1，或者從產品裡拿掉 My Work 的第五個 section 與兩個 quick filter。

---

### ☑ D93 — 可見專案集合走單一函式；isolation 測「述詞被套用」

**裁決**：`services/work/scope.py::visible_project_ids(session, user)` 是本期唯一決定
「哪些專案」的地方；`GATE-PX-ONE-PROJECT-SCOPE` 用 AST 斷言。
上游 SR-3 第 3 項改寫為「counts 與 items 由同一個 `ProjectScope` 與同一份 filter 編譯結果產生」。

**證據**：`services/rbac.py:92` 的 `_VIEWER_ACTIONS` 含 `PROJECT_VIEW`；
`db/models.py` 無 `project_members`；`services/authz.py` 無 project-scope 函式。

**後果**：SR-3 的簽核文字要明說「本部署模型下無法產生負面案例」。
不可測的那一半進 [`11`](./11-open-measurements.md) 第 1 項。

**不同意的話**：本期先做 per-project membership——新表、新 seed migration、
27 個動作重新想 scope、既有全部授權路徑改寫。那是 `Horizon 3` 的一整期。

---

### ☑ D94 — DTO 大小預算先量再釘

**裁決**：`PX-25` 的第一步是量測，不是實作。門檻 = 量測值 × 1.15，
數字與日期寫進測試 docstring；**上游的 160 KB 不得直接抄**。
同一支測試順便重量 `BoardCardDTO`，斷言仍是 **89,251 ± 2%**。

**證據**：`repositories/tasks.py:45` 記的是 89,251 / 90,000（99.2%），
而上游 160 KB 是從已經過期的 74 KB 推出來的。

**後果**：若量測值 > 200 KB，先砍欄位再寫 endpoint；砍了哪一個記在
[`12`](./12-implementation-status.md) §2。候選的砍除順序在
[`03`](./03-read-model-and-attention.md) §6。

**不同意的話**：預算若過鬆，這個測試從第一天起不守任何東西；
若過緊，會在 endpoint 與卡片元件都寫完之後才發現要砍欄位。

---

### ☑ D95 — 只輪詢 counts；beta.1 不開瀏覽器 WebSocket

**裁決**：`work-counts` 20 秒輪詢、`document.hidden` 暫停、counts 有 delta 才失效 items。
Drawer 開著時 conversation 5 秒輪詢。**不新增 central→browser 的 WS 通道。**

**證據**：`frontend/src/api/client.ts` 只鑄造 terminal 票券；
`views/ProjectDetailView.vue:108` 的 `reloadTasks()` 只在 mutation 後被呼叫。

**後果**：`work-counts` 是本期最熱的 endpoint，必須是單一查詢
（[`05`](./05-work-items-and-view-api.md) §3）。20 秒是可調的
→ [`11`](./11-open-measurements.md) 第 3 項。

**不同意的話**：新的認證推播通道 = 新的信任邊界 = SR-3 範圍上升一級，
與 `research/03/01` §1.4 把 provider sync 移到 `beta.2` 的理由逐字相同。

---

### ☑ D96 — bulk update 逐張走 `TaskService.update()`

**裁決**：`POST /api/tasks/bulk-update` 在一個交易裡逐張呼叫 `TaskService.update()`。
不寫第二條 stage 寫入路徑。上限先訂 100，`PX-25` 量交易 P95 後可下修。

**證據（已更正，見下）**：`services/done_gate.py:16`「There is one entrance」；
`services/activity.py:246` 是 `alpha.3` 唯一的 knowledge 入列點。

> ⚠️ **本計畫第一版把這條寫得太強了。** 我寫過
> 「`TaskService.update()` 是 `task.stage` 的唯一寫入點，而且有 AST gate 守著」。
> 兩半都不精確：
>
> ```bash
> # scripts/dv/gates.sh:106 —— 它是一個 grep，不是 AST；
> # 而且只掃一個檔案、只禁一個字串
> absent "GATE-DV-SINGLE-DONE-PATH" "a run advanced a card into done" \
>   -E '\.stage\s*=\s*["'"'"']done["'"'"']' backend/app/services/runs.py
> ```
>
> 實際上有**三個**地方寫 `task.stage`：
> `run_reaper.py:176`、`run_reaper.py:246`、`runs.py:1510`——全部寫 `'blocked'`。
> gate 掃不到前兩個（不同檔案），也不禁 `'blocked'`（不同字串）。
>
> **精確的不變式是**：`stage = 'done'` 只能經 `TaskService.update()`，
> 而那由一個只涵蓋 `runs.py` 的 grep 守著。
>
> **這讓 D96 的結論更強而不是更弱**：一個自己寫 `UPDATE tasks SET stage=…` 的
> bulk endpoint **不會被任何 gate 擋下**——`GATE-DV-SINGLE-DONE-PATH` 只看 `runs.py`。
> 所以「逐張走 `TaskService.update()`」是一條**只能靠 code review 維持**的規則，
> 因此 `PX-65` 要新增 `GATE-PX-BULK-USES-UPDATE`（[`10`](./10-verification-and-exit.md) §3）。

**後果**：100 張 ≈ 400 列寫入 ＋ 最多 100 次 Done Gate 評估。
UI 顯示進度與「全部或全不」，**不偷偷放寬成 partial**。

**不同意的話**：唯一的實作形式是繞過 AST 掃描（寫在 `repositories/` 或 raw SQL），
而那正是那個 gate 存在的理由。

---

### ☑ D97 — 不新增 `STAGE_TRANSITION_REFUSED`；DoR 維持警告

**裁決**：machine code 從上游的八個減為七個。Ready transition 在缺 readiness 時
是一個列出缺失項、可以按下去的確認對話框，不是 400。

**證據**：`services/process.py:11`「Definition of Ready and WIP report and do not
refuse」；兩個既有硬拒絕（`TASK_DEPENDENCY_UNSATISFIED`、Done Gate）**都已經**列出
全部未滿足項——那正是上游要求的行為。

**後果**：`PX-30` 的 UI 責任變重：缺失項要能直接點開去補。
這是 [`06`](./06-board-and-backlog.md) §5 的規格。

**不同意的話**：要改 `process_definitions` 的 schema、`ProcessService.effective()`、
`TaskService.update()`，並回答「既有部署預設哪個值」——預設 `true` 會讓所有現存看板
突然開始拒絕寫入。這是**改變 process 語意**，不是加一個錯誤碼。

**這一項與 `plan/25` §2.12 是同一個教訓**：一個沒有 raise 點的 machine code
是文件不是行為，而上一期是實作到一半才發現的。本期在計畫階段刪掉。

---

### ☑ D115 — 新增波次 0：可見價值先行

**裁決**：波次 0 四張 ticket（`PX-17`／`PX-24`／`PX-18`／`PX-38`）跑在**既有** backend 上，
交付「既有看板卡片有 attention 徽章 ＋ 點卡開 Drawer 不離開看板」。
四張都不是拋棄式的；唯一會刪的是 side-car endpoint
（[`05`](./05-work-items-and-view-api.md) §9，由 `PX-25` 負責刪、`PX-28` 斷言刪乾淨）。

**證據**：既有 `BoardCardDTO` 的十六欄已經足以推導**八級 attention 裡的六級**
（`active_run_status`／`waiting_reason`／`blocking_count`／`gates_approved_count`／`updated_at`）。
以及發布史：`alpha.1`／`alpha.2`／`alpha.3` 三次 prerelease，
使用者看到的畫面變化是「六欄看板 → 多一個對話面板 → 多一個 Knowledge 分頁」。

**後果**：波次 0 直接改 `components/project/TaskBoard.vue`
（☑ [D117](#d117) 之後不需要旗標包裹），改動前後各存一份視覺基準，
**diff 是給人審查的材料而不是 gate**。每個波次的可看產出寫進 [`00`](./00-execution-plan.md) §4b。

**不同意的話**：第一個可看的畫面落在波次 3 結束，前面是十張純後端 ticket——
**第四次**把畫面排在最後，而這一輪的論述是「產品體驗重設」。

---

### ~~D116 — 旗標預設在 `beta.1` 出口裁決~~ **（2026-08-23 由 D117 取代）**

原裁決是「dev／staging 預設 `true`，production 在 `PX-66` 裁決」。
**D117 拿掉了旗標本身，所以沒有預設值要裁決。** 原文的論證
（「預設 `false` 就沒有真實使用」是一個循環）**仍然成立，而且是 D117 的理由之一**。

---

### ☑ D117 — UI 不分 V1／V2；`CLIORA_PROJECT_EXPERIENCE_V2` 不建立

**裁決**（2026-08-23，人工確認）：**前端一律以最新為主，不保留舊版並存路徑。**
`CLIORA_PROJECT_EXPERIENCE_V2` **不新增**。
`CLIORA_PROJECTS_ENABLED` 與 `CLIORA_AGENT_RUNS_ENABLED` **不變**——
那兩個是**能力閘門**（有沒有 Project 層、有沒有 Agent），不是 UI 版本。

**證據**：`grep -rn "PROJECT_EXPERIENCE_V2" backend/ frontend/src/` **零結果**——
它從來只存在於規劃文件裡，所以拿掉它的成本是零。

**這件事簡化了什麼**：

| 原本 | 現在 |
|---|---|
| `PX-64` 每一頁「旗標關閉走舊路徑、開啟走新路徑」 | **逐頁替換**。仍然逐頁，但每頁只有一條路徑 |
| `ProjectDetailView.vue` 1515 行留到 `beta.2` | **`PX-64` 完成時刪除**。known limitation 少一條 |
| 波次 0 的改動要包在旗標之後 | 直接改 `TaskBoard.vue` |
| feature flag 矩陣五種組合 | **三種**（`PROJECTS` × `AGENT_RUNS`） |
| 出口條件 14「旗標關閉可回到舊 UI」、39「預設已裁決」 | **兩條都刪**（[`10`](./10-verification-and-exit.md) §11） |
| 視覺回歸的基準是「V1 逐像素不變」 | **替換前後各存一份，diff 是給人審查的材料**，不是 gate |

**逐頁替換仍然逐頁**——理由從「風險隔離」變成「diff 可讀」：
一次換掉八頁的視覺回歸沒有人看得完，而看不完的回歸等於沒有回歸。

**要一起接受的代價：沒有 kill switch。**

原本「新看板出問題就關旗標」這條路不存在了。回滾的唯一路徑是
**回上一個 image ＋ downgrade `0043`**，而 downgrade 會刪掉使用者的 saved view
（[`02`](./02-data-layer.md) §6）。三個緩解：

1. `/projects/:id/tasks/:taskId` **完整頁面保留**（已在禁區清單）——
   新 Drawer 出問題時，卡片仍然打得開。
2. `/board` API **保留一版**（[D118](#d118)）——外部整合不受影響。
3. **[D115](#d115) 的波次 0 因此更重要**：早三個波次拿到回饋，
   是沒有 kill switch 之後唯一剩下的風險控制。

**不同意的話**（維持旗標）：多一個要在五種組合下驗證的維度、
`ProjectDetailView.vue` 再留一個 release window、
以及 D116 原本要面對的那個循環——預設 `false` 就沒有真實使用資料。

---

## B 類（改變某一節，不擋開工）

### D98 — rank 純函式排在波次 1，早於 migration

**裁決**：`PX-61` 從上游的第二段移到波次 1，且必須早於 `PX-22`。

**證據**：`0043` 的 backfill 要對每個 project 依 `ORDER BY updated_at DESC`
產生初始 rank，而那需要 `rebalanced_ranks(count)`。上游把 `PX-61` 排在
[`05`](../../research/03/05-phase-p2-board-and-backlog.md) §6（第二段），
把 `PX-22`（migration）排在 [`04`](../../research/03/04-phase-p1-view-and-read-model.md) §7（第一段）。

**後果**：波次 1 的順序是 `PX-00 → PX-21 → PX-61 → PX-22`。

**不同意的話**：`0043` 的 backfill 得自己寫一份等距 rank 產生器，
於是 repo 裡有兩份，而其中一份沒有 kintra 那三個不變式的測試。

---

### D99 — kintra 的移植：函式體逐字、docstring 翻譯

**裁決**：`../kintra/backend/app/modules/board/ranking.py` 的**函式體與常數逐字移植**；
`tests/unit/test_ranking.py` 與 `tests/integration/test_rank_rebalance.py`
的**案例逐字移植**；**docstring 與註解翻成英文**，保留三個不變式的編號（I1／I2／I3）
與「不以 `'0'` 結尾」的完整理由。落點 `backend/app/services/work/ranking.py`。

**證據**：kintra 的註解是繁體中文，cliora 的 `backend/app/` 全部是英文
（`repositories/tasks.py`、`services/done_gate.py` 等）。

**後果**：新檔案的 module docstring 要有一句「ported from kintra
`app/modules/board/ranking.py`；invariants and test cases are that module's,
prose is ours」，否則下一個讀者無法判斷這是原創還是移植。

**不同意的話（連中文一起貼）**：這個 repo 的 `backend/app/` 出現一個語言不同的檔案，
而語言差異會被讀成「這個檔案不歸我們維護」。

---

### D100 — 新增 `queryCache`，`useAsyncResource` 一行不動

**裁決**：`frontend/src/modules/work/queryCache.ts`（新，目標 250–350 行）
承載 key／快取／失效／optimistic／in-flight 去重／counts 輪詢器。
`composables/useAsyncResource.ts` 進禁區清單。

**證據**：`useAsyncResource` 全檔 78 行（其中 28 行是 `deriveNodeState`），
`useAsyncResource()` 本體 26 行，每次呼叫 `shallowRef(null)` 建立新狀態
——**沒有跨呼叫點的快取可以擴充**。

**後果**：V1 的 12 個 Pinia store 與既有頁面完全不動。
新舊兩套並存是**刻意的**，而 [`09`](./09-frontend-architecture.md) §2 寫了退出條件。

**不同意的話（改造 `useAsyncResource`）**：它有 28 個既有呼叫點與一支測試檔，
其中大多在 `beta.1` **不碰**的畫面上（terminal、session、node、file）。
改造它等於為了一個新模組去動 28 個範圍外的呼叫點——
☑ [D117](#d117) 拿掉的是 UI 的版本承諾，不是「不要動範圍外的東西」這條常識。

---

### D101 — 預設 view 的 seed 有兩個入口

**裁決**：`0043` 的 backfill 為**既有**專案 seed 五個 project view；
`ProjectService.create()` 加一段為**新**專案 seed 同樣五個。
兩處呼叫同一個 `services/work/views.py::seed_default_views(project_id)`。

**五個**：`Active Work`（`is_default`）、`Backlog`、`Waiting for Me`、`Blocked`、`Verification`。

**證據**：上游 [`08`](../../research/03/08-data-model-and-contract.md) §4 只寫了
「每個 project seed 五個 project view」，沒說新專案怎麼辦。

**後果**：`seed_default_views` 必須是冪等的（`ON CONFLICT (name) DO NOTHING`），
因為 migration 與 create 都可能對同一個 project 跑到。

**不同意的話**：`beta.1` 上線後建立的第一個專案，Board 開起來沒有任何 view，
而那個狀態沒有任何測試會看到——既有測試建立的專案都在 migration 之前。

---

### D102 — `is_blocked` 的 dual write 期

**裁決**：使用者路徑（UI／API PATCH）**只寫** `is_blocked`／`blocking_reason`／
`blocking_message`；讀模型兩者都認（`stage='blocked'` → `lifecycle='ready'` ＋ `is_blocked=true`）。

**⚠️ 誰在寫 `stage='blocked'`（本計畫第一版寫錯了）**：不是「舊 UI」，是**平台自己**。

```text
run_reaper.py:176   lease 過期／run 失聯
run_reaper.py:246   重試耗盡
runs.py:1510        24 小時無人回答 question
```

所以 **[D117](#d117) 拿掉舊 UI 之後，dual write 並沒有結束**——
它會持續到 `beta.2` 的 `HD-06` 把這三處改成寫 `is_blocked` 為止。
`HD-06` 的工作內容因此是具體的三個檔案位置，不是一句「拆掉過渡」。

**後果**：**一張卡可能同時 `stage='blocked'` 與 `is_blocked=false`**
（舊 UI 移進 blocked，新 UI 解除阻塞）。讀模型的規則是
**`stage='blocked'` 一律投影成 `is_blocked=true`**，即使欄位是 `false`——
因為舊 UI 的使用者仍然把那一欄當成真相。這條規則有一個單元測試。

**不同意的話**：兩個真相來源在 `beta.1` 期間會產生「我明明解除了阻塞，
它還在 Blocked 欄」的回報，而那是舊看板的欄，不是新讀模型的欄。

---

### D103 — quick filter 只進 URL

**裁決**：quick filter chip 套用後只改 URL（`f=` ＋ base64url），不改 `work_views` 的列；
toolbar 顯示「已修改」＋「另存為…／還原」。URL 超過 1500 字元時退回
「view id ＋ 本機暫存」並在 UI 說明「此篩選未包含在連結中」。

**後果**：`PX-31` 要決定 `f=` 的序列化格式，並有一組
「序列化 → 反序列化 → 深度相等」的 property 測試。

**不同意的話（quick filter 寫回 view）**：一個共用 view 會被任何一個點過 chip 的人改掉，
而那個人不知道自己改了團隊的東西。

---

### D104 — `(project_id, updated_at DESC)` 索引補在 `0043`

**裁決**：`0043` 建 `ix_tasks_project_updated ON tasks(project_id, updated_at DESC)`。

**證據**：`0023_task_board.py:391` 只建了 `ix_tasks_project_stage` 與
`ix_tasks_project_story`；`0039` 加了 `ix_tasks_proposal_item`。
**沒有 `(project_id, updated_at)`** ——而 `_board_select()` 與 `board_cards()`
兩者都是 `ORDER BY Task.updated_at DESC`。

**後果**：這個索引同時服務三件事——現行看板的排序、Done 欄的「近 7 天」、
以及 work-items 的預設 `order_by`。**它是本期唯一一個會讓既有查詢變快的變更**，
所以 `PX-22` 要量它前後的差並記在 `artifacts/px/local/`。

**不同意的話**：Done 欄的「近 7 天」在 348 張已完成卡的專案上是全表掃描，
而那個專案正是最需要這個功能的專案。

---

### D105 — bulk update 的 audit 是一列

**裁決**：一次 bulk update 寫**一列** audit（`actor`、`patch`、**完整 item refs**），
不是 N 列。但 **activity 仍然是 N 列**——因為每張卡的時間軸要看得到自己那一次變更。

**證據**：上游 [`08`](../../research/03/08-data-model-and-contract.md) §7 只說了 audit 那一半。

**後果**：`audit_log` 的 metadata 會有一個最長 100 個 `card_ref` 的陣列。
100 × 8 字元 ≈ 800 bytes，可接受。**item refs 用 `card_ref` 不用 uuid**——
稽核紀錄是人在讀的（沿用 `unfinished_dependencies()` 的同一個判斷）。

**不同意的話（N 列 audit）**：一次 bulk 操作在稽核頁上是 100 列噪音，
而「誰在什麼時候批次改了什麼」這個問題要靠時間戳去拼。

---

### D106 — 本期的 daemon diff 是零，並且有 gate

**裁決**：`GATE-PX-NO-DAEMON-DIFF`：`git diff --stat <baseline>..HEAD -- daemon/`
必須為空。`GATE-PX-CONTRACT-FROZEN`：`contracts/` 全樹 sha256 與基線相同。

**後果**：`agentd` 版本不動（0.14.1）。這也表示
「未升級節點行為不變」這條出口條件在本期是**恆真**的，
但仍要跑一次完整 run 生命週期 E2E——因為 Central 半邊改了，
而 `alpha.2` 的 `CE-` 期證明過「兩邊都沒改協定」不等於「行為沒變」。

**不同意的話**：任何 daemon 變更都會把「未升級節點」從恆真變成要驗證的命題，
而那需要一個 0.14.0 的節點與一組相容性 fixture。

---

## 實作決策（不擋開工，但寫下來以免被重新發明）

### D107 — `WorkItemCardDTO` 不帶 `attention_signals` 全文，只帶 count

**裁決**：卡片 DTO 帶 `primary_attention`（一個 enum）與 `attention_count`（int）。
**完整的 signals 陣列只在 Drawer 的 detail endpoint 回傳。**

**理由**：D94。八級 signals 的陣列是不定長的，而 200 張卡 × 平均兩個 signal
× 每個 signal 的 JSON 物件 ≈ 20 KB，換來的是一個卡片上顯示不了的東西
（上游 [`05`](../../research/03/05-phase-p2-board-and-backlog.md) §3.2：「卡片只顯示 primary」）。

### D108 — `blocking_refs` 在卡片上限三個 ＋ 一個總數

**裁決**：`blocking_refs: list[str]`（最多 3）＋ `blocking_count: int`。

**理由**：同 D94。一條深相依鏈的卡片會帶 20 個 `card_ref`，
而卡片上只顯示得下「TK-3、TK-7 及其他 18 張」。Drawer 顯示全部。

### D109 — per-group cursor 的格式

**裁決**：cursor 是 `base64url(json({"rank": …, "id": …}))`，
不是 offset，也不是純 `updated_at`。每個 group 一個獨立 cursor，
response 回 `{group_key: next_cursor}` 的 map。

**理由**：預設 `order_by` 是 `rank`，而 rank 是唯一且穩定的；
`updated_at` 會在使用者看的時候變動，用它當 cursor 會漏卡或重複。
`id` 是 tie-breaker，因為 backfill 之後 rank 唯一，但**再平衡期間可能短暫重複**。

### D110 — `work-counts` 是一個 `GROUP BY`，不是跑一次 items 再數

**裁決**：`work-counts` 用同一個 filter 編譯結果，換成
`SELECT <group_key>, count(*) … GROUP BY <group_key>`，不 SELECT 任何卡片欄位。

**理由**：D95 讓它每 20 秒被打一次。跑一次 items 再數，成本是 items 查詢的全部
加上序列化 200 張卡然後丟掉。

**例外**：attention 的兩級（D92 相位 B）不能 `GROUP BY`，
所以 `work-counts` 對這兩級的處理是：先取 queued 候選集（一個小查詢），
相位 B 解析，回傳兩個純量。這是 `work-counts` 唯一的第二個查詢。

### D111 — Drawer 用 `router.replace`，不用 `push`

**裁決**：開啟 Drawer 加 `?task=<uuid>` 用 `replace`；關閉只移除 `task` query。

**理由**：上游 [`06`](../../research/03/06-phase-p3-task-drawer.md) §5 已寫，
但沒寫可觀察後果：**browser back 必須依序「關 Drawer → 還原 view → 才離開 Project」**。
用 `push` 的話，連續開關五張卡會在 history 堆五筆，返回鍵變成一個沒有人預期的東西。
這條有 E2E（[`10`](./10-verification-and-exit.md) §4 的 J10）。

---

### D118 — `/board` 與 `BoardCardDTO` 在 `beta.1` 標 deprecated，`beta.2` 刪除

**裁決**：`GET /api/projects/{id}/board` 加 `Deprecation` 回應標頭與 OpenAPI 的
`deprecated: true`；**shape 仍然凍結**；`beta.2` 的 `HD-` 期刪除。

**證據**：`grep` 顯示它只有**一個**消費者——`frontend/src/views/ProjectDetailView.vue:110`
（經 `api/client.ts:329`）。daemon、CLI、`contracts/` 都沒有用它。
所以 [D117](#d117) 之後，`PX-64` 一完成它就是零消費者。

**為什麼不在 `beta.1` 直接刪**：UI 版本與 API 相容性是兩件事。
一個外部腳本可能正在打它，而我們沒有辦法證明沒有。一版的 deprecation window
是那個不確定性的價格。

**`GATE-PX-BOARD-UNCHANGED` 仍然保留**，但理由改變：
不再是「舊看板繼續用它」，而是**「一個已宣告 deprecated 的東西在被刪除之前不該改」**。
其中的 bytes 斷言（89,251 ± 2%）**特別保留**——它守的是
`active_runs()`／`blocking_counts()` 這兩個**新舊共用**的查詢沒有被加寬，
而那個風險與 UI 版本無關。

---

### D112 — project view 軟刪除，personal view 硬刪除

**裁決**：`work_views` 加 `deleted_at`；`uq_work_views_name` 改為部分索引
（`WHERE deleted_at IS NULL`）。**project scope 軟刪除，personal scope 硬刪除。**

**證據**：kintra 的 `uq_board_views_board_user_name` 就是這個形狀
（`postgresql_where=sa.text("deleted_at IS NULL")`），而上游 §1.9 只寫了
「`(board,user,name)` 唯一鍵」，沒寫它是部分索引。

**理由**：[`research/03/08`](../../research/03/08-data-model-and-contract.md) §7
要求「shared view created／updated／deleted」寫 audit，
而一筆指向已消失 id 的 audit 回答不了「當時刪掉的是哪一個」。
personal view 不寫 audit，硬刪除比較乾淨。

**不同意的話**：刪掉一個共用 view 之後，稽核頁上那一列點不進去。

---

### D113 — filter 是一個 model，服務三個地方

**裁決**：query string 的 `f=`、`work_views.filter_json`、`work-counts` 的 filter
是**同一個 Pydantic model**，不是三個各自驗證的地方。

**證據**：kintra 的 `BoardFilterCriteria` docstring：
「看板讀取、欄位分頁與 `board_views.criteria` **共用同一個 model**。
兩處各寫一次必然漂移（`P2-D15`）」。

**後果**：這是 [`10`](./10-verification-and-exit.md) SR-3 第 1 項
「counts 與 items 同 predicate」的型別層版本。兩者一起成立才算數。

**保留分歧**：kintra 的 criteria 是**扁平**的七個欄位，沒有 and／or、
沒有深度限制、沒有三個 machine code。Cliora 依 D54 用樹狀——
差異與代價在 [`13`](./13-kintra-port.md) §4。

---

### D114 — kintra 用 `@tanstack/vue-query`，所以它不是 D100 的先例

**裁決**：`modules/` 佈局照抄 kintra；**query 層不照抄**（D56／D100 已裁決自建）。
把這個差異寫下來，不讓「參考 kintra」被讀成全盤背書。

**證據**：`../kintra/frontend/package.json` 有 `"@tanstack/vue-query": "^5.62.7"`，
而 `modules/board/queries.ts` 整支建立在 `useQuery`／`useMutation`／`useQueryClient` 上。

**後果**：[`11`](./11-open-measurements.md) 第 4 項的反悔點有了具體對照組——
`queryCache.ts` 的 250–350 行要做的，是 kintra 用一個套件解決的事。

---

## 兩份 ADR 的分工

| ADR | 標題 | 內容 | ticket |
|---|---|---|---|
| **0040** | Work lifecycle、attention projection 與 stage 相容策略 | 四個正交狀態面；lifecycle 由 stage 投影的完整對照表；**D92 的兩相位**與「為什麼不物化」；D102 的 dual write 與 `HD-06` 的還款計畫；D97 的「為什麼沒有第三個硬拒絕」 | `PX-21` |
| **0042** | View schema、scope、權限與 rank | `work_views` 的 schema 與 `ck_work_views_scope`；D93 的 `visible_project_ids`；view 不改變 Task 權限；D50 的 rank scope ＋ 三個不變式；D105 的 bulk audit 形狀 | `PX-21` |

**兩份而不是一份**：0040 談的是「一張卡現在怎麼樣」，0042 談的是
「誰能看到哪些卡、以什麼順序」。前者是投影，後者是授權與排序——
混在一份裡，日後要修改排序規則的人得先讀完 attention 的八級優先序。

---

## 治理

`v2` → `dev` **一律由人工確認**。出口條件全綠只是取得**提案資格**，不是核准。
任何自動化——CI、agent、排程——都不得執行這個合併。

發版到 `master` 時**不帶 V2**：從 V2 系列之前切 `release/*` 分支，不用 `dev` 當 head。
