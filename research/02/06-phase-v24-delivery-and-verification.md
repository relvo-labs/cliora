# V2.4 — 交付、驗證與證據（ticket 前綴 `DV-`）

> **執行計畫在 [`plan/21/`](../../plan/21/README.md)，讀了程式碼之後有十七處與本文不同**
> （完整差異表在 `plan/21/README.md`）。**三處已於 2026-08-14 裁決**：
>
> 1. ✅ **驗證命令從哪裡來 → 兩個來源都要。** 本文 DV-04 寫「來自 Project 設定」，
>    `01` D10 例外 2 寫「**卡片宣告的**驗證命令」——**不再二選一**：
>    兩者都做，用一個 `origin` 欄位分辨。**關鍵的一道**是卡片宣告需要
>    **`task.approve`**（`RUN_TOKEN_SCOPES` 永遠不含它，`agent_auth.py:70`），
>    所以人可以宣告、Agent 不行，`machine_verified` 的可信度因此保住。
> 2. ✅ **`existing_pr` 的範圍 → 縮範圍。** 五條硬約束只允許推 `cliora/` 前綴的分支
>    （V2.3 已交付、已通過安全審查），所以「推到既有 PR 的分支」
>    **只對平台自己開的 PR 成立**，其餘在 dispatch 當下拒絕。
> 3. ✅ **provider 先做 GitHub 一家**；GitLab 留介面不實作。
>
> 另外一處不需要裁決但改變了本文的形狀：
> **PR 由 Central 開，`delivery: pull_request` 在 wire 上表現為 `branch`**——
> daemon 端的 `runDeliverySet` 只有三個值，而收到未知值時它**靜默丟棄整個 offer**。
>
> 其餘十三處是修正（規劃的假設與現況不符）。

## 目標

讓一次 run 的成果**以正確的形式離開隔離目錄**，並讓平台能回答「這件事憑什麼算做完」。

這是紅線 5 落地的階段：出口只有三種，沒有第四種。

## 前置條件

- V2.3 出口條件全數通過。
- D9、D10、D21、D25 已裁決；PR／MR 供應商（GitHub／GitLab）已選定。
- ADR 0033（交付模式與 PR 建立）已撰寫並接受。

## 工作包

### DV-01 — ADR 0033：交付模式

**核心是 D21 的兩張表**：`source` 四值、`delivery` **五值**，以及它們為什麼是兩個獨立欄位（要不要程式碼、成果怎麼離開，是兩個問題）。

| `delivery` | daemon 做什麼 | 完成的證據是什麼 |
|---|---|---|
| `none` | **什麼都不推** | 完成摘要 ＋ 驗證報告 ＋ 卡片訊息 |
| **`artifact`** | **什麼都不推**；產物已在卡片上（D29） | **至少一件卡片產物** ＋ 完成摘要 |
| `branch` | push `cliora/<card_ref>-<run_seq>` | 分支連結 ＋ diff 摘要 |
| `pull_request` | push ＋ 開 PR／MR（target = `target_branch`） | PR 連結 ＋ diff 摘要 |
| `existing_pr` | push 到既有 PR 的分支 | 追加的 commit ＋ PR 連結 |

> **`artifact` 與「附加產物的能力」不是同一件事**（D29 §2）：任何 run 隨時都能附產物；`delivery: artifact` 只是宣告「這張卡的完成證據就是產物」。一張 `pull_request` 的卡照樣可以在執行中附測試報告與截圖——**附件是過程證據，delivery 是成果形式。**
>
> 調查、分析、產出報告這類任務，用 `artifact` 比 `none` 更精確：`none` 是「真的什麼都不留」，`artifact` 是「留下的是一份可下載的東西」。

**三個誠實性規則**（要寫進 Decision，不是註腳）：

1. **`delivery: none`／`artifact` 但工作目錄有變更 → 不得靜默丟棄。** 結果標示「本卡宣告不產出程式碼變更，但偵測到 N 個檔案變更」，並**把 diff 直接附成一件產物**（D29 §7）。那份工作就不會消失在被清掉的 run 目錄裡，而是變成卡片上一個可下載的 patch。
2. **沒有變更就沒有 PR。** `delivery: pull_request` 但 diff 是空的 → run 成功、結果「無變更」、不開空 PR。
3. **`delivery: artifact` 但一件產物都沒有 → run 不算成功。** 宣告了要交付卻沒交付，不能算完成。

**Alternatives rejected**：只有一種交付模式（會逼所有調查型任務開空 PR）、讓 delivery 由 Agent 自行決定（那是卡片的意圖，不是執行者的選擇）、允許 `merge` 作為第六種模式（紅線 5，且 `version2.md` §13 已明列不做）。

