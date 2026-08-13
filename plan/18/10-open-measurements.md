# 10 — 開放量測項

沿用 `plan/12`／`plan/15`／`plan/17` 的慣例：**這些是還不知道答案的問題，不是待辦事項。**
每一項都要寫清楚「答案會改變什麼」，否則它就只是一個沒有人會去看的數字。

> **2026-08-10 的兩個變動**：① **M-AR-1 已經量出答案**（見 §1.1）；
> ② 裁決把 clone 提前到 V2.2，所以 **M11／M12 從「V2.3 開工前」變成「V2.2 開工前」**。
>
> **2026-08-11**：M-AR-1 補量到**流式輸出旗標**，而它改變了存活判定的整個設計
> （`00-…md` D21）。新增 **M-AR-9**（事件間隔分布，校準 idle timeout）與
> **M-AR-10**（無人值守的 token 花費）。

## 1. 開工前必須有答案（`AR-00`）

**五項，其中 M-AR-1 已完成。** 它們擋的是波次 3（`AR-07`／`AR-07b`）；
波次 0–2 不受影響（`09-…md` §0）。

### 1.1 M-AR-1 — `claude` 與 `codex` 的非互動介面 ✅ **已量（2026-08-10）**

**先修正一件事：這台機器上兩支 CLI 都有裝**，在 `~/.local/bin/`。
先前記成「沒有裝」是因為用了預設 PATH 去 `which`——
而 `plan/17/09` §5 的第一列環境事實寫的正是「工具鏈不在預設 PATH 上」。
**同一個陷阱踩了第二次**，所以它現在也寫進 `09-…md` §5 的第三列。

```
$ claude --version   → 2.1.226 (Claude Code)
$ codex --version    → codex-cli 0.146.0
```

四個問題的答案，逐條貼原始輸出：

| 問題 | `claude` 2.1.226 | `codex-cli` 0.146.0 |
|---|---|---|
| 非互動的旗標／子命令 | **`-p, --print`** — "Print response and exit (useful for pipes). Note: The workspace trust dialog is skipped when Claude is run in non-interactive mode (via `-p`, or when stdout is not a TTY…)" | **`exec`**（別名 `e`）— "Run Codex non-interactively" |
| 從 stdin 讀 prompt？ | **是。** `--input-format <format>` — "Input format (only works with `--print`): \\"text\\" (default), or \\"stream-json\\""；prompt 是位置參數但 `-p` 明說 for pipes | **是，而且文件明寫。** `[PROMPT]` — "If not provided as an argument (or if `-` is used), **instructions are read from stdin**. If stdin is piped and a prompt is also provided, stdin is appended as a `<stdin>` block" |
| 核准／沙箱選項 | `--permission-mode <mode>`（`acceptEdits`／`auto`／`bypassPermissions`／`manual`／`dontAsk`／`plan`）；另有 `--dangerously-skip-permissions` 與 `--allow-dangerously-skip-permissions` | `-s, --sandbox <read-only｜workspace-write｜danger-full-access>`；另有既有的 `--dangerously-bypass-approvals-and-sandbox`（就是 `launch.go` 的 `SandboxBypassFlag`） |
| 🆕 **即時事件流（2026-08-11 補量）** | **`--output-format stream-json`** — "realtime streaming"；另有 `--input-format stream-json`（**realtime streaming input**）、`--replay-user-messages`（stdin 訊息回吐 stdout 做 ack）、`--include-partial-messages`（token 級 delta）、`--include-hook-events` | **`--json`** — "**Print events to stdout as JSONL**"；另有 `-o/--output-last-message <FILE>`、`--output-schema <FILE>` |
| 🆕 **成本上限** | **`--max-budget-usd <amount>`**（只在 `--print` 下有效） | **沒有對應的旗標** |
| 工作目錄 | `cmd.Dir` 即可；另有 `--add-dir` | `-C, --cd <DIR>` ＋ `--add-dir`；`cmd.Dir` 即可 |

**三個結論**：

1. ✅ **D7 成立。** 兩支都從 stdin 收 prompt，所以
   `runArgs` 的非互動部分是 `claude: ["-p"]`、`codex: ["exec"]`
   （流式旗標見結論 3），**argv 裡沒有一個字串來自呼叫端**。
   SEC-002 的條文逐字不變。
