# Cliora V2.2 — Agent Runner、自行取得程式碼與卡片產物

> **狀態：計畫已依 2026-08-10 裁決改寫，尚未開工。**
> 前置條件是 V2.1（[`plan/17/`](../17/README.md)）的十一條出口條件全綠——**本機已全綠**，
> 但出口條件 9（Traqora 正式 repo 實跑）與**合併提案**仍待人工完成（`plan/17/09` §4）。
> 本目錄不改變那條規則：**合併一律由人決定**，出口條件全綠只是取得提案資格。

本目錄是 [`research/02/`](../../research/02/README.md) 規劃的**第三個階段**的執行計畫，
ticket 統一使用 `AR-` 前綴（**A**gent **R**unner）。

規劃層（[`research/02/04-phase-v22-agent-runner.md`](../../research/02/04-phase-v22-agent-runner.md)）
回答「V2.2 要做什麼、為什麼」；本目錄回答「在**這個 repo 的現況**上怎麼做得出來、
做完怎麼證明」。

## 裁決紀錄

本目錄的形狀被兩天的裁決改過。**這張表是唯一的索引**——各處的 inline 註記都指回這裡。

### 2026-08-10 ① — Agent 自己拉專案

> 1. **Agent 收到任務後自己把專案拉到本地**，像 GitLab Runner 那樣。
> 2. 拉下來的東西放在**一個隱藏資料夾**（`.cliora/`）裡。
> 3. **Workspace 綁定從此只服務互動式 Session**（既有的 CLI 與 Terminal 功能）；
>    V2.2 新增的 runner 功能**鎖定在看板任務處理**。
> 4. **`project_agents` 綁定與 label 比對本期都不做**：
>    現在每個 agent 都可以拉每個 project。label match 是後續功能。

把 V2.3 的兩塊（D19 隔離目錄、D20 的取得半邊）提前到 V2.2，把 V2.2 的一塊（D18 綁定）
延後到 V2.3，並**移除**原本 V2.2 最大的已知缺口（「無人值守執行在使用者的 workspace 上」）。
完整搬動表見 `research/02/04` §0。

### 2026-08-10 ② — 不擋 Agent push，憑證不必唯讀

**這是一個取捨而不是缺口。** Agent 在沙箱裡可以用機器既有的憑證做 git 能做的任何事，
包含 push——刻意給的。平台提供的是**可觀測性**（run 摘要記錄 `git remote -v` 與
未推送 commit 數）而不是阻止（`04b-…md` §5.4）。
連帶：**紅線 4 第 1、2 條的措辭要改**（它們約束的是平台的 push 路徑，不是 Agent）。

### 2026-08-11 — 六項

| # | 裁決 | 落在哪 |
|---|---|---|
| 1 | **存活判定靠事件流，不靠牆鐘** — 一次性指令的逾時不代表它沒在執行 | `00-…md` **D21**、`04-…md` §3.4 |
| 2 | **`POST messages` / `POST artifacts` 要 `task.update`，不是 `project.view`** — 後者是一個 Viewer 寫入路徑 | `06-…md` §1／§2 |
| 3 | **log 記憶體聚合會掉最後 ≤64 KiB：接受** — log 可重跑；產物與訊息刻意不走這條路 | `01-…md` §4 Part A（進 ADR 0030 Consequences） |
| 4 | **紅線 4 第 1、2 條的措辭修訂：核准** — 改紅線是治理動作，有獨立核准 | `research/02/00` §7 |
| 5 | **本期不做 token 成本上限，只量**（M-AR-10） — `--max-budget-usd` 只有 claude 有，接一半比不接更危險 | `00-…md` §5、`08-…md` §8 |
| 6 | **`AR-00` 的基線點是 `3c8760d`**，**六份**基線必須取自同一個 commit（含 `COMMIT` 檔本身） | `01-…md` §1 |

另加一項 **V2.3 的**（不擋本期）：`runner.git.isolate_ambient_credentials`
**預設「取代」、可關成「疊加」**（`research/02/05` SC-02 第二點）。

## 這一期真正的形狀

> 讓任務卡從「人在看板上推」變成「Agent 自己領走、把專案拉到它自己的隔離目錄、
> 執行、把成果附回卡片」。工單掛得出去、被領得到、不會雙重領取、
> **拉得下來而且拉在一個不會弄壞任何人東西的地方**、runner 死掉能重排、執行過程看得見。

它由**四個風險等級完全不同的半邊**組成：

