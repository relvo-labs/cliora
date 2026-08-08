# 08 — 驗證、出口條件與尚未量測項

## 1. 共通完成定義（每張 ticket）

沿用 `../Monstrare/ai/process/definition-of-done.md` 的要求，對應到本 repo 的既有工具：

- 變更檔案清單與行為變更摘要。
- `make check` 通過（format、lint／vet、型別、單元、contract、build）。
- 涉及 daemon／tmux 的：`make integration`。
- 涉及畫面的：`make e2e` ＋ 截圖。
- 涉及 DB 的：`make test-db` ＋ migration 上下行演練。
- 涉及 RBAC 的：`backend/tests/db/test_permission_matrix.py` 三條全綠。
- 涉及 protocol 的：valid ＋ invalid fixtures 齊備。
- 高風險（授權模型、寫入面、路徑安全）：安全審查文件（`docs/security-review-*.md` 的既有格式）。
- 已知限制與後續任務寫下來。

**不算完成**（照既有紀律）：跳過測試沒說明理由、驗證只是「看起來沒問題」、UI 改了沒截圖、AC 沒逐項檢查、動了不相關的檔案。

## 2. 各階段出口條件

### 2.1 V2.0

1. 建立 Project，綁定**兩個不同 Node** 上的 workspace，Project 頁面正確顯示兩者的 node 線上狀態。
2. 從 Project 建立的 Session 出現在該 Project 時間軸；Ad-hoc Session 不出現在任何 Project。
3. 解綁 workspace 不影響進行中的 Session。
4. 刪除 Node → 綁定列消失，Project 存活。
5. 綁定一條「曾經合法但 root 已停用」的路徑後，用它建 Session 被拒（**重驗證，不信任綁定表**）。
6. 旗標關閉：完整 V1 回歸全綠，導覽退回五個平項，`/projects` 404。
7. `pg_dump --schema-only` 差異只有預期的四項；既有表逐欄比對無變化。

### 2.2 V2.1

1. 在平台上建立 Epic → User Story → 3 張 Task，拖曳推進，Roadmap 完成度正確。
2. 從 Task Detail 開 Session → `.cliora/context/<session_id>.md` 與 `.token` 出現、情境包 ≤4 KB 且含驗收標準。
3. Agent 執行 `cliora task update TASK-123 --stage implementing` → 看板即時更新 → 時間軸事件的 actor 標示為「Session 的 agent」而非人類。
4. Agent 用其 token 嘗試 `POST /gates/architecture` → **被拒**（scope 寫死不含 `task.approve`）。
5. 前置卡未完成的卡拖到 `implementing` → 被拒，訊息**指名是哪幾張卡**。
6. 兩分頁同時拖同一張卡 → 後者 409（`version` 衝突）、彈回、重新載入。
7. **Central 停機時**：Session 中的 CLI Agent 仍正常工作；`cliora context show` 仍可讀；`cliora task update` 失敗且訊息符合 D14。
8. 同一 workspace 開第二個 Session → 流程檔目錄已存在被跳過（`FILE_EXISTS` 視為成功），情境包是新檔案。
9. **`git status` 在使用者 repo 只看到 `.cliora/`**（且可 gitignore），沒有其他檔案被平台建立或修改。
10. `.cliora/` 保留期到期後由 daemon 清理，Session 仍可運作（過期只是少了投影，不是壞掉）。
11. 旗標關閉：完整 V1 回歸全綠；**contract fixtures 與 daemon 測試無任何變更**。

### 2.3 V2.2

1. `cliora plan snapshot` 寫三次 → Plan 面板顯示最新、Task Detail 顯示三次歷史與每次 `note`。
2. `result: failed` 的報告 → 失敗 check 與 AC 預設展開且**不可摺疊隱藏**。
3. Agent 請求裡帶 `source: machine_verified` → 伺服器忽略、存為 `agent_reported`、記一筆 activity（**要有測試**）。
4. 把缺驗證報告的卡拖到 `done` → **被拒**，訊息指名缺哪一項。
5. Admin `--force` 推進 → 成功，理由進時間軸且在 Task Detail 永久可見。
6. 斷網下 `cliora task update` **直接失敗**（D14），訊息含「Session 可繼續工作」；`cliora context show` **仍可讀**；Agent 未因此中斷工作。
7. 不合 schema 的輸入 → 拒絕並回可行動訊息，**不寫入半筆資料**。
8. **Ad-hoc Session 的 Session Workspace 與升級前截圖逐像素一致。**
9. 旗標關閉：完整 V1 回歸全綠。

