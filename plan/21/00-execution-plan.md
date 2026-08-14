# 00 — 執行總控（V2.4 交付、驗證與證據）

Ticket 前綴 `DV-`。上游規劃：[`research/02/06-phase-v24-delivery-and-verification.md`](../../research/02/06-phase-v24-delivery-and-verification.md)。

> **本期是紅線 5 的落地階段**：出口只有五種，沒有第六種。
> 而「沒有第六種」的驗收方式是**「那條路徑不存在」**，不是「那條路徑被擋住」——
> 對 daemon 的 git 子命令 allowlist 與 Central 的 provider 呼叫 allowlist 各斷言一次（`08-…md` §3）。

## 0. 待裁決項目

**這一節是開工前唯一要讀的東西。** 每一項都寫了「不同意的話會怎樣」。

### 0.1 A 類 — **兩項均已於 2026-08-14 裁決結清（0 項）**

---

**☑ D4 — 兩個來源都要：Project 設定 ＋ 卡片宣告**

> **裁決（2026-08-14）：兩者都要。**

上游那兩句互相矛盾的話（`research/02/01` D10 例外 2 的「卡片宣告」與
`research/02/06` DV-04 的「Project 設定」）**不再需要二選一**——
它們描述的是兩個來源，而本計畫把它們做成一個欄位的兩個值。

代價已在原表列出：**「那就要在 evidence 上多記一個『這條命令是誰宣告的』欄位並在 UI 分色。」**
本計畫照做，並且**多加一道**（見 D4 的完整落地）：

| | |
|---|---|
| **落地** | `origin` 是**第二軸**：`project`（`projects.verification_commands`，`project.manage`）與 `card`（`tasks.verification_commands`）。`source` 三級不變 |
| **關鍵的一道** | **卡片上宣告驗證命令需要 `task.approve`，不是 `task.update`。** `RUN_TOKEN_SCOPES = {PROJECT_VIEW, TASK_UPDATE}`（`agent_auth.py:70`）——**agent 憑證永遠拿不到 `task.approve`**，而該模組的註解白紙黑字寫著那正是它存在的理由。所以「人可以在卡片上宣告、Agent 不行」不是一行 if，是既有的 token scope 邊界 |
| **因此 `machine_verified` 保住了** | 這一級的價值是「**執行者沒有選擇要跑什麼**」，而不是「命令來自哪張表」。兩個來源都不是 Agent 選的，所以兩者都是機器事實——但 `origin` 仍要顯示，因為「誰指定的」是 reviewer 會問的下一個問題 |
| **連帶改動** | `02-…md` §2.1（新欄位）、`03-…md` §4.2（編碼多一格 origin）、`05-…md` §2（第二軸）、`06-…md` §2.1（第 4 項讀兩者）、`07-…md` §1.5／§6（徽章與編輯權限）、出口條件 15b／19c |

**唯一新增的取捨要寫進 ADR 0033 §3 與安全審查 §2**：
卡片宣告讓「這張卡驗了什麼」變成一張卡的屬性，
所以**兩張卡可以用不同的標準宣稱自己完成**——那是刻意換來的彈性，
而 `origin` 徽章 ＋ §2.2 的專案級開關是它的收斂點。

---

**☑ D7 — `existing_pr` 只對平台自己開的 PR 成立（選項 A）**

> **裁決（2026-08-14）：照計畫的預設，縮範圍。**

`existing_pr` 的 `base_branch` 必須在 `cliora/` 內，否則 **dispatch 當下拒絕**
（`TASK_EXISTING_PR_OUT_OF_NAMESPACE`）。
`push.go:54` 的第一條硬約束**一個字不改**，V2.3 的安全審查結論繼續有效。

**要一起接受的代價**：人自己開的 PR 要 Agent 接手，得先把分支改名或改用 `delivery: branch`。
**這一條看起來像 bug**，所以它有三處文案（dispatch 的拒絕訊息、卡片編輯的當場提示、
release note 的已知取捨），而那三處是對策不是裝飾。

---

### 0.2 B 類 — 確認即可（4 項）

| ☐ | 項目 | 內容 | 不同意的話 |
|---|---|---|---|
| ☐ | **D1／D2** | PR 由 Central 開；`pull_request` 在 wire 上表現為 `branch` | 若改成 daemon 開 PR：`provider_token` 要下放到 node（`secrets.py:48` 的 `UNDELIVERABLE_KINDS` 要改），而那枚憑證能改別人的 repo；且 `delivery` 要加值，舊 node 會靜默丟 offer（README 易錯 1） |
| ☐ | **D6** | 驗證命令沿用既有的 `spec.allowed_verification_commands` | 新增欄位會讓所有未升級的 node 丟掉每一個帶驗證命令的 offer（README 易錯 2）。而這個欄位的 `$comment` 本來就是為這件事寫的 |
| ☐ | **D9** | AC 的 `result` 本期封閉成四值 | 不封閉的話 Done Gate 的「每一項 AC 都有結果」等於沒有檢查——`result: "隨便"` 會通過 |
| ☐ | **D10** | `--force` 是新的 Admin 動作 `task.force_done`，不是 `task.approve` 的複用 | 複用 `task.approve` 會讓「核准一個 gate」與「跳過整個 Done Gate」同權，而後者的每一次都要被人看見 |