2. ✅ **codex 的沙箱是一個附帶好處。** `exec -s workspace-write` 給出一個
   **範圍就是 run 目錄**的真沙箱——因為裁決讓 run 有了自己的目錄。
   這比互動式 Session 的姿態更緊，而不是更鬆（`04-…md` §5.4）。
3. ✅ **兩支都有為程式設計的事件流，所以存活判定不必靠牆鐘**（2026-08-11 補量）。
   這是本次量測最重要的一項：它讓 `00-…md` D21 成立，
   也讓「用互動模式（PTY）取得即時狀態」這條路**不必走**——
   要的是 stdio 雙向即時，而那個兩支都有，且不需要 PTY。
   `runArgs` 因此是 `claude: ["-p","--output-format","stream-json"]`、
   `codex: ["exec","--json"]`。
4. ⚠️ **成本旗標不對稱**：claude 有 `--max-budget-usd`，codex 沒有。
   所以本期**不接**（M-AR-10），因為接一半會讓人以為兩邊都有保護。
5. ⚠️ **殘留一項：`claude` 的 `--permission-mode` 要用哪個值。**
   既有的 `sandboxBypassArgs` 表**沒有 claude 的條目**（只有 codex），
   所以本期要決定在 run 路徑上加不加、加什麼。`dontAsk` 從名字看是
   「不問、直接拒絕」——那是正確的失敗模式（失敗而不是掛住），
   但**語意要用一次真的 run 確認**，那不是能從 `--help` 讀出來的東西。
   這是 `AR-07` 的第一件事。

**探測（`RunCapable`）留著，但角色變了**：從「發現旗標是什麼」變成
**「第三方 CLI 改了介面時不要靜默壞掉」**（`00-…md` D8）。
探不到就 `runtimes: []`，doctor 印出原因。

### 1.2 M11 — 一個真實 repo 的首次 clone 與後續 worktree 各要多久 🆕 **移到本期**

原本是 V2.3 開工前（`research/02/10` §5）。裁決把 clone 提前，所以它現在擋 `AR-07b`。

| 量什麼 | 答案會改變什麼 |
|---|---|
| Traqora 的 `git clone --mirror` 耗時與大小 | mirror 策略成不成立；`runner.run_quota_bytes` 的量級 |
| 之後每次 `git worktree add` 的耗時 | run 的啟動延遲可不可接受；Run 詳情頁的 `checked_out` 那一段要不要顯示進度 |
| `git remote update --prune` 的耗時 | mirror 要不要有背景更新，還是每次 run 前更新 |
| **淺 clone（`--depth 1`）與 mirror 的比較** | 若 mirror 的優勢在小 repo 上不明顯，**先做淺 clone 更簡單**（少一個要清理的東西） |

最後一列是本計畫加的：`research/02/01` D19 規則 4 直接寫了「用 mirror」，
但那是一個**假設 repo 很大**的結論。Traqora 不大，而
**一個不需要的快取層是一個要清理、要處理鎖競爭、要處理損壞的東西**。
量完再決定。

#### 已量（2026-08-11）✅ **但不是量在 Traqora 上**

工具：`scripts/ar/measure_clone.py`。原始資料：`artifacts/ar/local/measurements/m11-m12.json`
（本機 `file://`）與 `m11-network.json`（真的走網路）。
**這台機器上沒有 Traqora 的 clone，而猜它的 URL 不是一件該做的事**——
所以量的是手上真的有的三個 repo，其中 `cliora` 自己的量級與 Traqora 相當。
**Traqora 的數字要在有 clone 的機器上補一次**，但下面那個結論不太可能被它推翻。

**走網路（GitHub，`git@`／`https`）**，每項 3 次取中位數：

| repo | mirror clone | mirror 大小 | `remote update` 空跑 | `worktree add` | 淺 clone | 淺 clone 大小 |
|---|---|---|---|---|---|---|
| cliora | 4.17 s | 4.1 MB | **2.40 s** | 0.065 s | 3.97 s | 18.0 MB |
| Monstrare | 0.96 s | 0.3 MB | **0.55 s** | 0.007 s | 0.99 s | 0.7 MB |

**每次 run 的成本**：mirror 路線 ＝ 空跑 update ＋ worktree ＝ **2.47 s**（cliora）；
淺 clone 路線 ＝ **3.97 s**。**mirror 每次 run 只省 1.5 秒**，
而它要 2.8 次 run 才把自己第一次 clone 的 4.17 s 賺回來。

