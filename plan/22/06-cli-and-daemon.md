# 06 — CLI 與 daemon（`RQ-09`，agentd 0.12.0）

**wire 零變更、runtime 零變更、workspace 零變更。** 本期在 daemon 裡動的只有
`daemon/internal/cli/`——三個新子命令與一道本機檢查。

## 1. 為什麼 contract 不動，而 agentd 要進版

| | 動不動 | 為什麼 |
|---|---|---|
| `contracts/v1/` | **零位元組** | 新增的東西全部在 HTTP 那一側（`/api/cli/runs/*`）。`run.offer` 逐欄位與 V2.4 相同，只有 `spec.context` 的**字串內容**不同——而字串內容不受 `DisallowUnknownFields` 管 |
| `daemon/internal/{runtime,runner,workspace,gitfetch}` | **零位元組** | 釐清與拆解 run 走的是完全相同的生命週期。差別全在 Central 送什麼 context 與 Agent 打哪些 HTTP |
| `daemon/internal/cli/` | 三個子命令 ＋ 一道檢查 | §2 |
| `daemon/cmd/agentd/main.go` | `version = "0.12.0-dev"` | CLI 是 agentd 的一部分 |

**「舊 node 會怎樣」要寫進 release note**：
一個還在 0.11.0 的 node 會正常領取釐清卡、正常執行、正常回報，
但 Agent 呼叫 `cliora spec submit` 會得到 cobra 的
`unknown command "spec"` ＋ 非零 exit code。

**這個失敗是可見的**（訊息 ＋ exit code ＋ 進 run log），
不是 V2.4 README 易錯 1 那種靜默丟棄。所以本期不需要 `features` 宣告的第二輪
——但 `03-…md` §2.2 的情境包第 6 行要加一句：
「這個指令不存在的話，把規格內容用 `cliora task say` 貼上來並註明是規格草稿」。
**一條可執行的降級路徑，而不是一句道歉。**

## 2. 三個新子命令

全部沿用既有形狀：**JSON 檔而不是 argv**（`readJSONFile` 的註解已經寫了理由：
SEC-002 對 argv 的一般性顧慮 ＋ `ps` 輸出）。

### 2.1 `cliora spec submit <file>`

```text
Use:   "submit <file>"
Short: "Submit a version of this requirement's specification (JSON)"
```

JSON 的形狀就是 `POST /api/cli/runs/spec` 的 body（`03-…md` §4.1）。

成功訊息要說兩件事，第二件比第一件重要：

```text
已送出第 3 版規格草稿（還有 2 個未解決的問題）。
規格由人核准，你核准不了——把未解決的問題留在 open_questions 裡就好。
```

第二句與 `verify report` 的成功訊息同一個用意
（`command.go` 的註解：「Not trying is cheaper than being refused」）：
Agent 看得到 `requirements.status`，所以要**先告訴它不要試**。

### 2.2 `cliora task ask` 加一道本機檢查

在送出之前先打 `GET /api/cli/runs/messages?since=…`，
若本地判定已有未答問題，**本機就拒絕**：

```text
上一個問題還沒有答案：「報表匯出是指 CSV 還是 PDF？」
要問新的：把兩個問題合併成一個，或先 `cliora task messages` 看看有沒有回覆。
```

**這是提示不是閘門**（閘門在伺服器，`03-…md` §3.1）。
它值得做的理由是省一趟往返，以及**訊息在本機比較完整**——
伺服器的 409 只能給一段 JSON，這裡可以直接把上一則問題印出來。

⚠️ **本機判定與伺服器判定必須用同一條規則**，否則會出現
「本機說可以、伺服器說不行」——那比只有一邊檢查更難懂。
所以本機那條也是「找最後一則 `question`，看它之後有沒有 `author_kind='user'`」，
**而不是「距離上次提問是否超過 N 分鐘」**（頻率限制是一個不同的規則，本期不做）。

### 2.3 `cliora proposal submit <file>`

```text
Use:   "submit <file>"
Short: "Submit a decomposition proposal (JSON: {epics, user_stories, tasks})"
```

成功訊息：

```text
已送出提案 #2：3 個 Epic、7 個 User Story、22 張 Task。
人會逐張勾選；缺 DoR 項目的會落在「待辦」而不是「就緒」。
```

**印出三個數字是刻意的。** 一個 Agent 拆出 38 張卡時，
這行輸出會出現在 run log 裡，而那是**在人打開接受介面之前**最早看得到規模的地方。

### 2.4 `cliora spec template`

印出 `../Monstrare/ai/templates/feature-spec.md` 的九節骨架成 JSON，
**離線可用，不打任何 HTTP**。

```bash
cliora spec template > spec.json   # 填完再 cliora spec submit spec.json
```

**這個子命令的存在是為了不把 2.5 KB 的範本塞進情境包**（`03-…md` §2.2 第 12 段）。
範本內容編譯進 binary（Go 的 `embed`），不從檔案系統讀——
run 目錄裡沒有 Monstrare。

**授權標註**：範本改寫自 Monstrare（MIT），
出處寫在 `daemon/internal/cli/` 的檔頭與 ADR 0034。

### 2.5 `cliora requirement show`

```text
GET /api/cli/runs/requirement   ← run 路由的第十條
```

回這張卡所屬需求的 `raw_text`、`status`、最新一版規格與 `open_questions`。

**為什麼需要它，而情境包裡已經有了**：情境包是 dispatch 當下的快照。
一個跑了四十分鐘、問了三輪的釐清 run，**它自己送出去的第 2 版規格不在情境包裡**。
沒有這條路由，Agent 要靠自己記得送過什麼——而它是無狀態地被叫起來的。

回應**不含** `approved_by`／`approved_at` 以外的任何使用者身分（沿用 `redact_actors` 的姿態）。

## 3. 三個都要有的離線行為

沿用 `RunOfflineMessage`（`cli.go:63`）：平台連不上時失敗、非零 exit code、
訊息說明「你的工作不受影響，恢復連線後再執行一次」。

**但 `spec submit` 多一句**：

```text
規格內容還在你的 spec.json 裡，沒有遺失。恢復連線後再執行一次同一個檔案。
```

理由是這三個子命令的 payload 是 Agent 花了時間產生的東西
（`say`／`ask` 的 payload 是一句話，重打不痛）。
**明說檔案還在，Agent 才不會重新產生一份不一樣的。**

## 4. 測試

| 層 | 覆蓋 | 條數 |
|---|---|---|
| CLI 單元 | 三個新子命令各一條成功路徑；`spec template` 離線可用；`readJSONFile` 對壞 JSON 的行為 | 6 |
| CLI 單元 | `ask` 的本機檢查：有未答問題時拒絕、沒有時放行、**與伺服器規則一致**（同一組 fixture 餵兩邊） | 3 |
| CLI 單元 | 三個子命令的離線訊息與 exit code | 3 |
| daemon 全域 | `daemon/internal/{runtime,runner,workspace,gitfetch}` 對 `RQ-00` 基線**零 diff**（`GATE-RQ-TOUCH-LIST`） | 1 gate |

**「與伺服器規則一致」那三條用同一組 fixture 餵兩邊**，
是本節唯一一個非顯而易見的測試設計。
兩份各自正確但不一致的實作，症狀是「有時候可以問有時候不行」，
而那會被當成 flaky 而不是 bug。
