# 06 — Done Gate 與流程可設定性（`DV-07`／`DV-08`）　**安全審查第三節**

本期的判準半。零新對外副作用，**但它決定「這件事憑什麼算做完」**——
所以它壞掉的方式是：卡片憑一句「完成」進了 `done`，而沒有人發現。

## 1. Done Gate 只有一條入口（README 易錯 12）

現況：

- `TaskService.update()`（`tasks.py:421`）是唯一會改 `task.stage` 的地方。
- `RunService.finish()`（`runs.py:793`）**不碰 `task.stage`**——run 成功不會移動卡片。
- `cliora task update --stage done`（`command.go:98`）走 `PATCH`，同一支 service。

所以 `research/02/06` DV-05 寫的「接到 `PATCH` 與 **run 完成路徑**上」
在現況上只需要接一處。**這讓本張 ticket 比規劃小很多，但要加一條斷言**：

```python
# GATE-DV-SINGLE-DONE-PATH
# `services/runs.py` 不得出現 `task.stage = ` 的賦值。
```

沒有這條 gate，日後有人在 `finish()` 裡加一行「成功就推進 done」
（那是一個很自然的體貼），Done Gate 就從側門被繞過去了，
**而且側門的那條路上沒有任何人會想到要檢查它**。

## 2. 六項完成證據

```text
TASK-123 進入 done 的前提
  ✅ 有 Completion Summary
  ✅ 每一項 Acceptance Criteria 都有結果            ← D9 的四值讓這句有意義
  ✅ 有 Verification Report
  ✅ 沒有未處理的 Critical Failure
  ✅ dependsOn 全部 done                           ← V2.1 已上線
  ✅ 依 delivery 的交付證據齊備                     ← 本期新增
       none         → 不要求任何產物
       artifact     → 至少一件卡片產物
       branch       → 有分支連結
       pull_request → 有 PR 連結（或明確的「無變更」結論）
       existing_pr  → 有追加的 commit
```

### 2.1 六項各自讀哪裡

| # | 判準 | 讀哪裡 | 缺的時候訊息說什麼 |
|---|---|---|---|
| 1 | Completion Summary | 最新一筆 `verification_reports.completion_summary`，或最新一次成功 run 的 `task_runs.summary` | 「缺完成摘要」 |
| 2 | 每項 AC 有結果 | `tasks.acceptance_criteria[].result != 'not_verified'` | 「這幾項驗收標準還沒有結果：…」**逐項列出** |
| 3 | 有驗證報告 | `verification_reports` 至少一列且 `result != 'not_started'` | 「缺驗證報告」 |
| 4 | 無未處理的 Critical Failure | 最新報告的 `checks[]` 沒有 `exit_code != 0` 且未被 `remaining_risks` 認領的項目。**兩個 `origin` 一視同仁**（D4） | 「這幾項檢查失敗且未被列為殘留風險：…」，**每一項帶 `origin`** |
| 4b | 🆕（選用）至少一條 `origin: project` 的檢查跑過 | 只在 `projects.require_project_verification = true` 時生效，**預設關閉** | 「這個專案要求至少通過一條專案層級的驗證，而這次 run 只跑了卡片宣告的那幾條」 |
| 5 | dependsOn | V2.1 的 `_check_dependencies_for` | 既有 |
| 6 | 交付證據 | 依 `task.delivery` 五分支（見下） | 各自不同 |

**第 4b 項為什麼預設關閉**：D4 讓卡片可以宣告自己的驗證命令，
而那換來的彈性的代價是「兩張卡可以用不同的標準宣稱自己完成」。
`require_project_verification` 是那個代價的收斂點——**但一開始就打開它，
卡片宣告這條路在第一天就會被繞過**（人會發現「反正還是要專案那幾條，
那我不如不宣告」）。先讓它跑一段，用指標看 `origin: card` 的比例再決定。

**第 4 項的定義值得解釋**：「未處理」的意思是**沒有人明說接受它**。
一條失敗的檢查加進 `remaining_risks` 就算處理過了——
那是一個人（或 Agent）寫下「我知道它失敗，而我接受」的動作。
把「處理」定義成「修好」的話，任何一個已知的環境問題都會擋住整張卡，
而使用者會直接去用 `--force`——那正是 `--force` 不該被用的方式。

### 2.2 第 6 項的五分支