```text
           佇列半                節點執行半            節點目錄半             產物半
           (AR-03..05,10)       (AR-06..08)          (AR-07b)             (AR-09,11)
 daemon    一行都不動            0.9.0：非互動執行      0.9.0：StateDirectory  一行都不動
                                log 分塊、取消三段     run 目錄、clone、配額
 contract  v1.10.0 不變          v1.11.0：runner/run   —                    不新增訊息（HTTP）
 新增的     七張表、四個動作      非互動執行面           新的檔案系統面 ＋      新的 blob 儲存面
           十七條 API                                 git 出口              ＋ 下載路徑
 觸發安審   是（認領授權）        是（新執行能力）        **是**（新儲存面）     **是**（stored XSS）
 壞了會怎樣  卡片不動             機器上多了程序          **磁碟被吃掉**         **stored XSS**
```

本期命中 `research/02/10` §6 的**三個**安全審查觸發條件，
所以 `docs/security-review-v22.md` 是**五節**而不是三節，且**不可略過**。

> **想先看「東西實際上長在哪裡」的話，讀
> [`04b-run-directory-and-git.md`](./04b-run-directory-and-git.md) §2。**
> 它畫出一台 node 上的**兩棵樹**（`/var/lib/agentd/.cliora/runs/…` 與使用者的
> allowed root）、具體執行的那一行、以及 run 與互動式 Session 的三種「同時」。
> 那一節是本目錄唯一一個「先看具體、再看理由」的地方。

## 這一期最容易做錯的十一件事

每一條都對應本目錄的一個決策，而且**每一條都是從這個 repo 的既有程式碼裡讀出來的**。

1. **把 `runner.poll → run.offer` 寫成一次關聯式請求。**
   Central 的 `registry.request()` 等的 future 是由 `node_gateway` 的**同一個接收迴圈**
   呼叫 `resolve_response()` 解開的（`registry.py:276`、`ws/nodes.py:276`）。
   在那個迴圈裡 `await` 一個要靠它自己讀出來的回應，就是一個必然逾時的死鎖。
   而且 daemon 端**根本沒有為自己發出的請求做關聯表**（`connection.go:494` 只有一條
   `switch`）。正解是 **claim-then-offer**（`00-…md` D1、`03-…md` §2）。

2. **讓 `run.log_chunk` 走 8 MiB 的大訊框。**
   控制訊框上限是 **64 KiB**，只有六個 `filesystem.*` 型別被放寬（`codec.py:15/21/32`）。
   而那條 socket **同時載著互動式終端的二進位輸出**——`node_gateway` 的 `raw_bytes`
   分支就在同一個 `while` 迴圈裡（`00-…md` D3、`04-…md` §6）。

3. **把卡片產物做成 protocol 訊息。**
   單件上限 10 MB **大於** 8 MiB 的訊框天花板，而且同樣要跟終端搶那條線。
   `cliora` CLI 已經有對 Central 的 HTTP client（`cli.go:191`），daemon 沒有
   （`00-…md` D4、`06-…md` §3）。

4. **把產物 blob 寫進檔案系統。**
   `docs/deployment-railway.md:27` 明寫容器檔案系統是 **ephemeral**，而
   `CLIORA_ARTIFACTS_DIR` 是**建置時烘進映像**的發行物目錄（`deploy/railway/env.md:29`）
   （`00-…md` D5、`02-…md` §2.6）。

5. **拿 `session_tokens` 當 run 的憑證。**
   `session_tokens.session_id` 是 `NOT NULL` FK → `terminal_sessions`（`0024`），
   而出口條件 16 要求 `terminal_sessions` **不得多出 run 的列**
   （`00-…md` D6、`05-…md` §1）。

6. **把 prompt 放進 argv。**
   `launch.go:23` 的註解已經替本期寫好判準：「加一個呼叫端提供的字串進這張表，
   正是 SEC-002 存在要防的那個變更」。**兩支 CLI 都從 stdin 收 prompt**
   （M-AR-1 於 2026-08-10 實測，`10-…md` §1.1），所以這條不必妥協。
   新表放在**新檔** `runtime/run.go`，讓 `runtime.go` 與 `launch.go` 逐位元組不變
   （`00-…md` D7、`04-…md` §5）。

7. 🆕 **把 run 目錄放進 `RuntimeDirectory`（`/run/agentd`）。**
   那是 tmpfs（`install/systemd.go:39`），重啟就消失，而**失敗的 run 目錄要留 14 天**。
   正解是新增 `StateDirectory=agentd` → `/var/lib/agentd/.cliora/runs/<run_id>/`
   （`00-…md` D17、`04b-…md` §2）。