### 0.3 C 類 — 開工時決定，計畫已給預設值（5 項）

| ☐ | 項目 | **計畫的預設** | 什麼情況要改 |
|---|---|---|---|
| ☑ | provider 先做哪一家 | **只做 GitHub**，GitLab 留 adapter 介面不實作 | **已裁決（2026-08-14）**：GitHub。未支援的 host 在 dispatch 當下拒絕（D15） |
| ☐ 🆕 | **專案是否要求至少一條 `origin: project` 的檢查** | **預設關閉**（`projects.require_project_verification = false`） | D4 換來的彈性需要一個收斂點時打開它。**預設關閉是刻意的**：一個一開始就擋人的開關會讓卡片宣告這條路在第一天就被繞過 |
| ☐ | 驗證命令的逾時 | **每條 300 秒、整組 900 秒**，值在 node 的設定檔不上 wire | M-DV-1 量出典型測試套組超過 |
| ☐ | evidence 的採集逾時 | **10 秒**（`git status --porcelain`） | **M6 的結果**——這是本期唯一擋開工的量測 |
| ☐ | PR 內文的長度上限 | **60 KiB**，超過就截斷並附「完整內容在 run 詳情」 | provider 的實際上限更小 |
| ☐ | 跨專案指標的快取 | 沿用 `dashboard_cache_ttl_seconds` | 指標查詢比既有 block 慢一個數量級 |

## 1. 成功定義

**要交付的：** Developer 在一張卡上宣告 `source: repo`、`delivery: pull_request`、
`target_branch: main`，填好三項 Acceptance Criteria；派給 Agent 之後，
run 在隔離目錄裡工作、commit 到 `cliora/TASK-123-1`、
**daemon 在同一個目錄裡跑完 Project 設定裡的兩條驗證命令並回報真實的 exit code**；
分支推回去之後**由 Central 開出一個 PR**，PR 內文含目標、逐項 AC 結果、驗證摘要、
殘留風險與 run 連結；卡片上出現執行計畫、驗證報告與證據三個區塊，
每一列都標著它是 `agent_reported`、`platform_observed` 還是 `machine_verified`；
把卡片拖到 `done` **通過**，因為六項完成證據都齊了。

**同一天要驗的反面：** 把驗證命令改成一條會失敗的，
報告是 **`failed`** 而不是 Agent 自稱的 `passed`；
把 AC 的其中一項清空，拖到 `done` **被拒並指名是哪一項**；
Admin 用 `--force` 帶理由推過去，**那個理由永久顯示在卡片上**；
一張 `delivery: none` 的卡照樣進得了 `done`，**不因為沒有 PR 被擋**。

**其餘一律不做。** 需求釐清、任務拆解、MCP 外殼——那是 V2.5 之後的事（§2）。

**不得弄壞的十四件事：**

1. **兩個旗標都關閉時，系統與 V2.3 逐位元組一致。** 本期新增端點全數 404。
2. **互動式 Session 的行為一個位元組都不變。** `daemon/internal/runtime/{runtime,launch}.go`
   對 `DV-00` 基線**零 diff**（沿用 `GATE-AR-TOUCH-LIST`）。
3. **SEC-002 的 argv 條款不再被修訂一次。** 本期新增的執行能力（驗證命令）
   **不是**「呼叫端指名命令」——**兩個來源都是平台自己的儲存面**（D4）。
   這一句要寫進 ADR 0033 §3 與安全審查 §2，**而且要寫成一個可驗證的形式**：
   `spec.allowed_verification_commands` 的值只來自 `projects.verification_commands`
   與 `tasks.verification_commands`，一條測試斷言 Central 從不從 request payload 讀它。
3b. 🆕 **Agent 不能宣告驗證命令。** `tasks.verification_commands` 需要 `task.approve`，
   而 `RUN_TOKEN_SCOPES` 永遠不含它（`agent_auth.py:70`）。
   這一條**不是靠 `EDITABLE_FIELDS` 的一行**——它靠的是既有的 token scope 邊界。
4. 🆕 **平台永不自動合併、永不 approve 自己的 PR、永不關閉別人的 PR、永不動 tag。**
   Central 的 provider 呼叫是一張**封閉表**（只有「建立 PR」與「查詢 PR」兩個動作），
   `GATE-DV-PROVIDER-VERBS` 對它斷言。daemon 的五條硬約束一個字不改。
5. 🆕 **`delivery: none` 與 `artifact` 產生零個遠端副作用。**
   不是「不推分支」而是**「連 provider API 都不呼叫」**——出口條件用遠端的狀態驗，不用 log 驗。
6. 🆕 **PR 建立失敗不讓 run 失敗。** 分支已經推上去了，工作沒有消失。
7. 🆕 **`source` 三級由伺服器端決定，忽略 payload。** 而且**忽略了要說出來**（記一筆 activity）。
8. 🆕 **Done Gate 只有一條入口。** run 完成路徑**不得**移動卡片——這是一條測試，不是一句約定。
9. 🆕 **`--force` 永久可見。** 進 `activity_events`，在 Task Detail 上不可摺疊、不可清除。
10. **既有 25 個 RBAC 動作的角色歸屬不變。** 只新增兩個（`process.manage`、`task.force_done`），
    兩個都是 Admin 專屬（合計 27）。
