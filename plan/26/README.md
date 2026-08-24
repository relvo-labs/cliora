# Cliora `v2.0.0-beta.1` — V2-P1 Collaborative Project Workspace

> **狀態（2026-08-24）：波次 0 至 7 全部實作完成，六條旅程全綠。**
> 34 張 ticket 全部完成；十一個 `GATE-PX-*` 全綠；
> 一次跑完的證據在 [`artifacts/px/local/evidence.log`](../../artifacts/px/local/README.md)。
> **J1／J4／J15 已對真的 daemon 跑過**（J1 32／32、J4 13／13、J15 8／8），
> 其中 J1 是不可降級的那一條，也是本期目的的證明。
> **四十項出口條件三十八項達成，剩下的兩項都是人的動作**
> ——`v2` → `dev` 的人工核准、SR-3 的具名簽名。逐項在 [`12`](./12-implementation-status.md) §6。
>
> **更正（2026-08-24）**：這一段先前寫「需要 Go 工具鏈」，那是錯的。
> Go 1.26.5 就在 `/usr/local/go/bin`，`scripts/e2e/run-stack.sh` 第 106 行本來就會把它加進 `PATH`。
> 三條旅程沒跑的真正原因是沒有人去跑，而把它記成環境限制
> **讓一件做得到的事看起來做不到**——這是這份文件裡最值得記住的一次錯誤。
> **波次 1 起是在三項前置條件未關閉的情況下、經人工裁決開工的**（[`12`](./12-implementation-status.md) §2.7）。
> 上游規劃：[`research/03/04`](../../research/03/04-phase-p1-view-and-read-model.md)–[`07`](../../research/03/07-phase-p4-my-work-and-overview.md)。
> 前一期：[`plan/25`](../25/README.md)（K1 實作完成，出口條件 26／28，**尚未打 `v2.0.0-alpha.3` tag**）。
> A 類八項的全文在 [`00`](./00-execution-plan.md) §0.1，每一項都寫了「不同意的話會怎樣」——
> **裁決之後那一段仍然保留**，它是日後想推翻某一項的人唯一的參考。裁決單在 [`12`](./12-implementation-status.md) §1。
> **合併規則不變**：`v2` → `dev` 一律由人決定，出口條件全綠只是取得提案資格。
> 發版到 `master` 時不帶 V2。

Ticket 前綴 `PX-`。

---

## 這一期要交付什麼

一句話：

> **同一份資料的多個投影**——Board、Backlog、List、Task Drawer、My Work 與 Project Overview
> 對「這張卡現在怎麼樣」給出的答案，由 backend 的**同一個函式**產生，前端只負責畫；
> 而「哪些事情在等一個人類，而那個人類是我」這個只有 Cliora 需要回答的問題，
> 有一個不必打開任何 Project 就能回答的入口。

`alpha.2` 交付的是「一句話怎麼保證只被做一次」；
`alpha.3` 交付的是「Agent 讀到的每一句話說得出它從哪裡來」。
**本期的形狀是「同一個事實在六個畫面上不會有六種說法」**——
而做不到這件事的原因不是 UI，是目前**根本沒有一個共用的讀模型**：
`ProjectDetailView.vue` 1515 行在協調四組各自查詢的 DTO，
`board_cards()` 一次載入專案的全部卡片、沒有游標、沒有篩選、沒有排序欄位。

---

## 八個真正的缺口（讀完程式碼與發布史才看得到的那種）

上游規劃寫的是「要做什麼」。以下七條是把它對到這個 repo 的現況之後，
**規劃層沒有寫、但會決定實作形狀**的事實。每一條都在 [`01`](./01-decisions-and-governance.md) 有對應的裁決。

