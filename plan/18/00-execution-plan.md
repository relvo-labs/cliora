# 00 — 執行總控（V2.2 Agent Runner、自行取得程式碼與卡片產物）

Ticket 前綴 `AR-`。上游規劃：[`research/02/04-phase-v22-agent-runner.md`](../../research/02/04-phase-v22-agent-runner.md)。

> **2026-08-10 裁決改寫了本期的形狀。** Agent 收到任務後**自己把專案拉到 daemon 擁有的
> 隱藏目錄**（像 GitLab Runner），**workspace 綁定從此只服務互動式 Session**，
> **`project_agents` 綁定與 label 比對延後**（現在每個 agent 都可以拉每個 project）。
> 搬動表見 `research/02/04` §0；它對本計畫的影響見本檔 §3 的 D11／D13／D15–D20 與 `04b-…md`。

## 1. 成功定義

**要交付的：** 一個 Developer 在看板上按「派給 Agent」，一張 `ready` 的卡片變成一張工單；
一台 enroll 過的 node 上的 `agentd --runner` 自己把它領走、**把該 Project 登記的 repository
clone 到一個 daemon 擁有的隔離目錄**、在那裡非互動地跑 `claude` 或 `codex`、把過程的 log
送回來、在卡片上留言與提問、把測試報告與 `git diff` 附成卡片產物；
跑到一半 kill 掉 runner 程序，租約逾時之後這張卡被重排並完成；
而**使用者的 workspace 一個位元組都沒被碰過**——`git status --porcelain` 全程為空。

**其餘一律不做。** git push、分支命名空間、機密、PR、驗證報告、需求釐清——
那是 V2.3 之後的事（§2）。

**不得弄壞的十一件事：**

1. **兩個旗標都關閉時，系統與 V2.1 逐位元組一致。** `CLIORA_AGENT_RUNS_ENABLED=false` 時
   本期新增端點全數 404、`runner.register` 一律拒絕、導覽沒有 Agents 項；
   `CLIORA_PROJECTS_ENABLED=false` 時再加上 V2.1／V2.0 的既有 404 集合。
2. **互動式 Session 的行為一個位元組都不變。** Agent Run 不進 `terminal_sessions`、
   不走 `terminal_relay`／`terminal_queue`、不佔 writer 名額、不建 tmux。
3. 🆕 **平台的任何路徑都不碰使用者的 workspace，而既有檔案 API 也碰不到 run 目錄。**
   run 目錄不在任何 allowed root 內；`daemon/internal/{files,workspace}/` 整包零 diff；
   **daemon 在 run root 落在 allowed root 內時拒絕以 runner 模式啟動並指名。**
   ⚠️ **注意這一條的措辭比原本弱**：原本寫「run 程序讀寫不到任何 allowed root」，
   而**那件事平台沒有實作**——run 的子程序與 agentd 同一個 OS 使用者，
   而 allowed roots 必須被它讀寫（否則 Session 開不起來）。
   那一段由**部署姿態**承擔，並由平台**回報**而不是強制（`04b-…md` §3.4／§2.5）。
4. 🆕 **`authorize_workspace()` 與 `workspace.Root` 一行都不動。** 本期不再有第二個呼叫者
   ——run 不使用 workspace 綁定，所以紅線 2 的適用範圍變得更乾淨而不是更複雜。
5. **SEC-002 的 argv 條款逐字不變。** argv 仍完全由 daemon 從封閉表組出；
   任務情境**從 stdin** 進去。`daemon/internal/runtime/{runtime,launch}.go` **零 diff**（D7）。
6. 🆕 **`daemon/internal/files/` 完全不動。** run 目錄是 daemon 自己的，情境包直接寫，
   **不經過 `VerbProject`、不經過任何 protocol 往返**。V2.1 的投影面在本期是禁區而不是重用對象。
7. **既有 20 個 RBAC 動作的角色歸屬不變。** 只新增四個（合計 24）。
8. **run 憑證永遠拿不到 `task.approve`、`task.create`、`project.manage`、`file.*`、`terminal.*`、
   `run.dispatch`、`run.cancel`。** 而且不是靠一行 if——它根本不走使用者的認證路徑。
9. **卡片產物不可變。** 沒有任何 API 可以修改一件已附加的產物；
   刪除只有 `project.manage`，需理由 ＋ audit。
10. **run log 不構成「平台現在會存終端內容」的先例。** 互動式 Session 的承諾未變。
11. **平台不做自動指派，也不做任何 git 寫入。** 認領是 runner 主動的；
    **平台自己一次 `git push` 都不發生**。
    （Agent 在沙箱裡用機器既有憑證自己 push 是**允許的**——2026-08-10 第二次裁決，
    見 D19。那不是平台的行為，而平台不攔它。）

成功的判準是以下十四項，每一項都要有可貼上的輸出（`08-…md` §5）：

1. 未指定 agent 的卡：**任一** runner 都領得到（本期沒有綁定，「任一」就是字面意思）；
   指定的卡：**只有那一個**領得到。
2. 指定一個**已停用**或 **runtime 不符**的 runner → dispatch **409 不入佇列**，訊息指名是哪一條。
3. 指定的 runner **離線** → `202` 入佇列，卡片顯示「等待指定的 Agent：<名稱>（目前離線）」；
   **文案與「目前沒有符合資格的 Agent」逐字不同**，且兩者各有一條測試。
4. 兩個 runner 在同一個 event loop tick 內對同一張卡發 `runner.poll` → **只有一個拿到 offer**，
   `task_runs` 只有一列 `runner_id` 非空。