8. 🆕 **讓 run 目錄落在 allowed root 裡面（哪怕只是預設值不小心）。**
   那會讓兩套授權模型互通：Agent 的中間產物出現在使用者的檔案瀏覽器裡，
   而使用者的 `filesystem.store` 能寫進 run 目錄。
   daemon 要在啟動時**拒絕啟動並指名**，不是印警告（`04b-…md` §3.4）。

9. 🆕 **為了 clone 引入一個 Go 的 git library。**
   mirror ＋ `git worktree` 正是 go-git 支援最弱的部分，而且 Agent 在沙箱裡用的
   一定是真的 `git`——兩套實作看到的狀態會不一樣。`daemon/go.mod` **零 diff**
   由 gate 斷言（`00-…md` D18、`04b-…md` §5.1）。

10. 🆕 **拿牆鐘逾時當「Agent 死了」的判準。**
    一次性指令的逾時**不代表它沒在執行**。兩支 CLI 都有為程式設計的事件流
    （`claude -p --output-format stream-json`、`codex exec --json`），
    所以存活判定是「距上一個事件多久」，牆鐘只是兜底。
    而**租約續租刻意維持無條件**——它答的是另一個問題（`00-…md` D21、`04-…md` §3.4）。

11. **在 UI 上做「在新分頁開啟產物」。**
    Cliora 是單一 origin 部署（ADR 0020），新分頁就是應用 origin，等同內嵌渲染
    （`00-…md` D14、`06-…md` §5、`07-…md` §6）。

## 與 `research/02/04` 的差異

上游規劃已於 2026-08-10 依裁決改寫，所以本表只列**本計畫相對於改寫後的規劃**的偏離。
**除了第 6 條之外都是修正而非裁量**——它們是讀了程式碼之後發現規劃的假設與現況不符。
第 6 條是唯一一項需要人接受代價的，**已於 2026-08-11 接受**。

| # | `research/02/04` | 本計畫 | 依據 |
|---|---|---|---|
| 1 | `runner.poll` → `run.offer` → `run.accept`，認領時機未指明 | **claim-then-offer**：原子認領發生在 poll 當下，offer 是既成事實；`run.decline` 是釋放 | `registry.request()` 的 future 由 `node_gateway` 迴圈自己解，在迴圈內 await 必死鎖；daemon 無 pending map（`00-…md` D1） |
| 2 | `run.artifact`（metadata ＋ 分塊上傳）或 HTTP 端點「二選一，ADR 決定」 | **選 HTTP**，`run.artifact` 不進 contract | 10 MB > 8 MiB 訊框上限；WSS 與終端共線；CLI 已有 HTTP client 而 daemon 沒有（`00-…md` D4） |
| 3 | migration 編號「依實作當下的現況」 | **`0029`／`0030`／`0031`** | 現況已到 `0028_node_removal_sessions` |
| 4 | 「run 目錄放在 `<state>/.cliora/runs/`」但未指明 `<state>` 是什麼 | **systemd `StateDirectory=agentd`** → `/var/lib/agentd`，unit 要新增一行 | 現況只有 `RuntimeDirectory=agentd`（tmpfs，`install/systemd.go:39`），撐不過重啟而失敗的 run 要留 14 天（`00-…md` D17） |
| 5 | 未指明 git 怎麼實作 | **shell out 到 `git` 執行檔**，`go.mod` 零 diff；argv 是封閉表；URL 拆成三欄存 | mirror／worktree 是 go-git 最弱的部分；兩套實作會看到不同狀態；URL 拆欄讓 userinfo 不可表示（`00-…md` D18、`02-…md` §2.2） |
| 6 ✅ | 未提「Central 端的 log 聚合」 | `run_logs` 存**已聚合的區段**（≤64 KiB／≤2 秒才寫一列），代價是 Central 崩潰掉最後一段 | 一個 chunk 一次 DB 寫入會在 `node_gateway` 的單一迴圈裡阻塞終端輸出。**代價已於 2026-08-11 裁決接受**：log 是診斷、可重跑；產物與訊息**不走這條路**所以不受影響（`00-…md` D3、`03-…md` §7） |
| 7 | run 憑證「就是既有的 node credential」（`research/02/08` §6） | node credential 認證 **WSS**；`cliora task say/ask/attach` 另用 **`run_tokens`** | CLI 走 HTTP 不走 WSS，而 `session_tokens` 掛不上 run（`00-…md` D6） |
| 8 | 未提舊 daemon 的情況 | `node.register` 加 **`agent_runner` 能力旗標**（migration `0031`） | 沿用 `context_projection`（`0027`）與 `image_upload`／`file_upload` 的既有形狀（`04-…md` §2） |
| 9 | 「一個 node 可跑多個 runner（不同 runtime）」 | **一個 node 一列 runner，`runtime` 是集合** | 多列共用一條 WSS 會讓「哪一列在線」變成一個要自己維護的假指示燈（`00-…md` D9、`02-…md` §2.1） |
| 10 | 出口條件「`run.cancel` 用 `ps` 驗證無殘留」 | **process group 三段終止 ＋ 掃 `/proc/*/stat` 第 5 欄** | `ps` 是人的驗證方式，不是可重跑的斷言；daemon 既有的 `cmd.WaitDelay` 慣例（`runtime.go:145`）已經是這條的一半（`04-…md` §3.3） |
| 11 | 未提 `project_repositories` 的欄位形狀 | **只有身分欄位**（scheme／host／path／default_branch），**不預建憑證欄位** | 那三欄是 FK 到一張本期不存在的表（`project_secrets`），一個指向不存在的表的 nullable UUID 沒有讀者可以驗證它（`02-…md` §2.2） |
| 12 | 未提 `project_agents` 要不要預先建表 | **不預先建表** | 一個不授權任何東西的授權表，會讓 V2.3 的安全審查失去一個真正的檢查點（`02-…md` §2.2） |

