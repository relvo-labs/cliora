# 03 — P0-W3 Daemon、tmux 與 PTY

## 目標

Go daemon 只能透過 typed runtime operation 操作由 internal UUID 命名的 tmux session，並把 attach PTY 的 raw bytes 安全地接到 relay。

## P0-06：tmux typed client

在 `daemon/internal/tmux` 建立介面：

```go
type Client interface {
    Start(ctx context.Context, spec StartSpec) error
    Exists(ctx context.Context, sessionID uuid.UUID) (bool, error)
    Capture(ctx context.Context, sessionID uuid.UUID, maxBytes int) (Snapshot, error)
    Attach(ctx context.Context, sessionID uuid.UUID, size Size) (PTYProcess, error)
    Stop(ctx context.Context, sessionID uuid.UUID) error
}
```

實作規則：

- tmux name 僅由 `cliora-` + lowercase canonical UUID 推導，禁止傳入顯示名稱。
- 所有 `exec.CommandContext` 使用分離 argv；禁止 `sh -c`、shell string 與 user-supplied executable。
- `StartSpec` 只接受 internal session UUID、allowlisted runtime ID、已由 test config 對應的 workspace ID、rows/columns。
- P0 workspace 是由 daemon 啟動參數固定的 temporary fixture directory；request 不能指定 path。
- 每個測試使用獨立 tmux socket/name prefix，避免碰到開發者既有 sessions。
- tmux stderr 只映射成 safe typed error；原文限 debug test capture，不傳給 renderer。

unit/integration 覆蓋 valid start、duplicate、invalid UUID/size/runtime、tmux missing、start timeout、stop idempotency 與 cleanup。

## P0-07：PTY attach 與 session manager

在 `daemon/internal/session` 建立 single-owner state：`starting → running → stopping → exited|failed`。在 `daemon/internal/terminal` 封裝 PTY：

- attach 成功後才發布 running/attached；半途失敗關閉 fd/process/context。
- PTY read 使用固定 32 KiB buffer，copy 後才交給 queue，禁止持有會被下一次 read 覆寫的 slice。
- input 原 bytes 寫入 PTY；不得特判 Enter、Ctrl+C、Ctrl+D、Tab 或 escape keys。
- resize 使用 platform PTY API，驗 rows/columns boundary；合併連續 resize 但最後值必須送達。
- context cancel → 關閉 PTY → 等 reader/writer → 等 attach child；不得 kill tmux session，除非收到明確 `session.stop`。
- `session.stop` 先停止 tmux，等待最多 5 秒，必要時回 safe failure；清掉 registry 但保存 exit event 到連線生命週期結束。

每個 session manager method 都必須可在 race detector 下並行呼叫；close/cancel/stop 重複執行不得 panic 或 deadlock。

## P0-08：outbound connection 與 dispatcher

P0 daemon 以 development-only shared credential 建立 outbound WS；credential 來自環境/受限 config，不能出現在 query string 或 log。此 auth 僅證明 boundary 位置，不作為 P1 正式方案。

- 一個 goroutine 擁有 socket read，一個擁有 socket write；其他 producer 只能送 bounded channel。
- dispatcher 先驗 protocol，再依 message type 呼叫 typed manager；unknown/invalid 不觸發 process。
- correlation 以 request ID 回應；重複 `session.start` 對同 session ID 回 conflict，不能再開 process。
- heartbeat 每 10 秒送 dev node ID、daemon version 與 active fake session count；不送 path、argv 或 terminal data。
- reconnect 採 1s、2s、5s、10s、30s 上限並含 jitter；關閉時可立即取消 timer。

## 自動驗收案例

| Case | 操作 | 必要結果 |
|---|---|---|
| echo/raw | 送 ASCII、UTF-8、escape bytes | byte-preserving output |
| signals | Ctrl+C、Ctrl+D | Fake CLI 相符 signal/exit 行為 |
| ANSI | 執行 `:ansi` | escape sequence 原樣存在 |
| resize | 40×140 → 24×80 | PTY 與 Fake CLI 都觀察到最後尺寸 |
| disconnect | 關閉 relay transport | attach process 清理、tmux/Fake CLI 繼續 |
| stop | 送 `session.stop` | tmux 消失、單一 exit event、無殘留 process |
| race | 重複 attach/stop/cancel | `go test -race ./...` 通過 |
| injection | payload 加 command/argv/path | schema/dispatcher 拒絕，無 child process |

測試 teardown 只能刪除測試自身 UUID/tmux socket，不得執行廣泛 `tmux kill-server`。