5. 🆕 **`source: repo` 的卡被領走後**，run 目錄裡出現 `repo/`、在正確的 `default_branch` 上，
   `commit_sha` 回報到平台並顯示在 Run 詳情頁；**第二次 run 走 mirror，不重新完整 clone**。
6. 🆕 **`filesystem.list` 對 run 目錄回 `WORKSPACE_OUTSIDE_ALLOWED_ROOT`**；
   **把 run root 設在 allowed root 裡面時 daemon 拒絕啟動並指名**；
   🆕 **`allowed_roots` 非空的 node 在 Agents 頁上顯示為「⚠ 混合用途」**
   （`dedicated: false` 的回報，`04b-…md` §3.5）。
7. 🆕 **使用者的 workspace 全程未被碰**：run 進行中與結束後，
   對該 Project 綁定的每一個 workspace 做 `git status --porcelain` **完全為空**。
8. 🆕 **run 摘要記錄得出這個 run 有沒有動到遠端**：`git remote -v`（userinfo 已遮）
   與 `git log --oneline --branches --not --remotes` 的行數都出現在 Run 詳情頁。
   （原本這一條是「`origin` 被移除、`push` 直接失敗」。第二次裁決撤回了那個作法：
   **可觀測性取代阻止**，見 D19。）
9. 🆕 **缺 git 憑證時 clone 秒級失敗**（`run.failed` ＋ 明確 error code），
   不掛在密碼提示上直到牆鐘兜底（6 小時）。**idle timer 救不了這一種**——
   clone 發生在 `run.accept` 之前，還沒有事件流可以量（`04b-…md` §5.4 第二點）。
10. 執行中 kill 掉 runner 程序 → 租約逾時標 `lost`、`attempt+1`、重排、被領走並完成；
    **被指定的卡重排時仍只給原本那個 runner**。重排三次都失敗 → 卡片進 `blocked`，原因寫明。
11. `run.cancel` → SIGINT → 等待 → SIGKILL 整個 process group；**run 的 pgid 下無殘留程序**。
12. Run log 超過 `CLIORA_RUN_LOG_MAX_BYTES` → **從中間截斷**、明示截斷位元組數。
13. Agent `cliora task ask` → run 進 `waiting_for_input`、卡片顯示「等待你的回覆」；
    回覆後拉得到；24h 未回覆自動退 `blocked`。
14. `cliora task attach report.md --message "初步發現"` → 訊息與產物同時出現在卡片；
    🆕 **`delivery: none` 的卡在工作目錄留下變更 → `git diff` 被附成一件產物**；
    **run 目錄被清掉之後兩者仍可下載**；
    上傳一個 `.html` → 下載帶 `Content-Disposition: attachment` ＋ `nosniff`，
    **應用 origin 內沒有任何路徑會渲染它**。

外加一條與 V2.1 相同的回歸判準：**兩個旗標關閉時完整 V1＋V2.0＋V2.1 全綠、
既有 contract fixtures 一個位元組未變、`agentd` 0.9.0 在旗標關閉的部署上行為與 0.8.0 相同。**

## 2. 範圍

### 納入

- `AR-00` **基線擷取 ＋ 五項量測**（閘門，動任何程式碼之前）：
  M-AR-1（**已量**）、M-AR-2、**M-AR-9**（事件間隔的尾巴 → `idle_timeout_seconds`）、
  M11／M12（後兩者原本是 V2.3 開工前的量測，隨 clone 一起提前）。
  **基線點是 `3c8760d`，六份基線必須取自同一個 commit**（`01-…md` §1）。
- `AR-01` **ADR 0029**（Runner 模型與 run 生命週期）＋ `research/prd.md` §8.13 ＋ skill 補述 ＋
  traceability 註冊（FR-AGENT-001、003–013）。
- `AR-02` **ADR 0030**（run 的兩種輸出：log 與卡片產物）。
- `AR-02b` 🆕 **ADR 0031**（隔離工作目錄與 git 取得）——原屬 V2.3，本期發佈取得半邊。
- `AR-03` 資料層：migration `0029`（`agent_runners`、`project_repositories`、`task_runs`、
  `run_logs`、`task_messages`、`task_artifacts`、`task_artifact_blobs`、`run_tokens`）、
  `0030`（seed `agent.*`／`run.*`）、`0031`（`nodes.agent_runner` 能力旗標）。
  **`project_agents` 不在本期**（延後到 V2.3，與機密同一支 migration）。
- `AR-04` RBAC ＋ Agents／Repositories／Dispatch API（**同一個 PR**）。
- `AR-05` 佇列與租約：四條件資格查詢、claim-then-offer、租約 sweep、重排、`waiting_for_input`。
- `AR-06` contract **v1.11.0**：`runner.*` 三則、`run.*` 八則（`spec` **含 `source`**）、fixtures。
- `AR-07` `agentd` **0.9.0** 的執行面：runner 模式、非互動執行、log 分塊、取消三段、容量控管。
- `AR-07b` 🆕 `agentd` **0.9.0** 的目錄與 git 面：`StateDirectory`、run 目錄、mirror ＋ worktree、
  配額、清理迴圈、隔離自檢（**觸發安全審查的第五節**）。