**這一列是本次量測最重要的一個發現**：mirror 的成本幾乎全在
`git remote update --prune` 的**空跑**上（cliora 2.40 s，Monstrare 0.55 s）
——那是一次網路往返，與 repo 大小幾乎無關。`worktree add` 本身只有 65 ms。
換句話說，**mirror 省下的不是「取得物件」而是「取得它已經有的物件」**，
而在這個量級的 repo 上，那兩者差 1.5 秒。

**判讀（給 `AR-07b` 的建議，不是裁決）**：在 Traqora 這個量級上，
**淺 clone 就夠了，而 mirror 是一個不需要的快取層**——它多帶來的是鎖競爭、
損壞處理、30 天清理與 `mirrors/` 這一整層目錄，換 1.5 秒。
ADR 0031 的 Alternatives 表已經把這一列寫成「不是否決，是待量測」，
**現在量完了，而答案偏向淺 clone**。
兩件事會翻轉它：① Traqora 實測比 cliora 大一個數量級以上；
② `run` 的頻率高到「每次省 1.5 秒」變得重要（那要 M-AR-7 的命中率）。
**若採淺 clone，`04b-…md` §2 的目錄樹要拿掉 `mirrors/`，§4.2 的第三列（mirror 30 天）
也隨之消失**——這正是計畫說的「改了就要改 daemon 的目錄配置」。

**本機 `file://` 的對照**（同一支腳本，`m11-m12.json`）：三個 repo 的
mirror／worktree／淺 clone 全部在 0.4 秒以下，`remote update` 空跑只有 7 ms。
**把它單獨拿來看會得到相反的結論**，所以它在這裡的用途只有一個：
證明上表那 2.40 s 是網路往返而不是磁碟。

### 1.3 M12 — run 目錄的典型大小 🆕 **移到本期**

| 量什麼 | 答案會改變什麼 |
|---|---|
| 一次典型 run 結束時 `<run>/` 的大小 | `runner.run_quota_bytes` 預設值 |
| 3 個並行需要多少磁碟（含 mirror） | `runner.total_quota_bytes` 預設值、runbook 的機器規格建議 |
| `node_modules` 之類的建置產物佔多少 | 配額的量級是 GB 還是 MB——**差一個數量級** |

**沒有這兩個數字就不能設配額，而沒有配額的 run 目錄會吃掉整台機器的磁碟**
（`00-…md` §5 的風險表）。這是它們從 V2.3 提前的實質理由，不只是為了對齊階段。

#### 已量（2026-08-11）✅

同一支腳本、同一批原始資料。

| | cliora | parksphere | Monstrare |
|---|---|---|---|
| checkout（`worktree add` 之後的 `repo/`） | **17.2 MB** | 3.5 MB | 0.4 MB |
| 淺 clone 之後的 `repo/`（含 `.git`） | 21.1 MB | 4.8 MB | 0.7 MB |
| 3 個並行（mirror ＋ 3 份 worktree） | 56 MB | 12 MB | 1.5 MB |
| 3 個並行（3 份淺 clone） | 63 MB | 14 MB | 2.1 MB |

**而這不是配額該用的數字。** 同一個 repo 上的建置產物：

| | 大小 |
|---|---|
| `frontend/node_modules` | **370 MB** |
| `backend/.venv` | **182 MB** |

一個跑 `npm ci` 的 run，它的目錄從 17 MB 變成約 390 MB——**22 倍**。
所以 M12 那一列問「量級是 GB 還是 MB」的答案是：
**checkout 是 MB，run 目錄是 GB**，而配額必須照後者設。

**給 `AR-07b` 的建議值（不是裁決）**：

```text
runner.run_quota_bytes    2 GB     ← 一個裝了 node_modules ＋ venv 的 run 約 0.4 GB，
                                      留 5 倍給建置快取、測試產物與一次 npm 的 peak
runner.total_quota_bytes  8 GB     ← 3 個並行 × 2 GB，再留一份給 mirror／暫存
runner.min_free_bytes     512 MB   ← 沿用 filesystem.upload 既有水位（config.go:226），
                                      理由是同一顆磁碟（04b-…md §4.1）
```

