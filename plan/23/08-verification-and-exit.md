# 08 — 驗證與出口條件（`CV-12`）

## 1. 這一期的驗證形狀

本期的錯誤幾乎都是**「沒發生的事」或「發生了兩次的事」**，兩者都沒有 stack trace。
所以驗證的重心不是「功能會動」，而是三類斷言：

```text
① 唯一性     同一件事只發生一次      → 唯一索引 ＋ 併發測試
② 原子性     兩件事一起發生或都不發生 → 單一交易 ＋ 中斷測試
③ 不可能性   某條路徑寫不到某個欄位   → gate（AST／grep）＋ 負面測試
```

## 2. 測試矩陣

### 2.1 Unit

| 分類 | 項目 |
|---|---|
| 取號 | 20 併發寫同一張卡 → seq 恰好 1..20 各一次 |
| 冪等 | 同 key 同內容 → 200 ＋ 原訊息；同 key 不同內容 → 409；不同 key → 兩則 |
| kind | 六種寫入驗證；`message`→`comment`、`event`→`system` 的讀取映射 |
| question 狀態機 | open→answered／cancelled／expired 各一；answered→answered 拒絕 |
| CAS 失敗解釋 | 四種原因回四種（404／404／409 ALREADY／409 NOT_OPEN） |
| `run_branch` | continuation 的分支 == root 的分支；三輪後仍然相等；`none`／`artifact` 仍回空字串 |
| cursor | `after_seq` 邊界；`after_seq > conversation_seq` → 409 |
| 投影 | `_reproject` 的三個分支（human／agent／NULL） |
| 情境包 | 四段組成；超 16 KiB 時裁切順序；省略有說明文字 |
| redaction | message body 含機密值 → 寫入前被換掉 |

### 2.2 Backend integration

| 分類 | 項目 |
|---|---|
| **原子性** | answer＋question close＋turn enqueue 三者同交易：注入一個在建 run 時失敗的錯誤，斷言 question 仍是 `open` 且沒有訊息 |
| **併發** | 兩個請求同時回答同一 question → 一個 201、一個 409，且**只有一個 continuation** |
| **重送** | 同 idempotency key 送 10 次 → 1 則訊息、1 個 turn |
| `finish()` 推導 | 有 open question 的 `run.complete` → `result='awaiting_input'`；沒有的 → `result='succeeded'` |
| `delivery_incomplete` 不誤判 | `delivery='artifact'` ＋ 問完就結束 → **無** `run.delivery_incomplete` 事件 |
| 逾時 | 兩種情境（run 還活著／已終結）都會在 24h 後 question 進 `expired` 且卡片進 `blocked` |
| 逾時後回覆 | `409 QUESTION_NOT_OPEN` |
| continuation refusal | 等待期間替卡片加 `required_secrets` → resume 回 409、**answer 仍然寫入**、卡片上有 system 訊息 |
| continuation 認領 | 走既有 `poll()`／`claim()`，可被不同 runner 接走 |
| run token 邊界 | 跨 task 讀寫 → 404；寫 `decision` → 403 ＋ audit；指定 actor → 忽略 |
| Viewer | 不可 POST 任何 kind |
| `task.approve` | 沒有它不能寫 `decision`（人類也一樣） |
| audit | message／answer／resume 的 payload **不含 body** |
| `run_logs` 無關性 | 刪光某卡全部 `run_logs` → conversation／question／proposal 完整 |
| backfill | 在有既有訊息的資料集上跑 `0040`，斷言 seq 連續、question 判定與現行 `pending_question()` 一致 |
| migration roundtrip | `0040` → `0039` → schema 與基線逐位元組相同 |

### 2.3 Frontend component

見 [`07`](./07-frontend.md) §10（12 條）。

### 2.4 CLI（Go）

見 [`06`](./06-cli.md) §5（10 條）。

## 3. 七個新 gate

`scripts/cv/gates.sh`，形狀沿用 `scripts/rq/gates.sh`。

| Gate | 斷言 | 違反時會怎樣（而且沒有其他症狀） |
|---|---|---|
| `GATE-CV-CONTRACT-FROZEN` | `contracts/` 全樹 sha256 與基線相同 | D44 被悄悄推翻，未升級節點靜默壞掉 |
| `GATE-CV-TOUCH-LIST` | [`00`](./00-execution-plan.md) §3 的禁區未被修改 | 本期的風險評估（「Central-only」）不再成立 |
| `GATE-CV-APPEND-ONLY` | `task_messages` 沒有 `update()` 呼叫；`task_questions` 只有白名單欄位 | 一則人看過的訊息被就地改寫 |
| `GATE-CV-PROJECTION-ONE-WRITER` | `waiting_for_actor`／`open_question_count` 的賦值點只在 `_reproject` | 看板顯示「等你回覆」但其實答完了 |
| `GATE-CV-CONTINUATION-REFUSALS` | `dispatch()` 與 `enqueue_continuation()` 都呼叫 `_assert_card_dispatchable`，且那些 `raise` 只在它裡面 | 一張等待期間被加了機密的釐清卡，第二輪帶著機密出去 |
| `GATE-CV-NO-LOG-IN-THREAD` | `conversation/` 下的元件不 import run log API | raw log 混進對話，「conversation 不是 log」這條變成一句口號 |
| `GATE-CV-NO-CLIENT-WAITING-DERIVATION` | 前端不出現「以最後一則訊息的 kind 判斷等待狀態」 | 同一張卡在不同畫面顯示不同的下一步 |

