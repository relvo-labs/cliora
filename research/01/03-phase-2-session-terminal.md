# 03 — Phase 2：Session 與 Terminal

## 階段目標

讓授權使用者從 Web 在合法 Workspace 以 Claude/Codex 建立 session，完整操作原生 CLI，並可在瀏覽器或 Daemon 短暫中斷後安全恢復。

## 工作包

### P2-W1 Session domain 與 API

- 定義 starting/running/waiting/disconnected/stopping/exited/failed 狀態與合法 transition。
- 實作 create/list/detail/attach/terminate/delete metadata；mutation 定義 conflict/idempotency/timeout。
- Central 不接受 command/binary/shell string，只接受 runtime ID、workspace、name、rows/columns。
- session metadata durable；terminal bytes 不入 DB。

驗收：transition、offline node、missing runtime、invalid workspace、duplicate request、rollback 全有 unit test。

### P2-W2 Runtime launcher 與 tmux ownership

- Go runtime adapter 建 allowlisted argv；workspace canonical validation 在 launch 前重做。
- tmux session 名稱由 internal UUID 生成，metadata 能支援 daemon restart 掃描與 reconciliation。
- process/PTY/goroutine/cancellation ownership 清楚；terminate 有 timeout、graceful/force policy。
- 真實 Claude/Codex 僅做 isolated smoke；日常 integration 使用 Fake CLI。

驗收：start/attach/terminate/exit/restart reconciliation 與 invalid path/process failure/race 測試通過。

### P2-W3 Terminal relay

- Browser WS 與 daemon WS 都在 handshake 驗 user/node/session 權限。
- control text frame、terminal binary frame；resize、heartbeat、attach/resume、exit/error 完整。
- queue/frame/scrollback 上限與 backpressure metric；slow client 不拖垮 node 或 Central。
- timeout/cancel/disconnect 清理 correlation、task 與 subscriptions。

驗收：malformed、forged session ID、burst、slow client、disconnect、duplicate/gap、unauthorized attach 通過。

### P2-W4 Single writer / viewers

- 預設一個 writer，其餘 viewer read-only；UI 明示角色，不只用顏色。
- writer disconnect 的保留時間、釋放與 takeover 流程依 Phase 0 決策實作。
- takeover 要 resource RBAC、confirm、通知現任使用者並記 audit。
- viewer 的 input frame 即使偽造也由 server 拒絕。

驗收：concurrent clients、stolen/expired browser token、viewer forged input、takeover race 測試通過。

### P2-W5 Frontend Session flow

- 拆出 Sessions list、New Session dialog、Session Workspace route。
- Node/runtime/workspace 選項彼此依賴；offline/missing runtime/forbidden 在提交前與 server 端都阻擋。
- New Session 顯示 validation、starting、timeout、conflict、daemon failure 與 retry guidance。
- Session header 提供狀態、reconnect、terminate；danger action 需 confirm 並保持 focus。

驗收：Admin/Developer/Viewer 的 create/attach/terminate 能力與錯誤狀態 E2E 正確。

### P2-W6 xterm production integration

- composable 單獨擁有 WS、Terminal、addons、ResizeObserver 與 retry timer。
- raw keyboard bytes、resize debounce、fit、scrollback、search、focus 與 copy 正常。
- refresh/reconnect 顯示 stale/gap；session exit 不盲目重連。
- session 切換不串流、不重複 listener，離頁完整 dispose。

驗收：CLI 原生審批選單、Ctrl+C、Unicode、resize、長輸出、refresh、切 session 與 cleanup E2E 通過。

### P2-W7 Audit 與 observability slice

- session create/attach/takeover/terminate/failure 記 metadata audit，不含 terminal content。
- metrics：running sessions、active terminal connections、bytes、queue size、timeouts、reconnects。
- log 以 request/node/session/user ID correlation，redact argv 中可能的敏感值。

驗收：可從 request ID 追查一次 session 操作；確認 DB/log 不含 Fake CLI 輸入輸出內容。

## 階段出口

- 可從 Web 在指定合法 Workspace 啟動 Claude 或 Codex 並完整互動。
- Browser refresh/短暫斷線不終止 session，能安全 reattach。
- writer/viewer、takeover、terminate、offline 與 gap 行為清楚且已自動測試。
- 端到端額外延遲在代表性環境符合 PRD 小於 200 ms 目標，或已有量測結果與改善門檻。