**這三個值明確標成「建議」**：它們是從一個 repo 的建置產物外推的，
而外推的倍率（5×）是判斷不是量測。上線後由 M-AR-7 與實際的 `RUN_DISK_QUOTA` 次數修正。

### 1.4 M-AR-2 — 一次典型 run 的 log 產生速率

決定 `00-…md` D3 的兩個常數（chunk 32 KiB、聚合窗 2 秒）與
`CLIORA_RUN_LOG_MAX_BYTES` 預設 5 MB 是否合理。

用 `daemon/cmd/fakecli` 的一個只吐輸出的變體，量三檔速率
（1 KB/s、100 KB/s、1 MB/s）下的三個數字：

| 量 | 影響 |
|---|---|
| 每秒訊框數 | 分塊器的待送佇列上限（預設 32） |
| Central 的 DB 寫入次數 | 聚合窗的長度 |
| 🆕 **JSONL 的體積相對純文字的倍數** | `CLIORA_RUN_LOG_MAX_BYTES` 的 5 MB 預設要用這個數字複查（D21 之後 log 是事件不是文字） |
| **同一個 node 上互動終端的 echo 延遲** | **出口條件 24**。要對照 `AR-00` 的 `terminal-latency.json` |

第三欄是重點：它是「run log 把互動終端的延遲賠進去」那條風險的直接證據。

### 1.5 🆕 M-AR-9 — 事件之間的實際間隔分布（校準 idle timeout）

**這是 D21 唯一一個「不量就只能猜」的常數。** `runner.idle_timeout_seconds` 建議 300 秒，
而那個數字現在只是一個直覺。

在真的 run 上量 JSONL 事件的**間隔**分布，特別是尾巴：

| 量什麼 | 答案會改變什麼 |
|---|---|
| 事件間隔的 p50／p95／**p99.9** | `idle_timeout_seconds`。**要看的是尾巴不是中位數**——誤殺發生在尾巴 |
| 最長的合法間隔出現在什麼動作上 | 若是「跑一個長測試」，那 tool-call 粒度就不夠，要考慮 `--include-partial-messages` 或讓 CLI 的 hook 事件補一個心跳 |
| 兩支 CLI 的分布是否不同 | `idle_timeout_seconds` 要不要 per-runtime |

**在量到之前不要把它調小。** 誤殺一個正在工作的 Agent 比多等五分鐘糟得多——
而且它會重排，所以誤殺一次通常是誤殺三次。

#### 部分已量（2026-08-11）◐ **尾巴沒量到，而沒量到的原因本身是一個發現**

工具：`scripts/ar/measure_event_intervals.py`（用 M-AR-1 那兩張 argv 表逐字）。
原始資料：`artifacts/ar/local/measurements/m-ar-9-*.json`，每份都含逐事件的
`at_seconds`／`gap_seconds`／`label` 時間軸。

| run | argv | 事件數 | 牆鐘 | gap p50 | gap p95 | gap max |
|---|---|---|---|---|---|---|
| claude，讀四個檔案並解釋 | `-p --output-format stream-json --verbose` | 12 | 21.2 s | 0.43 s | 6.49 s | **6.49 s** |
| codex，同一個提示 | `exec --json` | 9 | 30.2 s | 1.33 s | 13.75 s | **13.75 s** |
| claude，跑 `go test ./...` | 同上 | 20 | 19.6 s | 0.69 s | 3.02 s | 3.38 s |

**第三列沒有量到它要量的東西**：`Bash` 工具被環境的權限政策擋掉
（事件流裡是 `system/permission_denied`），所以那個 run 從來沒有真的跑測試。
要量到長 tool call 的尾巴，需要 `--permission-mode` 的其中一個值，
而**這個 session 的執行環境不允許啟動一個帶那個旗標的子行程**。
**尾巴要在一台可以真的無人值守執行的機器上補量。**

**但這三個 run 已經回答了兩件本來要靠猜的事：**

