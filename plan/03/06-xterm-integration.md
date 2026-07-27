# 06 — P2-W6：xterm Production Integration 與 Writer/Viewer UI

對應 `research/01/03-phase-2-session-terminal.md` §P2-W6。涵蓋 ticket **P2-13**（xterm production composable）、**P2-14**（writer/viewer 與 takeover UI）。需求：FR-TERM-001..006、FR-SESSION-006/007、PRD §8.7、style.md §18、tech §16.2/16.3。相關技能：`vue-naive-ui-workflow`、`terminal-websocket-protocol`、`ux-polish-reviewer`。

## 現況（P2 起點）

- P0 已交付 `frontend/src/composables/useTerminalSession.ts`：xterm/WS 生命週期 owner，`terminal/fit/socket/observer` 以 closure 變數持有 + `disposed` guard；`mount(el)` idempotent（`if (terminal) return`）、載入 `@xterm/addon-fit`、`terminal.open`、`ResizeObserver`；`dispose()` idempotent 且完整（clear timers、`observer.disconnect`、`socket.close`、`terminal.dispose`、置 null），並以 `onScopeDispose(dispose)` 註冊。回傳 readonly refs 與 `canRetry`。deps 已裝：`@xterm/xterm@5.5.0`、`addon-fit`、`addon-search`、`addon-web-links`。xterm theme 已硬編對齊 `--terminal-*`。
- **需替換**：P0 composable 以 dev token/subprotocol 連 `/ws/p0/...`；P2 改為以 P2-06 的 attach ws-ticket 連 `/ws/sessions/{id}/terminal`（session-scoped、認證）。
- 已有 leak 測試紀律（20 mount/dispose cycles 無殘留），P2 沿用並擴充。

## P2-13：xterm Production Composable

以 P0 composable 為基礎，productionize 到真實 relay：

- **連線**：`connect(sessionId)` 先向 `api().attachSession(id)` 取 single-use ws-ticket，再連 `/ws/sessions/{id}/terminal`；ticket 不入 URL log。單一 composable 實例只擁有一條 socket、一個 Terminal、addons、一個 `ResizeObserver`、一個 retry timer。
- **輸入**（FR-TERM-002、style.md §18）：`terminal.onData` 直接送**原始 bytes** binary frame，不自行處理 Enter/Ctrl+C/方向鍵/審批選單按鍵；viewer 模式下停用輸入（並由 server 端最終把關，見 P2-10）。
- **輸出/續傳**：收 `terminal.attached{truncated}` → snapshot binary → live binary，依序 `terminal.write`；`terminal.gap` 顯示 gap 標記；截斷提示「已顯示最新片段」。
- **resize**（FR-TERM-003）：`addon-fit` fit + debounce，變更後送 `terminal.resize{rows,columns}`。
- **scrollback/search/copy**（FR-TERM-004、PRD §8.7）：scrollback（沿用 P0 10_000）、`addon-search`、選取複製。
- **連線狀態/重連**（FR-TERM-005/006）：狀態 `connecting/connected/reconnecting/gap/disconnected/exited`（對應 `StatusBadge` terminal 狀態）；WS 中斷自動重連 1/2/5/10/30s bounded backoff（monotonic），每次成功 reset；手動 Retry 取消現有 timer 立即重試；**收到 `terminal.exited` 後進入 `exited` 狀態、不再盲目重連**（沿用 P0 修正）。
- **生命週期**：切換 session 或離開 route 完整 dispose（不串流、不重複 listener、無殘留 socket/observer/timer）；route param 變更時先 dispose 舊、再 mount/connect 新。

驗收（unit：`vi.mock('@xterm/xterm')` 記錄 instance/dispose；`effectScope` 觸發 `onScopeDispose`；20 mount/dispose 無 leak — 沿用 P0 gate。E2E：真實/Fake 後端）：CLI 原生審批選單可操作、Ctrl+C/Ctrl+D/Tab/方向鍵/PageUp-Down、Unicode/中文輸入、resize 生效、長輸出不卡、refresh 後 reattach 顯示 snapshot+gap、切 session 不串流、離頁 cleanup、exited 不重連。

## P2-14：Writer / Viewer 與 Takeover UI

- **角色明示（不只顏色）**（FR-SESSION-007、WCAG 1.4.1）：header/terminal 區清楚標示目前為 Writer 或 Viewer（icon + 文字 + badge）；viewer 模式輸入區停用並說明原因。
- **takeover 流程**：具 `terminal.takeover` 者可「請求控制權」→ `ConfirmDialog` 確認 → 送 `terminal.control_acquire`；現任 writer 收到被接管通知；成功後雙方角色 UI 即時更新。無權者不顯示該操作（UI 隱藏 + server 端 P2-10 授權雙重把關）。
- **writer 保留窗提示**：writer 短暫斷線時顯示「保留控制權（剩餘秒數）」；逾時釋放後顯示「控制權已釋放，可被接管」。
- **danger/confirm**：takeover 與 terminate 需確認並保持 focus（沿用 `ConfirmDialog`）。

驗收（E2E，多 client）：兩瀏覽器連同一 session，先到者 Writer、後到 Viewer 且輸入被禁；Viewer 嘗試輸入無效果（且 server 丟棄）；授權 Viewer 請求接管 → 確認 → 角色互換、現任被通知、UI 更新；無權者無接管入口；writer 斷線保留窗顯示與釋放；角色資訊在移除顏色後仍可理解（WCAG AA）。