- `AR-08` `run_tokens` ＋ `cliora` CLI 0.2.0 的四個新子命令（**安全審查第二節**）。
- `AR-09` 卡片產物：上傳端點、PostgreSQL blob 儲存、三層配額、安全提供（**安全審查第四節**）。
- `AR-10` 前端：Agents 頁、Project Settings 的 Repository 區、派給 Agent、看板 run 徽章。
- `AR-11` 前端：Run 詳情頁、卡片訊息串、產物區。
- `AR-12` 驗證與出口：測試、雙旗標關閉回歸、六個 gate、`docs/security-review-v22.md`、
  release note、**合併提案並停下來**。

### 不納入

- **平台的 git push 路徑、分支命名空間、五條 git 硬約束、bot identity。** V2.3。
  **本期平台一次 push 都不做**；Agent 自己用機器憑證 push 不在此列，那是允許的（D19）。
- **機密與環境變數。** V2.3。clone 用 node 上**既有的** git 認證，平台不管理任何憑證（D18）。
  宣告了 `required_secrets` 的卡在本期 dispatch 時直接 409。
- **`project_agents` 綁定、label 比對。** V2.3／後續（裁決）。
  `agent_runners.labels` 與 `tasks.required_labels` 本期**顯示但不比對**。
- **PR／MR、`delivery` 的行為（除了 `none`／`artifact`）、Done Gate 的驗證項強制、Evidence。** V2.4。
- **執行計畫與驗證報告。** V2.4（注意 `research/02/10` §2.3 原本標題誤寫為「V2.2」，
  已於 2026-08-10 更正）。
- **把 run 升級成互動 Session、或反過來。** D26。
- **自動指派、排程最佳化、負載平衡。** `research/02/00` §9。
- **`fallback_after_minutes`。** D17b §3 明寫 V2.2 不實作。
- **物件儲存（S3）。** 先進 PostgreSQL，M10／M16 量了再說。
- **MCP。** 條件性，V2.4。

## 3. 固定基線決策

