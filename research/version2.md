
# Version 2 升級規劃文件

版本：1.0
文件類型：產品與技術升級規劃
升級前提：Version 1 已完成並穩定運作

---

> ## ⚠️ 2026-08-08 更新：本文件已被 `research/02/` 的執行規劃部分修訂
>
> 本文件保留為**原始構想**，不刪改原文。三次裁決之後，可執行的規劃以
> [`research/02/`](./02/README.md) 為準；以下是三處結構性差異，內文中另有逐節註記。
>
> | # | 裁決 | 對本文件的影響 |
> |---|---|---|
> | 1 | 任務卡要能在平台上拖曳 | §7.3 的看板成為平台上的可操作看板 |
> | 2 | **Monstrare 功能內化**，不複製檔案進使用者專案 | §7.2 的「文件優先存 repo markdown」翻面為平台 DB；§10 的多數表不建 |
> | 3 | **Agent 作為 Runner 自行認領任務**（多對多、隔離工作目錄、機密下放、依卡片交付 PR／分支／無） | 新增執行階段；§11、§12、§13 大幅修訂 |
> | 4 | **納入 Monstrare 的需求釐清（提問）與任務拆解能力** | §7.6、§7.7 從零散的「Agent 工具」升級為完整的 V2.5 階段 |
> | 5 | **Agent 可交付產物到任務卡**（執行中亦可留言附檔） | §7.9 的 Evidence 之外多一種產出形式；交付模式從四種變五種 |
>
> 第三次裁決把 V2 從「專案管理功能」擴大為「AI 開發的執行控制平面」，並**撤銷兩條既有紅線**
> （SEC-002 的 env 部分、「不做 Git 自動化與任務派工」），換上一條新紅線：
> **Agent 的產出只能以 PR、獨立分支或無交付三種形式離開隔離目錄，永不自動合併。**
> 完整論證見 `research/02/00-upgrade-roadmap.md` §7。
>
> **未受影響**：§3 的四條升級原則、§5 的四個核心目標、§15 的向下相容策略，全部成立且已寫進執行規劃。

---

# 1. 文件目的

本文件說明 AI CLI 中央管理平台在完成 Version 1 後，如何升級為具備專案規劃、任務管理、開發追蹤與驗證能力的 Version 2。

Version 2 不取代 Version 1，也不重新設計既有的 Node、Runtime、Workspace、Terminal 與 Session 架構。

升級策略為：

> 保留 Version 1 的遠端 CLI 管理能力，在其上增加 Project、Task、Plan、Verification 與 Evidence 等專案管理能力。

Version 1 解決：

> 如何透過中央 Web 平台操作不同 VM 上的 Claude Code 或 Codex CLI。

Version 2 解決：

> 如何讓 Agent 在既有 CLI Session 中，同時完成需求理解、工作規劃、程式實作與成果驗證，並將過程納入平台管理。

---

# 2. 版本演進定位

## Version 1：CLI Central Management

Version 1 的核心是遠端執行與集中管理。

主要能力包括：

* VM Node 註冊與管理
* Claude Code／Codex Runtime 偵測
* Workspace 選擇與存取限制
* 遠端 PTY Terminal
* tmux Session 持久化
* Web Terminal
* Workspace 檔案瀏覽
* Session 啟動、恢復與終止
* 使用者與基本權限管理

Version 1 的產品定位：

> Claude Code／Codex CLI 的中央遠端管理平台。

---

## Version 2：Project-aware Agent Workspace

Version 2 在既有能力上新增專案管理與工程治理功能。

主要增加：

* Project 管理
* 專案文件與 PRD
* Task 管理
* Agent Execution Plan
* Task 與 Session 綁定
* 驗證結果管理
* Evidence 蒐集
* 專案進度與活動紀錄

Version 2 的產品定位：

> 具備專案管理與工程治理能力的 AI CLI 工作平台。

---

# 3. 升級原則

## 3.1 不重寫 Version 1

Version 2 應以擴充方式開發，不應重新設計下列核心模組：

* Node
* Daemon
* Runtime
* Workspace
* PTY
* tmux
* WebSocket Terminal
* Session Lifecycle

這些功能繼續作為平台的 Execution Layer。

---

## 3.2 不做複雜多 Agent 系統

Version 2 不導入：