### DV-02 — PR／MR 建立

- 供應商整合走 secret store 的 `kind=provider_token`（V2.3 已有），**不與 `tunnel_integration` 混用**。
- PR 內容由平台產生：標題帶 `card_ref`、內文含目標、驗收標準與逐項結果、驗證摘要、殘留風險、run 連結。**這正好是 Monstrare `verification-report.md` 模板的內容**——內化的流程在這裡變成 PR 描述。
- PR 建立失敗（權限、衝突、target 不存在）不讓整個 run 失敗：分支已經推上去了，結果標為 `delivered_branch_only` 並說明原因，讓人手動開。
- **永不自動合併、永不 approve 自己的 PR、永不關閉別人的 PR。**

### DV-03 — 執行計畫（D9）

migration `0028` — `execution_plans`：`task_id`、`run_id`、`seq`、`note`、`steps` JSONB、`created_by`、`created_at`。唯一鍵 `(task_id, seq)`，**只 INSERT 不 UPDATE**。

`steps[].status` 五值照 `version2.md` §7.5：`pending`／`in_progress`／`completed`／`skipped`／`failed`。改計畫必須有 `note`（為什麼改）——那是 §7.5「修改應留下 Activity Log」的具體形式。

Agent 用 `cliora plan snapshot` 提交。畫面顯示 `seq` 最大的一列，歷史可展開。

### DV-04 — 驗證報告與可信度分級（D10）

migration `0028` — `verification_reports`：`task_id`、`run_id`、`result`、`checks` JSONB、`acceptance_criteria` JSONB、`remaining_risks` JSONB、`completion_summary`、`source`、`reported_by`、`reported_at`。

`result` 五值、AC 四值，照 `version2.md` §7.8。

**`source` 三級，由伺服器端決定，不看 payload**：

| `source` | 誰產生 | UI |
|---|---|---|
| `agent_reported` | Agent 透過 CLI 提交 | 「Agent 自述」，exit code 不加粗，旁註「未經平台驗證」 |
| `platform_observed` | 平台自己看到的（run 狀態、push 結果、PR 建立） | 「平台紀錄」 |
| `machine_verified` | **daemon 在 run 內執行的驗證命令與其 exit code** | 「機器事實」 |

> **D10 的一個修訂**：原本否決「平台代跑驗證命令」，理由是那需要一條通用的任意執行路徑。**在 Agent Run 路徑上這個理由不成立**——run 本來就在執行 CLI，隔離目錄本來就是它的沙箱。所以驗證命令由 daemon 在 run 內執行、擷取真實 exit code，`source` 是 `machine_verified`。
>
> **仍然否決的是**：對任意 node、在 run 之外執行任意命令的 API。那條路徑不存在，也不會存在。驗證命令來自 Project 設定（Admin 維護），不是卡片、不是請求 payload。

### DV-05 — Done Gate（強制）

接到 V2.1 已建好的 `PATCH /api/tasks/{id}` 與 run 完成路徑上：

```text
TASK-123 進入 done 的前提
  ✅ 有 Completion Summary
  ✅ 每一項 Acceptance Criteria 都有結果
  ✅ 有 Verification Report
  ✅ 沒有未處理的 Critical Failure
  ✅ dependsOn 全部 done                    ← V2.1 已上線
  ✅ 依 delivery 的交付證據齊備              ← 本階段新增
       none         → 不要求任何產物
       artifact     → 至少一件卡片產物
       branch       → 有分支連結
       pull_request → 有 PR 連結（或明確的「無變更」結論）
       existing_pr  → 有追加的 commit
```

`delivery: none`／`artifact` 的卡**不能**用「有沒有 PR」當完成證據——這正是 D21 存在的理由。

**`--force` 出口**：Admin 可強制推進，需必填理由，理由進 `activity_events` 並在 Task Detail 永久可見。沒有這個出口，第一次遇到「驗證環境壞掉但工作確實完成」時，使用者會開始繞過整個系統。

### DV-06 — Evidence

migration `0029` — `evidence_items`：`task_id`、`run_id`、`project_id`、`kind`、`source`、`written_by`、`payload`、`collected_at`。

`kind`：`git_state`／`changed_files`／`diff_stat`／`command_result`／`run_event`／`delivery`／`agent_finding`／`agent_limitation`／`agent_risk`。

git 狀態由 daemon 在 run 內以固定 argv 擷取（`rev-parse`、`status --porcelain`、`diff --stat`），`source` 為 `machine_verified`。這比原規劃簡單得多——run 已經在 repo 裡了，不需要獨立的 git 查詢訊息。