| # | 缺口 | 證據 | 決策 |
|---:|---|---|---|
| 1 | **八個 attention 裡有兩個不在資料庫裡。** `no_eligible_runner` 與 `assigned_runner_offline` 由 `NodeConnectionRegistry` 這個**行程內的 dict** 決定，而 `runners.py` 的 module docstring 明文寫著「a stored copy would be a second answer that can go stale, and this module deliberately does not create one（ADR 0029 §1）」。於是上游 [`04`](../../research/03/04-phase-p1-view-and-read-model.md) §5「要不要物化」的兩個選項**都不成立**——它們都假設 attention 進得了 `WHERE` | `services/registry.py:80`、`services/runners.py:8`、`repositories/tasks.py:221` | **D92**：attention 兩相位求值；`tasks.attention_primary` 欄位**永不建立** |
| 2 | **沒有 project membership。** RBAC 是全域三角色，`_VIEWER_ACTIONS` 就含 `PROJECT_VIEW`——**任何拿得到 `project.view` 的人看得到全部專案**。上游 SR-3 的「My Work 跨專案隔離」與「無權專案的卡不在 counts」在今天**沒有可測的對象** | `services/rbac.py:92`（`_VIEWER_ACTIONS`）；`services/authz.py` 無任何 project-scope 函式 | **D93**：可見專案集合走單一函式 ＋ AST gate；**測「述詞被套用」，不測不存在的 ACL**；不可測的那一半寫進未量測項 |
| 3 | **160 KB 這個預算是從一個過期數字推出來的。** 上游說「74 KB 的兩倍多一點」，但 `BoardCard` 的 docstring 記的是 **89,251 bytes 對 90,000 的預算**——現行看板卡已經用掉自己預算的 **99.2%** | `repositories/tasks.py:45` | **D94**：**先量再釘**。`PX-25` 量出 33 欄的實際值，以「量測值 ＋15%」釘死並記錄逐欄 bytes；**不得直接抄 160 KB** |
| 4 | **看板沒有任何自動更新機制。** 瀏覽器端只有 terminal 一條 WebSocket；`reloadTasks()` 只在 mutation 之後被呼叫。於是「這張卡剛剛開始等你回覆」這件事**在畫面上永遠不會自己出現** | `frontend/src/api/client.ts:241`（唯一的 WS 票券是 terminal）、`views/ProjectDetailView.vue:108` | **D95**：只輪詢 `work-counts`（一個查詢），20 秒、分頁隱藏時停；**beta.1 不開瀏覽器 WS**——那是新的信任邊界 |
| 5 | **`GATE-DV-SINGLE-DONE-PATH` 比它的名字弱得多**——它是一個 grep，只掃 `runs.py`、只禁 `'done'`。實際上有三處寫 `task.stage='blocked'`（`run_reaper.py` ×2、`runs.py:1510`），全部在它的視野外。於是一個自己寫 `UPDATE tasks SET stage=…` 的 bulk endpoint **沒有任何 gate 擋得住**，而它會一次繞過 Done Gate、相依檢查、樂觀鎖與 knowledge outbox | `scripts/dv/gates.sh:106`、`services/activity.py:246` | **D96**：bulk 逐張走 `update()` ＋ **新增 `GATE-PX-BULK-USES-UPDATE`** |
| 6 | **Definition of Ready 刻意不拒絕，而那是寫在 docstring 裡的決定。** 上游的 machine code 表列了 `STAGE_TRANSITION_REFUSED`，但這個 repo 只有兩個硬拒絕，兩個都已經有 code 而且都已經列出全部缺失項 | `services/process.py:11`、`services/tasks.py:645`（`TASK_DEPENDENCY_UNSATISFIED`）、`done_gate.py:20` | **D97**：**不新增 `STAGE_TRANSITION_REFUSED`**。這正是 `plan/25` §2.12 的 `CROSS_PROJECT_DENIED` 教訓——一個沒有 raise 點的 code 是文件不是行為 |
| 7 | **`useAsyncResource` 沒有快取可以擴充。** 它 50 行，每個呼叫點拿到一組全新的 ref，沒有 key、沒有去重、沒有失效。上游說「擴充成 200–300 行的最小 query 層」——**沒有東西可以擴充** | `composables/useAsyncResource.ts`（全檔 78 行，含 `deriveNodeState`） | **D100**：新增 `modules/work/queryCache.ts`；`useAsyncResource` **一行不動**，V1 頁面繼續用它 |

| 8 | **這會是第四次把畫面排在最後。** `alpha.1`／`alpha.2`／`alpha.3` 三次 prerelease，使用者看到的變化是「六欄看板 → 多一個對話面板 → 多一個 Knowledge 分頁」。而本計畫**第一版**把全部前端排在十張純後端 ticket 之後，還讓它預設關閉 | 發布史；`00` §0.1 D115 的表 | **D115** 新增**波次 0**（跑在既有 backend 上）＋ **☑ D117** UI 不分版本、旗標不建立、`ProjectDetailView.vue` 直接刪 |

第 1、2、4 條合起來說明一件事：**上游把 `beta.1` 描述成一個「把既有資料換個畫法」的期，
它實際上是一個「加一個讀模型 ＋ 承認兩個 attention 不在資料庫裡 ＋ 決定新鮮度從哪來」的期。**

第 3、5、6 條各自是一個**會靜默通過所有測試**的陷阱。

**第 8 條不是讀程式碼看到的，是讀發布史看到的**——
而它的修法也在程式碼裡：既有 `BoardCardDTO` 的十六欄已經足以推導**八級 attention 裡的六級**
（`active_run_status`／`waiting_reason`／`blocking_count`／`gates_approved_count`／`updated_at`），
所以「看板卡片上有 attention」不必等新讀模型。