* 多 Agent 自動協作
* Agent 組織圖
* Planner Agent／Developer Agent／QA Agent 分工
* Agent 間訊息交換
* 複雜工作流編排器
* 自動任務派工系統

同一個 Agent 可以完成：

```text
Understand
→ Plan
→ Implement
→ Verify
→ Report
```

Claude Code 或 Codex 仍然是實際工作 Runtime。

---

## 3.3 Agent 保持原生能力

平台不應取代 Claude Code 或 Codex 的：

* 工具調用
* Shell 操作
* 檔案修改
* 權限審批
* 開發推理
* 任務執行方式

平台只補充其目前缺少的：

* 專案長期資訊
* 任務結構
* 執行計畫
* 驗證紀錄
* 進度可視化
* 歷史追蹤

---

## 3.4 逐步升級

Version 2 不應一次完成所有治理功能。

建議分階段交付：

```text
V2.0 Project Foundation
V2.1 Task and Session Integration
V2.2 Planning and Verification
V2.3 Evidence and Project Intelligence
```

> **已改為五階段（裁決 3）**：
>
> ```text
> V2.0 專案基座
> V2.1 任務看板與流程內化
> V2.2 Agent Runner 與任務認領
> V2.3 機密下放與隔離工作目錄
> V2.4 交付、驗證與證據
> ```
>
> 計畫與驗證併入 V2.4，因為它們的證據來源是 run；Runner、隔離環境、交付各自獨立一階段，
> 因為每一個都改變安全姿態，不該在同一階段同時上線。
> 見 `research/02/00-upgrade-roadmap.md` §6。

每一階段均應能獨立產生產品價值。

---

# 4. Version 1 架構基線

Version 2 開發前，Version 1 應至少具備以下穩定能力。

## Central Platform

* FastAPI Backend
* PostgreSQL
* WebSocket
* 使用者登入
* Node 管理
* Session 管理
* Workspace 管理
* Terminal Relay

## Frontend

* Vue 3
* TypeScript
* Naive UI
* xterm.js
* Monaco Editor
* Node 與 Session 管理介面
* Workspace Browser

## VM Daemon

* Go
* Persistent WebSocket
* Runtime Detection
* PTY
* tmux
* Workspace Validation
* Filesystem Browser
* Heartbeat
* Node Enrollment

## Version 1 核心資料模型

```text
users
nodes
node_runtimes
workspaces
sessions
session_events
audit_logs
```

Version 2 將在此基礎上增加專案層資料，不修改原有模型的核心責任。

---

# 5. Version 2 目標

Version 2 的目標不是讓平台自行完成軟體開發，而是讓既有 Agent Session 具備明確的專案上下文與可追蹤工作流程。

## 核心目標

### 目標一：讓 Session 知道自己屬於哪個專案

每個 Session 可以關聯：

* Project
* Task
* Workspace
* Runtime
* Node

---

### 目標二：讓 Agent 能管理自己的工作計畫

Agent 可以建立並更新：

* Task
* Execution Plan
* Progress
* Blocker
* Verification Result
* Completion Summary

---

### 目標三：讓使用者能從平台掌握開發進度

使用者不必進入 Terminal 才知道 Agent 正在做什麼。

平台應呈現：

* 正在執行的 Task
* Agent 的執行步驟
* 已修改檔案
* 測試結果
* 尚未完成事項
* 目前阻塞原因

---

### 目標四：保留可驗證的完成紀錄

Task 完成時應保存：

* 執行過的命令
* Exit Code
* 測試結果
* 變更檔案
* Git Diff 摘要
* Acceptance Criteria 結果
* Remaining Risks

---

# 6. 升級後的整體架構

```text
User
  │
  ▼
Central Platform
├── Version 1 Capabilities
│   ├── Nodes
│   ├── Runtimes
│   ├── Workspaces
│   ├── Sessions
│   └── Terminal
│
├── Version 2 Project Layer
│   ├── Projects
│   ├── Documents
│   ├── Tasks
│   ├── Execution Plans
│   ├── Verification
│   └── Evidence
│
└── Agent Tool Interface
    ├── Read Project Context
    ├── Create or Update Task
    ├── Update Plan
    ├── Submit Verification
    └── Report Result
          │
          ▼
    Claude Code / Codex
          │
          ▼
       Workspace
```

---

# 7. Version 2 功能範圍

# 7.1 Project Management

