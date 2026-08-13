# 04 — `AR-06`／`AR-07`：contract v1.11.0 與 `agentd` 0.9.0 的執行面

> **2026-08-10 裁決對本章的三個影響**：① `spec` **含 `source`**（repo URL ＋ ref），
> 原本排在 v1.12.0；② `spec` **不含 `workspace`**——run 目錄由 daemon 自己決定；
> ③ §4 的「重用 V2.1 的 `VerbProject` 投影」**整段作廢**——run 目錄是 daemon 自己的，
> 情境包直接寫，`daemon/internal/files/` 因此變成**整包禁區**。
> 目錄與 clone 的設計在 [`04b-run-directory-and-git.md`](./04b-run-directory-and-git.md)。

## 1. contract v1.11.0

### 1.1 訊息清單

十一個新型別，全部進 `control-envelope.schema.json` 的 `type` enum 與 `allOf` 的
`$ref` 分支，payload schema 進 `contracts/v1/schemas/messages/`：

| 型別 | 方向 | payload |
|---|---|---|
| `runner.register` | node → central | `{ runner_id?, name, runtimes[], labels[], max_concurrent, max_waiting, dedicated }` |
| `runner.registered` | central → node | `{ runner_id, accepted, reason? }` |
| `runner.poll` | node → central | `{ runner_id, capacity }` |
| `run.offer` | central → node | `{ run_id?, task_id, project_id, spec }`（`run_id: null` ＝ 沒有工作） |
| `run.accept` | node → central | `{ run_id }` |
| `run.decline` | node → central | `{ run_id, reason }` |
| `run.lease_renew` | node → central | `{ run_id }` |
| `run.progress` | node → central | `{ run_id, phase, message? }` |
| `run.log_chunk` | node → central | `{ run_id, seq, data, truncated }` |
| `run.complete` | node → central | `{ run_id, result, summary? }` |
| `run.failed` | node → central | `{ run_id, error_code, message }` |
| `run.cancel` | central → node | `{ run_id, reason }` |

**`run.artifact` 不在這張表上**（`00-…md` D4）：產物走 HTTP。
規劃把它列為「二選一」，這是那個選擇。

### 1.2 三條寫進 schema 而不是寫進註解的約束

1. **`run.log_chunk.data` 的 `maxLength` 是 32768。**
   控制訊框上限是 64 KiB（`backend/app/protocol/codec.py:15`），只有六個 `filesystem.*`
   型別被放寬到 8 MiB（同檔 `LARGE_FRAME_TYPES`）。`run.log_chunk` **不加進那個集合**
   （`00-…md` D3），所以 schema 的 `maxLength` 要留出 JSON 轉義與 envelope 的空間。
   一條 invalid fixture 專門測這條。

2. **`spec` 的 `additionalProperties: false`，而且它沒有 `secrets`、沒有 `command`、
   沒有 `args`、沒有 `env`、**也沒有 `workspace`**。** 本期的 `spec` 是：

   ```json
   { "runtime": "claude",
     "source": { "kind": "repo",                     // none | repo | existing_branch
                 "url": "https://github.com/Lei-k/Traqora",
                 "ref": "main" },
     "context": "…",
     "allowed_verification_commands": [],
     "timeout_seconds": 21600,          // 牆鐘兜底（§3.4），不是主要的存活判定
     "idle_timeout_seconds": 300 }      // 存活的主要判定
   ```

   **`workspace` 不存在，這是裁決在 contract 上最直接的痕跡。** 只要那個欄位在，
   Central 就得決定一條使用者的路徑並送過去，而那正是被否決的形狀。
   run 目錄由 daemon 自己決定（`04b-…md` §2），Central 連它叫什麼都不知道。

   `source.kind = "none"` 時 `url` 與 `ref` 必須**不存在**（`if/then` 條件式 schema），
   不是「送 null」。理由與 `filesystem-store` 那條註解相同：
   **一個不該存在的欄位要不可表示，而不是被忽略。**

   `context` 是**要餵給 stdin 的文字**，不是一個要放進 argv 的字串——這個區分寫在
   schema 的 `$comment` 裡（沿用 `context-project.schema.json` 那條註解的做法：
   註解不是裝飾，它是下一個人讀 schema 時唯一會讀到的設計說明）。

3. 🆕 **`dedicated` 是回報不是設定。** schema 的 `$comment` 要寫明它由
   `len(workspace.allowed_roots) == 0` 導出，Central **只存不驗**——
   與 `sandbox_bypass` 的 requested／actual 分離是同一種形狀（ADR 0023 D3）。
   它存在的理由在 `04b-…md` §3.5：「Agent 讀不到使用者的 workspace」這件事
   平台沒有技術上的隔離，而這個欄位讓那個事實在 console 上看得見。

