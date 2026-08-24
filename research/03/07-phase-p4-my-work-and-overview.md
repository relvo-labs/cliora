# 07 — `beta.1` 第四段：My Work、Project Overview 與導覽

> **ticket 前綴 `PX-`。前置條件：[`04`](./04-phase-p1-view-and-read-model.md) 的 `PX-24`／`PX-25`。**

## 1. 這一段是 Cliora 的差異化，不是附加功能

Cliora 的特殊狀態全部散在專案內：waiting for human input、no eligible runner、
assigned runner offline、failed run、gate pending、verification failed、
delivery waiting for review。管理三個 Project 的人必須逐一打開才知道發生了什麼。

**My Work 不是「Jira 也有的我的任務」**。它是「哪些事情在等一個人類，而那個人類是我」。
這個問題只有 Cliora 需要回答，因為只有 Cliora 有一群 Agent 在等人。

## 2. 全域導覽

```text
Home
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

現況是 `Dashboard / Nodes / Enrollment / Integrations / Projects / Agents / Sessions / Audit`
的平鋪清單。這一段把它分成四組並新增 `My Work`。
**`Dashboard` 更名為 `Home`**，內容從 fleet health 擴為跨專案摘要，但**保留 fleet health 區塊**
——V1 的操作者仍然需要它，這是 `plan/19` 的 V1 pixel-stability 承諾的延伸。

## 3. Project 導覽

```text
Project Overview
Work
  ├─ Active board
  ├─ Backlog
  ├─ All work
  └─ Saved views
Requirements
Knowledge                  ← alpha.3
Runs
Roadmap
Activity
Settings
  ├─ General
  ├─ Repositories
  ├─ Runners & tags
  ├─ Secrets
  ├─ Process
  └─ Workspaces