11. **run 憑證永遠拿不到那兩個新動作**，而且不是靠一行 if——它根本不走使用者的認證路徑。
12. **卡片產物仍然不可變**，run log 的兩種保留期不變。
13. 🆕 **執行計畫、驗證報告、evidence 三張表只 INSERT 不 UPDATE。**
    改計畫是新增一列並帶 `note`，不是改寫舊列。
14. 🆕 **指標只顯示，不進任何自動阻擋邏輯。** 沒有「失敗率太高就停止派工」這種東西。

成功的判準是以下十四項，每一項都要有可貼上的輸出（`08-…md` §5）：

1. **五種 `delivery` 各跑通一次**，`none` 與 `artifact` 跑完之後**遠端沒有任何新分支、沒有任何新 PR**。
2. `delivery: none`／`artifact` 但工作目錄有變更 → 摘要明示「偵測到 N 個檔案變更」
   **且 diff 已附成一件卡片產物**（兩種 delivery 都要，見 README 易錯 5）。
3. `delivery: artifact` 但一件產物都沒有 → **run 不算成功**，結果說明缺什麼。
4. `delivery: pull_request` 但 diff 是空的 → run 成功、結論「無變更」、**沒有空 PR**
   （斷言 provider API **從未被呼叫**，不是斷言 PR 不存在）。
5. PR 建立失敗（四種原因各一次）→ 分支仍在、結果 `delivered_branch_only`、
   原因可讀、**run 不算失敗**。
6. **自動合併的程式碼路徑不存在**：daemon 的 git 子命令表沒有 `merge`／`rebase`／`tag`；
   Central 的 provider 動作表只有兩個動作。
7. 故意讓一條驗證命令失敗 → 驗證報告是 `failed`，`exit_code` 是真的那一個，
   **不是 Agent 在 payload 裡自稱的 `passed`**。
7b. 🆕 **兩個來源各跑一條**：報告上兩列都是「機器事實」，
   但 `origin` 徽章分別是「專案設定」與「卡片宣告」；PR 內文也分得出來。
7c. 🆕 **Agent 憑證嘗試改 `tasks.verification_commands` → 403**（缺 `task.approve`），
   而人改同一個欄位可以。
8. Agent 在 payload 帶 `source: machine_verified` → 伺服器**存為 `agent_reported`**、
   **記一筆 activity**，且 UI 上那一列標「Agent 自述／未經平台驗證」。
9. 同一張卡上 Agent 自述的變更檔案與 `git status` 不一致 → **兩者都顯示、都標來源**，
   平台不猜誰對。
10. 缺驗證報告的卡拖到 `done` → **被拒並指名缺哪一項**；補齊之後通過。
11. `delivery: none`／`artifact` 的卡**進得了 `done`**，不因缺 PR 被擋；
    `artifact` 缺產物時**被擋**。
12. Admin `--force` 帶理由推過去 → 通過，理由在 Task Detail **永久可見**且進了時間軸；
    非 Admin 送同一個請求 → 403。
13. Project 覆寫關掉兩項 readiness 與一個 gate → 該專案的看板照那份覆寫運作，
    **而跨專案指標仍然算得出來**（欄位沒變）。
14. 跨專案 Dashboard 的五個指標各出一個數字，**其中一個查詢失敗時只有那一格降級**，
    其餘四格仍是真數字（沿用 `dashboard.py` 的 per-block 契約）。

外加一條回歸判準：**兩個旗標關閉時完整 V1＋V2.0…V2.3 全綠、
既有 contract fixtures 一個位元組未變、`agentd` 0.11.0 在旗標關閉的部署上行為與 0.10.0 相同、
且 `agentd` 0.10.0 的 node 連上 V2.4 的 Central 時仍能正常領取與完成
`none`／`artifact`／`branch` 三種卡（只是不跑驗證命令）。**

> 最後那半句是本期唯一的相容性承諾，而它之所以成立完全是因為 D2 與 D6。
> **沒有那兩條，這句話是假的**（README 易錯 1／2）。

## 2. 範圍

### 納入

- `DV-00` **基線擷取 ＋ M6**（閘門）：M6 是 `research/02/10` §5 標成「V2.4 開工前」的唯一一項。
  另加 `agentd` 與 contract 的版本序確認（本期發 `0.11.0`／`v1.13.0`）。
- `DV-01` **ADR 0033**（交付模式與 PR 建立，含**紅線 5 的拒絕清單**）
  ＋ ADR 0029／0031／0032 的三則增補 ＋ `research/prd.md` §8.15
  ＋ traceability（FR-DELIVERY-001…004、FR-EVIDENCE-001…002、FR-VERIFY-001…003、FR-AGENTTOOL-002）
  ＋ **回溯條目**：V2.3 的 `spec.branch` 對舊 daemon 的相容洞（`01-…md` §6）。
