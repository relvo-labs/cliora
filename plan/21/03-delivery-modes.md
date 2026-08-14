# 03 — 五種交付模式與 daemon 半邊（`DV-01` 的實作面／`DV-03`／`DV-04`）

本檔回答：五種 `delivery` 在**這個 repo 的現況**上各自要改哪幾行，
contract 要動哪一半，以及 daemon 0.11.0 的三塊工作。

## 1. 五種模式，逐一對照現況

| `delivery` | Central 現況 | daemon 現況 | 本期要做的 |
|---|---|---|---|
| `none` | ✅ 可 dispatch | ✅ 不推 | 摘要文案與 `artifact` 共用述詞 |
| `artifact` | ✅ 可 dispatch | ◐ 附 diff，**但摘要少一句**（`supervisor.go:316`） | 共用述詞 ＋ **Central 端數產物**（D8） |
| `branch` | ✅ V2.3 主路徑 | ✅ push ＋ 五條硬約束 | `pushed_branch` 上報 |
| `pull_request` | ❌ dispatch 409（`runs.py:353`） | ❌ 不認得這個值（`codec.go:961`） | **Central 開 PR，wire 送 `branch`**（D2） |
| `existing_pr` | ❌ dispatch 409 | ❌ 同上 | 同上 ＋ **命名空間限制**（D7） |

### 1.1 `artifact` 不是「附件功能」

`research/02/06` DV-01 的那句話值得抄進 ADR：
**任何 run 隨時都能附產物；`delivery: artifact` 只是宣告「這張卡的完成證據就是產物」。**
一張 `pull_request` 的卡照樣可以在執行中附測試報告與截圖——
**附件是過程證據，delivery 是成果形式。**

實作上這句話落在**兩個不同的地方**，而混在一起是本期最容易犯的分類錯誤：

- 「能不能附」由 `ArtifactService.attach()` 的配額與授權決定，**與 delivery 無關**。
- 「附了沒有」只在 `delivery == "artifact"` 時進入 run 的成敗判定（D8）。

## 2. `pull_request`：wire 上表現為 `branch`（D2）

### 2.1 Central 的三處改動

**① `RunOffer.spec()`（`runs.py:197`）——`delivery` 的線上投影**

```python
# 卡片的意圖有五種，線上只有三種。這不是相容性讓步：daemon 沒有 provider 憑證、
# 開不了 PR，也不必知道分支推上去之後會發生什麼(D1/D2)。
_WIRE_DELIVERY = {
    "none": "none",
    "artifact": "artifact",
    "branch": "branch",
    "pull_request": "branch",
    "existing_pr": "branch",
}
```

放在 `spec()` 裡而不是 dispatch 時寫進 `task_runs`：
**run 的快照要記卡片當時的真實意圖**，否則 PR 建立的背景工作讀不到它。
（run 的四個快照欄位是「執行時的事實」，而 delivery 的意圖屬於卡片——
所以背景工作讀 `task.delivery`，並用 `run.id` 定位。）

⚠️ **`GATE-DV-DELIVERY-COVERAGE` 對這張表斷言**：
`DELIVERIES` 的每一個值都要在 `_WIRE_DELIVERY`、`run_branch()` 與 Done Gate 三處有分支。
少一個值就是少一種行為，而少的那一種通常是最新加的。

**② `run_branch()`（`runs.py:1064`）——三值處置**

```python
if task.delivery in ("branch", "pull_request"):
    if task.source == "existing_branch":
        return task.base_branch or ""      # dispatch 已驗證在命名空間內
    return f"cliora/{task.card_ref}-{run.seq}"
if task.delivery == "existing_pr":
    return task.base_branch or ""          # dispatch 已驗證(D7)
return ""                                   # none / artifact
```

漏掉 `pull_request` 那一行的後果值得寫下來：offer 不帶 `branch` →
daemon 不建分支 → agent 在 base branch 上工作 → push 階段沒有東西可推 →
摘要說「沒有可推送的提交」。**症狀看起來像 Agent 什麼都沒做**（README 易錯 7）。