### 2.4 V2.2（Agent Runner）

1. runner 綁兩個 Project → 兩邊都能領；**沒綁的第三個永遠不會被 offer**。
2. 未指定 agent 的卡片：任一符合資格者可領。
3. **指定 agent 的卡片：只有那一個 runner 領得到。**
4. 指定一個沒綁該 Project 的 runner → dispatch **回 409 不入佇列**（指定不繞過授權）。
5. 指定的 runner 離線 → 入佇列並顯示「等待指定的 Agent（離線）」，**文案與「沒有可用的 Agent」不同**。
6. 兩個 runner 同時 poll 同一張卡 → **只有一個領到**，`task_runs` 沒有兩列。
7. kill runner 程序 → 租約逾時標 `lost`、重排、完成；**被指定的卡重排仍只給原本那個 runner**。
8. 重排三次都失敗 → 卡片進 `blocked`，原因寫明，**不無限重試**。
9. `run.cancel` → 程序真的停止，`ps` 驗證無殘留。
10. Run log 超過上限 → 截斷並**明示位元組數**。
11. `cliora task ask` → 卡片顯示「等待你的回覆」；回覆後 Agent 拉得到；24h 未回覆自動退 `blocked`。
12. **互動式 Session 完全不受影響**；`terminal_sessions` 沒有 run 的列。
13. 執行中 `cliora task attach` → 訊息與產物同時出現在卡片；**run 目錄被清掉後產物仍可下載**。
14. `.html` 產物下載時帶 `Content-Disposition: attachment` ＋ `nosniff`；**應用 origin 內沒有任何路徑會渲染它**。
15. 專案產物配額用盡 → runner 收到明確錯誤並顯示在卡片，**不是靜默失敗**。
16. 已附加的產物**沒有任何 API 可以修改**；刪除只有 `project.manage`，需理由 ＋ audit。
17. 旗標關閉：完整 V1 回歸全綠。

### 2.5 V2.3（機密與隔離）

1. 建立機密後**任何 API 都讀不回值**（OpenAPI schema 斷言 ＋ 實際回應斷言，兩條）。
2. 機密值出現在 CLI 輸出 → 平台收到的 log 是 `***`；**原值從未離開 node**（Central 端斷言）。
3. `accept_secrets: false` 的 node → 其 runner 永不被 offer 需要機密的卡片。
4. `source: repo` → run 目錄有 `repo/`、在正確 base branch、分支名 `cliora/<card_ref>-<run_seq>`。
5. `source: none` → **沒有** `repo/`，Agent 讀不到程式碼。
6. daemon 嘗試推 `main`／非 `cliora/` 前綴／force push／allowlist 外的 host → **四種全部在 daemon 內被拒**。
7. run 結束依保留期清理；第二次 run 用 mirror，**不重新完整 clone**（比對耗時）。
8. run 程序嘗試讀寫任何 allowed root → 失敗。
9. 配額用盡的 node 停止 poll 並顯示原因，其他 node 照常。
10. 刪除機密後下次 run 拿不到；進行中的 run 不受影響。
11. 旗標關閉：完整 V1 回歸全綠。

### 2.6 V2.4（交付與驗證）

1. **五種** `delivery` 各跑通一次；`none` 與 `artifact` 都不產生任何遠端變更。
2. `delivery: none`／`artifact` 但有變更 → 明示「偵測到 N 個檔案變更」**並把 diff 附成一件卡片產物**，未靜默丟棄。
2b. `delivery: artifact` 但一件產物都沒有 → **run 不算成功**。
3. `delivery: pull_request` 但無變更 → 成功、結論「無變更」、**沒有空 PR**。
4. PR 建立失敗 → 分支仍在、標 `delivered_branch_only`、**run 不算失敗**。
5. **自動合併的程式碼路徑不存在**（對 daemon 的 git 子命令 allowlist 斷言）。
6. 故意讓測試失敗 → 驗證報告是 `failed`，不是 Agent 自稱的 `passed`（exit code 是真的）。
7. Agent 帶 `source: machine_verified` → 伺服器忽略、存為 `agent_reported`、記 activity。
8. **`delivery: none`／`artifact` 的卡可正常進 `done`**，不因缺 PR 被擋；`artifact` 缺產物時被擋。
9. 缺驗證報告的卡進 `done` → 被拒並指名缺項；Admin `--force` 可過且理由永久可見。
10. 旗標關閉：完整 V1 回歸全綠。

