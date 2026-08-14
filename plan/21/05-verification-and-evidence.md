# 05 — 執行計畫、驗證報告與證據（`DV-06`）　**安全審查第二節**

三張表的 service、API 與 CLI。本檔的核心不是 CRUD，是**一句話**：

> **`source` 由伺服器端決定，忽略 payload——而且忽略了要說出來。**

## 1. 執行計畫（FR-PLAN-001）

### 1.1 形狀

`(task_id, seq)` 唯一，**只 INSERT**。畫面顯示 `seq` 最大的一列，歷史可展開。
`seq > 1` 時 `note` 必填（為什麼改計畫）——那是 `version2.md` §7.5
「修改應留下 Activity Log」的具體形式。

### 1.2 `steps[].status` 五值

`pending`／`in_progress`／`completed`／`skipped`／`failed`。
**在 service 層驗，不在 DB 上**（與 `acceptance_criteria` 一致）：
一個五值的 CHECK 在 JSONB 陣列裡要寫成一段讀不懂的表達式。

### 1.3 `seq` 的競態（規劃沒提的一件事）

兩個併發的 `cliora plan snapshot` 會撞同一個 `seq`——
一個 run 裡不太可能，但**一個人與一個 Agent 同時提交**是完全可能的。

處置：`seq = SELECT COALESCE(MAX(seq),0)+1` 之後 INSERT，
撞到唯一鍵 → **自動重試一次**，第二次再撞才回 `PLAN_SEQ_CONFLICT`。

**為什麼只重試一次**：撞第二次代表有第三方在高速寫入，而那不是這張表的用法。
自動重試無上限會把一個資料問題變成一個 CPU 問題。

### 1.4 API

| 方法 | 路徑 | 動作 |
|---|---|---|
| `GET` | `/api/tasks/{id}/plans` | `task.view`（＝`project.view`） |
| `POST` | `/api/tasks/{id}/plans` | `task.update` |

**沒有 PUT／PATCH／DELETE。** 這一句要寫進路由模組的 docstring，
因為「只 INSERT」在 REST 上的表現方式就是「沒有那三個方法」。

## 2. 驗證報告（FR-VERIFY-001／002）

### 2.1 三級 `source`，由伺服器端決定（D12）

| `source` | 誰產生 | 寫入路徑 | UI |
|---|---|---|---|
| `agent_reported` | Agent 透過 CLI 提交 | `POST /api/tasks/{id}/verification`（run 憑證或使用者） | 「Agent 自述」，exit code **不加粗**，旁註「未經平台驗證」 |
| `platform_observed` | 平台自己看到的 | 內部呼叫（run 狀態、push 結果、PR 建立） | 「平台紀錄」 |
| `machine_verified` | **daemon 在 run 內執行的驗證命令與其 exit code** | `run.complete` 的 `verification[]`（`03-…md` §3.1） | 「機器事實」 |

**三條實作規則：**

1. **payload 裡的 `source` 一律丟棄。** service 的簽名裡根本沒有那個參數——
   它由呼叫端（哪一支路由／哪一條內部路徑）決定。
   *這是結構上的保證，不是一行 if。* 與 `services/agent_auth.py`
   把使用者與 run 憑證分成兩條依賴是同一個手法。
2. **丟棄了要記一筆 activity**（出口條件 8）。
   ```python
   if "source" in raw_payload:
       await activity.record(VERIFICATION_SOURCE_IGNORED, …,
                             payload={"claimed": raw_payload["source"], "stored": actual})
   ```
   只忽略不記錄的話，**一個試圖偽稱的 Agent 與一個欄位打錯的 Agent
   在紀錄上長得一樣**，而那兩件事要做的處置不同。
3. **`machine_verified` 只有一個寫入點**：`RunService.finish()` 讀
   `payload["verification"]`。`GATE-DV-MACHINE-VERIFIED-ONE-WRITER`
   掃 `backend/` 只允許一處出現這個字串常數的寫入用法。
4. 🆕 **`origin` 由 daemon 原樣回報，Central 不重算。** Central 明明查得到，
   而**查回來的會與實際跑的那一條不一致**——有人在 run 進行中改了 Project 設定
   或卡片的清單就會。一個跟著結果一起走的值不會漂移。

### 2.2 為什麼 `machine_verified` 值得存在，以及 `origin` 這個第二軸

**這一級的價值是「執行者沒有選擇要跑什麼」**，不是「命令來自哪一張表」。
2026-08-14 裁決之後有兩個來源（D4），而兩者都滿足那句話：

| 軸 | 問的問題 | 值 |
|---|---|---|
| `source` | **誰觀察到**這件事 | `agent_reported`／`platform_observed`／`machine_verified` |
| `origin` | **誰指定**要跑這件事 | `project`（`project.manage`）／`card`（**`task.approve`**） |