| # | 決策 | 選擇 | 理由 |
|---|---|---|---|
| D0 | **本期在 V2 的哪一格** | 四個半邊：佇列半（零新執行面）＋節點執行半（新執行能力）＋**節點目錄半（新的檔案系統面 ＋ git 出口）**＋產物半（新儲存面 ＋ 不受信任內容出口）。共用一個旗標 `CLIORA_AGENT_RUNS_ENABLED` | 四者的失敗長相不同：佇列半壞了是卡片不動、執行半壞了是機器上多了程序、**目錄半壞了是磁碟被吃掉或碰到了使用者的檔案**、產物半壞了是 stored XSS。共用一個旗標是因為沒有一個能單獨有用 |
| D1 ⚠️ | **claim-then-offer：原子認領發生在 `runner.poll` 當下** | `runner.poll` → 資格查詢 ＋ `UPDATE … WHERE id=… AND runner_id IS NULL` → 命中才送 `run.offer`（＝「這張卡已經是你的了，租約已開始」）。`run.accept` 是開工回報，`run.decline` 是**釋放** | 兩行程式碼決定的：① `registry.request()` 等的 future 由 `node_gateway` 的**同一個接收迴圈**呼叫 `resolve_response()` 解開（`registry.py:276`／`ws/nodes.py:276`），在迴圈裡 await 必逾時；② daemon 沒有為自己發出的請求做關聯表（`connection.go:494` 只有一條 `switch`）。**被否決**：三方握手（多一個型別，窗口只是往後挪）；WS 迴圈裡 `asyncio.create_task`（那條連線只有**一個** `AsyncSession`，不可並行使用）；另開 runner 專用 WSS（違反 D16） |
| D2 ⚠️ | **所有 `run.*` 訊息都是非關聯的單向訊框** | node→central 走 `node_gateway` 的 `elif` 鏈（與 `tunnel.status` 同形狀）；central→node 走 `registry.send_text_frame()`（與 `terminal.resize` 同形狀） | `node_gateway` 的最後一個分支是 `resolve_response()`，沒被接住的訊息**丟棄並記一筆 warning**。漏一個型別的症狀是「訊息不見了但沒有錯誤」，那是本期最難查的 bug。`GATE-AR-DISPATCH-COVERAGE` 用 contract 的型別清單反查這條鏈 |
| D3 ⚠️ | **`run.log_chunk` 留在 64 KiB 訊框級別，Central 端記憶體聚合後才寫 DB** | `data` 上限 **32 KiB**；不加進 `LARGE_FRAME_TYPES`。每個 run 一個緩衝，**攢滿 64 KiB 或 2 秒**寫一列 | 那條 socket **同時載互動式終端的二進位輸出**（`node_gateway` 的 `raw_bytes` 分支在同一個 `while` 迴圈）。放進 8 MiB 級別、或每 chunk 一次 DB 往返，都是拿 V1 的終端延遲換 Agent 的除錯輸出。代價寫進 ADR：Central 崩潰掉最後 ≤64 KiB 的 log。**2026-08-11 裁決：接受。** 它成立的理由是本 ADR 的核心區分——**log 是診斷（重跑一次就有了）；產物與卡片訊息是交付物，而它們刻意不走這條路**（產物走 HTTP／D4，訊息走 API 並逐筆 commit） |
| D4 ⚠️ | **卡片產物走 HTTP，`run.artifact` 不進 contract** | `POST /api/tasks/{id}/artifacts`，`multipart/form-data`，帶 `run_tokens` 的 bearer。上傳者是 `cliora task attach` | 三條各自足以否決 WSS：① 單件 10 MB **大於** 8 MiB 的 `MAX_FILE_PAYLOAD`（`codec.py:21`）；② 那條線載著互動式終端；③ `cliora` CLI **已經有**對 Central 的 HTTP client（`cli.go:191`），daemon 沒有。上游把這條寫成「二選一」，這是那個決定 |
| D5 ⚠️ | **產物 blob 進 PostgreSQL，metadata 與 blob 分兩張表** | `task_artifacts`（會被列出）＋ `task_artifact_blobs`（`bytea`，只在下載時讀）。`storage_ref` 本期恆為 `db:<blob_id>` | `docs/deployment-railway.md:27` 明寫容器檔案系統 **ephemeral**，`CLIORA_ARTIFACTS_DIR` 是**建置時烘進映像**的發行物目錄（`deploy/railway/env.md:29`），不是可寫的持久卷。分表讓「列十件產物把 100 MB 拖進記憶體」這個錯誤**不可能發生** |
| D6 ⚠️ | **run 的 CLI 憑證是新表 `run_tokens`** | 前綴 `cliora_rt_`，同一把 `CLIORA_TOKEN_PEPPER`、同一個 `keyed_hash`、只存 HMAC。`AgentPrincipal` 加 `kind`（`session`／`run`）與 `run_id`／`task_id` | `session_tokens.session_id` 是 `NOT NULL` FK → `terminal_sessions` 且 CASCADE（`0024_session_tokens.py`），與「run 不得有 session 列」不可能同時成立。**被否決**：`session_id` 改 nullable（一張表兩種主體，`revoke_for_session` 那句「一定會有第五扇門」會變成謊話）；為 run 建一列假 session（污染 Sessions 畫面與每一條 `authz.may_*`） |
| D7 ⚠️ | **非互動 argv 放在新檔，prompt 走 stdin** | 新檔 `daemon/internal/runtime/run.go`：封閉表 `runArgs` ＋ 自由函式 `BuildRunCommand(rt, opts)`，用既有的 `rt.Binary()`／`rt.LaunchArgs()`。**`runtime.go` 與 `launch.go` 零 diff。** 情境從 **stdin** 進去 | `launch.go:23` 的註解已經替本期寫好判準：「加一個呼叫端提供的字串進這張表，正是 SEC-002 存在要防的那個變更」。放 stdin 之後 argv 仍然只有「設定檔的 binary ＋ daemon 自己的兩張封閉表」。新檔而不是改舊檔，是為了讓 gate 能用「這兩個檔零 diff」當斷言 |
| D8 | **非互動旗標已量出來，探測降級為迴歸守衛** | `runArgs = {claude: ["-p","--output-format","stream-json"], codex: ["exec","--json"]}`（M-AR-1 的實測，`10-…md`）。**流式旗標與非互動旗標一起探**——存活判定靠它（D21）。`RunCapable(rt)` 仍然探 `--help`，但它的角色從**發現**變成**迴歸守衛**：第三方 CLI 改了介面時，node 回報 `runtimes: []` 而不是每個 run 都跑到硬逾時。**快取生命週期是「一次連線」不是「一個行程」**（`04-…md` §5.3）| 2026-08-10 在裝了兩支 CLI 的機器上實測：`claude -p` 明寫 "Print response and exit (useful for pipes)"；`codex exec` 明寫 "If not provided as an argument (or if `-` is used), instructions are read from stdin"。**兩支都從 stdin 收 prompt，所以 D7 成立。** 探測留著的理由是那兩個值**是第三方介面不是契約**——CLI 由使用者自己裝，與 `node_update` 的發布沒有版本綁定；沒有探測的失敗長相是「程序開了互動式 session 然後等到牆鐘兜底」，症狀看起來像「Agent 很慢」而不是「設定壞了」。形狀沿用 ADR 0023 D3：回報機器實際的姿態，不要回報你希望的姿態。**但快取要比 `bypassProbe` 窄一格**：後者是行程生命週期，而重連並不重探（`runtime.go:86` 的註解在這一點上略微樂觀）；`RunCapable` 過期的後果是「runner 一直領不到卡，而看板上的原因是假的」，所以它每次重連重探（`04-…md` §5.3）|
| D9 | **一個 node 一列 runner** | `agent_runners` 對 `node_id` 唯一；`runtimes` 是集合；`max_concurrent`／`max_waiting` 是 node 級的 | D16 推論出「runner 的線上狀態就是 node 的線上狀態」。多列共用一條 WSS 就要回答「哪一列在線」，而答案永遠等於 node ——那個欄位會變成假指示燈。並行度也一樣：多列共用一台機器的 CPU 與**磁碟**，加總沒有意義 |
| D10 | **租約回收是週期性 sweep，不是 `shell_reaper` 的 per-item timer** | `RunReaper`：`lifespan` 啟動、間隔 `lease_timeout/3`、走 `ix_task_runs_lease`；啟動時先 reconcile | `shell_reaper.py` 寫「This is not a scheduler」是對的——一個 shell 的閒置只有一個觸發點。租約不同：續租每 30 秒重設一次 timer；`waiting_for_input` 的 24 h 撐不過 Central 重啟；而 `lease_expires_at` **已經在列上**。啟動時 reconcile 沿用 `main.py:73` |
| D11 | **本期做不到的宣告在 dispatch 當下拒絕；`source` 現在做得到了** | 擋下：`required_secrets` 非空、`delivery ∈ {branch, pull_request, existing_pr}`。**放行**：`source ∈ {none, repo, existing_branch}`（裁決把 clone 提前） | 裁決之前這條擋下三類，現在只擋兩類。`source` 從「本期不支援」變成**本期的主路徑**，這是本次裁決在 API 層最直接的表現。錯誤訊息仍寫「V2.3 起生效」而不是「不支援」 |
| D12 | **兩個旗標，且外層旗標先判** | `require_agent_runs_enabled` 掛在 `require_projects_enabled` **之後** | 順序反了，旗標關閉的部署會從 404（正確）變成 403（洩漏了這條路由存在） |
| D13 | **dispatch 的檢查順序寫死** | ① 卡片本身能不能派 → ② 本期做不到的宣告（D11）→ ③ 該 Project 有沒有登記 repository（`source ≠ none` 時）→ ④ 指定的 runner：啟用 → runtime 相符 → **⑤ 沒有綁定這一層**（延後到 V2.3） | 順序寫死的用意是錯誤訊息的可讀性。**裁決移除了原本的第一順位（綁定）**，所以本期最先擋下的授權類問題變成「這個專案還沒有登記 repository」——一個要在 Project Settings 修的東西，而 dispatch 的訊息要直接指向那裡 |
| D14 ⚠️ | **產物一律下載，白名單才預覽，HTML 永不渲染** | `GET /api/artifacts/{id}` 恆帶 `attachment` ＋ `nosniff` ＋ `CSP: default-src 'none'; sandbox`；`content_type` **由伺服器判定**，不採信上傳者宣告；預覽只給圖片／純文字／markdown，且 markdown 回 `text/plain` | 本期最容易做錯的一項。Cliora 是單一 origin 部署（ADR 0020），「在新分頁開啟」與「內嵌渲染」是同一件事。**被否決**：`sandbox` iframe（做錯一個 flag 就全開，而 D31 已給了 V2.5 用 Pinggy 的**另一個 origin** 的答案）；獨立產物 origin（第二個部署單元，違反 ADR 0020） |
| D15 ⚠️ | **本期觸發安全審查，五節** | `docs/security-review-v22.md`：① 認領授權與「指定」（**本期的邊界是 enrollment**，以及「程式碼落在哪台機器」這個變化）；② run 憑證；③ log 邊界與去識別掛勾；④ 產物的接收與提供；🆕 ⑤ **run 目錄隔離、配額與 git 取得** | 裁決把隔離目錄與 clone 提前之後，本期命中 `research/02/10` §6 的**三個**觸發條件（新執行能力、新儲存面、新憑證流）。第五節是新加的，而它要回答的問題最具體：**run 目錄與使用者的 allowed root 有沒有任何一條互通的路徑？** |
| D16 | **這一期不碰的東西** | `backend/app/services/{terminal_relay,terminal_queue,tunnels,integrations,node_update,files,favorites}.py`、`backend/app/api/ws/terminal.py`、`daemon/internal/{terminal,tmux,tunnel,update,workspace,systeminfo,session}`、**`daemon/internal/files/` 整包**、`daemon/internal/runtime/{runtime,launch}.go`、`frontend/src/{terminal,monaco,protocol}`、`deploy/`（**除了 systemd unit 的 `StateDirectory`**，見 D17） | 判準寫死：diff 出現在上述任一處就是走錯路了。**與 `TK` 的三個差別**：① `daemon/internal/files/` 從「部分允許」變成**整包禁區**——run 目錄是 daemon 自己的，不經過 `VerbProject`（成功定義第 6 條）；② `daemon/internal/runtime/` 從整包禁區變成「兩個檔零 diff、可新增檔案」；③ `daemon/internal/install/` 要動一行（`StateDirectory`） |
| D17 🆕 | **run root 是 systemd 的 `StateDirectory`，路徑含 `.cliora`** | `runner.work_dir`，預設 `<StateDirectory>/.cliora/runs/<run_id>/`，即 `/var/lib/agentd/.cliora/runs/…`。systemd unit **新增 `StateDirectory=agentd`** | 現況的 unit 只有 `RuntimeDirectory=agentd`（→ `/run/agentd`，**tmpfs**，`install/systemd.go:39` 的註解說它放 tmux 設定）。失敗的 run 目錄要留 14 天，tmpfs 撐不過一次重啟。`StateDirectory` 是 systemd 原生的、會自動以服務使用者的身分建立並設好權限，不必自己 `mkdir` ＋ `chown`。**`.cliora` 這一段保留**（裁決的字面要求，也有實用理由）：營運者若把 `work_dir` 設在別處，這個名字讓它是隱藏的、而且與既有 `.cliora/.gitignore` 的慣例一致——萬一它落在一個 repo 裡，git 本來就會忽略它。**啟動自檢**：`work_dir` 落在任何 `workspace.allowed_roots` 之內就**拒絕啟動並指名**，不是印警告 |
| D18 ⚠️ 🆕 | **git 走 `git` 執行檔，而非 Go library；本期用 node 上既有的認證** | `daemon/go.mod` 不新增依賴；新檔 `daemon/internal/gitfetch/`，argv 由一張**封閉表**組出（與 `runArgs` 同一條紀律）。repo URL 來自 `project_repositories`（Admin 建立的**平台設定**），不是請求 payload | 引入 go-git 會把 git 的行為換成第二套實作，而 mirror／worktree 這些正是 go-git 支援最弱的地方。SEC-002 的判準在這裡仍然成立：**URL 是平台設定不是呼叫端字串**，與 `runtime.binary` 來自設定檔是同一種來源。**本期用既有認證的五條後果**（`04b-…md` §5.4）要寫進 ADR 0031，其中第三條是一個**刻意給的自由**：**Agent 可以用機器的憑證做 git 能做的任何事，包含 push**——收斂點是 D19 的可觀測性，而不是一道護欄 |
| D19 🆕 | **不擋 Agent push；用可觀測性取代阻止。三個 fail-fast 環境變數只套用在 daemon 自己的 git 呼叫上** | **不做** `git remote remove origin`。`GIT_TERMINAL_PROMPT=0`／`GIT_ASKPASS=/bin/false`／SSH `BatchMode=yes` ＋ known_hosts pinning **只進 daemon 自己 clone／fetch 的環境，不進 Agent 程序的環境**。run 結束時把 `git remote -v`（userinfo 遮掉）與 `git log --branches --not --remotes` 的行數寫進 run 摘要 | **2026-08-10 第二次裁決：不需要擋 Agent push，憑證也不需要唯讀。** 原本的計畫是移除 `origin` 讓「隨手一個 push」失敗；裁決之後那個作法**是有害的**——它會連帶弄壞 fetch／pull 與那個被允許的 push。fail-fast 變數的範圍要收窄，理由同源：它們是為了「daemon 自己的 clone 不要掛在密碼提示上」，套進 Agent 的環境會讓一個需要密碼的 push 失敗，而那正是裁決要允許的。**換上的收斂點是可觀測性**：兩行零成本的資訊讓「這個 run 有沒有動到遠端」在 Run 詳情頁上是事實而不是猜測。**一個必須一起做的回寫**：紅線 4 的第 1、2 條原文寫「Agent 只能推 `cliora/`…寫死在 daemon」，那個主詞在裁決之後不準確——它們約束的是**平台的 push 路徑**（`04b-…md` §5.5） |
| D21 ⚠️ 🆕 | **存活判定靠事件流，不靠牆鐘；三個計時器各答一個問題** | `claude -p --output-format stream-json`／`codex exec --json` 的 JSONL 事件流：每一行事件更新 `last_event_at`。**idle timer**（`runner.idle_timeout_seconds`，建議 300 秒）是存活的主要判定；牆鐘 `spec.timeout_seconds` **放大到 6 小時**變成兜底；`run.lease_renew` 維持無條件，因為它答的是另一個問題 | **2026-08-11 的更正。原本只有一個 1 小時牆鐘硬逾時，而那是錯的**：一次性指令的逾時**不代表它沒在執行**，很可能 Agent 還在處理。更糟的是**租約續租原本無條件**，所以 child 掛死時 Central 完全看不出來——唯一會踩到的就是那個會誤判的牆鐘。三個計時器分別答：`lease` 答「**runner** 活著嗎」（Central 判，`lost` → 重排）、`idle` 答「**child** 在前進嗎」（daemon 判，`RUN_IDLE_TIMEOUT`）、牆鐘答「它會不會永遠不停」（`RUN_TIMEOUT`）。**`lease_renew` 刻意保持無條件**：把它改成「只在 child 有活動時續租」會讓「runner 掛了」與「child 掛了」長得一樣，而它們的收斂路徑不同。**被否決：用互動模式（PTY）取得即時狀態**——方向對（要的是 stdio 雙向即時）但機制錯：兩支 CLI 都有為程式設計的事件流，不需要 PTY；而 PTY 會讓 run 變成 Session（D26／出口條件 16 倒），且 run log 變成一段 ANSI 終端錄影，把 D27 的界線用最難看的方式重新打開。**byte-level 存活比 event-level 弱**——spinner 在重繪只證明 renderer 活著（`04-…md` §3.4） |
| D20 🆕 | **`git diff` 附成產物，這條誠實性規則從 V2.4 提前** | `delivery ∈ {none, artifact}` 且 run 結束時工作目錄有變更 → 把 `git diff` 附成一件產物，並在 run 摘要寫「宣告不交付，但偵測到 N 個檔案變更」 | D21 的誠實性規則原本排在 V2.4，理由是那時才有 `delivery` 行為。裁決之後**它在本期就必要了**：run 真的會拉程式碼、真的會改檔案，而 run 目錄有保留期（成功 3 天）。不附成產物，那份工作會在三天後消失——而使用者不會知道它曾經存在。**第二次裁決（Agent 可自己 push）縮小了它的適用面但不取消它**：推了分支的 Agent 的工作不會消失，沒推的仍然會，而平台分不出這兩種，所以規則不變（`04b-…md` §6） |

