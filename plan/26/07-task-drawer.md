# 07 — Task Drawer

> **ticket：`PX-38`（shell ＋ 版面）、`PX-40`（inline edit）、`PX-41`（conversation-first）、
> `PX-42`（run／dependency／activity）、`PX-43`（artifact／delivery／verification／gate）、
> `PX-62`（related knowledge）、`PX-46`（行動版）。依賴 `PX-18`、`PX-27`。**

## 1. 為什麼不是「把 TaskDetailView 塞進側邊」

現況：點卡片 → 導航到 `/projects/:id/tasks/:taskId`（`views/TaskDetailView.vue`，
158 行，內嵌 `components/project/conversation/ConversationPanel.vue`）。
代價是看板 scroll 消失、filter 的注意力中斷、連續審查多張卡成本高。

但**目標不是「同樣的內容換個容器」**：

> 使用者的動作是「掃描看板 → 打開細節 → 回覆 Agent → 繼續掃描」。
> Drawer 存在的理由是讓中間兩步不打斷前後兩步。

所以 Drawer 的內容順序與 `TaskDetailView` 不同：
**conversation 前移到主欄第二位**，執行設定後移並預設收合。

**`/projects/:id/tasks/:taskId` 保留**（禁區清單）。Drawer 有「開新分頁」指向它。

### 從 kintra `TicketDetailDrawer` 逐字採納的三條

不移植程式碼（1394 行、綁 Naive UI、custom field 與 i18n），移植三條規格
（[`13`](./13-kintra-port.md) §5）：

```text
Header（ID／標題／狀態／操作）＋ Main ＋ Sidebar 三段
一般 Ticket 詳情**不使用 Modal**
行動版改為全螢幕
```

「不使用 Modal」值得單獨說：modal 會讓背後的看板不可互動，
而 Drawer 存在的理由就是**不打斷前後兩步**——同一個決定的兩種說法。

Cliora 的 Main 順序與 kintra 不同（conversation 前移到第二位），Sidebar 內容也不同。

## 2. Desktop layout（`PX-38` shell ＋ `PX-39` 版面）

寬度 720–920px 依 viewport 調整。

```text
┌──────────────────────────────────────────────────────────────┐
│ TK-142 · task · In progress · ⚠ Waiting for your input   [⤢][×]│
│ 支援 SAML SSO 登入                                            │
│ [回覆並繼續] [指派] [派工] [⋯]                                 │
├───────────────────────────────────┬──────────────────────────┤
│ Description                       │ Owner        陳小美       │
│ Human–Agent conversation      ★   │ Assigned Agent  —        │
│ Current run                       │ Priority / risk  high    │
│ Deliverables / artifacts          │ Stage        implementing│
│ Verification                      │ Required labels [sso]    │
│ Related knowledge             ★   │ Source / delivery  PR    │
│ Readiness / checklist             │ Repository / branch      │
│ Dependencies                      │ Required secret names    │
│ Activity                          │ Requirement / Epic / Story│
│                                   │ timestamps               │
└───────────────────────────────────┴──────────────────────────┘
                                      ★ = 本輪新增的兩個區塊
```

### Advanced execution 預設收合

以下預設收合：source、delivery、base／target branch、required labels、
required secrets、dispatch diagnostics。

**但若任一欄位造成 blocked 或 warning，該 section 自動展開並把問題置頂。**
這是提案 R7 的緩解：progressive disclosure ≠ 刪除。

四種情境各一元件測試（SR-3 的第六項）：

| 情境 | 判斷依據 | 展開哪一段 |
|---|---|---|
| `no_eligible_runner` | `primary_attention` | Required labels ＋ dispatch diagnostics |
| `assigned_runner_offline` | `primary_attention` | Assigned Agent |
| 缺 required secret | 既有 dispatch 拒絕的 machine code | Required secret names |
| repository 未綁定 | `repository_id is null` 且 `delivery != 'none'` | Repository / branch |

**「造成 blocked」的判斷不在前端重算**——前端讀
`primary_attention`、`blocking_reason` 與既有的 dispatch 診斷欄位。
這是 [`03`](./03-read-model-and-attention.md) §2 那句「前端不得重建這個順序」的延伸。

## 3. Conversation first（`PX-41`）

`waiting_for_input` 時，Drawer **自動捲到並聚焦**：

1. Agent 的問題（question card）
2. 相關 context（Agent 引用了什麼——來自 `alpha.3` 的 citation）
3. 回覆 composer
4. 送出後的 run resume 狀態

**不要求使用者先展開 Run log 才知道 Agent 在問什麼。**

Composer 的兩個動作在視覺上明確不同：

```text
[ 留言 ]         ← 次要樣式。POST /messages kind=comment，不改 run 狀態
[ 回覆並繼續 ]    ← 主要樣式。POST /questions/{id}/answer resume=true
                    按鈕下方一行小字：「會建立一個新的 Agent turn」
```

兩者呼叫的是 `alpha.2` 已經存在的兩個端點
（`AnswerQuestionRequest.resume` 的 docstring 就寫著這個區別：
「the difference between 留言 and 回覆並繼續」）。
**`PX-41` 不新增後端。**