新增 Project 作為 Version 2 最上層管理單位。

## Project 欄位

```text
ID
Name
Description
Status
Owner
Default Workspace
Default Runtime
Repository Information
Created At
Updated At
```

## Project Status

```text
Active
Paused
Archived
```

## Project 與既有資源關係

```text
Project
├── Workspaces
├── Sessions
├── Documents
├── Tasks
└── Activities
```

一個 Project 可以關聯多個 Workspace，例如：

```text
Central Platform
├── platform-backend
├── platform-frontend
├── agent-daemon
└── documentation
```

---

# 7.2 Project Documents

Version 2 提供基本專案文件管理。

## 第一階段文件類型

* Project Overview
* PRD
* Architecture
* Development Conventions
* Decision Log
* Verification Guide

## 儲存策略

建議採混合模式。

平台資料庫保存：

* 文件名稱
* 文件類型
* 版本
* 關聯專案
* 檔案位置
* 更新時間
* 更新者

實際內容可以存放於：

* Git Repository Markdown
* 平台資料庫
* 外部文件連結

Version 2 初期優先支援 Repository 中的 Markdown 文件。

> **已修訂（裁決 2）**：改為**平台 DB 為真實來源**。Monstrare 的流程與模板內化成平台功能，
> Agent 需要讀的參考文件由平台在執行時投影成檔案放進工作目錄。使用者的 repo 只有程式碼。
> 見 `research/02/01-architecture-decisions.md` D1／D2。

---

# 7.3 Task Management

Task 是 Version 2 的核心管理單位。

## Task 基本欄位

```text
ID
Project ID
Title
Description
Objective
Scope
Non-goals
Status
Priority
Risk
Workspace
Runtime Preference
Created By
Created At
Updated At
```

> **已擴充（裁決 3）**：Task 另有四個執行欄位——`source`（`none`／`repo`／`existing_branch`：
> 這張卡要不要程式碼）與 `delivery`（`none`／`branch`／`pull_request`／`existing_pr`：成果怎麼離開），
> 以及 `required_secrets` 與 `required_labels`。
> **不是每張卡都要開 PR**：調查、分析、寫規格型的任務 `delivery: none`，完成證據是摘要與驗證報告。
> 見 `research/02/01-architecture-decisions.md` D21。

## Task Status

第一版任務流程保持簡單：

```text
Backlog
Ready
In Progress
Verify
Done
Blocked
```

不導入複雜的企業審批流程。

---

## Acceptance Criteria

每個 Task 可以有多項 Acceptance Criteria。

```text
Task
├── Acceptance Criterion 1
├── Acceptance Criterion 2
└── Acceptance Criterion 3
```

每項標準具備：

```text
Description
Verification Status
Evidence Reference
Note
```

Verification Status：

```text
Pending
Passed
Failed
Not Applicable
```

---

## Dependency

Task 可關聯其他 Task。

```text
TASK-102 depends on TASK-101
```

Version 2 初期只需要：

* 建立依賴
* 顯示依賴
* 檢查循環依賴
* 顯示阻塞狀態

不需要複雜的排程引擎。

---

# 7.4 Task 與 Session 整合

Version 1 的 Session 是獨立的 CLI 執行單位。

Version 2 增加 Task 關聯。

```text
Session
├── Project
├── Task
├── Workspace
├── Node
└── Runtime
```

## 建立 Session 時

使用者可以選擇：

```text
Project
Task
Workspace
Runtime
Node
```

平台將相關資訊整理成 Context，提供給 Agent。

> **已擴充（裁決 3）**：除了使用者手動建立的 Session，任務也可以**掛上佇列讓 Agent 自行認領**，
> 在隔離的工作目錄中無人值守地執行。兩條路徑並存：互動式 Session 是「我自己來」，
> Agent Run 是「派給它做」。見 `research/02/00-upgrade-roadmap.md` §2。

---

## Session Context

建立 Session 時可以提供：

* Project Overview
* Current Task
* Acceptance Criteria
* Related Documents
* Workspace
* Development Conventions
* Verification Commands

平台應避免一次載入所有專案資料。

建議分為：

### Always Included

* Project summary
* Current task
* Acceptance criteria
* Workspace rules

### On-demand

* Complete PRD
* Architecture document
* Previous tasks
* Decision history
* Verification reports

---

# 7.5 Agent Execution Plan

