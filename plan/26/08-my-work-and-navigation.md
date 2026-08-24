# 08 — My Work、Project Overview 與導覽

> **ticket：`PX-47`（後端，波次 2）、`PX-49`（My Work UI）、`PX-50`（Overview）、
> `PX-63`（全域導覽）、`PX-64`（Project 子路由與拆分）。**

## 1. 這一段是 Cliora 的差異化，不是附加功能

Cliora 的特殊狀態全部散在專案內：waiting for human input、no eligible runner、
assigned runner offline、failed run、gate pending、verification failed、
delivery waiting for review。管理三個 Project 的人必須逐一打開才知道發生了什麼。

**My Work 不是「Jira 也有的我的任務」**。它是
「哪些事情在等一個人類，而那個人類是我」。
這個問題只有 Cliora 需要回答，因為只有 Cliora 有一群 Agent 在等人。

## 2. 跨專案讀模型（`PX-47`，波次 2）

```text
GET /api/me/work-items       filter / sort / cursor / ProjectScope
GET /api/me/attention-counts
```

**與 `/api/projects/{id}/work-items` 共用同一個 query compiler
與同一個 `derive_attention`**，只有 `ProjectScope` 不同
（[`05`](./05-work-items-and-view-api.md) §7）。

`/api/me/` 是新的命名空間——**這個 repo 今天沒有任何 `/api/me/`**。
`me.py` 的 module docstring 要寫下它的規則：

> **只回「與這個呼叫者有關」的東西，永遠不接受 `user_id` 參數。**

沒有這句話，第一個需要「看別人的 My Work」的需求會在這裡加一個 `?user_id=`，
而那會把一個「我的東西」的端點變成一個需要 `audit.view` 等級判斷的端點。

## 3. My Work 的六個 section（`PX-49`）

| Section | filter |
|---|---|
| Waiting for your response | `attention = waiting_for_your_input` 且（open question 指向我 或 我是 owner） |
| Pending your approval | `attention = pending_human_approval` 且我有 `task.approve` |
| Failed runs you own or follow | `attention = run_failed` 且 `owner = @me` |
| Assigned work | `owner = @me` 且 `lifecycle in (ready, in_progress, review)` |
| No eligible runner | `attention = no_eligible_runner` 且 `owner = @me` |
| Recently completed deliveries | `lifecycle = done` 且近 7 天 |

加上使用者自己的 saved personal views（`work_views` 的 `project_id IS NULL`）。

**第五個 section 依賴 attention 的 runtime 級**（[D92](./01-decisions-and-governance.md)）。
`runtime_signals_available = false` 時，這一段顯示
「節點連線資訊暫時不可用」而不是「0 件」。
**這一條有一支元件測試**，因為「0 件」與「不知道」在這個畫面上的後果不同：
前者讓人去做別的事，後者讓人重新整理。

**「open question 指向我」在今天沒有欄位可查。** `task_questions` 沒有
`addressed_to_user_id`（`0040` 的 schema）。所以第一個 section 的實際述詞是
`attention = waiting_for_your_input AND (owner_user_id = @me OR <我是這張卡最近一則人類訊息的作者>)`。
第二個 disjunct 需要一個對 `task_messages` 的 exists 子查詢，
而它有 `(task_id, conversation_seq DESC)` 索引可用。
**這是上游 §4.2 沒有寫的一個事實**，記在 [`12`](./12-implementation-status.md) §0。

## 4. Notification 與 My Work 的界線

| | Notification | My Work |
|---|---|---|
| 表示 | 事件**發生過** | 目前**仍需要行動** |
| 已讀 | 改變 notification 狀態 | **不改變任何東西** |
| 消失的條件 | 使用者讀了 | Task／Run／Gate 的**真實狀態**改變 |

**這個 repo 今天沒有 notification 系統**（沒有表、沒有端點）。
所以上游的出口條件「標記全部已讀之後 My Work 的 counts 不變」
**在本期是恆真的**——沒有東西可以標記。

**本計畫的處置**：保留這條原則寫進 ADR 0040 的一節
（「當 notification 進來時，它不得寫入任何 My Work 讀得到的欄位」），
並把測試改成一支 gate：`GATE-PX-MYWORK-READS-STATE`——
AST 斷言 `me.py` 的查詢只讀 `tasks` / `task_runs` / `task_questions` /
`verification_reports`，**不讀任何 `*_read_at` 或 `*_seen` 欄位**。
今天它掃過就是綠的；notification 進來的那一天它會擋住第一個錯誤的寫法。

## 5. Project Overview（`PX-50`）

Overview 不複製完整 dashboard，只回答五個問題：
這個 Project 的目標是什麼？進度與風險如何？有什麼需要人處理？
Agent 現在做什麼？最近交付了什麼？

```text
1 Project summary        目標、狀態、workspace 綁定摘要
2 Attention strip        八種 attention 的計數，點擊進 filtered view
3 Work distribution      Backlog / Ready / In Progress / Review / Done
4 Active Agent Runs      正在跑的 run、runner、時長
5 Requirements progress
6 Recent deliveries
7 Recent activity
```