---

## 這一期不做什麼

| 不做 | 為什麼 | 落點 |
|---|---|---|
| provider（PR／MR／Release）同步 | 本期新增的對外副作用是**零**，混進來會把 SR-3 的範圍拉高一級 | `beta.2`（★ D46 仍未裁決） |
| `stage='blocked'` 的真正遷移 | 本期只做投影（D49）；拆過渡需要 ambiguous report 先被人看過 | `beta.2` `HD-06` |
| 瀏覽器 WebSocket | 新的認證通道 = 新的信任邊界 | `beta.2`（D95） |
| virtualization | 200 張是第一個 gate，1000 張才評估 | Horizon 2 |
| 向量檢索、新的 RBAC 動作、contract 變更、**任何 daemon diff** | 見 [`00`](./00-execution-plan.md) §3 禁區清單 | — |

**本期的 `daemon/` diff 應為零。** 這是可以用 `git diff --stat` 斷言的，
而且它是 `GATE-PX-NO-DAEMON-DIFF` 的全部內容。

---

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | **開工前唯一必讀**：**八項 A 類裁決**、九項 B 類、**八個波次**、34 張 ticket、禁區清單、版本節奏 |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | **D92–D111** 全文，每一項含「不同意的話會怎樣」 |
| [02-data-layer.md](./02-data-layer.md) | Migration `0043`、`work_views`、`tasks` 四欄、索引、rank backfill、預設 view seed、downgrade |
| [03-read-model-and-attention.md](./03-read-model-and-attention.md) | 四個狀態面、`derive_attention` 的兩相位、lifecycle 投影、`WorkItemCardDTO` |
| [04-filter-and-query-compiler.md](./04-filter-and-query-compiler.md) | 15 欄 × 8 運算子的 allowlist、編譯路徑、可見專案述詞、三個 machine code |
| [05-work-items-and-view-api.md](./05-work-items-and-view-api.md) | `work-items`／`work-counts`／view CRUD／bulk／rank／`/api/me/*`、游標、大小預算 |
| [06-board-and-backlog.md](./06-board-and-backlog.md) | Active Board 四欄、Backlog、toolbar、quick filter、DnD 與鍵盤等價路徑 |
| [07-task-drawer.md](./07-task-drawer.md) | URL 驅動的 Drawer、conversation-first、inline edit 與衝突、Related knowledge |
| [08-my-work-and-navigation.md](./08-my-work-and-navigation.md) | My Work 六區、Overview、全域導覽重整、`ProjectDetailView` 逐頁拆分 |
| [09-frontend-architecture.md](./09-frontend-architecture.md) | `queryCache`、URL state、`modules/` 佈局、token、新鮮度政策 |
| [10-verification-and-exit.md](./10-verification-and-exit.md) | 九個新 gate、測試矩陣、六條旅程、SR-3、效能預算、**36 項出口條件** |
| [11-open-measurements.md](./11-open-measurements.md) | 本期知道自己沒量的東西與理由 |
| [12-implementation-status.md](./12-implementation-status.md) | 實作後回填；**與計畫不同時以這裡為準並回寫計畫** |
| [13-kintra-port.md](./13-kintra-port.md) | **從 `../kintra` 移植什麼、不移植什麼**：上游 §1.9 七項的逐項處置 ＋ 實際讀過 kintra 之後才看得到的六件事 |

## 建議使用方式

1. 先讀 [`00`](./00-execution-plan.md) §0.1 的 **A 類八項**。**☑ 已全部裁決**，
   所以這一步是**讀而不是決定**——但要讀，因為每一項的「不同意的話會怎樣」
   就是實作時不能繞過的那條線。
2. 波次順序照 [`00`](./00-execution-plan.md) §1。**波次 0 跑在既有 backend 上，
   三個波次之前就交付一個看得見的看板改變**；波次 1 才是新讀模型的地基。
   每個波次的可看產出在 [`00`](./00-execution-plan.md) §4b。
3. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
4. **出口條件未通過，不建立 `v2.0.0-beta.1` tag。**
   證據是自己的兩張 ticket（`PX-65`／`PX-66`），不是別人的尾巴——
   這是 [`plan/24`](../24/README.md) 花了一整期學到的。
5. 需求變更先更新 `research/prd.md` 與 `traceability/requirements.json`，
   再同步 [`research/03/11`](../../research/03/11-requirement-traceability.md)。

## 規劃基準（2026-08-23 實際讀過程式碼確認）