Agent 在開始較複雜工作時，可以建立 Execution Plan。

## Plan 範例

```yaml
steps:
  - title: Inspect existing workspace API
    status: completed

  - title: Design directory entry response
    status: completed

  - title: Implement file tree endpoint
    status: in_progress

  - title: Add path security checks
    status: pending

  - title: Run tests
    status: pending
```

## Plan Step Status

```text
Pending
In Progress
Completed
Skipped
Failed
```

## 設計目的

Execution Plan 用於：

* 呈現 Agent 工作進度
* 讓使用者知道目前步驟
* 保存工作中斷時的狀態
* Session 恢復後繼續執行
* 發現 Agent 是否偏離 Task

平台不透過 Execution Plan 逐步控制 Agent。

Agent 仍可自行調整計畫，但修改應留下 Activity Log。

---

# 7.6 PRD 更新建議

Version 2 可以讓 Agent協助修改 PRD，但初期不應讓 Agent 靜默覆蓋正式內容。

建議流程：

```text
User Requirement
→ Agent analyzes affected PRD
→ Agent creates document patch
→ Platform displays diff
→ User accepts or rejects
```

## PRD Patch 包含

* Added Sections
* Modified Sections
* Removed Sections
* Reason
* Related Tasks
* Open Questions

Version 2 初期只實作「提案與確認」，不做複雜文件審批流程。

> **已擴充為完整階段（裁決 4）**：本節與 §7.7 原本是兩個零散的「Agent 工具」，
> 實際上它們與 Monstrare 的 `spec-interrogation`（把模糊需求**問**成規格）是同一條流程的三段：
> **釐清 → 規格核准 → 拆解 → 提案接受**。已獨立為 **V2.5**（`research/02/07-phase-v25-…`）。
>
> 兩個關鍵設計：
> 1. **提問直接走既有的看板訊息串**（Agent `task ask` → 卡片顯示「等待你的回覆」→ 使用者回答），
>    **不新增聊天介面**——兩套訊息管道會讓使用者不知道在哪回話、稽核要看兩個地方。
> 2. **Agent 的產出是提案，不是正式資料。** 人接受之後才建立真正的卡片；
>    未解決的 `open_questions` 會讓規格無法被核准。
>
> PRD patch 本身仍然**由平台渲染、由人決定、由 Agent 自己套用**——而且是走一張正常的
> `delivery: pull_request` 卡片，所以 PRD 的修改跟程式碼一樣有 PR 可審。

---

# 7.7 Agent Task Planning

Agent 可以根據需求或 PRD 產生 Task 建議。

## Agent 輸出內容

```yaml
title: Implement Workspace File Tree API

objective:
  Provide a read-only API for browsing workspace directories.

scope:
  - List directory entries
  - Support lazy directory loading
  - Return file metadata

non_goals:
  - File editing
  - File uploads

acceptance_criteria:
  - Access is limited to allowed roots
  - Path traversal is rejected
  - Symlink escape is rejected

verification:
  - Run workspace API unit tests
  - Run path security tests

risk: medium
```

## 套用方式

使用者可以：

* 接受全部
* 選擇部分 Task
* 編輯後建立
* 拒絕建議

不要求 Agent 每次先建立完整 Roadmap。

> **已納入 V2.5（裁決 4）**：拆解產出的每張 Task 提案必須自帶完整的 **Definition of Ready 七項**
> 與 V2 執行模型欄位（`source`／`delivery`／`required_labels`／`dependsOn`），缺項者接受後
> 落 `backlog` 而非 `ready`。**`delivery` 由拆解決定**——哪些卡要出 PR、哪些是純調查，
> 拆解時就分清楚比事後補救便宜得多。

---

# 7.8 Verification Management

Agent 完成實作後，可以提交結構化驗證結果。

## Verification Report

```yaml
result: passed

checks:
  - name: Unit Tests
    command: pytest tests/workspaces
    exit_code: 0

  - name: Lint
    command: ruff check app
    exit_code: 0

acceptance_criteria:
  - criterion: Reject path traversal
    result: passed

  - criterion: Reject symlink escape
    result: passed

remaining_risks:
  - Windows junction has not been tested
```

## Verification Status

```text
Not Started
Running
Passed
Failed
Partial
```

Task 不應只因 Agent 回覆「完成」而直接進入 Done。