### 2.7 V2.5（需求釐清與拆解）

1. 丟一句模糊需求 → 釐清 run 領走 → **在看板訊息串裡提問**（不是另一個介面）→ 回答 → 產出規格草稿。
2. 規格帶未解決的 `open_questions` → **核准按鈕停用**且說明是哪幾個。
3. 未核准的規格**不能被拆解**（API 層拒絕，不是 UI 隱藏）。
4. 拆解產出的每張 Task 提案都帶完整 DoR 七項與 `source`／`delivery`；缺項的卡接受後**落 `backlog` 而非 `ready`**。
5. 部分接受：勾 3 張建立 3 張，其餘保留；被拒絕的提案保留理由。
6. 建立出來的卡片顯示「來自需求 #N 的提案 #M」。
7. 釐清 run 嘗試帶機密 → **dispatch 當下被拒**。
8. 釐清 run 的 `delivery` 是 `none` → 執行後**遠端無任何變更**；工作目錄若有變更則明示。
9. Agent 嘗試自己核准規格或接受提案 → 被拒（scope 不含 `task.approve`）。
10. 24h 未回覆自動退 `blocked`，**已問到的內容保留為規格草稿，不整批丟棄**。
11. **未啟用 tunnel 整合時**：`ui` gate **自動停用**（不是靠 Admin 手動關）；Project Settings 寫出停用原因；產出 mockup 變體的卡片 dispatch **被拒並說明**；**一般 UI 實作卡照常執行**；Agent 附截圖為產物**不受影響**。
12. 啟用 tunnel 整合後：mockup 變體可預覽，保護策略由 Agent 在卡片上詢問、人選擇、**平台開啟**；Agent 憑證嘗試 `tunnel.manage` 被拒；run 結束 tunnel 一併關閉。
13. 旗標關閉：完整 V1 回歸全綠。

## 3. 旗標關閉回歸套組（每階段都跑）

這是「既有功能都要保留」這句話的可執行形式。`CLIORA_PROJECTS_ENABLED=false` 時：

| 檢查 | 方法 |
|---|---|
| API 表面未變 | OpenAPI schema 與升級前 diff：只允許新增路徑，且新增路徑全部 404 |
| 兩個旗標各自獨立 | `PROJECTS_ENABLED=true` ＋ `AGENT_RUNS_ENABLED=false` 時，看板可用、Agents 頁不出現、`dispatch` 404 |
| Protocol 未變 | 現有 fixtures 全數通過；舊 daemon 可正常連線與工作 |
| 五個既有路由可直達 | e2e 逐一造訪 `/dashboard`、`/nodes`、`/sessions`、`/enrollment`、`/audit` |
| 導覽外觀 | 截圖比對 |
| Session 全生命週期 | 建立 → 操作 → 重整重連 → 接手 writer → 終止 |
| 檔案面 | 瀏覽、搜尋、預覽、圖片投放、一般上傳（含 `FILE_EXISTS` 拒絕） |
| System terminal | 開啟、sudo 姿態、單一 live shell 限制 |
| Tunnel | 開啟、狀態、關閉 |
| RBAC | 三角色 × 既有 16 動作的矩陣 |
| DB | 既有表逐欄 schema 比對 |

## 4. 測試矩陣（新功能）