4. **`secrets` 在任何訊息上都不合法。** 這是紅線 1 修訂後不變式的機器檢查
   （`research/02/08` §4 明文要求）。本期 `run.offer` 也沒有 `secrets`
   （V2.3 才加），所以這條 invalid fixture 現在測的是「所有訊息」，
   V2.3 把它縮成「`run.offer` 以外的所有訊息」。

### 1.3 錯誤碼

envelope 的 `error.code` enum 新增五個：

```text
RUN_NOT_FOUND          未知的 run_id（late/duplicate）
RUN_INVALID_STATE      對一個終態的 run 送 lease_renew / progress
RUNNER_NOT_REGISTERED  poll 之前沒有 register
RUNNER_DISABLED        runner 被 Admin 停用
AGENT_RUNS_DISABLED    CLIORA_AGENT_RUNS_ENABLED=false（D12）
RUN_SOURCE_UNAVAILABLE clone／fetch 失敗（含缺憑證、host 不在 allowlist、ref 不存在）
RUN_DISK_QUOTA         run 目錄或 node 總量配額用盡
RUN_IDLE_TIMEOUT       child 距上一個事件超過 idle 上限（存活的主要判定，§3.4）
RUN_TIMEOUT            牆鐘上限（兜底，不是主要判定）
```

後四個是 2026-08-10／08-11 帶來的。
**`RUN_IDLE_TIMEOUT` 與 `RUN_TIMEOUT` 要分開**，因為它們對使用者的意思不同：
前者是「它卡住了」（值得看 log 最後一個事件），後者是「它跑不完」（值得看卡片是不是太大）。
`RUN_SOURCE_UNAVAILABLE` 的 `details` 要能分辨
**認證失敗／host 不允許／ref 不存在**三種——它們是使用者要做三件不同事情的訊號
（`04b-…md` §5.4）。**`details` 不得回顯 URL**（使用者可能貼錯，把憑證放進去了）。

同步進 `backend/app/api/error_catalog.py`，並重新產生 `docs/error-catalog.md`。

### 1.4 fixtures

每個訊息一個 valid，加上規劃點名的六類 invalid，共 **12 valid + 17 invalid**：

| invalid | 測什麼 |
|---|---|
| 缺 `run_id` | 必填欄位 |
| 未知 `phase` | 封閉詞彙 |
| `log_chunk` 的 `data` 超過 32 KiB | §1.2 第 1 條 |
| `capacity` 為負／`max_concurrent` 為 0 | 數值下界 |
| 非 UTC 時間戳 | envelope 的既有 pattern |
| 未知型別 `run.something` | enum |
| `spec` 帶 `secrets` | §1.2 第 3 條 |
| `spec` 帶 `command`／`args`／`env` 各一 | SEC-002 的機器形式 |
| **`spec` 帶 `workspace`** | 裁決的機器形式：run 不使用 workspace（§1.2） |
| `source.kind = "none"` 卻帶 `url` | 條件式 schema |
| `source.url` 帶 userinfo（`https://u:p@host/…`） | `04b-…md` §5.2 的禁令 |
| `source.url` 的 scheme 不是 https／ssh | 同上 |
| `runtimes` 含未知 runtime | allowlist |
| `run.complete` 的 `result` 未知 | 封閉詞彙 |

**`GATE-AR-CONTRACT-ADDITIVE`**（沿用 `scripts/tk/gate-contract-additive.sh`）斷言
**既有 fixture 逐檔未變**（開工當下是 46 valid ＋ 63 invalid ＝ 109 個檔，
以 `AR-00` 的清單為準），`manifest.json` 具名豁免並列印
（沿用 `plan/17/09` §3 第 6 條的處置）。三個語言（Python／Go／TypeScript）都要跑。

## 2. 能力旗標與舊 node

`node.register` 的 payload 加一個 `agent_runner: boolean`（與 `context_projection`、
`image_upload`、`file_upload` 逐字同形狀），落地為 `nodes.agent_runner`
（migration `0031`，預設 false 且**不回填**）。

- 0.8.0 的節點不送這個欄位 → 保持 false → Agents 頁上顯示
  「此 node 的 agentd 需升級到 0.9.0 才能作為 Agent Runner」，
  **不是 500、不是靜默隱藏**（`research/02/08` §9 要求可行動訊息）。
- **不做自動升級**：`node_update` 是既有的分批機制，本期不碰它、也不自動觸發它。

`runner.register` 本身**只有在 `agent_runner=true` 且 `CLIORA_AGENT_RUNS_ENABLED=true`
時才被接受**，否則回 `error` ＋ `AGENT_RUNS_DISABLED`。