外加兩個沿用既有的：

| Gate | 來源 |
|---|---|
| `GATE-AR-SINGLE-CLAIM` | `plan/18`。continuation 走同一條認領路徑，這條要對新基線重跑 |
| `GATE-RQ-CONTEXT-DISPATCH` | `plan/22`。`RENDERERS` 加第四個（D65），chooser 不變 |

### 3.1 `GATE-CV-PROJECTION-ONE-WRITER` 怎麼實作

AST 掃 `backend/app/`，找對 `Task.waiting_for_actor` 與 `Task.open_question_count`
的賦值（`ast.Attribute` 在 `ast.Assign` 的 target，或 `update(Task).values(...)`
的 key），斷言 enclosing function 只有 `ConversationService._reproject`。
形狀與 `gate_context_dispatch.py` 的「以呼叫點斷言」相同，
換成「以賦值點斷言」——`gate_human_actor.py`（`plan/22`）已經有這個形狀，直接改。

### 3.2 `GATE-CV-CONTINUATION-REFUSALS` 怎麼實作

兩層：

1. **靜態**：AST 找 `TASK_KIND_FORBIDS_SECRETS`、`TASK_KIND_NEEDS_REQUIREMENT`、
   `TASK_KIND_DELIVERY_NOT_ALLOWED`、`TASK_MOCKUP_INTEGRATION_DISABLED`、
   `TASK_SECRETS_NOT_ALLOWED`、`TASK_SECRETS_MISSING` 這六個字串出現的位置，
   斷言全部在 `_assert_card_dispatchable` 之內。
2. **動態**：對 `dispatch()` 與 `enqueue_continuation()` 各跑一遍六種違規輸入，
   斷言兩者回**同樣的 code**。

第二層是必要的：靜態那層只證明 `raise` 在同一個函式裡，
不證明 `enqueue_continuation` 真的呼叫了它。

## 4. 六條 E2E

沿用 [`research/03/10`](../../research/03/10-verification-and-exit.md) §3 的編號。

| # | 旅程 | 關鍵斷言 |
|---|---|---|
| **J3** | Ready 卡被認領 → Running → Agent 提問 → 卡片顯示「等待你的回覆」 | 徽章來自 server 的 questions 清單（**不是**投影欄——`CV-13` 是「先寫入不顯示」）；投影欄另以 API 斷言。見 `plan/24/03` §0.1 |
| **J5** | answer commit 後 daemon 斷線／重啟 → 補拉且**只建立一個 turn** | 重啟後 `SELECT count(*) FROM task_runs WHERE resumed_question_id = ?` 恰為 1 |
| **J6** | 只送 comment → **run 不被誤 resume** | 送 20 則 comment，`task_runs` 筆數不變、run 狀態不變 |
| **J7** | Run failure → 顯示原因 → retry，**conversation 保留** | retry 之後訊息串完整，seq 連續 |
| **J8** | 兩個使用者同時回答同一 question | 一個成功、一個拿到帶 `answered_by`／`answered_at` 的 409 |
| **J9** | Agent 嘗試送 `decision` | `403 AGENT_CANNOT_DECIDE` ＋ audit 有一筆 |

加一條本期特有的：

| # | 旅程 | 關鍵斷言 |
|---|---|---|
| **J1a** | **三輪釐清 ＋ spec proposal ＋ 要求修改 ＋ 接受**，全程不進 Terminal | 四輪都是新的 run，但**不是** `turn_seq` 1→2→3→4：兩次 answer 產生 continuation（2、3），第四輪是「要求修改」之後**人重新派工**的 root（`CE-18`）。`decision` **不改** readiness——那是刻意的（出口 8）。見 `plan/24/03` §0 |

`J1a` 是 `beta.1` 主旅程 J1 的前半段。**它是本期不可降級的那一條。**

## 5. SR-1 安全審查

在 `v2.0.0-alpha.2` 的 tag 之前，由人執行並具名簽核。

| ☐ | 審查項 | 通過標準 |
|---|---|---|
| ☐ | run token 不能寫 `decision` | J9 ＋ audit |
| ☐ | run token 不能跨 task 讀寫 | 負面測試（`_own_task` 既有，回歸） |
| ☐ | run token 不能指定 actor | POST 帶 `author_user_id` → 被忽略，寫入的仍是 runner |
| ☐ | Viewer 不可發言 | 負面測試 |
| ☐ | `comment` 不 resume、`answer` 不 approve | J6 ＋ gate 後斷言 `tasks.gates` 未變 |
| ☐ | Agent `proposal` 不改 readiness | 提出 proposal 後卡片仍非 ready |
| ☐ | secret value 不出現在 message、error、telemetry | Central 端 redaction 測試（[`03`](./03-conversation-api.md) §10） |
| ☐ | audit 只記 metadata | audit payload 斷言不含 body |
| ☐ | body 大小上限 | > 20000 → `400 MESSAGE_TOO_LARGE` |
| ☐ | continuation 不繞過卡片 refusal | `GATE-CV-CONTINUATION-REFUSALS` 兩層 |
| ☐ | **未升級節點（`agentd` 0.12.0）行為不變** | 用 0.12.0 的 binary 跑完整 run 生命週期 E2E |
| ☐ | `RUN_TOKEN_SCOPES` 未變 | grep 斷言那一行 |
| ☐ | RBAC 動作數仍是 24 | 比對 `rbac.py` 與 seed |

