# 07 — CLI 與 Agent 的引用契約（`KN-09`）

> `agentd` 0.13.1 → **0.14.0**，只動 `internal/cli/`。**節點半邊零 diff**（D87）。

## 1. 四個子命令

```text
cliora knowledge context [--layers 1,2,4] [--json]
cliora knowledge search <詞> [--limit 8] [--type repo_doc,decision] [--json]
cliora knowledge cite <source-id> [--json]
cliora knowledge sync [--dry-run]
```

`knowledge` 掛在 root 底下（與 `task`、`context`、`spec` 平行），
不掛在 `task` 底下——它的範圍是 project 而不是卡片。

### 1.1 `context`

預設輸出就是那份 markdown（直接可讀），`--json` 給 manifest。
**這是本期最重要的一個命令**，因為 D78 把完整 pack 放在它後面。

三個設計細節：

| 細節 | 為什麼 |
|---|---|
| 沒有 `--save` | Agent 有 shell，要存自己會存。多一個旗標多一個「檔案留在 run 目錄裡」的路徑 |
| Central 連不上時的訊息 | 沿用既有 `RunOfflineMessage` 的形狀：「平台連不上，**你的工作不受影響**——繼續做」。knowledge 不是必要條件 |
| `--layers` 可以只要 4 | 續跑時 Agent 已經有層 1–3，只要新的檢索結果。省它自己的上下文 |

### 1.2 `search`

```text
$ cliora knowledge search 租約過期
[S1] accepted   ADR 0029 §5 租約與重排                 2026-07-02  spec:41
[S2] canonical  daemon/internal/runner/supervisor.go   139f143     repo_doc
[S3] discussion TK-142 「這裡的 24 小時是哪來的」      seq:18      conversation
（只做模糊比對：單字查詢）        ← 只在退回 trigram 時出現（05 §1.2）
```

`limit` 伺服器端上限 8（[`05`](./05-retrieval-and-search.md) §5.2）。
**不在提示裡限制，在伺服器限制**——一個回 50 筆的端點會讓 Agent 讀 50 筆。

### 1.3 `cite`

```text
$ cliora knowledge cite S2
docs/adr/0029-v22-agent-runner-model-and-run-lifecycle.md @ 139f143
來源類型：repo 文件　可信層級：canonical　時間：2026-08-21
（全文，或超過 16 KiB 時的頭尾 ＋ 省略說明）
```

`S2` 這種短標籤由 **`context` 與 `search` 的輸出定義**，只在該 run 內有效
（存在 `context_packs.source_manifest` 的順序裡）。
理由：uuid 不適合出現在 Agent 要寫進留言的引用裡，
而 `[S2]` 這種形式在 Agent 的回覆中可讀、可被人點回去。

**找不到 source 的行為**（出口條件之一）：

| 情況 | 回應 |
|---|---|
| 標籤不在這個 run 的 manifest 裡 | `SOURCE_NOT_FOUND`，訊息說「先跑 `cliora knowledge context`」 |
| source 已被 tombstone | `SOURCE_NOT_FOUND`，訊息說「這份來源已不存在（可能是檔案被刪或被新版取代）」 |
| source 被 exclude | `SOURCE_EXCLUDED`，訊息說「有人把它從這張卡排除了」 |
| 跨 project | **`SOURCE_NOT_FOUND`（不是 403）** ——不揭露存在 |

★ 最後一列是安全要求而不是使用者體驗：403 會告訴呼叫端「這個 id 存在但你沒權限」。

### 1.4 `sync`

見 [`04`](./04-sources-and-authority.md) §5.3。

**放在 `knowledge` 底下而不是 `context` 底下**：它寫入平台，
而 `cliora context show` 是唯一一個保證離線可用的命令（D14），
把一個會發網路請求的子命令放進那棵樹會弄壞那個保證。

## 2. 引用格式（Agent 回覆裡的）

Agent 在 `cliora task say` 的內容裡引用來源時，格式是：

```text
依 [S2] 的說明，租約 sweep 不看子行程活著沒有。
```

Central **不解析**它，前端渲染時把 `[S2]` 對到該卡最近一次 context pack 的
manifest 並變成可點的引用。

★ **不解析是一個決定。** 解析的誘惑很大（可以驗證引用是否真實存在），
但那會讓 `task_messages.body` 從「有人說的話」變成「一個要維護 schema 的結構」，
而 `GATE-CV-APPEND-ONLY` 說這張表沒有更新路徑——一個事後才發現引用錯誤的訊息
會需要一條它沒有的路徑。所以：**引用是文字，渲染是最佳努力，
對不上就顯示成純文字。** 這一句要進 ADR 0039。

