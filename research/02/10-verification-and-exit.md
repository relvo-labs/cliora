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
11. 旗標關閉：完整 V1 回歸全綠；**contract 的既有 fixtures 逐檔 sha256 無變更**（只允許新增檔案），
    daemon 的 terminal／tmux／tunnel／既有檔案路徑零 diff，且 `agentd` 0.8.0 在旗標關閉時
    行為與 0.7.0 相同。（2026-08-09 修訂：V2.1 動 contract v1.10.0 ＋ `agentd` 0.8.0，
    原本寫的「無任何變更」改為「既有的無變更」。）

### 2.3 V2.4（計畫與驗證）

> **2026-08-10 更正**：本節原本的標題是「V2.2」，但內容（`plan snapshot`、驗證報告、
> 證據可信度、Done Gate、Admin `--force`）對應的是 **FR-PLAN／FR-VERIFY**，
> 那是 **V2.4** 的工作包（`11` §2）。V2.2 的出口條件在 §2.4，V2.4 的其餘出口條件在 §2.6。
> 不更正的話，V2.2 的收尾 ticket 會對著一份不屬於它的清單交差。

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

> **2026-08-10 裁決改寫本節。** Agent 自己把專案拉到 daemon 擁有的隱藏目錄；
> workspace 綁定從此只服務互動式 Session；`project_agents` 綁定與 label 比對延後到 V2.3／後續。
> **2026-08-12 更新**：綁定**不做了**，label（tag）比對**提前到 V2.3**——本節（V2.2）不受影響，
> 受影響的是 §2.5（`01` D18）。
> **完整的 23 條清單見 `04-phase-v22-agent-runner.md` §出口條件**，本節列其中改動最大的十條，
> 其餘不變。搬動了什麼、為什麼，見 `04` §0。

1. **未指定** agent 的卡片：任一 runner 都領得到（本期不比對 tag，「任一」就是字面意思）。
2. **指定** agent 的卡片：只有那一個 runner 領得到。
3. 指定一個**已停用**或**runtime 不符**的 runner → dispatch **回 409 不入佇列**，訊息指名是哪一條。
   （原本這一條的例子是「沒綁該 Project」。D18 延後之後例子換了，
   **而「不符資格要在 dispatch 當下擋下」這條規則不變**。
   2026-08-12 之後 V2.3 會再加一種例子：**缺哪幾個 tag**，見 §2.5 條件 6c。）
4. 指定的 runner 離線 → 入佇列並顯示「等待指定的 Agent（離線）」，
   **文案與「沒有可用的 Agent」不同**。
5. 兩個 runner 同時 poll 同一張卡 → **只有一個領到**，`task_runs` 沒有兩列。
6. 🆕 **`source: repo` 的卡被領走後，run 目錄裡出現一份 clone**，`commit_sha` 回報並顯示在 Run 詳情頁。
7. 🆕 **run 目錄不在任何 allowed root 內**：既有檔案瀏覽 API 讀不到它；
   daemon 在 run root 落在 allowed root 內時**拒絕以 runner 模式啟動並指名**。
8. 🆕 **平台的任何路徑都沒有碰使用者的 workspace**：run 進行中與結束後對 workspace 做
   `git status --porcelain` **完全為空**。⚠️ **不是「Agent 讀不到」**——
   那件事平台沒有實作（`04` AR-02b 規則 1 的 2026-08-10 更正）。
   替代條件：**`allowed_roots` 非空的 node 在 Agents 頁顯示「⚠ 混合用途」**。
9. 🆕 **clone 之後 `git remote -v` 是空的**；一次 `git push` 在 run 目錄裡直接失敗。
10. 🆕 缺 git 憑證時 clone **快速失敗**（秒級 `run.failed`，不掛在密碼提示上直到牆鐘兜底）。
10b. 🆕 **一個「還在跑但很慢」的 run 不會被誤殺**（每 60 秒一個事件、共 20 分鐘 → 正常完成）；
    **一個真的掛住的 child 在 idle 上限內被收掉**（`RUN_IDLE_TIMEOUT`，不是等牆鐘）；
    **runner 掛了（`lost` → 重排）與 child 掛了（不重排）是兩種不同結果**。
    存活判定靠事件流不靠牆鐘（`04` AR-04 的三個計時器）。
11. 🆕 **`delivery: none` 的卡在工作目錄留下變更 → `git diff` 被附成一件產物**，不是靜默丟棄。
12. 🆕 **run 目錄配額用盡 → runner 停止領取新工作並回報原因**，
    平台顯示為「磁碟用盡」而非「離線」。