**矛盾不仲裁**：Agent 自述的變更檔案與 `git status` 不一致時，兩者都顯示、都標來源。平台不猜誰對。

### DV-07 — 專案智能與指標

- Project Overview：進度（Epic／User Story 聚合）、風險摘要、阻塞摘要、驗證摘要、**Agent 產能**（近 7 天完成的 run、平均時長、失敗率）。
- 跨專案 Dashboard，先做五個指標：有 run 的 Task 比例、有 Verification Report 的完成 Task 比例、用 `--force` 略過 Done Gate 的次數、run 失敗率與失敗原因分布、`waiting_for_input` 的平均等待時間。
- 最後一個是產品健康度指標：等太久代表 Agent 問太多、或人回太慢，兩種都要知道。

### DV-08 — 流程可設定性（D15 最小版）

`process_definitions` 從全域種子變成 Project 可覆寫：**只允許啟用／停用既有項目**（關掉某幾項 readiness、某幾個 gate、調 WIP 建議值），**不允許新增自訂項目、不允許改車道**。新增動作 `process.manage`（Admin）。

理由：跨專案指標要能聚合，欄位不同就無法比。可設定性是最容易在沒有使用者的情況下被過度設計的東西。

## 這一階段明確不做

- **不做自動合併**（紅線 5、`version2.md` §13）。
- 不做自動部署、不做 release／tag。
- 不做 approve／request-changes 等 PR 審查動作。
- 不做流程編輯器（`00` §9）。
- 不開放「對任意 node 執行任意命令」的 API（DV-04 的修訂只在 run 內成立）。
- **不做 PRD patch 提案與任務建議**——它們屬於 V2.5 的釐清與拆解（`07` RQ-06）。
- **MCP 外殼是條件性的**：只在 M2／M5 指向要做時才建（`01` D11 的決策規則）。transport 已定為 **stdio**（`cliora mcp` 子命令，隨 `agentd` 附帶），**只在 Agent Run 路徑自動配置**——互動式 Session 的工作目錄是使用者的 repo，平台不代寫 MCP 設定（D2 的同一條邊界）。

## 出口條件

1. **五種** `delivery` 各跑通一次；`none` 與 `artifact` 都不產生任何遠端變更。**對 `Lei-k/Traqora` 開出第一個真實 PR**（D30）——這是整個 V2 的第一次真實交付。
2. `delivery: none`／`artifact` 但工作目錄有變更 → 明示「偵測到 N 個檔案變更」**並把 diff 附成一件卡片產物**，未靜默丟棄。
2b. `delivery: artifact` 但一件產物都沒有 → **run 不算成功**，結果說明缺什麼。
3. `delivery: pull_request` 但無變更 → run 成功、結論「無變更」、**沒有空 PR**。
4. PR 建立失敗 → 分支仍在、結果標 `delivered_branch_only`、原因可讀、**run 不算失敗**。
5. daemon 嘗試自動合併 → 程式碼裡不存在這條路徑（以「不存在」為驗收方式：對 daemon 的 git 子命令 allowlist 斷言）。
6. 驗證命令的 exit code 是真的（故意讓測試失敗，看報告是不是 `failed` 而不是 Agent 自稱的 `passed`）。
7. Agent 在 payload 帶 `source: machine_verified` → 伺服器忽略、存為 `agent_reported`、記一筆 activity。
8. `delivery: none`／`artifact` 的卡片可以正常進入 `done`，不因為缺 PR 被擋；`artifact` 的卡缺產物時被擋。
9. 缺驗證報告的卡拖到 `done` → 被拒，訊息指名缺哪一項；Admin `--force` 可過且理由永久可見。
10. 旗標關閉：完整 V1 回歸全綠。

## 風險

| 風險 | 對策 |
|---|---|
| **自動合併被日後加回來** | git 子命令 allowlist ＋ 出口條件 5 的「不存在」驗收 ＋ ADR 的拒絕清單 |
| PR 灌爆 repo | 同一張卡同時只有一個進行中的 run；無變更不開 PR；分支命名可辨識、可批次清理 |
| 驗證命令變成任意執行的後門 | 命令來自 Project 設定（Admin 維護），不來自卡片或請求；只在 run 的隔離目錄內執行 |
| Done Gate 太嚴導致繞過 | `--force` ＋ 必填理由 ＋ 永久可見 ＋ 指標追蹤次數 |
| 指標讓人追求數字而非品質 | 指標只顯示，不進任何自動阻擋邏輯 |