| 層 | 覆蓋 |
|---|---|
| Contract fixtures | V2.0／V2.1 **零變更**；V2.2 起每個新訊息 valid ＋ ≥6 invalid，**含「`secrets` 出現在非 offer 訊息」這一條** |
| Daemon 單元 | 租約續租與逾時、容量控管、log 分塊與截斷、**去識別**、git 五條約束的 argv 組裝、run 目錄配額與隔離 |
| Daemon 整合 | 真實 repo 的 clone／worktree／push 拒絕；真實程序的 cancel 與殘留檢查 |
| Central 單元 | **原子認領**、重排上限、**資格判定五條件（含指定不覆蓋綁定）**、Done Gate 依 `delivery` 分歧、`source` 伺服器端判定、機密 allowlist 子集檢查 |
| Central DB | migration 上下行、`version` 樂觀鎖併發、**併發認領**、RBAC 矩陣 |
| CLI | 每個子命令一條測試；`task ask`／`say`／`messages` 的往返；**離線行為**（失敗訊息內容、非零 exit code、`context show` 免連線） |
| 前端單元 | 看板分組、藍圖聚合（含未分類桶）、run 狀態徽章、訊息串三種來源、機密欄位無顯示值路徑 |
| E2E | 建 Project→綁 runner→建卡（四種 delivery 各一）→dispatch→領取→執行→提問→回覆→交付→Done Gate |
| E2E（V2.5） | 提需求→釐清 run 提問→回答→規格→核准→拆解→部分接受→卡片可追溯回需求 |
| 安全 | 機密不可讀回（schema ＋ 回應）、log 去識別、git 四種推送拒絕、run 目錄隔離、token scope、gate 必帶人類 actor |

## 5. 尚未量測、開工前或階段內要補的數字

沿用 `plan/12`／`plan/15` 的「開放量測項」慣例——這些是**還不知道答案的問題**，不是待辦事項。

| # | 問題 | 影響什麼 | 何時測 |
|---|---|---|---|
| M1 | 一個 200 張卡的專案，看板 API 的回應大小與耗時？ | 是否需要分頁 | V2.1 開工前用假資料測 |
| M10 | 一次典型 run 的 log 有多大？100 個 run 之後 `run_logs` 多大？ | 是否要改物件儲存（AR-05 先進 PostgreSQL） | V2.2 上線後統計 |
| M11 | 一個真實 repo 的首次 clone 與後續 worktree 各要多久？ | run 的啟動延遲是否可接受；mirror 策略 | **V2.3 開工前** |
| M12 | run 目錄的典型大小？一個 node 跑 3 個並行需要多少磁碟？ | 配額預設值與 node 的部署規格建議 | V2.3 開工前 |
| M13 | `waiting_for_input` 的實際等待時間分布？ | 24h 逾時是否合理；Agent 是不是問太多 | V2.2 上線後觀察 |
| M14 | **V2.1 的人工規格／拆解表單有沒有人用？** | **V2.5 值不值得做的早期訊號**（D28 §4）。沒人用人工流程，Agent 版也不會有人用 | V2.1 上線後持續觀察 |
| M15 | 一次釐清平均要問幾輪？使用者回覆的中位時間？ | 「一次一個問題」是否可行；逾時值 | V2.5 上線後觀察 |
| M16 | 一張卡實際會累積多少產物、多大？ | `ARTIFACT_PROJECT_QUOTA_MB` 預設值；要不要改物件儲存 | V2.2 上線後統計 |
| M2 | **Agent 實際使用 `cliora` CLI 回報的比例？** | D11 的整個前提；也是 **MCP 做不做**的第一個判準 | **V2.1 上線後觀察前 10 個 Session** |
| M3 | 情境包壓到 4 KB 後，Agent 的行為是否真的變好？ | D8 的預算值 | V2.1 上線後觀察 10 個 Session |
| M4 | 計畫快照一張卡實際會產生幾個？50 的上限合理嗎？ | D9 的清理策略 | V2.2 上線後觀察 20 張卡 |
| M5 | Agent 提交的資料有多少比例不合 schema？ | 更寬鬆的解析／更好的提示；與 M2 合看決定 **MCP 做不做**（`01` D11 的三格規則） | V2.2 上線後統計 |
| M17 | 情境包實際用掉多少 4KB 預算？ | MCP 的工具定義約 1KB 常駐——**預算已緊時，MCP 的淨效果可能是負的** | V2.1 上線後統計 |
| M9 | 平台不可用的實際頻率與時長？ | **D14 重新評估的觸發條件**（目前裁決是直接失敗、不做佇列）。數據若顯示不可用頻繁，先問「為什麼平台這麼常掛」，而不是直接做佇列 | V2.1 起持續觀察 |
| M6 | `git status --porcelain` 在最大的實際 repo 上要多久？ | 證據採集的逾時值 | V2.4 開工前 |
| M7 | 有多少 Session 實際上是 Ad-hoc？ | 決定 V2 的預設值該不該變 | V2.1 起持續觀察 |
| M8 | sidebar 208px 在七列兩層下是否還夠？ | `07` §3 | V2.0 開工時 |