## 6. 效能

固定資料集：一張卡 500 則訊息、一個專案 200 張卡、一個 runner。

| 項目 | 目標 | 怎麼量 |
|---|---|---|
| message commit P95 | < 500ms | 100 次 POST |
| **answer → continuation turn 開始 P95** | **< 10s** | 50 次，量到 `task_runs.claimed_at` |
| conversation reopen（最近 50 則）P95 | < 500ms | 100 次 `?before_seq=` |
| cursor 分頁（每頁 200）P95 | < 300ms | 深度 500 |
| 20 併發寫同一張卡 | 無錯誤、seq 無洞 | 併發測試同時量 |

`< 10s` 的組成要拆開記錄，否則調不動：

```text
answer commit  →  下一次 runner.poll   ：0–5s（poll 間隔）
runner.poll    →  claim                ：< 100ms
claim          →  子行程啟動            ：依 runtime，1–3s
```

若 P95 超過 10 秒，先看是哪一段——**如果是第一段，那就是 D44 的證據**，
而不是 Central 的效能問題。

## 7. 出口條件

| ☐ | # | 條件 | 證明 |
|---|---:|---|---|
| ☐ | 1 | 人類 answer 讓新 turn 在 **P95 < 10s** 內開始 | §6 |
| ☐ | 2 | 每則 answer **至多**建立一個 continuation turn | J8 ＋ `uq_task_runs_continuation` |
| ☐ | 3 | retry 不產生重複訊息或重複回覆 | 重送 10 次測試 |
| ☐ | 4 | Agent process 結束後 conversation 可從 DB 恢復 | J1a |
| ☐ | 5 | daemon 重啟後 answer 仍被讀到且只處理一次 | J5 |
| ☐ | 6 | `comment` 不誤 resume | J6 |
| ☐ | 7 | `answer` 不誤 approve | SR-1 |
| ☐ | 8 | Agent `proposal` 不改正式 readiness | SR-1 |
| ☐ | 9 | run token 不能寫 `decision`、不能跨 task、不能冒充 | J9 ＋ SR-1 |
| ☐ | 10 | Viewer 不可發言 | SR-1 |
| ☐ | 11 | 三輪釐清 ＋ proposal ＋ 修改 ＋ 接受在同一畫面完成 | **J1a** |
| ☐ | 12 | 清除全部 run log 後 conversation／question／proposal 完整 | 整合測試 |
| ☐ | 13 | 不使用 Terminal、PTY、tmux 或 raw log 作為 conversation 依賴 | `GATE-CV-NO-LOG-IN-THREAD` ＋ 程式碼審查 |
| ☐ | 14 | Secret value 不出現在 message、error、telemetry | SR-1 |
| ☐ | 15 | **contract 未變更** | `GATE-CV-CONTRACT-FROZEN` |
| ☐ | 16 | **未升級的 `agentd` 0.12.0 節點行為不變** | SR-1 |
| ☐ | 17 | `0040` 可 downgrade 且 schema 逐位元組相同 | `GATE-CV-MIGRATION-ROUNDTRIP` |
| ☐ | 18 | backfill 的 question 判定與現行規則一致 | 整合測試 |
| ☐ | 19 | 前端不推導等待狀態 | `GATE-CV-NO-CLIENT-WAITING-DERIVATION` |
| ☐ | 20 | 使用者打的字在任何失敗後都不消失 | 元件測試 |
| ☐ | 21 | `make check` 全綠、七個新 gate 全 PASS | CI |
| ☐ | 22 | release note 列出 known limitations | `CV-12` |
| ☐ | 23 | **`v2` → `dev` 由人工明確核准** | 流程 |

## 8. 回歸套組

本期改到既有行為的四處，各要一組回歸：

| 改動 | 回歸什麼 |
|---|---|
| `finish()` 加推導 | 一般 run（無 open question）的完成流程：verification、evidence、delivery、PR |
| `_record_run_outcome` 加條件 | `delivery='artifact'` 且**真的**沒附產物 → 仍然 `delivery_incomplete` |
| reaper 換掃描對象 | 租約回收（job A）與 PR 派送（job D）不受影響 |
| `GET /messages` 回應形狀 | `TaskAgentPanel` 與 `cliora task messages` 兩個消費者都通過 |

第二列是最容易漏的：**加了 `not awaiting` 的條件之後，
「真的忘了附產物」那條路徑還要繼續會失敗**，否則本期修好一個誤判、
弄壞一個真的檢查。
