# 03 — P2-W3：Protocol v1.2 與 Terminal Relay

對應 `research/01/03-phase-2-session-terminal.md` §P2-W3。涵蓋 ticket **P2-03**（protocol v1.2 凍結）、**P2-09**（browser terminal WS relay）。需求：FR-TERM-001..006、FR-CONN-001/004/005/006、FR-SESSION-006/007、SEC-003/005、PRD §9.5/9.6、§10.6。相關技能：`terminal-websocket-protocol`。

## P2-03：Protocol v1.2 凍結（契約先行）

**現況**：`contracts/v1/schemas/control-envelope.schema.json` 的 `type` enum 已含 `session.start/started/attach/attached/stop/stopped`、`terminal.resize/gap/exited` 等，但**多數尚無專屬 payload schema**（fall through 到 generic `payload:{type:object}`）；envelope（version=1、ULID request_id、uuid node_id、UTC-`Z` timestamp、`additionalProperties:false`、error enum）與 binary frame（18-byte header：version、kind 1=input/2=output、16-byte session UUID、payload）已由 P0/P1 凍結。三語言 consumer 由 `contracts/v1/fixtures/manifest.json` 驅動（`accept/reject/code` 為 source of truth），Python 走 JSON-Schema、Go/TS 為手寫 validator，必須同步。

**新增/補齊 payload schema 與 fixtures**（版本仍為 `1`，CHANGELOG minor bump 1.2.0）：

- `session.start` / `session.started` / `session.start_failed`：start payload = `{session_id(uuid), runtime(enum claude|codex), workspace(string ≤4096), rows(2..300), columns(2..500)}`；started = `{session_id, pid(int|null), runtime, workspace}`；start_failed = `{session_id, error{code,message}}`。**payload 不得含 `command`/argv/env**（新增 invalid fixture：start 帶 `command` → reject，比照既有 `forbidden-command.json`）。
- `session.stop` / `session.stopped`：`{session_id}` → `{session_id, exit_code(int|null), forced(bool)}`。
- `session.list` / `session.list_result`：`{}` → `{sessions:[{session_id,runtime,workspace,status,rows,columns,started_at}]}`（供 restart reconcile）。
- `session.recover` / `session.status_changed`：recover=`{session_id}`；status_changed（daemon→Central 事件）=`{session_id, status(enum), exit_code?, reason?}`。
- `terminal.attach` / `terminal.attached` / `terminal.detach`：attach=`{session_id, rows, columns}`；attached=`{session_id, snapshot_bytes(int), truncated(bool), continuity:"snapshot"}`；detach=`{session_id}`。
- `terminal.gap` / `terminal.exited` / `terminal.error`：gap=`{session_id, reason(enum: reattach_boundary|overflow)}`；exited=`{session_id, code(int|null)}`；error=`{session_id, code, message}`。
- writer 控制：`terminal.control_acquire` / `terminal.control_release`（見 `04-single-writer-viewers.md`）=`{session_id}`（+ 接管者標識由 server 端補）。

**新增 error codes**（加入 envelope error enum、Python schema、Go `stable()` allowlist、TS decoder，並各補 invalid fixture）：`SESSION_INVALID_STATE`、`SESSION_LIMIT_REACHED`、`WORKSPACE_OUTSIDE_ALLOWED_ROOT`、`WORKSPACE_NOT_FOUND`、`WORKSPACE_PERMISSION_DENIED`（launch-time 驗證用；檔案層 `FILE_*` 留 P3）。既有 `SESSION_*`、`RUNTIME_*`、`TERMINAL_ALREADY_CONTROLLED`、`INVALID_TERMINAL_SIZE`、`REQUEST_TIMEOUT`、`QUEUE_OVERFLOW`、`FRAME_TOO_LARGE`、`NODE_OFFLINE/DISABLED` 沿用。