第 2 與第 3 段**只打一次 `work-counts`**（`group=attention` 與 `group=lifecycle`
是兩個請求，但兩者都是 [D110](./01-decisions-and-governance.md) 的單一 `GROUP BY`）。

**不在 Overview 直接顯示 Secret 管理、Workspace binding 表單或 process 設定。**
它們移到 `Settings`，理由是風險等級不同的功能不該共存在同一層——
而這正是 `ProjectDetailView.vue` 1515 行的成因。

## 6. 全域導覽（`PX-63`）

```text
Home                       ← Dashboard 更名；內容擴為跨專案摘要，但保留 fleet health
My Work                    ← 新增，日常主要入口
Projects
Agents
Sessions
Infrastructure
  ├─ Nodes
  └─ Integrations
Administration
  ├─ Audit
  ├─ Enrollment
  └─ Access / Settings
```

現況是 `Dashboard / Nodes / Enrollment / Integrations / Projects / Agents /
Sessions / Audit` 的平鋪清單（`router/index.ts:12-140`）。

**保留 fleet health 區塊**——V1 的操作者仍然需要它，
**這一項不受 ☑ D117 影響**：fleet health 是 V1 操作者每天在用的東西，
把它搬到 Home 是**移動**不是重畫。`PX-63` 的視覺基準就是「Home 上的 fleet health 與 Dashboard 上的逐像素相同」。

`/dashboard` 保留為 `/` 的別名（既有的 `{ path: "/", redirect: { name: "dashboard" } }`
反過來變成 `/dashboard` → `/`）。

## 7. Project 子路由與 `ProjectDetailView` 拆分（`PX-64`）

```text
/projects/:projectId                          → ProjectOverviewView
/projects/:projectId/work[/backlog|/views/:viewId] → ProjectWorkView
/projects/:projectId/requirements             → ProjectRequirementsView
/projects/:projectId/knowledge                → 已存在（alpha.3）
/projects/:projectId/runs                     → ProjectRunsView
/projects/:projectId/roadmap                  → ProjectRoadmapView
/projects/:projectId/activity                 → ProjectActivityView
/projects/:projectId/settings/:section?        → ProjectSettingsView
/projects/:projectId/tasks/:taskId             → 保留（完整頁面）
```

`?tab=board` 等舊 query 轉到對應的新子路由（保留 query 的其餘部分）。

### 逐頁替換，不是一次改寫（☑ [D117](./01-decisions-and-governance.md#d117)）

**每一頁只有一條路徑**——不再有「旗標關閉走舊路徑」。
但**仍然逐頁**，理由從「風險隔離」變成**「diff 可讀」**：
一次換掉八頁的視覺回歸沒有人看得完，而看不完的回歸等於沒有回歸。

```text
每一頁：替換 → 存替換前後兩張視覺基準 → 人看過 diff → 下一頁
PX-64 完成時刪除 ProjectDetailView.vue（1515 行）
```

**順序**（依風險由低到高）：

| 序 | 頁 | 為什麼這個順序 |
|---:|---|---|
| 1 | `activity` | 唯讀、最單純、驗證 `ProjectShell` 的殼是對的 |
| 2 | `roadmap` | 唯讀、既有元件（`TaskRoadmap.vue`）整塊搬 |
| 3 | `requirements` | 有寫入但範圍窄 |
| 4 | `settings` | **拆最多**：repositories／secrets／runners／process／workspaces 五段 |
| 5 | `overview` | 需要 `PX-50` 的新模組 |
| 6 | `work` | 需要 `PX-29`…`PX-36` 全部 |

**`ProjectDetailView.vue` 在第 6 頁（`work`）替換完成時刪除。**
`PX-64` 的最後一個 commit 是那次刪除，而不是「把最後一頁接上」——
**「拆分完成」與「舊檔案已刪」是兩件事**，而只做前者會讓下一個人以為 repo 乾淨了。
出口條件第 39 項就是在斷言這件事。

## 8. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | 使用者不進入各 Project 即可找到所有 human-required actions | E2E ＋ 任務時間量測（10 秒內） |
| ☐ | counts 與 detail query 用同一個 `ProjectScope` 與同一份 filter | 程式碼路徑斷言 ＋ `GATE-PX-ONE-PROJECT-SCOPE` |
| ☐ | My Work counts P95 < 500ms | 效能量測（多專案 fixture） |
| ☐ | 舊路由（含 `?tab=`）仍可用 | route 相容測試，六個 tab 各一 |
| ☐ | V1 的 fleet health 在 Home 上仍在且未變形 | 視覺回歸 |
| ☐ | `/api/me/*` 不接受 `user_id` 參數 | OpenAPI 斷言 ＋ module docstring |
| ☐ | My Work 只讀真實狀態，不讀任何已讀欄位 | `GATE-PX-MYWORK-READS-STATE` |
| ☐ | `runtime_signals_available=false` 時第五段顯示「不可用」而非 0 | 元件測試 |
| ☐ | 六個子路由逐頁替換，每頁留下替換前後的視覺 diff | 逐頁 route 測試 ＋ 六組 diff ＋ **`ProjectDetailView.vue` 已刪除** |