## 檔案

| 檔案 | 內容 |
|---|---|
| `00-execution-plan.md` | 成功定義（十四項判準）、範圍、固定基線決策 **D0–D21**、波次與 ticket、風險 |
| `01-decisions-and-governance.md` | `AR-00`／`AR-01`／`AR-02`：基線與量測、ADR 0029、ADR 0030、PRD §8.13、skill、traceability |
| `02-data-layer.md` | `AR-03`：migration `0029`／`0030`／`0031`，八張表逐欄設計、狀態機、索引、blob 分表 |
| `03-queue-lease-and-eligibility.md` | `AR-05`：**四條件**資格查詢、claim-then-offer、租約 sweep、`waiting_for_input`、重排 |
| `04-contract-and-daemon-runner.md` | `AR-06`／`AR-07`：contract v1.11.0（`spec` 含 `source`）、非互動 argv、取消三段、log 分塊 |
| **`04b-run-directory-and-git.md`** | 🆕 `AR-02b`／`AR-07b`：**§2 一台 node 上的兩棵樹（先看這個）**、`StateDirectory`、run 目錄六條規則、配額與清理、mirror ＋ worktree、**run 程序其實讀得到 allowed root 這件事**、**「專用 runner」的可檢查定義與 `dedicated` 回報**、**Agent 的 git 自由與可觀測性**、**紅線 4 措辭修訂**、`git diff` 附成產物 |
| `05-run-credential-and-cli.md` | `AR-08`：`run_tokens`、Agent principal 的第二種形狀、`cliora task say/ask/messages/attach` |
| `06-rbac-api-and-artifacts.md` | `AR-04`／`AR-09`：四個動作、十七條 API、Repository 端點的驗證、產物儲存與安全提供 |
| `07-frontend.md` | `AR-10`／`AR-11`：Agents 頁、Repository 設定、派工 picker、看板徽章、Run 詳情、訊息串、產物區 |
| `08-verification-and-exit.md` | `AR-12`：測試矩陣、雙旗標回歸、六個 gate ＋ 六條掃描斷言、**24 條出口條件**、五節安全審查、合併關卡 |
| `09-implementation-status.md` | 實作進度與證據（隨實作更新） |
| `10-open-measurements.md` | **M-AR-1（已量）**、M11／M12／M-AR-2／M8-b（開工前）、M10／M13／M16 等（上線後） |

## 執行慣例

```bash
tmux new-session -d -s cliora-v22 -c /home/ubuntu/workspace/cliora
tmux send-keys -t cliora-v22 'make check' C-m
tmux attach -t cliora-v22        # 需要看的時候才 attach
```

**環境事實**（`09-…md` §5）：工具鏈不在預設 PATH 上；DB 測試要**兩個**環境變數；
`claude` 與 `codex` 都裝在 `~/.local/bin`；🆕 **`git` 是 runner 模式的新前置條件**。

## 驗收素材

**Traqora，而且裁決之後正式 repo 可以了**（D30 的階段表已更新）。
原本的限制（「限用 scratch clone」）成立的理由是「run 沒有隔離，直接在 workspace 執行」，
而裁決移除了那個前提：run 拉的是一份自己的 clone、不 push、`origin` 還被移掉了。

**第一次仍建議先用 scratch clone 走一遍**，確認配額與清理之後再對正式 repo 跑。

## 合併回 `dev`

**一律由人工確認。** 出口條件全綠只是取得提案資格，不是核准；
自動化（含 CI 與 agent）不得發起或完成這個合併
（`research/02/10-verification-and-exit.md` §7）。
