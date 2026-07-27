# 05 — P2-W5：Frontend Session Flow

對應 `research/01/03-phase-2-session-terminal.md` §P2-W5。涵蓋 ticket **P2-11**（Sessions list + New Session dialog）、**P2-12**（Session Workspace route 與 header）。需求：FR-SESSION-001/003/004/005/006、FR-RUNTIME-002、FR-WORKSPACE-003、PRD §10.5/10.6、style.md §12/§15/§17。相關技能：`vue-naive-ui-workflow`、`frontend-design`、`ux-polish-reviewer`。

## 現況（P2 起點）

- 尚無 Session 相關 view/store：`frontend/src/views` 只有 Login/Nodes/NodeDetail/Enrollment 與 dev 用 `TerminalPocView`（`/poc/terminal`，`import.meta.env.DEV` 後）。三欄 Session Workspace **不存在**，P2 需新建。
- 可沿用：`api/client.ts`（class-based，`request<T>`、401→refresh、`ApiError{code,message,status,requestId}`、`wsTicket(resource)`）、`stores/*.ts`（option store，呼叫 `api()`）、`composables/useAsyncResource.ts`（`idle/loading/success/empty/forbidden/error` + view 端 derive `stale/offline/partial`）、`components/common/AsyncState.vue`（9 狀態、`role=status`）、`StatusBadge.vue`（已含 terminal 狀態 connected/reconnecting/gap/exited 與 node 狀態）、`components/layout/AppLayout.vue`（header+sidebar+`<slot/>`）、`theme/tokens.css`（`--terminal-*` 深色 token）、router lazy load、`stores/auth.ts` 的 `hasPermission(action)`。
- DTO 手寫鏡像 backend（`api/dto.ts`，含 `NodeWorkspaceRoot`），需與 P2-06 的 session DTO lockstep；RBAC action 常數加入 session/terminal action key。

## P2-11：Sessions List 與 New Session Dialog

**Store/API**：新增 `stores/sessions.ts`（`list`、`current`、`create/terminate/fetch` actions 呼叫 `api()`）；`api/client.ts` 加 `listSessions`、`getSession`、`createSession`、`terminateSession`、`attachSession`（回 ws-ticket）方法與對應 `dto.ts` 型別（status enum、時間 RFC 3339、與 backend 對齊）。

**SessionsView**（FR-SESSION-003、PRD §11.6）：欄位 Session 名稱、Node、Runtime、Workspace、建立者、狀態（`StatusBadge`，**不只用顏色**）、開始時間、最後活動；node/status filter、分頁；RBAC 差異（Viewer 無建立/終止）。狀態集齊備：`idle/loading/success/empty/stale/offline/forbidden/partial/error`（以 `useAsyncResource` + view derive）；空清單引導建立 session；錯誤 + retry。

**NewSessionDialog**（FR-SESSION-001、PRD §10.5）：欄位 Node、Runtime、Workspace、Session 名稱、Terminal Size（rows/columns，預設值）。**相依選項**：先選 Online node → 載入該 node 的 runtimes 與 enabled workspace roots；runtime 只列可用（missing/disabled 標示不可選）；workspace 從 root 起可選其下合法目錄（P2 先支援選 root 或手動輸入 root 下路徑，完整目錄瀏覽於 P3）。**前置阻擋（提交前 + server 端雙重）**：offline/disabled node、missing/disabled runtime、非 allowed root 路徑在提交前禁用啟動並提示原因，server 端仍會再驗（不信任前端）。提交後顯示 `validation → starting → (success | timeout | conflict | daemon-failure)` 並提供 retry guidance；`SESSION_LIMIT_REACHED`、`REQUEST_TIMEOUT`、`NODE_OFFLINE` 有具體訊息。**不提供任意啟動參數/環境變數欄位**（FR-SESSION-001 第一階段）。

驗收（unit + E2E）：相依選項載入與連鎖清空；offline node 無法提交；三角色能力差異；starting/timeout/conflict/daemon-failure 呈現與 retry；鍵盤可操作、focus 管理、danger/primary 按鈕語意（style.md §15）。

## P2-12：Session Workspace Route 與 Header

**路由**：新增 `views/SessionWorkspaceView.vue`（`/sessions/:id`），於 `AppLayout` main slot 內自建三欄布局（tech §16.1、style.md §12）：

```text
Session Header（名稱/Node/Runtime/Workspace/狀態/Reconnect/Terminate）
┌ Sessions ┬──────── Terminal（xterm，最大比例）────────┬ Workspace ┐
│ 列表/切換 │                                            │ P3 佔位   │
└──────────┴────────────────────────────────────────────┴───────────┘
Status Bar
```

- **布局行為**（tech §16.1、style.md §18「Terminal 就是工作區、不包 Card」）：左右面板可拖曳調整、右側 Workspace 面板可收合（P2 先放 P3 佔位/收合狀態）；Terminal 佔最大比例並自動 fit；深色工作區背景（`--terminal-*` token）。
- **Header**（PRD §10.6）：Session 名稱、Node、Runtime、Workspace、狀態（`StatusBadge`）、Reconnect、Terminate。Terminate 為 danger action，需 `ConfirmDialog` 二次確認並保持 focus。
- **狀態可恢復 / 切換**：頁面刷新後重新以 attach ticket 連線（reconnect）；session 切換時保留/正確重建各面板狀態，切走完整 dispose（交由 P2-13 的 composable 落實）。左欄 session 清單支援切換不同 session。
- **不做**：Workspace 面板的 file tree/preview（P3）；此處僅保留面板骨架與 collapse。

驗收（E2E）：從 Sessions list/建立後進入 workspace；header 狀態與 reconnect/terminate 正確；面板拖曳/收合；刷新後 reattach；session 切換不串流、狀態正確；responsive（≥1440×900 baseline，較窄 viewport 面板可收合、無水平溢位）；WCAG AA（狀態非僅顏色、focus 可見）。