## 3. `agentd` 0.9.0 — runner 模式

### 3.1 開關與生命週期

`agentd serve --runner`，或設定檔 `runner.enabled: true`。它**不是**第二個行程、
不是第二條連線——它是既有 `connection.Manager` 上的一組新 handler 與一個 poll 迴圈。

```text
session() 成功認證並 node.register 之後：
  若 runner 啟用且至少一個 runtime runner-capable
    → 送 runner.register
    → 起 pollLoop（與 heartbeatLoop 同一個 sctx，同樣用 wg 等它退出）
```

`pollLoop` 沿用 `heartbeatLoop`（`connection.go:334`）的形狀逐字：
同一個 context、同一個 `write` 閉包（所以共用那把 `writeMu`，
不會與終端輸出交錯）、同一個「連線斷了就退出」語意。

**capacity 的計算**：`max_concurrent - len(running) `。滿了**就不送 poll**——
背壓天然（D17），不是送一個 `capacity: 0` 讓 Central 去判斷。

**`max_concurrent` 與 Session 的上限是兩個互不相干的計數器**：
後者是 Central 的 `sessions_per_node_max`（`settings.py:75`，預設 10）。
一台 `max_concurrent: 2` 的 node 可以同時有 2 個 run ＋ 好幾個 Session。
三種「同時」與它們的共用點（一條 WSS、一顆磁碟、一個 OS 使用者）見
`04b-…md` §2.2／§2.3。

### 3.2 執行一次 run

```text
run.offer（run_id 非 null）
  1. 檢查容量與磁碟配額 → 不行就 run.decline（04b §4.1）
  2. 建立 run 目錄；情境包與 run token 直接寫進 <run>/.cliora/（04b §3.3）
  3. source ≠ none → mirror + worktree + 移除 origin
     → run.progress{phase:"checked_out", commit_sha}（04b §5.3）
     失敗 → run.failed{RUN_SOURCE_UNAVAILABLE}
  4. runtime.BuildRunCommand(rt, RunOptions{Dir: <run>/repo 或 <run>, Context}) （§5）
  5. run.accept
  6. 起程序、接管 stdout/stderr、送 run.progress{phase:"running"}
  7. 逐行讀 stdout 的 JSONL 事件 → ① 更新 last_event_at（存活）
     ② 映射成 run.progress 的 phase ③ 分塊送 run.log_chunk
     另外每 30 秒送 run.lease_renew（那是「runner 活著」，與 child 無關，§3.4）
  8. 程序結束 → git status --porcelain；有變更且 delivery ∈ {none,artifact}
     → git diff 附成產物（04b §6）
  9. run.complete{result, disk_bytes} 或 run.failed{error_code}
 10. 刪掉 token 檔（目錄本體留到保留期）
```

**第 3 步在第 5 步（`run.accept`）之前**：clone 可能要幾十秒到幾分鐘（M11），
而那段時間 run 的狀態應該是 `claimed` 而不是 `running`——
Run 詳情頁的時間軸要能分出「在拉程式碼」與「在執行」。
`run.progress{phase:"checked_out"}` 是那條分界線。

**沒有 PTY、沒有 tmux、沒有 `session.Manager`、沒有 `workspace.Root`。**
這是 `research/02/00` §2 那張「兩種執行模式」表在程式碼上的形式。
`GATE-AR-TOUCH-LIST` 斷言
`daemon/internal/{terminal,tmux,session,workspace,files}` 零 diff
——**`workspace` 與 `files` 是裁決之後新加進禁區的兩個**（§7）。

### 3.3 取消：三段終止

`run.cancel` 進來時：

```text
1. SIGINT 給整個 process group（Setpgid + syscall.Kill(-pgid, SIGINT)）
2. 等 cancel_grace（預設 10 秒）
3. SIGKILL 給整個 process group
4. cmd.WaitDelay 關閉 I/O pipe，避免孤兒孫程序卡住 Wait
```

第 4 步不是新東西：`runtime.go:145`／`:168` 已經在 `--version` 與 `--help` 的探測上
用 `cmd.WaitDelay = 200ms`，理由逐字相同（「一個孤兒孫程序握著寫入端會讓
`CombinedOutput` 卡過逾時」）。run 的程序會 fork 子程序（測試、建置），
所以**必須是 process group 而不是單一 pid**。

出口條件 8 的斷言是**掃 pgid**（`/proc/*/stat` 的第 5 欄），不是 `ps` 目視——
規劃寫「用 `ps` 驗證」，那是人的驗證方式，不是可重跑的測試（差異表 #10）。

### 3.4 三個計時器，各自回答一個不同的問題

