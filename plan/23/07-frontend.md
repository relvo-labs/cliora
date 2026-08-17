# 07 — 前端（`CV-10`、`CV-11`、`CV-13`）

## 1. 現況

對話 UI 全部在 `components/project/TaskAgentPanel.vue`（**332 行**），
它同時管四件事：runs、messages、artifacts、agents。

三個必須改的地方：

| 行 | 現況 | 問題 |
|---:|---|---|
| 65-68 | 打開時一次載入四個列表 | 每次 post 之後**整份 messages 重抓**（118 行） |
| 112-122 | `post(kind)` 只有 `"message" \| "answer"` | 沒有 question 關聯、沒有冪等鍵、失敗時 `draft` 已被清空 |
| 126-129 | `unanswered` 從「最後一則是不是 question」推 | **前端自己猜等待狀態**——上游規劃[明文禁止](../../research/cliora-project-experience-redesign-plan.md)（§14.6：「不可讓不同頁面自行用『最後一則訊息是誰』猜測 waiting state」） |

第三點是本期在前端最重要的修正：**等待狀態由 server 給**
（`tasks.waiting_for_actor` ＋ `TaskQuestionDTO`），前端不推導。

## 2. 拆分

```text
components/project/
  TaskAgentPanel.vue        保留，但只留 runs ＋ agents ＋ dispatch（約 150 行）
  conversation/
    ConversationPanel.vue   訊息串容器、無限捲動、seq 合併
    MessageItem.vue         一則訊息（三種 actor × 六種 kind）
    QuestionCard.vue        Agent 的問題（三態）
    MessageComposer.vue     輸入框 ＋ 兩個動作 ＋ 草稿
    ProposalCard.vue        spec proposal ＋ 人類的接受／要求修改
    DeliveryState.vue       sending / sent / agent_seen / failed
```

`TaskDetailView.vue` 掛 `ConversationPanel`，位置在 `TaskAgentPanel` **之前**
——對話是主要工作面，不是 run 面板的附屬。

> **這是為 `beta.1` 的 Drawer 預先做的拆分。** `plan/25` 的 `PX-41` 會把
> `ConversationPanel` 原封不動放進 Drawer 的主欄；本期把它做成可以被搬的形狀，
> 就不必在 `beta.1` 再改一次。

## 3. 訊息串

### 3.1 三種 actor，不只靠顏色

| actor | 標示 |
|---|---|
| human | 頭像圓形 ＋ 顯示名稱 ＋ 靠右 |
| agent | 頭像方形 ＋ runner 名稱 ＋ 🤖 icon ＋ 靠左 |
| system | 無頭像 ＋ 置中 ＋ 細字 ＋ **可折疊** |

沿用 `plan/19` 建立的 token 與 `StatusBadge`；
**不擴大 naive-ui 的使用面**（`plan/19` D35）。

### 3.2 六種 kind 的呈現

| kind | 呈現 |
|---|---|
| `comment` | 一般氣泡 |
| `question` | **`QuestionCard`**，有邊框、有狀態徽章、有「回覆並繼續」 |
| `answer` | 氣泡 ＋ 上方一行「回覆：〈問題前 40 字〉」（來自 `reply_to_message_id`） |
| `proposal` | **`ProposalCard`**，可展開／收合，有「接受」「要求修改」 |
| `decision` | 氣泡 ＋ 明確的 actor 與時間（**永遠顯示人類 actor**） |
| `system` | 細字、置中、預設折疊成一行「3 個系統事件」 |

**raw log 不進訊息串。** run 的 log 用既有的 `RunDetailView` deep link 開啟。
`GATE-CV-NO-LOG-IN-THREAD`：`ConversationPanel` 及其子元件不 import
任何 run log 的 API（[`08`](./08-verification-and-exit.md) §3）。

### 3.3 分頁與合併

- 初次載入最後 **50** 則（`?before_seq=` 往回）。
- 向上捲動載入更早的。
- **新訊息以 `conversation_seq` 合併並 append，不重排整個串。**
  重排會讓正在閱讀的人捲動位置跳掉。