**③ `dispatch()`（`runs.py:353`）——`UNSUPPORTED_DELIVERIES` 清空並補三個檢查**

```python
# 這張表現在是空的，而它留著是為了下一種 delivery(D18)。
UNSUPPORTED_DELIVERIES: dict[str, str] = {}
```

新增的三個檢查放在同一個第 ② 步（「卡片的宣告要可滿足」）：

```python
if task.delivery in ("pull_request", "existing_pr"):
    if repository is None or adapter_for(repository.host) is None:
        raise ApiError("TASK_PROVIDER_UNSUPPORTED", …)     # D15
if task.delivery == "pull_request" and not task.target_branch:
    raise ApiError("TASK_PR_TARGET_MISSING", …)
if task.delivery == "existing_pr":
    base = task.base_branch or ""
    if not base.startswith("cliora/"):
        raise ApiError("TASK_EXISTING_PR_OUT_OF_NAMESPACE", …)   # D7
```

⚠️ **順序有一個陷阱**：`TASK_PROVIDER_UNSUPPORTED` 要在第 ③ 步（解析 repository）**之後**才判得了，
但 `TASK_PR_TARGET_MISSING` 在第 ② 步就判得了。
**把兩者都移到第 ③ 步之後**，不要為了「宣告檢查在②」而把一個判得了的檢查往後排——
`dispatch()` 的 docstring 已經寫了那個順序是**為了拒絕的可讀性**而不是為了正確性，
而「你的 repo host 不支援」比「你沒填 target branch」更根本。

### 2.2 `existing_pr` 的範圍，說成一句使用者讀得懂的話

拒絕訊息不要說「不在命名空間內」就結束：

> 「`feature/login` 不在 `cliora/` 命名空間內，而**平台只推得到那裡面**。
> `existing_pr` 只能接續平台自己開的 PR；要接續別人的分支，
> 請改用 `delivery: branch` 並自行合併。」

`06-…md` §4 的 Project Settings 與卡片編輯畫面各有一段同樣的說明。
**這是一個設計決定看起來像 bug 的典型**，所以文案是對策的一部分（`00-…md` §5 風險表最後一列）。

## 3. contract v1.13.0（`DV-03`）

**只在 node→central 方向新增。** 這是本期最值得保護的一個性質（`README.md` 的開頭那一節）。

### 3.1 `run.complete` 新增兩個欄位

```jsonc
"pushed_branch": {
  "$comment": "The branch this run actually pushed, absent when it pushed nothing. **A fact, not an intention**: Central composed the name and could compute it, but only the daemon knows whether the push succeeded — and a PR may only be opened on a branch that is really there (plan/21/02-…md §2.2).",
  "type": "string", "minLength": 1, "maxLength": 255,
  "pattern": "^cliora/[A-Za-z0-9._][A-Za-z0-9._-]*$"
},
"verification": {
  "$comment": "What the daemon ran and what came back. `exit_code` is the real one — this is the whole substance of the `machine_verified` level. Commands come from one of **two** platform-side stores, never from a request payload: the project's settings or the card's own list, and `origin` says which (plan/21/00-…md D4). Declaring one on a card takes `task.approve`, which a run token never holds, so neither source is chosen by the agent being verified. Absent when neither store declared any, which is the default.",
  "type": "array", "maxItems": 16,
  "items": {
    "type": "object", "additionalProperties": false,
    "required": ["name", "origin", "exit_code"],
    "properties": {
      "name":        {"type": "string", "minLength": 1, "maxLength": 128},
      "origin":      {"$comment": "Which store named this command: the project's settings or the card's own list (plan/21/00-…md D4). **Echoed back by the daemon rather than recomputed by Central** — Central could look it up, but a value that travels with the result cannot drift from the command that actually ran when someone edits the settings mid-run. Both are `machine_verified`: neither was chosen by the agent, because declaring one on a card requires `task.approve` and a run token never holds it.", "enum": ["project", "card"]},
      "exit_code":   {"type": "integer", "minimum": -1, "maximum": 255},
      "duration_ms": {"type": "integer", "minimum": 0},
      "output_tail": {"type": "string", "maxLength": 2000}
    }
  }
}
```