**這一節在 2026-08-11 被改寫。** 原本只有一個牆鐘硬逾時，而那是錯的：

> 一次性指令的逾時**不代表它沒在執行**，很可能 Agent 還在處理。
> 拿牆鐘當存活訊號就是拿誤判當機制。

更糟的是**租約續租原本是無條件的**：daemon 每 30 秒送 `run.lease_renew`，
不管 child 在做什麼。所以 child 掛死時 Central 完全看不出來——
唯一會踩到的就是那個會誤判的牆鐘逾時。

拆成三個計時器，每一個回答一個不同的問題：

| 問題 | 機制 | 誰判 | 逾時後 |
|---|---|---|---|
| **runner** 還活著嗎 | `lease_expires_at`（30s 續租／`CLIORA_RUN_LEASE_TIMEOUT_S` 180s） | **Central** 的 sweep | `lost` → 重排（`03-…md` §6） |
| **child** 還在前進嗎 | **idle timer**：距上一個 JSONL 事件 > `runner.idle_timeout_seconds` | **daemon** 本地 | `run.failed{RUN_IDLE_TIMEOUT}` |
| child 會不會永遠不停 | 牆鐘上限 `spec.timeout_seconds` | **daemon** 本地 | `run.failed{RUN_TIMEOUT}` |

三件事要寫清楚：

1. **`run.lease_renew` 仍然是無條件的，而那是對的。** 它回答的是「runner 活著」——
   一個事實，而且是一個有用的事實：它把「runner 掛了」與「child 掛了」分成兩種
   **不同的失敗與不同的收斂路徑**（前者重排，後者是 run 失敗）。
   把它改成「只在 child 有活動時續租」會讓兩種失敗長得一樣，而它們的處置不同。
2. **idle timer 是存活的主要機制，牆鐘變成兜底。** 所以牆鐘的預設值要**放大**
   （建議 6 小時，而不是原本的 1 小時）——它現在防的是「一個真的跑不完的 Agent」，
   不是「一個正在工作的 Agent」。`runner.idle_timeout_seconds` 建議 **300 秒**，
   而真實值等 M-AR-9 量（`10-…md`）。
3. **`stdin` 餵完立即關閉**這條保留。一個等輸入的程序拿到 EOF 而不是永遠等——
   而現在它拿到 EOF 之後若還是不動，idle timer 會在 5 分鐘內收掉它，不是 6 小時。

#### 為什麼不用互動模式（PTY）取得即時狀態

「用互動模式像互動 Session 那樣，透過 stdio 交互」的方向是對的——
**要的是 stdio 的雙向即時，而那個兩支 CLI 都有，且不需要 PTY**：

| | 互動模式（PTY） | `stream-json` / `--json` |
|---|---|---|
| 存活訊號 | 有 byte 就算活著 | **有 event 就算活著，而且知道它在做什麼** |
| 即時輸入 | 打字進 PTY | `claude --input-format stream-json` ＋ `--replay-user-messages`（有 ack） |
| log 長什麼樣 | ANSI 螢幕重繪：spinner、alternate screen、游標移動 | 結構化事件，逐行可解析 |
| 與 D26／出口條件 16 | **run 變成 Session**：PTY ＋ tmux ＋ relay ＋ writer 語意，「兩條路徑在程式碼上分開」倒了 | 不變 |
| 與 D27 的界線 | run log 變成一段終端錄影——把「平台不存終端位元組」用最難看的方式重新打開 | log 是事件紀錄，D27 的四條約束原封不動成立 |

**關鍵論點：byte-level 存活比 event-level 弱。**
一個 spinner 在重繪只證明 renderer 活著；一個 `tool_use` 事件證明它在前進。

**`--include-partial-messages` 本期不用**（token 級的 delta）：它會把 log 量放大一個數量級，
而 D3 的訊框預算與出口條件 24（終端延遲）都在同一條線上。
若 M-AR-9 顯示 tool-call 粒度的 idle 判定太粗，它是第一個要試的旋鈕。

## 4. run 的情境包：daemon 直接寫，不經過投影面

裁決之前，本計畫打算重用 V2.1 的 `VerbProject` 把情境包寫進使用者 workspace 的 `.cliora/`。
**裁決之後那整段作廢**，而作廢的方式讓事情變簡單而不是變複雜：