```python
def _delivery_evidence_missing(task, latest_run) -> str | None:
    match task.delivery:
        case "none":
            return None
        case "artifact":
            return None if artifact_count > 0 else "這張卡宣告以產物交付，但一件產物都沒有"
        case "branch":
            return None if latest_run and latest_run.pushed_branch else "沒有已推送的分支"
        case "pull_request":
            if latest_run and latest_run.delivery_ref:  return None
            if latest_run and latest_run.result == "no_changes": return None   # 「無變更」的明確結論
            return "沒有 PR 連結，也沒有『無變更』的結論"
        case "existing_pr":
            return None if latest_run and latest_run.pushed_branch else "沒有追加的 commit"
```

⚠️ **`pull_request` 的第二個出口**（`no_changes`）是誠實性規則 2 的另一半：
沒有變更就沒有 PR，那麼**也不能因為沒有 PR 而擋住這張卡**。
漏掉這一格的結果是一張正確完成的調查型卡片永遠進不了 `done`，
而使用者只能用 `--force`——**又一次把旁路變成正常路徑**。

⚠️ **`delivered_branch_only` 也要通過**：PR 建立失敗不是卡片的錯，
分支在、工作在，`delivery_ref` 是空的但 `pushed_branch` 不是。
所以 `pull_request` 那一格要多一個條件：`latest_run.delivery_state == "branch_only"`
→ 通過，**但在 Task Detail 上顯示「PR 未能建立，需手動開」**。

### 2.3 拒絕的形狀

```json
{
  "code": "TASK_DONE_GATE_UNMET",
  "message": "這張卡還缺 2 項完成證據",
  "details": {
    "missing": [
      {"key": "acceptance_criteria", "text": "這幾項驗收標準還沒有結果：拒絕 symlink escape"},
      {"key": "verification_report", "text": "缺驗證報告"}
    ]
  }
}
```

**逐項而不是一句話**，因為使用者要做的事每一項都不同。
`plan/20` 對同一件事已經表過態（機密的兩種拒絕，`runs.py:307`：
「一個訊息會送一半的讀者到錯的頁面」）。

## 3. `--force`（D10）

### 3.1 形狀

`PATCH /api/tasks/{id}`，body 多兩個欄位：

```json
{"stage": "done", "force": true, "force_reason": "驗證環境壞掉，工作已由 X 目視確認"}
```

- 需要 **`task.force_done`**（Admin 專屬，migration `0037`）。沒有 → **403**。
- `force_reason` 必填、非空、≤2000 字。缺 → `TASK_FORCE_REASON_REQUIRED`。
- 寫進 `tasks.force_done_{reason,by,at}`（`02-…md` §2.3）**與** `activity_events`。
- **`cliora` CLI 沒有這個子命令，永遠不會有。**

### 3.2 為什麼要有這個出口

`research/02/06` 的一句話值得逐字保留：

> 沒有這個出口，第一次遇到「驗證環境壞掉但工作確實完成」時，
> 使用者會開始繞過整個系統。

而「繞過整個系統」的具體長相是：把卡片停在 `verify` 不動、
或是關掉 `CLIORA_PROJECTS_ENABLED`。兩者都比一筆有理由的旁路糟得多。

### 3.3 永久可見

Task Detail 上，卡片標題旁一枚常駐徽章：
**「此卡由 {who} 於 {when} 強制推進：{reason}」**，不可摺疊、不可清除。

**取消 force 的方式只有一個**：把卡片移出 `done` 再正常推進一次，
那時三個欄位一起清空。**沒有「只清掉那個徽章」的操作**——
一個可以單獨清掉的紀錄不是紀錄。

### 3.4 指標

第三個跨專案指標就是「用 `--force` 略過 Done Gate 的次數」（`07-…md` §3）。
**它存在的理由不是抓人，是告訴我們判準是不是訂錯了**——
這一句要寫在指標的說明文字上，因為一個沒有解釋的計數會被讀成一個排行榜。

## 4. 流程可設定性（`DV-08`／D13）

### 4.1 只允許啟用／停用

`projects.process_overrides`（JSONB）：

```json
{
  "readiness_disabled": ["has_design_link", "has_test_plan"],
  "gates_disabled": ["ui"],
  "wip": {"implementing": 3}
}
```

**三種操作，沒有第四種**：關掉某幾項 readiness、關掉某幾個 gate、調 WIP 建議值。
**不允許新增自訂項目、不允許改車道。**

理由（`research/02/06` DV-08）：**跨專案指標要能聚合，欄位不同就無法比。**
可設定性是最容易在沒有使用者的情況下被過度設計的東西。