`exit_code` 的 `minimum: -1`：**`-1` 保留給「逾時，命令被殺」**。
一個逾時的命令沒有 exit code，而把它記成 `1` 會讓「測試失敗」與「測試沒跑完」
在報告上長得一樣——那是兩件人要做不同事的事。

⚠️ **`run.complete` 的 `result` enum 一個字都不動**（README 易錯 11）：
`delivered_branch_only` 是 **Central** 寫進 `task_runs.result` 的值，
daemon 永遠不知道 PR 開了沒有。

### 3.2 `run.progress` 的 `phase` 新增 `verifying`

排在 `running` 與 `finishing` 之間。
理由與 v1.12.0 加 `authenticating` 的一樣：**「卡在測試上」與「卡在收尾上」是兩件事**，
而 Run 詳情頁不該用猜的。

### 3.3 `runner.register` 新增 `features`（D3）

```jsonc
"features": {
  "$comment": "What this daemon can do that an older one cannot. **Absent means the empty set** — the opposite default from `run_untagged` and `accept_secrets`, and deliberately so: those two are refusal flags (absent = does not refuse), this is a support flag (absent = does not support). A permissive default on a support flag would mean assuming an un-upgraded machine performs a feature it has never heard of. Central only puts feature-gated content into an offer for a node that named the feature (ADR 0029 amendment C).",
  "type": "array", "maxItems": 16, "uniqueItems": true,
  "items": {"enum": ["verification", "evidence"]}
}
```

**enum 而不是自由字串**：一個 feature 名是 Central 與 daemon 之間的約定，
自由字串會讓打錯的名字變成「靜默地不支援」——而那正是本期在修的那種 bug。

### 3.4 `spec` 零新增欄位

**這是一條要寫進 fixtures 的斷言，不只是一個決定。**
新增 invalid fixture：一個帶 `spec.verification` 的 `run.offer`，
斷言它**不合法**。理由寫在 fixture 的 `manifest.json` 註記裡：

> `spec` 的接收端是一個 `DisallowUnknownFields` 的解碼器，而 `run.offer` 的驗證失敗
> 不會產生任何回應。所以往 `spec` 加欄位的代價不是「舊 node 忽略它」，
> 是「舊 node 丟掉整個 offer 而沒有人知道」。要加欄位，先加 feature 宣告。

### 3.5 CHANGELOG

`contracts/CHANGELOG.md` 的 1.13.0 那一節要寫三件事：
新增的三處（都是 node→central）、`spec` 為什麼沒動、
以及**兩個方向的相容性預設相反**這一句（`01-…md` §6.3）。

## 4. daemon 0.11.0（`DV-04`）

三塊，互相獨立。

### 4.1 交付：兩個函式共用一個述詞

現況（`supervisor.go`）：

```go
func ShouldAttachDiff(delivery string, summary Summary) bool {   // :301
    if delivery != "none" && delivery != "artifact" { return false }
    return summary.Dirty && summary.Diff != ""
}
func SummaryText(delivery string, summary Summary) string {      // :314
    if summary.Dirty && delivery == "none" { … }                 // ← 少了 artifact
}
```

改成：

```go
// declaresNoCode reports whether this card said its outcome is not code changes.
// **One predicate, two callers.** The first version wrote the condition twice and the
// two drifted immediately: the diff was attached for `artifact` while the sentence
// explaining it was only produced for `none` — so an artifact card's diff arrived on
// the board with nothing saying why (ADR 0033 §2, honesty rule 1).
func declaresNoCode(delivery string) bool {
    return delivery == "none" || delivery == "artifact"
}
```

**測試的形狀**：一個 table test 走五個 delivery 值 × 兩種 dirty 狀態，
斷言 `ShouldAttachDiff` 與 `SummaryText` 的「有沒有那句話」**永遠一致**。
這條測試的價值不在它現在會不會綠，在於下一次有人加第六種 delivery 時它會紅。