- `DV-02` 資料層：migration `0035`（`execution_plans`／`verification_reports`／`evidence_items`）、
  `0036`（`projects.verification_commands`／`process_overrides`／`require_project_verification`、
  🆕 **`tasks.verification_commands`**、`task_runs` 的三個交付欄、
  AC `result` 的資料收緊）、`0037`（seed `process.manage` ＋ `task.force_done`）。
- `DV-03` contract **v1.13.0**：**只在 node→central 方向新增**——
  `run.complete` 的 `pushed_branch` 與 `verification`、`run.progress` 的 `verifying` phase、
  `runner.register` 的 `features`。**`spec` 零新增欄位**（D6）。
- `DV-04` `agentd` **0.11.0**：五種 delivery 的節點半邊（實際上是三種，D2）、
  **驗證命令的執行**、evidence 的採集、`features` 的上報、
  `ShouldAttachDiff`／`SummaryText` 共用述詞的修正。
- `DV-05` **PR 建立**：Central 的 provider adapter（GitHub）、PR 內文的產生、
  四種失敗的處置、**新的 egress 與它的三條斷言**。**安全審查第一節。**
- `DV-06` 執行計畫、驗證報告、evidence 的 service 與 API ＋ **`cliora` CLI 的三個新子命令**。
  **安全審查第二節。**
- `DV-07` **Done Gate**：六項完成證據、指名缺項的拒絕、`--force` 與它的永久可見性。
  **安全審查第三節。**
- `DV-08` **流程可設定性**：Project 覆寫（只允許啟用／停用）、`process.manage`。
- `DV-09` **指標**：Project Overview 的五塊、跨專案 Dashboard 的五個指標。
- `DV-10` 前端：Task Detail 的四個新區塊、Run 詳情的交付結果、Project Settings 的兩節、
  Dashboard 的新卡片。
- `DV-11` 驗證與出口：測試、雙旗標關閉回歸、十一個 gate、`docs/security-review-v24.md`、
  release note、**合併提案並停下來**。

### 不納入

- **自動合併、自動部署、release／tag。** 紅線 5，`version2.md` §13。永久不做。
- **PR 的審查動作**（approve／request-changes／comment on a PR）。
  平台只建立，不參與審查。
- **對任意 node、在 run 之外執行任意命令的 API。** D10 的修訂只在 run 內成立，
  而且命令來自 Project 設定（D4）。這條路徑不存在，也不會存在。
- **流程編輯器。** DV-08 只允許啟用／停用既有項目，不允許新增自訂項目、不允許改車道。
- **PRD patch 提案與任務建議。** V2.5（`research/02/07` RQ-06）。
- **需求釐清與拆解的 run。** V2.5。
- 🆕 **MCP 外殼。** `research/02/01` D11 的決策規則是「只在 M2／M5 指向要做時才建」，
  而 **M2 尚未量**（`plan/17` 之後沒有回填）。**沒有量到就不做**，而不是「順手做了反正不貴」——
  一個沒有人用的第二介面要維護，而它與 CLI 的行為差異會變成一種新的支援負擔。
- 🆕 **GitLab 的 provider adapter。** 介面留著（`04-…md` §2），實作不寫。
  未支援的 host → **dispatch 當下拒絕並指名**，不是執行到最後才發現。
- 🆕 **PR 的更新**（推了新 commit 之後改 PR 內文）。`existing_pr` 追加 commit 之後
  PR 內文維持原樣，只在卡片上留一筆訊息。改內文要決定「以哪一次 run 為準」，
  而那是一個沒有人問過的問題。