- 樂觀插入：送出時先插一則 `pending` 的本地訊息（seq 用 `Infinity` 排在最後），
  收到 201 之後用真的 seq 取代。

## 4. Question card

三態，**由 server 的 `question_state` 決定，不由前端推**：

```text
┌─ open ─────────────────────────────────────────┐
│ 🤖 runner-03 問（14:33，等了 12 分鐘）           │
│ 「SP metadata 要放在哪個路徑？」                  │
│ [ 回覆並繼續 ]                                   │
└────────────────────────────────────────────────┘

┌─ answered ─────────────────────────────────────┐
│ 🤖 runner-03 問（14:33）· ✓ 陳小美已於 14:45 回覆 │
│ 「SP metadata 要放在哪個路徑？」                  │
│ → 跳至回覆                                       │
└────────────────────────────────────────────────┘

┌─ expired ──────────────────────────────────────┐
│ 🤖 runner-03 問（昨天 14:33）· ⏰ 逾時未回覆       │
│ 「SP metadata 要放在哪個路徑？」                  │
│ 這張卡已退回「阻塞」。[ 重新派工 ]                 │
└────────────────────────────────────────────────┘
```

`expired` 那一格的動作是**重新派工**而不是「回覆並繼續」，
因為卡片已經在 `blocked`，而 continuation 需要它不在 blocked
（[`04`](./04-answer-resume-and-turns.md) §4）。這個粗糙邊緣記在
[`09`](./09-open-measurements.md) 第 5 項。

## 5. Composer：兩個動作，視覺上必須不同

```text
┌──────────────────────────────────────────────────┐
│ 輸入你的回覆…                                     │
│                                                  │
├──────────────────────────────────────────────────┤
│                    [ 留言 ]  [ 回覆並繼續 ]        │
│                     次要        主要（有 icon）    │
│                                                  │
│  回覆並繼續會建立一個新的 Agent 回合。              │
└──────────────────────────────────────────────────┘
```

| | 留言 | 回覆並繼續 |
|---|---|---|
| 送到哪 | `POST /messages` `kind='comment'` | `POST /questions/{id}/answer` `resume=true` |
| 何時出現 | 永遠 | **只有在有 open question 時** |
| 樣式 | 次要 | 主要 ＋ icon |
| 送出後 | 串裡多一則 | 串裡多一則 ＋ 上方出現「已排入新的一輪」 |

**沒有 open question 時，「回覆並繼續」不出現**——
不是 disabled，是不存在。一個永遠灰著的按鈕會被理解成「壞了」。

`CV-12` 的元件測試有一條：**兩個按鈕的可及名稱（accessible name）不得相同，
且主要動作的名稱必須包含「繼續」**。這是 E2E-J6（comment 不誤 resume）
在 UI 層的對應。

### 5.1 草稿

```text
存在哪   localStorage，key = `cliora.draft.<taskId>`
何時存   輸入停止 500ms 後
何時清   201/200 成功之後
何時不清 **任何失敗**——網路錯誤、409、403、500
```

`CV-12` 的元件測試：mock 一個 500，斷言輸入框內容不變。
這是本期在前端唯一一條**「使用者打的字不會不見」**的機械保證。

### 5.2 冪等鍵

前端每次開始編輯產生一個 UUID，隨請求送出，成功後才丟棄。
使用者連點兩次送出 → 同一個 key → 第二次回 200 ＋ 原訊息 → UI 不多一則。

## 6. Delivery state

每則自己送出的訊息顯示狀態：

| 狀態 | 什麼時候 | 呈現 |
|---|---|---|
| `sending` | 樂觀插入後、回應前 | 淡色 ＋ 轉圈 |
| `sent` | 收到 201/200 | ✓ |
| `agent_seen` | `last_acked_seq >= 這則的 seq` | ✓✓ ＋ tooltip |
| `failed` | 錯誤 | ⚠ ＋ 「重試」 |