| | 裁決之前（作廢） | 現在 |
|---|---|---|
| 情境包寫在哪 | 使用者 workspace 的 `.cliora/context/<run_id>.md` | **run 目錄**的 `.cliora/context/<run_id>.md`（`04b-…md` §3.3） |
| 誰寫 | daemon，經過 `files` 套件的 `VerbProject` 政策 | daemon **直接寫**——那是它自己的目錄 |
| 要不要動 `daemon/internal/files/` | 要（至少要讓 `VerbProject` 接受一個新的呼叫情境） | **不要。整包禁區** |
| 清理 | 靠 V2.1 的 `projectionRetentionLoop`（30 天） | run 目錄自己的保留期（成功 3 天／失敗 14 天） |
| 一個目錄有多份 context 的歧義 | 要處理（Session 的 ＋ run 的） | **不存在**：一個 run 目錄只有一份 |

三個後果：

1. **`daemon/internal/files/` 從「部分允許」變成整包禁區**（`00-…md` D16）。
   本期不碰使用者的檔案面**任何一個位元組**，這比 V2.1 的承諾更強。
2. **`.cliora/` 的可寫集合不必放寬。** 紅線 3 在本期完全不受挑戰。
3. **`cliora` CLI 不必改一行就找得到情境包**：`FindContext` 是「從 cwd **往上**找
   `.cliora/context/`」（`cli.go:71`），而程序的 cwd 是 `<run>/repo`，往上一層就是。
   只有兩句錯誤訊息的措辭要改（`05-…md` §2.1）。

`process/` 的投影同理：直接寫進 run 目錄，**不必處理「已存在就跳過」**——
V2.1 那條「`FILE_EXISTS` 視為成功」的規則是為了共用 workspace 而設的，
而 run 目錄每次都是新的。

## 5. 非互動執行面（`daemon/internal/runtime/run.go`）

### 5.1 新檔，不改舊檔

```go
// run.go — 新增。runtime.go 與 launch.go 零 diff（plan/18/00 D7）。

// runArgs is the complete, closed table of arguments that put an allowlisted
// runtime into non-interactive mode. Same rule as sandboxBypassArgs in launch.go:
// adding a caller-supplied string here is the change SEC-002 exists to prevent.
// The prompt does NOT go here — it goes on stdin.
// M-AR-1 於 2026-08-10／08-11 實測填入（`10-…md`）：
//   claude 2.1.226     -p                              "Print response and exit"
//                      --output-format stream-json     "realtime streaming"
//   codex-cli 0.146.0  exec                            "Run Codex non-interactively"
//                      --json                          "Print events to stdout as JSONL"
var runArgs = map[string][]string{
    // 事件流是刻意的，不是額外的：整個存活判定靠它（§3.4）。
    "claude": {"-p", "--output-format", "stream-json"},
    "codex":  {"exec", "--json"},
}

func RunCapable(rt Runtime) bool          // 探測 --help，快取一次
func BuildRunCommand(rt Runtime, opts RunOptions) (*exec.Cmd, error)
```

`BuildRunCommand` 用 `rt.Binary()` ＋ `rt.LaunchArgs()` ＋ `runArgs[rt.ID()]`，
三者都是既有的或本檔的封閉表。**沒有任何一個字串來自 `run.offer`**。

`RunOptions` 只有四個欄位：`Dir`、`Context`（→ stdin）、`Timeout`、`Env`（見 §5.2）。
**沒有 `Command`、沒有 `Args`、沒有 `Workspace`。** 型別本身就是 SEC-002 的形式，
與 `StartOptions` 一樣（`runtime.go:38`）。

**欄位叫 `Dir` 而不是 `Workspace`**：那個字在這個 repo 裡有一個明確的意思
（allowed root 內的一條路徑，`workspace.Root` 管的東西），而 run 目錄不是那個東西。
用同一個字會讓下一個人以為它該過 `authorize_workspace()`。

新檔而不是改舊檔，是為了讓 `GATE-AR-TOUCH-LIST` 能用
「`runtime.go` 與 `launch.go` 零 diff」當斷言——一個 `git diff --name-only`
判得出來的承諾，比一段話有用。

### 5.2 環境變數：本期是空的，但介面要在

紅線 1 的部分撤銷（環境變數，僅 Agent Run 路徑）**是 V2.3 的事**。
本期 `RunOptions.Env` 恆為空，但欄位與「值只來自平台 secret store」的註解要在，
否則 V2.3 會變成事後補綴。

同理**去識別的掛勾點**：

```go
type Redactor interface{ Redact([]byte) []byte }
var noopRedactor Redactor  // 本期沒有機密可去識別
```

一條測試斷言「所有送出的 `run.log_chunk` 都經過 `Redactor`」——
本期它什麼都不做，但那條測試在 V2.3 會變成真的護欄。

### 5.3 `RunCapable` 的探測——現在是迴歸守衛，不是發現機制

**先看要寫什麼（四件事，約 60 行 Go ＋ 一行 UI 文案），再看為什麼。**