- **物件儲存（S3）、token 成本上限。** 理由與前兩期相同，不變。
- **`delivery` 的第六種。** 紅線 5。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **本期在 V2 的哪一格** | 三個半邊：交付半（**新的對外副作用**）＋驗證半（**新的執行能力**）＋判準半（零新副作用）。共用旗標 `CLIORA_AGENT_RUNS_ENABLED` | 三者的失敗長相不同：交付半壞了是**在別人的 repo 上開了不該開的 PR**；驗證半壞了是**把 Agent 自述當成機器事實**；判準半壞了是**卡片憑一句「完成」進 done**。共用一個旗標是因為判準半沒有交付半就沒有東西可判 |
| D1 ⚠️ | **PR 由 Central 開，daemon 永不持有 `provider_token`** | Central 在收到 `run.complete` 且確認分支已推之後，用 `project_repositories.provider_token_secret_id` 指向的機密呼叫 provider API | `secrets.py:48` 的 `UNDELIVERABLE_KINDS` 今天就把 `provider_token` 排除在下放之外，而那不是暫時的：一枚能在別人 repo 上開 PR 的憑證進了沙箱，**五條硬約束一條都攔不到它**（它們約束的是 git push，不是 HTTPS 請求）。連帶好處是 D2 成立。**被否決**：daemon 開 PR（上述）；Central 把 PR 內容交給 daemon 由 daemon 呼叫（憑證還是要下放，只是多繞一圈） |
| D2 ⚠️ | **`delivery: pull_request` 在 wire 上表現為 `branch`** | `RunOffer.spec()` 送出的 `delivery` 對 `pull_request` 與 `existing_pr` 都填 `"branch"`；卡片的真實意圖留在 Central（`task.delivery`）。daemon 只知道「推這條分支」 | `codec.go:961` 的 `runDeliverySet` 是 `{none, artifact, branch}`，而 `handleRunOffer` 對驗證失敗的 offer **直接 `return`，不回任何訊息**（`run_handlers.go:168`）。送 `pull_request` 給任何一台 0.10.0 的 node ＝ 靜默丟棄 → 租約到期 → 重排三次 → `blocked`。**而且這不是暫時的相容性讓步**：daemon 本來就不該知道 PR 這件事——它沒有 provider 憑證、開不了 PR、也不必知道分支推上去之後會發生什麼。**被否決**：加值到 enum 並要求所有 node 升級（本期會是第一個強制升級的階段，而 `node_update` 的推送是 opt-in 的）；用 `nodes.daemon_version` 判斷（`plan/20` 出口條件 3f 已經立過先例：**不依賴版本號**，依賴宣告） |
| D3 ⚠️ | **`runner.register` 新增 `features`（字串陣列），未帶時視為空集合** | 0.11.0 上報 `["verification", "evidence"]`。Central 只在 node 宣告了對應 feature 時才把相關內容放進 offer | **預設極性與 V2.3 的兩個布林相反**，而那是刻意的：`run_untagged`／`accept_secrets` 是**拒絕**旗標（不帶＝不拒絕），`features` 是**支援**旗標（不帶＝不支援）。把支援旗標做成寬鬆預設，等於假設沒升級的機器會做新功能。⚠️ **這條同時修掉一個既存的洞**：`spec.branch` 是 v1.12.0 加的，一台 0.8.0 的 node 今天就會丟掉每一張 `delivery: branch` 的 offer（`01-…md` §6） |
| D4 ⚠️ 🆕 | **驗證命令有兩個來源，而「誰指定的」是一個資料欄位**（2026-08-14 裁決） | `origin: project` ← `projects.verification_commands`（`project.manage`，Admin）；`origin: card` ← `tasks.verification_commands`（**`task.approve`**）。Central 把兩者合併填進 `spec.allowed_verification_commands`，**project 的排在前面**；`origin` 一路帶到 `verification_reports.checks[].origin`、`evidence_items.payload.origin`、UI 徽章與 PR 內文。**Central 從不從 request payload 讀命令**（一條測試斷言）——兩個來源都是平台自己的儲存面 | 卡片宣告買到的是彈性（一張卡有它自己的驗收方式，不必動全專案設定），而它的風險是「被驗證的一方自己選要跑什麼」。**`task.approve` 正好把那個風險關掉**：`RUN_TOKEN_SCOPES = {PROJECT_VIEW, TASK_UPDATE}`（`agent_auth.py:70`），而該模組註解寫著 `task.approve` 的持有者集合與 `task.update` **刻意相同**——拆開就是為了 token scope。所以人可以在卡片上宣告、**Agent 不行**，而 `machine_verified` 的定義（執行者沒有選擇要跑什麼）在兩個來源上都成立。**被否決**：只留 Project 設定（失去彈性）；卡片宣告走 `task.update`（等於把選擇權交給被驗證的一方，`machine_verified` 就要降級成 `agent_reported`） |
| D5 | **命令以 argv 陣列儲存與傳輸，永不經 shell**（兩個來源都是） | `{"name": "unit tests", "argv": ["pytest", "-q", "tests/"]}`。daemon 用 `exec.Command(argv[0], argv[1:]...)`，**不帶 `sh -c`**。wire 的形狀見 D6 | 一個 shell 字串是一條注入路徑，而它會在**平台自己的儲存面**上；把它做成陣列，SEC-002 的 argv 條款對這條新路徑仍然逐字成立。⚠️ **卡片宣告讓這一條更重要而不是更寬鬆**：`tasks.verification_commands` 比 Project 設定容易被改，所以它**用完全相同的驗證器**，沒有「卡片上比較方便所以允許字串」這種例外。**被否決**：`sh -c "make test"`（好寫、好用、而且會讓安全審查在這一節停下來） |
| D6 ⚠️ | **沿用既有的 `spec.allowed_verification_commands`（`string[]`），一條命令一個字串，daemon 端切分** | 每個元素是 `origin\tname\tcmd\targ1…`（**tab 分隔**；`origin` 是單字元 `p`／`c`）。daemon 切開之後直接 `exec.Command`，並把 `origin` 原樣回報在 `run.complete.verification[].origin`。上限沿用既有的 `maxItems: 16` 與 `maxLength: 256`，**兩個來源各 ≤8 條** | **`spec` 不能加欄位**（`codec.go:437` 的 `DisallowUnknownFields` 遞迴適用，README 易錯 2）。而這個欄位的 `$comment` 本來就寫著「present so that V2.4 s verification step does not need a contract change to be *refused* today」——V2.2 刻意留的座位，本期坐上去。**舊 daemon 收到非空值只是忽略**（`codec.go:938` 只檢查長度），所以這條路徑天生前向相容。⚠️ **`origin` 塞進同一個字串而不是另開欄位，正是為了不碰 `spec`**——多一個欄位就多一批被靜默丟棄的 offer。**被否決**：新增 `spec.verification` 物件；JSON-in-string（tab 切分讀 log 時看得懂，JSON 在 256 字元的預算裡浪費得太快） |
| D7 ⚠️ | **`existing_pr` 的 `base_branch` 必須在 `cliora/` 命名空間內，否則 dispatch 當下拒絕** | 沿用 `runs.py:339` 已經在守 `existing_branch` ＋ `branch` 的那個檢查的形狀與錯誤碼家族 | §0.1 D7。`push.go:54` 是 V2.3 安全審查通過的東西 |
| D8 ⚠️ | **「`artifact` 缺產物 → run 不算成功」的判定在 Central 的 `finish()`** | 收到 `run.complete` 且 `task.delivery == "artifact"` 時，數 `task_artifacts` 中 `run_id == run.id 且 deleted_at IS NULL` 的列；為 0 → `run.result = "delivery_incomplete"`、`status = "failed"`，並在卡片上留一筆事件 | daemon 不知道 Agent 附了幾件（產物走 HTTP，`command.go:204`）。**寫在 daemon 端會做出一個永遠通過的檢查**，而那比沒有檢查糟。⚠️ 注意順序：daemon 自己附的 diff（`ShouldAttachDiff`）**也算一件**，所以一張有變更的 `artifact` 卡不會因為 Agent 忘了附而失敗——這是對的，那份 diff 就是它的產物 |
| D9 | **AC 的 `result` 本期封閉成四值：`passed`／`failed`／`partial`／`not_verified`** | `tasks.py` 的 `_validated()` 加一次 `_require_choice`；`0036` 先跑一次資料檢查：既有值只可能是 `None` 或人手填的字串，**遷移把不認得的值一律寫成 `not_verified` 並在 migration 的輸出裡印出被改的列數** | `tasks.py:603` 今天只檢查形狀與長度，`result` 是自由字串。Done Gate 的「每一項 AC 都有結果」在自由字串上等於沒有檢查。**改寫而不是保留**：保留舊值會讓 Done Gate 對舊卡片與新卡片有兩種行為 |
| D10 | **`--force` 是新的 Admin 專屬動作 `task.force_done`；`cliora` CLI 沒有對應的子命令** | `PATCH /api/tasks/{id}` 帶 `force_reason`（必填、非空、≤2000 字）；沒有那個動作 → 403；理由寫進 `activity_events` 並在 Task Detail 永久顯示 | 複用 `task.approve` 會讓「核准一個 gate」與「跳過整個完成判準」同權。CLI 沒有這個子命令的理由與 `command.go:21` 寫的一模一樣：**一個存在的子命令會邀請 Agent 去試**，而它拿到的會是一個要它自己解讀的 403 |
| D11 | **執行計畫／驗證報告／evidence 三張表都只 INSERT** | 執行計畫用 `(task_id, seq)` 唯一鍵，改計畫是新增一列並帶 `note`；驗證報告與 evidence 沒有更新語意，只有新增 | `research/02/01` D9。**append-only 是這三張表唯一的完整性保證**——它們是「這件事憑什麼算做完」的依據，而一份可以就地改寫的依據不是依據 |
| D12 | **`source` 三級由伺服器端決定，忽略 payload，而且忽略了要說出來** | 寫入路徑固定：CLI／HTTP 提交的 → `agent_reported`；平台自己觀察到的（run 狀態、push 結果、PR 建立）→ `platform_observed`；daemon 在 run 內執行並擷取 exit code 的 → `machine_verified`。payload 帶了 `source` → **丟棄該欄位並記一筆 activity** | 出口條件 8 要驗的是「忽略了**而且說出來**」。只忽略的話，一個試圖偽稱的 Agent 與一個欄位打錯的 Agent 在紀錄上長得一樣 |
| D13 | **流程覆寫是 `projects` 上的一個 JSONB 欄，不新增表** | `projects.process_overrides`：`{"readiness_disabled": [...], "gates_disabled": [...], "wip": {"implementing": 3}}`。`ProcessService.effective(key, project_id)` 讀 default 那一列再套覆寫 | DV-08 要的是「**只允許啟用／停用既有項目**」——那是一組布林。做成表會邀請下一個人往裡面塞自訂項目，而「跨專案指標要能聚合」正是禁止自訂項目的理由。**被否決**：`process_definitions` 多幾列（那讓「有幾份流程定義」變成一個要查的問題，而答案應該永遠是一份） |
| D14 | **指標只顯示，不進任何自動阻擋邏輯** | 五個指標是查詢，不是狀態機的輸入 | `research/02/06` 的風險表最後一列。一個會影響派工的指標會立刻變成一個被優化的數字 |
| D15 | **provider adapter 只做 GitHub；host 不支援 → dispatch 當下拒絕** | `ProviderAdapter` 是一個 Protocol，`GitHubAdapter` 是唯一的實作；`repository.host` 決定挑哪一個；挑不到 → `TASK_PROVIDER_UNSUPPORTED` | 做一半的 GitLab 比沒有 GitLab 糟：它會讓人在 dispatch 之後才發現。**拒絕發生在 dispatch**，與 `TASK_BRANCH_NOT_DELIVERABLE` 同一個位置與同一個理由 |
| D16 ⚠️ | **Central 的對外 HTTP 出口有自己的 allowlist、逾時與重試上限，且 token 不進 log** | 只允許 `api.github.com`（可由 `CLIORA_PROVIDER_API_HOSTS` 覆寫，形狀抄 `runner.git.allowed_hosts`）；連線 5 秒、總計 20 秒；**不重試**（一個逾時的 PR 建立要當成失敗處理，重試會開出兩個 PR）；`httpx` 的 event hook 斷言 `Authorization` 不出現在任何 log 記錄 | Central 第一次主動連外（README 易錯 10）。**不重試**那一條是本條最容易做反的：一般的 HTTP client 慣例是重試，而**「建立」不是冪等的** |
| D17 | **PR 建立發生在 `finish()` 之外，由一個背景工作驅動** | `finish()` 只寫下「這個 run 需要開 PR」的意圖（`task_runs.delivery_state = 'pending_pr'`），實際的 HTTP 呼叫由既有的 reaper 迴圈（`run_reaper.py` 的形狀）撿起來做 | `finish()` 是 `node_gateway` 接收迴圈呼叫的，而那條迴圈**同時載著互動式終端的位元組**——一個 20 秒的 HTTP 呼叫會讓終端停 20 秒。`runs.py` 的 module docstring 與 `GATE-AR-NO-REQUEST-IN-LOOP` 已經為同一件事立過規矩。**這是本期最容易寫錯的一行程式碼**，因為在 `finish()` 裡 `await adapter.create_pr(...)` 看起來完全合理 |
| D18 | **`UNSUPPORTED_DELIVERIES` 清空但保留** | `runs.py:94` 的 dict 變成 `{}`，並在註解裡寫明它現在是空的、為什麼留著（下一種 delivery 的掛勾點） | 一個永遠不成立的檢查會被下一個人順手刪掉，而刪掉之後下一種 delivery 就沒有地方拒絕了。⚠️ 這條要配一個 gate（`GATE-DV-DELIVERY-COVERAGE`），否則註解擋不住任何事 |
| D19 | **本期的觸碰禁區（touch list）** | `terminal_relay.py`／`terminal_queue.py`／`tunnels.py`／`node_update.py`／`files.py`／`favorites.py`／`secret_box.py`／`secret_envelope.py`／`api/ws/terminal.py`／`daemon/internal/runtime/{runtime,launch}.go`／`daemon/internal/gitfetch/push.go` 的**五條約束區塊** | 前九項沿用 V2.3。🆕 **`push.go` 的約束區塊加進來**：本期會動那支檔案（`existing_pr` 的分支來源），而**約束本身一個字都不該改**——把它與檔案分開列，讓 gate 問得出「約束變了嗎」而不只是「檔案動了嗎」 |
| D20 | **本期的版本序** | contract **v1.13.0**、`agentd` **0.11.0**、migration 到 **0037**、RBAC **27** 個動作、ADR **0033** | 起點：contract v1.12.0、`agentd` 0.10.0、migration 0034、RBAC 25、ADR 0032 |
| D21 | **`cliora` CLI 新增三個子命令，且都是寫入** | `cliora plan snapshot <file>`、`cliora verify report <file>`、`cliora evidence add <kind> <file>`。**沒有讀取版**（`plan show` 之類）——Agent 剛寫的東西不需要讀回來，而每一個讀取端點都是一個要授權的面 | 沿用 `command.go` 既有的克制。三個都用 run 憑證，scope 不變（`task.update`） |