| 項目 | 現況 | 讀哪裡 |
|---|---|---|
| `v2` HEAD | `3e503de`（`Merge pull request #44 from Lei-k/v2`） | `git rev-parse HEAD` |
| tag | `v2.0.0-alpha.1`、`v2.0.0-alpha.2` 已建立；**`alpha.3` 未建立**（`plan/25` 出口 26／28） | `git tag` |
| contract | **1.13.0**；`run.offer.context` 上限 32768 bytes | `contracts/CHANGELOG.md`、`daemon/internal/protocol/codec.go:962` |
| `agentd` | **0.14.1** | `daemon/VERSION` |
| migration head | **0042**`_knowledge_tables` | `backend/app/db/migrations/versions/` |
| ADR | 0035–0039、0041 已用；**`0040` 與 `0042` 是空號，本期用掉這兩個** | `docs/adr/` |
| RBAC | **27 個動作、三個全域角色、無 project membership**；`_VIEWER_ACTIONS` 含 `project.view` | `services/rbac.py:92,194` |
| run token scope | `{project.view, task.update}`；`AGENT_FORBIDDEN_FIELDS` 五欄 | `services/agent_auth.py:70,81` |
| requirements | **189** 條、**28** 個 family；**沒有 `FR-WORK`** | `traceability/requirements.json` |
| `tasks` 欄位 | **沒有 rank／position／order_index／is_blocked**（`epics` 與 `user_stories` 有 `order_index`，`tasks` 沒有） | `db/models.py:764` |
| `tasks` 索引 | 只有 `ix_tasks_project_stage`、`ix_tasks_project_story`、`ix_tasks_proposal_item`。**沒有 `(project_id, updated_at)`** ——而看板正是 `ORDER BY updated_at DESC` | `0023_task_board.py:391`、`0039_…py:216` |
| 看板查詢 | `board_cards()` 一次回**全部**卡片；`BoardDTO.has_more` 永遠 `False`；「不分頁」是寫在 docstring 裡的決定 | `repositories/tasks.py:110`、`api/http/tasks.py:304` |
| 看板卡實測 | **89,251 bytes / 200 張，預算 90,000**（`plan/19` 加了三欄之後） | `repositories/tasks.py:45` |
| stage | 六值 `backlog blocked ready implementing verify done`；**沒有轉移矩陣**，`_require_stage` 只檢查成員資格 | `services/process.py:46`、`services/tasks.py:199` |
| 硬拒絕 | 只有兩個：`TASK_DEPENDENCY_UNSATISFIED`（409 ＋ `blocking_refs`）與 Done Gate（列出全部 missing item）。**DoR 只警告** | `services/tasks.py:645`、`done_gate.py`、`process.py:11` |
| `task.stage` 寫入點 | **唯一**：`TaskService.update()`，由 `GATE-DV-SINGLE-DONE-PATH` 用 AST 守著 | `services/done_gate.py:16` |
| runner online | **行程內 dict**，無持久化，ADR 0029 §1 明文拒絕存一份 | `services/registry.py:80`、`services/runners.py:8` |
| activity | `ActivityService.record()` 同一交易內寫 activity ＋ knowledge outbox hint（`ON CONFLICT DO NOTHING`） | `services/activity.py:199,246`、`knowledge/outbox.py:181` |
| 前端 | 無 query cache 套件；`useAsyncResource` **78 行、無快取**；12 個 Pinia store；`tokens.css` **62** 個 property | `frontend/src/` |
| 前端 `modules/` | **已存在**：`modules/knowledge/{views,components}`（`alpha.3` 建立）。本期沿用同一形狀，不是新慣例 | `frontend/src/modules/` |
| 前端路由 | `/projects/:id` 單一路由 ＋ `?tab=`；`/projects/:id/knowledge`、`/tasks/:taskId`、`/runs/:runId` 已是獨立路由 | `router/index.ts:73-118` |
| 瀏覽器推播 | **沒有**。唯一的 WS 是 terminal；board 只在 mutation 後 `reloadTasks()` | `api/client.ts:241`、`views/ProjectDetailView.vue:108` |
| 固定資料集 | `scripts/cv/seed-dataset.py`，seed 20260819：200 卡、500 則訊息的深卡、20 張等待卡、6 runs、5 failed、一條相依鏈 | `scripts/cv/seed-dataset.py` |
| kintra rank | `../kintra/backend/app/modules/board/ranking.py` **存在且可移植**（純函式、三個不變式、`rebalanced_ranks`），測試在 `tests/unit/test_ranking.py` ＋ `tests/integration/test_rank_rebalance.py` | `../kintra/` |

> 執行計畫與 `research/03/` 不一致時，**以本目錄為準並回寫上游**——
> 本目錄讀的是程式碼，上游讀的是構想。已知需要回寫的九處列在
> [`12`](./12-implementation-status.md) §0，由 `PX-00` 負責。