13. `run.cancel` → 程序真的停止，**process group 下無殘留**
    （原本寫「`ps` 驗證」；改為掃 pgid，因為 `ps` 目視不是可重跑的斷言）。
14. 其餘（重排、log 截斷、`task ask`、互動式 Session 不受影響、產物的四條、旗標關閉）
    與原清單相同，見 `04` §出口條件 11–23。

### 2.5 V2.3（機密與隔離）

1. 建立機密後**任何 API 都讀不回值**（OpenAPI schema 斷言 ＋ 實際回應斷言，兩條）。
2. 機密值出現在 CLI 輸出 → 平台收到的 log 是 `***`；**原值從未離開 node**（Central 端斷言）。
3. `accept_secrets: false` 的 node → 其 runner 永不被 offer 需要機密的卡片。
4. `source: repo` → run 目錄的 `repo/` 在正確 base branch，**分支名 `cliora/<card_ref>-<run_seq>`**
   （目錄與 clone 本身已在 V2.2 交付；本期新增的是**分支命名空間**）。
5. daemon 嘗試推 `main`／非 `cliora/` 前綴／force push／allowlist 外的 host → **四種全部在 daemon 內被拒**。
6. ~~**`project_agents` 綁定成為機密的授權邊界**~~ → **2026-08-12 裁決刪除這一條**（綁定表不做）。
   取而代之的是下面 6a–6e 五條：四條驗 tag 比對真的成立，一條驗**沒有畫面暗示存在一個更強的邊界**。
6a. **tag 比對**：卡片要 `docker` → 只有具備 `docker` 的 runner 拿得到；另一台線上、閒置、
   runtime 相符但缺該 tag 的 runner **永遠不會被 offer 它**。
6b. **`run_untagged: false` 的 runner 只領有宣告 tag 的卡片**，同時線上的
   `run_untagged: true` runner 照常領走無 tag 的卡片（兩台一起跑一次）。
6c. **指定一個 tag 不符的 runner → 409 且訊息指名缺哪幾個 tag**，不入佇列（D17b）。
6d. **湊不齊 tag 的卡片說得出缺什麼**：畫面顯示「沒有 runner 同時具備 `docker`、`node20`」，
   不是泛用的「等待可用的 Agent」。
6e. **授權邊界的誠實性**：Agents 頁與卡片上**沒有任何 UI 暗示 tag 是授權**（無鎖頭、無「授權」字樣），
   而 **enrollment 畫面直接寫著「這台機器將可以領取任何專案的卡片，並取得那些卡片宣告的機密」**
   （`01` D18 代償第 4 條）。這一條是畫面斷言，不是文件承諾。
6f. **舊版 daemon（0.9.0）連上來仍能領無 tag 的卡片**（`run_untagged` 未帶時視為 `true`）。
7. **（2026-08-13 裁決改寫）平台管理的 git 憑證是一個預設關閉的能力**：
   `CLIORA_GIT_SECRET_DELIVERY_ENABLED=false`（預設）時——`kind: git_pat`／`git_ssh_key`
   的機密**建立被拒並指名該變數**、`auth_kind` 只能是 `ambient`、
   **`HOME`／`GIT_CONFIG_GLOBAL` 不被改寫**，clone 與 push 用 node 上既有的憑證且都成功。
   `=true` 時——`clone` 用的是下放的 PAT／SSH key，且 run 的 git 環境裡讀不到機器原本的憑證。
   **兩種組態各跑一次才算通過。**
   （原文只有後半，而那會讓預設組態下的每一次私有 repo clone 都失敗——見 `05` SC-02 的修訂。）
8. 刪除機密後下次 run 拿不到；進行中的 run 不受影響。
9. `source: none` → **沒有** `repo/`，Agent 讀不到程式碼（V2.2 已成立，本期回歸）。
10. run 結束依保留期清理；第二次 run 用 mirror，**不重新完整 clone**（V2.2 已成立，本期回歸）。
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
11. 🆕 **一張真的派給 Agent 的交付型卡，跑完之後六項完成證據齊備而不需要 `--force`。**
    ⚠️ **這一條是 2026-08-14 補的，而它補的是一個真實的洞**（Traqora `TASK-4`，`plan/21/09` §6.2）：
    第 9 條驗的是「缺證據會被擋」——那一條**過了**。沒有人驗過的是**反過來的那一面**：
    一次正常、成功、把工作做完的 run，證據會不會自己到位。答案是不會，
    而症狀要等到有人嘗試移動卡片才出現。
    **只驗「該擋的擋住了」而不驗「該過的過得去」，一個擋住所有東西的 gate 也能全綠。**