M1、M8（V2.1 前）、M11、M12（V2.3 前）、M6（V2.4 前）是**開工前**要有答案的；**M2 是 V2.1 上線後最重要的一項**——它驗證的是內化路線的核心假設（Agent 會用工具回報）。其餘是上線後觀察，答案回填到對應階段的 `plan/NN/0X-open-measurements.md`。

## 6. 每階段的安全審查觸發條件

以下任一成立就要產出 `docs/security-review-*.md`：

- 新增或改變授權輸入。
- 新增寫入路徑或新的儲存面。
- 新增在 node 上執行程序的能力。
- 新增憑證或機密流。

**四次安全審查，都不可略過**：

| 階段 | 觸發原因 | 審查重點 |
|---|---|---|
| V2.1 | Session token | 發行、scope、失效、檔案落地與保留期 |
| V2.2 | 無人值守執行 ＋ run log ＋ **卡片產物** | 認領授權、租約、log 界線（D27）、cancel 可靠性、**產物提供路徑的 stored XSS**（D29 §4）、配額 |
| **V2.3** | **機密流 ＋ 新儲存面 ＋ git 寫入** | 加密與金鑰、不可讀回、去識別、run 目錄隔離與配額、git 五條約束 |
| V2.4 | 對外副作用（PR） | 交付模式邊界、無自動合併、供應商憑證 |
| V2.5 | **不必然觸發**（無新憑證、無新儲存面、無新執行能力）；若釐清 run 需要讀敏感文件則補 | — |

**V2.3 是整個 V2 風險最高的一次**，它同時觸發三條。它的審查文件要分成三節、三組邊界測試各自獨立，不要合寫成一段「Agent 執行環境安全審查」。

## 7. 合併回 `dev` 的關卡（**人工確認，不自動**）

> **2026-08-08 裁決：`v2` 何時合併回 `dev`，一律由人工確認。**
> 自動化（含 CI 與 agent）**不得**發起或完成這個合併，即使所有出口條件都是綠的。

### 為什麼這一條要寫下來

它和平台自己的設計是同一個形狀，只是高了一層：

| 層 | 客觀條件 | 人工關卡 |
|---|---|---|
| 一張任務卡 | Done Gate（驗證報告、AC、交付證據） | Review Gate 必帶人類 actor；Agent 憑證的 scope 寫死不含 `task.approve` |
| 一個階段 | 本文件 §2 的出口條件 ＋ §3 的旗標關閉回歸 | **合併回 `dev` 由人決定** |

「客觀條件通過」與「可以合併了」是兩件事。前者是機器能回答的，後者不是——它還包含時機、其他分支的狀態、要不要先等某個量測結果。**條件全綠只是取得提案資格，不是核准。**

### 操作規則

1. 階段工作以正常 PR 進 `v2`。
2. 階段的 §2 出口條件與 §3 回歸套組全部通過 → **在 PR 或 issue 上提出合併請求**，附上證據。
3. 由人審閱後決定合併時機。**沒有自動合併、沒有排程合併、沒有「條件綠了就 merge」的 CI job。**
4. 合併後在對應的 `plan/NN/0X-implementation-status.md` 記錄合併的 commit 與日期。

### 建議（不強制）

在 GitHub 上對 `dev` 設 branch protection（required PR review），讓這條規則由平台強制而不只是靠紀律。**這是 repo 設定的變更，要由你自己決定與執行。**

### 與合併節奏的關係

建議仍是**每階段合併一次**（`00` §6：階段是 release gate），讓 merge debt 最多累積一個階段的量。但「每階段都應該合併」與「這一次要不要合併」是兩個問題——前者是節奏建議，後者永遠是人的決定。
