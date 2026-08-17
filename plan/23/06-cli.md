# 06 — CLI（`CV-08`）

`agentd` **0.12.0 → 0.13.0**。改動全部在 `daemon/internal/cli/`，
節點半邊零 diff（[`05`](./05-context-pack-and-runner.md) §1）。

## 1. 現況

`command.go` 的 `task` 子命令樹：

```text
cliora task list                     command.go:81
cliora task get <ref>                command.go:102
cliora task update <ref>             command.go:125
cliora task say <text>               command.go:162
cliora task ask <text>               command.go:182   ← 不等待，印一行提示
cliora task messages [--since <ts>]  command.go:217   ← 時間戳分頁
cliora task attach <file>            command.go:242
```

`cli.go` 的 client：`PostMessage`（429）、`PendingQuestion`（540）、`ListMessages`（561）。

## 2. 改動

### 2.1 `messages --after <seq>`

```text
cliora task messages [--after <seq>] [--limit <n>] [--json]
cliora task messages [--since <ts>]        # deprecated，D64
```

- `--after` 與 `--since` 同時給 → 本地拒絕（`ExitRefused`），不送請求。
- `--since` 印一行 stderr：
  `「--since 會在下一版移除，改用 --after <seq>；每則訊息的 seq 在 --json 輸出裡。」`
- 純文字輸出加上 seq，因為那是下一次 `--after` 要用的值：

```text
[  12] 14:32 你: 用 SAML 2.0，IdP 是 Okta
[  13] 14:33 agent: 收到。那 SP metadata 要放在哪個路徑？
```

- `--json` 輸出從陣列改成 `MessagePageDTO` 的形狀
  （`items` / `next_after_seq` / `has_more`）。**這是一個破壞性變更**，
  與 [`03`](./03-conversation-api.md) §9 是同一個決定的兩端。

### 2.2 `wait`

```text
cliora task wait --after <seq> [--timeout <sec>]     預設 30，上限 120
```

長輪詢：有新訊息就印出並 `exit 0`；逾時 `exit 4` 且**不印錯誤**
（逾時不是錯誤，是「還沒有」）。

**上限 120 秒寫死在 CLI 裡，不是只寫在文件裡。**

```go
if timeout > 120 {
    return exit(cmd, ExitRefused, errors.New(
        "--timeout 上限是 120 秒。要等更久，就結束這個 process——"+
        "人回覆之後平台會用新的一輪把你叫回來，對話不會遺失。"))
}
```

那段錯誤訊息是本期產品模型唯一一次直接對 Agent 說話的地方。
它要說的不是「不行」，是「有更好的做法，而那個做法是設計出來的」。

實作：**client 側輪詢**，間隔 2 秒，不是伺服器長連線。理由：
Central 目前沒有長輪詢的基礎設施，而一個 120 秒的 HTTP 連線會佔住一個
worker；60 次 `GET ?after_seq=` 對 `ix_task_messages_task_seq` 是索引掃描，便宜得多。

### 2.3 `say --reply-to`

```text
cliora task say [--reply-to <message_id>] [--kind comment|answer] <text>
```

- `--kind` 預設 `comment`（既有預設是 `message`，讀取映射後是同一個東西）。
- `--kind answer` ＋ `--reply-to` 指向一個 question → 走 answer 路徑。
- **Agent 不能用 `--kind decision`**：本地就拒絕，並說明
  「decision 是人類動作」——server 那邊也會回 `403 AGENT_CANNOT_DECIDE`，
  本地擋只是為了省一次往返並給出更好的訊息。與 `ask` 的
  `PendingQuestion()` 本地提示是同一個模式（`cli.go:530-539` 的 docstring
  已經說明了「本地是提示，server 是閘門」）。

### 2.4 `propose-spec`

```text
cliora task propose-spec <file|->
```

寫一則 `kind='proposal'` 的訊息，body 是檔案內容。

**與既有的 `cliora spec submit` 是兩件事**，這一點要在 help 文字裡說清楚：