#### ① 一張表 — `daemon/internal/runtime/run.go`（新檔）

見 §5.1。`{claude: ["-p"], codex: ["exec"]}`。

#### ② 一個探測 ＋ 一個重置 — 同一個新檔

```go
var (
    probeMu    sync.Mutex
    probeCache map[string]bool          // runtime id -> runner-capable
)

// RunCapable reports whether the installed binary still accepts the
// non-interactive entry point in runArgs. Probed by --help, exactly like
// cliRuntime.bypassAvailable (runtime.go:114) — but the cache lives HERE and is
// reset per connection, not per process. Two caches with two lifetimes is
// deliberate; see ResetRunProbes for why.
func RunCapable(rt Runtime) bool {
    args := runArgs[rt.ID()]
    if len(args) == 0 || rt.Binary() == "" { return false }
    probeMu.Lock(); defer probeMu.Unlock()
    if v, ok := probeCache[rt.ID()]; ok { return v }
    v := helpMentions(rt.Binary(), args[0])   // <binary> --help + WaitDelay + Contains
    if probeCache == nil { probeCache = map[string]bool{} }
    probeCache[rt.ID()] = v
    return v
}

// ResetRunProbes clears the cache, once per connection, before runner.register:
// "the user upgraded the CLI" must not require a daemon restart to be noticed.
func ResetRunProbes() { probeMu.Lock(); probeCache = nil; probeMu.Unlock() }

// RunnerCapableIDs returns the ids that are both Available and RunCapable.
// Uses only exported API (Registry.Get, Runtime.Binary/ID), so runtime.go stays
// zero-diff (plan/18/00 D7).
func RunnerCapableIDs(reg *Registry, detected []DetectResult) []string
```

**快取放 package 層而不是 `cliRuntime` 上，唯一的理由是 `runtime.go` 是本期的零 diff 禁區**
（D7）。這句話要寫進 `run.go` 的註解，否則下一個人會覺得它放錯地方了。

#### ③ 一個接線點 — `connection.go` 的 `session()`

在 `node.register` 之後、`runner.register` 之前（`detected` 已經在手上，`:238`）：

```go
runtime.ResetRunProbes()
capable := runtime.RunnerCapableIDs(m.registry, detected)
if m.cfg.Runner.Enabled && len(capable) > 0 {
    write("runner.register", protocol.NewID(), map[string]any{
        …, "runtimes": capable,
        "dedicated": len(m.cfg.Workspace.AllowedRoots) == 0,   // 04b-…md §3.5
    })
    go m.pollLoop(sctx, write)
}
```

#### ④ 兩個消費端

- **Central**：`capable` 落成 `agent_runners.runtimes`；資格查詢用
  `r.runtime = ANY(:runner_runtimes)` 比對它（`03-…md` §3）。
  **空陣列 ⇒ 這台 runner 永遠不符合任何卡。**
- **UI ＋ `agentd doctor`**：`runtimes` 缺了一個**已偵測到**的 runtime 時，印
  「codex：偵測到，但這個版本不支援非互動執行」。

**沒有新 protocol 訊息**（`runtimes[]` 本來就在 `runner.register` 的 payload 裡）、
**沒有額外 migration**、**沒有新 RBAC**。

#### 兩個走查（這是 D8 唯一的價值所在）

```text
正常：
  probe → claude --help 含 "-p"、codex --help 含 "exec"
  register runtimes: ["claude","codex"]
  runtime=codex 的卡 → 符合資格 → 領走

codex 升級後 exec 改名：
  probe → codex --help 不含 "exec" → not capable
  register runtimes: ["claude"]                    ← codex 消失
  runtime=codex 的卡 → 候選集合為空 → 一直排隊
  Agents 頁 ＋ doctor：「codex：偵測到，但這個版本不支援非互動執行」
```

**沒有 ② 的話**，第二個走查會變成：程序帶著一個不存在的旗標啟動 →
`codex` 把 `exec` 當成 prompt → 開互動式 session → 一個事件都不吐 →
**idle timer 在 5 分鐘後收掉它**（而不是牆鐘的 6 小時）。
比原本好，但仍然是一個每張卡都要浪費 5 分鐘、而症狀指不到旗標的失敗。
使用者看到的是「Agent 跑了一小時然後失敗」，而症狀指不到旗標。

**沒有 `ResetRunProbes` 的話**，反方向一樣難查：升級**修好**了旗標但快取還是 `false`，
那台 runner 一直領不到卡，**而看板上的解釋是假的**。

#### 為什麼要留探測（量完了還留）


M-AR-1 已經量出答案（§5.1 的表），所以探測的角色變了：
它不再是「找出旗標是什麼」，而是**「第三方 CLI 改了介面時不要靜默壞掉」**。