## 4. 波次與 ticket

**波次之間有真正的依賴，波次內可以並行。**

### 波次一 — 契約與資料（`DV-00` → `DV-03`）

| Ticket | 標題 | 交付 |
|---|---|---|
| `DV-00` | 基線擷取 ＋ **M6** | `artifacts/dv/local/baseline/` 六份；M6 的數字與它決定的逾時值 |
| `DV-01` | **ADR 0033** ＋ 三則增補 ＋ PRD §8.15 ＋ traceability ＋ **回溯條目** | `docs/adr/0033-…md`（proposed）；`traceability/requirements.json` 新增 11 筆 |
| `DV-02` | migration `0035`／`0036`／`0037` ＋ 模型 ＋ **AC 四值的資料收緊** | 40 張表；`downgrade` 回 `0034` 與基線逐位元組相同 |
| `DV-03` | contract **v1.13.0** ＋ fixtures ＋ `features` 的相容處置 | **`spec` 零新增欄位**；新增 fixture 含「`spec` 不得出現 `verification` 欄位」的 invalid 案例 |

> ⚠️ `DV-01` 的 ADR 要在 `DV-05` 開工前定稿到「內容不再變動」的程度——
> 那份 ADR 的 §4 是紅線 5 的拒絕清單，而 `DV-05` 的每一行程式碼都在它的約束下。