## 4. 波次與 ticket

| 波次 | Ticket | 標題 | 依賴 |
|---|---|---|---|
| **0（閘門）** | `AR-00` | 基線擷取（**基線點 `3c8760d`**）＋ **M-AR-1（已量）／M-AR-2／M-AR-9／M11／M12** | — |
| | `AR-01` | ADR 0029、PRD §8.13、skill 補述、traceability（`proposed`） | `AR-00` |
| | `AR-02` | ADR 0030（log 與產物，兩種保留期） | `AR-01` |
| | `AR-02b` | 🆕 ADR 0031（隔離目錄六條規則 ＋ git 取得 ＋ **ambient 憑證的四條後果**） | `AR-00` 的 M11／M12 |
| **1（佇列半・資料）** | `AR-03` | migration `0029`／`0030`／`0031` ＋ 模型 | `AR-01`／`AR-02`／`AR-02b` 核准 |
| **2（佇列半・API）** | `AR-04` | RBAC 四動作 ＋ Agents／Repositories／Dispatch API（同一個 PR） | `AR-03` |
| | `AR-05` | 四條件資格查詢、claim-then-offer、租約 sweep、重排 | `AR-04` |
| **3（節點半）** | `AR-06` | contract v1.11.0（`spec` 含 `source`）＋ fixtures | `AR-05` |
| | `AR-07b` | 🆕 `StateDirectory`、run 目錄、mirror ＋ worktree、配額、清理、**隔離自檢**（**安審第五節**） | `AR-06` |
| | `AR-07` | 非互動執行、log 分塊、取消三段、容量控管 | `AR-07b` |
| | `AR-08` | `run_tokens` ＋ `cliora` CLI 0.2.0（**安審第二節**） | `AR-07` |
| **4（產物半）** | `AR-09` | 產物上傳、blob 儲存、三層配額、安全提供、**diff 附成產物**（**安審第四節**） | `AR-04`／`AR-08` |
| **5（前端）** | `AR-10` | Agents 頁、Repository 設定、派給 Agent、看板徽章 | `AR-04` |
| | `AR-11` | Run 詳情頁、訊息串、產物區 | `AR-05`／`AR-09`／`AR-10` |
| **6（收尾）** | `AR-12` | 測試、雙旗標關閉回歸、六個 gate、安審定稿、release note、**合併提案並停下來** | 全部 |