沿用 `cliRuntime.bypassAvailable()`（`runtime.go:114`）的形狀：
`<binary> --help`、`WaitDelay`、探不到就是 false。
探的是 `runArgs[id]` 的**每一個非值元素**是否出現在 help 輸出裡
（claude：`-p` ＋ `--output-format`；codex：`exec` ＋ `--json`）。

**流式旗標與非互動旗標同等重要，所以一起探。** 理由：整個存活判定建立在事件流上
（§3.4）。一個支援 `-p` 但沒有 `--output-format stream-json` 的版本，
**我們寧可宣告它 not capable，也不要退回「純文字輸出 ＋ 牆鐘逾時」那個會誤判的模式**
——退化路徑會在半年後變成唯一還在跑的路徑，而沒有人記得它比較差。

**`git` 也走同一條探測**（`git --version`，`04b-…md` §5.1）：
沒有 `git` 的 node 不能當 runner，而那要在註冊時就說清楚，不是等第一個 run 失敗。

#### ⚠️ 快取的範圍要比 `bypassProbe` 窄一格：**每次重連重探**

既有的 `bypassProbe` 快取在 `cliRuntime` 上，而 `Registry` 在 `cmd/agentd/run.go:37`
建立一次、由 `connection.Manager` 持有**整個行程的生命週期**。
`DetectAll` 每次重連都會跑（`connection.go:238`），但它只重跑 `Detect`（`--version`）,
**不會清掉旗標探測的快取**。

所以 `runtime.go:86` 的那句註解——

> Probed once per process: the answer only changes when the CLI is upgraded,
> and an upgrade is followed by a daemon restart **or reconnect** (runbook).

——的「or reconnect」對 `bypassProbe` 就已經略微樂觀了（重連並不會重探）。
對 `RunCapable` 後果更大，因為它決定的不是一個顯示用的徽章而是**能不能領卡**：

| 情境 | `bypassProbe` 過期的後果 | `RunCapable` 過期的後果 |
|---|---|---|
| 升級後旗標**消失** | console 上的沙箱徽章說錯（顯示問題） | 每個 run 帶著壞旗標啟動 → 立刻報錯（**可見**，可接受） |
| 升級後旗標**出現** | 徽章保守（顯示問題） | **那台 runner 一直領不到卡，而 Agents 頁上的原因是過期的**（難查） |

右下角那一格是不可接受的：症狀是「卡片一直排隊」，而看板上的解釋
（「codex：這個版本不支援非互動執行」）**是假的**——它已經支援了。

**處置：`RunCapable` 的快取生命週期是「一次連線」而不是「一個行程」。**
`session()` 在送 `runner.register` 之前呼叫一次 `registry.ResetRunProbes()`，
然後 `RunCapable` 重探一次。成本是**每個 runtime 每次重連一次 `--help`**
——重連不頻繁（backoff 最長 `maxBackoff`），而 `--version` 本來就在同一個位置重跑了。

**不動 `bypassProbe`**（那是 `runtime.go` 的既有行為，而 `runtime.go` 是本期的零 diff 禁區，
D7）。新的重探只作用在 `run.go` 自己的快取上——**兩個快取、兩個生命週期，
而它們的差別要寫在 `run.go` 的註解裡**，否則下一個人會覺得其中一個寫錯了。

**探不到 ⇒ 該 runtime 不進 `runner.register` 的 `runtimes[]`**（`02-…md` §2.1），
所以它永遠不符合任何卡片的資格。doctor 印出原因，Agents 頁顯示
「codex：偵測到，但這個版本不支援非互動執行」。

這與 ADR 0023 D3 是同一條原則：**回報機器實際的姿態，不要回報你希望的姿態**。

### 5.4 沙箱姿態

`LaunchArgs()` 帶的是 sandbox bypass 旗標。一個無人值守的 run 若在
`sandbox_bypass: false` 的 node 上跑，很可能會停在一個沒有人會回答的核准提示前，
直到牆鐘兜底。

**M-AR-1 量到了兩支 CLI 的實際選項**（`10-…md`），而它們的形狀不同：

| | 非互動時的核准／沙箱選項 | 本期怎麼用 |
|---|---|---|
| `claude` | `--permission-mode {acceptEdits, auto, bypassPermissions, manual, dontAsk, plan}`；`-p` 時 workspace trust 對話被跳過 | **待定，見下** |
| `codex` | `-s {read-only, workspace-write, danger-full-access}` ＋ 既有的 `--dangerously-bypass-approvals-and-sandbox` | `exec -s workspace-write`；node 要求 bypass 時才用既有那個旗標 |