`RUN_TOKEN_SCOPES = {PROJECT_VIEW, TASK_UPDATE}`（`agent_auth.py:70`）——
run 憑證永遠拿不到 `task.approve`，所以**卡片宣告是人做的，不是 Agent 做的**。
兩者因此都是機器事實。

**但 `origin` 仍然要顯示**，因為 reviewer 會問的下一個問題就是「誰定的標準」：
一條 `origin: card` 的檢查是這張卡自己的標準，而一條 `origin: project` 的
是這個部署對「算完成」的定義。兩者都有效，**分量不同**。

反過來說，這一句是不變的判準：**如果哪一天有人把卡片宣告的權限從
`task.approve` 降到 `task.update`，`origin: card` 的那幾列就要降級成
`agent_reported`**——而不是保留一個名字說謊的分級。
這一句要同時出現在 ADR 0033 §3、這裡、以及安全審查 §2。

### 2.3 `result` 五值與 AC 四值

報告的 `result`：`not_started`／`running`／`passed`／`failed`／`partial`（`version2.md` §7.8）。
報告裡的 `acceptance_criteria[]` 用 D9 的四值。

**報告的 AC 與卡片的 AC 是兩份資料，而它們可以不一致。**
這一點要寫清楚：報告是「這次 run 驗到了什麼」的快照，
卡片的 AC 是「現在的狀態」。Done Gate 讀的是**卡片**（`06-…md` §2），
而報告是它的依據之一。兩者混成一份的話，一次舊 run 的報告會把卡片的狀態改回去。

### 2.4 API

| 方法 | 路徑 | 動作 |
|---|---|---|
| `GET` | `/api/tasks/{id}/verification` | `project.view`，回全部歷史 |
| `POST` | `/api/tasks/{id}/verification` | `task.update`，**`source` 永遠是 `agent_reported`** |

## 3. Evidence（FR-EVIDENCE-001／002）

### 3.1 九種 `kind`

| kind | 誰寫 | source |
|---|---|---|
| `git_state` | daemon（`Inspect()`） | `machine_verified` |
| `changed_files` | daemon | `machine_verified` |
| `diff_stat` | daemon | `machine_verified` |
| `command_result` | daemon（驗證命令） | `machine_verified` |
| `run_event` | Central | `platform_observed` |
| `delivery` | Central（push／PR 結果） | `platform_observed` |
| `agent_finding` | Agent（CLI） | `agent_reported` |
| `agent_limitation` | Agent（CLI） | `agent_reported` |
| `agent_risk` | Agent（CLI） | `agent_reported` |

**kind 決定 source，而不是相反。** 一張表（`_SOURCE_FOR_KIND`）把兩者綁死，
所以「Agent 寫了一筆 `git_state`」這件事在資料層是**不可表示**的——
它會被拒絕（`EVIDENCE_KIND_NOT_WRITABLE`），而不是被存成一筆假的機器事實。

> 這比「檢查寫入者身分」強一級：檢查可以被第二個呼叫端繞過，
> 一張把 kind 映射到 source 的表沒有第二種讀法。

### 3.2 矛盾不仲裁

Agent 自述的變更檔案（`agent_finding`）與 `git status`（`changed_files`）不一致時，
**兩者都顯示、都標來源，平台不猜誰對**。

實作上這代表**沒有比對邏輯**——這一節的工作量是零，
而它之所以要寫下來，是因為「順手加一個一致性檢查」是很自然的衝動，
而那個檢查的結論會變成一個沒有人負責的判斷。

UI 上的處置在 `07-…md` §2.3：兩列並排，各自帶來源徽章，**不排序、不合併**。

### 3.3 大小

`payload` ≤ **16 KiB／列**，一次 run ≤ **64 列**。
超過 → `EVIDENCE_PAYLOAD_TOO_LARGE`，訊息說「改附成產物」。

**為什麼是產物**：產物有配額、有保留期、有下載路徑、有 stored XSS 的處置（ADR 0030 Part B）。
evidence 是給人掃一眼的結構化事實，不是一個檔案儲存體——
讓它變成後者的話，ADR 0030 的那四件事要在這裡再做一次。

### 3.4 API

| 方法 | 路徑 | 動作 |
|---|---|---|
| `GET` | `/api/tasks/{id}/evidence` | `project.view` |
| `POST` | `/api/tasks/{id}/evidence` | `task.update`，kind 限三種 `agent_*` |

## 4. `cliora` CLI 的三個新子命令（D21）

```
cliora plan snapshot <file>          # JSON：{"note": "...", "steps": [...]}
cliora verify report <file>          # JSON：驗證報告（source 欄位會被忽略）
cliora evidence add <kind> <file>    # kind ∈ {finding, limitation, risk}
```