### 波次二 — 節點半（`DV-04`）

單張，但它是本期最大的一張。三塊互相獨立，可再細分：

1. 交付：`ShouldAttachDiff`／`SummaryText` 共用述詞、`delivery: artifact` 的摘要修正。
2. 驗證：`allowed_verification_commands` 的切分與執行、`verifying` phase、exit code 的擷取。
3. 證據：`diff --stat` 的補齊、`features` 的上報、`doctor` 多一行。

### 波次三 — Central 半（`DV-05` → `DV-09`，可並行）

| Ticket | 依賴 |
|---|---|
| `DV-05` PR 建立 | `DV-02`（`delivery_state` 欄）、`DV-01`（ADR §4） |
| `DV-06` 計畫／報告／evidence 的 service 與 API ＋ CLI | `DV-02`、`DV-03` |
| `DV-07` Done Gate ＋ `--force` | `DV-02`（AC 四值）、`DV-06`（要有報告才判得了） |
| `DV-08` 流程覆寫 | `DV-02` |
| `DV-09` 指標 | `DV-05`～`DV-08`（指標的分母來自它們） |

### 波次四 — 前端與出口（`DV-10`、`DV-11`）

`DV-10` 可以在波次三完成一半時開始（Task Detail 的四個區塊只依賴 `DV-06`）。
`DV-11` 最後，且**安全審查三節要在合併提案之前定稿**。

