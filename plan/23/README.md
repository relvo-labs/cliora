# Cliora `v2.0.0-alpha.2` — Ticket-native Agent Conversation

> **狀態：計畫已定稿，A 類四項裁決已完成（2026-08-16），可開工。**
> 2026-08-16 開立。
> 前置條件是 `v2.0.0-alpha.1` 的 freeze checklist（[`research/03/00`](../../research/03/00-roadmap-and-versioning.md) §6）。
> **合併規則不變**：`v2` → `dev` 一律由人決定，出口條件全綠只是取得提案資格。

本目錄是 [`research/03/02-phase-c1-ticket-conversation.md`](../../research/03/02-phase-c1-ticket-conversation.md)
的執行計畫，ticket 統一使用 `CV-` 前綴（**C**on**v**ersation）。

規劃層回答「這一期要做什麼、為什麼」；本目錄回答
「在**這個 repo 的現況**上怎麼做得出來、做完怎麼證明」。

---

## 這一期真正的形狀

一句話：

> 平台已經有一條「Agent 提問、人在卡片上回答」的路。**那條路只有在 Agent 的 process
> 一直活著的時候才走得通**——它一結束，`run.complete` 就把 run 收成 `succeeded`，
> 對話就結束了。這一期把「對話」從「那個 process 還活著」這件事上拆下來。

### 已經在庫裡的東西（比想像中多）

| 東西 | 現況 | 位置 |
|---|---|---|
| `task_messages` 表 ＋ 四種 `kind` | **已存在**（`0029`） | `models.py:1196-1213` |
| `POST/GET /api/tasks/{id}/messages`（人） | **已存在** | `api/http/agents.py:511-557` |
| `POST/GET /api/cli/runs/messages`（Agent） | **已存在** | `api/http/agents.py:769-816` |
| `cliora task say`／`ask`／`messages` | **已存在** | `daemon/internal/cli/command.go:162-232` |
| 「一個 run 一次一個未答問題」 | **已實作**，server 409 ＋ CLI 本地提示 | `services/runs.py:1331-1385`、`cli.go:530-557` |
| `waiting_for_input` run 狀態 ＋ 不被租約 sweep 回收 | **已實作** | `services/runs.py:80-83`、`api/http/agents.py:806-813` |
| 24 小時未回覆 → 卡片退 `blocked` | **已實作** | `services/run_reaper.py:120-170` |
| 訊息串 UI ＋ 回覆框 | **已存在**（332 行） | `components/project/TaskAgentPanel.vue` |
| 原子認領（`claim`）與租約、重排 | **已實作** | `services/runs.py:1396-1430` |
| run token（`project.view` ＋ `task.update`），認領時發、結束時撤 | **已實作** | `services/agent_auth.py:70`、`runs.py:1031` |

### 五個真正的缺口（讀完程式碼才看得到的那種）

| # | 缺口 | 證據 | 修在哪 |
|---:|---|---|---|
| 1 | **分頁用時間戳。** `--since` 與 `list_for(since=)` 比對 `created_at`；同一毫秒的兩則訊息會重複或遺漏 | `runs.py:1278-1285`、`command.go:217` | `CV-03`／`CV-04` |
| 2 | **「回答」沒有被關聯到「問題」。** `pending_question()` 的規則是「**任何**使用者訊息，只要時間在問題之後，就算答了」 | `runs.py:1331-1365` | `CV-03`／`CV-05` |
| 3 | **Agent 的 process 一結束，對話就結束。** daemon 從不送 `run.progress {waiting_for_input}`；它送的是 `run.complete`，而 `finish()` 無條件把 run 收成 `succeeded` | `run_handlers.go:503-522`、`runs.py:1003-1012` | `CV-07` |
| 4 | **沒有冪等鍵。** POST 重送就是第二則一模一樣的訊息 | `models.py:1196-1213` 無此欄 | `CV-04` |
| 5 | **前端用「最後一則訊息是什麼 kind」猜等待狀態** | `TaskAgentPanel.vue:126-129` | `CV-13`／`CV-10` |

**第 3 條是這一期的核心。** 其餘四條都是它的前置或後果。

---

## 這一期的風險形狀

```text
                       V2.0–V2.4        V2.5（RQ）      本期（CV）
 新的對外副作用          有               零              **零**
 新的執行能力            有               零              **零**（不新增 run 種類）
 新的憑證                有               零              **零**
 contract               v1.10→v1.13     不動            **不動**（D44）
 daemon 的節點半邊        每期都動         只動 CLI        **只動 CLI**
 主要工作落在哪           daemon ＋ Central Central ＋ 前端  **Central**
 風險的形狀              「平台做了不該做的事」「Agent 的話變成事實」 **「同一句話被做了兩次」**
```

**本期唯一的新風險是傳遞語意的。** 會出事的方式只有兩種：