### 4.2 `ProcessService.effective()` 的改動

```python
async def effective(self, key: str = DEFAULT_KEY, *, project_id: uuid.UUID | None = None):
    row = await self.definition(key)
    overrides = await self._overrides(project_id) if project_id else {}
    ...
```

三個消費端要一起改：`readiness_keys()`、`wip_for()`、`gate()`。
⚠️ **`gate()` 的停用有兩種來源了**：integration 停用（既有，`process.py:106`）
與專案覆寫（新增）。`disabled_reason` 要**分得出來**——
「這個部署沒有 tunnel 整合」與「這個專案關掉了它」是兩件不同的事，
而使用者的下一步不同（一個找 Admin，一個找專案負責人）。

### 4.3 驗證覆寫的 key

每一個 key 都必須存在於 default 定義裡，不存在 → `PROCESS_OVERRIDE_UNKNOWN_KEY` 並指名。

**為什麼要驗**：一個打錯的 key 是靜默無效的，
而使用者會以為自己關掉了那一項——直到它擋住一張卡。

### 4.4 API

| 方法 | 路徑 | 動作 |
|---|---|---|
| `GET` | `/api/projects/{id}/process` | `project.view`，回**套用覆寫後**的定義 ＋ 覆寫本身 |
| `PUT` | `/api/projects/{id}/process/overrides` | **`process.manage`**（Admin） |

回**套用後**的定義而不是只回覆寫：畫面要顯示的是「這個專案現在的流程」，
而讓前端自己套一次覆寫等於把同一套規則實作兩次。

## 5. 安全審查 §3 要回答的四個問題

| # | 問題 | 這一期的答案 |
|---|---|---|
| 1 | Done Gate 有幾條入口 | **一條**，而且有 gate 守著（§1） |
| 2 | 誰能繞過 | 只有 `task.force_done`（Admin）。run 憑證拿不到——它不走使用者的認證路徑，而且 CLI 沒有這個子命令 |
| 3 | 繞過留下什麼 | 三個欄位（永久可見）＋ 一筆 activity ＋ 一個指標。**三者都不可由 API 清除** |
| 4 | 流程覆寫能不能關掉 Done Gate | **不能。** 覆寫只碰 readiness、gates、WIP 三者，而 Done Gate 的六項**不在** `process_definitions` 裡——它是 service 層的常數。這一句要寫下來，否則下一個人會很自然地想「把 Done Gate 也做成可設定的」 |
| 5 | 🆕 卡片宣告的驗證命令能不能讓一張卡自己放水 | **能，而那是刻意換來的彈性**（D4）。三個收斂點：宣告要 `task.approve`（**Agent 拿不到**）、`origin` 在四處可見、以及 `require_project_verification` 這個專案級開關。⚠️ **審查要明確接受這一條**，不是略過它——它是本期唯一一個「使用者裁決之後才加進來」的風險 |

> 第 4 條是本節最重要的一條。DV-08 的「可設定性」與 DV-05 的「完成判準」
> **在資料上必須是分開的兩件事**，否則第一次有人嫌 Done Gate 麻煩，
> 他會去關掉它而不是去用 `--force`——而關掉它不留任何痕跡。

## 6. 驗收

| # | 斷言 | 怎麼驗 |
|---|---|---|
| 1 | 缺項時逐項指名 | `test_the_refusal_names_every_missing_item` |
| 2 | 五種 delivery 的交付證據各驗一次 | 五條測試 |
| 3 | `no_changes` 的 `pull_request` 卡進得了 done | `test_a_no_change_pull_request_card_is_not_blocked_by_a_missing_pr` |
| 4 | `delivered_branch_only` 進得了 done 且畫面說得出 | 一條後端 ＋ 一條前端 |
| 5 | `artifact` 缺產物被擋 | `test_an_artifact_card_without_one_is_refused` |
| 6 | run 完成不移動卡片 | `GATE-DV-SINGLE-DONE-PATH` ＋ 一條端到端 |
| 7 | 非 Admin 的 `--force` → 403 | `test_force_requires_its_own_action` |
| 8 | 理由永久可見且不可單獨清除 | 一條後端（沒有清除端點）＋ 一條前端（徽章不可摺疊） |
| 9 | 覆寫的未知 key 被拒並指名 | `test_an_unknown_override_key_is_named` |
| 10 | 覆寫關不掉 Done Gate | `test_process_overrides_cannot_reach_the_done_gate`（掃 `effective()` 的回傳不含 Done Gate 的任何欄位） |