最低完成條件：

* 有 Completion Summary
* Acceptance Criteria 已填寫結果
* 有 Verification Report
* 沒有未處理的 Critical Failure

---

# 7.9 Evidence Management

Evidence 分為自動蒐集與 Agent 補充。

## 平台或 Daemon 自動蒐集

* Command
* Exit Code
* Started At
* Finished At
* stdout／stderr 摘要
* Changed Files
* Git Branch
* Git Commit
* Diff Statistics
* Test Report Path

## Agent 補充

* Completion Summary
* Findings
* Known Limitations
* Remaining Risks
* Recommended Follow-up

## Evidence 關聯

```text
Evidence
├── Project
├── Task
├── Session
└── Verification Report
```

> **已擴充（裁決 5）**：Evidence 之外新增**任務卡產物**（`task_artifacts`）——Agent 可以在執行中或完成時，
> 把報告、截圖、diff、mockup 等檔案直接附到任務卡上，也可以用留言附檔的方式。
>
> 三個設計要點：
> 1. **產物存平台，不留在 node。** run 目錄有保留期（成功 3 天／失敗 14 天），但卡片是永久的——
>    留在 node 上三天後卡片會是一堆死連結。
> 2. **run log 與卡片產物的保留期不同**：log 是**診斷**（到期即刪），產物是**交付物**（跟著卡片走）。
> 3. **提供時預設下載不內嵌渲染**（`Content-Disposition: attachment` ＋ `nosniff`）。
>    Cliora 是單一 origin 部署，直接渲染 Agent 產生的 HTML 等於 stored XSS。
>
> 交付模式因此從四種變五種，新增 `delivery: artifact`。見 `research/02/01-architecture-decisions.md` D29。

---

# 7.10 Activity Timeline

平台應為 Project、Task 與 Session 保存事件。

例如：

```text
Task created
Task moved to In Progress
Session started
Execution plan updated
File changed
Verification started
Verification failed
Agent resumed implementation
Verification passed
Task marked Done
```

Activity Timeline 是使用者理解 Agent 工作歷史的重要功能。

---

# 8. Agent Tool Interface

Version 2 應提供標準工具介面，讓 Claude Code、Codex 或其他 Runtime 可以讀寫專案管理資料。

可以使用：

* MCP Server
* Local CLI
* HTTP API
* Daemon Proxy

建議優先採 MCP 或 CLI Wrapper，避免 Agent 直接存取平台資料庫。

> **已確認並提前（裁決 2）**：採 CLI 優先、MCP 為同源第二外殼。因為真實來源翻面為平台 DB，
> 這個介面從「便利品」變成**前提**——沒有它 Agent 無法記錄任何工作，所以提前到 V2.1 首發。
> 另新增看板溝通工具（`cliora task say`／`ask`／`messages`），讓使用者透過卡片與執行中的 Agent 對話。
> 見 `research/02/01-architecture-decisions.md` D11／D24。

## 建議工具

```text
project.get
project.get_context
project.list_documents
project.read_document
project.propose_document_patch

task.get
task.list
task.create
task.update
task.set_status
task.add_dependency

plan.create
plan.update_step
plan.complete

verification.create
verification.add_check
verification.submit

evidence.add_command
evidence.add_finding
evidence.add_file

activity.add
```

## 權限原則

Agent 可以：

* 建立 Task
* 更新 Execution Plan
* 提交 Verification
* 新增 Evidence
* 建議 PRD 修改

Agent 不應直接：

* 刪除 Project
* 修改使用者權限
* 修改 Node 設定
* 繞過 Workspace 限制
* 直接修改資料庫
* 靜默覆蓋正式 PRD

---

# 9. 前端升級規劃

Version 2 延續原本：

> Quiet Intelligence＋Developer Workbench＋Modern Industrial

視覺方向。

## 新增主選單

```text
Projects
Tasks
Sessions
Infrastructure
```

Version 1 原有功能可重新整理為：

```text
Infrastructure
├── Nodes
├── Workspaces
└── Runtimes
```

---

## Project Overview

顯示：

* Project Description
* Active Tasks
* Running Sessions
* Progress
* Recent Activity
* Workspace Status
* Verification Summary

---

## Project Board

欄位：

```text
Backlog
Ready
In Progress
Verify
Done
Blocked
```

卡片顯示：