**codex 那一格是裁決的一個附帶好處**：run 目錄是隔離的，所以 `-s workspace-write`
給出一個**真的、範圍就是 run 目錄**的沙箱——比互動式 Session 的姿態更緊，而不是更鬆。

**claude 那一格是本期唯一還沒定的實作細節**，因為既有的 `sandboxBypassArgs` 表裡
**沒有 claude 的條目**（只有 codex）。三個選項：
① 不加任何 `--permission-mode`，用預設（風險：非互動下遇到需要核准的動作可能停住）；
② 加 `--permission-mode dontAsk`（若語意是「不問、直接拒絕」，那是**失敗而不是掛住**，
是正確的失敗模式）；③ 依 node 的 `sandbox_bypass` 設定在 `bypassPermissions` 與
`dontAsk` 之間選。

**建議 ③，但要先用一次真的 run 確認 `dontAsk` 的語意**——那是 `AR-07` 的第一件事，
不是能從 `--help` 讀出來的東西（`10-…md` M-AR-1 的殘留項）。
不做的是「偷偷在 run 路徑上打開 bypass」：那是繞過 node 的部署姿態。

## 6. log 分塊（daemon 側）

```text
stdout（JSONL 事件）＋ stderr（純文字）→ 合併 → Redactor → 分塊器
  逐行切，不切斷一行 JSON——一個被切成兩半的事件在 UI 上無法渲染，
  而「不要切斷一行」比「湊滿 32 KiB」重要
分塊器：≤32 KiB／塊，或 200ms 沒有新資料就送出（避免一行輸出等到湊滿才出現）
每塊帶遞增 seq
每讀到一行事件就更新 last_event_at（§3.4 的 idle timer 用同一個時間戳）
累計超過 CLIORA_RUN_LOG_MAX_BYTES 的一半（node 側自己的保險）→ 設 truncated 旗標
```

**兩端都有上限**是刻意的：node 端的是「不要送」，Central 端的是「不要存」。
只有一端有，另一端就得信任對方。

`run.log_chunk` 與 `run.lease_renew` 共用那把 `writeMu`（§3.1），
所以續租不會被一長串 log 卡住——**除非**分塊器一次排隊太多。
所以分塊器對「待送佇列」也要有上限（預設 32 塊），滿了就丟棄並累加 truncated 計數，
**不是阻塞讀取**（阻塞讀取會讓被執行的程序的 stdout pipe 填滿而卡死）。

## 7. `GATE-AR-TOUCH-LIST`（節點側）

本期的允許清單與禁區與 V2.1 不同，差別要寫下來：

```text
ALLOWED   daemon/internal/runtime/run(_test)?\.go        ← 新檔（D7）
          daemon/internal/gitfetch/                      ← 新套件（04b §5.1）
          daemon/internal/connection/(connection|runner_handlers)\.go
          daemon/internal/config/                        ← runner 區段
          daemon/internal/install/systemd\.go            ← 只加 StateDirectory 一行（D17）
          daemon/internal/cli/                           ← 四個新子命令
          daemon/internal/protocol/codec\.go             ← 新型別
          daemon/cmd/agentd/main\.go, daemon/VERSION, contracts/

FORBIDDEN daemon/internal/(terminal|tmux|tunnel|update|systeminfo|metrics)/
          daemon/internal/files/                         ← 🆕 整包（run 不碰檔案面）
          daemon/internal/workspace/                     ← 🆕 整包（run 不在 allowed root 內）
          daemon/internal/session/                       ← 整包
          daemon/internal/runtime/(runtime|launch)\.go   ← 兩個檔零 diff（D7）
          daemon/go\.mod                                 ← 🆕 不新增依賴（04b §5.1）
```

與 V2.1 的四個差別，各有一句理由：

1. **`daemon/internal/files/` 從「部分允許」變成整包禁區。** V2.1 為了投影動了
   `project.go`／`store_policy.go`／`search.go`；裁決之後 run 目錄是 daemon 自己的、
   情境包直接寫（§4），所以本期不碰使用者的檔案面**任何一個位元組**。
2. **`daemon/internal/workspace/` 進禁區。** run 不在 allowed root 內，
   它連讀 `workspace.Root` 都不需要。**這條 gate 是判準 6（互不可達）的靜態形式**
   ——動態形式是 `04b-…md` §7 的測試 1–3。
3. **`daemon/internal/runtime/` 從整包禁區變成「兩個檔零 diff、可新增檔案」**（D7）。
4. **`daemon/go.mod` 進禁區。** git 走執行檔不走 library（`04b-…md` §5.1），
   而「有沒有新增依賴」是那個決定唯一可機器判定的形式。
