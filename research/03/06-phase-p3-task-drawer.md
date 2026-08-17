# 06 — `beta.1` 第三段：Task Drawer

> **ticket 前綴 `PX-`。前置條件：[`05`](./05-phase-p2-board-and-backlog.md)，以及 `alpha.2` 的 `CV-10`／`CV-11`。**

## 1. 為什麼不是「把 TaskDetailView 塞進側邊」

現況：點卡片 → 導航到 `/projects/:id/tasks/:taskId`（`TaskDetailView.vue`）。
代價是看板 scroll 消失、filter 的注意力中斷、連續審查多張卡成本高、
返回後不一定知道剛才看的是哪一張。

但**目標不是「同樣的內容換個容器」**。Drawer 要解決的是一個不同的問題：

> 使用者的動作是「掃描看板 → 打開細節 → 回覆 Agent → 繼續掃描」。
> Drawer 存在的理由是讓中間兩步不打斷前後兩步。

所以 Drawer 的內容順序與 `TaskDetailView` 不同：**conversation 前移到主欄第二位**，
執行設定後移並預設收合。

## 2. Desktop layout

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

## 3. Conversation first

`waiting_for_input` 時，Drawer **自動捲到並聚焦**：

1. Agent 的問題（question card）
2. 相關 context（Agent 引用了什麼——來自 `alpha.3` 的 citation）
3. 回覆 composer
4. 送出後的 run resume 狀態

**不要求使用者先展開 Run log 才知道 Agent 在問什麼。**
這是 `plan/19` D24（「等待你的回覆」必須最醒目）在 Drawer 內的延續。

Composer 的兩個動作在視覺上明確不同（[`02`](./02-phase-c1-ticket-conversation.md) §3）：

```text
[ 留言 ]  ← 次要樣式，保存 comment，不改 run 狀態
[ 回覆並繼續 ]  ← 主要樣式，建立 answer + continuation turn
                  按鈕下方一行小字說明「會建立一個新的 Agent turn」
```

訊息狀態顯示 `sending` / `sent` / `agent_seen` / `failed`。
**`agent_seen` 代表 supervisor 已 ack，不代表模型同意內容**——
這句話要出現在 tooltip 裡，不是只在文件裡。

## 4. Advanced execution 預設收合

以下預設收合：source、delivery、base／target branch、required labels、
required secrets、dispatch diagnostics。

**但若任一欄位造成 blocked 或 warning，該 section 自動展開並把問題置頂。**
這是提案 R7 的緩解：progressive disclosure ≠ 刪除。

## 5. URL 與狀態

```text
/projects/:projectId/work?task=:taskId&view=:viewId&filter=...
```

| 情境 | 行為 |
|---|---|
| 開啟 | 加上 `?task=<uuid>`，用 `router.replace`（不堆 history） |
| 關閉 | **只移除 `task` query**，view／filter／scroll 全部保留 |
| reload | 仍開啟同一 Task |
| browser back | 依序：關 Drawer → 還原 view → 才離開 Project |
| 無權查看 | 403 state，**不洩漏標題** |
| 已刪除／不存在 | 404 state，**底層 view 保留** |
| 完整頁面 | `/projects/:id/tasks/:taskId` 保留；Drawer 有「開新分頁」 |
| 行動裝置 | 全螢幕 route overlay，header 固定，sidebar 收成 Details accordion，composer 保持可見 |

## 6. Inline editing

| 規則 | 說明 |
|---|---|
| title、description | **explicit save 或穩定 autosave 擇一，不混用**。建議 explicit save（有 dirty 指示） |
| select 類欄位 | immediate patch |
| 每次帶 `version` | 沿用既有樂觀鎖 |
| conflict（409） | **保留使用者草稿**，提供 reload／compare 兩個動作 |
| field error | 顯示在欄位旁，**不只顯示 toast** |
| composer draft | 以 task id 隔離保存；**mutation 失敗不得清除使用者文字** |

## 7. Tickets

| ID | 工作 | 來源 |
|---|---|---|
| `PX-38` | URL-driven Drawer shell ＋ Drawer primitive（focus trap／restore、aria） | PX-38 ＋ PX-16 殘留 |
| `PX-39` | Main ＋ Sidebar 版面、區塊順序、收合規則 | PX-39 |
| `PX-40` | Inline editing 與 conflict recovery（草稿保留） | PX-40 |
| `PX-41` | 整合 `CV-10`／`CV-11`：conversation-first waiting／resume flow | PX-41 |
| `PX-42` | Run summary ＋ log deep link（log 不混進 conversation） | PX-42 |
| `PX-43` | Artifact／delivery review 面板 | PX-43 |
| `PX-44` | Verification／gate／human actor 呈現（actor ＋ 時間永遠可見） | PX-44 |
| `PX-45` | Dependency／Activity 面板 | PX-45 |
| `PX-46` | 行動版全螢幕 detail | PX-46 |
| `PX-62` | **Related knowledge 區塊**（整合 `KN-11`） | 新增 |

## 8. 出口條件

| ☐ | 條件 | 怎麼證明 |
|---|---|---|
| ☐ | reload 回到同一 Task | E2E |
| ☐ | 關閉 Drawer 不丟失 view、filter、scroll | E2E-J10 |
| ☐ | Waiting flow 不必打開 Terminal 或 raw log | E2E-J1 |
| ☐ | Agent 的多輪問答、訊息狀態與 open questions 在同一 Drawer 可見 | E2E-J1 |
| ☐ | human approval 永遠顯示 human actor 與時間 | 元件測試 ＋ 視覺檢查 |
| ☐ | 403 不洩漏標題、404 保留底層 view | 兩個測試 |
| ☐ | conflict 保留草稿 | 元件測試：409 後輸入框內容不變 |
| ☐ | 造成 blocked／warning 的執行設定自動展開並置頂 | 元件測試，四種情境 |
| ☐ | raw log 不出現在 conversation 串 | 元件測試 |
| ☐ | 打開已快取 Drawer < 150ms 感知回應 | 效能量測 |
| ☐ | focus trap／restore、aria label、狀態播報 | a11y 測試 |