* Task ID
* Title
* Priority
* Risk
* Assigned Session
* Runtime
* Verification Status

---

## Task Detail

```text
+----------------------------------------------------------+
| TASK-123  Workspace File Tree API             In Progress|
+-----------------------------+----------------------------+
| Task Definition             | Agent Execution            |
|                             |                            |
| Objective                   | Runtime: Codex             |
| Scope                       | Node: dev-vm-01            |
| Non-goals                   | Workspace: backend         |
| Acceptance Criteria         | Session: Running           |
| Dependencies                |                            |
| Verification                | [Open Terminal]            |
| Evidence                    | [Resume Session]           |
+-----------------------------+----------------------------+
| Execution Plan                                           |
+----------------------------------------------------------+
```

---

## Session Workspace

Version 1：

```text
Terminal | Workspace
```

Version 2：

```text
Plan | Terminal | Workspace | Task
```

> **不採用四欄（已修訂）**：`plan/08` 已把三欄改為兩欄 ＋ 中央區 tab 並放棄面板拖曳收合，
> `plan/09` 又把 sidebar 收窄把空間讓給 Terminal。四欄會一次推翻這些決定。
> 改為右欄 tab 化（Task／Plan／Files），Terminal 寬度完全不變。
> 見 `research/02/08-frontend-information-architecture.md` §5。

建議配置：

```text
+----------------------------------------------------------+
| Project / Task / Runtime / Node                          |
+------------+--------------------------+------------------+
| Plan       | Terminal                 | Workspace        |
|            |                          |                  |
| ✓ Inspect  |                          | src/             |
| ● Develop  |                          | tests/           |
| ○ Verify   |                          | README.md        |
+------------+--------------------------+------------------+
| Task Status | Verification | Git Branch | Session State  |
+----------------------------------------------------------+
```

Terminal 仍是主要工作區。

---

# 10. Backend 升級規劃

Version 2 建議新增模組：

```text
app/
├── projects/
├── documents/
├── tasks/
├── plans/
├── verification/
├── evidence/
├── activities/
└── agent_tools/
```

## 新增資料表

```text
projects
project_members
project_workspaces

documents
document_versions
document_patches

tasks
task_dependencies
task_acceptance_criteria
task_sessions

execution_plans
execution_plan_steps

verification_reports
verification_checks

evidence_items
activity_events
```

> **已修訂（裁決 2、3）**：`documents`／`document_versions`／`document_patches` **不建表**（文件在 repo）；
> `task_acceptance_criteria`／`verification_checks` 併入 JSONB；
> 新增 `agent_runners`／`project_agents`／`task_runs`／`run_logs`／`task_messages`／
> `project_secrets`／`project_repositories`。
> 另注意：本文件寫的 `sessions` 表，實際名稱是 **`terminal_sessions`**。
> 見 `research/02/07-data-model-and-contract.md` §2。

## 既有資料表調整

### sessions

增加可選欄位：

```text
project_id
task_id
```

### workspaces

增加 Project 關聯表，不直接限制一個 Workspace 只能屬於一個 Project。

---

# 11. Daemon 升級規劃

Version 2 不要求大幅改寫 Daemon。

## 建議新增能力

* Session command event capture
* Exit code capture
* Git state retrieval
* Changed file listing
* Test report file collection
* Evidence file upload
* Agent tool proxy
* Session environment injection

> **兩處需修正（重要）**：
>
> 1. **「Session environment injection」不能照字面做。** SEC-002 明定呼叫端不得指定 argv 或環境變數，
>    `StartOptions` 只有 `SessionID`／`Workspace`／`Rows`／`Columns`。互動式 Session 的情境改用
>    **檔案投影**交付。Agent Run 路徑確實需要環境變數，但值只能來自平台的 secret store、
>    名稱須在專案 allowlist 內、且永不進入任何日誌——這是對 SEC-002 的**精確修訂**，不是取消。
> 2. **「Session command event capture／Exit code capture」對互動式 Session 做不到。**
>    終端位元組從不儲存（PRD、ADR 0013），解析 PTY 猜命令不可靠且違反既有承諾。
>    **但在 Agent Run 路徑上做得到**：驗證命令由 daemon 在隔離目錄內執行，exit code 是真的機器事實。
>    兩條路徑的隱私語意不同，不可混為一談。
>
> 見 `research/02/01-architecture-decisions.md` D10／D23／D27。