三個都是**寫入，沒有讀取版**。理由沿用 `command.go:21` 的既有克制：
Agent 剛寫的東西不需要讀回來，而每一個讀取端點都是一個要授權的面。

**`verify report` 的輸出要明說 source 被改了**：

```
已提交驗證報告（記為「Agent 自述」）。
平台自己執行的驗證由專案設定或卡片上的宣告決定，而那兩處你都改不了。
```

第二句是刻意的，而**後半句在 2026-08-14 裁決之後更重要**：
Agent 現在看得到卡片上有一份驗證命令清單（它讀得到卡片），
所以要直接說「你改不了它」，否則它會花一次 `task.update` 去試。
**不會去試**比**試了被擋**便宜。

⚠️ **`--force` 不在這裡，而且永遠不會在**（D10、README 易錯 13）。

## 5. 安全審查 §2 要回答的五個問題

| # | 問題 | 這一期的答案 |
|---|---|---|
| 1 | 新增的執行能力邊界在哪 | **只在 run 的隔離目錄內、只執行兩個平台儲存面裡的 argv 陣列、不經 shell**。沒有「對任意 node 執行任意命令」的 API，而那條路徑的不存在是可斷言的（沒有接受命令的請求欄位） |
| 2 | SEC-002 被修訂了嗎 | **沒有。** 修訂後的不變式（ADR 0032 §1）是「沒有任何**請求 payload** 能命名一個命令」。`tasks.verification_commands` 是**平台資料庫裡的一欄**，不是請求 payload——它由一個帶 `task.approve` 的請求寫入，然後由 Central 從自己的 store 取出，與 `spec.secrets` 逐字同構 |
| 3 | 誰能改那組命令 | **兩個來源、兩個授權，都不是 Agent**：Project 設定要 `project.manage`（Admin），卡片宣告要 **`task.approve`**。`RUN_TOKEN_SCOPES` 兩個都不含（`agent_auth.py:70`），而 `agent_auth.py:51` 的註解白紙黑字寫著 `task.approve` 是它「永遠不能持有的那一半」。兩處改動都進稽核 |
| 3b | 🆕 卡片宣告新增了什麼風險 | **不是提權**（沙箱本來就能跑那些命令），而是**「兩張卡可以用不同的標準宣稱自己完成」**。收斂點有三個：`origin` 在四處可見、專案級開關 `require_project_verification`、以及指標會顯示 `origin: card` 的比例。⚠️ **這一條要在審查裡被明確接受，不是被略過** |
| 4 | 驗證命令的輸出會外洩機密嗎 | `output_tail` 過 Redactor（`03-…md` §4.2 細節 2），而 Redactor 掛在 `send` 上所以自動涵蓋。**有一條測試釘住它** |
| 5 | `machine_verified` 可以被偽造嗎 | 寫入點只有一個（`finish()` 讀 `run.complete`），而那條路徑要一個有效的 node 認證 ＋ 該 run 屬於該 node（`_run_for_node`，`runs.py:832`）。CLI 送的一律是 `agent_reported`，且**偽稱會留下一筆 activity** |

## 6. 驗收

| # | 斷言 | 怎麼驗 |
|---|---|---|
| 1 | payload 帶 `source` → 存成 `agent_reported` ＋ 一筆 activity | `test_a_claimed_source_is_ignored_and_recorded` |
| 1b | **run 憑證改 `tasks.verification_commands` → 403**；人改可以 | `test_declaring_a_check_on_a_card_takes_task_approve` |
| 1c | 兩個來源的檢查都存成 `machine_verified`，`origin` 分得出來 | `test_both_origins_are_machine_verified_and_distinguishable` |
| 2 | `machine_verified` 只有一個寫入點 | `GATE-DV-MACHINE-VERIFIED-ONE-WRITER` |
| 3 | Agent 寫 `git_state` 被拒 | `test_kind_decides_source_and_agents_cannot_claim_machine_kinds` |
| 4 | 三張表沒有 PUT／PATCH／DELETE | `test_every_mounted_route_is_in_the_matrix` ＋ 一條斷言 |
| 5 | `seq` 撞一次自動重試、撞兩次回 409 | `test_two_concurrent_snapshots` |
| 6 | 矛盾兩列並存 | `test_a_disagreement_is_stored_twice_not_resolved` |
| 7 | evidence 超過 16 KiB 被拒並指向產物 | 一條測試，斷言 message 含「產物」 |
| 8 | 故意讓驗證命令失敗 → 報告 `failed`、`exit_code` 是真的 | 端到端，`cmd/fakecli` ＋ 一條 `exit 3` 的驗證命令 |