**`agent_seen` 的 tooltip 是本期唯一一句必須逐字寫進計畫的 UI 文案**：

> 「Agent 已讀取這則訊息。**這不代表它同意或已經照做。**」

理由在 [`research/03`](../../research/03/01-architecture-decisions.md) R9：
把「訊息已存進資料庫」與「模型讀到了」混為一談，是這類產品最常見的錯覺。
兩個勾勾的隱喻來自即時通訊軟體，而那個隱喻在這裡有一半是錯的——
所以要用文字把那一半說回來。

`agent_seen` 的資料來源：`conversation_consumers.last_acked_seq`，
在 `TaskQuestionDTO` 旁邊一起回，不另開請求。

## 7. Spec proposal（`CV-11`）

`ProposalCard`：

```text
┌─ 🤖 runner-03 提出規格（14:52）───────────────┐
│ ## 目標                                       │
│ …（預設顯示前 15 行，可展開）                   │
│                                              │
│ [ 接受 ]  [ 要求修改 ]        ← 需 task.approve │
└──────────────────────────────────────────────┘
```

- 兩個按鈕**只在使用者有 `task.approve` 時渲染**。
  沒有權限時顯示「等待有核准權限的人檢視」——**不是** disabled 的按鈕。
- 「要求修改」開一個必填理由的輸入框，送出 `kind='decision'` ＋ 理由。
- 「接受」送 `kind='decision'`，並且**只有這個動作能改 readiness**。
- 兩者都在訊息串裡留下帶人類 actor 與時間的 `decision` 訊息。

**同一張卡有多個 proposal 時，只有最新的顯示按鈕**，
較早的顯示「已被 v2 取代」。避免有人接受了一份舊的。

## 8. `CV-13` 在前端的部分

卡片（`TaskBoard.vue` 的既有卡片，本期不重做）新增一個徽章：

```text
waiting_for_actor === 'human'  →  ⚠「等待你的回覆」  最高層級（plan/19 D24）
waiting_for_actor === 'agent'  →  🤖「Agent 處理中」
open_question_count > 1        →  在徽章旁顯示數字
```

**這三個值全部來自 server 的投影欄**，
`TaskAgentPanel.vue:126-129` 那段自己推導的程式碼**刪除**。
`GATE-CV-NO-CLIENT-WAITING-DERIVATION`：前端不得出現
「以最後一則訊息的 kind 判斷等待狀態」的模式（[`08`](./08-verification-and-exit.md) §3）。

## 9. 資料層

本期**不引入 query cache 套件**（[`research/03`](../../research/03/01-architecture-decisions.md) D56 是 `beta.1` 的事）。
`ConversationPanel` 用一個自帶的 `useConversation(taskId)` composable：

```ts
{ messages, questions, load(beforeSeq?), append(msg), post(...), answer(...) }
```

約 120 行，**刻意不通用**。`beta.1` 的 `PX-27` 把它接進那時的 query 層；
現在為了一個面板蓋一個框架是提前付款。

## 10. 元件測試

| 測試 | 斷言 |
|---|---|
| 六種 kind × 三種 actor | 各自渲染正確，system 預設折疊 |
| question card 三態 | open 有「回覆並繼續」、answered 有跳轉、expired 有「重新派工」 |
| 兩個動作不可混淆 | 可及名稱不同，主要動作含「繼續」 |
| 沒有 open question 時 | 「回覆並繼續」**不存在**（不是 disabled） |
| 草稿在 500 之後保留 | 輸入框內容不變 |
| 連點兩次送出 | 只有一則訊息（同一個 idempotency key） |
| 新訊息 append 不重排 | 捲動位置不變 |
| `agent_seen` 的 tooltip | 逐字比對那句話 |
| proposal 按鈕的權限 | 無 `task.approve` 時不渲染按鈕 |
| 舊 proposal | 不顯示按鈕，顯示「已被取代」 |
| 卡片徽章 | 三種投影值各一 |
| raw log 不在串裡 | 元件不 import run log API |