## 不應加入 Daemon 的功能

* PRD 分析
* Task 拆解
* Project workflow 判斷
* Agent planning logic
* Verification 結論判斷

Daemon 只負責執行與資料蒐集。

---

# 12. 分階段升級路線

# V2.0：Project Foundation

## 目標

建立 Project 與既有 Workspace、Session 的關係。

## 範圍

* Project CRUD
* Project Workspace 關聯
* Project Session 關聯
* Project Overview
* Project Activity
* 基本 Documents
* Session 建立時選擇 Project

## 不包含

* Task Board
* Execution Plan
* Verification
* Evidence 自動蒐集

## 完成條件

使用者可以從 Project 進入相關 Workspace 與 Session。

---

# V2.1：Task and Session Integration

## 目標

讓 Session 有明確 Task。

## 範圍

* Task CRUD
* Kanban Board
* Acceptance Criteria
* Task Dependency
* Task 與 Session 綁定
* Task Detail
* 從 Task 啟動 Session
* Agent Task Context Injection

## 完成條件

每次 Agent 開發工作都可被關聯到 Project 與 Task。

---

# V2.2：Planning and Verification

## 目標

讓 Agent 能回報規劃與驗證過程。

## 範圍

* Execution Plan
* Plan Step 更新
* Verification Report
* Acceptance Criteria 驗證結果
* Completion Summary
* Task Done 基本 Gate
* Session Workspace 的 Plan Panel

## 完成條件

使用者可以在平台上看到 Agent 正在做什麼，以及完成時執行過哪些驗證。

---

# V2.3：Evidence and Project Intelligence

## 目標

提升專案追蹤完整度與 Agent 使用體驗。

## 範圍

* Command Evidence
* Exit Code
* Git Diff 摘要
* Changed Files
* Evidence Files
* PRD Patch Proposal
* Agent Task Generation
* Context On-demand Loading
* Project Progress Summary
* Risk 與 Blocker 摘要

## 完成條件

平台可以完整回答：

* Agent 修改了什麼
* 為什麼修改
* 執行了哪些驗證
* 驗證是否成功
* 還有哪些風險

---

# 13. 明確不納入 Version 2 的功能

為控制複雜度，以下項目不納入 Version 2 主範圍：

* 多 Agent 自動協作
* Agent 自動派工
* Agent 組織架構

> **需要精確化（裁決 3）**：「Agent 自動派工」被撤銷的只有一半——
> **任務認領納入範圍**（Agent 主動領走符合資格的卡片，像 GitHub Runner，拉取式）；
> **自動指派仍不納入**（平台不做排程器、不做負載平衡、不替你決定誰做什麼）。
>
> 任務卡**可以指定特定 Agent，也可以不指定**（預設不指定）。指定在拉取模型裡只是 poll 查詢的一個
> 過濾條件，不是推送；而且**指定永遠不能繞過 Project ↔ Agent 的綁定授權**，否則它會變成一條授權旁路。
>
> 多 Agent 協作、Agent 互相派工、組織架構仍全部不做。
* 跨 Agent 訊息佇列
* 自動 Sprint 排程
* 工時預測
* 複雜資源最佳化
* 完整 Jira 替代功能
* 自動 Merge  ← **這一條在 V2 升級為紅線**：Agent 的產出只能落在 PR 或獨立分支，永不自動合併
* 自動 Production Deployment
* 自動核准高風險變更
* 視覺化 Workflow Designer

這些能力只有在 Version 2 穩定並確認使用需求後才評估。

---

# 14. 技術風險

## 14.1 Agent 輸出不穩定

Agent 可能無法每次產生完全一致的 Task、Plan 或 Verification 格式。

### 對策

* 定義 JSON Schema
* 平台驗證輸出格式
* 無效輸出不可直接寫入
* 提供 CLI／MCP Tool，而非依賴文字解析
* 允許 Agent 分步提交資料

---

## 14.2 Context 過大

完整 PRD、Architecture、Task History 與 Repository 資訊可能超過合理 Context。

### 對策

* 區分 Always Loaded 與 On-demand
* 使用文件摘要
* 依 Task 關聯文件
* 只載入相關 Acceptance Criteria
* 允許 Agent 主動查詢需要的資料

---

## 14.3 Agent 錯誤標記完成