### 4.2 驗證：`allowed_verification_commands` 的切分與執行

**編碼**（D6）：每個元素是 `origin\tname\tcmd\targ1…`，`origin` 是單字元 `p`（project）或 `c`（card）。

**兩個來源的合併規則**（D4）：

```
spec.allowed_verification_commands =
      [p\t… for c in project.verification_commands]      # ≤8，排前面
    + [c\t… for c in task.verification_commands]         # ≤8，排後面
```

**project 的排前面**是刻意的：如果整組逾時（900 秒），
被砍掉的是卡片宣告的那幾條而不是專案的——**專案設定是那個部署對「算完成」的定義**，
而卡片宣告是一張卡的補充。順序在這裡是一個優先權宣告，不是美觀。

預算算式（要寫進註解，因為它決定了 `02-…md` §2.1 的三個上限）：

```
單條上限 256 字元 = origin(1) + tab + name(≤32) + tab + argv 元素們
argv 16 個元素 × 平均 12 字元 + 15 個 tab ≈ 207 → 總計 ≈ 241 < 256 ✅
→ 兩端共用的上限：name ≤32、argv ≤16 個元素、每元素 ≤128 字元。
  兩個來源各 ≤8 條，合計 ≤16 ＝ 既有的 maxItems。
```

**在存檔時算**而不是在組 offer 時算：一條存得下來卻送不出去的驗證命令，
會讓「這個專案的驗證從來沒跑過」變成一個沒有人會去查的靜默事實。
（這與 `plan/20` D2 的訊框大小檢查是同一種病：**量的地方要在人看得到的那一端**。）

⚠️ **兩端各自存檔時各算一次**，因為它們是兩個端點、兩個授權、兩個錯誤訊息。
共用一支驗證器函式，但**不要**合併成「組 offer 時算一次」——那會讓
「是誰讓這張卡送不出去」在兩個來源之間變成一個要查的問題。

**執行**：

```go
// runVerification executes the platform's own checks inside the run directory.
//
// **No shell.** `exec.CommandContext(ctx, argv[0], argv[1:]...)` — the same shape the
// runtime layer uses, and for the same reason SEC-002 gives: a shell string is an
// injection path, and this one would sit on the platform's own storage surface
// (plan/21/00-…md D5).
//
// Runs **after the agent exits and before the summary is taken**, so a command that
// changes the tree (a formatter, a build) is visible in `git status` — that ordering is
// a decision, not an accident: hiding a verification step's own side effects would make
// the evidence disagree with the diff for reasons nobody could see.
```

四個細節，每一個都會被做錯一次：

1. **環境**：與 CLI 子程序**相同的環境**（含 `env` kind 的機密），
   因為測試常常要 `NPM_TOKEN` 才跑得起來。
   ⚠️ **git kind 的機密仍然不進去**（`ChildEnv` 已經在守這件事，ADR 0032 §4）。
   ⚠️ **`origin: card` 的命令拿到的環境與 `origin: project` 的完全相同**，
   而那是對的：兩者都是人宣告的（卡片那邊要 `task.approve`），
   而給它們不同的環境會讓「為什麼這條在專案設定裡跑得起來、搬到卡片上就不行」
   變成一個沒有人答得出來的問題。
2. **輸出**：`output_tail` 只留**最後 2000 字元**，而且**要過 Redactor**——
   一條 `env | grep` 的驗證命令會把機密印進報告，而報告是存進 DB 的。
   ⚠️ Redactor 掛在 `send` 上（V2.3 的 D6），而 `run.complete` 的
   `verification[].output_tail` 是 payload 的一部分，所以它**自動被涵蓋**——
   這正是「包住 `send` 而不是包住 log sink」買到的東西。**加一條測試釘住它。**
3. **逾時**：每條 300 秒、整組 900 秒（`00-…md` §0.3），值在 node 的設定檔。
   逾時 → `exit_code: -1`，**繼續跑下一條**（一條卡住的 lint 不該讓測試結果消失）。
