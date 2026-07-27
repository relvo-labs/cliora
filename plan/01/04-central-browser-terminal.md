# 04 — P0-W4 Central relay 與 Browser xterm

## P0-09：最小 Central gateway

FastAPI 只實作 P0 所需 endpoint：

```text
GET /healthz
GET /readyz
WS  /ws/p0/daemon
WS  /ws/p0/sessions/{session_id}/terminal
```

`/ws/p0/*` 必須由 development flag 才能啟用，production config 啟動時應 fail closed。daemon gateway 驗固定 dev node identity；browser gateway 使用固定 dev user identity。兩者不得被誤當 P1 auth 實作。

記憶體 registry 分別擁有 node connection、session metadata、browser subscriptions 與 request correlations：

- registry mutation 透過單一 service/lock 邊界，不能讓 WS handler 任意改共享 dict。
- 同一 dev node 新連線採明確 replace-old policy，先關舊連線並清其 pending requests。
- request timeout 預設 10 秒、start 30 秒；timeout/cancel/late response 都刪 correlation。
- daemon disconnect 將 browser 狀態改為 disconnected，但不把 tmux session 宣告 exited。
- log 只含 request/node/session ID、message type、duration、byte count、queue depth；不含 frame payload。

## P0-10：terminal relay

browser WS 建立後：

1. 驗 session UUID 與 dev identity。
2. 接受第一個 `session.attach` control message；未 attach 前拒絕 binary input。
3. 向 daemon correlation request attach；收到 snapshot metadata 後回 `session.attached`。
4. binary input 加 daemon header，binary output移除 header後送 browser。
5. resize 保持 control frame並驗尺寸。
6. 任一 side 關閉都 cancel 本 connection tasks；browser 關閉不送 session.stop。

P0 只有一個 browser writer；第二個連線回 `TERMINAL_ALREADY_CONTROLLED`。viewer/takeover 是 P2，不在這裡做半套。writer disconnect 後立即釋放 P0 lease；P2 再實作 30 秒 grace policy。

每個 browser 使用 control queue 與 terminal byte queue；terminal queue 符合 2 MiB/256 frames 雙上限。overflow 時先嘗試送 `terminal.gap` control，然後 close 1013；不得丟 control frame或拖慢其他 client。

## P0-11：xterm composable

新增 `frontend/src/composables/useTerminalSession.ts`，它是以下資源的唯一 owner：

- `Terminal`、Fit/Search/WebLinks addons。
- WebSocket 與 `open/message/error/close` listeners。
- `ResizeObserver`、resize debounce、reconnect/manual retry timers。
- terminal `onData`、`onBinary`、status subscriptions。

介面至少提供 `mount(element)`、`connect(sessionId)`、`retry()`、`disconnect()`、`dispose()`，以及 readonly `status`、`gap`、`exit`、`lastError`。`dispose()` 必須 idempotent，取消 timer、observer、socket、listeners、addons 與 Terminal。

xterm 設定：`convertEol: false`、`scrollback: 10000`、13px JetBrains Mono fallback、暗色 theme。`onData`/`onBinary` 轉成原 bytes 送 WS，禁止自訂 Enter/Ctrl+C 邏輯。ResizeObserver 經 100ms trailing debounce，只有 rows/columns 改變才送，首次 attach 使用 fit 後尺寸。

頁面 `frontend/src/views/TerminalPocView.vue` 提供：session ID、狀態文字/icon、retry、stop（只供 PoC）、terminal mount point。Connected/Reconnecting/Disconnected/Exited/Gap 必須有文字，不只靠顏色；error message 不展示 raw server/daemon detail。

## Frontend 測試

- unit：mock Terminal、addons、WebSocket、ResizeObserver 與 fake timers，逐項證明 single initialization/disposal。
- component：狀態、retry、focus restore、keyboard reachable、gap/exited 不盲目 reconnect。
- browser：ANSI、Unicode、Ctrl+C、方向鍵 bytes、resize、scrollback、refresh、route leave/re-enter。
- leak gate：同頁 mount/unmount 20 次後 active socket/listener/observer/timer 回到 baseline，console 無 error。

## 驗收

完整輸入到 Fake CLI 回顯的額外 relay latency 在本機測試記錄 p50/p95（P0 不設定 production SLO）；所有 WS handler 正常與異常離開後 task count 回 baseline，`pytest` 不出現 pending task warning。