Agent 可能在測試不足時回報完成。

### 對策

* Done 需要 Verification Report
* Acceptance Criteria 必須逐項有結果
* Daemon 自動保存 Exit Code
* 失敗測試不可被隱藏
* 顯示 Remaining Risks

---

## 14.4 Version 2 影響 Version 1 穩定性

專案管理功能可能增加 Session 啟動流程的複雜度。

### 對策

* Project 與 Task 關聯全部允許為空
* 保留純 Terminal Session
* Version 2 功能以 Feature Flag 啟用
* 不修改 PTY 與 tmux 核心流程
* Agent Tool Interface 與 Terminal Relay 分離

---

# 15. 向下相容策略

Version 2 必須保留 Version 1 的使用方式。

使用者仍可直接：

```text
選擇 Node
→ 選擇 Runtime
→ 選擇 Workspace
→ 啟動 Session
```

Project 與 Task 為可選項。

因此平台同時支援：

## Managed Session

```text
Project + Task + Workspace + Runtime
```

## Ad-hoc Session

```text
Workspace + Runtime
```

Ad-hoc Session 適合：

* 臨時問題排查
* 環境檢查
* 小型修改
* 不需要專案管理的 CLI 操作

---

# 16. Version 2 成功指標

## 使用指標

* 有 Project 關聯的 Session 比例
* 有 Task 關聯的 Session 比例
* Task 由平台啟動 Session 的比例
* 有 Execution Plan 的 Task 比例
* 有 Verification Report 的完成 Task 比例

## 品質指標

* 無驗證直接完成的 Task 數量
* Verification Failed 後重新修正的比例
* Task Blocked 原因可識別率
* Agent Session 中斷後成功恢復率

## 效率指標

* 從需求建立到開始執行的時間
* 使用者人工整理 Task 的時間
* 使用者進入 Terminal 查看進度的次數
* Agent 重複讀取專案背景的次數

---

# 17. 建議開發順序

Version 1 完成後，不應立即全面開始 Version 2。

建議先進行 Version 1 穩定期。

## Version 1 穩定期

建議先確認：

* Session 建立與恢復穩定
* 多 Node 連線穩定
* Workspace 權限安全
* Terminal 長時間連線正常
* Runtime 切換正常
* Daemon 更新機制可用
* Audit Log 完整
* 使用者實際使用流程成熟

完成後再進入 Version 2。

## Version 2 開發優先順序

```text
Project
→ Task
→ Task-linked Session
→ Execution Plan
→ Verification
→ Evidence
→ PRD and Task Agent Tools
```

不要先做 Agent 自動生成 PRD。

先建立可靠的資料結構與人工操作流程，再讓 Agent 使用相同 API。

> **這一段被完整採納，而且決定了 V2.5 的排程（裁決 4）**：
> `requirements`／`feature_specs`／`task_proposals` 三張表與**人工表單**在 **V2.1** 就交付，
> 讓人可以自己寫規格、自己拆卡；**V2.5** 只是讓 Agent 走同一條 API。
> 若 V2.1 的人工流程沒人用，那就是 V2.5 值不值得做的免費早期訊號
> （量測項 M14，見 `research/02/10-verification-and-exit.md` §5）。

---

# 18. 最終升級結果

Version 1 完成後，平台具備：

```text
Node Management
Runtime Management
Workspace Management
Remote Terminal
Persistent Session
File Browser
```

Version 2 完成後，平台進一步具備：

```text
Project Management
Task Management
Agent Planning Visibility
Task-linked Session
Verification Management
Evidence Collection
Project Context
PRD Update Assistance
```

完整演進路徑：

```text
Remote CLI Management
        ↓
Project-aware CLI Sessions
        ↓
Agent Planning and Verification
        ↓
AI Development Control Plane
```

Version 2 的核心不是增加更多 Agent，而是讓原本的 Claude Code 或 Codex Session 擁有專案上下文、任務結構與成果紀錄。

最終讓 Agent 能在同一個工作流程中完成：

```text
理解需求
→ 規劃工作
→ 執行開發
→ 驗證成果
→ 留下紀錄
```

而平台持續負責：

```text
管理環境
管理狀態
管理專案
管理進度
管理證據
```

這樣可以保留 Version 1 的簡單與穩定，同時為 Version 2 建立清楚、可漸進開發且不過度複雜的升級方向。