1. **同一個 answer 讓 Agent 跑了兩次**（重複 continuation、重複回覆、重複 push）。
2. **一句普通留言被當成核准**（`comment` 誤 resume、`answer` 誤 approve、
   Agent 的 `decision` 被接受）。

所以本期的閘門幾乎全部長成這兩個形狀：**單調序號 ＋ 冪等鍵 ＋ 單列 CAS**，
以及 **`decision` 這個 kind 只有帶人類 actor 的路徑寫得到**。

---

## 八個裁決，四個已定

完整表格在 [`00-execution-plan.md`](./00-execution-plan.md) §0，狀態表在 [`10`](./10-implementation-status.md) §0。

**A 類（擋開工）四項全部於 2026-08-16 裁決，全部採納計畫的答案——所以本期可以開工：**

| 決策 | 裁決 |
|---|---|
| **D44** `alpha.2` 動不動 contract | ☑ **不動**（維持 1.13.0） |
| **D59** process 結束時 run 怎麼收 | ☑ **Central 在 `finish()` 推導 `awaiting_input`** |
| **D42** 放不放寬單一未答問題 | ☑ **不放寬** |
| **D61** 歷史問題怎麼 backfill | ☑ **用現行規則判定已答** |

**B 類（不擋開工，但會改寫某一節）四項待定：**

- **D60** — continuation run 的分支名。計畫的答案：**沿用 root run 的 seq**，
  否則第二輪會 push 到 `cliora/TK-142-3` 而 PR 指著 `-2`。
- **D65** — continuation 情境包放哪個 renderer，以及 `GATE-RQ-CONTEXT-DISPATCH` 怎麼改。
- **D66** — 兩種等待（process 還活著／已釋放）要不要都保留。計畫的答案：**都保留，
  但只有一個投影。**
- **D51** — conversation 的保留與附件政策。計畫的答案在 [`01`](./01-decisions-and-governance.md) §3.5。

---

## 文件導覽

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 八項裁決（**A 類四項已定**）、四個波次、14 張 ticket、依賴圖、禁區清單 |
| [01-decisions-and-governance.md](./01-decisions-and-governance.md) | D59–D66 全文，以及從 `research/03` 繼承的六項 |
| [02-data-layer.md](./02-data-layer.md) | migration `0040`：兩張新表、三張表 12 個欄位、backfill、索引、rollback |
| [03-conversation-api.md](./03-conversation-api.md) | cursor 分頁、冪等寫入、六種 kind、九個 machine code、DTO |
| [04-answer-resume-and-turns.md](./04-answer-resume-and-turns.md) | **本期核心**：單一交易、question CAS、child run、run 生命週期與 reaper 的改動 |
| [05-context-pack-and-runner.md](./05-context-pack-and-runner.md) | 情境包 v2、分支繼承、gate 修改、**為什麼 daemon 的節點半邊不動** |
| [06-cli.md](./06-cli.md) | `messages --after`／`wait`／`say --reply-to`／`propose-spec`、`--since` 的退場 |
| [07-frontend.md](./07-frontend.md) | 訊息串、question card、兩個動作、delivery state、拆 `TaskAgentPanel` |
| [08-verification-and-exit.md](./08-verification-and-exit.md) | 七個新 gate、測試矩陣、六條 E2E、SR-1 安全審查、出口條件 |
| [09-open-measurements.md](./09-open-measurements.md) | 六個不量的東西與不量的理由 |
| [10-implementation-status.md](./10-implementation-status.md) | 實作後回填；**與計畫不同時以這裡為準並回寫計畫** |

## 建議使用方式

1. 先讀 [`00`](./00-execution-plan.md) §0。**A 類四項已於 2026-08-16 全部裁決，可以開工。**
2. B 類四項（D60、D65、D66、D51）在各自的 ticket 開工前定即可；
   最早需要的是 **D60**（`CV-03` 的 `root_run_id` 欄位）與 **D51**（`CV-03` 的 schema）。
3. 每張 ticket 以「決策 → 契約 → 實作 → 自動測試 → 操作證據」完成。
4. 出口條件未通過，不建立 `v2.0.0-alpha.2` tag。
5. 實作與計畫不一致時，**寫進 [`10`](./10-implementation-status.md) 並回寫本目錄**。

## 基線（開工前確認）

| 項目 | 值 |
|---|---|
| 起點 commit | `f91d9c4`（`v2.0.0-alpha.1` 的 tag target） |
| migration head | `0039_requirements_agent_driven` → 本期到 **`0040`** |
| contract | **1.13.0，不動** |
| `agentd` | **0.12.0 → 0.13.0**（只有 CLI 子命令，節點半邊不動） |
| RBAC | 24 個動作，**不新增** |
| ADR | 到 `0034` → 本期新增 **`0035`、`0036`、`0037`、`0041`** |
| 新需求 | `FR-CONV-001`…`-010`（10 條，見 [`research/03/11`](../../research/03/11-requirement-traceability.md) §2） |
