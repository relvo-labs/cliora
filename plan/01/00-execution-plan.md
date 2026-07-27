# 00 — P0 執行總控

## 1. 成功定義與非目標

P0 要退休四個最高風險：tmux/PTY 是否保留原生 CLI 語意、三語言是否能共享 wire contract、瀏覽器生命週期是否與 session 分離，以及慢速 consumer 是否能被有界處理。

P0 必須交付：

- deterministic Fake CLI；可測 echo、ANSI、UTF-8、Ctrl+C、resize、burst 與 exit。
- versioned JSON control frame 與 daemon link binary terminal frame。
- 最小 FastAPI relay；只維護記憶體內 connection/session registry。
- Go daemon 以 allowlisted typed operation 啟動並 attach `tmux`。
- Vue/xterm 頁面；直接傳 raw bytes，能顯示連線與 gap 狀態。
- 自動 contract/unit/integration/browser 測試與可重現操作證據。

P0 明確不做 PostgreSQL、Alembic、JWT/RBAC、enrollment、systemd installer、正式 runtime discovery、Claude/Codex live integration、workspace files、audit persistence、production TLS termination。P0 的 dev identity 與固定單一 node/session 只能在明確標示的 development configuration 使用。

## 2. 固定實作基線

| 項目 | P0 決定 |
|---|---|
| Layout | 根目錄 `backend/`、`daemon/`、`contracts/`、`tests/`，保留現有 `frontend/` |
| Runtime | Python 3.12、Go 1.24、Node 22（以版本檔與 CI 固定實際 patch） |
| Package | Python `uv` + `pyproject.toml`/lock、Go modules、frontend npm lockfile；不導入 Turborepo |
| CI | GitHub Actions；PR 跑靜態檢查、unit、contract、build，主分支與 P0 gate 跑 Linux/tmux integration 和 Playwright matrix |
| Central | FastAPI/Uvicorn；P0 registry 僅記憶體內，restart 行為列入 spike |
| Session host | 系統 `tmux`；名稱嚴格為 `cliora-<lowercase UUID>` |
| Fake CLI | Go test binary，daemon 只以 runtime ID `fake` 查 allowlist，不收 command/string argv |
| Browser | Vue 3 + TypeScript + xterm addons；P0 單一路由 `/poc/terminal` |
| Product name | 正式名稱為 `Cliora`；移除 prototype 的 `Cask` 品牌字樣 |
| Time | JSON timestamp 僅接受 RFC 3339 UTC `Z`，內部使用 aware time |
| Terminal storage | 不進 log/DB；重連以 tmux capture-pane 取得有界快照 |

若實際工具最新版與現有 prototype 衝突，先記 ADR 並選一個可重現版本，不以 `latest` 留在可發布 lockfile 中。

## 3. 垂直架構與 ownership

```text
TerminalPocView / useTerminalSession
  └─ browser WebSocket（每條只對應一個 session）
       └─ FastAPI terminal gateway
            └─ bounded browser send queue
            └─ in-memory session/node registry
                 └─ daemon outbound WebSocket（單一 dev node）
                      └─ session Manager（session 唯一 owner）
                           └─ tmux client
                                └─ attach process + PTY
                                     └─ tmux session → Fake CLI
```

資源 owner：Frontend composable 擁有 Terminal/addons/ResizeObserver/socket/timers；Central 每條 WS handler 擁有其 reader/writer tasks 與 queue；Go `Session` 擁有 attach command、PTY、reader/writer goroutine 與 cancellation。owner 關閉時必須能等待所有 child 結束。

## 4. 執行順序與 ticket

| Wave | Ticket | 產出 | 前置 |
|---:|---|---|---|
| 0 | P0-01 | 版本與 package topology ADR | 無 |
| 0 | P0-02 | 三元件 scaffold、統一命令、CI skeleton | P0-01 |
| 0 | P0-03 | deterministic Fake CLI | P0-02 |
| 1 | P0-04 | protocol schema、fixtures、limits ADR | P0-01 |
| 1 | P0-05 | Python/Go/TS codec 與 negative contract tests | P0-04 |
| 2 | P0-06 | tmux typed client 與安全 session naming | P0-03、P0-04 |
| 2 | P0-07 | PTY attach、raw I/O、resize、cleanup | P0-06 |
| 2 | P0-08 | 最小 daemon outbound connection/dispatcher | P0-05、P0-07 |
| 2 | P0-09 | Central daemon gateway、registry、correlation | P0-05 |
| 3 | P0-10 | Browser terminal gateway 與 bounded relay | P0-08、P0-09 |
| 3 | P0-11 | xterm composable、頁面與 cleanup tests | P0-05、P0-10 |
| 3 | P0-12 | semantic tokens、App Shell、terminal states | P0-02 |
| 4 | P0-13 | refresh/reattach 與 bounded scrollback | P0-10、P0-11 |
| 4 | P0-14 | slow consumer、burst、gap policy | P0-10、P0-13 |
| 4 | P0-15 | Central/Daemon restart spikes 與 ADR | P0-13、P0-14 |
| 5 | P0-16 | CI、E2E、race、操作證據與 exit review | 全部 |

關鍵路徑為 `01 → 04 → 05 → 06/09 → 08 → 10 → 11 → 13 → 14 → 16`。Wave 內可並行，但修改 fixture 的 PR 必須先於 consumer 合併。

## 5. 每張 ticket 的完成格式

每張 ticket 至少附：變更檔案、契約/假設、成功與失敗測試、實際執行命令、log/metric 影響、cleanup 證據，以及對應 requirement (`FR-TERM-*`、`FR-CONN-*`、`SEC-002`)。跨語言行為改變時，同一變更必須更新 schema、fixtures 與三個 consumer。

## 6. P0 預設限制（待量測）

| 限制 | 初值 | 滿額行為 |
|---|---:|---|
| JSON control frame | 64 KiB | close 1009 + `FRAME_TOO_LARGE`（若可安全送出） |
| terminal binary payload | 64 KiB | reject；不得部分解析 |
| browser outbound queue | 2 MiB、最多 256 frames | 丟棄該 client queue、送 gap/close，要求 reattach |
| daemon outbound queue | 4 MiB、最多 512 frames | cancel attach stream 並回報 overflow；tmux session 保留 |
| reattach snapshot | 2 MiB UTF-8 bytes 上限 | 截取最新內容並標示 `truncated=true` |
| control request timeout | 10 s | `REQUEST_TIMEOUT`，清除 correlation entry |
| session start timeout | 30 s | cancel start；清理部分資源 |
| P0 concurrent sessions | 1 | `LIMIT_EXCEEDED` |

queue 同時受 byte 與 frame count 限制，先碰到任一即滿；control frame 不與 terminal bytes 共用可被餓死的 queue。