**`AR-07b` 排在 `AR-07` 之前**，這是裁決帶來的順序變化：先有一個正確隔離、有配額、
會清理的目錄，再往裡面放一個會跑一小時的程序。反過來做，第一次測試就會在一台機器上
留下三十個沒人清的 clone。

**閘門一：`AR-00` 的六份基線完成前不得動任何程式碼**（量測可以晚一點，見下）。 判準需要「本期之前」的 OpenAPI、
contract fixtures 清單、前端路由表、**互動終端延遲基線**。M11／M12 也在這裡——
它們決定 `runner.run_quota_bytes` 與「mirror 還是淺 clone」，而後者是一個**改了就要改
daemon 的目錄配置**的形狀。

**但量測與基線的擋法不同**（2026-08-11 釐清）：**基線擋所有程式碼**（改完就取不到）；
**四項量測只擋波次 3** 的 `AR-07`／`AR-07b`。所以波次 0–2
（閘門票、三份 ADR、資料層、API、佇列）可以在量測還沒做完時就開工（`09-…md` §0）。

**閘門二：`AR-01` 核准前不得動 `backend/`、`frontend/`、`daemon/`、`contracts/`。**
skill 範圍句要補的是**三個** V2.1 沒有的面：無人值守執行、平台儲存 Agent 產生的檔案、
🆕 **平台觸發 git 操作**。