1. 🆕 **`claude -p` 在預設權限下會擋掉 `Bash`，而 run 不會失敗——它會照樣給一個答案。**
   第三個 run 的結局是 `result/success`，內容是一份它沒有執行過測試就寫出來的報告。
   **這是一個比逾時嚴重得多的失敗模式**：一個「成功」的 run 交出一份沒有根據的結論。
   所以 `04-…md` §5.4 那個殘留問題（`--permission-mode` 用哪個值）
   **不是一個調校問題而是一個正確性問題**——`BuildRunCommand` 必須帶一個值，
   而且 `RunCapable` 的探測應該連同它一起驗。`--help` 列出的選項是
   `acceptEdits`／`auto`／`bypassPermissions`／`manual`／`dontAsk`／`plan`。
   （`Read` 類工具在預設權限下**可以**執行——第一個 run 的時間軸上有兩次 `tool:Read`。）

2. 🆕 **兩支 CLI 的事件粒度不同，而差別正好落在 idle timer 最在意的地方。**
   `claude` 在思考時會持續吐 `system/thinking_tokens`（上表第一個 run 裡間隔 1.4–1.5 s），
   所以「模型在想」這一段是**看得見的**；`codex` 只在 `item.completed` 時才出一個事件，
   一次工具呼叫從開始到結束之間**完全安靜**（上表 13.75 s 那一格就是這樣來的）。
   推論：**idle timeout 必須大於「最長的單一工具呼叫」，而不是「最長的思考」**，
   而在 codex 這條路徑上這兩者是同一件事的機率更低。
   `idle_timeout_seconds` 若要 per-runtime，理由就是這一條——但**在尾巴量到之前不要拆**，
   一個共用的、夠大的值比兩個猜出來的值安全。

**對 `runner.idle_timeout_seconds = 300` 的判讀**：目前量到的最大合法間隔是 13.75 s，
離 300 s 還有 20 倍餘裕，**所以 300 s 沒有被這批資料否定**；
但這批資料裡沒有任何一個長工具呼叫，而那正是尾巴的來源。
**維持 300 s，並在 `AR-07` 的第一次真實 run 上補量**（那次 run 本來就要跑測試）。

### 1.6 M8-b — sidebar 在多一列之後夠不夠（不擋任何票，但改完就不容易補）

M8 在 V2.0 量過。本期加一項（Agents），**要重跑一次**而不是假設它還夠
（`research/02/09` §3、`07-…md` §1）。三個角色 × 兩個旗標組合各一張截圖。

## 2. 上線後統計

### M10 — run log 的實際體積（規劃既有）

> 一次典型 run 的 log 有多大？100 個 run 之後 `run_logs` 多大？

**影響**：是否要改物件儲存。本期的決定是**先進 PostgreSQL**（簡單、可查、
與 audit 同一套備份）。**先量再改。**

門檻先寫下來，否則「太大了」會變成一個沒有依據的爭論：
**`run_logs` 佔 `pg_dump` 總量 > 30%，或單月成長 > 5 GB。**

### M16 — 一張卡實際會累積多少產物、多大（規劃既有）

同一個門檻規則。另外量三件本期特有的：

- **重複上傳的比例**（用 `task_artifacts.sha256` 統計）。高於 30% 才值得做內容定址去重
  ——`02-…md` §2.6 明寫 `sha256` **不是**為了去重而存的，這個數字是那個決定的複查。
- **`content_type` 的分布**。`application/octet-stream` 佔比高代表白名單太窄。
- 🆕 **`git diff` 產物的大小分布**（D20）。若中位數就很大，
  那條「附成產物」的規則要加一個大小上限並改成「只附 `--stat`」。

### M13 — `waiting_for_input` 的實際等待時間分布（規劃既有）

> 24h 逾時是否合理；Agent 是不是問太多。

另外量：**`ask` 被擋下（已經有一個問題在等）的次數**。
高的話代表 D28 §6「一次一個問題」與 Agent 的實際行為衝突，
那是情境包要改的訊號而不是規則要放寬的訊號。

### M4 — 一張卡實際會有幾次 run（規劃既有，本期才有資料）

`task_runs.seq` 實際會長到多少？**影響** `CLIORA_RUN_MAX_ATTEMPTS = 3` 是否合理。

### M5 — Agent 提交的資料有多少比例不合 schema（規劃既有）

本期第一次有無人值守的 Agent 在打 API，所以這個數字第一次有意義。
量 `cliora task update`／`say`／`ask`／`attach` 四個命令的 4xx 比例。
**與 M2 合看決定 MCP 做不做**（`research/02/01` D11 的三格規則）。

### M9 — 平台不可用的實際頻率與時長（規劃既有，V2.1 起持續）