## 3. 提示文字的改動

`render_run_context()` 的「你可以怎麼回報進度」區塊之後、卡片內容之前，
加入 [`06`](./06-context-builder.md) §2.1 的兩段。

**既有文字一個字都不改。** 理由：那些字是 `alpha.1` 已經在跑的東西，
而它們與 M2 的量測綁在一起。新增的段落自成一段，可以被單獨移除。

## 4. Go 端的測試（`KN-09`）

| # | 測試 | 斷言 |
|---|---|---|
| 1 | `TestKnowledgeContextPrintsMarkdown` | 預設輸出不是 JSON |
| 2 | `TestKnowledgeContextOfflineSaysWorkContinues` | 沿用 `RunOfflineMessage` |
| 3 | `TestKnowledgeSearchCapsLimit` | 送 `--limit 50` → 請求裡是 8（客戶端先夾，伺服器再夾） |
| 4 | `TestKnowledgeCiteMapsShortLabel` | `S2` → manifest 的第二個 source_id |
| 5 | `TestKnowledgeCiteExplainsAMissingSource` | 四種情況各一句話 |
| 6 | `TestSyncDryRunSendsNothing` | 零 HTTP 請求 |
| 7 | `TestSyncSkipsIgnoredPaths` | `.clioraignore` |
| 8 | `TestSyncBatchesUnderTheByteCeiling` | 8 MiB 分批 |
| 9 | `TestNoApproveSubcommandExists` | 既有精神的回歸：`knowledge` 樹裡沒有任何寫 authority 的命令 |

★ 第 9 條對應 `NewCommand()` 的既有註解：
「Deliberately **no `approve` subcommand.** The API refuses it, but a subcommand
that exists invites an agent to try」。同一個理由，
`cliora knowledge` 底下**沒有** `mark-authoritative`、`retract`、`pin`——
那三個都是人的動作（`project.manage`），而 run token 永遠沒有它。

## 5. 版本與相容性

| 項目 | 值 |
|---|---|
| `daemon/VERSION` | `0.13.1` → `0.14.0` |
| `daemon/cmd/agentd/main.go` 的 `version` | `0.14.0-dev`（★ `plan/23/10` §2.12：版本要改兩個地方） |
| contract | **1.13.0 不動**，`GATE-KN-CONTRACT-FROZEN` |
| 未升級節點（0.13.1） | 完整 run 生命週期不變。**`cliora knowledge` 不存在**，於是 Agent 拿不到 knowledge——**這要在 release note 明寫** |

★ 最後一列是本期唯一的相容性議題，而它比 `alpha.2` 的溫和：
`alpha.2` 的風險是「未升級節點會壞」，本期是「未升級節點少一個功能」。
但**它的症狀一樣容易被誤讀**——一個 0.13.1 節點上的 Agent 會看到 offer 裡那句
「`cliora knowledge context` 讀完整的引用清單」然後得到 `unknown command`。

所以 offer 裡那一段要**由 Central 依節點能力決定要不要放**：

```text
node.daemon_version >= 0.14.0  →  放那兩段
低於或讀不出來                  →  只放 policy digest，不放 CLI 指引
```

> **★ 這一節原本寫的是用 `runner.register.features` 宣告 `"knowledge"`，那是錯的。**
> 該欄位在 contract 1.13.0 存在，但它的 **enum 是封閉的**
> （`contracts/v1/schemas/messages/runner-register.schema.json` 只允許
> `verification` 與 `evidence`），而且「拼錯 = 整個 frame 被拒」是它刻意的設計
> ——`contracts/v1/fixtures/invalid/runner-register-unknown-feature.json` 就在斷言這件事。
> 加一個值就是動 contract（違反 D87），而且後果比那更糟：**一個沒升級的 Central
> 會直接拒絕新 daemon 的註冊**，於是那台機器連上線都不行。
>
> 節點本來就回報 `daemon_version`，而那正好回答了要問的問題。
> 實作在 `RunService._daemon_has_knowledge_cli()`，版本以整數 tuple 比較——
> 字串比較下 `"0.9.0" > "0.14.0"`，那種錯十次對九次。

**這一條是本期最容易被漏掉的相容性細節**，而它的成本只有一個 if。
`KN-13` 的相容性驗證（沿用 [`plan/24/04`](../24/04-compatibility-0120.md) 的形狀）
要包含「0.13.1 節點的 offer 裡沒有那兩行，但仍然有 policy digest」。