## 5. 風險

| 風險 | 對策 | 殘留 |
|---|---|---|
| 🔴 **在別人的 repo 上開了不該開的 PR** | provider 動作是封閉表（只有建立與查詢）；`base` 來自 `task.target_branch` 且必須存在於該 repo；`head` 必須是本次 run 推的那條 `cliora/` 分支；**四者任一不成立就不呼叫** | 一個設錯 `target_branch` 的卡片仍會開出一個目標錯誤的 PR。**這是人要看的東西**，平台只保證它在正確的 repo 上 |
| 🔴 **自動合併被日後加回來** | git 子命令 allowlist ＋ provider 動作 allowlist ＋ 兩個 gate ＋ ADR 0033 §4 的拒絕清單 | 低。三道都是「那個字不在表裡」而不是「那個字被檢查了」 |
| 🔴 **`finish()` 裡直接呼叫 provider API** | D17 的背景工作 ＋ `GATE-AR-NO-REQUEST-IN-LOOP` 的擴充（掃 `services/runs.py` 不得出現 `httpx`／`adapter.`） | 低，但**這是本期最可能被寫錯的一行**，所以 gate 而不是 review |
| 🔴 **驗證命令變成任意執行的後門** | 兩個來源都是平台的儲存面；Project 設定要 `project.manage`，**卡片宣告要 `task.approve`**（agent 永遠拿不到）；argv 陣列不經 shell；只在 run 的隔離目錄內 | 人本來就能設任意命令——**但那是人，而且它進了稽核**。與「Agent 自選」的差別是誰負責 |
| 🆕 **兩張卡用不同的標準宣稱自己完成**（D4 換來的彈性的代價） | `origin` 徽章在四處可見（報告、evidence、Run 詳情、PR 內文）＋ 專案級開關 `require_project_verification`（預設關閉）＋ 指標會顯示 `origin: card` 的比例 | 中。**這是刻意換來的**，收斂點是可見性而不是禁止——與 2026-08-10 ② 對 Agent 的 git 自由採取的是同一種處置 |
| 🔴 **把 Agent 自述當成機器事實** | `source` 伺服器端判定 ＋ payload 帶值時記 activity ＋ UI 三種樣式 ＋ 出口條件 7／8 | 中。**UI 是最後一道**，而一個把三級都畫成一樣的畫面會讓前面三道全部白做——所以 3g 那種「畫面斷言」的形式本期也要有（`08-…md` §5 的條件 8b） |
| **Done Gate 太嚴導致繞過** | `--force` ＋ 必填理由 ＋ 永久可見 ＋ **指標追蹤次數**（第三個指標就是它） | 中。指標會告訴我們判準是不是訂錯了，**而那正是它存在的理由**——不是為了抓人 |
| **PR 灌爆 repo** | 同一張卡同時只有一個進行中的 run（V2.2 已有）；無變更不開 PR；分支命名可辨識、可批次清理 | 低 |
| **舊 daemon 收到本期的 offer** | D2 ＋ D6 讓 `spec` 零新增；D3 的 `features` 讓新功能不被送給不宣告的 node | 低，**而且順便修好了 V2.3 留下的同一個洞** |
| **Central 的新 egress 成為 SSRF 面** | host allowlist ＋ 不重試 ＋ 逾時 ＋ token 不進 log ＋ 安審 §1 | 中。`CLIORA_PROVIDER_API_HOSTS` 是部署層的設定，設錯是部署的責任——**但預設值必須是安全的**（只有 `api.github.com`） |
| **三張新表讓 run 的寫入路徑變慢** | 三張都只 INSERT，沒有索引以外的約束；evidence 的採集在 daemon 端有逾時（M6） | 低 |
| 🆕 **`existing_pr` 的範圍限制讓人以為功能壞了** | dispatch 的拒絕訊息**直接說出來**：「這條分支不在 `cliora/` 命名空間內，而平台只推得到那裡面」＋ 設定頁的一段說明 | 中。這是一個**設計決定看起來像 bug** 的典型，所以文案是對策的一部分不是裝飾 |