本期新增一個面向：**平台不可用對 run 的影響與對 Session 的影響不同**。
Session 裡的 Agent 照常工作（D14）；一個進行中的 run 會因為租約續租不到
而在 Central 恢復後被標成 `lost` 並重排——**即使那個 run 其實跑完了**。

🆕 **裁決讓這件事的代價變高了**：重排意味著**重新 clone 一次**。
若發生率不低，處置是讓 runner 在重連後主動回報進行中的 run
（一個 `runner.register` 的欄位），而不是延長租約。

## 3. 本期新增、上線後觀察

### M-AR-3 — 「派給 Agent」與「我自己來」的實際比例

**影響**：D26（兩條路徑並存）的假設。若幾乎沒有人用「派給 Agent」，
那是 V2.3 值不值得做的第一個訊號——與 M14 對 V2.5 的作用相同。

### M-AR-4 — `run.decline` 的實際發生率與原因分布

**影響**：`03-…md` §2 的 60 秒冷卻是否合理，以及「滿了就不 poll」的背壓是否有效。
🆕 裁決之後 decline 多了一個原因（**磁碟配額**），要能分開統計——
「忙」與「滿」的處置完全不同。

### M-AR-5 — 資格查詢的四個條件各自擋掉多少卡

在 poll 路徑上取樣記錄「候選集合為空」時是哪一條先不成立。

**影響**：它直接回答使用者一定會問的「為什麼我的卡沒有人領」。
🆕 裁決之後條件少了兩條，所以這個分布會集中在
「卡片不在 `ready`」與「相依未滿足」——那兩個是**看板上看得到**的狀態，
所以若佔比高，處置是在卡片上顯示原因而不是改規則。

### M-AR-6 🆕 — clone 失敗的原因分布

`RUN_SOURCE_UNAVAILABLE` 的三種 `details`（認證失敗／host 不允許／ref 不存在）各佔多少。

**影響**：**這是「用 node 上既有 git 憑證」這個作法的成本量測**（`04b-…md` §5.4）。
若「認證失敗」佔絕大多數，代表這個作法在實務上不可用，
而那會把 V2.3 的機密下放從「下一期」變成「必須先做」。

> 原本這一項是「run 在使用者 workspace 上造成的實際變更量」。
> **裁決把那個問題消滅了**（run 不碰 workspace），所以編號讓給這一項。

### M-AR-8 🆕 — Agent 實際推了多少東西，推到哪裡

第二次裁決（不擋 Agent push）把阻止換成了可觀測性，**而可觀測性的價值取決於有人看它**。
從 run 摘要的兩行統計：有多少比例的 run 結束時未推送 commit 數為 0（＝可能推了）、
`git remote -v` 出現過哪些 host。

**影響**：三件事。
① 若比例很高，代表「Agent 自己交付分支」是實際發生的主要出口，
那 V2.4 的 `delivery: branch` 應該把它**正規化**（平台記錄 `delivery_ref`）而不是另做一套；
② 若出現過登記 repository 以外的 host，那是一個要看一眼的訊號
（不是違規——沙箱內是自由的——但值得知道）；
③ 它是紅線 5「每一種出口都落在人看過才生效的地方」在本期的**唯一實證**。

### M-AR-10 🆕 — 一次 run 實際花多少 token／錢

**本期沒有處置，只有一個數字。** 無人值守的 Agent 燒 token 是一個**沒有人提過的風險**，
而它的旋鈕不對稱：`claude --max-budget-usd` 存在（只在 `--print` 下有效），
**codex 沒有對應的旗標**。

**影響**：若一次典型 run 的成本高到會被注意，那 V2.3 要處理它，
而處理方式不會是「只給 claude 加上限」——那會讓人以為兩邊都有保護。
可能的形狀是卡片層的預算宣告 ＋ 兩支各自的落地（claude 用旗標，codex 用……要查）。
**先量再說。**

### M-AR-7 🆕 — mirror 的實際命中率與磁碟佔用

同一個 repo 被幾個 Project／幾張卡共用？mirror 目錄的總大小成長曲線？

**影響**：M11 若選了 mirror，這是它的事後複查。命中率低（例如每個 Project 一個 repo，
而 Project 之間不共用）意味著 mirror 只是多了一層要清理的東西，
那時該退回淺 clone——**而退回要在資料說話之後，不是在感覺之後**。