4. **run 的整體時鐘**：驗證發生在 agent 結束之後，而 wall clock（6 小時）仍在跑。
   **驗證的 900 秒要算在裡面**，不另外延長——否則一個接近 6 小時的 run
   會在驗證階段被 wall clock 砍掉，而那時報告已經產生了一半。
   處置：驗證開始前檢查剩餘時間，不足 900 秒就**跳過驗證並回報
   `exit_code: -1` ＋ `name` 加註「時間不足」**，不是靜默跳過。

### 4.3 證據：`Inspect()` 的補齊與 `features` 的上報

`Inspect()`（`supervisor.go:261`）已經有 `Status`、`Remotes`、`UnpushedCommits`、`Diff`。
本期補：

- `diff --stat`（新的 `Fetcher.DiffStat`，與 `Diff` 同一個形狀）。
- **每一個 git 呼叫套 M6 決定的逾時**，逾時的那一項**留空並標記**，
  不是讓整個 `Inspect` 失敗。
- `runnerRegisterPayload`（`run_handlers.go:55`）加 `"features": []string{"verification", "evidence"}`。
  **常數而不是設定值**：它描述的是這個 binary 會什麼，不是這台機器想不想做。
- `agentd doctor` 加一行：報告 `features` 與驗證命令的逾時值。

### 4.4 `run.complete` 的組裝

```go
send("run.complete", map[string]any{
    "result":           result,
    "summary":          summaryText,
    "disk_bytes":       summary.DiskBytes,
    "git_remotes":      summary.Remotes,
    "unpushed_commits": summary.UnpushedCommits,
    "untracked_files":  summary.UntrackedFiles,
    "pushed_branch":    pushedBranch,   // 空字串會被 send 的既有邏輯刪掉？
    "verification":     verificationResults,
})
```

⚠️ **`send` 只對 `summary` 與 `message` 兩個 key 做空字串清除**（`run_handlers.go:220`）。
`pushed_branch` 是新的第三個，**要加進那個清單**——
一個 `"pushed_branch": ""` 會被 contract 的 `minLength: 1` 擋下，
而那代表整個 `run.complete` **靜默消失**、租約到期、卡片被重排。
`plan/18` 的 D2 已經因為同一件事付過一次代價（那次是 `summary`），
而 `GATE-AR-DISPATCH-COVERAGE` 就是為此存在的——**本期要確認它涵蓋新欄位**。

`verification` 是空陣列時也刪掉（contract 上它是 optional，空陣列合法但沒有意義）。

## 5. 驗收

| # | 斷言 | 怎麼驗 |
|---|---|---|
| 1 | 五個 delivery 值在三處都有分支 | `GATE-DV-DELIVERY-COVERAGE` |
| 2 | `ShouldAttachDiff` 與 `SummaryText` 對五值 × 兩狀態一致 | Go table test |
| 3 | 驗證命令不經 shell | `GATE-DV-NO-SHELL`：掃 `daemon/` 不得出現 `"sh", "-c"` 或 `"bash", "-c"` |
| 4 | `output_tail` 過 Redactor | 一條測試：機密值出現在驗證命令的輸出裡，斷言 payload 是 `***` |
| 4b | 兩個來源合併、project 排前面、`origin` 原樣回報 | Go table test ＋ Central 端一條 |
| 5 | 逾時的命令是 `exit_code: -1` 且不影響其他條 | Go test，三條命令中間那條 `sleep` |
| 6 | 剩餘時間不足時跳過並說明 | Go test，wall clock 設成 60 秒 |
| 7 | `pushed_branch` 空值不上線 | Go test ＋ `GATE-AR-DISPATCH-COVERAGE` |
| 8 | `spec` 零新增欄位 | invalid fixture ＋ `GATE-DV-CONTRACT-ADDITIVE` |
| 9 | 0.10.0 的 node 收到本期的 offer 仍能完成 | 用真的 0.10.0 binary 跑一次 `branch` 卡 |
