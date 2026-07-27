# 01 — Phase 0：技術基線與高風險 PoC

## 階段目標

用最小垂直切片證明 Browser → Central → Go Daemon → tmux/Fake CLI 的互動、斷線恢復與流量控制可行，並建立後續可持續擴充的 repository、contract 與 CI 基線。

## 工作包

### P0-W1 Repository 與工具鏈基線

- 確認 Node 22、npm lockfile、Python/Go 版本與 package topology。
- 建立 backend/daemon/contracts/tests；將 frontend prototype 保留為視覺參照後逐步拆分。
- 建立最小 lint、typecheck、unit、build pipeline；不因名稱而假設 Turborepo。
- 建立本地 deterministic Fake CLI 與 test config，不依賴真實 Claude/Codex 帳號。

驗收：乾淨 checkout 可依 README 啟動三元件；CI 能建置且測試 Fake CLI。

### P0-W2 Protocol v1 與跨語言 fixtures

- 定義 versioned envelope、message direction、request ID、timestamp、payload 與 safe error。
- 定義 `session.start/attach/stop`、`terminal.input/resize/output`、heartbeat 的最小集合。
- text control 與 binary Terminal frame 分離；定義 max frame/queue、ordering 與 unknown frame。
- 建立 Python/Go/TypeScript encode/decode golden fixtures。

驗收：三語言讀取同一 fixtures；malformed、unknown version/type、oversize frame 都被安全拒絕。

### P0-W3 tmux/PTTY 垂直切片

- Go 以 typed runtime operation 與 allowlisted args 在指定測試目錄啟動 Fake CLI。
- tmux 名稱只由 internal session UUID 推導，不使用 user input。
- 支援 PTY attach、raw bytes、Ctrl+C、UTF-8、ANSI、resize 與 exit code。
- 明確 goroutine/process/cancellation ownership，shutdown 不殘留測試 process。

驗收：Fake CLI echo、ANSI、Ctrl+C 與 resize 自動測試通過；`go test -race ./...` 無 race。

### P0-W4 Browser xterm 垂直切片

- 安裝 xterm、fit/search/web-links addon；使用 typed composable 管理 lifecycle。
- 不轉譯 Enter、Ctrl+C 等輸入，直接傳 raw bytes。
- 顯示 connected/reconnecting/disconnected/exited，保持 keyboard/focus/scrollback。
- dispose Terminal、addon、ResizeObserver、WS subscription。

驗收：瀏覽器能完整操作 Fake CLI；切換/離開頁面後 listener 與 terminal instance 無洩漏。

### P0-W5 斷線、恢復與 backpressure

- 瀏覽器斷線不 kill tmux；重新連線可 attach 並取得 bounded scrollback/resume 資訊。
- 測試 1s→2s→5s→10s→30s bounded reconnect；手動 retry 可中止等待。
- slow client 使用 bounded queue；定義 disconnect/drop/gap signal，不讓 Central 無限增長。
- Central/Daemon restart 各自做一次 recovery spike，記錄限制與選定策略。

驗收：刷新瀏覽器後 Fake CLI 狀態仍在；burst/slow client 測試不超過設定記憶體界線，gap 對使用者可見。

### P0-W6 UI foundation

- 把 style.md primitives 映射成 semantic tokens 與 Naive UI theme overrides。
- 建立 App Shell、status badge、async state、dialog/toast、focus ring 基礎。
- 保留 Quiet Intelligence / Developer Workbench 視覺；移除展示原型中硬編碼 palette 的重複來源。

驗收：token showcase 含 default/hover/focus/disabled/loading/error；不只靠顏色表達狀態。

## 測試清單

- Contract：round trip、malformed、version mismatch、frame limit。
- Daemon：PTY lifecycle、tmux attach、invalid args、timeout、shutdown、race。
- Browser：keyboard、resize、scrollback、refresh、cleanup、console error。
- Integration：disconnect、duplicate/gap、output burst、slow consumer。

## 階段出口

- 核心 Terminal 垂直切片在本機與 CI 穩定通過。
- protocol v1 與 resume/backpressure 決策有 ADR/contract，不再依口頭假設。
- 高風險點若失敗，有可執行替代方案與重新估算；未解決不得進 Phase 2 production 實作。
- 原型拆分策略與產品命名決策已記錄。