12. 🆕 **兩條 PR 建立路徑各驗一次，而且分得出來驗的是哪一條。**
    A＝平台的 `DeliveryService` 開；B＝**Agent 自己接單開**（2026-08-14 在 staging 上
    已經走通，`plan/21/09` §6.1）。兩者在 PR 的作者欄上**分不開**（同一枚憑證的擁有者），
    **分得出來的是標題與內文的形狀**——A 產的是 `[{card_ref}] {title}` ＋ 驗證報告模板。
    ⚠️ **驗收時要看那個形狀，不要看「PR 存在」**：一個 PR 存在只證明其中一條路走通了，
    而這一條的兩半各自可以失敗。
13. 🆕 **走 B 的卡片要能不靠 `--force` 進 `done`。**
    ⚠️ 目前不行，而且是結構性的：`delivery_ref` 對 B 永遠是空的，
    所以第 8 條的交付證據那一項**對 B 恆缺**。
    **這一條沒過的話，B 就不是一條路而是一個會卡住的洞。**

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
| Contract fixtures | V2.0 **零變更**；**V2.1 新增一組 `context.project` 的 valid ×3 ＋ invalid ×8**（既有 fixtures 零變更）；V2.2 起每個新訊息 valid ＋ ≥6 invalid，**含「`secrets` 出現在非 offer 訊息」這一條** |
| Daemon 單元 | 租約續租與逾時、容量控管、log 分塊與截斷、**去識別**、**非互動 argv（prompt 走 stdin，不進 argv）**、run 目錄配額與隔離（V2.2）；git 五條約束的 argv 組裝（V2.3） |
| Daemon 整合 | 真實 repo 的 clone／worktree（V2.2）與 push 拒絕（V2.3）；真實程序的 cancel 與 process group 殘留檢查 |
| Central 單元 | **原子認領**、重排上限、**資格判定（V2.2 是四條件；V2.3 加回綁定並測「指定不覆蓋綁定」）**、Done Gate 依 `delivery` 分歧、`source` 伺服器端判定、機密 allowlist 子集檢查 |
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
| M11 | 一個真實 repo 的首次 clone 與後續 worktree 各要多久？ | run 的啟動延遲是否可接受；mirror 策略 | **V2.2 開工前**（2026-08-10 裁決把 clone 提前到 V2.2） |
| M12 | run 目錄的典型大小？一個 node 跑 3 個並行需要多少磁碟？ | 配額預設值與 node 的部署規格建議 | **V2.2 開工前**（同上） |
| M13 | `waiting_for_input` 的實際等待時間分布？ | 24h 逾時是否合理；Agent 是不是問太多 | V2.2 上線後觀察 |
| M14 | **V2.1 的人工規格／拆解表單有沒有人用？** | **V2.5 值不值得做的早期訊號**（D28 §4）。沒人用人工流程，Agent 版也不會有人用 | V2.1 上線後持續觀察 |
| M15 | 一次釐清平均要問幾輪？使用者回覆的中位時間？ | 「一次一個問題」是否可行；逾時值 | V2.5 上線後觀察 |
| M16 | 一張卡實際會累積多少產物、多大？ | `ARTIFACT_PROJECT_QUOTA_MB` 預設值；要不要改物件儲存 | V2.2 上線後統計 |
| M2 | **Agent 實際使用 `cliora` CLI 回報的比例？** | D11 的整個前提；也是 **MCP 做不做**的第一個判準 | **V2.1 上線後觀察前 10 個 Session**。⚠️ **第一個資料點是 0/1（2026-08-14，Traqora `TASK-4`）**：Agent 寫了一份完整的報告，**用 PR 留言送**，沒有走 CLI——`verification_reports` 是空的（`plan/21/09` §6.2）。**這一個樣本不足以下結論，但它指出的方向要記**：問題不是 Agent 不肯回報，是**它選了一個人看得到、平台看不到的通道**。所以 M2 要跟著問第二個問題——**沒走 CLI 的那些，證據去了哪裡**。如果答案總是「一個人類可讀但平台讀不到的地方」，那 MCP 這條路買到的不是格式而是**通道的唯一性**，而那是一個比格式更強的理由 |
| M3 | 情境包壓到 4 KB 後，Agent 的行為是否真的變好？ | D8 的預算值 | V2.1 上線後觀察 10 個 Session |
| M4 | 計畫快照一張卡實際會產生幾個？50 的上限合理嗎？ | D9 的清理策略 | V2.2 上線後觀察 20 張卡 |
| M5 | Agent 提交的資料有多少比例不合 schema？ | 更寬鬆的解析／更好的提示；與 M2 合看決定 **MCP 做不做**（`01` D11 的三格規則） | V2.2 上線後統計 |
| M17 | 情境包實際用掉多少 4KB 預算？ | MCP 的工具定義約 1KB 常駐——**預算已緊時，MCP 的淨效果可能是負的** | V2.1 上線後統計 |
| M9 | 平台不可用的實際頻率與時長？ | **D14 重新評估的觸發條件**（目前裁決是直接失敗、不做佇列）。數據若顯示不可用頻繁，先問「為什麼平台這麼常掛」，而不是直接做佇列 | V2.1 起持續觀察 |
| M6 | `git status --porcelain` 在最大的實際 repo 上要多久？ | 證據採集的逾時值 | V2.4 開工前 |
| M7 | 有多少 Session 實際上是 Ad-hoc？ | 決定 V2 的預設值該不該變 | V2.1 起持續觀察 |
| M8 | sidebar 208px 在七列兩層下是否還夠？ | `07` §3 | V2.0 開工時 |
| M18 | 🆕 **成功結束的 run 裡，六項完成證據自己到位的比例？** | 「證據入口在不在 Agent 的順手路徑上」是不是真問題。**低於 80% 就不是 Agent 的問題而是入口的問題** | **V2.4 起，從第一張交付型卡開始**——分母小的時候這個比例最有資訊。逐格見 `plan/21/10` §2.2b（M-DV-3） |