| | `spec submit` | `task propose-spec` |
|---|---|---|
| 寫到哪 | `feature_specs` 表（結構化，九節） | `task_messages`（一則訊息） |
| 用在哪 | 釐清卡對某個 **requirement** 提規格 | 任何卡片對**這張卡**提方案 |
| 誰接受 | `requirements` 的核准流程 | 卡片上的 `decision` 訊息 |
| 既有 | ✅ `command.go:391` | 🆕 |

**不合併它們。** `spec submit` 有 schema 驗證與九節結構，
`propose-spec` 是自由文字的方案提議。合併會讓其中一個變成另一個的退化形式。

### 2.5 `ask` 的說明文字

`ask` 的行為**不變**（不等待），但送出後印的那行提示要改：

```text
現在：「已提問。用 `cliora task messages` 拉取回覆；24 小時無人回覆這張卡會退回「阻塞」。」

之後：「已提問。你可以：
        ① 結束這個 process——人回覆之後平台會用新的一輪把你叫回來（建議）
        ② `cliora task wait --after <seq>` 等最多 120 秒
        ③ `cliora task messages --after <seq>` 自己輪詢
      24 小時無人回覆，這張卡會退回「阻塞」。」
```

**①排在最前面**，與 `render_run_context` 把「怎麼回報」放在第一節是同一個判斷
（`runs.py:1487`）：最可能出錯的不是 Agent 誤解任務，是它不知道有這個選項。

## 3. `client` 的改動（`cli.go`）

| 方法 | 改動 |
|---|---|
| `ListMessages(since string)` | → `ListMessages(after int, since string, limit int) (MessagePage, ...)` |
| `PendingQuestion()` | 內部改查 `/questions?state=open`；**回傳型別與行為不變** |
| `PostMessage(body, kind)` | → `PostMessage(body, kind, replyTo string, idempotencyKey string)` |
| 🆕 `WaitMessages(after int, timeout time.Duration)` | 2 秒輪詢 |
| 🆕 `ProposeSpec(body string)` | `kind='proposal'` |

**每個寫入呼叫都帶 idempotency key。** key 由 CLI 產生：
`sha256(run_id + kind + body)[:32]`。這讓「網路斷了，Agent 重跑同一個指令」
不會產生第二則訊息——**而那正是 Agent 在不穩定網路上會做的事**。

> key 用內容雜湊而不是 UUID，是因為 Agent 的重試通常是**重跑整個指令**
> 而不是重送同一個 HTTP 請求。UUID 每次都不同，等於沒有冪等。

## 4. 平台連不上時的行為（`FR-VERIFY-004`，不變）

既有規則沿用，一個字不改：

- **直接失敗，不佇列。**
- 錯誤訊息含「Session 可繼續工作」。
- `context show` 免連線。
- 非零 exit code，但**不中斷 Agent**。

`wait` 的逾時（`exit 4`）與連線失敗（`ExitRefused`）**用不同的 exit code**，
因為 Agent 對兩者的正確反應不同：前者是「還沒有回覆」，後者是「平台連不上」。

## 5. 測試（Go）

| 測試 | 斷言 |
|---|---|
| `--after` 與 `--since` 同時給 | 本地拒絕，不發請求 |
| `--since` 印 deprecation | stderr 含提示，stdout 不受污染 |
| `wait --timeout 300` | 本地拒絕，訊息含「結束這個 process」 |
| `wait` 逾時 | `exit 4`，stderr 為空 |
| `wait` 收到訊息 | `exit 0`，印出訊息 |
| `say --kind decision` | 本地拒絕 |
| `PostMessage` 的 idempotency key | 同 body 同 kind → 同 key；不同 body → 不同 key |
| 純文字輸出含 seq | 格式比對 |
| `--json` 的新形狀 | 與 `MessagePageDTO` 對齊 |
| 平台連不上 | 訊息含「Session 可繼續工作」（既有測試，回歸） |
