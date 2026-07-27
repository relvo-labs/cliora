# Cliora P0 可實作規劃

本目錄把 `research/01` 的 Phase 0 轉成可直接建立 ticket、撰寫程式與驗收的執行規格。P0 的唯一產品成果，是在本機以 Browser → Central → Go Daemon → tmux → Fake CLI 完成原始 Terminal I/O、resize、重新連線及有界流量控制；不在此階段提前實作 P1 的資料庫、正式登入、enrollment 或真實 Claude/Codex 整合。

## 文件順序

| 文件 | 用途 |
|---|---|
| [00-execution-plan.md](./00-execution-plan.md) | 範圍、架構、依賴順序、交付節奏與共同完成定義 |
| [01-repository-foundation.md](./01-repository-foundation.md) | P0-W1：repository、工具鏈、Fake CLI、開發入口 |
| [02-protocol-v1.md](./02-protocol-v1.md) | P0-W2：控制 envelope、binary frame、fixtures 與錯誤行為 |
| [03-daemon-tmux-pty.md](./03-daemon-tmux-pty.md) | P0-W3：Go daemon、tmux、PTY、process ownership |
| [04-central-browser-terminal.md](./04-central-browser-terminal.md) | P0-W4：最小 Central relay、xterm、lifecycle |
| [05-reconnect-backpressure.md](./05-reconnect-backpressure.md) | P0-W5：重新連線、scrollback、queue 與 restart spike |
| [06-ui-foundation.md](./06-ui-foundation.md) | P0-W6：semantic tokens、App Shell、狀態與 a11y |
| [07-verification-and-exit.md](./07-verification-and-exit.md) | 測試矩陣、操作證據、階段出口與決策紀錄 |

## 使用規則

1. 先完成 `P0-01`～`P0-04`，凍結 wire contract 後再並行 Central、Daemon 與 Browser。
2. 每項 task 都需提交其列出的產物與測試；「可手動展示」不能替代自動測試。
3. 預設值是 PoC 的可測假設，不是永久產品限制；量測後在 ADR 中接受或修訂。
4. 任何新增任意 shell、真實 agent 帳號、資料庫、RBAC、檔案瀏覽或部署功能的需求，都移至後續 phase。

## 完成結果

P0 通過時，一個開發者可依根目錄 README 啟動三個元件，在瀏覽器操作 Fake CLI，看到 ANSI/UTF-8，送出 Ctrl+C 與 resize，刷新頁面後重新 attach；burst 或 slow client 不造成無界記憶體成長，所有 protocol failure 都以穩定錯誤碼安全結束。