```

路由（舊路由全部保留）：

```text
/projects/:projectId
/projects/:projectId/work[/backlog|/views/:viewId]
/projects/:projectId/requirements
/projects/:projectId/knowledge
/projects/:projectId/runs
/projects/:projectId/roadmap
/projects/:projectId/activity
/projects/:projectId/settings/:section?
/projects/:projectId/tasks/:taskId          （完整頁面，保留）
```

`?tab=board` 等舊 query 轉到對應的新子路由（`HD-07`）。

## 4. My Work

### 4.1 跨專案 read model

```text
GET /api/me/work-items       filter / sort / cursor / permission boundary
GET /api/me/attention-counts
```

**不在前端對每個專案各發一次請求再合併。** 三個理由：
N 個專案就是 N 個請求；分頁無法跨專案正確排序；
權限邊界會變成前端的責任，而那是 [`04`](./04-phase-p1-view-and-read-model.md) §4 明確禁止的。

`/api/me/work-items` 與 `/api/projects/{id}/work-items` **共用同一個 query compiler
與同一個 `derive_attention`**，只有 project scope 的 predicate 不同。

### 4.2 預設 sections

| Section | filter |
|---|---|
| Waiting for your response | `attention = waiting_for_your_input` 且 **我是 owner**——見下 |
| Pending your approval | `attention = pending_human_approval` 且我有 `task.approve` |
| Failed runs you own or follow | `attention = run_failed` 且 owner = 我 |
| Assigned work | `owner = @me` 且 `lifecycle in (ready, in_progress, review)` |
| No eligible runner | `attention = no_eligible_runner` 且 owner = 我 |
| Recently completed deliveries | `lifecycle = done` 且近 7 天 |

加上使用者自己的 saved personal views（`work_views` 的 `project_id IS NULL`）。

> **「open question 指向我」在今天沒有欄位可以問**（2026-08-23，`plan/26` 的 `PX-00` 回寫）。
> `task_questions` 沒有 `addressed_to_user_id`：一個問題是問「這張卡的人類」，
> 不是問某一個人。加上那一欄要回答「誰指定的」「改指定算不算一次 activity」
> 「沒有 owner 的卡問誰」三個問題，而那是一次 schema 變更加一段產品設計。
>
> `beta.1` 的第一段因此是 **`owner_user_id = @me`**，
> 並在 section 標題旁寫明「你負責的卡片」而不是「問你的問題」——
> 一個說得比實際窄的標題，比一個做不到的承諾好。
> 詳見 [`plan/26/08`](../../plan/26/08-my-work-and-navigation.md) §3。

### 4.3 Notification 與 My Work 的界線

| | Notification | My Work |
|---|---|---|
| 表示 | 事件**發生過** | 目前**仍需要行動** |
| 已讀 | 改變 notification 狀態 | **不改變任何東西** |
| 消失的條件 | 使用者讀了 | Task／Run／Gate 的**真實狀態**改變 |

**已讀 notification 不代表 action resolved。** 這一條有測試：
標記全部已讀之後，My Work 的 counts 不變。

> **這個系統沒有 notification**（2026-08-23，`plan/26` 的 `PX-00` 回寫）。
> 沒有表、沒有端點、沒有已讀狀態，所以上面那條出口條件**沒有可以標記已讀的東西**，
> 而一個永遠通過的測試比沒有測試更糟。
>
> 這一節保留，因為它說的分界是對的——它只是還沒有第一半。
> `beta.1` 把出口條件改成 **`GATE-PX-MYWORK-READS-STATE`**：
> AST 斷言 My Work 的每一個 section 的述詞都只讀 Task／Run／Gate 的真實狀態，
> 沒有任何一個讀「使用者看過了沒有」。
> 那守住的是**未來加 notification 時不會有人把它接進 counts**，
> 而那正是這一節真正在防的事。
> 詳見 [`plan/26/08`](../../plan/26/08-my-work-and-navigation.md) §4。

## 5. Project Overview

Overview 不複製完整 dashboard，只回答五個問題：
這個 Project 的目標是什麼？進度與風險如何？有什麼需要人處理？
Agent 現在做什麼？最近交付了什麼？

模組順序：

```text
1 Project summary        目標、狀態、workspace 綁定摘要
2 Attention strip        八種 attention 的計數，點擊進 filtered view
3 Work distribution      Backlog / Ready / In Progress / Review / Done
4 Active Agent Runs      正在跑的 run、runner、時長
5 Requirements progress
6 Recent deliveries
7 Recent activity
```

**不在 Overview 直接顯示 Secret 管理、Workspace binding 表單或 process 設定。**
它們移到 `Settings`，理由是風險等級不同的功能不該共存在同一層。

## 6. Tickets

| ID | 工作 | 來源 |
|---|---|---|
| `PX-47` | 跨專案 My Work read model（共用 query compiler） | PX-47 |
| `PX-48` | Attention counts API（與 items 同 predicate） | PX-48 |
| `PX-49` | My Work 六個 section ＋ 個人 saved views | PX-49 |
| `PX-50` | Project Overview attention strip | PX-50 |
| `PX-51` | Active runs／recent delivery 模組 | PX-51 |
| `PX-52` | Stale／failure 可見性 | PX-52 |
| `PX-63` | **全域導覽重整**（四組 ＋ My Work ＋ Dashboard→Home，保留 fleet health） | 新增 |
| `PX-64` | **Project 子路由與 ProjectDetailView 拆分**（見 [`09`](./09-frontend-architecture.md) §2） | 新增 |

## 7. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | 使用者不進入各 Project 即可找到所有 human-required actions | E2E ＋ 任務時間量測（10 秒內） |
| ☐ | Notification read state 不影響 My Work | 標記全部已讀 → counts 不變 |
| ☐ | counts 與 detail query 權限一致 | 同一 predicate 的斷言 ＋ inference 測試 |
| ☐ | My Work counts P95 < 500ms | 效能量測（多專案 fixture） |
| ☐ | 跨專案不洩漏 | 無權專案的卡片不出現在 items **也不計入 counts** |
| ☐ | 舊路由（含 `?tab=`）仍可用 | route 相容測試 |
| ☐ | V1 的 fleet health 在 Home 上仍在且未變形 | 視覺回歸 |