M1、M8（V2.1 前）、**M11、M12、M-AR-1（V2.2 前）**、M6（V2.4 前）是**開工前**要有答案的；**M2 是 V2.1 上線後最重要的一項**——它驗證的是內化路線的核心假設（Agent 會用工具回報）。其餘是上線後觀察，答案回填到對應階段的 `plan/NN/0X-open-measurements.md`。

## 6. 每階段的安全審查觸發條件

以下任一成立就要產出 `docs/security-review-*.md`：

- 新增或改變授權輸入。
- 新增寫入路徑或新的儲存面。
- 新增在 node 上執行程序的能力。
- 新增憑證或機密流。

**四次安全審查，都不可略過**：

| 階段 | 觸發原因 | 審查重點 |
|---|---|---|
| V2.1 | Session token **＋ `.cliora/` 的新寫入面** | 發行、scope、失效、檔案落地與保留期；投影 verb 的可寫集合與既有 verb 互斥；token 檔的敏感檔分類 |
| V2.2 | 無人值守執行 ＋ run log ＋ **卡片產物** ＋ **隔離目錄與 git 取得**（2026-08-10 裁決提前） | 認領授權（**本期是 enrollment，不是綁定**）、租約、log 界線（D27）、cancel 可靠性、**產物提供路徑的 stored XSS**（D29 §4）、配額、**run 目錄與 allowed root 互不可達**、**Agent 的 git 自由（含 push）是刻意給的，收斂點是可觀測性**（`04` AR-04b）、**「程式碼落在哪台機器」這個變化**（不是存取控制退步，見 `04` 風險表） |
| **V2.3** | **機密流 ＋ 新儲存面 ＋ git 寫入** | 加密與金鑰、不可讀回、去識別、git 五條約束（push 半邊）。**授權邊界那一節改寫**（2026-08-12）：原本審的是「`project_agents` 綁定＝機密授權邊界」這個檢查點，**現在沒有那個檢查點了**——改為驗 `01` D18 的**代償四條**真的存在（卡片級 `required_secrets`、node 端 `accept_secrets: false`、可撤銷 ＋ 下放稽核、enrollment 畫面的說明文字），並確認**沒有任何 UI 暗示 tag 是授權**。（run 目錄隔離與配額已在 V2.2 審過，此處只審機密如何進入那個目錄） |
| V2.4 | 對外副作用（PR） | 交付模式邊界、無自動合併、供應商憑證 |
| V2.5 | **不必然觸發**（無新憑證、無新儲存面、無新執行能力）；若釐清 run 需要讀敏感文件則補 | — |

**V2.2 與 V2.3 各觸發三條。** 2026-08-10 裁決把隔離目錄與 git 取得提前之後，V2.2 命中「新增在 node 上執行程序的能力」「新增儲存面」「新增憑證流」；V2.3 仍命中「機密流」「新儲存面」「git 寫入」。它的審查文件要分成三節、三組邊界測試各自獨立，不要合寫成一段「Agent 執行環境安全審查」。

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