驗收：Python/Go/TS 對 v1.2 `manifest.json` 一致 accept/reject；forbidden 欄位（start 帶 command）、naive-time、bad enum、out-of-range rows/columns、unknown type/field 全被安全拒絕；binary frame round-trip（input/output kind、session UUID）不變。**契約 PR 先於任何 consumer 合併。**

## P2-09：Browser Terminal WS Relay

新增 `app/api/ws/terminal.py`，端點 `WS /ws/sessions/{session_id}/terminal`（PRD §11.7）。沿用 P0 的 `app/relay/queue.py`（`BrowserChannel` byte-aware bounded queue）與 P0 relay 修正（daemon→browser control frame 經 per-session channel、單一 writer 依序 drain、overflow 送 `terminal.gap` + close 1013）；把 P0 dev relay 的單租戶 plumbing 升級為 **session-scoped、認證** 版本。

**Handshake（SEC-003/005、FR-SESSION-007）**：連線時消費 P2-06 簽發、綁 `(user_id, session_id)` 的 single-use ws-ticket（`WsTicketService.consume`，monotonic TTL 60s）；再驗 session 存在、node online、user 具 `session.view`（唯讀 attach）。失敗 handshake 拒絕並 close，不接受 query string 長效 token。

**Relay 行為**：

- browser→Central control text frame（`terminal.attach`/`resize`/`detach`/writer acquire/release）在 boundary 驗權後轉 daemon；browser→Central 的**輸入 binary frame 僅 writer 可送**（viewer 偽造 input 由 server 丟棄，見 `04`）。
- daemon→browser：`terminal.attached`（snapshot metadata）→ snapshot binary → live output binary，皆經 per-session `BrowserChannel` byte計帳依序送出；control（gap/exited/error/status）與 output 有序不交錯。
- resize：browser fit 後送 `terminal.resize`，Central 轉 daemon 調 PTY size（FR-TERM-003）。
- heartbeat/keepalive：連線層心跳，偵測 half-open；斷線時取消該連線的 read task、release 其在 session 的訂閱與 writer 標記，`BrowserChannel` 已計帳 bytes 歸零。

**Bounds 與 backpressure**（FR-CONN-005、沿用 P0 `plan/01/05` 矩陣）：control queue 獨立且小（64 frames）；terminal queue bytes+frames 雙上限；overflow 不阻塞上游（daemon PTY reader），該 consumer 進入 gap/close 流程；一個 slow consumer 不持全域 lock、不阻塞他人；close 與 enqueue race 不 panic。metrics（label 不含 user input 或高 cardinality request ID）：`terminal_queue_bytes`、`terminal_queue_frames`、`terminal_queue_overflow_total`、`terminal_gap_total`、`terminal_reconnect_total`、`terminal_snapshot_bytes`、`active_terminal_connections`。

**Timeout/cleanup**：control 對 daemon 的請求走 `registry.request()` 帶 timeout，逾時 `REQUEST_TIMEOUT` 並清 correlation；handler 退出時保證 read task、queue、subscription、writer 標記全部釋放（pytest 無 pending task/leak）。

驗收（`backend/tests`，沿用 `test_relay.py`/`test_queue.py`/`test_correlation.py` 的 `FakeWebSocket` 與 byte-accounting；DB-backed handshake 測試沿用 `tests/db/test_node_ws.py` 模式）：
- malformed frame、forged/未授權 session_id、過期/重用 ws-ticket → handshake 或 frame 安全拒絕。
- output burst（Fake CLI 16 MiB）RSS/queue 有界、CLI/tmux 存活；slow browser 只該連線 gap/close 且 bytes 歸零；daemon queue full 時 attach stream cancel、tmux/CLI 存活可再 attach。
- rapid reconnect ×20 無重複訂閱、無 goroutine/task/timer leak；reattach snapshot 截斷 `truncated=true` + `terminal.gap`。
- unauthorized attach、viewer 偽造 input frame（交由 P2-10 斷言）被拒；斷線清理無 leak。
- **DB/log 不含 Fake CLI 輸入輸出內容**（掃描證明）。