**閘門三：`AR-02b` 要在 `AR-03` 與 `AR-07b` 開工前接受。** 它決定 run root 的位置、
配額語意與清理責任，而那三件事各自都會回頭改 schema 或 systemd unit。

**閘門四：`AR-09` 的安全審查第四節要在該票合併前定稿。**

**波次 3／4 可以整批延後而不擋波次 1／2／5 的大部分。** 佇列半（卡片可以掛上佇列、
可以看到「等待 Agent」）是一個可以獨立交付的成果，只是判準 5–14 未達成、本期不得標為完成。

## 5. 風險

| 風險 | 徵狀 | 處置 |
|---|---|---|
| **poll／offer 的往返在 Central 上是死鎖** | `run.offer` 永遠逾時，log 上只看得到 `REQUEST_TIMEOUT` | 已經先撞掉了（D1）。`GATE-AR-NO-REQUEST-IN-LOOP` 對 `api/ws/nodes.py` 與它呼叫的服務做文字掃描 |
| **紅線 4 的措辭在裁決之後不準確，而它會靜默漂掉** | V2.3 的人讀到一條寫著「Agent 只能推 `cliora/`，寫死在 daemon」的紅線，而那件事在 V2.2 就已經不是真的 | **`AR-01` 要一起改 `research/02/00` §7 紅線 4 的第 1、2 條**：主詞從「Agent」改為「**平台的 push 路徑**」，並明寫 Agent 在沙箱內的 git 操作不在其範圍（`04b-…md` §5.5）。這不是放寬紅線，是把它的對象寫對——D25 一向是「不限制沙箱內能做什麼，限制產出怎麼離開」 |
| **Agent 推出去的東西沒有人知道** | 遠端多了一條分支，而卡片上什麼都沒寫 | 不擋（裁決），但**要看得見**：run 摘要的兩行（`git remote -v` ＋ 未推送 commit 數）＋ M-AR-8 統計實際發生率。**偵測不等於阻止，而本期刻意選了偵測** |
| **run 目錄吃掉整台機器的磁碟** | node 磁碟滿，連互動式 Session 都開不起來 | 兩層配額（單 run／node 總量）＋ 清理迴圈 ＋ **M12 在開工前量** ＋ 判準：配額用盡時**停止 poll 並回報原因**（`04b-…md` §4.1）。既有的 `filesystem.upload` 已經有 `MinFreeBytes` 的概念（`config.go:226`），沿用同一個保留水位 |
| **run root 被設在 allowed root 裡面** | 兩條路徑互通，Agent 的中間產物出現在使用者的檔案瀏覽器裡 | daemon 啟動時**拒絕啟動並指名**（D17）。判準 6 |
| ⚠️ **Agent 在混合用途的 node 上讀了使用者的 workspace** | 一個 Session 用的目錄裡的東西出現在 run log 或產物裡 | **平台沒有技術上的隔離**（`04b-…md` §3.4：同一個 OS 使用者、家目錄刻意不隱藏、無 namespace）。三道：① `allowed_roots: []` 的專用 node 讓它恆真；② **平台回報 `dedicated` 並在 Agents 頁顯示 ⚠**，讓混合用途是一個看得見的選擇而不是一個沒人知道的事實；③ `codex exec -s workspace-write` 在 codex 這條路徑上確實更緊，但那是 runtime 給的不是平台給的。**不做 mount namespace**，理由見 `04b-…md` §3.4 |
| **缺 git 憑證時 clone 掛一小時** | 使用者看到「跑了一小時然後失敗」 | D19 的三個環境變數；判準 9 斷言**秒級**失敗 |
| **每次 run 都完整 clone 一個大 repo** | run 的啟動延遲不可接受 | bare mirror ＋ `git worktree`；**M11 在開工前量**，它決定 mirror 與淺 clone 的取捨 |
| **run log 把互動終端的延遲賠進去** | 「跑 Agent 的時候終端變頓」 | D3 的兩條 ＋ 一條 e2e：run 全速輸出時同 node 的終端 echo p95 不比基線差 20% 以上。**在 `AR-07` 就量**，不留到 `AR-12` |
| **產物成為 stored XSS 管道** | 一個 `.html` 產物在應用 origin 裡被渲染 | D14 的四條 ＋ 判準 14 的**兩個機器斷言**（OpenAPI 掃描、前端路由表 diff）。安審第四節 |
| **`run.cancel` 之後有殘留程序** | node 上累積孤兒程序，容量判斷是錯的 | 三段終止對整個 **process group**（`Setpgid`），沿用 `runtime.go:145` 的 `WaitDelay` 慣例。判準 11 用 pgid 掃描 |
| **`run_logs` 撐爆資料庫** | `pg_dump` 一天比一天大 | 單 run 上限 ＋ 保留期 ＋ **M10 從第一天就量**。到量測說話之前不做物件儲存 |
| **`waiting_for_input` 佔容量** | `max_concurrent` 被三個在等回覆的 run 用光 | 24h 逾時 ＋ **`waiting_for_input` 不佔 `max_concurrent`**（另設 `max_waiting`） |
| **`claude`／`codex` 的非互動介面改變** | run 卡在一個看不見的提示上 | D8 的探測（迴歸守衛）**且流式旗標一起探**——沒有事件流就宣告 not capable，不退回「純文字 ＋ 牆鐘」那個會誤判的模式 ＋ stdin 餵完立即關閉。**收掉它的是 idle timer（5 分鐘）而不是牆鐘（6 小時）** |
| ⚠️ **把「逾時」當成「死了」而誤殺一個正在工作的 Agent** | 一個跑了 40 分鐘、還在跑測試的 run 被砍掉並重排，然後第二次也被砍 | **D21 的整格都在處理這件事。** 判存活的是事件流不是牆鐘；牆鐘放大到 6 小時當兜底。M-AR-9 量真實的事件間隔分布來校準 `idle_timeout_seconds`——**在量到之前不要把它調小** |
| **無人值守的 Agent 燒掉大量 token** | 帳單 | **2026-08-11 裁決：本期不做上限，只量**（M-AR-10）。`claude --max-budget-usd`（只在 `--print` 下有效）是一個現成的旋鈕，**而 codex 沒有對應的**——接一半會讓人以為兩邊都有保護，而那比沒有保護更危險。V2.3 做成**卡片層的預算宣告 ＋ 兩支各自的落地**。⚠️ **這是本期唯一一個「知道有風險而刻意不處置」的項目**，所以它要出現在 release note 的已知取捨裡，不能只躺在量測清單裡 |
| **一個專案的原始碼會被 clone 到任何一台有 runner 的 node 上** | 某個專案的程式碼出現在一台沒有人決定要放它的機器上 | **這不是一個存取控制的退步**：`api/http/projects.py:109` 的 docstring 已經記載「Every holder of `project.view` sees every project… two teams sharing one Cliora see each other's project names — a real disclosure, accepted deliberately」（ADR 0027 Consequences）。系統沒有 `project_members`，人本來就看得到所有專案，也本來就能在任何 node 的 allowed root 上開 Session 讀那裡的程式碼。**真正變的是「程式碼落在哪台機器上」**：以前 `project_workspaces` 是 Admin 刻意建立的「這個專案的程式碼住在這幾台機器」紀錄，現在 runner 繞過那個紀錄。**處置是寫下來而不是加機制**：ADR 0029 的 Consequences 記一段（沿用 ADR 0027 記錄既有揭露的同一種做法），Agents 頁明說授權邊界是 enrollment。V2.3 的 `project_agents` 會把它收回去 |
| **一張卡的 blast radius 是「它落在哪台機器」** | Agent 在 node N 上跑 A 專案的卡，而 N 有 B 專案 repo 的寫入憑證 | 這是兩次裁決的組合（任何 node 可領任何卡 ＋ 憑證不必唯讀）。**它是部署姿態問題不是平台問題**：ADR 0023 已經宣告 node 是可拋棄的隔離 VM，而 enrollment 是 Admin 才有的動作。要寫進安審第一節的是**接受這個姿態的前提**：runner node 應該是專用的，不與需要不同信任等級的東西共用 |
| **Agent 根本不用 `cliora task say`／`ask`** | 卡片上只有系統事件 | 與 M2 同一條理由：這是內化路線的核心假設，不是 bug。情境包第一段就是三行「怎麼提問、怎麼回報、怎麼附檔」 |