訊息狀態顯示 `sending` / `sent` / `agent_seen` / `failed`。
**`agent_seen` 代表 supervisor 已 ack，不代表模型同意內容**——
這句話要出現在 tooltip 裡，不是只在文件裡。

`AnswerResultDTO.mode` 的四個值（`new_turn` / `live_run` / `no_run` / `none`）
各有一句 UI 文案，而 `refusal_code` 非空時顯示
「答覆已保存，但續跑被拒：<code>」——**答覆仍然寫了，這一點要說清楚**
（那正是 `refusal_code` 是欄位而不是錯誤的理由）。

### 新鮮度（[D95](./01-decisions-and-governance.md)）

Drawer 開著時 conversation 每 5 秒輪詢 `GET /messages?after=<seq>`，
以 `conversation_seq` 合併，**append 不重排**。
關閉 Drawer 停止輪詢。形狀沿用 `views/RunDetailView.vue:99` 的 2 秒輪詢器，放寬到 5 秒。

**raw log 不混進 conversation 串**（`GATE-CV-NO-LOG-IN-THREAD` 已經在守後端；
`PX-42` 補一支前端元件測試）。system event 可折疊；log 以 deep link 開啟。

## 4. URL 與狀態（[D111](./01-decisions-and-governance.md)）

```text
/projects/:projectId/work?view=:viewId&f=…&task=:taskId
```

| 情境 | 行為 |
|---|---|
| 開啟 | 加上 `?task=<uuid>`，用 **`router.replace`**（不堆 history） |
| 關閉 | **只移除 `task` query**，view／filter／scroll 全部保留 |
| reload | 仍開啟同一 Task |
| browser back | 依序：關 Drawer → 還原 view → 才離開 Project |
| 無權查看 | 403 state，**不洩漏標題** |
| 已刪除／不存在 | 404 state，**底層 view 保留** |
| 完整頁面 | `/projects/:id/tasks/:taskId` 保留；Drawer 有「開新分頁」 |
| 行動裝置 | 全螢幕 route overlay（`PX-46`） |

**403 不洩漏標題**在今天的權限模型下（[D93](./01-decisions-and-governance.md)）
只有一種構造方式：呼叫者沒有 `project.view`。測試照這個構造寫，
並在測試名字裡說出來：`test_a_caller_without_project_view_gets_403_without_the_title`。

## 5. Inline editing（`PX-40`）

| 規則 | 說明 |
|---|---|
| title、description | **explicit save**（有 dirty 指示）。不與 autosave 混用 |
| select 類欄位 | immediate patch |
| 每次帶 `version` | 沿用既有樂觀鎖（`TASK_VERSION_CONFLICT`） |
| conflict（409） | **保留使用者草稿**，提供 reload／compare 兩個動作 |
| field error | 顯示在欄位旁，**不只顯示 toast** |
| composer draft | 以 task id 隔離保存；**mutation 失敗不得清除使用者文字** |

409 的 `details.current` 已經帶了完整的當前卡片
（`services/tasks.py` 的既有行為：「so a board can re-render without a follow-up GET」）。
`PX-40` 的 compare 動作直接用它，**不再發一次 GET**。

「保留草稿」有一支元件測試：注入 409 之後，輸入框的內容**逐字不變**。

## 6. Related knowledge（`PX-62`）

整合 `alpha.3` 的 `KN-11`。三件事：

```text
top sources        Context Builder 這個 turn 選了哪幾個來源
pin / exclude      需要 project.manage
「為什麼被選中」    authority × freshness × 命中的 query term
```

**只讀既有 endpoint**（`services/knowledge/` 在禁區清單）。
`PX-62` 是把 `modules/knowledge/components/` 已有的元件放進 Drawer 的一個 section，
不是新的 knowledge 功能。

**前置條件**：`v2.0.0-alpha.3` 已 tag 且 SR-2 已簽核
（[`00`](./00-execution-plan.md) §1 的前置條件）。

## 7. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | reload 回到同一 Task | E2E |
| ☐ | 關閉 Drawer 不丟失 view、filter、scroll | E2E-J10 |
| ☑ | Waiting flow 不必打開 Terminal 或 raw log | E2E-J1，32／32。最後一條斷言是這個專案的 `terminal_sessions` 計數為零 |
| ☑ | Agent 的多輪問答、訊息狀態與 open questions 在同一 Drawer 可見 | E2E-J1 走了三輪 continuation，規格裡引用了三個回答 |
| ☐ | human approval 永遠顯示 human actor 與時間 | 元件測試 ＋ 視覺檢查 |
| ☐ | 403 不洩漏標題、404 保留底層 view | 兩個測試 |
| ☐ | conflict 保留草稿 | 元件測試：409 後輸入框內容逐字不變 |
| ☐ | 造成 blocked／warning 的執行設定自動展開並置頂 | 元件測試，**四種情境**（§2） |
| ☐ | raw log 不出現在 conversation 串 | 元件測試 |
| ☐ | 打開已快取 Drawer < 150ms 感知回應 | 效能量測 |
| ☐ | focus trap／restore、aria label、狀態播報 | a11y 測試 |
| ☐ | browser back 依序關 Drawer → 還原 view → 離開 | E2E（D111 的可觀察後果） |
